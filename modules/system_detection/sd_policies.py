# system_detection/sd_policies.py
import os, re, math, langid, pycountry
from functools import lru_cache

# ===== LLM-based language detection =====
from langchain_anthropic import ChatAnthropic
from core.app_config import Config
cfg = Config()

# Ambil chain builder + schema dari sd_prompts (prompt disatukan di sana)
from .sd_prompts import build_language_detect_chain, LanguageDetectSchema

# ---------- Auth ----------
def validate_auth(website_id: str, api_key: str):
    if os.getenv("AUTH_BYPASS", "true").lower() in ("1", "true", "yes"):
        return True, "bypass"
    expect_site = os.getenv("API_WEBSITE_ID")
    expect_key  = os.getenv("API_USER_KEY")
    if not expect_site or not expect_key:
        return False, "server_missing_api_credentials"
    if website_id != expect_site:
        return False, "invalid_website_id"
    if api_key != expect_key:
        return False, "invalid_api_key"
    return True, "ok"

# ---------- Retrieval / Routing ----------
RETRIEVAL_K = int(os.getenv("RETRIEVAL_K", "4"))
DOCS_THRESHOLD = int(os.getenv("DOCS_THRESHOLD", "1"))  # >1 → incontext, else outcontext

# ---------- Greeting Regex (multi-language) ----------
GREETING_REGEX = re.compile(
    r"""(?xi)
    ^\s*
    (
      hi+|hello+|hey+|heya|hiya|howdy|
      halo+|hallo+|hai+|hei+|
      selamat\s+(pagi|siang|sore|malam)|
      ass?alam[uo]?(?:'|`)?alaikum|salam|السلام\s?عليكم|
      bonjour|bonsoir|salut|coucou|
      hola|buen(?:os|as)\s+(?:dias|d[ií]as|tardes|noches)|
      ol[aá]|oi|bom\s+(?:dia|tarde|noite)|
      hallo|guten\s+(?:morgen|tag|abend)|servus|moin|gr[üu]ß\s*gott|
      привет|privet|здрав(?:с|ств)уй(те)?|добр(?:ое|ого)\s*(?:утро|день|вечер)|
      مرحب(?:ا|ه)|أهلاً(?:\s*وسهلاً)?|
      你(?:好|们好)|您(?:好)|早上好|早安|晚上好|嗨|ni\s*hao|
      こんにちは|こんばんは|おはよう(?:ございます)?|もしもし|
      안녕(?:하세요|하십니까)?|여보세요|annyeong(?:haseyo)?|
      สวัสดี(?:ครับ|ค่ะ)?|sawasdee|
      xin\s*ch[aà]o|ch[aà]o(?:\s+(?:b[uư]ổi\s+(?:s[aá]ng|tr[uư]a|t[oố]i)|b[aạ]n|anh|ch[iị]|em))?
    )
    [\s!,.…]*$
    """,
)

# salam di awal baris, tidak dipaksa sampai akhir (boleh ada 2–6 kata lanjutan)
GREETING_START = re.compile(
    r"""(?xi)
    ^\s*
    ( bonjour|bonsoir|salut|coucou|
      hola|buen(?:os|as)\s+(?:dias|d[ií]as|tardes|noches)|
      hi+|hello+|hey+|heya|hiya|howdy|
      halo+|hallo+|hai+|hei+|
      selamat\s+(pagi|siang|sore|malam)|
      ass?alam[uo]?(?:'|`)?alaikum|salam|
      ol[aá]|oi|bom\s+(?:dia|tarde|noite)
    )
    \b
    """,
)

# NOTE: `GREETING_LANG_HINTS` (regex prefix shortcut yang return bahasa
# tanpa Claude detection) dihapus 2026-05-07. Bypass tersebut mismatch
# untuk input campur (mis. "Halo, can you help me with X?" → tag id padahal
# konten English). Kebijakan: setiap input → Claude detection per-turn untuk
# akurasi. See feedback_language_detection memory.

def is_greeting(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) <= 3:
        return True
    # 1) pure greeting (hanya salam) – regex lama, di-anchored ^...$
    if GREETING_REGEX.search(t):
        return True
    # 2) salam di awal + kalimat pendek (≤6 token) → tetap greeting
    if GREETING_START.search(t):
        if len(t.split()) <= int(os.getenv("GREETING_MAX_TOKENS", "6")):
            return True
    # 3) fallback: pesan sangat pendek tanpa tanda tanya
    if len(t.split()) <= 3 and "?" not in t and not any(ch.isdigit() for ch in t):
        return True
    return False

