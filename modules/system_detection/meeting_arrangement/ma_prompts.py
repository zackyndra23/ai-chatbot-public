from modules.system_detection.sd_prompts import (
    _salutation_rule,
    _personalization_rule,
    MEETING_HANDOFF_NOTE_EN,
    _address_forms_by_language,
    _clip,
    DEFAULT_MAX,
)
from .ma_utils import example_lines

# === MEETING START: i18n NOTE (no hardcode English) ===
MEETING_START_NOTE_PROMPT = """
You are a localization assistant.
Target language: {language_code}.
Return ONLY one concise sentence (no quotes, no markdown) that states:
- The meeting duration is 1 hour,
- The window is between {start_hour}:00 and {end_hour}:00 WIB,
- End with exactly: "Opsi: {slot_windows_csv}" (translate the word for "Options" appropriately in the target language).
Do NOT mention minutes like "on the hour".
One sentence only.
"""

def render_meeting_start_note_prompt(language_code: str, start_hour: int, end_hour: int, slot_windows_csv: str) -> str:
    # Kembalikan micro-prompt generik; hasil kalimatnya akan dibuat oleh LLM di sd_service
    return MEETING_START_NOTE_PROMPT.format(
        language_code=language_code or "id",
        start_hour=start_hour,
        end_hour=end_hour,
        slot_windows_csv=slot_windows_csv,
    )

# --- di ma_prompts.py ---

meeting_start_prompt_applied = """You are an AI Helpfull Assistant acting as a professional, persuasive, and trustworthy business consultant providing accurate and up-to-date information about Integrity’s services.
Target language: {language_name}.

The user wants to arrange a meeting. Reply briefly (2–4 sentences) in the SAME language.
Ask the user for a preferred day and a time window. All times are WIB (GMT+07).
Working hours: {business_hours}.

MANDATORY NOTE (output requirement):
- Include the following note as a separate sentence in your answer, verbatim, without rephrasing:
  {note_constraints}
"""


def render_meeting_start_prompt(
    *,
    language_name: str,
    is_first_turn: bool,
    user_nick: str | None = None,
    language_code: str | None = None,
    # configurable business hours + note constraints
    business_hours: str = "09:00–17:00 WIB",
    note_constraints: str = "",
    # SD-style context blocks
    max_chars: int | None = None,
    chat_history_block: str | None = None,   # e.g. last3
    chat_summary_block: str | None = None,   # e.g. allsum
) -> str:
    """
    Unified renderer:
    - Salutation & Personalization (pola SD)
    - Core meeting-start prompt + examples
    - Dynamic business hours + NOTE (language-aware, injected by caller)
    - Optional chat_summary_block / chat_history_block
    - Length clipping (pola SD)
    """
    # import kecil agar tidak bikin siklus
    from modules.system_detection.sd_prompts import _address_forms_by_language, _clip, DEFAULT_MAX
    # util lokal yg sudah ada di file ini:
    sal = _salutation_rule(
        language_name, is_first_turn, user_nick, language_code=language_code,
    )
    nick_plain, address_formal = _address_forms_by_language(language_code, user_nick)
    pers = _personalization_rule(language_name, language_code, user_nick)
    ex_lines = example_lines(language_code or "id")  # sudah ada di file ini
    ex_block = "\n".join(f"- {x}" for x in ex_lines)

    # isi template utama + NOTE (dynamic) + business hours
    core = meeting_start_prompt_applied.format(
        language_name=(language_name or "").strip(),
        nickname=nick_plain or "",
        address_formal=address_formal or "",
        business_hours=business_hours,
        note_constraints=(note_constraints or "").strip(),  # <- langsung pakai
    )

    # rangkai final prompt (pola SD tetap dipertahankan)
    text = (
        sal + "\n" +            # salutation rule
        pers + "\n" +           # personalization rule
        core + "\n" +           # main meeting-start block (with NOTE)
        ex_block + "\n"         # example lines
    )

    # konteks opsional (ikut pola lama SD)
    if chat_summary_block:      # allsum (panjang, global)
        text += "\n\n" + chat_summary_block.strip()
    if chat_history_block:      # last3 (pendek, lokal)
        text += "\n\n" + chat_history_block.strip()

    # clipping tetap ada (pola SD)
    if max_chars is None:
        max_chars = DEFAULT_MAX
    return _clip(text, max_chars)

