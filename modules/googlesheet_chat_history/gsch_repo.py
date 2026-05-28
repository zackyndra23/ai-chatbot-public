from __future__ import annotations
from typing import Sequence, Any
from .gsch_client import get_worksheet, SheetNotConfigured, get_ws_by_id_tab
from .gsch_utils import flag_enabled
from core.app_config import Config

cfg = Config()

# Urutan kolom sesuai permintaan user (tanpa duplikasi prompt_applied):
_COLS: list[str] = [
    "sessionId",
    "tokenId",
    "user_nick",
    "timestamp",
    "summary_applied",
    "prompt_applied",
    "route",
    "related_services",
    "docs_retrieved_count",
    "question",
    'language',
    "message",
    "respond_duration",
    "input_token",
    "output_token",
    "summary_input",
    "summary_output",
    "input_total",
    "output_total",
    "chat_summarization",
    "choices",
    "required",
    # === NEW (dual_agent_meta) ===
    "respond_type_prompt",     # prompt_type
    "respond_type",            # type
    "question_count",          # question_count
    "next_question",           # next_question
    "respond_type_input",      # input_token_pt
    "respond_type_output",     # output_token_pt
    "interest_prompt",         # prompt_interest
    "status_of_interest",      # interest_label
    "invalid_count",           # invalid_count
    "interest_type_input",     # input_token_pi
    "interest_type_output",    # output_token_pi  (FIX: bukan respond_type_output lagi)
    "meeting_interception",    # meeting_arrangement
]

def _ensure_header(ws) -> None:
    """
    Pastikan header persis _COLS.
    Jika header lama (tanpa 3 kolom baru), baris header akan di-update
    dan kolom-kolom baru ditambahkan di kanan. Data lama tetap aman.
    """
    first_row = ws.row_values(1)
    if first_row != _COLS:
        # pastikan jumlah kolom cukup
        ws.resize(rows=max(ws.row_count, 2), cols=max(ws.col_count, len(_COLS)))
        ws.update("A1", [_COLS])

def _coerce_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        # gabung pakai ; agar ringkas
        return "; ".join(map(_coerce_text, v))
    return str(v)

def _coerce_text2(val) -> str:
    """
    Normalize value for GoogleSheet cell.
    - None        -> ""
    - bool        -> "true" / "false"
    - int / float -> str(number)
    - str         -> str
    - others      -> str(val)
    """
    if val is None:
        return ""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        return val
    return str(val)

def _extract_message_text(message: Any) -> str:
    """
    Normalisasi kolom 'message' untuk Google Sheet:
    - Jika string -> pakai apa adanya
    - Jika dict picker -> ambil content.text
    - Jika tipe lain -> cast ke string
    """
    if message is None:
        return ""
    # case lama: string biasa
    if isinstance(message, str):
        return message
    # case baru: struktur picker
    if isinstance(message, dict):
        content = message.get("content") or {}
        text = content.get("text")
        if isinstance(text, str):
            return text
    # fallback: list/dict lain -> pakai _coerce_text
    return _coerce_text(message)

def _extract_picker_meta(message: Any) -> tuple[list[str], str]:
    # return (choices_labels, required_str)
    if not isinstance(message, dict):
        return ([], "")
    if message.get("type") != "picker":
        return ([], "")
    content = message.get("content") or {}
    req = content.get("required")
    choices = content.get("choices") or []
    labels = []
    for c in choices:
        if isinstance(c, dict) and c.get("label"):
            labels.append(str(c["label"]))
    return (labels, str(bool(req)) if req is not None else "")