SELF_INTRO_KEYWORDS = {
    # English
    # "en": [
    #     "i am", "i'm", "my name is", "this is",
    #     "i am from", "i work at", "i work for"
    # ],
    "en": [
        "i am from", "i work at", "i work for"
    ],

    # Indonesian
    # "id": [
    #     "saya", "nama saya", "aku", "saya dari",
    #     "kami dari", "saya bekerja di"
    # ],
    "id": [
        "saya dari", "kami dari", "saya bekerja di"
    ],

    # Malay
    # "ms": [
    #     "saya", "nama saya", "saya dari",
    #     "kami dari", "saya bekerja di"
    # ],
    "ms": [
        "saya dari", "kami dari", "saya bekerja di"
    ],

    # # Vietnamese
    # "vi": [
    #     "tôi là", "tên tôi là", "tôi đến từ",
    #     "chúng tôi từ", "tôi làm việc tại"
    # ],

    # # French
    # # "fr": [
    # #     "je suis", "je m'appelle", "nous sommes de",
    # #     "je travaille chez", "je viens de"
    # # ],
    # "fr": [
    #     "nous sommes de", "je travaille chez", "je viens de"
    # ],

    # # German
    # "de": [
    #     "ich bin", "mein name ist", "ich komme aus",
    #     "ich arbeite bei"
    # ],

    # # Italian
    # "it": [
    #     "sono", "mi chiamo", "vengo da",
    #     "lavoro presso"
    # ],

    # # Spanish
    # "es": [
    #     "soy", "me llamo", "vengo de",
    #     "trabajo en"
    # ],

    # # Portuguese
    # "pt": [
    #     "sou", "meu nome é", "venho de",
    #     "trabalho na"
    # ],

    # # Russian
    # "ru": [
    #     "я", "меня зовут", "я из",
    #     "я работаю в"
    # ],

    # # Japanese
    # "ja": [
    #     "私は", "わたしは", "私の名前は"
    # ],

    # # Chinese
    # "zh": [
    #     "我是", "我叫", "来自"
    # ],

    # # Thai
    # "th": [
    #     "ผมคือ", "ฉันคือ", "ชื่อของฉัน", "ผมมาจาก"
    # ],
}

SELF_INTRO_RX = re.compile(
    r"""(?ix)
    \b(
        i\s*am|my\s+name\s+is|this\s+is|
        nama\s+saya|kami\s+dari|
        saya\s+dari|saya\s+bekerja\s+di|
        ich\s+bin|mein\s+name\s+ist|
        sono|mi\s+chiamo|
        soy|me\s+llamo|
        sou|meu\s+nome\s+é|
        tôi\s+là|tên\s+tôi\s+là
    )\b
    """
)

def is_self_introduction(text: str) -> bool:
    if not text:
        return False

    t = text.lower().strip()

    # Regex check (Latin languages)
    if SELF_INTRO_RX.search(t):
        return True

    # Keyword fallback (multilingual)
    for words in SELF_INTRO_KEYWORDS.values():
        for w in words:
            if w in t:
                return True

    return False

# ---- Meeting command triggers (multilang, aliases, emoji) ----
# Memicu HANYA jika isi pesan adalah perintah/alias + optional args (tanggal/jam, dll.)
MEETING_COMMAND_RX = re.compile(
    r"""
    ^\s*
    (?:
        # 1) Emoji kalender sebagai command eksplisit
        (?P<emoji>📅|🗓️)
        (?:\s*(?P<args_emoji>[:\-]\s*.*))?
      |
        # 2) Slash/bang command + alias lintas bahasa
        (?P<prefix>[\/!#])?\s*
        (?P<cmd>
            # --- EN ---
            m|meet|mtg|appt|meeting
            # --- Indonesian (ID) ---
            |jadwal|jadwalin|temu|janji(?:_|\s*)temu|rapat
            # --- Malay (MS) ---
            |temujanji|mesyuarat|janji(?:_|\s*)temu
            # --- French (FR) ---
            |rdv|reunion|réunion|rendez(?:\-|\s*)vous
            # --- Thai (TH) ---
            |นัด|นัดหมาย|ประชุม|ตาราง
            # --- German (DE) ---
            |termin|besprechung|sitzung
            # --- Russian (RU) ---
            |встреча|совещание|митинг
        )
        (?:\s*(?P<args_cmd>[:\-]\s*.*))?
    )
    \s*$
    """,
    re.IGNORECASE | re.UNICODE | re.VERBOSE,
)