# === Deskripsi meeting untuk kalender (LLM) ===
DESC_SUMMARY_PROMPT = """
You are a helpful assistant generating a concise meeting description in {language_name}.
Goal: write 4–6 compact sentences (no bullets) summarizing the client’s need and context.

Inputs (JSON):
- user_profile: {user_profile_json}
- chat_snippets: {chat_snippets_json}
- window: {window_text}
- related_services: {related_services_json}

Rules:
- Be factual; only use provided info. No fabrication.
- Put most important goal first, then key details (scope/questions), then next step.
- If services list exists, mention it naturally (not as a list).
- End with a single sentence stating the meeting objective and expected outcome.
- Language: {language_name}. No markdown, no headers.
"""

def render_desc_summary_prompt(*, language_name: str,
                               user_profile: dict,
                               chat_snippets: list[dict],
                               window_text: str,
                               related_services: list[str]) -> str:
    import json
    return DESC_SUMMARY_PROMPT.format(
        language_name=language_name,
        user_profile_json=json.dumps(user_profile, ensure_ascii=False),
        chat_snippets_json=json.dumps(chat_snippets[-12:], ensure_ascii=False),
        window_text=window_text,
        related_services_json=json.dumps(related_services, ensure_ascii=False),
    )

#LLM generate untuk hasil propose meeting slots
def llm_meeting_reply_inline(lang: str, nick_plain: str, addr_formal: str, vars: dict) -> str:
    who = (addr_formal or nick_plain or "").strip()
    when_txt = vars.get("when_text","")
    mode = (vars.get("mode","") or "").upper()
    weekly_md = vars.get("weekly_table_md","")

    if mode == "AVAILABLE":
        if (lang or "").lower().startswith("en"):
            return f"{who}, I can schedule your meeting on {when_txt}. Does this time work? If yes, I’ll confirm and send a calendar invite."
        return f"{who}, saya dapat menjadwalkan pertemuan pada {when_txt}. Apakah waktu tersebut sesuai? Jika ya, saya akan konfirmasi dan mengirim undangan kalender."
    else:
        if (lang or "").lower().startswith("en"):
            head = f"{who}, the requested time {when_txt} isn’t available. Here are recommendations for the next 7 days:"
            tail = "Please pick one of the options above or propose another time."
        else:
            head = f"{who}, waktu {when_txt} tidak tersedia. Berikut rekomendasi 7 hari ke depan:"
            tail = "Silakan pilih salah satu opsi di atas atau ajukan waktu lain."
        return "\n".join([head, "", weekly_md or "_Belum ada opsi yang cocok_", "", tail])

def render_meeting_reply_prompt(language_code: str, nick_plain: str, addr_formal: str, llm_vars: dict) -> str:
    who = (addr_formal or nick_plain or "").strip()
    when_txt = llm_vars.get("when_text","")
    weekly_md = llm_vars.get("weekly_table_md","")
    if (llm_vars.get("mode") or "").upper() == "AVAILABLE":
        if (language_code or "").lower().startswith("en"):
            return (f"You are a helpful assistant.\n"
                    f"Write a concise confirmation to the user named '{who}'.\n"
                    f"Say that the requested meeting time {when_txt} is available.\n"
                    f"Ask politely if this time works, and mention you'll confirm and send a calendar invite.")
        else:
            return (f"Anda adalah asisten yang membantu.\n"
                    f"Tuliskan konfirmasi singkat kepada '{who}'.\n"
                    f"Sebutkan bahwa waktu {when_txt} tersedia.\n"
                    f"Tanyakan apakah waktu tersebut sesuai, dan sebut Anda akan konfirmasi serta kirim undangan kalender.")
    else:
        if (language_code or "").lower().startswith("en"):
            return (f"You are a helpful assistant.\n"
                    f"Inform the user '{who}' that {when_txt} is not available.\n"
                    f"Then present the following Markdown table of alternatives for the next 7 days and ask them to pick one:\n\n{weekly_md}\n")
        else:
            return (f"Anda adalah asisten yang membantu.\n"
                    f"Beritahu '{who}' bahwa {when_txt} tidak tersedia.\n"
                    f"Lalu tampilkan tabel Markdown alternatif 7 hari ke depan berikut dan minta mereka memilih:\n\n{weekly_md}\n")

