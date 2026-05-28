from modules.system_detection.sd_prompts import (
    DEFAULT_MAX,
    _salutation_rule,
    _address_forms_by_language,
    _personalization_rule,
    _format_related_services,
    _format_context,
    _clip,
)

from core.app_config import Config
cfg = Config()

# ---------------------------------------------------------------------------
# Opener diversification (Sentence-1 openers)
#
# Problem: the LLM defaults to the same polite acknowledgment every turn
# (e.g. "Baik, " in Indonesian). This makes qualification flows feel robotic.
#
# Fix, in three cooperating pieces:
#   1) _OPENER_PALETTE: curated per-language alternatives the LLM can pick from.
#   2) _BANNED_OPENERS_BY_LANG: openers we never want (e.g. "Baik" in id-*).
#   3) _opener_guidance_block: a shared Sentence-1 guideline block that all
#      qualification-flow prompts use. It also bans the last few used openers
#      passed via recent_openers.
#
# A post-process safety net in modules/system_detection/sd_opener_guard.py
# swaps the opener deterministically if the LLM ignores the guidance.
# ---------------------------------------------------------------------------

_DEFAULT_OPENER_LANG = "en"

# DEPRECATED 2026-05-13 (Task 15): opener palette migrated to centralized i18n loader.
# See `modules/i18n/strings/{lang}.yaml::opener.palette` entries.
# Kept as runtime fallback during Phase 0. Task 19 deletes.
_OPENER_PALETTE: dict[str, list[str]] = {
    "id": [
        "Oke", "Siap", "Paham", "Mengerti", "Noted", "Tentu", "Catat",
        "Nah", "Lalu", "Selanjutnya", "Kalau begitu", "Menarik", "Hmm",
    ],
    "en": [
        "Got it", "Understood", "Noted", "Makes sense", "Sure", "Alright",
        "Right", "Next", "So then", "Following that", "Hmm", "Interesting",
    ],
    "ms": [
        "Baiklah", "Faham", "Noted", "Oke", "Siap",
        "Seterusnya", "Kemudian", "Kalau begitu", "Menarik", "Hmm",
    ],
    "fr": [
        "D'accord", "Compris", "Bien noté", "Parfait", "Très bien", "Entendu",
        "Alors", "Ensuite", "Maintenant", "Donc", "Intéressant", "Hmm",
    ],
    "de": [
        "Verstanden", "Klar", "In Ordnung", "Alles klar", "Gut",
        "Dann", "Jetzt", "Also", "Übrigens", "Interessant", "Hmm",
    ],
    "th": [
        "เข้าใจแล้ว", "รับทราบ", "ตกลง", "โอเค",
        "ต่อไป", "แล้ว", "น่าสนใจ", "อืม",
    ],
    "ru": [
        "Понятно", "Хорошо", "Ясно", "Отлично", "Принято",
        "Итак", "Теперь", "Дальше", "Интересно", "Хм",
    ],
    "zh": [
        "好的", "明白了", "知道了", "了解", "收到",
        "接下来", "那么", "另外", "有意思", "嗯",
    ],
    "it": [
        "Capito", "Va bene", "D'accordo", "Perfetto", "Certo", "Bene",
        "Allora", "Ora", "Quindi", "Interessante", "Hmm",
    ],
    "ja": [
        "了解しました", "承知しました", "なるほど", "かしこまりました",
        "では", "さて", "次に", "ところで", "興味深いですね",
    ],
}

# DEPRECATED 2026-05-13 (Task 15): banned openers migrated to centralized i18n loader.
# See `modules/i18n/strings/id.yaml::opener.banned_forms`.
# Kept as runtime fallback during Phase 0. Task 19 deletes.
_BANNED_OPENERS_BY_LANG: dict[str, tuple[str, ...]] = {
    "id": ("baik", "baiklah"),
}


