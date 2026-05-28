from langchain_core.prompts import PromptTemplate, ChatPromptTemplate
from typing import Any, Sequence
from core.app_config import Config
cfg = Config()

DEFAULT_MAX = getattr(cfg, "PROMPT_MAX_CHARS", 6000)

# ====== Schema untuk structured output LLM language detect ======
try:
    # LangChain Pydantic v1 (dipakai di repo ini)
    # from langchain_core.pydantic_v1 import BaseModel, Field
    from pydantic import BaseModel, Field
except Exception:
    from pydantic import BaseModel, Field  # fallback jika diperlukan

class LanguageDetectSchema(BaseModel):
    """Schema hasil deteksi bahasa oleh LLM."""
    code: str = Field(description="BCP-47/ISO code 2-3 huruf; contoh: 'id', 'en', 'fr', 'ms'.")
    name: str = Field(description="Endonym / nama bahasa yang natural, singkat; contoh: 'Indonesia', 'English', 'Français'.")
    confidence: float = Field(description="Keyakinan 0..1.")
    script: str | None = Field(default=None, description="Nama aksara jika relevan, mis. 'Latin', 'Cyrillic', 'Thai'.")

def build_language_detect_chain(llm):
    """
    Menghasilkan runnable chain untuk deteksi bahasa dengan structured output.
    Hasil mengikuti LanguageDetectSchema.
    """
    system = (
        "You are a language identification expert. "
        "Detect the language of the USER text precisely. "
        "For CODE-MIXED messages (multiple languages in one input), return the language that occupies the LARGEST PORTION of the SUBSTANTIVE content by word count — NOT the language of the opening greeting alone. "
        "Examples:\n"
        "- 'Selamat sore, can you help me with market research?' → 'en' (English) — the request is English; the greeting is just a politeness opener.\n"
        "- 'Hi, mau tanya tentang layanan market research nya' → 'id' (Indonesian) — the substantive question is Indonesian.\n"
        "- 'Halo' → 'id' (only 1 word, Indonesian).\n"
        "- 'Hi' → 'en' (only 1 word, English).\n"
        "Return a structured object with: code (BCP-47/ISO 639-1/2), name (endonym), confidence (0..1), and script (if relevant). "
        "Prefer the macrolanguage code when appropriate (e.g., 'id' for Indonesian, 'ms' for Malay). "
        "Do NOT include explanations."
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", system),
        ("human", "USER:\n{user_text}")
    ])
    structured = llm.with_structured_output(LanguageDetectSchema)
    return prompt | structured

# helper: format "Relevant services"
def _format_related_services(rs: Any) -> str:
    if rs is None:
        return "(none)"
    if isinstance(rs, str):
        rs = rs.strip()
        return rs or "(none)"
    if isinstance(rs, Sequence):
        items = [str(x).strip() for x in rs if str(x).strip()]
        if not items:
            return "(none)"
        # bullet list biar enak dibaca
        return "\n".join(f"- {it}" for it in items)
    return str(rs).strip() or "(none)"

# helper: format "Context"
def _format_context(ctx: Any) -> str:
    if ctx is None:
        return "(no matching context)"
    if isinstance(ctx, str):
        ctx = ctx.strip()
        return ctx or "(no matching context)"
    if isinstance(ctx, Sequence):
        lines: list[str] = []
        for i, x in enumerate(ctx, 1):
            if x is None:
                continue
            # dukung LangChain Document / dict / string
            if hasattr(x, "page_content"):
                txt = getattr(x, "page_content", "") or ""
            elif isinstance(x, dict):
                txt = x.get("page_content") or x.get("content") or x.get("text") or str(x)
            else:
                txt = str(x)
            txt = txt.strip()
            if txt:
                lines.append(f"{i}. {txt}")
        return "\n".join(lines) if lines else "(no matching context)"
    return str(ctx).strip() or "(no matching context)"

def _clip(text: str, limit: int | None) -> str:
    if not limit or limit <= 0:
        return text
    return text if len(text) <= limit else text[:limit] + "…"

def _safe_nick(nick: str | None) -> str | None:
    if not nick: return None
    nick = str(nick).strip().replace("\n"," ").replace("\r"," ")
    return nick[:25] or None