MEETING_SLOT_PARSE_SYSTEM = (
    "You normalize a single scheduling request for an Asia/Jakarta assistant. "
    "Return STRICT JSON only (no extra text)."
)

MEETING_SLOT_PARSE_HUMAN = """
Extract exactly THREE fields for searching availability in a Google Sheet.

Context:
- Timezone: Asia/Jakarta (WIB, UTC+07:00)
- TODAY_WIB = {today_wib}

Rules:
- Resolve Indonesian/English relative dates ("besok", "lusa", "minggu depan", "next Monday") to a local WIB date.
- Date format must be day_iso: "YYYY-MM-DD" (WIB local date).
- Slot label must be EXACTLY "HH:MM - HH:MM" in 24h format (no seconds, include spaces around the hyphen).
- If the user provides only date OR only time, set incomplete=true and fill missing field with null.
- DO NOT include anything else besides the three keys below.

STRICT JSON KEYS:
{{
  "day_iso": "YYYY-MM-DD or null",
  "slot_label": "HH:MM - HH:MM or null",
  "incomplete": true|false
}}

Examples (output JSON only):

User: "aku mau meeting di tanggal 24 Oktober 2025 jam 14:00 sampai 15:00 apakah bisa?"
{{
  "day_iso": "2025-10-24",
  "slot_label": "14:00 - 15:00",
  "incomplete": false
}}

User: "aku mau meeting minggu depan jam 10:00 - 11:00"
{{
  "day_iso": "<first Monday after {today_wib}>",
  "slot_label": "10:00 - 11:00",
  "incomplete": false
}}

User: "bisa hari Jumat siang?"
{{
  "day_iso": "<compute upcoming Friday date after {today_wib}>",
  "slot_label": null,
  "incomplete": true
}}
"""

def render_meeting_slot_parse_human(today_wib_iso: str) -> str:
    return MEETING_SLOT_PARSE_HUMAN.format(today_wib=today_wib_iso)

# === MICRO I18N FOR UNAVAILABLE RESPONSE (labels & headers) ===

MEETING_ALT_TEXT_PROMPT = """
You are a localization assistant.
Return ONLY JSON with the following keys in target language ({language_code}):
{{
  "lead_sentence": "After validating our schedule",
  "label_available_slots": "available slots:",
  "label_no_slots": "(—)",
  "header_unavailable": "Sorry, the schedule {{when_txt}} is not available.",
  "subheader_alternatives":
    "Here are alternative schedules available for the {n_days} working days starting from your proposed date:",
  "footer_choose": "Please pick one of the available times above."
}}
Keep {{when_txt}} placeholder unchanged. No extra text, no markdown.
"""

def render_alt_text_prompt(language_code: str, when_txt: str, n_days: int) -> str:
    return MEETING_ALT_TEXT_PROMPT.format(language_code=language_code, when_txt=when_txt, n_days=n_days)

MEETING_DATE_HEADERS_PROMPT = """
You format a list of dates into headers like "[Wednesday, 29 October 2025]" in target language ({language_code}).
Input is a JSON array of ISO dates (YYYY-MM-DD) in Asia/Jakarta.
Return ONLY JSON: {{ "headers": ["[...]", "[...]", ...] }} with the same order and length.
Do not include anything else.
Dates: {iso_dates_json}
"""

def render_date_headers_prompt(language_code: str, iso_dates_json: str) -> str:
    return MEETING_DATE_HEADERS_PROMPT.format(language_code=language_code, iso_dates_json=iso_dates_json)

MEETING_AVAILABLE_TEXT_PROMPT = """
You are a localization assistant.
Return ONLY JSON with the following keys in target language ({language_code}):
{{
  "available_intro": "The time you requested on {{when_txt}} is available.",
  "confirm_line": "If that works, I will confirm and send a calendar invite."
}}
Keep {{when_txt}} placeholder unchanged. No extra text, no markdown.
"""

def render_available_text_prompt(language_code: str, when_txt: str) -> str:
    # Hindari .format() agar brace JSON tidak diinterpretasikan sebagai placeholder.
    s = MEETING_AVAILABLE_TEXT_PROMPT
    s = s.replace("{language_code}", (language_code or "en"))
    # Biarkan placeholder double-brace di prompt, lalu turunkan ke single brace, lalu substitusi final.
    s = s.replace("{{when_txt}}", "{when_txt}")
    s = s.replace("{when_txt}", when_txt)
    return s