def _opener_guidance_block(
    *,
    language_code: str | None,
    language_name: str,
    recent_openers: list[str] | None = None,
) -> str:
    """Return the Sentence-1 opener guideline block to inject into a prompt.

    Includes:
    - A curated palette in the target language for the LLM to choose from.
    - Permission (~40%) to skip the opener entirely and go straight to substance.
    - An explicit ban on language-specific bad openers (e.g. "Baik" in id-*).
    - A dynamic ban of the last few openers the assistant used this session.
    """
    lc = (language_code or "").strip().lower()

    # Task 15 (2026-05-13): primary path — i18n loader; legacy palette as defensive fallback.
    palette: list[str] | None = None
    try:
        from modules.i18n import _get_registry as _i18n_get_registry
        _reg = _i18n_get_registry()
        # Try exact 2-char code first, then walk legacy prefix-match for compat
        for try_code in (lc[:2], lc):
            entry = _reg.entries.get(("opener.palette", try_code))
            if entry is not None and isinstance(entry.text, list) and entry.text:
                palette = entry.text
                break
    except Exception:
        palette = None

    if palette is None:
        # Legacy fallback (DEPRECATED — Task 19 deletes)
        for prefix, pal in _OPENER_PALETTE.items():
            if lc.startswith(prefix):
                palette = pal
                break
        if palette is None:
            palette = _OPENER_PALETTE[_DEFAULT_OPENER_LANG]

    palette_str = ", ".join(f'"{o}"' for o in palette)

    # Task 15: banned-forms via i18n loader; legacy fallback
    banned_words: tuple[str, ...] = ()
    try:
        from modules.i18n import _get_registry as _i18n_get_registry
        _reg = _i18n_get_registry()
        for try_code in (lc[:2], lc):
            entry = _reg.entries.get(("opener.banned_forms", try_code))
            if entry is not None and isinstance(entry.text, list) and entry.text:
                banned_words = tuple(entry.text)
                break
    except Exception:
        banned_words = ()

    if not banned_words:
        # Legacy fallback (DEPRECATED — Task 19 deletes)
        for prefix, words in _BANNED_OPENERS_BY_LANG.items():
            if lc.startswith(prefix):
                banned_words = words
                break

    banned_line = ""
    if banned_words:
        banned_quoted = ", ".join(f'"{w.capitalize()}"' for w in banned_words)
        banned_line = f"  - NEVER start with: {banned_quoted}.\n"

    recent = [o for o in (recent_openers or []) if o]
    recent_line = ""
    if recent:
        recent_quoted = ", ".join(f'"{o}"' for o in recent[-3:])
        recent_line = (
            f"  - FORBIDDEN this turn (used in recent turns): {recent_quoted}. "
            f"Pick a DIFFERENT opener, or skip entirely.\n"
        )

    return (
        f"- Sentence 1 opener (≤8 words, no question mark, {language_name} only):\n"
        f"  - CHOOSE ONE from this palette: {palette_str}.\n"
        f"  - OR skip the opener and go straight to the substance (~40% of turns should have NO opener).\n"
        f"  - Do NOT echo, restate, or paraphrase the user's answer in Sentence 1.\n"
        f"{banned_line}"
        f"{recent_line}"
    )


def _engagement_nudge_block(*, language_name: str) -> str:
    """Soft in-prompt acknowledgment fired every 2 cumulative invalid answers.
    Inserted into the normal continuation prompt — the qualification flow
    keeps going; we just weave a warm line into one of the sentences so the
    user realizes the assistant noticed.

    Triggered by the `warnings_shown` counter in sd_service.py via the formula
    `(invalid_count - 2 * warnings_shown) >= 2`. At the same threshold, a
    more visible post-process appended warning fires in sd_warning_guard so
    the two layers reinforce each other on the same turn.
    """
    return (
        "- ENGAGEMENT NUDGE (one-time, this turn only): In ONE of the sentences, "
        f"weave in a brief, warm acknowledgment (in {language_name}) that you want to make sure "
        "you understand the user's needs correctly, since the last few answers were short or unclear. "
        "Frame it as YOUR desire to help well — not as a complaint about the user. "
        "Do NOT sound frustrated. Do NOT imply they're wasting time. Do NOT offer to end the conversation "
        "or restart the chat. Then continue with the qualification question as normal.\n"
        "  - Example (Indonesian): \"Untuk memastikan saya bisa membantu dengan tepat, saya ingin memahami kebutuhan Anda lebih jelas.\"\n"
        "  - Example (English): \"Just to make sure I'm helping you the right way, I want to understand your needs a bit more clearly.\"\n"
    )


def _no_echo_and_advance_guidance_block(*, language_name: str) -> str:
    """Reinforced whole-reply rules: no echoing user input, advance the
    conversation like a sales consultant, stay strictly inside the knowledge
    base. Applied across every qualification-flow prompt so the assistant
    stops saying things like "Baik, sistem akan tersedia di Indonesia" when
    the user just typed "Indonesia".
    """
    return (
        "- DO NOT echo, restate, paraphrase, confirm back, or summarize the user's answer in ANY sentence.\n"
        "  Treat the user's answer as received; advance the conversation instead of repeating it.\n"
        "  - BAD: User says \"Indonesia\" → reply starts with \"sistem akan tersedia di Indonesia\" (echo).\n"
        "  - GOOD: User says \"Indonesia\" → reply starts with \"Untuk konfigurasi optimal, ...\" (advances).\n"
        "  - BAD: User says \"Internal aja\" → reply contains \"fokus internal saja\" (echo).\n"
        "  - GOOD: User says \"Internal aja\" → reply continues with insight about channels for employees.\n"
        "- Write as a professional sales consultant who is DEVELOPING the conversation toward qualification:\n"
        "  add brief insight, context, or rationale that makes the next question feel natural and valuable.\n"
        "- KNOWLEDGE-BASE DISCIPLINE (STRICT):\n"
        "  - Use ONLY facts present in the provided Context chunks above. Do NOT invent, assume, or\n"
        "    generalize product names, features, pricing, regions, timelines, certifications, testimonials,\n"
        "    capabilities, or availability claims that are not in Context.\n"
        "  - If the user asks about something the Context does not cover, briefly acknowledge it is not\n"
        "    confirmed yet and move back to the current qualification question — do NOT fabricate.\n"
        f"- Write naturally in {language_name}. Do NOT mix languages. Do NOT mention internal labels.\n"
    )