def append_chat_history_row(
    session_id: str,
    token_id: str | None,
    user_nick: str | None,
    timestamp_iso: str,
    summary_applied: str | None,
    prompt_applied: str | None,
    route: str | None,
    related_services: Sequence[str] | None,
    docs_retrieved_count: int | None,
    question: str | None,
    language_name: str | None,
    message,
    respond_duration: float | int | None = None,
    input_token: int | None = None,
    output_token: int | None = None,
    summary_input: int | None = None,            
    summary_output: int | None = None,   
    input_total: int | None = None,
    output_total: int | None = None,        
    chat_summarization: str | None = None,
    choices: Sequence[str] | None = None,
    required: bool | None = None,
    dual_agent_meta: dict | None = None,    
) -> bool:
    """
    Tulis satu baris ke Google Sheet sesuai _COLS.
    Jangan lempar error ke caller: return False jika gagal.
    """
    if not flag_enabled():
        print("[GSH] GOOGLE_CHAT_HISTORY=off (flag_enabled False)")
        return False
    try:
        ws = get_worksheet()
        _ensure_header(ws)

        # Normalisasi message -> selalu teks murni
        message_text = _extract_message_text(message)

        # Hitung total token (LLM utama + summarization) HANYA jika belum dikirim
        if input_total is None:
            input_total = (input_token or 0) + (summary_input or 0)
        if output_total is None:
            output_total = (output_token or 0) + (summary_output or 0)

        choices_labels, required_str = _extract_picker_meta(message if isinstance(message, dict) else None)

        da = dual_agent_meta or {}

        respond_type_prompt   = _coerce_text2(da.get("prompt_type"))
        respond_type          = _coerce_text2(da.get("type"))
        question_count        = _coerce_text2(da.get("question_count"))
        next_question         = _coerce_text2(da.get("next_question"))

        respond_type_input    = _coerce_text2(da.get("input_token_pt"))
        respond_type_output   = _coerce_text2(da.get("output_token_pt"))

        interest_prompt       = _coerce_text2(da.get("prompt_interest"))
        status_of_interest    = _coerce_text2(da.get("interest_label"))
        invalid_count         = _coerce_text2(da.get("invalid_count"))

        interest_type_input   = _coerce_text2(da.get("input_token_pi"))
        interest_type_output  = _coerce_text2(da.get("output_token_pi"))

        meeting_interception  = _coerce_text2(da.get("meeting_arrangement"))

        row = [
            _coerce_text(session_id),
            _coerce_text(token_id or session_id),
            _coerce_text(user_nick),
            _coerce_text(timestamp_iso),
            _coerce_text(summary_applied),
            _coerce_text(prompt_applied),
            _coerce_text(route),
            _coerce_text(related_services or []),
            _coerce_text(docs_retrieved_count if docs_retrieved_count is not None else 0),
            _coerce_text(question),
            _coerce_text(language_name),
            _coerce_text(message_text),   # 🔹 pakai teks yang sudah diextract
            _coerce_text(f"{float(respond_duration):.3f}" if respond_duration is not None else ""),
            _coerce_text(int(input_token) if input_token is not None else ""),
            _coerce_text(int(output_token) if output_token is not None else ""),
            _coerce_text(int(summary_input) if summary_input is not None else ""),
            _coerce_text(int(summary_output) if summary_output is not None else ""),
            _coerce_text(int(input_total) if input_total is not None else ""),
            _coerce_text(int(output_total) if output_total is not None else ""),
            _coerce_text(chat_summarization or "-"),
            _coerce_text(choices_labels),
            _coerce_text(required_str),

            # NEW dual_agent_meta columns
            respond_type_prompt,
            respond_type,
            question_count,
            next_question,
            respond_type_input,
            respond_type_output,
            interest_prompt,
            status_of_interest,
            invalid_count,
            interest_type_input,
            interest_type_output,
            meeting_interception,
        ]
        # append di bawah header; gunakan value_input_option RAW agar tidak di-parse
        ws.append_row(row, value_input_option="RAW")
        # print("[GSH] append_row OK")
        return True
    except SheetNotConfigured as e:
        print(f"[GSH] SheetNotConfigured: {e}")
        return False
    except Exception as e:
        print(f"[GSH] append_row failed: {e}")
        return False

def get_range_values(spreadsheet_id: str, range_a1: str) -> list[list[str]]:
    """
    Baca nilai dalam A1-notation, misal: "'Sales_Slots2_IDV'!A1:ZZ999".
    Return 2D list (list of rows). Jika gagal → [].
    """
    try:
        # Ambil spreadsheet dulu, lalu panggil values_get via gspread client raw
        import gspread
        from google.oauth2.service_account import Credentials
        from core.app_config import Config, PROJECT_ROOT
        cfg = Config()
        from .gsch_client import _build_credentials
        cred = _build_credentials()
        gc = gspread.authorize(cred)
        sh = gc.open_by_key(spreadsheet_id)
        data = sh.values_get(range_a1) or {}
        return data.get("values", []) or []
    except Exception as e:
        print(f"[GSH] values_get error for {range_a1}: {e}")
        return []

# def get_sheet_values(spreadsheet_id: str, tab_name: str) -> list[list[str]]:
#     """Baca seluruh tab sebagai A1 range lebar."""
#     rng = f"'{tab_name}'!A1:ZZ999"
#     return get_range_values(spreadsheet_id, rng) or []
def get_sheet_values(spreadsheet_id: str, tab_name: str) -> list[list[str]]:
    """Ambil seluruh isi tab (A1:ZZ999)."""
    try:
        ws = get_ws_by_id_tab(spreadsheet_id, tab_name)
        return ws.get_all_values()
    except Exception as e:
        print(f"[GSH] error get_sheet_values({spreadsheet_id}, {tab_name}): {e}")
        return []
