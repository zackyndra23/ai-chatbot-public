import os
from datetime import datetime, timezone
from typing import List, Optional, Any
from .cwh_prompt import build_history_summarize_prompt, format_chat_summarization_block
from .cwh_repo import get_collections
from modules.system_detection.sd_policies import build_language_meta
from core.app_config import Config
cfg = Config()

# app_repo diambil via DI dari app_service kamu
_app_repo = None
def init(app_repo):
    global _app_repo
    _app_repo = app_repo

# def get_history_pairs(session_id: str) -> List[dict]:
def get_history_pairs(session_id: str, token_id: Optional[str] = None) -> List[dict]:
    coll_hist, coll_threads, _ = get_collections(_app_repo)
    # # ambil SEMUA untuk ekspor tampilan (bukan hanya tail)
    # cur = coll_hist.find({"session_id": session_id}).sort("turn", 1)
    # ambil SEMUA untuk ekspor tampilan (bukan hanya tail)
    q = {"session_id": session_id}
    # jika koleksi per-turn menyimpan token_id, aktifkan filter ini
    if token_id:
        q["token_id"] = token_id
    cur = coll_hist.find(q).sort("turn", 1)
    tail_docs = list(cur)
    tail = [{"role": d["role"], "content": d["content"], "ts": d.get("ts")} for d in tail_docs]
    pairs = []
    cur_q = None; cur_ts = None
    for m in tail:
        r = (m.get("role") or "").lower()
        c = (m.get("content") or "").strip()
        ts = m.get("ts")
        if not c:
            continue
        if r == "user":
            if cur_q is not None:
                pairs.append({"ts": cur_ts, "question": cur_q, "message": ""})
            cur_q, cur_ts = c, ts
        elif r == "assistant":
            if cur_q is None:
                pairs.append({"ts": ts, "question": "", "message": c})
            else:
                pairs.append({"ts": cur_ts, "question": cur_q, "message": c})
                cur_q, cur_ts = None, None
    if cur_q is not None:
        pairs.append({"ts": cur_ts, "question": cur_q, "message": ""})
    return pairs

def export_session_document(session_id: str, token_id: str | None = None) -> dict:
    """
    Build one JSON doc like your example, with `chat_history` array.
    NOTE: ini hanya view/export; penyimpanan asli tetap append-per-turn (best practice).
    """
    coll_hist, coll_threads, _ = get_collections(_app_repo)
    thread = coll_threads.find_one({"_id": session_id}) or {}
    pairs = get_history_pairs(session_id)

    # guess created/updated from first/last pair
    created_at = (pairs[0].get("ts") if pairs else thread.get("first_ts"))
    updated_at = (pairs[-1].get("ts") if pairs else thread.get("last_ts"))

    # transform for output
    ch = []
    for p in pairs:
        ch.append({
            "ts": (p.get("ts") or datetime.now(timezone.utc)).isoformat(),
            "question": p.get("question") or "",
            "message": p.get("message") or "",
            # optional: attach prompt name if you store it in meta; empty for now
            "prompt_applied": "",
            "language_name": "",
            "route": "",
            "related_services": [],
            "docs_retrieved_count": 0
        })

    return {
        "tokenId": token_id or thread.get("token_id", ""),
        "sessionId": session_id,
        "chat_history": ch,
        "created_at": (created_at or datetime.now(timezone.utc)).isoformat(),
        "updated_at": (updated_at or datetime.now(timezone.utc)).isoformat(),
    }

def _normalize_message_text(val: Any) -> str:
    """
    Normalisasi field message dari dokumen chat_history:
    - string biasa  -> pakai apa adanya
    - dict picker   -> ambil content.text
    - lainnya       -> cast ke str
    """
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        content = val.get("content") or {}
        text = content.get("text")
        if isinstance(text, str):
            return text
    # fallback untuk tipe lain (list, int, dll)
    return str(val)