def render_serviceagent_prompt_01(*,
    language_name: str,
    related_services,
    context,
    question,
    is_first_turn: bool,
    user_nick: str | None = None,
    language_code: str | None = None,
    max_chars: int | None = None,
    chat_history_block: str | None = None,
    chat_summary_block: str | None = None,
    next_q_enabled: bool = False,
    next_q_seed: str | None = None,
    service_validation_enabled: bool = False,
    service_validation_seed: str = "-",
    recent_openers: list[str] | None = None,
    engagement_nudge: bool = False,
) -> str:

    sal = _salutation_rule(language_name, is_first_turn, user_nick, language_code=language_code)
    nick_plain, _addr_formal = _address_forms_by_language(language_code, user_nick)
    pers = _personalization_rule(language_name, language_code, user_nick)

    fixed_head = sal + "\n" + pers + "\n"
    body_wo_ctx = (
        "You are an AI Assistant acting as a professional, persuasive, and trustworthy business consultant providing accurate and up-to-date information about Integrity’s services.\n"
        f"Target language: {language_name}. Answer strictly using the provided context chunks. Be concise (3 sentences), synthesize points, avoid repetition.\n"
        # f"You may use either the plain name (“{nick_plain or ''}”).\n\n"
        f"Relevant services:\n{_format_related_services(related_services)}\n\n"
        "Context:\n"
    )

    q_block = (
        "Next Qualification Question:\n"
        f"{(next_q_seed or '-').strip()}\n"
    )

    opener_block = _opener_guidance_block(
        language_code=language_code,
        language_name=language_name,
        recent_openers=recent_openers,
    )
    no_echo_block = _no_echo_and_advance_guidance_block(language_name=language_name)
    nudge_block = _engagement_nudge_block(language_name=language_name) if engagement_nudge else ""

    tail_after_ctx = (
        f"\n\nUser Question:\n{(question or '').strip()}\n\n"
        f"{q_block}\n"
        "Guidelines:\n"
        "- Summarize only key points relevant to the question using the context above; do not fabricate.\n"
        "- Do NOT output any handoff block on the first turn.\n"
        f"- Answer concisely in {language_name}. Use ≤3 sentences or ≤3 bullet points. Avoid long introductions. If a list is needed, cap at 3 items.\n"
        "- Your reply MUST be EXACTLY 3 sentences in a SINGLE paragraph.\n"
        f"{opener_block}"
        f"{no_echo_block}"
        f"{nudge_block}"
        "- Sentence 1: a brief, natural bridging phrase that moves the conversation forward — as if a consultant heard the answer and is now thinking ahead.\n"
        "- Sentence 2: explain what the selected service key benefits, strictly using the context above.\n"
        "- Sentence 3: ask the Next Qualification Question exactly once, naturally.\n"
        "- Do NOT start a new line or paragraph for the question.\n"
        "- You may rephrase naturally, but keep the intent and requested fields identical.\n"
        "- Do NOT mention internal labels like 'Next Qualification Question' in your final user-visible reply.\n\n"
        "Output Formatting Rules (STRICT):\n"
        "- Output MUST be a SINGLE paragraph.\n"
        "- Do NOT use line breaks or blank lines.\n"
        "- Do NOT separate answer and question into different paragraphs.\n"
        "- Do NOT start a new line or paragraph for the question.\n"
        "- The qualification question MUST be in the same paragraph as the answer.\n"
        "- Use natural sentence flow, separated only by spaces.\n"
    )

    if max_chars is None:
        max_chars = DEFAULT_MAX

    opt_blocks = ""
    if chat_summary_block:
        opt_blocks += "\n\n" + chat_summary_block
    if chat_history_block:
        opt_blocks += "\n\n" + chat_history_block

    fixed_len = len(fixed_head) + len(body_wo_ctx) + len(tail_after_ctx) + len(opt_blocks)
    remain_for_ctx = max(0, max_chars - fixed_len)

    ctx_text = _format_context(context)
    ctx_text = _clip(ctx_text, remain_for_ctx)

    text = fixed_head + body_wo_ctx + ctx_text + tail_after_ctx
    if chat_summary_block:
        text += "\n\n" + chat_summary_block
    if chat_history_block:
        text += "\n\n" + chat_history_block

    return _clip(text, max_chars)

