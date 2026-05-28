import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

import json
from google.oauth2.service_account import Credentials


# Project root = folder yang berisi "core/", "modules/", "secrets/", dst.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ".env"

# Muat secrets/.env kalau ada (tidak error kalau tak ada)
load_dotenv(dotenv_path=ENV_FILE, override=True)
def _clean(s: str) -> str:
    return s.strip().strip('"').strip("'")

def _parse_trusted_hosts(raw: str | None) -> tuple[str, ...] | None:
    value = (raw or "").strip()
    if not value or value == "*":
        return None
    if value.lower() in {"off", "none", "disable", "disabled"}:
        return None
    items = tuple(part.strip() for part in value.split(",") if part.strip())
    return items or None

# Validate enum-typed env knobs at module load. Unknown values are operator
# errors — fail loudly at startup rather than silently fall back.
_VALID_QUALIFICATION_METHODS = {"two_decision_tree", "natural_qualification"}
_q_method = os.getenv("QUALIFICATION_METHOD", "two_decision_tree").strip().lower()
if _q_method not in _VALID_QUALIFICATION_METHODS:
    raise SystemExit(
        f"QUALIFICATION_METHOD={_q_method!r} is not a valid value. "
        f"Allowed: {sorted(_VALID_QUALIFICATION_METHODS)}. "
        f"Set QUALIFICATION_METHOD=two_decision_tree (default) or "
        f"QUALIFICATION_METHOD=natural_qualification in .env."
    )