# === MEETING TITLE (8–10 words) ===
MEETING_TITLE_PROMPT = """
You are a meeting agenda titler.
Return ONLY one concise title in target language ({language_code}) with about 8–10 words,
derived from the following conversation summary:

---
{summary}
---

Rules:
- No quotes, no trailing period, no emojis.
- Be specific and action-oriented (verbs like: discuss, review, align, finalize).
- Avoid generic words like "meeting" unless needed.
- Max 85 characters if possible.
"""

def render_meeting_title_prompt(language_code: str, summary: str) -> str:
    return MEETING_TITLE_PROMPT.format(language_code=language_code, summary=summary or "")

# === MEETING AVAILABLE + CHECKLIST CONFIRM (i18n JSON) ===
MEETING_AVAILABLE_CONFIRM_PROMPT = """
You are a localization assistant helping to confirm a meeting slot.
Return ONLY JSON with the following keys in target language ({language_code}):

{
  "available_intro": "The time you requested on {{when_txt}} is available.",
  "confirm_header": "Please confirm the details below:",
  "label_date": "Date:",
  "label_time": "Time:",
  "label_agenda": "Agenda summary:",
  "recap_lead": "From our conversation (key points summarization):",
  "confirm_line": "If that works, I will send a calendar invite."
}

Guidelines:
- Keep {{when_txt}} placeholder unchanged.
- Translate labels only. Do NOT include any recap content.
- No extra text, no markdown.
"""

def render_available_confirm_prompt(language_code: str, when_txt: str) -> str:
    # Sama: jangan gunakan .format() pada template yang mengandung JSON braces.
    s = MEETING_AVAILABLE_CONFIRM_PROMPT
    s = s.replace("{language_code}", (language_code or "en"))
    s = s.replace("{{when_txt}}", "{when_txt}")
    s = s.replace("{when_txt}", when_txt)
    return s

# === Recap 30–40 words (language-locked) ===
def render_recap_3040_prompt(language_code: str, summary_block: str) -> str:
    """
    Recap 30–40 kata:
    - Tulis DALAM bahasa {language_code} (paksa, jangan deteksi otomatis).
    - Sorot layanan/produk Integrity yang dibahas, poin teknis/pengetahuan yang sudah dijawab,
      tujuan/keingintahuan user, dan potensi manfaat/peningkatan bisnis.
    - 1 kalimat, tanpa heading/markdown/kutipan.
    - Reformulasi; jangan menyalin "Chat Summarization:".
    """
    lang = (language_code or "id")
    return f"""
You are a professional meeting summarizer.
Write ONE sentence of 30–40 words in {lang}.

Focus on:
- Main Integrity service(s) discussed,
- Key technical/informational points provided,
- The user's goal/curiosity and the potential business/operational improvement.

No headings, no quotes, no lists, no markdown. Rephrase essentials only.

Text:
{summary_block}

Return only the sentence.
""".strip()

MEETING_CONFIRM_THANKS_PROMPT = """
You are a localization assistant.
Return ONE short polite closing message (4–5 sentences) in target language ({language_code})
to thank the user for confirming the meeting and to express positive tone.
Include these ideas:
- Thank them for confirming the schedule.
- Mention that the calendar invitation has been sent.
- Say that the specialist/team will contact them soon.
- End with a warm wish for future collaboration.
No quotes, no markdown.
"""
def render_meeting_confirm_thanks_prompt(language_code: str) -> str:
    return MEETING_CONFIRM_THANKS_PROMPT.format(language_code=language_code or "en")

# === Simple scenary meeting arrangement (agile prompt) =========================
def render_meeting_simple_prompt_agile(
    language_name: str,
    nickname: str | None = None,
    address_formal: str | None = None,
    note_constraints: str = MEETING_HANDOFF_NOTE_EN,
) -> str:
    """
    Return agile meeting prompt — universal English template that adapts to {language_name}.
    """

    prompt = f"""
You are an AI Helpful Assistant acting as a professional, persuasive, and trustworthy business consultant providing accurate and up-to-date information about Integrity’s services.
Target language: {language_name}.

The user wants to arrange a meeting. Reply briefly (1–2 sentences) in the SAME language.
Ask the user for a preferred day and a time window. All times are WIB (GMT+07).

MANDATORY NOTE (output requirement):
- Include the following note as a separate sentence in your answer, verbatim, without rephrasing:
  {note_constraints}
""".strip()

    return prompt