def render_serviceagent_continue_prompt(
    *,
    language_name: str,
    context: str,
    prev_q: str,
    user_answer: str,
    next_q: str,
    is_first_turn: bool,
    user_nick: str | None = None,
    language_code: str | None = None,
    chat_history_block: str | None = None,
    chat_summary_block: str | None = None,
    max_chars: int | None = None,
    recent_openers: list[str] | None = None,
    engagement_nudge: bool = False,
) -> str:
    if max_chars is None:
        max_chars = DEFAULT_MAX

    sal = _salutation_rule(language_name, is_first_turn, user_nick, language_code=language_code)
    nick_plain, _addr_formal = _address_forms_by_language(language_code, user_nick)
    pers = _personalization_rule(language_name, language_code, user_nick)

    fixed_head = sal + "\n" + pers + "\n"

    body_wo_ctx = (
        "You are an AI Assistant acting as a professional, persuasive, and trustworthy business consultant providing accurate and up-to-date information about Integrity’s services.\n"
        f"Target language: {language_name}. Use the context only if it is directly relevant; otherwise keep it natural and concise.\n"
        # f"You may use either the plain name (“{nick_plain or ''}”).\n\n"
        "Context:\n"
    )

    opener_block = _opener_guidance_block(
        language_code=language_code,
        language_name=language_name,
        recent_openers=recent_openers,
    )
    no_echo_block = _no_echo_and_advance_guidance_block(language_name=language_name)
    nudge_block = _engagement_nudge_block(language_name=language_name) if engagement_nudge else ""

    tail_after_ctx = (
        "Previous Qualification Question:\n"
        f"{(prev_q or '').strip()}\n\n"
        "User Answer:\n"
        f"{(user_answer or '').strip()}\n\n"
        "Next Qualification Question:\n"
        f"{(next_q or '').strip()}\n\n"
        "Guidelines:\n"
        f"- Output MUST be EXACTLY 3 sentences in a SINGLE paragraph using target language {language_name}.\n"
        f"{opener_block}"
        f"{no_echo_block}"
        f"{nudge_block}"
        "- The bridging sentence (Sentence 2) MUST NOT contain a question mark.\n"
        "- Sentence 3 MUST ask the Next Qualification Question exactly once, with minimal rewording and identical intent.\n"
        "- Do NOT start a new line or paragraph for the question.\n"
        "- You may rephrase naturally, but keep the intent and requested fields identical.\n"
        "- Do NOT mention internal labels like 'Next Qualification Question' in your final user-visible reply.\n\n"
        f"Output Formatting Rules (STRICT) using target language {language_name}:\n"
        "- Output MUST be a SINGLE paragraph.\n"
        "- Do NOT use line breaks or blank lines.\n"
        "- Do NOT separate answer and question into different paragraphs.\n"
        "- Do NOT start a new line or paragraph for the question.\n"
        "- The qualification question MUST be in the same paragraph as the answer.\n"
        "- Prefer natural conversational phrasing over formal report-style wording, separated only by spaces.\n"
    )

    if max_chars is None:
        max_chars = DEFAULT_MAX

    opt_blocks = ""
    if chat_summary_block:
        opt_blocks += "\n\n" + chat_summary_block
    if chat_history_block:
        opt_blocks += "\n\n" + chat_history_block

    fixed_len = len(fixed_head) + len(body_wo_ctx) + len(tail_after_ctx) + len(opt_blocks)
    remain_for_ctx = max(0, max_chars - fixed_len)

    ctx_text = _format_context(context)
    ctx_text = _clip(ctx_text, remain_for_ctx)

    text = fixed_head + body_wo_ctx + ctx_text + tail_after_ctx
    if chat_summary_block:
        text += "\n\n" + chat_summary_block
    if chat_history_block:
        text += "\n\n" + chat_history_block

    return _clip(text, max_chars)

def _closing_sentences_by_language(language_code: str | None, service_label: str) -> str:
    """Return multilingual closing instruction for the final gate prompt."""
    lc = (language_code or "en").strip().lower()
    if lc.startswith("id"):
        return (
            f"- Tulis kalimat penutup alami dalam Bahasa Indonesia yang: "
            f"(1) merangkum bahwa Anda telah memahami kebutuhan user terkait {service_label}, "
            f"(2) menyampaikan bahwa tim kami akan menghubungi mereka segera, "
            f"(3) menanyakan apakah ada hal lain yang bisa dibantu. "
            f"Jangan gunakan kalimat berbahasa Inggris sama sekali.\n"
        )
    elif lc.startswith("ms"):
        return (
            f"- Tulis ayat penutup semula jadi dalam Bahasa Melayu yang: "
            f"(1) merumuskan bahawa anda faham keperluan pengguna berkaitan {service_label}, "
            f"(2) memaklumkan bahawa pasukan kami akan menghubungi mereka tidak lama lagi, "
            f"(3) bertanya sama ada ada perkara lain yang boleh dibantu.\n"
        )
    elif lc.startswith("th"):
        return (
            f"- เขียนประโยคปิดท้ายตามธรรมชาติเป็นภาษาไทยที่: "
            f"(1) สรุปว่าคุณเข้าใจความต้องการของผู้ใช้เกี่ยวกับ {service_label} "
            f"(2) แจ้งว่าทีมของเราจะติดต่อกลับเร็วๆ นี้ "
            f"(3) ถามว่ามีอะไรอื่นที่ช่วยได้อีกไหม\n"
        )
    elif lc.startswith("fr"):
        return (
            f"- Rédigez une phrase de clôture naturelle en français qui: "
            f"(1) résume que vous avez compris les besoins de l'utilisateur concernant {service_label}, "
            f"(2) informe que notre équipe le contactera prochainement, "
            f"(3) demande s'il y a autre chose que vous pouvez aider.\n"
        )
    elif lc.startswith("ru"):
        return (
            f"- Напишите естественное заключительное предложение на русском языке, которое: "
            f"(1) подводит итог тому, что вы поняли потребности пользователя в {service_label}, "
            f"(2) сообщает, что наша команда свяжется с ними в ближайшее время, "
            f"(3) спрашивает, можете ли вы чем-то ещё помочь.\n"
        )
    elif lc.startswith("zh"):
        return (
            f"- 用中文写一个自然的结束语，其中: "
            f"(1) 总结您已理解用户关于{service_label}的需求, "
            f"(2) 说明我们的团队将很快与他们联系, "
            f"(3) 询问是否还有其他可以帮助的事情.\n"
        )
    elif lc.startswith("de"):
        return (
            f"- Schreiben Sie einen natürlichen Abschlusssatz auf Deutsch, der: "
            f"(1) zusammenfasst, dass Sie die Bedürfnisse des Benutzers bezüglich {service_label} verstanden haben, "
            f"(2) mitteilt, dass unser Team sich in Kürze melden wird, "
            f"(3) fragt, ob noch etwas anderes geholfen werden kann.\n"
        )
    elif lc.startswith("it"):
        return (
            f"- Scrivete una frase conclusiva naturale in italiano che: "
            f"(1) riepiloghi che avete compreso le esigenze dell'utente riguardo a {service_label}, "
            f"(2) comunichi che il nostro team li contatterà a breve, "
            f"(3) chieda se c'è altro con cui si possa aiutare.\n"
        )
    else:  # English default
        return (
            f"- Write a natural closing in English that: "
            f"(1) summarizes that you understood the user's needs regarding {service_label}, "
            f"(2) states our team will get in touch shortly, "
            f"(3) asks if there's anything else you can assist with.\n"
        )