# DEPRECATED 2026-05-13 (Task 14): greeting palette migrated to centralized i18n loader.
# See modules/i18n/strings/{lang}.yaml `greeting.palette` entries.
# This dict is kept as RUNTIME FALLBACK during Phase 0 in case the i18n loader is
# unavailable (e.g., test isolation, very-early init). To be removed in Task 19 after
# consumer migration verified.
# Reference: docs/superpowers/specs/2026-05-13-ooc-response-engine-design.md §4.6 Step 3.
_GREETING_PALETTE: dict[str, list[str]] = {
    "id": [
        "Halo", "Hai", "Selamat pagi", "Selamat siang", "Selamat sore",
        "Apa kabar", "Senang bisa membantu", "Senang bertemu Anda",
        "Terima kasih sudah menghubungi", "Salam hangat", "Senang berbincang",
        "Selamat datang",
    ],
    "ms": [
        "Hai", "Apa khabar", "Selamat datang", "Selamat sejahtera",
        "Selamat pagi", "Selamat tengah hari", "Senang dapat membantu",
        "Terima kasih kerana menghubungi", "Salam mesra",
    ],
    "en": [
        "Hi there", "Hello", "Hey", "Good to hear from you",
        "Pleased to help", "Thanks for reaching out", "Welcome",
        "Glad you're here", "Nice to connect", "Great to meet you",
    ],
    "fr": [
        "Bonjour", "Salut", "Bienvenue", "Ravi de vous aider",
        "Heureux de vous rencontrer", "Merci de nous contacter",
        "Enchanté", "Content de vous voir", "Bonne journée",
    ],
    "de": [
        "Hallo", "Guten Tag", "Willkommen", "Schön, dass Sie da sind",
        "Freut mich zu helfen", "Danke für Ihre Anfrage",
        "Schönen Tag", "Grüß Sie", "Hallo zusammen",
    ],
    "it": [
        "Ciao", "Salve", "Buongiorno", "Buon pomeriggio", "Benvenuto",
        "Felice di aiutarla", "Grazie per averci contattato",
        "Piacere", "Lieto di assisterla",
    ],
    "pt": [
        "Olá", "Bom dia", "Boa tarde", "Bem-vindo",
        "Prazer em ajudar", "Obrigado pelo contato",
        "Que bom ter você aqui", "Saudações",
    ],
    "es": [
        "Hola", "Buenos días", "Buenas tardes", "Bienvenido",
        "Encantado de ayudarle", "Gracias por contactarnos",
        "Mucho gusto", "Un placer atenderle",
    ],
    "vi": [
        "Xin chào", "Chào bạn", "Rất vui được hỗ trợ",
        "Cảm ơn bạn đã liên hệ", "Hân hạnh được phục vụ", "Chào mừng bạn",
    ],
    "th": [
        "สวัสดี", "สวัสดีครับ", "สวัสดีค่ะ", "ยินดีต้อนรับ",
        "ยินดีที่ได้พบ", "ขอบคุณที่ติดต่อเรา", "ยินดีให้บริการ",
    ],
    "da": [
        "Hej", "Goddag", "God morgen", "Velkommen",
        "Tak fordi du henvendte dig", "Glæder mig at hjælpe",
        "Rart at møde dig",
    ],
    "zh": [
        "你好", "您好", "早上好", "下午好", "欢迎",
        "很高兴为您服务", "感谢您的联系", "很高兴认识您",
    ],
    "ja": [
        "こんにちは", "はじめまして", "ようこそ",
        "お問い合わせありがとうございます", "お役に立てれば幸いです",
        "おはようございます", "お疲れさまです",
    ],
    "ru": [
        "Здравствуйте", "Привет", "Добрый день", "Доброе утро",
        "Добро пожаловать", "Рад вам помочь", "Спасибо за обращение",
        "Приятно познакомиться",
    ],
}


def _greeting_palette_from_i18n(code: str) -> list[str]:
    """Task 14 — read greeting palette from i18n loader.

    Returns the list-typed entry from `modules/i18n/strings/{code}.yaml::greeting.palette`.
    Falls back to English i18n entry if the requested lang has no palette in i18n.
    Returns empty list if i18n loader is unavailable (caller falls back to legacy dict).
    """
    try:
        from modules.i18n import _get_registry
        registry = _get_registry()
        entry = registry.entries.get(("greeting.palette", code))
        if entry is not None and isinstance(entry.text, list) and entry.text:
            return entry.text
        # i18n fallback to English
        en_entry = registry.entries.get(("greeting.palette", "en"))
        if en_entry is not None and isinstance(en_entry.text, list) and en_entry.text:
            return en_entry.text
    except Exception:
        # i18n loader unavailable — caller falls back to legacy palette dict
        pass
    return []


def _pick_greeting(language_code: str | None, seed: str | None = None) -> tuple[str, str]:
    """Pick ONE greeting deterministically per session_id (or randomly if no seed).

    Returns (greeting_phrase, language_code_used). Falls back to English palette
    when language_code is unknown.

    Task 14 (2026-05-13): reads from centralized i18n loader via
    `_greeting_palette_from_i18n`. Falls back to DEPRECATED `_GREETING_PALETTE`
    dict only when i18n loader returns empty (defensive — keeps the helper
    safe during test isolation / early init). Task 19 deletes the legacy dict.
    """
    import random
    code = (language_code or "").strip().lower()[:2]

    # NEW (Task 14): primary path — i18n loader
    palette = _greeting_palette_from_i18n(code)

    # Legacy fallback (DEPRECATED — to be removed in Task 19)
    if not palette:
        palette = _GREETING_PALETTE.get(code) or _GREETING_PALETTE["en"]

    if seed:
        rnd = random.Random(seed)
        return rnd.choice(palette), code or "en"
    return random.choice(palette), code or "en"


def _salutation_rule(
    language_name: str,
    is_first_turn: bool,
    user_nick: str | None = None,
    *,
    language_code: str | None = None,
    session_seed: str | None = None,
) -> str:
    nick = _safe_nick(user_nick)
    if is_first_turn:
        # 2026-05-08 rev 2: programmatically pre-pick greeting from palette so we
        # don't depend on LLM choice. LLM kept defaulting to one safe phrase per
        # language. Now we pick the greeting outside the LLM and tell it to USE
        # this exact one (or a close natural variant if it must adapt).
        picked, _ = _pick_greeting(language_code, seed=session_seed)
        nick_clause = f" Address the user by name once ('{nick}') somewhere in the first sentence." if nick else ""
        return (
            f"Salutation:\n"
            f"- FIRST message. Open EXACTLY with this greeting (or a close natural variant if grammar requires): '{picked}'.{nick_clause}\n"
            f"- Total opener ≤8 words, including the greeting.\n"
            f"- After the greeting, briefly transition into the substance — do NOT append day-wishes ('semoga hari Anda menyenangkan' style).\n"
            f"- FORBIDDEN exact phrases (overused): 'Selamat datang, semoga hari Anda menyenangkan', 'Selamat datang di Acme Services', 'Welcome, hope your day is going well'.\n"
            f"- Keep tone human and natural in {language_name}; do NOT mix languages.\n"
        )
    return ("Salutation:\n- Not first message. No greeting; answer immediately.\n")