# Pemetaan alias -> normalisasi (supaya pipeline downstream konsisten)
_MEETING_CMD_CANON = {
    # EN
    "m": "meeting", "meet": "meeting", "mtg": "meeting", "appt": "meeting", "meeting": "meeting",
    # ID
    "jadwal": "meeting", "jadwalin": "meeting", "temu": "meeting",
    "janji temu": "meeting", "janji_temu": "meeting", "rapat": "meeting",
    # MS
    "temujanji": "meeting", "mesyuarat": "meeting", "janji temu": "meeting",
    # FR
    "rdv": "meeting", "reunion": "meeting", "réunion": "meeting", "rendez-vous": "meeting", "rendez vous": "meeting",
    # TH (dipetakan per huruf apa adanya)
    "นัด": "meeting", "นัดหมาย": "meeting", "ประชุม": "meeting", "ตาราง": "meeting",
    # DE
    "termin": "meeting", "besprechung": "meeting", "sitzung": "meeting",
    # RU
    "встреча": "meeting", "совещание": "meeting", "митинг": "meeting",
    # Emoji
    "📅": "meeting", "🗓️": "meeting",
}

MEETING_KEYWORDS_RX = re.compile(
    r"""
    # verbose, case-insensitive

    # --- EN general ---
    (?:\bmeet(?:ing|up)?\b |
       \bschedul(?:e|ing)\b |
       \breschedul(?:e|ing)\b |
       \bappoint(?:ment)?\b | \bappt\b | \bmtg\b |
       \bbook(?:ing)?\s+(?:a\s+)?(?:meeting|call|slot)\b |
       \bset\s*(?:up|ting)?\s+(?:a\s+)?(?:meeting|call)\b |
       \barrang(?:e|ement)\s+(?:a\s+)?(?:meeting|call)\b |
       \bavailability\b | \bavailable\s+slot(?:s)?\b | \btime\s*slot(?:s)?\b |
       \bcalendar\s*(?:inv(?:ite)?|slot|hold)?\b |
       \b(catch\s*up)\s*(?:call|meeting)?\b |
       \bvideo\s*call\b | \bzoom\b | \bgoogle\s*meet\b | \bteams\b)

    |

    # --- Indonesian (ID) ---
    (?:\bjadwal(?:kan|in)?\b | \bpenjadwalan\b |
       \bjanji\s*temu\b | \btemu\s*janji\b |
       \bpertemuan\b | \brapat\b | \bdiskusi\b | \bkonsultasi\b |
       \batur(?:in)?\s*(?:temu|jadwal|rapat)\b |
       \bketemu\b |
       \bketersediaan\s*waktu\b | \bwaktu\s*luang\b |
       \bslot\s*(?:kosong|available)\b | \bpilih\s*waktu\b | \bambil\s*slot\b |
       \bubah\s*jadwal\b | \bpindah\s*jadwal\b | \bre?schedule\b)

    |

    # --- Malay (MS) ---
    (?:\btemu\s*janji\b | \btemujanji\b |
       \btetapkan\s*(?:pertemuan|mesyuarat)\b | \bmesyuarat\b |
       \batur\s*(?:temu|jadual)\b | \bjadual(?:kan)?\b |
       \bslot\s*kosong\b | \bketersediaan\b | \bmasa\s*lapang\b |
       \bpindah\s*jadual\b)

    |

    # --- French (FR) ---
    (?:\brendez[-\s]?vous\b | \brdv\b |
       \bréunion\b | \breunion\b | \bentretien\b |
       \bprise\s+de\s+rdv\b |
       \bfixer\s+un\s+rdv\b | \bplanifier\b | \breplanifier\b |
       \bdéplacer\s+le\s+rdv\b | \bdeplacer\s+le\s+rdv\b |
       \bdisponibilités?\b |
       \bcréneau[x]?\b | \bcreneau[x]?\b |
       \bappel\b | \bvisio(?:conférence)?\b | \bvisioconference\b)

    |

    # --- Thai (TH) ---   (tanpa \b: Thai tidak pakai word boundaries standar)
    (?:นัดหมาย|นัดคุย|นัด|
       ประชุม|
       จัด\s*ตาราง|ตาราง(?:นัด)?|กำหนดเวลา|
       จอง(?:เวลา)?|
       วิดีโอคอล|วีดีโอคอล|ซูม|กูเกิล\s*มีต|ทีมส์|
       เลื่อน(?:นัด|เวลา)|เปลี่ยน(?:เวลา|ตาราง)|
       ว่าง|คิวว่าง|ช่วงเวลา)

    |

    # --- German (DE) ---
    (?:\btermin(?:vereinbarung|findung|buchung|planung)?\b |
       \b(besprechung|meeting|sitzung)\b |
       \bverabred(?:en|ung)\b | \bvereinbar(?:en|ung)\b |
       \bverschieb(?:en|ung)\b | \bumplan(?:en|ung)\b | \bneu\s*terminieren\b |
       \bverf(?:ü|u)gbarkeiten?\b | \bfreie\s*(?:termine|zeitfenster)\b | \bzeitfenster\b |
       \bkalender(?:\s*einladung)?\b |
       \bvideo(?:call|anruf)\b | \bzoom\b | \bgoogle\s*meet\b | \bteams\b)

    |

    # --- Russian (RU) ---
    (?:\bвстреч[аиуы]\b |
       \bсовещани[ея]\b |
       \bмитинг\b |
       \bназначить\s+встречу\b | \bдоговорит(?:ь|ься|ся)?\s+о\s+встрече\b | \bзапланировать\b |
       \bрасписани[ея]\b |
       \bперенест(?:и|ь)\s+встречу\b | \bперепланиров(?:ка|ать)\b |
       \bдоступност[ьи]\b |
       \bсвободн(?:ое|ые)\s*(?:врем(?:я|ени)|слоты?|окн(?:о|а))\b |
       \bкалендар[ья]\b | \bприглашени[ея]\b |
       \bвидео(?:звонок|колл)\b | \bzoom\b | \bgoogle\s*meet\b | \bteams\b)

    |

    # --- Italian (IT) ---
    (?:\bappuntament[oi]\b |
       \briunion(?:e|i)\b | \bincontr[oi]\b |
       \bpianific(?:are|azione)\b | \bprogramm(?:are|azione)\b |
       \bprenot(?:are|azione)\b | \bfiss(?:are)?\s+(?:un\s+)?appuntament[oi]\b |
       \bdisponibilit(?:à|a)\b | \bfasci[ae]\s*orar(?:ia|ie)\b | \borar(?:io|i)\s*liber[oi]\b |
       \bslot\s*disponibil[i]\b | \binvito\s*calendario\b | \bcalendario\b |
       \bspost(?:are|amento)\b | \bripianific(?:are|azione)\b | \briprogramm(?:are|azione)\b |
       \bvideochiamata\b | \bzoom\b | \bgoogle\s*meet\b | \bteams\b)

    |

    # --- Romansh (RM) ---
    (?:\bappuntament\b |
       \bscuntranz[ae]\b | \binscuntrar\b |
       \btermin\b |
       \bplanis(?:ar|aziun)\b | \bprogram(?:mar|maziun)\b |
       \bdisponibilitad\b |
       \bspust(?:ar|ament)\b |
       \binvitaziun\b | \b(?:chalender|calender)\b |
       \bzoom\b | \bgoogle\s*meet\b | \bteams\b)
    """,
    re.UNICODE | re.IGNORECASE | re.VERBOSE,
)