def render_serviceagent_prompt_final(
    *,
    language_name: str,
    service_label: str,
    user_answer: str,
    is_first_turn: bool,
    context: str | None = None,          
    user_nick: str | None = None,
    language_code: str | None = None,
    max_chars: int | None = None,
    chat_history_block: str | None = None,
    chat_summary_block: str | None = None,
) -> str:
    sal = _salutation_rule(language_name, is_first_turn, user_nick, language_code=language_code)
    pers = _personalization_rule(language_name, language_code, user_nick)

    head = sal + "\n" + pers + "\n"
    
    # Inject FAQ context jika ada, fallback ke user_answer
    ctx_section = _format_context(context) if context else _format_context(user_answer)

    closing_instruction = _closing_sentences_by_language(language_code, service_label)

    body = (
        "You are an AI Assistant acting as a professional business consultant for Integrity's services.\n"
        f"Target language: {language_name}. Use the context and the chat summary/history to write a closing.\n\n"
        f"Relevant services:\n{_format_related_services(service_label)}\n\n"
        "Knowledge Base Context:\n"
        f"{ctx_section}\n\n"
        "User Question:\n"
        f"{user_answer}\n\n"
        "Rules (STRICT):\n"
        "- Output MUST be a SINGLE paragraph.\n"
        "- Output MUST be 2-3 sentences.\n"
        "- Provide a short wrap-up and invite the user to schedule a meeting.\n"
        # # ↓ TAMBAH RULE ANTI-HALUSINASI INI
        # "- CRITICAL: Only mention product names, features, or services that are EXPLICITLY stated "
        # "in the Knowledge Base Context above. Do NOT introduce any new product names"
        # "that are not present in the Context. If the user asks about products not in the Context, "
        # "say you will connect them with the team for complete information.\n"
        # f"- Mention: 'Thank you very much for sharing all the details. I am glad I could understand your needs regarding {service_label}. "
        # f"Our team will review your requirements and get in touch with you shortly. Is there anything else I can assist you with in the meantime?"\
        "- CRITICAL: Only mention product names explicitly in Knowledge Base Context. "
        "Do NOT invent new product names. If asked about unknown products, say team will provide info.\n"
        + closing_instruction
    )

    text = head + body
    if chat_summary_block:
        text += "\n\n" + chat_summary_block
    if chat_history_block:
        text += "\n\n" + chat_history_block
    return _clip(text, max_chars or DEFAULT_MAX)