def _address_forms_by_language(language_code: str | None, user_nick: str | None) -> tuple[str, str]:
    nick = _safe_nick(user_nick)
    if not nick:
        return "", ""
    # lang = (language_code or "").lower()
    # by_lang = {
    #     "id": f"Bapak/Ibu {nick}",
    #     "ms": f"Encik/Puan {nick}",
    #     "fr": f"Monsieur/Madame {nick}",
    #     "de": f"Herr/Frau {nick}",
    #     "it": f"Signore/Signora {nick}",
    #     "rm": f"Signur/Signura {nick}",   # Romansh
    #     "ru": f"уважаемый(ая) {nick}",
    #     "th": f"คุณ{nick}",
    #     "es": f"Sr./Sra. {nick}",
    #     "pt": f"Sr./Sra. {nick}",
    #     "en": f"Mr./Ms. {nick}",
    #     # fallback lain bila perlu
    # }
    # # match prefix (mis. fr-CH → fr)
    # for k, v in by_lang.items():
    #     if lang.startswith(k):
    #         return nick, v
    return nick, nick  # fallback: nama saja

def _personalization_rule(language_name: str, language_code: str | None,
                          user_nick: str | None) -> str:
    nick_plain, addr_formal = _address_forms_by_language(language_code, user_nick)
    _lang = (language_code or "").lower()
    _formal_pronoun_rule = ""
    if _lang.startswith("id") or _lang.startswith("ms"):
        _formal_pronoun_rule = (
            "- Address the user using the formal pronoun 'Anda'. "
            "NEVER use casual forms such as 'kamu', 'kau', 'lu', 'lo', or 'engkau'. "
            "Maintain a polite, professional tone throughout.\n"
        )
    if not nick_plain:
        return "Personalization:\n- No nickname provided; do not invent a name.\n" + _formal_pronoun_rule

    # --- Aturan khusus per bahasa (prefix match: 'fr', 'id', 'de', dst.) ---
    lang = (language_code or "").lower()

    _lang_specific_guidance = {
        # # Indonesia
        # "id": (
        #     "- In Indonesian (id-*), use the paired neutral honorific “Bapak/Ibu {nick}”. "
        #     "Do not shorten to Pak/Bu unless the user does so first. "
        #     "When leading a sentence, you may add a comma (e.g., “Bapak/Ibu {nick}, ...”).\n"
        # ),
        # # Melayu
        # "ms": (
        #     "- In Malay (ms-*), use “Encik/Puan {nick}”. Keep spacing normal (one space). "
        #     "Do not stack honorific and name twice in the same sentence.\n"
        # ),
        # # Prancis
        # "fr": (
        #     "- In French (fr-*), ALWAYS use the paired honorific “Monsieur/Madame {nick}” "
        #     "unless the user explicitly states a gendered form. A comma after the salutation is acceptable.\n"
        # ),
        # # Jerman
        # "de": (
        #     "- In German (de-*), use “Herr/Frau {nick}”. When the address starts a sentence, "
        #     "prefer a comma after it (e.g., “Herr/Frau {nick}, ...”).\n"
        # ),
        # # Italia
        # "it": (
        #     "- In Italian (it-*), use “Signore/Signora {nick}”. "
        #     "Avoid gendered selection unless the user clarifies; keep the paired form when unsure.\n"
        # ),
        # # Romansh
        # "rm": (
        #     "- In Romansh (rm-*), use “Signur/Signura {nick}”. Keep it concise and polite.\n"
        # ),
        # # Rusia
        # "ru": (
        #     "- In Russian (ru-*), use “уважаемый(ая) {nick}”. "
        #     "Do not guess gender or add patronymics unless provided by the user. "
        #     "A comma after the salutation is stylistically correct.\n"
        # ),
        # # Thai
        # "th": (
        #     "- In Thai (th-*), use the prefix “คุณ{nick}” (no space between honorific and name). "
        #     "Avoid repeating the honorific in adjacent sentences.\n"
        # ),
        # # Spanyol
        # "es": (
        #     "- In Spanish (es-*), use “Sr./Sra. {nick}”. Keep one space after the abbreviation. "
        #     "A comma after the salutation is acceptable when leading a sentence.\n"
        # ),
        # # Portugis
        # "pt": (
        #     "- In Portuguese (pt-*), use “Sr./Sra. {nick}”. Keep one space after the abbreviation. "
        #     "A comma after the salutation is acceptable when leading a sentence.\n"
        # ),
        # # Inggris (netral)
        # "en": (
        #     "- In English (en-*), use “Mr./Ms. {nick}” as a neutral paired form when a title is needed; "
        #     "prefer the plain name if unsure. Avoid guessing gendered titles.\n"
        # ),

        # Indonesia
        "id": (
            "- In Indonesian (id-*), use the paired neutral honorific “{nick}”. "
            "Do not shorten to Pak/Bu unless the user does so first. "
            "When leading a sentence, you may add a comma (e.g., “{nick}, ...”).\n"
        ),
        # Melayu
        "ms": (
            "- In Malay (ms-*), use “{nick}”. Keep spacing normal (one space). "
            "Do not stack honorific and name twice in the same sentence.\n"
        ),
        # Prancis
        "fr": (
            "- In French (fr-*), ALWAYS use the paired honorific “{nick}” "
            "unless the user explicitly states a gendered form. A comma after the salutation is acceptable.\n"
        ),
        # Jerman
        "de": (
            "- In German (de-*), use “{nick}”. When the address starts a sentence, "
            "prefer a comma after it (e.g., “{nick}, ...”).\n"
        ),
        # Italia
        "it": (
            "- In Italian (it-*), use “{nick}”. "
            "Avoid gendered selection unless the user clarifies; keep the paired form when unsure.\n"
        ),
        # Romansh
        "rm": (
            "- In Romansh (rm-*), use “{nick}”. Keep it concise and polite.\n"
        ),
        # Rusia
        "ru": (
            "- In Russian (ru-*), use “{nick}”. "
            "Do not guess gender or add patronymics unless provided by the user. "
            "A comma after the salutation is stylistically correct.\n"
        ),
        # Thai
        "th": (
            "- In Thai (th-*), use the prefix “{nick}” (no space between honorific and name). "
            "Avoid repeating the honorific in adjacent sentences.\n"
        ),
        # Spanyol
        "es": (
            "- In Spanish (es-*), use “{nick}”. Keep one space after the abbreviation. "
            "A comma after the salutation is acceptable when leading a sentence.\n"
        ),
        # Portugis
        "pt": (
            "- In Portuguese (pt-*), use “{nick}”. Keep one space after the abbreviation. "
            "A comma after the salutation is acceptable when leading a sentence.\n"
        ),
        # Inggris (netral)
        "en": (
            "- In English (en-*), use “{nick}” as a neutral paired form when a title is needed; "
            "prefer the plain name if unsure. Avoid guessing gendered titles.\n"
        ),
    }

    # Pilih aturan bahasa (prefix match); kalau tidak ada, tak perlu extra khusus.
    extras = ""
    for prefix, guidance in _lang_specific_guidance.items():
        if lang.startswith(prefix):
            # substitusi {nick} agar contoh di guidance konsisten
            extras = guidance.replace("{nick}", nick_plain)
            break

    # --- Aturan umum (tetap dipertahankan) ---
    # base = (
    #     "Personalization:\n"
    #     f"- Nickname: \"{nick_plain}\""
    #     "- Use at least ONE mention per reply; do not force it in the greeting.\n"
    #     "- For longer replies, you MAY repeat the name or the honorific roughly every 3 sentences.\n"
    #     "- Cadence limits: ≤6 sentences → max 2 mentions; >6 sentences → max 3 mentions.\n"
    #     "- Vary the placement (opening/middle/closing) and alternate between plain name and the honorific.\n"
    #     "- Never repeat the name in consecutive sentences.\n"
    # )
    return (
        "Personalization:\n"
        "- Do NOT mention, address, paraphrase, or repeat the user's name in ANY sentence. "
        "The user's name must NEVER appear in your response — not as a greeting, not as a vocative, not at the end. "
        "Respond naturally without any name, title, or honorific.\n"
    ) + _formal_pronoun_rule