def parse_meeting_command(text: str):
    """
    Return:
      (is_command: bool, data: dict|None)
    data fields (saat is_command=True):
      - trigger_type: "emoji" | "command"
      - cmd_raw: string yang ditangkap (emoji atau alias)
      - cmd_normalized: "meeting"
      - args: string setelah ':' atau '-' (bila ada), sdh strip()
    """
    if not text:
        return False, None

    m = MEETING_COMMAND_RX.search(text)
    if not m:
        return False, None

    # emoji branch
    emoji = m.group("emoji")
    if emoji:
        args = (m.group("args_emoji") or "").lstrip(":-").strip()
        return True, {
            "trigger_type": "emoji",
            "cmd_raw": emoji,
            "cmd_normalized": _MEETING_CMD_CANON.get(emoji, "meeting"),
            "args": args,
        }

    # command branch
    cmd_raw = (m.group("cmd") or "").strip()
    # Normalisasi key untuk FR (rendez vous / rendez-vous) & ID (janji_temu)
    cmd_key = cmd_raw.lower()
    if cmd_key in ("rendez-vous", "rendez – vous", "rendez –vous", "rendez–vous", "rendez – vos"):  # variasi strip
        cmd_key = "rendez-vous"
    elif cmd_key in ("rendez vous", "rendez  vous"):
        cmd_key = "rendez vous"
    elif cmd_key in ("janji_temu",):
        cmd_key = "janji temu"

    cmd_norm = _MEETING_CMD_CANON.get(cmd_key, "meeting")
    args = (m.group("args_cmd") or "").lstrip(":-").strip()

    return True, {
        "trigger_type": "command",
        "cmd_raw": cmd_raw,
        "cmd_normalized": cmd_norm,
        "args": args,
    }