def _get_pairs_from_doc_array(session_id: str, token_id: str | None) -> list[dict]:
    """Ambil pasangan Q/A dari satu dokumen yang menyimpan array 'chat_history'."""
    coll_hist, _, _ = get_collections(_app_repo)
    q = {"sessionId": session_id}
    if token_id:
        q["tokenId"] = token_id

    doc = coll_hist.find_one(q, {"chat_history": 1, "_id": 0}) or {}
    arr = doc.get("chat_history") or []

    pairs: list[dict] = []
    if isinstance(arr, list):
        for it in arr:
            qtext = (it.get("question") or "").strip()
            raw_msg = it.get("message")
            atext = _normalize_message_text(raw_msg).strip()
            if qtext or atext:
                pairs.append(
                    {
                        "question": qtext,
                        "message": atext,
                        "ts": it.get("ts"),
                    }
                )
    return pairs

def build_chat_summarization_block(
    session_id: str,
    token_id: str,
    ask_llm,
    max_chars: int | None = None,
    language_name_hint: str | None = None,
) -> tuple[str, dict]:
    # 1) Coba dari doc-array
    pairs = _get_pairs_from_doc_array(session_id, token_id)

    # 2) Fallback: kalau doc-array kosong, ambil dari per-turn history
    if not pairs:
        pairs = get_history_pairs(session_id, token_id=token_id)

    # 3) Kalau tetap kosong → tidak usah panggil LLM
    if not pairs:
        block = "Chat Summarization:\n(Not exist yet)"
        meta = {
            "prompt": None,
            "summary_text": None,
            "input_tokens": 0,
            "output_tokens": 0,
        }
        return block, meta

    # 4) Ada history → susun prompt + bahasa
    max_pairs = int(os.getenv("HISTORY_SUMMARY_MAX_PAIRS", str(getattr(cfg, "HISTORY_SUMMARY_MAX_PAIRS", 20))))
    if max_pairs > 0 and len(pairs) > max_pairs:
        pairs = pairs[-max_pairs:]

    if language_name_hint:
        language_name = language_name_hint
    else:
        last_q = (pairs[-1].get("question") or "").strip()
        _, language_name = build_language_meta(last_q)

    prompt = build_history_summarize_prompt(
        pairs=pairs,
        max_chars=max_chars,
        language_name=language_name,
    )

    msg = ask_llm(prompt)
    summary_text = (getattr(msg, "content", "") or "").strip()

    usage = getattr(msg, "usage_metadata", None) or getattr(msg, "response_metadata", {}) or {}
    token_usage = usage.get("token_usage") or usage
    in_tok  = int(token_usage.get("input_tokens",  0) or token_usage.get("input",  0) or 0)
    out_tok = int(token_usage.get("output_tokens", 0) or token_usage.get("output", 0) or 0)

    block = format_chat_summarization_block(summary_text)

    meta = {
        "prompt": prompt,
        "summary_text": summary_text,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
    }
    return block, meta

def build_history_summarization_prompt_only(
    session_id: str,
    token_id: str,
) -> str:
    """
    Bangun prompt untuk chat summarization (dipakai buat logging summary_applied di Google Sheet).
    Di sini kita pakai bahasa yang sama dengan pertanyaan user terakhir (language_name).
    """
    pairs = _get_pairs_from_doc_array(session_id, token_id)

    # Default: nggak ada bahasa
    language_name: str | None = None

    if pairs:
        # Ambil question terakhir dari history
        last_q = (pairs[-1].get("question") or "").strip()
        if last_q:
            _code, _name = build_language_meta(last_q)
            language_name = _name or None

    # Panggil prompt builder dengan language_name (bisa None → fallback rule di dalam fungsi)
    return build_history_summarize_prompt(
        pairs=pairs,
        max_chars=cfg.HISTORY_SUMMARY_MAX_CHARS,
        language_name=language_name,
    )