# ---- PROMPT Automation Processing ----

# def build_greeting_chain(llm):
#     template = ChatPromptTemplate.from_messages([
#         ("system",
#          "You are an AI Assistant acting as a professional, persuasive, and trustworthy business consultant providing accurate and up-to-date information about Acme Services’s services named the chatbot"
#         #  "If the user's message is only a greeting/salutation, reply in the SAME language as the user's message. "
#          "Target language: {language_name}. If the user's message is only a greeting/salutation, reply in the SAME language as the user's message."
#          "You may use either the plain name (“{nickname}”) or the formal address (“{address_formal}”) according to the target language."
#          "Keep it very short (2–3 sentences, <25 words). No lists, no markdown. "
#         #  "Politely ask how you can help and optionally offer to schedule a meeting with our sales/specialist team."),
#         "Politely ask how you can help."),
#         ("human", "{user_text}")
#     ])
#     return template | llm

# def build_prompts():
#     incontext_prompt = PromptTemplate(
#         template="""
# You are an AI Assistant acting as a professional, persuasive, and trustworthy business consultant providing accurate and up-to-date information about Acme Services’s services named the chatbot.
# Target language: {language_name}. Answer strictly using the provided context chunks. Be concise (4–6 sentences), synthesize points, avoid repetition.
# You may use either the plain name (“{nickname}”) or the formal address (“{address_formal}”) according to the target language.

# Relevant services:
# {related_services}

# Context:
# {context}

# User Question:
# {question}

# Guidelines:
# - Summarize only key points relevant to the question using the context above; do not fabricate.
# - Do NOT output any handoff block on the first turn.
#  -Answer concisely in {language_name}. Use ≤5 sentences or ≤5 bullet points. Avoid long introductions. If a list is needed, cap at 5 items.
# - Closing: End with ONE short, natural closing sentence in the target language (not English unless the target language is English) that:
#   (a) offers further assistance, and
#   (b) invites the user to schedule a meeting with our sales/specialist team regarding their needs.
# """,
#         input_variables=["context", "question", "language_name", "related_services"]
#     )