DEFAULT_MEETING_MAX = 500
DEFAULT_SERVICE_PICK_MAX = 500

def render_service_picker_prompt(
    *,
    language_name: str,
    language_code: str | None,
    is_first_turn: bool,
    user_nick: str | None,
    user_email: str | None,
    service_label: str | None,
    max_chars: int | None = None,
    chat_history_block: str | None = None,
    chat_summary_block: str | None = None,
) -> str:
    """
    Prompt untuk LLM agar menghasilkan 1 paragraf singkat:
    - Sapaan hangat (personalized)
    - Ajak memilih salah satu SERVICE yang tampil di UI (tanpa menyebut daftar service)
    - Bahasa mengikuti language_name
    """

    sal = _salutation_rule(
        language_name, is_first_turn, user_nick, language_code=language_code,
    )
    nick_plain, _ = _address_forms_by_language(language_code, user_nick)
    pers = _personalization_rule(language_name, language_code, user_nick)

    if max_chars is None:
        max_chars = DEFAULT_SERVICE_PICK_MAX

    _service = (service_label or "").strip()
    _email = (user_email or "").strip()

    opt_blocks = ""
    if chat_summary_block:
        opt_blocks += "\n\n" + chat_summary_block
    if chat_history_block:
        opt_blocks += "\n\n" + chat_history_block

    prompt = (
        f"{sal}\n"
        f"{pers}\n\n"
        "You are a professional, persuasive, and trustworthy business consultant.\n"
        f"Target language: {language_name}. Output MUST be in {language_name}.\n\n"
        "Goal:\n"
        "- Warmly invite the user to choose ONE service to focus on.\n"
        "- The service options are shown in the UI as multiple choice. Do NOT list any service names in your text.\n"
        "- Keep the message warm and concise.\n\n"
        "User & context:\n"
        f"- Nickname (plain): {nick_plain or ''}\n"
        f"- User email: {_email}\n"
        f"- Current/last service label (may be empty): {_service}\n\n"
        "Guidelines:\n"
        "- Output MUST be exactly 2 sentences in ONE paragraph.\n"
        "- Sentence 1: warm, personalized invitation (use nickname if available).\n"
        "- Sentence 2: ask the user to pick ONE service from the options shown in the UI (without listing any service names).\n"
        "- Do NOT add greetings like 'Selamat pagi' if this is not the first turn.\n"
        "- Do NOT use bullet points or line breaks.\n"
        "- Do NOT mention internal labels or UI technical terms.\n"
        f"{opt_blocks}\n"
    )

    try:
        return _clip(prompt, max_chars)
    except Exception:
        return prompt[:max_chars]