@dataclass
class Config:
    # === Google Sheets & Service Account ===
    SHEET_ID: str = os.getenv("SHEET_ID", "")
    # Path kredensial: jika ENV kosong, default ke secrets/sa.json
    # CREDS_PATH: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", str(SECRETS_DIR / "sa.json"))
    CREDS_PATH: str = os.getenv("GOOGLE_SERVICE_ACCOUNT", "secrets/sa.json")
    OUTPUT_TITLE: str = os.getenv("OUTPUT_TITLE", "FAQ")
    INCLUDE_SHEETS: list = tuple(
        s.strip() for s in os.getenv("INCLUDE_SHEETS", "").split(",") if s.strip()
    )
    WRAP_WIDTH: int = int(os.getenv("WRAP_WIDTH", "0"))

    GOOGLE_SERVICE_ACCOUNT = os.getenv("GOOGLE_SERVICE_ACCOUNT", "").strip()
    SA_CLIENT_EMAIL = os.getenv("SA_CLIENT_EMAIL", "").strip()  # opsional
    GOOGLE_SHEETS_SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly",
    ]

    # Definisikan PORT di setiap micro service
    PORT_TG: int = int(os.getenv("PORT_TG", "2303"))
    PORT_UI_TEST: int = int(os.getenv("PORT_UI_TEST", "2304"))
    PORT_CHATBOT: int = int(os.getenv("PORT_CHATBOT", "2305"))
    TRUSTED_HOSTS: tuple[str, ...] | None = field(
        default_factory=lambda: _parse_trusted_hosts(os.getenv("TRUSTED_HOSTS"))
    )

    # === Mongo Target ===
    MONGO_URI: str = os.getenv("MONGO_URI", "")
    MONGO_DB: str = os.getenv("MONGO_DB", "faq_automation")
    MONGO_FAQ_UPDATE: str = os.getenv("MONGO_FAQ_UPDATE", "faq_update_doc")
    FIELD_FAQ_TEXT: str = os.getenv("FIELD_FAQ_TEXT", "text")
    CHAT_HISTORY_COLL: str = os.getenv("CHAT_HISTORY_COLL", "chat_history")
    SA_HISTORY_COLL: str = os.getenv("SA_HISTORY_COLL", "qfc_service_agent")
    MAX_DOCS: int = int(os.getenv("MAX_DOCS", "1"))
    CTX_DOCS_FLOOR: int = int(os.getenv("CTX_DOCS_FLOOR", "4"))
    CTX_DOCS_SAME_SERVICE: int = int(os.getenv("CTX_DOCS_SAME_SERVICE", "4"))
    CTX_DOCS_OTHER_SERVICE: int = int(os.getenv("CTX_DOCS_OTHER_SERVICE", "2"))
    CTX_INFER_SERVICE_FROM_QUERY: bool = os.getenv("CTX_INFER_SERVICE_FROM_QUERY", "on").strip().lower() in ("1", "true", "on", "yes")
    CTX_INFER_FUZZY_RATIO: float = float(os.getenv("CTX_INFER_FUZZY_RATIO", "0.82"))
    CTX_PIN_SERVICE_DEFINITION: bool = os.getenv("CTX_PIN_SERVICE_DEFINITION", "on").strip().lower() in ("1", "true", "on", "yes")

    # Vector DB
    VECTORDB_PATH: str = os.getenv("VECTORDB_PATH", "./vector_data")
    COLLECTION_NAME: str = os.getenv("COLLECTION_NAME", "FaQ_ChromaDB_OpenAI")
    VECTOR_HARD_RESET: bool = os.getenv("VECTOR_HARD_RESET", "false").lower() in ("1","true","yes")

    # === Penjadwalan & Zona Waktu ===
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Jakarta")
    CRON_HOUR: int = int(os.getenv("CRON_HOUR", "17"))
    CRON_MINUTE: int = int(os.getenv("CRON_MINUTE", "30"))

    # === API Trigger ===
    API_KEY: str = _clean(os.getenv("API_KEY", ""))
    API_HEADER_NAME: str = os.getenv("API_HEADER_NAME", "x-api-key")
    SERVICE_AGENT_API_KEY: str = _clean(os.getenv("SERVICE_AGENT_API_KEY", ""))
    SERVICE_AGENT_API_HEADER_NAME: str = os.getenv("SERVICE_AGENT_API_HEADER_NAME", "x-service-agent-api-key")
    TRIGGER_TRUE_VALUE: str = os.getenv("TRIGGER_TRUE_VALUE", "true").strip().lower()
    WEBSITE_ID_HEADER_NAME: str = os.getenv("WEBSITE_ID_HEADER_NAME", "off")

    # === RAG defaults (bisa dipakai nanti) ===
    CHUNK_SIZE_CHARS: int = int(os.getenv("CHUNK_SIZE_CHARS", "1200"))
    CHUNK_OVERLAP_CHARS: int = int(os.getenv("CHUNK_OVERLAP_CHARS", "200"))
    # NOTE: `TOP_K` was a dead knob — never read by retrieval code. Actual
    # retrieval is governed by RETRIEVAL_K (sd_policies.py) and
    # CTX_DOCS_SAME_SERVICE / CTX_DOCS_OTHER_SERVICE below.

    PUBLIC_BASE_URL: str | None = os.getenv("PUBLIC_BASE_URL")  # contoh: https://chatbot.example.com

    # === Session & Token Generate ===
    MONGO_SESSION: str = os.getenv("MONGO_SESSION", "api_keys")

    SESSION_IDLE_WITH_HISTORY_SECONDS: int = int(
        os.getenv("SESSION_IDLE_WITH_HISTORY_SECONDS", "600")
    )
    SESSION_NO_ACTIVITY_TTL_SECONDS: int = int(
        os.getenv("SESSION_NO_ACTIVITY_TTL_SECONDS", "604800")
    )
    CHECK_INTERVAL_SECONDS: int = int(
        os.getenv("CHECK_INTERVAL_SECONDS", "60")
    )

    PORT: int = int(os.getenv("PORT", "2303"))

    TESTING_WEBSITEID: str = os.getenv("TESTING_WEBSITEID", "off")
    TESTING_APIKEY: str = os.getenv("TESTING_APIKEY", "")

    # --- DB backend selector (Postgres reserved; only mongo implemented) ---
    DB_BACKEND: str = os.getenv("DB_BACKEND", "mongo").strip().lower()

    # --- LLM / Anthropic ---
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", os.getenv("CLAUDE_API_KEY", ""))
    ANTHROPIC_MODEL: str   = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    # Per-stage model override (cost optimisation). Empty/unset = use ANTHROPIC_MODEL.
    # Recommended: claude-haiku-4-5-20251001 untuk binary classification.
    GRADER_MODEL: str      = os.getenv("GRADER_MODEL", "")
    # MAX TOKEN Consistency
    MAX_OUTPUT_TOKENS: int = int(os.getenv("MAX_OUTPUT_TOKENS", "500"))
    MAX_TOKENS_BRIEF: int = int(os.getenv("MAX_TOKENS_BRIEF", "300"))
    MAX_TOKENS_ASK: int = int(os.getenv("MAX_TOKENS_ASK", "120"))
    LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.2"))

    LANGUAGE_DETECTOR: str   = os.getenv("LANGUAGE_DETECTOR", "ensemble")

    # --- Prompt audit/store control ---
    PROMPT_STORE_MODE: str = os.getenv("PROMPT_STORE_MODE", "text")  # "text" | "messages" | "off"
    PROMPT_MAX_CHARS: int = int(os.getenv("PROMPT_MAX_CHARS", "6000"))  # batasi ukuran yang disimpan

    GOOGLE_CHAT_HISTORY = os.getenv("GOOGLE_CHAT_HISTORY", "off")
    GOOGLE_CHAT_SHEET_ID = os.getenv("GOOGLE_CHAT_SHEET_ID")
    GOOGLE_CHAT_SHEET_TAB = os.getenv("GOOGLE_CHAT_SHEET_TAB", "Chat_History_151025")

    QUERY_RECORDING_COLL: str = os.getenv("QUERY_RECORDING_COLL", "query_recording")

    # --- Prompt audit backend selection ---
    PROMPT_AUDIT_BACKEND: str = os.getenv("PROMPT_AUDIT_BACKEND", "mongo").strip().lower()
    PROMPT_AUDIT_QUEUE_SIZE: int = int(os.getenv("PROMPT_AUDIT_QUEUE_SIZE", "1024"))
    PROMPT_AUDIT_WORKERS: int = int(os.getenv("PROMPT_AUDIT_WORKERS", "1"))

    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY", ""))

    # Chat with history schema
    UTILIZER_STATUS: str = os.getenv("UTILIZER_STATUS", "local").strip().lower()
    CHAT_HISTORY_SCHEMA: str = os.getenv("CHAT_HISTORY_SCHEMA", "allsum").strip().lower()
    HISTORY_SUMMARY_MAX_CHARS: int = int(os.getenv("HISTORY_SUMMARY_MAX_CHARS", "2500"))
    HISTORY_SUMMARY_MAX_TOKENS: int = int(os.getenv("HISTORY_SUMMARY_MAX_TOKENS", "220"))
    HISTORY_SUMMARY_MAX_PAIRS: int = int(os.getenv("HISTORY_SUMMARY_MAX_PAIRS", "20"))
    INPUT_MAX_PROMPT: int = int(os.getenv("INPUT_MAX_PROMPT", os.getenv("PROMPT_MAX_CHARS", "3000")))

    # === KB backend feature flag (Stage 3A — per-service vector store) ===
    # "legacy" = single Chroma collection (pre-3A behavior)
    # "split"  = N per-service collections (target steady state)
    # "dual"   = both, per-service primary, legacy fallback (migration window)
    KB_BACKEND: str = os.getenv("KB_BACKEND", "legacy").strip().lower()
    # Fraction of retrieval calls that run BOTH backends in dual mode for
    # divergence telemetry. 0.0 = off, 1.0 = every call. Default off.
    KB_DUAL_AB_SAMPLE_RATE: float = float(os.getenv("KB_DUAL_AB_SAMPLE_RATE", "0.0"))

    # === Redundancy & answer quality (Stage 2026-05-11) ===
    # Runtime method selector. Default "mmr" — promoted from "normal" on
    # 2026-05-12 after targeted QA run showed MMR is the most effective
    # anti-repetition method (rc_count_final=11 vs 10 fuzzy/embedding vs 0
    # normal across 3-turn FAQ-RAG flow; correct recap bypass; -9% latency
    # vs normal on incontext path). Valid values: "mmr" | "fuzzy" |
    # "embedding" | "normal". "normal" remains available as the runtime
    # kill-switch (byte-identical to pre-patch).
    REDUNDANCY_METHOD: str = os.getenv("REDUNDANCY_METHOD", "mmr").strip().lower()
    # fuzzy strategy: rapidfuzz.token_set_ratio threshold on 0..1 scale.
    REDUNDANCY_FUZZY_THRESHOLD: float = float(os.getenv("REDUNDANCY_FUZZY_THRESHOLD", "0.85"))
    # embedding strategy: cosine-similarity threshold on 0..1 scale.
    REDUNDANCY_EMBEDDING_THRESHOLD: float = float(os.getenv("REDUNDANCY_EMBEDDING_THRESHOLD", "0.92"))
    # mmr strategy: lambda weight between relevance (1.0) and diversity (0.0).
    REDUNDANCY_MMR_LAMBDA: float = float(os.getenv("REDUNDANCY_MMR_LAMBDA", "0.7"))
    # mmr strategy: fetch_k = k × multiplier, the candidate pool size for diversification.
    REDUNDANCY_MMR_FETCH_K_MULTIPLIER: int = int(os.getenv("REDUNDANCY_MMR_FETCH_K_MULTIPLIER", "2"))
    # recent-chunks filter: how many turns of history to remember (× CTX_DOCS_FLOOR for total IDs).
    REDUNDANCY_RECENT_CHUNKS_WINDOW: int = int(os.getenv("REDUNDANCY_RECENT_CHUNKS_WINDOW", "5"))
    # recent-chunks filter: extra chunks to over-fetch when recent_chunk_ids non-empty.
    REDUNDANCY_RECENT_CHUNKS_SPILLOVER: int = int(os.getenv("REDUNDANCY_RECENT_CHUNKS_SPILLOVER", "2"))
    # When True, "say that again"/"ulangi"/etc bypasses the recent-chunks filter.
    REDUNDANCY_RECAP_BYPASS: bool = os.getenv("REDUNDANCY_RECAP_BYPASS", "true").strip().lower() in ("1", "true", "on", "yes")

    # === Qualification method toggle (Stage 2026-05-12) ===
    # Two options:
    #   "two_decision_tree" — DEFAULT. Existing 2-agent decision-tree flow
    #                         (intent_type + intent_interest LLMs per turn,
    #                         fixed FLOW_REGISTRY question order). Byte-identical
    #                         to pre-Stage-4 behavior — strict-additive guarantee.
    #   "natural_qualification" — New single-agent natural-conversation collector.
    #                              Same FLOW_REGISTRY fields, different journey.
    #                              Picker offered proactively when min-set collected.
    # Validated below — unknown values raise SystemExit at startup.
    QUALIFICATION_METHOD: str = os.getenv("QUALIFICATION_METHOD", "two_decision_tree").strip().lower()

    FAQ_VERIFICATOR: str = os.getenv("FAQ_VERIFICATOR", "on").strip().lower()

    # Sales slots monitoring and knowledge base
    DB_CHATBOT: str = os.getenv("DB_CHATBOT", "rag_assistant_chatbot").strip()
    PAYLOAD_CALENDAR_COL: str = os.getenv("PAYLOAD_CALENDAR_COL", "calendar_payload").strip()
    SALES_SHEET_ID: str = os.getenv("SALES_SHEET_ID", "1Kz7WIVaNBHmVEX-LeKm_EtKl9vCffkiu-U-7_YSc3XI").strip()
    SALES_SHEET_NAME: str = os.getenv("SALES_SHEET_NAME", "Sales_Slots2").strip()
    INDV_SALES_SHEET_NAME: str = os.getenv("INDV_SALES_SHEET_NAME", "Sales_Slots2_IDV").strip()
    MA_CONFIRMATION_COLL: str = os.getenv("MA_CONFIRMATION_COLL", "ma_confirmation")
    DAYS_PROPOSAL: int = int(os.getenv("DAYS_PROPOSAL", "7"))
    INDV_SHEET_TTL_SEC: int = int(os.getenv("INDV_SHEET_TTL_SEC", "60"))
    INDV_INDEX_TTL_SEC: int = int(os.getenv("INDV_INDEX_TTL_SEC", "60"))
    # Safety throttle antar request actual API (ketika cache refresh)
    SHEETS_MIN_INTERVAL: float = float(os.getenv("SHEETS_MIN_INTERVAL", "0.25"))
    BOOKED_PATH_API: str = os.getenv("BOOKED_PATH_API", "").strip()
    BEARER_TOKEN_CALENDAR_API: str = os.getenv("BEARER_TOKEN_CALENDAR_API", "").strip()

    # === Vector/KB paths (standarisasi) ===
    VECTOR_DATA_DIR: str = os.getenv("VECTOR_DATA_DIR", os.getenv("VECTORDB_PATH", "./vector_data"))
    VECTOR_CURRENT_SYMLINK: str = os.getenv("VECTOR_CURRENT_SYMLINK", str(Path(VECTOR_DATA_DIR) / "current"))
    # Koleksi/collection Chroma
    CHROMA_COLLECTION: str = os.getenv("CHROMA_COLLECTION", os.getenv("COLLECTION_NAME", "faq_kb"))
    COLLECTION_NAME: str = CHROMA_COLLECTION  # alias agar legacy code tetap hidup
    # Backend/label embedding untuk meta (label saja; pemanggilan real di code)
    VECTOR_BACKEND: str = os.getenv("VECTOR_BACKEND", "chroma").strip().lower()
    EMBED_MODEL: str = os.getenv("EMBED_MODEL", "text-embedding-3-large")
    # Registry KB
    KB_META_COLL: str = os.getenv("KB_META_COLL", "kb_registry")
    KB_NAMESPACE: str = os.getenv("KB_NAMESPACE", "faq")

    BOARD_ID = os.getenv("BOARD_ID", "").strip()
    TOPICS = os.getenv("TOPICS", "").strip()  # bisa CSV / string
    MONDAY_PATH: str = os.getenv("MONDAY_PATH", "").strip()
    MONDAY_KEY = os.getenv("MONDAY_KEY", "").strip()  
    MONDAY_VALUE = os.getenv("MONDAY_VALUE", "").strip()

    #Meeting arrangement inquiries
    SALES_EMAIL_API_BASE_URL: str = os.getenv("SALES_EMAIL_API_BASE_URL", "").strip()
    SALES_COVERAGE_PATH: str = os.getenv("SALES_COVERAGE_PATH", "").strip()
    SALES_EMAIL_API_BEARER_TOKEN: str = os.getenv("SALES_EMAIL_API_BEARER_TOKEN", "").strip()
    SALES_EMAIL_API_TIMEOUT_SECS: int = int(os.getenv("SALES_EMAIL_API_TIMEOUT_SECS", "30"))

    # Meeting user + availability API (new method)
    MEETING_API_BASE_URL: str = os.getenv("MEETING_API_BASE_URL", "").strip()
    MEETING_API_BEARER_TOKEN: str = os.getenv("MEETING_API_BEARER_TOKEN", "").strip()
    MEETING_USER_PATH: str = os.getenv("MEETING_USER_PATH", "chat/user").strip()
    MEETING_AVAILABILITY_PATH: str = os.getenv("MEETING_AVAILABILITY_PATH", "sales/availability").strip()
    MEETING_API_TIMEOUT_SECS: int = int(os.getenv("MEETING_API_TIMEOUT_SECS", "10"))
    MAX_OTHER_SLOT_PICKS: int = int(os.getenv("MAX_OTHER_SLOT_PICKS", "5"))
    ORGANIZER_EMAIL: str = os.getenv("ORGANIZER_EMAIL", "").strip()
    TIME_CHAT_BORDER: str = os.getenv("TIME_CHAT_BORDER", "15:00").strip()
    HOST_TIME_FORMAT: str = os.getenv("HOST_TIME_FORMAT", "UTC+7").strip()
    MEETING_POPUP: int = int(os.getenv("MEETING_POPUP", "0") or 0)

    # AI Chatbot Late Respond Feature
    LATE_RESPONDS_FEATURE: str = os.getenv("LATE_RESPONDS_FEATURE", "off").strip().lower()
    LATE_RESPONDS_TIME: int = int(os.getenv("LATE_RESPONDS_TIME", "1800"))
    LATE_RESPONDS_CHECK_INTERVAL: int = int(os.getenv("LATE_RESPONDS_CHECK_INTERVAL", "60"))
    LATE_RESPONDS_MAX_PER_SESSION: int = int(os.getenv("LATE_RESPONDS_MAX_PER_SESSION", "1"))
    LATE_RESPONDS_REQUIRE_CHAT_HISTORY: bool = os.getenv("LATE_RESPONDS_REQUIRE_CHAT_HISTORY", "1").strip().lower() in ("1", "true", "yes", "on")
    LATE_RESPONDS_COLL: str = os.getenv("LATE_RESPONDS_COLL", "late_response_followups").strip()

    # =========================================================================
    # OOC engine Stage 0 (2026-05-13)
    # See docs/superpowers/specs/2026-05-13-ooc-response-engine-design.md §6.3
    # =========================================================================
    OOC_AGENT_ENABLED: bool = os.getenv("OOC_AGENT_ENABLED", "on").strip().lower() in ("1", "true", "on", "yes")
    OOC_MODE: str = os.getenv("OOC_MODE", "hybrid").strip().lower()
    OOC_ESCALATION_THRESHOLD: int = int(os.getenv("OOC_ESCALATION_THRESHOLD", "3"))
    OOC_ESCALATION_SUPPRESSION_TURNS: int = int(os.getenv("OOC_ESCALATION_SUPPRESSION_TURNS", "3"))
    OOC_LLM_CONFIDENCE_FLOOR: float = float(os.getenv("OOC_LLM_CONFIDENCE_FLOOR", "0.6"))
    OOC_CATCHALL_FLOOR: float = float(os.getenv("OOC_CATCHALL_FLOOR", "0.7"))
    OOC_KEYWORD_CONFIDENCE: float = float(os.getenv("OOC_KEYWORD_CONFIDENCE", "0.95"))
    OOC_LANG_DETECTION_FLOOR: float = float(os.getenv("OOC_LANG_DETECTION_FLOOR", "0.85"))
    OOC_MIN_KEYWORD_HITS: int = int(os.getenv("OOC_MIN_KEYWORD_HITS", "1"))
    OOC_MIN_TEXT_LEN: int = int(os.getenv("OOC_MIN_TEXT_LEN", "3"))
    OOC_FREELANCER_URL: str = os.getenv("OOC_FREELANCER_URL", "https://www.acmeservices.example.com/freelancer/").strip()
    OOC_PARTNER_URL: str = os.getenv("OOC_PARTNER_URL", "https://www.acmeservices.example.com/partner/").strip()
    OOC_HIGH_STAKES_SERVICES: tuple[str, ...] = tuple(
        s.strip() for s in os.getenv(
            "OOC_HIGH_STAKES_SERVICES",
            "compliance_audit,claim_review,asset_verification,contact_verification"
        ).split(",") if s.strip()
    )
    OOC_ALLOWED_LOCALES: tuple[str, ...] = tuple(
        s.strip() for s in os.getenv("OOC_ALLOWED_LOCALES", "").split(",") if s.strip()
    )
    OOC_POSTHOC_CLASSIFIER_ENABLED: bool = os.getenv("OOC_POSTHOC_CLASSIFIER_ENABLED", "false").strip().lower() in ("1", "true", "on", "yes")
    OOC_POSTHOC_CLASSIFIER_SAMPLE_RATE: float = float(os.getenv("OOC_POSTHOC_CLASSIFIER_SAMPLE_RATE", "0.1"))
    OOC_POSTHOC_CLASSIFIER_MODE: str = os.getenv("OOC_POSTHOC_CLASSIFIER_MODE", "keyword").strip().lower()

    def build_google_credentials(self, scopes: list[str] | None = None) -> Credentials:
        """Bangun Credentials dari .env yang bisa berformat JSON inline atau path file."""
        data = self.GOOGLE_SERVICE_ACCOUNT
        sc = scopes or self.GOOGLE_SHEETS_SCOPES
        if not data:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT is empty")

        # JSON inline?
        data_str = data.strip()
        if data_str.startswith("{"):
            info = json.loads(data_str)
            # normalisasi private_key newline jika datang sebagai '\n'
            pk = info.get("private_key", "")
            if "\\n" in pk:
                info["private_key"] = pk.replace("\\n", "\n")
            return Credentials.from_service_account_info(info, scopes=sc)

        # fallback: diasumsikan path file
        return Credentials.from_service_account_file(data_str, scopes=sc)

    def validate(self):
        missing = []
        if not self.SHEET_ID: missing.append("SHEET_ID")
        if not self.MONGO_URI: missing.append("MONGO_URI")
        if not self.API_KEY: missing.append("API_KEY")
        # CREDS_PATH boleh default, tapi pastikan file ada
        from pathlib import Path
        # GOOGLE_SERVICE_ACCOUNT bisa berupa path ATAU JSON inline
        raw_sa = (self.CREDS_PATH or "").strip()
        if not raw_sa:
            missing.append("GOOGLE_SERVICE_ACCOUNT")
        else:
            if raw_sa.lstrip().startswith("{"):
                pass  # inline JSON → ok
            else:
                from pathlib import Path
                if not Path(raw_sa).exists():
                    missing.append("GOOGLE_SERVICE_ACCOUNT (file not found)")

        # (opsional) tegaskan MONGO_SESSION ada
        if not self.MONGO_SESSION:
            missing.append("MONGO_SESSION")
        if missing:
            raise RuntimeError(f"Missing/invalid env or files: {', '.join(missing)}")
        if self.SALES_EMAIL_API_BASE_URL.endswith("/"):
            self.SALES_EMAIL_API_BASE_URL = self.SALES_EMAIL_API_BASE_URL[:-1]
        if not self.SALES_COVERAGE_PATH.startswith("/"):
            self.SALES_COVERAGE_PATH = "/" + self.SALES_COVERAGE_PATH