#     outcontext_prompt = PromptTemplate(
#         template="""
# You are an AI Assistant acting as a professional, persuasive, and trustworthy business consultant providing accurate and up-to-date information about Acme Services’s services named the chatbot.
# Target language: {language_name}. Very concise answer (3–4 sentences). If the context is limited or not directly answering,
# acknowledge the limitation without inventing details and suggest the next step (e.g., provide more specifics or arrange a meeting).
# You may use either the plain name (“{nickname}”) or the formal address (“{address_formal}”) according to the target language.

# Relevant services:
# {related_services}

# Available Context (may be 0–2 items):
# {context}

# User Question:
# {question}

# Closing:
# - Answer concisely in {language_name}. Use ≤5 sentences or ≤5 bullet points. Avoid long introductions. If a list is needed, cap at 5 items.
# - End with ONE short, natural closing sentence in the target language (not English unless the target language is English) that:
#   (a) offers further assistance, and
#   (b) invites the user to schedule a meeting with our sales/specialist team regarding their needs.
# """,
#         input_variables=["context", "question", "language_name", "related_services"]
#     )

#     return incontext_prompt, outcontext_prompt

def build_greeting_chain(llm):
    template = ChatPromptTemplate.from_messages([
        ("system",
         "You are an AI Assistant acting as a professional, persuasive, and trustworthy business consultant providing accurate and up-to-date information about Acme Services’s services"
        #  "If the user's message is only a greeting/salutation, reply in the SAME language as the user's message. "
         "Target language: {language_name}. If the user's message is only a greeting/salutation, reply in the SAME language as the user's message."
         "Keep it very short (2–3 sentences, <25 words). No lists, no markdown. "
        #  "Politely ask how you can help and optionally offer to schedule a meeting with our sales/specialist team."),
        "Politely ask how you can help."),
        ("human", "{user_text}")
    ])
    return template | llm

def build_prompts():
    incontext_prompt = PromptTemplate(
        template="""
You are an AI Assistant acting as a professional, persuasive, and trustworthy business consultant providing accurate and up-to-date information about Acme Services’s services.
Target language: {language_name}. Answer strictly using the provided context chunks. Be concise (3 sentences), synthesize points, avoid repetition.

Relevant services:
{related_services}

Context:
{context}

User Question:
{question}

Guidelines:
- Summarize only key points relevant to the question using the context above; do not fabricate.
- Do NOT output any handoff block on the first turn.
 -Answer concisely in {language_name}. Use ≤3 sentences or ≤3 bullet points. Avoid long introductions. If a list is needed, cap at 3 items.
""",
        input_variables=["context", "question", "language_name", "related_services"]
    )

    outcontext_prompt = PromptTemplate(
        template="""
You are an AI Assistant acting as a professional, persuasive, and trustworthy business consultant providing accurate and up-to-date information about Acme Services’s services.
Target language: {language_name}. Very concise answer (3 sentences). If the context is limited or not directly answering,
acknowledge the limitation without inventing details and suggest the next step (e.g., provide more specifics or arrange a meeting).

Relevant services:
{related_services}

Available Context (may be 0–2 items):
{context}

User Question:
{question}

Closing:
- Answer concisely in {language_name}. Use ≤3 sentences or ≤3 bullet points. Avoid long introductions. If a list is needed, cap at 3 items.
- End with ONE short, natural closing sentence in the target language (not English unless the target language is English) that:
  (a) offers further assistance.
""",
        input_variables=["context", "question", "language_name", "related_services"]
    )

    return incontext_prompt, outcontext_prompt

# ---- PROMPT List -----

# greeting_prompt_applied = """You are the chatbot.

# Target language: {language_name}. If the user's message is only a greeting/salutation, reply in the SAME language as the user's message.

# Strict rules:
# - Reply in EXACTLY 1 short sentence for pure greetings.
# - Use only a simple natural greeting and one short offer to help.
# - Examples:
#   - "Good morning. How can I help you today?"
#   - "Hi there. How can I assist you?"
# - Do NOT introduce yourself.
# - Do NOT mention the chatbot unless the user asks who you are.
# - Do NOT mention company or services.
# - Do NOT use promotional wording.
# - No lists, no markdown.

# User Message:
# {user_text}
# """

# outcontext_prompt_applied="""You are an AI Assistant acting as a professional, persuasive, and trustworthy business consultant providing accurate and up-to-date information about Acme Services’s services named the chatbot.
# Target language: {language_name}. Very concise answer (3–4 sentences). If the context is limited or not directly answering,
# acknowledge the limitation without inventing details and suggest the next step (e.g., provide more specifics or arrange a meeting).
# You may use either the plain name (“{nickname}”) or the formal address (“{address_formal}”) according to the target language.

# Relevant services:
# {related_services}

# Available Context (may be 0–2 items):
# {context}

# User Question:
# {question}

# Closing:
# - Answer concisely in {language_name}. Use ≤5 sentences or ≤5 bullet points. Avoid long introductions. If a list is needed, cap at 5 items.
# - End with ONE short, natural closing sentence in the target language (not English unless the target language is English) that:
#   (a) offers further assistance, and
#   (b) invites the user to schedule a meeting with our sales/specialist team regarding their needs.
# """

greeting_prompt_applied = """You are an AI Assistant acting as a professional, persuasive, and trustworthy business consultant providing accurate and up-to-date information about Acme Services’s services.
Target language: {language_name}. If the user's message is only a greeting/salutation, reply in the SAME language as the user's message.
Keep it very short (1–2 sentences, <15 words). No lists, no markdown. Politely ask how you can help.

User Message:
{user_text}
"""