def detect_meeting_intent(text: str) -> tuple[bool, str]:
    """
    Return (is_meeting, reason) where reason ∈ {"command","keyword","none"}.
    - "command": pesan hanya "m", "/m", "/meeting" (sangat eksplisit)
    - "keyword": ada kata kunci meeting/scheduling lintas bahasa
    """
    t = (text or "").strip()
    if not t:
        return False, "none"
    if MEETING_COMMAND_RX.search(t):
        return True, "command"
    if MEETING_KEYWORDS_RX.search(t):
        return True, "keyword"
    return False, "none"

# ---------- Language meta (BCP-47-lite) ----------
LANG_CANON = {"in": "id", "iw": "he", "ji": "yi", "jw": "jv", "zsm": "ms"}

@lru_cache
def _english_lang_name(code: str) -> str:
    c = code.lower()
    rec = pycountry.languages.get(alpha_2=c) or pycountry.languages.get(alpha_3=c)
    if rec and getattr(rec, "name", None):
        return rec.name.replace(" (macrolanguage)", "")
    return {"id": "Indonesian", "ms": "Malay", "jv": "Javanese", "zh": "Chinese"}.get(c, "English")

@lru_cache
def _endonym(code: str) -> str:
    endonyms = {
        "id": "Indonesia", "en": "English", "ms": "Melayu", "zh": "中文",
        "ja": "日本語", "ko": "한국어", "th": "ไทย", "vi": "Tiếng Việt",
        "fr": "Français", "de": "Deutsch", "es": "Español", "pt": "Português",
        "ru": "Русский", "ar": "العربية"
    }
    return endonyms.get(code.lower(), _english_lang_name(code))

def _detect_language_langid(text: str) -> tuple[str, float]:
    """
    Langid-based detection returning (code, confidence 0..1).
    Confidence is estimated from the probability gap between the
    best and second-best predictions.
    """
    t = (text or "").strip()
    if not t:
        return "en", 1.0
    try:
        ranked = langid.rank(t)
    except Exception:
        ranked = []
    if not ranked:
        try:
            ranked = [langid.classify(t)]
        except Exception:
            return "en", 1.0
    best_code, best_logprob = ranked[0]
    if len(ranked) > 1:
        second_logprob = ranked[1][1]
        try:
            gap = second_logprob - best_logprob
            conf = 1.0 / (1.0 + math.exp(gap))
        except Exception:
            conf = 0.7
    else:
        conf = 1.0
    best_code = LANG_CANON.get(best_code, best_code)
    conf = max(0.0, min(1.0, conf))
    return best_code or "en", conf

def _detect_language_llm(text: str) -> tuple[str, str, float]:
    """
    Pakai Claude (Anthropic) untuk deteksi bahasa.
    Return: (code, endonym_name, confidence)
    Exception-safe: kalau error → raise ke caller (biar caller yang fallback).
    """
    import time as _time
    from core.app_audit import record_llm_call

    llm = ChatAnthropic(
        model=os.getenv("LANGUAGE_LLM_MODEL", cfg.ANTHROPIC_MODEL),
        anthropic_api_key=cfg.ANTHROPIC_API_KEY,
        max_tokens=int(os.getenv("LANGUAGE_LLM_MAX_TOKENS", "64")),
        temperature=0.0,
    )
    chain = build_language_detect_chain(llm)
    t0 = _time.perf_counter()
    res: LanguageDetectSchema = chain.invoke({"user_text": text})
    latency_ms = int((_time.perf_counter() - t0) * 1000)
    code = (res.code or "en").strip().lower()
    code = LANG_CANON.get(code, code)
    name = (res.name or "").strip() or _endonym(code)
    conf = float(res.confidence or 0.5)

    record_llm_call(
        route="system_detection",
        stage="language_detect",
        session_id="",
        token_id=None,
        prompt=text,
        response=f"code={code} name={name} conf={conf}",
        model=os.getenv("LANGUAGE_LLM_MODEL", cfg.ANTHROPIC_MODEL),
        latency_ms=latency_ms,
        input_tokens=0,
        output_tokens=0,
        extras={"confidence": conf, "structured_output": True},
    )
    return code, name, conf