def _daypart_name(language_code: str | None, hour_24: int) -> str:
    """
    Return nama waktu dalam sehari berdasarkan language_code dan jam lokal 24h.
    Cakupan:
    - id : Indonesia
    - en : English
    - ms : Malay / Malaysia
    - th : Thai
    - vi : Vietnamese
    - fr : French
    - de : German
    - it : Italian
    - ro : Romanian
    - ja : Japanese
    - zh : Chinese
    - ru : Russian

    Window default:
    - 04:00–10:59
    - 11:00–14:59
    - 15:00–18:59
    - selain itu
    """
    lc = (language_code or "en").strip().lower()

    def _bucket(h: int) -> str:
        if 4 <= h < 11:
            return "morning"
        if 11 <= h < 15:
            return "midday"
        if 15 <= h < 19:
            return "evening"
        return "night"

    bucket = _bucket(int(hour_24))

    # Indonesia
    if lc.startswith("id"):
        mapping = {
            "morning": "pagi",
            "midday": "siang",
            "evening": "sore",
            "night": "malam",
        }
        return mapping[bucket]

    # English
    if lc.startswith("en"):
        mapping = {
            "morning": "morning",
            "midday": "afternoon",
            "evening": "evening",
            "night": "night",
        }
        return mapping[bucket]

    # Malay / Malaysia
    if lc.startswith("ms"):
        mapping = {
            "morning": "pagi",
            "midday": "tengah hari",
            "evening": "petang",
            "night": "malam",
        }
        return mapping[bucket]

    # Thai
    if lc.startswith("th"):
        mapping = {
            "morning": "ตอนเช้า",
            "midday": "ตอนบ่าย",
            "evening": "ตอนเย็น",
            "night": "ตอนกลางคืน",
        }
        return mapping[bucket]

    # Vietnamese
    if lc.startswith("vi"):
        mapping = {
            "morning": "buổi sáng",
            "midday": "buổi chiều",
            "evening": "buổi tối",
            "night": "ban đêm",
        }
        return mapping[bucket]

    # French
    if lc.startswith("fr"):
        mapping = {
            "morning": "matin",
            "midday": "après-midi",
            "evening": "soir",
            "night": "nuit",
        }
        return mapping[bucket]

    # German
    if lc.startswith("de"):
        mapping = {
            "morning": "Morgen",
            "midday": "Nachmittag",
            "evening": "Abend",
            "night": "Nacht",
        }
        return mapping[bucket]

    # Italian
    if lc.startswith("it"):
        mapping = {
            "morning": "mattina",
            "midday": "pomeriggio",
            "evening": "sera",
            "night": "notte",
        }
        return mapping[bucket]

    # Romanian
    if lc.startswith("ro"):
        mapping = {
            "morning": "dimineață",
            "midday": "după-amiază",
            "evening": "seară",
            "night": "noapte",
        }
        return mapping[bucket]

    # Japanese
    if lc.startswith("ja"):
        mapping = {
            "morning": "朝",
            "midday": "午後",
            "evening": "夕方",
            "night": "夜",
        }
        return mapping[bucket]

    # Chinese
    if lc.startswith("zh"):
        mapping = {
            "morning": "早上",
            "midday": "下午",
            "evening": "傍晚",
            "night": "晚上",
        }
        return mapping[bucket]

    # Russian
    if lc.startswith("ru"):
        mapping = {
            "morning": "утро",
            "midday": "день",
            "evening": "вечер",
            "night": "ночь",
        }
        return mapping[bucket]

    # fallback English
    mapping = {
        "morning": "morning",
        "midday": "afternoon",
        "evening": "evening",
        "night": "night",
    }
    return mapping[bucket]


def render_existing_meeting_warning_prompt(
    *,
    language_name: str,
    language_code: str | None,
    is_first_turn: bool,
    user_nick: str | None,
    user_email: str | None,
    service_label: str | None,
    booked_date_txt: str,
    booked_slot_txt: str,
    tz_label: str,
    current_hour_24: int,
    max_chars: int | None = None,
    chat_history_block: str | None = None,
    chat_summary_block: str | None = None,
) -> str:
    """
    Prompt untuk warning bahwa user sudah punya meeting di session ini.
    Output tetap hangat, personal, dan sesuai bahasa.
    """
    sal = _salutation_rule(
        language_name, is_first_turn, user_nick, language_code=language_code,
    )
    nick_plain, _addr_formal = _address_forms_by_language(language_code, user_nick)
    pers = _personalization_rule(language_name, language_code, user_nick)

    if max_chars is None:
        max_chars = DEFAULT_MEETING_MAX

    _service = (service_label or "").strip()
    _email = (user_email or "").strip()
    _daypart = _daypart_name(language_code, int(current_hour_24))

    opt_blocks = ""
    if chat_summary_block:
        opt_blocks += "\n\n" + chat_summary_block
    if chat_history_block:
        opt_blocks += "\n\n" + chat_history_block

    prompt = (
        f"{sal}\n"
        f"{pers}\n\n"
        "You are a professional, persuasive, and trustworthy business consultant.\n"
        f"Target language: {language_name}. Output MUST be in {language_name}.\n\n"
        "Goal:\n"
        "- Inform the user that a meeting has already been scheduled earlier in this same session.\n"
        "- Do NOT offer new meeting slots.\n"
        "- Politely invite the user to contact our team if they need changes or additional help.\n"
        "- Keep the message warm, concise, and personalized.\n\n"
        "User & context:\n"
        f"- Nickname (plain): {nick_plain or ''}\n"
        f"- User email: {_email}\n"
        # f"- Service currently being discussed: {_service}\n"
        f"- Current daypart for tone: {_daypart}\n"
        f"- Previously booked date: {booked_date_txt}\n"
        f"- Previously booked time: {booked_slot_txt}\n"
        f"- Timezone label: {tz_label}\n\n"
        "Guidelines:\n"
        "- Output MUST be exactly 2 sentences in ONE paragraph.\n"
        "- Do NOT start with a greeting such as 'Good morning', 'Good afternoon', 'Selamat pagi', 'Selamat siang', 'Selamat sore', or similar opening salutations.\n"
        "- Use the daypart naturally inside the first sentence when appropriate, for example: 'I see that you have already chosen ...' or the equivalent natural phrasing in the target language.\n"
        "- For Indonesian, prefer natural continuing-conversation phrasing such as 'Anda di pagi/siang/sore/malam ini sudah memilih jadwal meeting dengan tim kami ...' instead of starting with 'Selamat pagi/siang/sore/malam'.\n"
        "- Sentence 1: mention naturally that the user has already scheduled/chosen a meeting earlier in this same session, and include the booked date/time above.\n"
        "- Sentence 2: politely ask the user to contact our team if they want to revise the schedule, then ask what else you can help with.\n"
        "- The tone must feel like a continuing conversation, not like the very first greeting of a new chat.\n"
        "- Do NOT show additional meeting options.\n"
        "- Do NOT use bullet points or line breaks.\n"
        "- Do NOT mention internal labels or technical field names.\n"
        f"{opt_blocks}\n"
    )

    try:
        return _clip(prompt, max_chars)
    except Exception:
        return prompt[:max_chars]