incontext_prompt_applied = """You are an AI Assistant acting as a professional, persuasive, and trustworthy business consultant providing accurate and up-to-date information about Acme Services’s services.
Target language: {language_name}. Answer strictly using the provided context chunks. Be concise (2–4 sentences), synthesize points, avoid repetition.

Relevant services:
{related_services}

Context:
{context}

User Question:
{question}

Guidelines:
- Summarize only key points relevant to the question using the context above; do not fabricate.
- Do NOT output any handoff block on the first turn.
 -Answer concisely in {language_name}. Use ≤3 sentences or ≤3 bullet points. Avoid long introductions. If a list is needed, cap at 3 items.
"""

intro_prompt_applied = """You are a professional assistant.

Target language: {language_name}.

The user is introducing themselves or their organization.
Your reply must sound natural, human, and common in business chat.

Strict rules:
- Reply in EXACTLY 2 short sentences.
- Sentence 1 must briefly acknowledge the introduction naturally.
- Prefer simple phrases like:
  - "Nice to meet you."
  - "Nice to meet you, John."
  - "Thanks for the introduction."
- Do NOT thank the user for reaching out.
- Do NOT repeat the full company name unless the user explicitly asks about it.
- Do NOT introduce yourself again.
- Do NOT mention any internal product or persona name for the assistant.
- Do NOT sound promotional, persuasive, or ceremonial.
- Do NOT use long formal phrases.
- Sentence 2 must simply ask how you can help.
- No lists, no markdown, no extra details.

User Message:
{user_text}
"""

outcontext_prompt_applied="""You are an AI Assistant acting as a professional, persuasive, and trustworthy business consultant providing accurate and up-to-date information about Acme Services’s services.
Target language: {language_name}. Very concise answer (3 sentences). If the context is limited or not directly answering,
acknowledge the limitation without inventing details and suggest the next step (e.g., provide more specifics or arrange a meeting).

Guard:
- If the user is only greeting or introducing themselves, do NOT mention lack of context.
- For greetings or introductions, respond naturally and briefly.
- Do NOT thank the user for reaching out unless they asked for help.
- Do NOT restate the company name unless necessary.
- Do NOT introduce yourself unless the user asks who you are.

Relevant services:
{related_services}

Available Context (may be 4 items):
{context}

User Question:
{question}

Closing:
- Answer concisely in {language_name}. Use ≤3 sentences or ≤3 bullet points. Avoid long introductions. If a list is needed, cap at 3 items."
"""

# Greeting prompt juga kita kondisikan:
def render_greeting_prompt(*, language_name: str, user_text: str,
                           is_first_turn: bool, user_nick: str | None = None,
                           language_code: str | None = None,
                           max_chars: int | None = None,
                           chat_history_block: str | None = None,
                           chat_summary_block: str | None = None) -> str: #penambahan cwh logic
    sal = _salutation_rule(language_name, is_first_turn, user_nick, language_code=language_code)
    nick_plain, addr_formal = _address_forms_by_language(language_code, user_nick)
    pers = _personalization_rule(language_name, language_code, user_nick)
    text = sal + "\n" + pers + "\n" + greeting_prompt_applied.format(
        language_name=(language_name or "").strip(),
        user_text=(user_text or "").strip(),
        nickname=nick_plain or "",
        address_formal=addr_formal or "",
    )

    if chat_summary_block:  # allsum
        text += "\n\n" + chat_summary_block
    if chat_history_block:  # last3
        text += "\n\n" + chat_history_block
    if max_chars is None: max_chars = DEFAULT_MAX
    return _clip(text, max_chars)

def render_intro_prompt(*, language_name: str, user_text: str,
                        is_first_turn: bool, user_nick: str | None = None,
                        language_code: str | None = None,
                        max_chars: int | None = None,
                        chat_history_block: str | None = None,
                        chat_summary_block: str | None = None) -> str:
    sal = _salutation_rule(language_name, is_first_turn, user_nick, language_code=language_code)
    text = sal + "\n" + intro_prompt_applied.format(
        language_name=(language_name or "").strip(),
        user_text=(user_text or "").strip(),
    )

    if chat_summary_block:
        text += "\n\n" + chat_summary_block
    if chat_history_block:
        text += "\n\n" + chat_history_block
    if max_chars is None:
        max_chars = DEFAULT_MAX
    return _clip(text, max_chars)

# def render_incontext_prompt(*, language_name: str, related_services, context, question,
#                             is_first_turn: bool, user_nick: str | None = None,
#                             language_code: str | None = None,
#                             max_chars: int | None = None,
#                             chat_history_block: str | None = None,
#                             chat_summary_block: str | None = None) -> str:
#     sal = _salutation_rule(language_name, is_first_turn, user_nick, language_code=language_code)
#     nick_plain, addr_formal = _address_forms_by_language(language_code, user_nick)
#     pers = _personalization_rule(language_name, language_code, user_nick)

#     # 1) format bagian yang FIXED dulu (tanpa context)
#     fixed_head = sal + "\n" + pers + "\n"
#     body_wo_ctx = (
#         "You are an AI Assistant acting as a professional, persuasive, and trustworthy business consultant providing accurate and up-to-date information about Acme Services’s services named the chatbot.\n"
#         f"Target language: {language_name}. Answer strictly using the provided context chunks. Be concise (4–6 sentences), synthesize points, avoid repetition.\n"
#         f"You may use either the plain name (“{nick_plain or ''}”) or the formal address (“{addr_formal or ''}”) according to the target language.\n\n"
#         f"Relevant services:\n{_format_related_services(related_services)}\n\n"
#         "Context:\n"  # <— context akan ditulis belakangan setelah diklip
#     )