def render_serviceagent_postgate_prompt(
    *,
    language_name: str,
    context: str,
    user_answer: str,
    next_q: str,
    is_first_turn: bool,
    user_nick: str | None = None,
    language_code: str | None = None,
    max_chars: int | None = None,
    chat_history_block: str | None = None,
    chat_summary_block: str | None = None,
    recent_openers: list[str] | None = None,
    engagement_nudge: bool = False,
) -> str:
    """
    Prompt untuk kondisi post-gate (gate sudah ditampilkan sekali).
    Jawab pertanyaan user dalam 2 kalimat, lalu lanjutkan pertanyaan kualifikasi.
    """
    sal = _salutation_rule(language_name, is_first_turn, user_nick, language_code=language_code)
    pers = _personalization_rule(language_name, language_code, user_nick)
    if max_chars is None:
        max_chars = DEFAULT_MAX

    fixed_head = sal + "\n" + pers + "\n"

    body_wo_ctx = (
        "You are an AI Assistant acting as a professional business consultant for Integrity's services.\n"
        f"Target language: {language_name}. Write ENTIRELY in {language_name}. Do NOT switch to English.\n"
        "Context:\n"
    )

    opener_block = _opener_guidance_block(
        language_code=language_code,
        language_name=language_name,
        recent_openers=recent_openers,
    )
    no_echo_block = _no_echo_and_advance_guidance_block(language_name=language_name)
    nudge_block = _engagement_nudge_block(language_name=language_name) if engagement_nudge else ""

    tail = (
        f"\n\nUser Question:\n{(user_answer or '').strip()}\n\n"
        f"Next Qualification Question:\n{(next_q or '').strip()}\n\n"
        "Guidelines:\n"
        f"- Output MUST be EXACTLY 2 sentences in a SINGLE paragraph in {language_name}.\n"
        f"{opener_block}"
        f"{no_echo_block}"
        f"{nudge_block}"
        "- Sentence 1: Answer the user's question briefly and factually using Context above.\n"
        "- Sentence 2: Ask the Next Qualification Question naturally, as if continuing a business conversation.\n"
        "- Do NOT mention that the meeting invitation was already shown.\n"
        "- Do NOT show choices or invite to book a meeting again.\n"
        "- Do NOT mention internal labels.\n"
        "Output Formatting:\n"
        "- SINGLE paragraph, no line breaks, no markdown.\n"
    )

    opt_blocks = ""
    if chat_summary_block:
        opt_blocks += "\n\n" + chat_summary_block
    if chat_history_block:
        opt_blocks += "\n\n" + chat_history_block

    fixed_len = len(fixed_head) + len(body_wo_ctx) + len(tail) + len(opt_blocks)
    remain = max(0, max_chars - fixed_len)
    ctx_text = _clip(_format_context(context), remain)

    text = fixed_head + body_wo_ctx + ctx_text + tail
    if chat_summary_block:
        text += "\n\n" + chat_summary_block
    if chat_history_block:
        text += "\n\n" + chat_history_block
    return _clip(text, max_chars)

def render_serviceagent_final_title_prompt(
    *,
    language_name: str,
    service_label: str,
    description: str,
    max_chars: int | None = None,
) -> str:
    max_chars = max_chars or DEFAULT_MAX
    body = (
        "You are a helpful assistant that writes a short CRM conversation title.\n"
        f"Target language: {language_name}.\n"
        "Rules (STRICT):\n"
        "- Output MUST be exactly ONE sentence.\n"
        "- 10 to 15 words.\n"
        "- No quotes, no bullet points.\n"
        f"- Must reflect the user's needs about: {service_label}.\n\n"
        "Conversation summary:\n"
        f"{description}\n"
    )
    return _clip(body, max_chars)

def render_serviceagent_question_validation_prompt(
    *,
    user_question: str,
    current_question: str | None = None,
    prev_q: str | None = None,
    service_code: str = "",
) -> str:
    cq = (current_question or prev_q or "").strip()
    uq = (user_question or "").strip()

    return f"""
You are a strict classifier for a qualification flow.
Service: {service_code}

CURRENT QUALIFICATION QUESTION:
{cq}

USER MESSAGE:
{uq}

Classify the USER MESSAGE into exactly ONE label:
- answer_only
- question_only
- answer_and_question

Rules:
- Output MUST be exactly one label, lowercase, no punctuation, no extra words.
- If unsure between answer_only vs question_only, prefer question_only.

OUTPUT:
""".strip()

def render_serviceagent_interest_validation_prompt(*, user_question: str, prev_q: str) -> str:
    uq = (user_question or "").strip()
    return f"""
You are a strict classifier.

Return ONLY one of these exact labels:
- valid
- not_interest

valid: user response is relevant / aligned with the qualification question.
not_interest: user response is irrelevant / not answering / off-topic.

Previous question:
{prev_q}

User input:
{uq}
""".strip()