def detect_language_with_confidence(text: str) -> tuple[str, str, float]:
    """Canonical language-detection primitive — returns (code, name, confidence).

    Per spec §1.1 Step 1 + memory `feedback_language_detection` policy
    (2026-05-07): per-turn fresh Claude call, no cache.

    Detector mode (`LANGUAGE_DETECTOR` env):
    - `claude` (default) — Claude only; langid hard-fallback on Claude error
    - `ensemble`         — Claude + langid hybrid (legacy)
    - `langid`           — langid only

    Confidence semantics:
    - Empty text → ("en", endonym, 1.0)
    - Claude-mode success → ("<code>", "<name>", llm_confidence)
    - Claude-mode error → langid fallback → ("<code>", endonym, langid_confidence)
    - Ensemble mode: confidence reflects whichever detector won the policy decision
    - Langid mode: langid_confidence directly

    Used by `OOCService.handle()` orchestrator (Task 11+) to enforce
    OOC_LANG_DETECTION_FLOOR per spec §1.1 Step 2 fallback gating.
    """
    t = text or ""
    stripped = t.strip()

    detector_mode = (os.getenv("LANGUAGE_DETECTOR", "claude") or "claude").lower()
    conf_min = float(os.getenv("LANGUAGE_CONFIDENCE_MIN", "0.85"))

    if not stripped:
        # Empty / whitespace-only input → degenerate path. conf=1.0 is a sentinel,
        # NOT a real confidence (no detection actually ran). In practice the
        # orchestrator never reaches here for user-facing messages because the
        # OOC_MIN_TEXT_LEN=3 gate (or upstream message-validation) filters short
        # inputs first. Keeping conf=1.0 instead of 0.0 means callers that read
        # the value without context don't accidentally trigger the
        # OOC_LANG_DETECTION_FLOOR fallback for an empty-text edge case.
        return "en", _endonym("en"), 1.0

    # === CLAUDE ONLY MODE ===
    if detector_mode == "claude":
        try:
            code_llm, name_llm, conf_llm = _detect_language_llm(stripped)
            if code_llm:
                return code_llm, name_llm or _endonym(code_llm), conf_llm
        except Exception:
            # hard fallback only kalau Claude gagal total
            code_langid, conf_langid = _detect_language_langid(stripped)
            return code_langid, _endonym(code_langid), conf_langid

        # safety fallback (Claude returned empty code)
        code_langid, conf_langid = _detect_language_langid(stripped)
        return code_langid, _endonym(code_langid), conf_langid

    # === legacy ensemble / langid modes ===
    use_llm = os.getenv("LLM_LANG_VALIDATION", "1") in ("1", "true", "yes")
    min_chars = int(os.getenv("LANGUAGE_MIN_CHARS", "1"))
    langid_conf_fallback = float(os.getenv("LANGUAGE_LANGID_CONF_MIN", "0.55"))

    code_llm, name_llm, conf_llm = None, None, 0.0
    code_langid, conf_langid = _detect_language_langid(stripped)

    if use_llm and detector_mode in ("ensemble",) and len(stripped) >= min_chars:
        try:
            code_llm, name_llm, conf_llm = _detect_language_llm(stripped)
        except Exception:
            code_llm, name_llm, conf_llm = None, None, 0.0

    if detector_mode == "langid":
        return code_langid, _endonym(code_langid), conf_langid

    # ensemble policy
    if detector_mode == "ensemble" and code_llm:
        llm_strong = (len(stripped) >= min_chars and conf_llm >= conf_min)
        langid_weak = conf_langid < langid_conf_fallback or code_langid in ("und", "xx")
        english_override = code_langid == "en" and conf_langid < 0.75 and code_llm != "en"
        if llm_strong or langid_weak or english_override:
            return code_llm, name_llm or _endonym(code_llm), conf_llm

    return code_langid, _endonym(code_langid), conf_langid


def build_language_meta(text: str):
    """Backward-compat wrapper around `detect_language_with_confidence`.

    Returns `(code, name)` to preserve the original signature; drops the
    confidence value. Existing callers continue to work without modification.
    For OOC orchestrator (Task 11+) use `detect_language_with_confidence`
    directly to get the confidence value.
    """
    code, name, _conf = detect_language_with_confidence(text)
    return code, name