#     tail_after_ctx = (
#         f"\n\nUser Question:\n{(question or '').strip()}\n\n"
#         "Guidelines:\n"
#         f"- Summarize only key points relevant to the question using the context above; do not fabricate.\n"
#         f"- Do NOT output any handoff block on the first turn.\n"
#         f" -Answer concisely in {language_name}. Use ≤5 sentences or ≤5 bullet points. Avoid long introductions. If a list is needed, cap at 5 items.\n"
#         f"- Closing: End with ONE short, natural closing sentence in the target language (not English unless the target language is English) that:\n"
#         f"  (a) offers further assistance, and\n"
#         f"  (b) invites the user to schedule a meeting with our sales/specialist team regarding their needs.\n"
#     )

#     # 2) hitung budget
#     if max_chars is None:
#         max_chars = DEFAULT_MAX

#     # panjang blok opsional yang harus ikut
#     opt_blocks = ""
#     if chat_summary_block:
#         opt_blocks += "\n\n" + chat_summary_block
#     if chat_history_block:
#         opt_blocks += "\n\n" + chat_history_block

#     # 3) tentukan sisa untuk CONTEXT
#     # pastikan konteks yang ditulis muat bersama semua bagian penting
#     fixed_len = len(fixed_head) + len(body_wo_ctx) + len(tail_after_ctx) + len(opt_blocks)
#     remain_for_ctx = max(0, max_chars - fixed_len)
#     ctx_text = _format_context(context)
#     ctx_text = _clip(ctx_text, remain_for_ctx)

#     # 4) rakit final string
#     text = fixed_head + body_wo_ctx + ctx_text + tail_after_ctx
#     if chat_summary_block:
#         text += "\n\n" + chat_summary_block
#     if chat_history_block:
#         text += "\n\n" + chat_history_block

#     # safeguard terakhir (harusnya sudah aman)
#     return _clip(text, max_chars)

# --- konstanta singkat untuk handoff (opsional) -----------------------
MEETING_HANDOFF_NOTE_EN = "Our team will get in touch soon to follow up on your needs."

def render_incontext_prompt(*,
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
    # === NEW: kontrol handoff note (default None = tidak ditampilkan) ===
    MEETING_HANDOFF_NOTE_EN: str | None = None,
    next_q_enabled: bool = False,
    next_q_seed: str | None = None,
    service_validation_enabled: bool = False,
    service_validation_seed: str = "-",
) -> str:
    sal = _salutation_rule(language_name, is_first_turn, user_nick, language_code=language_code)
    nick_plain, addr_formal = _address_forms_by_language(language_code, user_nick)
    pers = _personalization_rule(language_name, language_code, user_nick)

    # 1) header & body tanpa context
    fixed_head = sal + "\n" + pers + "\n"
    body_wo_ctx = (
        "You are an AI Assistant acting as a professional, persuasive, and trustworthy business consultant providing accurate and up-to-date information about Acme Services’s services.\n"
        f"Target language: {language_name}. Answer strictly using the provided context chunks. Be concise (3 sentences), synthesize points, avoid repetition.\n\n"
        f"Relevant services:\n{_format_related_services(related_services)}\n\n"
        "Context:\n"  # <— context akan ditulis belakangan setelah diklip
    )

    # next_q_block = ""
    # if next_q_enabled:
    #     # kalau seed kosong, tampilkan "-" (sesuai request)
    #     _seed_txt = (str(next_q_seed).strip() if next_q_seed is not None else "").strip()
    #     if not _seed_txt:
    #         _seed_txt = "-"
    #     next_q_block = f"Next Qualification Question:\n{_seed_txt}\n"

    sv_block = ""
    if service_validation_enabled:
        sv_block = (
            "Service Validation Question:\n"
            f"{(service_validation_seed or '-').strip()}\n"
        )
    else:
        sv_block = (
            "Next Qualification Question:\n"
            f"{(next_q_seed or '-').strip()}\n"
        )

    # 2) bagian setelah context (GUIDELINES diperbaiki)
    tail_after_ctx = (
        f"\n\nUser Question:\n{(question or '').strip()}\n\n"
        f"{sv_block}\n"
        "Guidelines:\n"
        "- Summarize only key points relevant to the question using the context above; do not fabricate.\n"
        "- Do NOT output any handoff block on the first turn.\n"
        f"- Answer concisely in {language_name}. Use ≤3 sentences or ≤3 bullet points. Avoid long introductions. If a list is needed, cap at 3 items.\n"
        # "- Closing: End with ONE short, use a formal and polite tone, natural closing sentence in the target language (not English unless the target language is English) that:\n"
        # "  (a) offers further assistance in the form of invite a two-way conversation.\n"
        # "  (b) is clearly related to the user's main goal and, when helpful, the Chat history / Chat summarization blocks above.\n"
        # f"  (b) includes a brief, polite assurance such as: {MEETING_HANDOFF_NOTE_EN}.\n"
        "- If a Service Validation Question block is present, you MUST end your reply with ONE short question asking the user to select ONE service to focus on, WITHOUT listing any service names (choices are shown in UI).\n"
        "- If a Next Qualification Question block is present, you MUST append ONE question at the END of the SAME paragraph as the answer.\n "
        "- Do NOT start a new line or paragraph for the question.\n"
        "- You may rephrase naturally, but keep the intent and requested fields identical.\n"
        "- Do NOT mention internal labels like 'Next Qualification Question' in your final user-visible reply.\n\n"
        "Output Formatting Rules (STRICT):\n"
        "- Output MUST be a SINGLE paragraph.\n"
        "- Do NOT use line breaks or blank lines.\n"
        "- Do NOT separate answer and question into different paragraphs.\n "
        "- Do NOT start a new line or paragraph for the question.\n"
        "- The qualification question MUST be in the same paragraph as the answer.\n"
        "- Use natural sentence flow, separated only by spaces.\n"
    )

    # 3) budget & optional blocks (summary/history)
    if max_chars is None:
        max_chars = DEFAULT_MAX

    opt_blocks = ""
    if chat_summary_block:
        opt_blocks += "\n\n" + chat_summary_block
    if chat_history_block:
        opt_blocks += "\n\n" + chat_history_block

    # 4) sisa untuk context
    fixed_len = len(fixed_head) + len(body_wo_ctx) + len(tail_after_ctx) + len(opt_blocks)
    remain_for_ctx = max(0, max_chars - fixed_len)
    ctx_text = _format_context(context)
    ctx_text = _clip(ctx_text, remain_for_ctx)

    # 5) rakit final
    text = fixed_head + body_wo_ctx + ctx_text + tail_after_ctx
    if chat_summary_block:
        text += "\n\n" + chat_summary_block
    if chat_history_block:
        text += "\n\n" + chat_history_block
    return _clip(text, max_chars)