def render_serviceagent_continue_question_prompt(
    *,
    language_name: str,
    context: str,
    prev_q: str,
    user_answer: str,
    is_first_turn: bool,
    user_nick: str | None = None,
    language_code: str | None = None,
    chat_history_block: str | None = None,
    chat_summary_block: str | None = None,
    max_chars: int | None = None,
    recent_openers: list[str] | None = None,
    engagement_nudge: bool = False,
) -> str:
    if max_chars is None:
        max_chars = DEFAULT_MAX

    sal = _salutation_rule(language_name, is_first_turn, user_nick, language_code=language_code)
    nick_plain, _addr_formal = _address_forms_by_language(language_code, user_nick)
    pers = _personalization_rule(language_name, language_code, user_nick)

    fixed_head = sal + "\n" + pers + "\n"

    body_wo_ctx = (
        "You are an AI Assistant acting as a professional, instructional, not persuasive, and trustworthy business consultant "
        "providing accurate and up-to-date information about Integrity’s services.\n"
        f"Target language: {language_name}. Use the context only if it is directly relevant; otherwise keep it natural and concise.\n"
        # f"You may use either the plain name (“{nick_plain or ''}”).\n\n"
        "Context:\n"
    )

    opener_block = _opener_guidance_block(
        language_code=language_code,
        language_name=language_name,
        recent_openers=recent_openers,
    )
    no_echo_block = _no_echo_and_advance_guidance_block(language_name=language_name)
    nudge_block = _engagement_nudge_block(language_name=language_name) if engagement_nudge else ""

    tail_after_ctx = (
        "User Answer:\n"
        f"{(user_answer or '').strip()}\n\n"
        "Active Question:\n"
        f"{(prev_q or '').strip()}\n\n"
        "Guidelines:\n"
        f"- Output MUST be EXACTLY 4 sentences in a SINGLE paragraph using target language {language_name}.\n"
        f"{opener_block}"
        f"{no_echo_block}"
        f"{nudge_block}"
        "- Sentence 1 MUST also clearly state whether the user's answer is valid or not, briefly and politely (no question mark).\n"
        "- Sentence 2 and 3 MUST explain and answer the user answer based only on context.\n"
        "- Sentence 2 and 3 MUST be informative, not persuasive. Do NOT add new product claims.\n"
        "- Sentence 4 MUST ask the SAME qualification question again based on Active Question (rephrase slightly) to confirm.\n"
        "- Output MUST be a SINGLE paragraph. No line breaks.\n"
    )

    # history + summary (kalau kamu pakai)
    hist = (chat_history_block or "").strip()
    summ = (chat_summary_block or "").strip()
    audit = ""
    if hist:
        audit += f"\n\nChat History:\n{hist}"
    if summ:
        audit += f"\n\nChat Summarization:\n{summ}"

    prompt = fixed_head + body_wo_ctx + (context or "").strip() + "\n\n" + tail_after_ctx + audit
    return prompt[:max_chars]

def render_serviceagent_continue_answerquestion_prompt(
    *,
    language_name: str,
    context: str,
    prev_q: str,
    next_q: str,
    user_answer: str,
    is_first_turn: bool,
    user_nick: str | None = None,
    language_code: str | None = None,
    chat_history_block: str | None = None,
    chat_summary_block: str | None = None,
    max_chars: int | None = None,
    recent_openers: list[str] | None = None,
    engagement_nudge: bool = False,
) -> str:
    if max_chars is None:
        max_chars = DEFAULT_MAX

    sal = _salutation_rule(language_name, is_first_turn, user_nick, language_code=language_code)
    nick_plain, _addr_formal = _address_forms_by_language(language_code, user_nick)
    pers = _personalization_rule(language_name, language_code, user_nick)

    fixed_head = sal + "\n" + pers + "\n"

    body_wo_ctx = (
        "You are an AI Assistant acting as a professional, instructional, not persuasive, and trustworthy business consultant "
        "providing accurate and up-to-date information about Integrity’s services.\n"
        f"Target language: {language_name}. Use the context only if it is directly relevant; otherwise keep it natural and concise.\n"
        # f"You may use either the plain name (“{nick_plain or ''}”).\n\n"
        "Context:\n"
    )

    opener_block = _opener_guidance_block(
        language_code=language_code,
        language_name=language_name,
        recent_openers=recent_openers,
    )
    no_echo_block = _no_echo_and_advance_guidance_block(language_name=language_name)
    nudge_block = _engagement_nudge_block(language_name=language_name) if engagement_nudge else ""

    tail_after_ctx = (
        "Previous Qualification Question:\n"
        f"{(prev_q or '').strip()}\n\n"
        "User Answer:\n"
        f"{(user_answer or '').strip()}\n\n"
        "Next Qualification Question:\n"
        f"{(next_q or '').strip()}\n\n"
        "Guidelines:\n"
        f"- Output MUST be EXACTLY 4 sentences in a SINGLE paragraph using target language {language_name}.\n"
        f"{opener_block}"
        f"{no_echo_block}"
        f"{nudge_block}"
        "- Sentence 1 MUST also clearly state whether the user's answer is valid or not, briefly and politely (no question mark).\n"
        "- Sentence 2 and 3 MUST explain and answer the user's clarification based only on context (informative, not persuasive).\n"
        "- Sentence 4 MUST ask the Next Qualification Question exactly once.\n"
        "- Output MUST be a SINGLE paragraph. No line breaks.\n"
    )

    hist = (chat_history_block or "").strip()
    summ = (chat_summary_block or "").strip()
    audit = ""
    if hist:
        audit += f"\n\nChat History:\n{hist}"
    if summ:
        audit += f"\n\nChat Summarization:\n{summ}"

    prompt = fixed_head + body_wo_ctx + (context or "").strip() + "\n\n" + tail_after_ctx + audit
    return prompt[:max_chars]

# render_serviceagent_reset_prompt removed — Crisp handles reset natively.