MEETING_INVITE_CONFIRM_TEXT = {
    "id": "Terima kasih, saya catat jadwal {date_txt} pukul {slot_txt} ({tz_label}). Saya telah mengirim undangan meeting ke email Anda. Mohon konfirmasi.",
    "en": "Thank you, I have noted {date_txt} at {slot_txt} ({tz_label}). I have sent the meeting invitation to your email. Please confirm.",
    "ms": "Terima kasih, saya telah mencatat jadual {date_txt} pada {slot_txt} ({tz_label}). Saya telah menghantar jemputan mesyuarat ke emel anda. Sila sahkan.",
    "th": "ขอบคุณ ฉันได้บันทึกนัดหมายวันที่ {date_txt} เวลา {slot_txt} ({tz_label}) แล้ว ฉันได้ส่งคำเชิญประชุมไปยังอีเมลของคุณ กรุณายืนยัน",
    "vi": "Cảm ơn bạn, tôi đã ghi nhận lịch hẹn vào {date_txt} lúc {slot_txt} ({tz_label}). Tôi đã gửi lời mời họp đến email của bạn. Vui lòng xác nhận.",
    "fr": "Merci, j’ai bien noté le rendez-vous le {date_txt} à {slot_txt} ({tz_label}). J’ai envoyé l’invitation à la réunion à votre e-mail. Merci de confirmer.",
    "de": "Vielen Dank, ich habe den Termin am {date_txt} um {slot_txt} ({tz_label}) notiert. Ich habe die Meeting-Einladung an Ihre E-Mail gesendet. Bitte bestätigen Sie.",
    "it": "Grazie, ho preso nota dell’incontro per il {date_txt} alle {slot_txt} ({tz_label}). Ho inviato l’invito alla riunione alla tua e-mail. Ti prego di confermare.",
    "ro": "Mulțumesc, am notat întâlnirea pentru {date_txt} la {slot_txt} ({tz_label}). Am trimis invitația la întâlnire pe e-mailul dvs. Vă rog să confirmați.",
    "ru": "Спасибо, я зафиксировал встречу на {date_txt} в {slot_txt} ({tz_label}). Я отправил приглашение на встречу на вашу электронную почту. Пожалуйста, подтвердите.",
    "ja": "ありがとうございます。{date_txt} の {slot_txt}（{tz_label}）で予定を承りました。会議招待をメールでお送りしましたので、ご確認ください。",
    "zh": "感谢您，我已记录您在 {date_txt} {slot_txt}（{tz_label}）的会议安排。我已将会议邀请发送到您的电子邮箱，请确认。",
    "nl": "Dank u, ik heb de afspraak op {date_txt} om {slot_txt} ({tz_label}) genoteerd. Ik heb de vergaderuitnodiging naar uw e-mail gestuurd. Bevestig deze alstublieft.",
}