def render_outcontext_prompt(*, language_name: str, related_services, context, question,
                             is_first_turn: bool, user_nick: str | None = None,
                             language_code: str | None = None,
                             max_chars: int | None = None,
                             chat_history_block: str | None = None,
                             chat_summary_block: str | None = None) -> str:
    sal = _salutation_rule(language_name, is_first_turn, user_nick, language_code=language_code)
    nick_plain, addr_formal = _address_forms_by_language(language_code, user_nick)
    pers = _personalization_rule(language_name, language_code, user_nick)
    text = sal + "\n" + pers + "\n" + outcontext_prompt_applied.format(
        language_name=language_name.strip(),
        related_services=_format_related_services(related_services),
        context=_format_context(context),
        question=(question or "").strip(),
        nickname=nick_plain or "",
        address_formal=addr_formal or "",
    )
    if chat_summary_block:  # allsum
        text += "\n\n" + chat_summary_block
    if chat_history_block:  # last3
        text += "\n\n" + chat_history_block
    if max_chars is None:
        max_chars = DEFAULT_MAX
    return _clip(text, max_chars)

meeting_start_prompt_applied = """You are an AI Helpfull Assistant acting as a professional, persuasive, and trustworthy business consultant providing accurate and up-to-date information about Acme Services’s services.
Target language: {language_name}.
The user wants to arrange a meeting. Reply briefly (2–3 sentences) in the SAME language
Ask for: preferred day and time window.
All times are in WIB (GMT+07). Working hours are 08:30–17:30 WIB. IMPORTANT: Lunch break 12:00–13:00 WIB is unavailable—never offer or confirm any slot that overlaps it.
"""

def render_meeting_start_prompt(*, language_name: str, is_first_turn: bool,
                                user_nick: str | None = None,
                                language_code: str | None = None,
                                max_chars: int | None = None,
                                chat_history_block: str | None = None,
                                chat_summary_block: str | None = None) -> str:
    sal = _salutation_rule(language_name, is_first_turn, user_nick, language_code=language_code)
    nick_plain, addr_formal = _address_forms_by_language(language_code, user_nick)
    pers = _personalization_rule(language_name, language_code, user_nick)
    text = sal + "\n" + pers + "\n" + meeting_start_prompt_applied.format(
        language_name=(language_name or "").strip(),
        nickname=nick_plain or "",
        address_formal=addr_formal or "",
    )
    if chat_summary_block:  # allsum
        text += "\n\n" + chat_summary_block
    if chat_history_block:  # last3
        text += "\n\n" + chat_history_block
    if max_chars is None:
        max_chars = DEFAULT_MAX
    return _clip(text, max_chars)


# === Anti-Redundancy: dedup guidelines wrapper (Stage 2026-05-11) ===
# Appends 3 extra bullets at the END of an already-rendered prompt. Only
# invoked when REDUNDANCY_METHOD != "normal" (see sd_service.py). Existing
# render_*_prompt functions remain byte-identical for the normal path.

_DEDUP_GUIDELINES_EN = (
    "\n\nAdditional guidelines (anti-redundancy):\n"
    "- Each FAQ entry below is distinct. Do NOT paraphrase the same point twice "
    "in your reply. If two entries express similar ideas, synthesize them into "
    "ONE sentence and treat that as the single mention.\n"
    "- If your previous reply already covered a topic (visible in chat history / "
    "summary), do NOT restate it verbatim. Either add new detail, switch angle, "
    "or acknowledge briefly: \"I covered that earlier — would you like a "
    "different angle?\".\n"
    "- If the context above is empty OR you cannot answer confidently from "
    "context + chat history, say in the user's language: \"I don't have that "
    "specific information; let me connect you with our team\" — DO NOT invent."
)


def apply_dedup_guidelines(rendered_text: str, language_name: str | None = None) -> str:
    """Append anti-redundancy guideline bullets to an already-rendered prompt.

    The `language_name` parameter is reserved for future i18n; v0 always uses
    the English bullet set because the SD/SA prompt scaffolding is in English
    and the LLM applies the rules to its target-language output naturally.
    """
    return (rendered_text or "") + _DEDUP_GUIDELINES_EN