SERVICE_QUESTIONING = """
You are a Qualification Assistant working inside Integrity's sales assistant.

Goal:
- Collect clear, structured information from the user to qualify a lead for the service:
  "{service_label}" (code: {service_code}).
- Make it easy for the sales team to understand the user's needs and propose the right solution.

Language & Personalisation:
- Answer concisely in {language_name} as a target language.

Context:
- Current qualification step: {qualification_order} of {total_steps}
- Current qualification question:
  "{question_text}"

Conversation history (user and assistant):
{history_block}

Instructions:
1. Focus on the current qualification question above. You may slightly rephrase it, but do NOT change its meaning.
2. Your reply MUST have exactly two parts:
   a) One short, natural bridging sentence that smoothly connects from the previous conversation.
   b) The qualification question, asked in a friendly and clear way on a new line.
3. Be concise, professional, and friendly. Use clear business language.
4. If the user already answered the current question in the conversation history, briefly acknowledge it and ONLY ask for clarification if needed.
5. Do NOT mention step numbers, internal codes, or the word "qualification". Just sound like a helpful consultant.
6. If the user goes off-topic, gently steer the conversation back to the current question.

Output:
- Return ONLY the assistant's reply text that should be shown to the user.
- Do NOT include any JSON, labels, bullet points, or explanations.
""".strip()

def render_qfc_prompt(
    service_code: str,
    service_label: str,
    qualification_order: int,
    total_steps: int,
    question_text: str,
    language_name: str,
    nickname: str,
    history_text: str = "",
    user_answer: str = "",
) -> str:
    """
    QFC = Qualification Flow Controller
    Dipakai ketika flow Service Agent aktif untuk membentuk teks 3 kalimat:
    1) respon terhadap jawaban/pilihan user,
    2) transisi yang smooth,
    3) pertanyaan kualifikasi berikutnya.
    """
    history_block = history_text.strip() or "(No prior messages provided.)"
    last_answer = user_answer.strip() or "(The user’s latest reply is not available; infer from history.)"

    return f"""
You are a Qualification Assistant working inside Integrity's sales assistant.

Goal:
- Collect clear, structured information from the user to qualify a lead for the service:
  "{service_label}" (code: {service_code}).
- Make it easy for the sales team to understand the user's needs and propose the right solution.

Language & Personalisation:
- Answer concisely in {language_name} as a target language.
- You may use the plain name (“{nickname}”) when it feels natural, but not in every sentence.

Context:
- Current qualification step: {qualification_order} of {total_steps}
- Current qualification question (for this step):
  "{question_text}"

Conversation history (user and assistant):
{history_block}

Latest user answer or choice (if any):
{last_answer}

Instructions:
1. Focus on the current qualification question above. You may slightly rephrase it, but do NOT change its meaning.
2. Your reply MUST consist of EXACTLY three sentences in a single paragraph:
   a) Sentence 1: briefly acknowledge or respond to the user's latest answer/choice in a natural way.
   b) Sentence 2: provide a smooth transition that links the previous context to the next question.
   c) Sentence 3: ask the qualification question clearly and directly.
3. Be concise, professional, and friendly. Use clear business language.
4. If the user already answered the current question in the conversation history, sentence 1 should reflect that,
   and sentence 3 should ONLY ask for clarification or confirmation, not repeat everything.
5. Do NOT mention step numbers, internal codes, or the word "qualification". Just sound like a helpful consultant.
6. If the user goes off-topic, gently steer the conversation back to the current question in sentences 2–3.

Output:
- Return ONLY the three-sentence reply text that should be shown to the user.
- No bullet points, no markdown, no JSON, no meta-commentary.
""".strip()

CLARIFY_ANSWER_PROMPT = """
You are a service qualification assistant.

Given:
- service: {service_code}
- question: {question_text}
- user_answer: {user_answer}
- valid_choices: {choices}

Task:
1. Decide if the user's answer clearly maps to one of the valid_choices.
2. If yes, return JSON: {{ "status": "mapped", "choice_value": "..." }}
3. If unclear, return JSON: {{ "status": "clarify", "clarify_text": "..." }}
"""

SA_SUMMARY_PROMPT = """
You are a careful summarizer for a multilingual service-qualification flow
inside Integrity's sales assistant.

Goal:
- Turn all question–answer (Q/A) pairs from the qualification flow into a concise
  internal summary that sales or meeting arrangers can quickly understand.
- Highlight what the user needs, in the context of the specific service.

Language:
- Write the entire summary STRICTLY in {language_name}.
- Do NOT switch languages. Do NOT use English unless {language_name} is English.

Instructions:
1. Read carefully all Q/A pairs.
2. Produce a short, factual qualification summary that captures:
   - Which service the user is interested in (implicitly from context),
   - The user's main needs or objectives,
   - Any mentioned scope (roles, geography, volume),
   - Important constraints (timeline, budget, compliance, etc.) if present,
   - Any open questions, assumptions, or next-step notes useful for sales.
3. Target maximum length: around {max_chars} characters. Write in 1–3 short paragraphs or up to 10 bullet points. Avoid hallucinations.
4. The summary is for internal use only (not shown to the user).

Inputs:
- service_code: {service_code}
- qa_pairs: all Q/A pairs in plain text

=== FULL QA LOG ===
{qa_pairs}
=== END QA LOG ===

Now write the summary:
""".strip()


SUMMARY_PROMPT = """
You are a consultant preparing a short qualification summary.

Given all Q&A for service {service_code}:

{qa_pairs}

Write:
1. A 1-sentence title (10–15 words).
2. A short paragraph summary for internal use (max 120 words).
Return JSON:
{{ "summary_title": "...", "summary_description": "..." }}
"""