def render_meeting_invite_confirmation(language_code: str | None, date_txt: str, slot_txt: str, tz_label: str) -> str:
    lc = (language_code or "en").strip().lower()
    text = (
        MEETING_INVITE_CONFIRM_TEXT.get(lc)
        or MEETING_INVITE_CONFIRM_TEXT.get(lc.split("-")[0])
        or MEETING_INVITE_CONFIRM_TEXT["en"]
    )
    return text.format(date_txt=date_txt, slot_txt=slot_txt, tz_label=tz_label)

MEETING_INVITE_PENDING_TEXT = {
    "id": "Terima kasih, saya catat jadwal {date_txt} pukul {slot_txt} ({tz_label}). Permintaan meeting Anda sudah kami terima. Mohon tunggu email konfirmasi dari tim kami.",
    "en": "Thank you, I have noted {date_txt} at {slot_txt} ({tz_label}). We have received your meeting request. Please wait for the confirmation email from our team.",
    "ms": "Terima kasih, saya telah mencatat jadual {date_txt} pada {slot_txt} ({tz_label}). Permintaan mesyuarat anda telah kami terima. Sila tunggu e-mel pengesahan daripada pasukan kami.",
    "th": "ขอบคุณ ฉันได้บันทึกนัดหมายวันที่ {date_txt} เวลา {slot_txt} ({tz_label}) แล้ว เราได้รับคำขอประชุมของคุณแล้ว กรุณารออีเมลยืนยันจากทีมของเรา",
    "vi": "Cảm ơn bạn, tôi đã ghi nhận lịch hẹn vào {date_txt} lúc {slot_txt} ({tz_label}). Chúng tôi đã nhận được yêu cầu họp của bạn. Vui lòng chờ email xác nhận từ đội ngũ của chúng tôi.",
    "fr": "Merci, j’ai bien noté le rendez-vous le {date_txt} à {slot_txt} ({tz_label}). Nous avons bien reçu votre demande de réunion. Merci d’attendre l’e-mail de confirmation de notre équipe.",
    "de": "Vielen Dank, ich habe den Termin am {date_txt} um {slot_txt} ({tz_label}) notiert. Wir haben Ihre Meeting-Anfrage erhalten. Bitte warten Sie auf die Bestätigungs-E-Mail unseres Teams.",
    "it": "Grazie, ho preso nota dell’incontro per il {date_txt} alle {slot_txt} ({tz_label}). Abbiamo ricevuto la tua richiesta di riunione. Ti preghiamo di attendere l’e-mail di conferma dal nostro team.",
    "ro": "Mulțumesc, am notat întâlnirea pentru {date_txt} la {slot_txt} ({tz_label}). Am primit solicitarea dvs. de întâlnire. Vă rugăm să așteptați e-mailul de confirmare din partea echipei noastre.",
    "ru": "Спасибо, я зафиксировал встречу на {date_txt} в {slot_txt} ({tz_label}). Мы получили ваш запрос на встречу. Пожалуйста, дождитесь письма с подтверждением от нашей команды.",
    "ja": "ありがとうございます。{date_txt} の {slot_txt}（{tz_label}）で予定を承りました。会議リクエストは受け付けました。チームからの確認メールをお待ちください。",
    "zh": "感谢您，我已记录您在 {date_txt} {slot_txt}（{tz_label}）的会议安排。我们已收到您的会议请求，请等待团队发送的确认邮件。",
    "nl": "Dank u, ik heb de afspraak op {date_txt} om {slot_txt} ({tz_label}) genoteerd. We hebben uw vergaderverzoek ontvangen. Wacht alstublieft op de bevestigingsmail van ons team.",
}

def render_meeting_invite_pending(
    *,
    language_code: str | None,
    date_txt: str,
    slot_txt: str,
    tz_label: str,
) -> str:
    lc = (language_code or "en").strip().lower()
    text = (
        MEETING_INVITE_PENDING_TEXT.get(lc)
        or MEETING_INVITE_PENDING_TEXT.get(lc.split("-")[0])
        or MEETING_INVITE_PENDING_TEXT["en"]
    )
    return text.format(date_txt=date_txt, slot_txt=slot_txt, tz_label=tz_label)