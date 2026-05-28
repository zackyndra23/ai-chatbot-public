import os, re, random
import copy
import time
import threading
from time import perf_counter
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage#
from pymongo import MongoClient
from datetime import datetime, date
from zoneinfo import ZoneInfo
from uuid import uuid4
import json
import requests
import uuid

from .sd_policies import (
    DOCS_THRESHOLD,
    build_language_meta,
    is_greeting,
    is_self_introduction,
)
from .sd_prompts import (
    render_incontext_prompt,
    render_outcontext_prompt,
    render_greeting_prompt,
    render_intro_prompt,
    _address_forms_by_language,
    MEETING_HANDOFF_NOTE_EN,
)
from .sd_nodes import (
    retrieve_candidates,
    build_grader,
    grade_and_filter_yes,
    render_context,
    extract_related_services,
)
from .sd_vector_repo import get_retriever, retrieve_service_biased
from .sd_retrieval_strategies import retrieve_with_strategy, ResolutionContext
from .sd_repo import (
    log_run,
    has_any_history,
    read_user_nick_from_sessions,
    ensure_user_nick_in_sessions,
    read_chat_history,
    read_chat_history_full,
    read_language_history,
)
from modules.system_detection.meeting_arrangement.ma_utils import (
    parse_date, parse_time_range, to_wib, violates_business_rules,
    human_date, human_time_range, business_hours_text, WIB, 
)
from .meeting_arrangement.ma_prompts import (
    render_meeting_start_prompt,
    render_meeting_start_note_prompt, render_meeting_confirm_thanks_prompt,
    render_available_text_prompt, render_meeting_title_prompt, render_recap_3040_prompt,
    render_meeting_invite_confirmation, render_meeting_invite_pending,
)
from .meeting_arrangement.ma_policies import detect_meeting_intent
from .meeting_arrangement.ma_service import (
    llm_parse_day_and_slot, _compose_outside_hours_message, _compose_unavailable_grouped_i18n, _summarize_with_cwh,
    _compose_available_confirm_i18n, _compose_available_i18n, send_calendar_booking, build_meeting_choices_now,
    plan_meeting_service_picker, handle_meeting_service_selected, build_calendar_payload_draft,
)
from modules.system_detection.meeting_arrangement.ma_repo import (
    list_distinct_sales_emails, get_sales_available_from_sheet, _parse_label_to_wib,
    save_calendar_payload, get_count_from_summary, get_sales_available_from_sheet,
    get_weekly_availability_counts, pick_most_available_weekly_from_sheet, _load_indv_index_cached,
    fetch_user_profile, get_last_service_context_from_history, fetch_sales_pic_by_service,
)
from core.app_audit import audit_llm_call
from .meeting_arrangement.ma_utils import to_wib, human_date, human_time_range
from modules.chat_with_history.cwh_prompt import format_chat_history_block
from modules.chat_with_history.cwh_history import (
    build_chat_summarization_block,
)
from .sd_quotation import is_quotation_request, build_quotation_footer
from .sd_meeting import is_meeting_request, build_meeting_footer, build_meeting_picker_preamble
# from modules.service_agent.sa_service import INTAgentService
# from modules.service_agent.sa_repo import ServiceAgentRepo
from infra.app_repo import get_mongo_client 
from modules.service_agent.sa_policies import (
    SERVICE_VALUE_CODE_MAP,
    SERVICE_LABEL_CODE_MAP,
)
from modules.service_agent.sa_prompts import render_qfc_prompt, render_serviceagent_postgate_prompt
# from modules.service_agent.sa_service import SA_ENGINE
from modules.service_agent import sa_policies as SA_POL
from modules.service_agent.sa_flows import FLOW_REGISTRY
from core.app_config import Config
cfg = Config()

MAX_OTHER_SLOT_PICKS = int(getattr(cfg, "MAX_OTHER_SLOT_PICKS", 5) or 5)
_MEETING_CONTEXT_CACHE: dict[str, dict] = {}

def _cache_meeting_context_entry(
    session_id: str,
    *,
    service_label: str | None,
    sales_email: str | None,
    sales_name: str | None,
    extra: dict | None,
) -> None:
    if not session_id:
        return

    incoming = {
        "service_label": service_label or "",
        "sales_email": sales_email or "",
        "sales_name": sales_name or "",
        "extra": copy.deepcopy(extra) if isinstance(extra, dict) else {},
    }

    merged = _merge_booked_meeting_into_ctx(
        ctx=incoming,
        session_id=session_id,
        token_id=None,
    )

    _MEETING_CONTEXT_CACHE[session_id] = merged

from modules.chat_with_history import cwh_history as cwh
from modules.chat_with_history import cwh_prompt as cwhp
from modules.out_of_context.ooc_service import OOCService
from modules.system_detection.sd_sa_handoff import (
    decide_sa_handoff,
    compose_confirm_question,
)
from modules.chat_payload.payload_types import ChatMessage
from modules.chat_payload.payload_builder import (
    build_string_message, build_picker_message, build_lockpicker_message,
    default_summarization_meta, build_chat_turn_payload,
)
from modules.service_agent.sa_prompts import (
    render_serviceagent_prompt_01,
    render_serviceagent_continue_prompt,
    render_serviceagent_continue_question_prompt,
    render_serviceagent_prompt_final,
    render_serviceagent_question_validation_prompt,
    render_serviceagent_interest_validation_prompt,
    render_serviceagent_continue_answerquestion_prompt,
)
from modules.system_detection.sd_opener_guard import extract_opener, sanitize_opener
from modules.system_detection.sd_warning_guard import append_invalid_warning

# Pisah kalimat (cukup robust untuk bhs Latin + Arab + CJK umum)
_SENT_SPLIT = re.compile(r'(?<=[.!?؟。！…])\s+(?=[^\s])', re.UNICODE)

_load_indv_index_cached.cache_clear()

# # singleton simple untuk Service Agent
# _sa_repo = ServiceAgentRepo(get_mongo_client())
# SA_ENGINE = INTAgentService(repo=_sa_repo, llm_client=ASK_LLM)

def _load_meeting_context(session_id: str, token_id: str | None) -> dict:
    key = session_id or ""

    cached = _MEETING_CONTEXT_CACHE.get(key)
    if cached:
        merged_cached = _merge_booked_meeting_into_ctx(
            ctx=cached,
            session_id=session_id,
            token_id=token_id,
        )
        _MEETING_CONTEXT_CACHE[key] = copy.deepcopy(merged_cached)
        return copy.deepcopy(merged_cached)

    ctx = get_last_service_context_from_history(session_id=session_id, token_id=token_id)
    if ctx:
        ctx = _merge_booked_meeting_into_ctx(
            ctx=ctx,
            session_id=session_id,
            token_id=token_id,
        )
        _MEETING_CONTEXT_CACHE[key] = copy.deepcopy(ctx)
        return ctx

    if token_id:
        ctx = get_last_service_context_from_history(session_id=session_id, token_id=None) or {}
        if ctx:
            ctx = _merge_booked_meeting_into_ctx(
                ctx=ctx,
                session_id=session_id,
                token_id=None,
            )
            _MEETING_CONTEXT_CACHE[key] = copy.deepcopy(ctx)
        return ctx

    return {}

def _find_existing_booked_meeting(session_id: str, token_id: str | None, limit: int = 500) -> dict:
    """
    Cari booking meeting yang sudah completed di session ini, lintas service.
    Limit dinaikkan ke 500 agar rows WBS lama tidak terlewat setelah reset.
    """
    rows = _read_all_chat_pairs(session_id=session_id, token_id=token_id, limit=limit) or []
    if not rows and token_id:
        rows = _read_all_chat_pairs(session_id=session_id, token_id=None, limit=limit) or []
    for row in reversed(rows):
        extra = row.get("extra") or {}
        ma_state = dict((extra.get("meeting_arrangement") or {}))
        if not ma_state:
            continue

        if not bool(ma_state.get("booking_completed")):
            continue

        selected_slot = dict((ma_state.get("selected_slot") or {}))
        if not selected_slot:
            continue

        return {
            "service_label": (extra.get("service_label") or "").strip(),
            "sales_email": (extra.get("sales_email") or "").strip(),
            "sales_name": (extra.get("sales_name") or "").strip(),
            "extra": extra,
        }
    return {}

def _merge_booked_meeting_into_ctx(
    *,
    ctx: dict | None,
    session_id: str,
    token_id: str | None,
) -> dict:
    """
    Pastikan context saat ini tetap membawa info booking completed lintas service
    dalam 1 session, walaupun cache/context terakhir sudah berganti service.
    """
    base = copy.deepcopy(ctx or {})
    extra_ctx = dict((base.get("extra") or {}))

    booked_ctx = _find_existing_booked_meeting(session_id=session_id, token_id=token_id)
    if not booked_ctx and token_id:
        booked_ctx = _find_existing_booked_meeting(session_id=session_id, token_id=None)

    if not booked_ctx:
        base["extra"] = extra_ctx
        return base

    booked_extra = dict((booked_ctx.get("extra") or {}))
    booked_ma = dict((booked_extra.get("meeting_arrangement") or {}))
    if not booked_ma:
        base["extra"] = extra_ctx
        return base

    current_ma = dict((extra_ctx.get("meeting_arrangement") or {}))

    # Pertahankan service/sales context TERKINI,
    # tapi suntikkan state booking lama agar guard bisa mendeteksi.
    current_ma["booking_completed"] = bool(booked_ma.get("booking_completed"))
    current_ma["followup_stage"] = booked_ma.get("followup_stage") or current_ma.get("followup_stage")
    current_ma["selected_slot"] = dict((booked_ma.get("selected_slot") or current_ma.get("selected_slot") or {}))
    current_ma["timezone"] = booked_ma.get("timezone") or current_ma.get("timezone")
    current_ma["timezone_label"] = booked_ma.get("timezone_label") or current_ma.get("timezone_label")
    current_ma["reset_ready"] = booked_ma.get("reset_ready", current_ma.get("reset_ready"))
    current_ma["calendar_sent_ok"] = booked_ma.get("calendar_sent_ok", current_ma.get("calendar_sent_ok"))
    current_ma["monday_meeting_sent"] = booked_ma.get("monday_meeting_sent", current_ma.get("monday_meeting_sent"))

    extra_ctx["meeting_arrangement"] = current_ma
    base["extra"] = extra_ctx
    return base

SERVICE_AGENT_PREFIX = "SA_SELECT_"
RELATED_SERVICE_BATCH_PREFIX = "RS_OTHER_BATCH_"
RELATED_SERVICE_BATCH_RE = re.compile(r"^RS_OTHER_BATCH_(\d+)$", re.I)
RELATED_SERVICE_BATCH_SIZE = 5
# RESET_CONVERSATION_AFTER_MEETING constant removed — reset flows handled by Crisp.

# --- 1) Normalisasi honorifik per bahasa ------------------------------

def _normalize_pair_for_lang(text: str, lang: str, nick: str) -> str:
    if not nick or not text:
        return text
    l = (lang or "").lower()
    escn = re.escape(nick)

    def pair_re(a: str, b: str) -> re.Pattern:
        # tangkap: A atau B, boleh sudah berpasangan/berulang: A/B, A/B/A, dst.
        return re.compile(rf"\b(?:{a}|{b})(?:\s*/\s*(?:{a}|{b}))*\s+{escn}\b", re.I | re.U)

    subs: list[tuple[re.Pattern, str]] = []

    # ID
    if l.startswith("id"):
        subs.append((pair_re(r"Bapak", r"Ibu"), f"{nick}"))

    # MS
    if l.startswith("ms"):
        subs.append((pair_re(r"Encik", r"Puan"), f"{nick}"))

    # FR
    if l.startswith("fr"):
        subs.append((pair_re(r"Monsieur", r"Madame"), f"{nick}"))

    # DE
    if l.startswith("de"):
        subs.append((pair_re(r"Herr", r"Frau"), f"{nick}"))

    # IT
    if l.startswith("it"):
        subs.append((pair_re(r"Signore", r"Signora"), f"{nick}"))

    # RM
    if l.startswith("rm"):
        subs.append((pair_re(r"Signur", r"Signura"), f"{nick}"))

    # ES
    if l.startswith("es"):
        subs.append((pair_re(r"Sr\.?", r"Sra\.?"), f"{nick}"))

    # PT
    if l.startswith("pt"):
        subs.append((pair_re(r"Sr\.?", r"Sra\.?"), f"{nick}"))

    # EN
    if l.startswith("en"):
        subs.append((pair_re(r"Mr\.?", r"Ms\.?"), f"{nick}"))

    # RU: tetap satu bentuk netral
    if l.startswith("ru"):
        subs.append((re.compile(rf"\bуважаем(?:ый|ая)\s+{escn}\b", re.I | re.U), f"{nick}"))

    # TH: pastikan tanpa spasi
    if l.startswith("th"):
        subs.append((re.compile(rf"คุณ\s+{escn}", re.U), f"{nick}"))

    out = text
    remaining = 2  # cukup 1–2 koreksi awal; hindari over-correct
    for pat, repl in subs:
        if remaining <= 0:
            break
        out, cnt = pat.subn(repl, out, count=remaining)
        remaining -= cnt
    return out

# --- 2) Penempatan mention fleksibel (awal / tengah / akhir) ----------

def _inject_mention(sent: str, mention: str, lang: str, rnd: random.Random) -> str:
    """Sisipkan 'mention' secara natural di awal/tengah/akhir kalimat."""
    s = sent or ""
    l = (lang or "").lower()

    # TH: hindari koma
    use_comma = not l.startswith("th")
    comma = "," if use_comma else ""

    style = rnd.choices(["start", "middle", "end"], weights=[0.35, 0.35, 0.30])[0]

    if style == "start":
        return f"{mention}{comma} {s.lstrip()}"

    if style == "end":
        m = re.search(r'\s*([.!?؟。！…]+)\s*$', s)
        sep = (comma + " ") if use_comma else " "
        if m:
            core = s[:m.start()]
            tail = s[m.start():]
            return f"{core}{sep}{mention}{tail}"
        return f"{s.rstrip()}{sep}{mention}"

    # middle: setelah tanda koma/titik dua/dash; kalau tak ada, setelah ~3 kata
    m = re.search(r'(,|:| — | - |;)', s)
    if m:
        idx = m.end()
        ins = f" {mention}{comma}"
        return f"{s[:idx]}{ins}{s[idx:]}"
    tokens = s.split()
    if len(tokens) > 3:
        pos = len(" ".join(tokens[:3]))
        ins = f"{comma} {mention}"
        return f"{s[:pos]}{ins}{s[pos:]}"
    # fallback -> awal
    return f"{mention}{comma} {s.lstrip()}"

def build_service_choices(related_services: list[str], *, value_prefix: str = SA_POL.SERVICE_AGENT_PREFIX) -> list[dict]:
    seen_names = set()
    uniq = []
    for s in related_services or []:
        s2 = (s or "").strip()
        if not s2 or s2 in seen_names:
            continue
        seen_names.add(s2)
        uniq.append(s2)

    normalized: list[dict] = []
    seen_values: set[str] = set()
    for svc_name in uniq:
        value_code, label = _map_related_service_to_value_code(svc_name)
        if not value_code:
            continue
        value_code_norm = value_code.strip().lower()
        if not value_code_norm or value_code_norm == "general_service":
            continue
        if value_code_norm in seen_values:
            continue
        seen_values.add(value_code_norm)
        normalized.append({
            "value_code": value_code,
            "label": label or SERVICE_LABEL_CODE_MAP.get(value_code, svc_name),
        })

    has_dd = "due_diligence" in seen_values
    has_ebs = "background_check" in seen_values
    if has_dd and not has_ebs:
        seen_values.add("background_check")
        normalized.append({
            "value_code": "background_check",
            "label": SERVICE_LABEL_CODE_MAP.get("background_check", "Background Check"),
        })
    elif has_ebs and not has_dd:
        seen_values.add("due_diligence")
        normalized.append({
            "value_code": "due_diligence",
            "label": SERVICE_LABEL_CODE_MAP.get("due_diligence", "Due Diligence"),
        })

    out = []
    for entry in normalized:
        out.append({
            "value": f"{value_prefix}{entry['value_code']}",
            "label": entry["label"],
            "selected": False,
        })
    return out

# --- 3) Pilih posisi target menurut cadence ---------------------------

def _pick_positions(n_sents: int, cadence: int, seed: int | None) -> list[int]:
    rnd = random.Random(seed)
    if n_sents <= 0:
        return []
    start_choices = [0] + list(range(1, min(3, n_sents)))
    start = start_choices[0] if rnd.random() < 0.4 else (rnd.choice(start_choices[1:]) if len(start_choices) > 1 else 0)
    pos = sorted(set([start] + list(range(start + cadence, n_sents, cadence))))
    return pos

# --- 4) Orkestrator: enforce variasi & bahasa -------------------------

def enforce_name_variation(text: str, language_code: str, nick_plain: str, addr_formal: str,
                           cadence: int = 3, max_mentions_short: int = 2, max_mentions_long: int = 3,
                           seed: int | None = None) -> str:
    """Pastikan penyebutan nama/honorifik natural lintas bahasa:
       - Normalisasi bentuk honorifik (ID/MS/FR/DE/IT/RM/RU/TH/ES/PT/EN).
       - Alternasi honorifik ↔ nama.
       - Posisi fleksibel (awal/tengah/akhir) tiap ~3 kalimat.
    """
    if not text or not nick_plain:
        return text

    lang = (language_code or "").lower()

    # 1) Normalisasi honorifik existing di text (termasuk FR)
    t = _normalize_pair_for_lang(text.strip(), lang, nick_plain)

    # 2) Pecah kalimat & hitung
    sents = _SENT_SPLIT.split(t)
    n = len(sents)
    if n == 0:
        return t

    def has_mention(s: str) -> bool:
        return (nick_plain in s) or (addr_formal and addr_formal in s)

    mentions = sum(1 for s in sents if has_mention(s))
    max_mentions = max_mentions_long if n > 6 else max_mentions_short

    # 3) Pilih posisi target dan siapkan urutan sebutan (honorifik ↔ nama)
    rnd = random.Random(seed if seed is not None else 0xC0FFEE)
    positions = _pick_positions(n, cadence=cadence, seed=rnd.randint(0, 2**32 - 1))

    seq = []
    use_hon = True
    for _ in range(max_mentions):
        seq.append(addr_formal if (use_hon and addr_formal) else nick_plain)
        use_hon = not use_hon

    # 4) Sisipkan di posisi yang belum punya mention, dengan placement fleksibel
    k = 0
    for pos in positions:
        if mentions >= max_mentions or pos >= n:
            break
        if not has_mention(sents[pos]):
            sents[pos] = _inject_mention(sents[pos], seq[k], lang, rnd)
            mentions += 1
            k += 1
            if k >= len(seq):
                break

    return " ".join(sents)

# === LLM singleton ===
# gunakan max_tokens (bukan max_tokens_to_sample)
BASE_LLM = ChatAnthropic(
    model=cfg.ANTHROPIC_MODEL,
    anthropic_api_key=cfg.ANTHROPIC_API_KEY,
    max_tokens=cfg.MAX_OUTPUT_TOKENS,
    temperature=cfg.LLM_TEMPERATURE,
)

# Profil keluaran
BRIEF_LLM = BASE_LLM.bind(max_tokens=cfg.MAX_TOKENS_BRIEF)  # jawaban user
ASK_LLM   = BASE_LLM.bind(max_tokens=cfg.MAX_TOKENS_ASK)    # greeting/pertanyaan singkat

# Prebuild grader runnable.
# Use GRADER_MODEL (e.g. claude-haiku-4-5) for cost optimisation — grader does
# binary yes/no classification per retrieved doc and runs K times per turn,
# so a cheaper/smaller model gives ~5× cost reduction with negligible quality
# drop. Fallback to ANTHROPIC_MODEL when GRADER_MODEL is unset.
_GRADER_MODEL_NAME = (cfg.GRADER_MODEL or cfg.ANTHROPIC_MODEL).strip()
if _GRADER_MODEL_NAME and _GRADER_MODEL_NAME != cfg.ANTHROPIC_MODEL:
    _GRADER_LLM = ChatAnthropic(
        model=_GRADER_MODEL_NAME,
        anthropic_api_key=cfg.ANTHROPIC_API_KEY,
        max_tokens=64,                 # binary structured output, cap small
        temperature=0.0,               # deterministic for classification
    )
else:
    _GRADER_LLM = BASE_LLM
GRADER = build_grader(_GRADER_LLM)

# Summarizer instance (Claude Sonnet)
SUM_LLM = ChatAnthropic(
    model=cfg.ANTHROPIC_MODEL,
    anthropic_api_key=cfg.ANTHROPIC_API_KEY,
    max_tokens=max(64, int(getattr(cfg, "HISTORY_SUMMARY_MAX_TOKENS", 220))),
    temperature=cfg.LLM_TEMPERATURE,           # 0.2 = stabil, cocok untuk summary
)

_SUMMARY_CACHE: dict[tuple[str, str], dict] = {}
_SUMMARY_INFLIGHT: set[tuple[str, str]] = set()
_SUMMARY_LOCK = threading.Lock()
_SUMMARY_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="summary-refresh")

def _summary_async_on() -> bool:
    return os.getenv("SUMMARY_ASYNC", "on").strip().lower() in ("1", "true", "on", "yes")

def _summary_cache_key(session_id: str, token_id: str | None) -> tuple[str, str]:
    return (session_id or "", token_id or "")

def _get_cached_summary(session_id: str, token_id: str | None) -> tuple[str | None, dict | None]:
    key = _summary_cache_key(session_id, token_id)
    with _SUMMARY_LOCK:
        row = _SUMMARY_CACHE.get(key)
    if not row:
        return None, None
    return row.get("summary_block"), row.get("sm")

def _schedule_summary_refresh(
    *,
    session_id: str,
    token_id: str | None,
    language_name_hint: str | None = None,
):
    if not _summary_async_on():
        return
    if _fast_mode_on():
        return
    if (cfg.CHAT_HISTORY_SCHEMA or "last3").lower() != "allsum":
        return

    key = _summary_cache_key(session_id, token_id)
    with _SUMMARY_LOCK:
        if key in _SUMMARY_INFLIGHT:
            return
        _SUMMARY_INFLIGHT.add(key)

    def _job():
        try:
            delay_s = float(os.getenv("SUMMARY_ASYNC_DELAY_SEC", "0.6"))
            if delay_s > 0:
                time.sleep(delay_s)

            summary_block, summary_meta = build_chat_summarization_block(
                session_id=session_id,
                token_id=token_id or "",
                ask_llm=_call_llm_text_sum,
                max_chars=getattr(cfg, "HISTORY_SUMMARY_MAX_CHARS", 4500),
                language_name_hint=language_name_hint,
            )
            sm = {
                "summary_applied": summary_meta.get("prompt") or "-",
                "summary_input": int(summary_meta.get("input_tokens") or 0),
                "summary_output": int(summary_meta.get("output_tokens") or 0),
                "chat_summarization": summary_meta.get("summary_text") or "-",
            }
            with _SUMMARY_LOCK:
                _SUMMARY_CACHE[key] = {
                    "summary_block": summary_block,
                    "sm": sm,
                    "updated_at": time.time(),
                }
        except Exception:
            pass
        finally:
            with _SUMMARY_LOCK:
                _SUMMARY_INFLIGHT.discard(key)

    _SUMMARY_POOL.submit(_job)

def _call_llm_text_sum(prompt: str):
    """
    Helper untuk summarization.
    Return ChatMessage LLM supaya build_chat_summarization_block
    bisa baca usage_metadata (input/output tokens).
    """
    prompt_msgs_sum = [HumanMessage(content=prompt)]
    with audit_llm_call(
        route="system_detection",
        stage="history_summary",
        session_id="",
        token_id=None,
        prompt=prompt_msgs_sum,
    ) as ctx:
        msg = SUM_LLM.invoke(
            prompt_msgs_sum,
            config={"max_tokens": max(64, int(getattr(cfg, "HISTORY_SUMMARY_MAX_TOKENS", 220)))},
        )
        ctx.set_response_from_message(msg)

    # kalau kamu masih mau hard cap by chars, boleh dipotong di sini:
    max_chars = getattr(cfg, "HISTORY_SUMMARY_MAX_CHARS", 2500)
    text = (getattr(msg, "content", "") or "").strip()
    if len(text) > max_chars:
        text = text[: max_chars].rstrip() + "…"
        # override content supaya yang dipakai ke depan versi yang sudah dipotong
        msg.content = text

    return msg

def _summary_meta_from_sm(sm: dict | None) -> dict:
    sm = sm or {}
    return {
        "prompt": sm.get("summary_applied") or "-",
        "input_tokens": int(sm.get("summary_input") or 0),
        "output_tokens": int(sm.get("summary_output") or 0),
        "summary_text": sm.get("chat_summarization") or "-",
    }

def _attach_request_total_duration(result: dict, started_at: float) -> dict:
    result["request_total_duration"] = round(time.monotonic() - started_at, 3)
    return result

def _maybe_build_already_booked_result(
    *,
    slot_plan: dict,
    question: str,
    session_id: str,
    request_t0: float,
    token_id: str | None,
    language_name: str,
    resolved_nick: str | None,
    related_services: list[str] | None,
    summarization_meta: dict | None,
    service_label: str | None,
    sales_email: str | None,
    sales_name: str | None,
) -> dict | None:
    """
    Kalau slot_plan adalah warning 'already booked',
    render jadi payload final dan langsung return result.
    """
    if (slot_plan or {}).get("route") != "meeting_arrangement_already_booked":
        return None

    rendered_prompt = (slot_plan.get("prompt") or "").strip()
    extra_payload = slot_plan.get("extra") or {}
    related_services = related_services or ([service_label] if service_label else [])
    sm = summarization_meta or {}

    prompt_msgs_already_booked = [
        SystemMessage(content=rendered_prompt),
        HumanMessage(content=question or "User is asking for another meeting.")
    ]
    with audit_llm_call(
        route="system_detection",
        stage="already_booked_reply",
        session_id=session_id,
        token_id=token_id,
        prompt=prompt_msgs_already_booked,
    ) as ctx:
        llm_msg = BRIEF_LLM.invoke(prompt_msgs_already_booked)
        ctx.set_response_from_message(llm_msg)
    text = normalize_single_paragraph(getattr(llm_msg, "content", "") or "")
    in_tok = ctx.input_tokens
    out_tok = ctx.output_tokens
    dur = ctx.latency_ms / 1000.0

    # Crisp's native "start a new chat" handles reset — we no longer show
    # a START_NEW_CHAT picker here. Plain string so the user can type freely.
    msg_obj = build_string_message(text)

    payload = build_chat_turn_payload(
        question=question,
        message=msg_obj,
        route="meeting_arrangement_already_picked_validation",
        language_name=language_name,
        user_nick=resolved_nick or "",
        prompt_applied=rendered_prompt,
        related_services=related_services,
        docs_retrieved_count=0,
        respond_duration=dur,
        input_token=in_tok,
        output_token=out_tok,
        input_total=in_tok + int(sm.get("summary_input") or 0),
        output_total=out_tok + int(sm.get("summary_output") or 0),
        summarization_meta=sm,
        extra=extra_payload,
    )

    result = {"session_id": session_id, **payload}
    _attach_request_total_duration(result, request_t0)
    log_run(session_id, question, result)

    _cache_meeting_context_entry(
        session_id,
        service_label=service_label,
        sales_email=sales_email,
        sales_name=sales_name,
        extra=extra_payload,
    )
    _schedule_summary_refresh(
        session_id=session_id,
        token_id=token_id,
        language_name_hint=language_name,
    )
    return result

def _fast_mode_on() -> bool:
    return os.getenv("SD_FAST_MODE", "off").strip().lower() in ("1", "true", "on", "yes")

def _parallel_prep_on() -> bool:
    return os.getenv("SD_PARALLEL_PREP", "off").strip().lower() in ("1", "true", "on", "yes")

def _guess_type_label_fast(user_question: str) -> str:
    q = (user_question or "").strip()
    low = q.lower()
    question_starts = (
        "what", "why", "how", "when", "where", "who", "which",
        "can ", "could ", "would ", "do ", "does ", "is ", "are ",
        "apakah", "bagaimana", "kenapa", "mengapa", "kapan", "dimana",
    )
    is_question = ("?" in q) or any(low.startswith(s) for s in question_starts)
    if not is_question:
        return "answer_only"
    # pendek murni tanya, panjang cenderung campur jawab+tanya
    return "question_only" if len(q.split()) <= 10 else "answer_and_question"

def _guess_interest_label_fast(user_question: str) -> str:
    low = (user_question or "").strip().lower()
    if not low:
        return "not_interest"
    hard_no = (
        "not interested", "no thanks", "don't need", "dont need",
        "tidak tertarik", "ga tertarik", "gak tertarik", "skip dulu",
        "nanti saja", "later",
    )
    if any(k in low for k in hard_no):
        return "not_interest"
    return "valid"

def _build_history_blocks(
    session_id: str,
    token_id: str | None,
    precomputed_summary_block: str | None = None,
    precomputed_summary_meta: dict | None = None,
):
    schema = (cfg.CHAT_HISTORY_SCHEMA or "last3").lower()

    if schema == "allsum":
        # Reuse summary built earlier in the same request to avoid duplicate LLM calls.
        if precomputed_summary_meta is not None:
            summary_block = precomputed_summary_block
            summary_meta = precomputed_summary_meta
        else:
            # RINGKASAN + history_block None (atau sebaliknya tergantung desain kamu)
            summary_block, summary_meta = build_chat_summarization_block(
                session_id=session_id,
                token_id=token_id or "",
                ask_llm=_call_llm_text_sum,
                max_chars=getattr(cfg, "HISTORY_SUMMARY_MAX_CHARS", 4500),
            )
        history_block = None
    else:
        # hanya history, tanpa summary
        pairs = _get_array_tail(session_id, token_id or "", tail_k=3)
        history_block = format_chat_history_block(pairs)
        summary_block = None
        summary_meta = None

    return history_block, summary_block, summary_meta

def _pad_to_floor(filtered, candidates, floor: int):
    """Backfill `filtered` with retrieved `candidates` the grader rejected,
    preserving vector-similarity order, up to `floor` total docs. Idempotent
    and order-preserving. Used at every retrieval site so the main prompt
    always sees a consistent number of FAQ docs."""
    if floor <= 0 or len(filtered) >= floor:
        return filtered[:floor] if floor > 0 else filtered
    seen = {id(d) for d in filtered}
    out = list(filtered)
    for d in candidates:
        if len(out) >= floor:
            break
        if id(d) not in seen:
            out.append(d)
    return out[:floor]


# DB-form overrides for canonical labels whose FAQ-pipeline-stored form drifts
# from the SERVICE_LABEL_CODE_MAP canonical spelling. Keep this in sync with
# the Google Sheet's "Service" column if new services are added.
_DB_ALIAS_OVERRIDES = {
    "Claim Investigation": ["Insurance Investigation", "ISI"],
    "Anti-Counterfeiting Investigation": ["Anti-Counterfeit Investigation", "ACI"],
}


def _service_aliases(canonical_label: str) -> list[str]:
    """Return all plausible metadata values that represent the same service.

    Example:
      canonical "Whistleblowing Hotline" → ["Whistleblowing Hotline", "WBS"]
      canonical "Market Research"         → ["Market Research", "MSY"]
      canonical "General Service"       → ["General Service", "General", "GRL"]

    Used to build Chroma filters that match across stored forms (short alias
    vs long label). The FAQ ingestion pipeline stores whichever form the
    source sheet used, which is a mix of short and long.
    """
    from modules.service_agent.sa_policies import VALUE_TO_FLOW_CODE as _V2F
    canonical = (canonical_label or "").strip()
    if not canonical:
        return []
    out = [canonical]
    for alias, flow in _V2F.items():
        code = SERVICE_VALUE_CODE_MAP.get(alias)
        canon = SERVICE_LABEL_CODE_MAP.get(code) if code else None
        if canon == canonical:
            if alias and alias not in out:
                out.append(alias)
            if flow and flow not in out:
                out.append(flow)
    for extra in _DB_ALIAS_OVERRIDES.get(canonical, []):
        if extra and extra not in out:
            out.append(extra)
    return out


def _infer_service_from_query(question: str) -> str | None:
    """
    Detect a service name in the user's query via substring or fuzzy word-match
    against SERVICE_LABEL_CODE_MAP values + VALUE_TO_FLOW_CODE keys.

    Tolerates typos via difflib.SequenceMatcher ratio (default threshold
    CTX_INFER_FUZZY_RATIO=0.82). Handles short aliases (EBS, WBS, DD) via
    word-boundary substring match. Handles mixed-language queries as long as
    the service word is present (most Indonesian/Malay users use English
    service names).

    Returns the canonical SERVICE_LABEL_CODE_MAP value (e.g. "Market Research")
    or None if no confident match.

    Example: "Tolong jelaskan tentang Merket survey" → "Market Research".
    """
    import difflib
    import re as _re

    q = (question or "").strip().lower()
    if not q:
        return None

    # Build {canonical_label: [aliases]} map. Canonical is the long form from
    # SERVICE_LABEL_CODE_MAP (e.g. "Market Research"). Aliases include short
    # codes (EBS, WBS) via VALUE_TO_FLOW_CODE keys.
    from modules.service_agent.sa_policies import VALUE_TO_FLOW_CODE as _V2F
    canon_to_aliases: dict[str, list[str]] = {}
    for code, label in SERVICE_LABEL_CODE_MAP.items():
        canon_to_aliases[label] = [label]
    # VALUE_TO_FLOW_CODE keys are service labels ("Mystery Shopping", "EBS", ...)
    # and values are 2-4 letter flow codes ("MSG", "EBS", "KYC", ...).
    # Both sides contribute aliases.
    for alias, flow in _V2F.items():
        code = SERVICE_VALUE_CODE_MAP.get(alias)
        canon = SERVICE_LABEL_CODE_MAP.get(code) if code else None
        if canon:
            canon_to_aliases.setdefault(canon, [canon])
            if alias not in canon_to_aliases[canon]:
                canon_to_aliases[canon].append(alias)
            if flow and flow not in canon_to_aliases[canon]:
                canon_to_aliases[canon].append(flow)

    # Step 1: exact-substring match (case-insensitive) on any alias.
    # Short aliases (≤4 chars) require a word-boundary match to avoid false
    # positives like "dd" inside "adding".
    for canon, aliases in canon_to_aliases.items():
        for al in aliases:
            al_low = al.lower()
            if len(al_low) <= 4:
                if _re.search(rf"\b{_re.escape(al_low)}\b", q):
                    return canon
            else:
                if al_low in q:
                    return canon

    # Step 2: fuzzy per-word match on long aliases only. For each canonical
    # label, every word in the label must have a close match (ratio >= threshold)
    # with some word in the query.
    threshold = float(getattr(cfg, "CTX_INFER_FUZZY_RATIO", 0.82))
    q_words = set(_re.findall(r"[a-zA-Z]+", q))
    best_canon = None
    best_score = 0.0
    for canon, aliases in canon_to_aliases.items():
        for al in aliases:
            al_low = al.lower()
            if len(al_low) <= 4:
                continue
            lbl_words = [w for w in _re.findall(r"[a-z]+", al_low) if len(w) >= 3]
            if not lbl_words:
                continue
            matched = 0
            score_sum = 0.0
            for lw in lbl_words:
                best_word_score = 0.0
                for qw in q_words:
                    r = difflib.SequenceMatcher(None, lw, qw).ratio()
                    if r > best_word_score:
                        best_word_score = r
                if best_word_score >= threshold:
                    matched += 1
                    score_sum += best_word_score
            if matched == len(lbl_words):
                avg = score_sum / matched
                if avg > best_score:
                    best_score = avg
                    best_canon = canon
    return best_canon


_EXPLANATION_INTENT_PATTERNS = [
    # English
    r"\bwhat\s+is\b", r"\bwhat\s+are\b", r"\bwhat's\b", r"\bexplain\b",
    r"\bdescribe\b", r"\btell\s+me\s+about\b", r"\boverview\b",
    r"\bcan\s+you\s+(?:explain|describe|tell)\b",
    # Indonesian
    r"\bjelaskan\b", r"\bjelasin\b", r"\bapa\s+itu\b", r"\bapa\s+sih\b",
    r"\bceritakan\b", r"\btolong\s+jelask", r"\bmenjelaskan\b",
    r"\btentang\b",
    # Malay
    r"\bterangkan\b", r"\bapakah\b",
]


def _is_explanation_intent(query: str) -> bool:
    """True when the user's query is asking for an explanation/definition/
    overview of a service. Multi-language (en/id/ms)."""
    import re as _re
    q = (query or "").strip().lower()
    if not q:
        return False
    for p in _EXPLANATION_INTENT_PATTERNS:
        if _re.search(p, q):
            return True
    return False


# === Anti-Redundancy: explicit-recap detection (Stage 2026-05-11) ===========
# When user says "ulangi"/"say that again"/etc., the recent-chunks filter must
# be bypassed (user explicitly wants the prior answer). Word-boundary regex per
# language to avoid false positives like Indonesian "berulang".
import re as _re_recap

_RECAP_PATTERNS: dict[str, list[str]] = {
    "id": [r"\bulang(?:i|in)?\b", r"\bjelaskan\s+lagi\b", r"\bsebutkan\s+lagi\b",
           r"\bdiulang\b", r"\bdijelaskan\s+lagi\b", r"\bkatakan\s+lagi\b"],
    "ms": [r"\bulang(?:\s+semula)?\b", r"\bjelaskan\s+sekali\s+lagi\b"],
    "en": [r"\bsay\s+(?:that|it)\s+again\b", r"\brepeat\s+(?:that|it|please)\b",
           r"\bcan\s+you\s+repeat\b", r"\bexplain\s+again\b", r"\btell\s+me\s+again\b"],
    "fr": [r"\brépétez\b", r"\bredites\b", r"\brépéter\b"],
    "de": [r"\bwiederholen\s+sie\b", r"\bwiederholen\b", r"\bnochmal\s+sagen\b"],
    "it": [r"\bripeti\b", r"\bripetere\b", r"\bdimmi\s+di\s+nuovo\b"],
    "pt": [r"\brepita\b", r"\brepetir\b"],
    "es": [r"\brepita\b", r"\brepetir\b", r"\bdime\s+de\s+nuevo\b"],
    "vi": [r"\blặp\s+lại\b", r"\bnói\s+lại\b"],
    "th": [r"พูดอีกที", r"อธิบายอีกที", r"พูดใหม่"],
    "da": [r"\bgentag\b", r"\bsig\s+det\s+igen\b"],
    "zh": [r"再说一[遍次]", r"再讲一[遍次]", r"重复"],
    "ja": [r"もう一度", r"もういちど", r"繰り返し"],
    "ru": [r"\bповторите\b", r"\bещё\s+раз\b", r"\bеще\s+раз\b"],
}


def _is_explicit_recap(question: str | None, language_code: str | None) -> bool:
    """True if the user's question is an explicit "say that again" style request.

    Patterns are checked per-language; unknown language codes fall back to English.
    """
    if not question:
        return False
    text = question.lower()
    lang = (language_code or "").lower().split("-")[0] or "en"
    patterns = _RECAP_PATTERNS.get(lang) or _RECAP_PATTERNS["en"]
    for pat in patterns:
        if _re_recap.search(pat, text, flags=_re_recap.IGNORECASE | _re_recap.UNICODE):
            return True
    return False


def _extract_chunk_ids_from_docs(docs) -> list[str]:
    """Return metadata.chunk_id of every doc that has one. Skips missing."""
    out: list[str] = []
    for d in docs or []:
        cid = (getattr(d, "metadata", {}) or {}).get("chunk_id")
        if cid:
            out.append(str(cid))
    return out


def _apply_recent_chunk_filter(over_fetched: list, recent_ids: list[str], *, floor: int) -> list:
    """Partition into fresh/stale by chunk_id, return top-`floor`.

    fresh = docs whose chunk_id ∉ recent_ids (original rank preserved).
    stale = docs whose chunk_id ∈ recent_ids (original rank preserved).
    Output: take top-floor from fresh; if fewer than floor, top up with stale
    in their original rank order (demoted to the tail). Never drops below floor.
    """
    recent_set = set(recent_ids or [])
    fresh: list = []
    stale: list = []
    for doc in over_fetched or []:
        cid = (getattr(doc, "metadata", {}) or {}).get("chunk_id")
        if cid and cid in recent_set:
            stale.append(doc)
        else:
            fresh.append(doc)
    if len(fresh) >= floor:
        return fresh[:floor]
    needed = floor - len(fresh)
    return fresh + stale[:needed]


def _fetch_service_definition_doc(service_label: str):
    """Fetch the canonical 'What is X service?' FAQ from the vector store,
    filtered to the specified service (all alias forms). Returns None if the
    store isn't loaded or no match exists."""
    try:
        from . import sd_vector_repo as _vr
        if _vr._vectorstore is None:
            _vr.bootstrap_vectorstore()
        vs = _vr._vectorstore
        if vs is None:
            return None
        aliases = _service_aliases(service_label)
        svc_filter = _vr._service_filter(aliases)
        results = vs.similarity_search(
            f"What is the {service_label} service? Definition and overview.",
            k=1,
            filter=svc_filter,
        )
        return results[0] if results else None
    except Exception:
        return None


def _prepare_rag_context(
    question: str,
    sa_service_label: str | None = None,
    *,
    session_id: str | None = None,
    token_id: str | None = None,
    turn_language_code: str | None = None,
):
    """
    Generic RAG context preparation, split into two phases:

    - Phase 1 (sa_service_label NOT set): generic top-N retrieval over the
      whole KB. Floor = CTX_DOCS_FLOOR (default 4). Cross-service mix.
    - Phase 2 (sa_service_label set, i.e. user committed via SA picker click):
      service-biased retrieval. Floor = CTX_DOCS_SAME_SERVICE +
      CTX_DOCS_OTHER_SERVICE.

    Auto-infer (`_infer_service_from_query`) is decoupled from retrieval
    bias — it only feeds definitional-FAQ pinning. This stops a fuzzy
    service-name match in the user's query from silently locking Phase 1
    retrieval to one service.

    When the resolved def_svc is set AND the query has explanation intent
    ('what is X?', 'apa itu X', etc.), the canonical 'What is X service?'
    FAQ is pinned at position 0 — guards cross-lingual / typo'd queries
    where the definitional FAQ embeds weakly.
    """
    _same_k = int(getattr(cfg, "CTX_DOCS_SAME_SERVICE", 4))
    _other_k = int(getattr(cfg, "CTX_DOCS_OTHER_SERVICE", 0))

    bias_svc = (sa_service_label or "").strip() or None

    def_svc = bias_svc
    if not def_svc and bool(getattr(cfg, "CTX_INFER_SERVICE_FROM_QUERY", True)):
        def_svc = _infer_service_from_query(question)

    pin_def = bool(
        def_svc
        and getattr(cfg, "CTX_PIN_SERVICE_DEFINITION", True)
        and _is_explanation_intent(question)
    )
    def_doc = _fetch_service_definition_doc(def_svc) if pin_def else None

    # Consolidate method + context once, above both branches.
    method = (getattr(cfg, "REDUNDANCY_METHOD", "normal") or "normal").strip().lower()
    rc_ctx = ResolutionContext(service_id=(bias_svc or None))

    if bias_svc:
        _floor = _same_k + _other_k
        # Per-service vectorstore for strategy dispatch (split/dual modes).
        from modules.system_detection import sd_vector_repo as _svr
        target_id = _svr._resolve_alias_to_service_id(_service_aliases(bias_svc))
        strategy_vs = _svr._vectorstores.get(target_id) if target_id else None
        strategy_result = retrieve_with_strategy(
            method, question, scope="service_biased", k=_floor,
            vectorstore=strategy_vs, ctx=rc_ctx,
        )
        if strategy_result is None:
            candidates = retrieve_service_biased(question, _service_aliases(bias_svc), same_k=_same_k, other_k=_other_k)
        else:
            candidates = strategy_result
    else:
        _floor = int(getattr(cfg, "CTX_DOCS_FLOOR", 4))
        retriever = get_retriever()
        # Strategy dispatch needs a concrete vectorstore. Pull the underlying
        # vectorstore from the retriever for unbiased mode.
        strategy_vs = getattr(retriever, "vectorstore", None)
        strategy_result = retrieve_with_strategy(
            method, question, scope="unbiased", k=_floor,
            vectorstore=strategy_vs, ctx=rc_ctx,
        )
        if strategy_result is None:
            candidates = retrieve_candidates(retriever, question)
        else:
            candidates = strategy_result

    # Anti-Redundancy: apply recent-chunks filter when method != normal AND
    # the user is not explicitly asking for a recap. Bypass otherwise.
    if method != "normal" and session_id and not _is_explicit_recap(question, turn_language_code) \
            and bool(getattr(cfg, "REDUNDANCY_RECAP_BYPASS", True)):
        from modules.system_detection.sd_repo import get_recent_chunk_ids
        recent_ids = get_recent_chunk_ids(session_id, token_id)
        if recent_ids:
            candidates = _apply_recent_chunk_filter(candidates, recent_ids, floor=_floor)

    # Toggle verifier via .env / Config.
    _flag = (getattr(cfg, "FAQ_VERIFICATOR", "on") or "on").strip().lower()
    _verif_on = _flag in ("1", "true", "on", "yes")
    filtered = grade_and_filter_yes(GRADER, candidates, question) if _verif_on else candidates

    filtered = _pad_to_floor(filtered, candidates, _floor)

    # Pin the definitional FAQ at position 0. Dedupe by content so we don't
    # double-insert if the biased retrieval already returned it.
    if def_doc is not None:
        def_content = def_doc.page_content
        rest = [d for d in filtered if d.page_content != def_content]
        filtered = [def_doc] + rest[: _floor - 1] if _floor > 0 else [def_doc] + rest

    ctx_str = render_context(filtered)
    # Scan ALL retrieved docs (not just top-4) so other-service backfill from
    # biased retrieval contributes to related_services. This ensures the
    # multi-service picker fires when biased retrieval returns, e.g., 4 ABMS
    # + 2 General — without this, extract_related_services would miss the
    # "General" entries and treat the turn as single-service direct handoff.
    related_services = extract_related_services(filtered, top_k=len(filtered))
    return filtered, ctx_str, related_services

def _need_meeting_start(question: str) -> bool:
    """Balik True kalau user berniat meeting tapi belum kasih day & slot lengkap."""
    try:
        is_meet, _ = detect_meeting_intent(question)
    except Exception:
        is_meet = False
    d = parse_date(question)
    ts, te, _ = parse_time_range(question)
    # start jika ada niat meeting, tapi tanggal atau jam belum lengkap
    return bool(is_meet and not (d and ts and te))

def _need_meeting_proposal(text: str) -> bool:
    # sederhana: ada tanggal & jam → kemungkinan proposal (bukan sekadar “mulai”)
    try:
        d = parse_date(text)
        ts, te, _ = parse_time_range(text)
        return bool(d and ts)
    except Exception:
        return False

# konfirmasi agenda calender
def detect_confirmation_intent(text: str) -> bool:
    """Deteksi user menyetujui atau mengkonfirmasi meeting (multi-bahasa)."""
    t = text.lower()
    confirm_words = [
        # Bahasa Indonesia
        "ya", "setuju", "konfirmasi", "oke", "baik", "benar", "cocok",
        # Bahasa Inggris
        "yes", "ok", "okay", "confirm", "sure", "sounds good", "works for me",
        # Bahasa Prancis dll (kalau mau)
        "oui", "d’accord", "bien"
    ]
    return any(w in t for w in confirm_words)

def _slugify_simple(s: str) -> str:
    s = (s or "").strip().lower()
    s = s.replace("&", " and ").replace("/", " ")
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-]+", "", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "item"

def _unique_preserve_order_str(items: List[str]) -> List[str]:
    seen, out = set(), []
    for x in items or []:
        k = (x or "").strip()
        if not k:
            continue
        low = k.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(k)
    return out

def to_picker(
    message_text: str,
    related_services: List[str] | None,
    *,
    max_choices: int = 6,
    value_prefix: str = ""
) -> Dict[str, Any]:

    # ambil unique labels
    raw_labels = _unique_preserve_order_str(related_services or [])[:max_choices]

    choices: List[Dict[str, Any]] = []
    seen_values: set[str] = set()

    for raw in raw_labels:
        key = raw.strip()
        if not key:
            continue

        # 1) Cari value berdasarkan SERVICE_VALUE_CODE_MAP
        code = SERVICE_VALUE_CODE_MAP.get(key)

        if code:
            value_code = code
            label_final = SERVICE_LABEL_CODE_MAP.get(code, key)
        else:
            # fallback kalau tidak ada di mapping
            value_code = _slugify_simple(key)
            label_final = key

        # prefix
        if value_prefix:
            value_code = f"{value_prefix}{value_code}"

        # hindari value yang duplikat
        if value_code in seen_values:
            continue
        seen_values.add(value_code)

        if value_code == "general_service":
            continue

        choices.append({
            "value": value_code,
            "label": label_final,
            "selected": False,
        })

    # 🔹 ALWAYS append generic "More Services" option
    extra_value = f"{value_prefix}more_services" if value_prefix else "more_services"
    if extra_value not in seen_values:
        choices.append({
            "value": extra_value,
            "label": "More Services",
            "selected": False,
        })

    qid = f"q-{uuid.uuid4().hex[:8]}"

    return {
        "type": "picker",
        "content": {
            "id": qid,
            "text": (message_text or "").strip(),
            "choices": choices,
        },
    }

def _plain_from_message_field(m: Any) -> str:
    """
    Selalu kembalikan string *teks* dari message apa pun:
    - jika string, return apa adanya
    - jika dict picker, ambil content.text
    - selain itu, cast ke str
    """
    if isinstance(m, str):
        return m
    if isinstance(m, dict):
        c = m.get("content") or {}
        t = c.get("text")
        if isinstance(t, str):
            return t
    return str(m or "")

def _picker_choices_from_message(message_obj: Any) -> list[dict]:
    """
    Extract picker choices from stored message payload.
    Supports:
    - {"type":"picker","content":{"choices":[...]}}
    - {"content":{"choices":[...]}}
    """
    if not isinstance(message_obj, dict):
        return []

    content = message_obj.get("content") or {}
    choices = content.get("choices")

    if isinstance(choices, list):
        return [c for c in choices if isinstance(c, dict)]

    return []

_RE_LINEBREAKS = re.compile(r"\s*\n+\s*")
_RE_SPACES = re.compile(r"[ \t\u00A0]{2,}")

def normalize_single_paragraph(text: str) -> str:
    """
    Paksa output jadi 1 paragraf:
    - hapus semua line breaks jadi spasi
    - rapikan spasi ganda
    """
    s = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    s = _RE_LINEBREAKS.sub(" ", s)
    s = _RE_SPACES.sub(" ", s)
    return s.strip()

def _fallback_language_from_history(session_id: str, token_id: str | None) -> tuple[str | None, str | None]:
    def _pick(rows: list[dict]) -> tuple[str | None, str | None]:
        for r in reversed(rows or []):
            ln = (r.get("language_name") or "").strip()
            if ln:
                low = ln.lower()
                if "indo" in low: return ("id", ln)
                if "english" in low: return ("en", ln)
                if "thai" in low: return ("th", ln)
                if "malay" in low: return ("ms", ln)
                if "french" in low: return ("fr", ln)
                if "german" in low or "deutsch" in low: return ("de", ln)
                if "dutch" in low or "nederlands" in low: return ("nl", ln)
                if "romanian" in low or "română" in low or "romana" in low: return ("ro", ln)
                if "japanese" in low or "日本語" in low: return ("ja", ln)
                if "russian" in low or "рус" in low: return ("ru", ln)
                if "italian" in low or "italiano" in low: return ("it", ln)
                if "chinese" in low or "mandarin" in low or "中文" in low:
                    # biasanya cukup 'zh' untuk kebutuhan prompt
                    return ("zh", ln)
                if "vietnamese" in low or "tiếng việt" in low or "viet" in low:
                    return ("vi", ln)
                return (None, ln)
        return (None, None)

    try:
        rows = read_language_history(session_id, token_id=token_id, limit=12)
        code, name = _pick(rows)
        if name:
            return code, name

        # ✅ fallback kedua: ignore token_id (session-only)
        rows2 = read_language_history(session_id, token_id=None, limit=12)
        return _pick(rows2)
    except Exception:
        return (None, None)

def _is_technical_language_input(text: str | None) -> bool:
    q = (text or "").strip()
    if not q:
        return True

    if q in {
        "BOOK_A_MEETING",
        "CONTINUE_QUALIFICATION",
        "OTHER_PICKED_SLOT",
    }:
        return True

    if q.startswith("PICKED_SLOT_"):
        return True
    if q.startswith("SA_SELECT_"):
        return True
    if RELATED_SERVICE_BATCH_RE.match(q):
        return True

    return False


def _pick_language_from_name_or_code(language_code: str | None, language_name: str | None) -> tuple[str | None, str | None]:
    lc = (language_code or "").strip().lower()
    ln = (language_name or "").strip()

    if lc:
        if lc == "en":
            return "en", ln or "English"
        if lc == "id":
            return "id", ln or "Indonesia"
        return lc, ln

    if ln:
        low = ln.lower()
        if "english" in low:
            return "en", ln
        if "indo" in low:
            return "id", ln
        return None, ln

    return None, None


def _majority_language_from_history(session_id: str, token_id: str | None) -> tuple[str | None, str | None]:
    """Return (code, name) of the MAJORITY language across non-technical user
    turns in this session/token's history.

    Replaces the old "lock to first natural turn" logic (2026-05-07): user
    feedback is that locking to first turn doesn't follow real conversation
    behavior. Now we tally language_code across ALL natural turns and return
    the most common — fallback ONLY for inputs where current-turn detection
    is unreliable (technical tokens like BOOK_A_MEETING, picker IDs).

    Empty history → (None, None).
    """
    from collections import Counter

    rows = _read_all_chat_pairs(session_id=session_id, token_id=token_id, limit=500) or []
    if not rows and token_id:
        rows = _read_all_chat_pairs(session_id=session_id, token_id=None, limit=500) or []

    code_count: Counter[str] = Counter()
    code_to_name: dict[str, str] = {}
    for row in rows:
        q = (row.get("question") or "").strip()
        if _is_technical_language_input(q):
            continue
        code, name = _pick_language_from_name_or_code(
            row.get("language_code"),
            row.get("language_name"),
        )
        if code:
            code_count[code] += 1
            if code not in code_to_name and name:
                code_to_name[code] = name

    if not code_count:
        return None, None
    majority_code, _ = code_count.most_common(1)[0]
    return majority_code, code_to_name.get(majority_code)


# DEPRECATED 2026-05-07: kept as alias for any out-of-tree callers; new code
# should call `_majority_language_from_history` directly. The "lock to first
# natural turn" semantics caused user-reported bug where reply language
# stayed Indonesian even after user switched to English mid-conversation.
def _get_locked_language_from_history(session_id: str, token_id: str | None) -> tuple[str | None, str | None]:
    return _majority_language_from_history(session_id, token_id)

def _call_service_agent_http(session_id: str, question: str, token_id: str | None = None) -> dict:
    """
    Forward payload yg sama persis ke endpoint /service-agent.
    """
    base_url = cfg.PUBLIC_BASE_URL or f"http://127.0.0.1:{cfg.PORT_CHATBOT}"
    url = base_url.rstrip("/") + "/rag-assistant/chatbot/claude4sonnet/service-agent"

    headers = {
        # kunci internal khusus service agent
        cfg.SERVICE_AGENT_API_HEADER_NAME: cfg.SERVICE_AGENT_API_KEY,
        # kalau mau, bisa ikutkan API utama juga (opsional):
        # cfg.API_HEADER_NAME: cfg.API_KEY,
        "Content-Type": "application/json",
    }

    payload: dict[str, Any] = {
        "session_id": session_id,
        "question": question,
    }
    if token_id:
        payload["token_id"] = token_id

    resp = requests.post(url, json=payload, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()

def _maybe_build_summary_meta(
    *,
    session_id: str,
    token_id: str | None,
    first_turn: bool,
    language_name_hint: str | None = None,
):
    """
    Return: (summary_block_text_or_None, summarization_meta_dict)
    summarization_meta_dict sesuai schema SummarizationMeta (nested).
    """
    if _fast_mode_on():
        return None, default_summarization_meta().dict()

    if (cfg.CHAT_HISTORY_SCHEMA or "last3").lower() != "allsum":
        return None, default_summarization_meta().dict()

    if first_turn:
        return None, default_summarization_meta().dict()

    # Non-blocking mode: pakai cache summary terakhir (jika ada).
    summary_block, sm = _get_cached_summary(session_id, token_id)
    if sm:
        return summary_block, sm

    return None, default_summarization_meta().dict()
    
def _sa_is_active(session_id: str | None) -> bool:
    try:
        #  pakai repo yang sudah benar (punya mongo_client) dari SA_ENGINE
        from modules.service_agent.sa_service import SA_ENGINE

        st = SA_ENGINE.repo.get_state(session_id)
        if not st:
            return False

        status = (getattr(st, "status", "") or "").lower()
        return status.startswith("ongoing") or status == "completed"  # atau status != "completed"
    except Exception:
        return False
    
def _is_ma_service_choice(question: str | None) -> bool:
    q = (question or "").strip()
    return q.startswith("MA_ARRANGEMENT_")


_SLOT_VALUE_RE = re.compile(
    r"^PICKED_SLOT_(\d{2})(\d{2})(\d{4})_(\d{2})h(\d{2})-(\d{2})h(\d{2})_(.+)$"
)
_OTHER_SERVICE_BATCH_RE = re.compile(r"^MA_ARRANGEMENT_other_batch(\d+)$", re.I)


def _is_ma_slot_choice(question: str | None) -> bool:
    q = (question or "").strip()
    return q.startswith("PICKED_SLOT_") or q == "OTHER_PICKED_SLOT"


def _parse_slot_choice_value(value: str) -> dict | None:
    m = _SLOT_VALUE_RE.match(value or "")
    if not m:
        return None
    day_iso = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    start = f"{m.group(4)}:{m.group(5)}"
    end = f"{m.group(6)}:{m.group(7)}"
    return {
        "date_iso": day_iso,
        "start": start,
        "end": end,
        "slot_label": f"{start} - {end}",
        "tz_tag": m.group(8),
    }

def _slot_choice_datetimes(slot_meta: dict, timezone_name: str | None) -> tuple[datetime, datetime]:
    """
    Convert parsed slot metadata into timezone-aware datetimes.
    """
    tz_name = (timezone_name or "Asia/Jakarta").strip() or "Asia/Jakarta"
    try:
        zone = ZoneInfo(tz_name)
    except Exception:
        zone = ZoneInfo("Asia/Jakarta")
    date_iso = slot_meta.get("date_iso")
    if not date_iso:
        raise ValueError("Missing slot date")
    day = datetime.fromisoformat(date_iso).date()

    def _hm(key: str) -> tuple[int, int]:
        txt = slot_meta.get(key) or ""
        h, m = txt.split(":")
        return int(h), int(m)

    sh, sm = _hm("start")
    eh, em = _hm("end")
    start_dt = datetime(day.year, day.month, day.day, sh, sm, tzinfo=zone)
    end_dt = datetime(day.year, day.month, day.day, eh, em, tzinfo=zone)
    return start_dt, end_dt
    
def _build_sa_quotation_footer(*, question: str, language_code: str, sa_state: dict) -> str:
    """Task 21 — quotation-only footer extracted from `_build_sa_post_footer`.

    Runs when `OOC_AGENT_ENABLED=on` to preserve quotation-footer behavior at mid-flow.
    The OOC-append logic stays inside `_build_sa_post_footer` (called only when flag=off
    to preserve Q#5 latent infrastructure + byte-identical legacy behavior).

    Phase 1 ledger entry: quotation logic is duplicated across this helper and
    `_build_sa_post_footer`. Consolidate when Q#5 secondary-OOC scope is defined.
    """
    q = (question or "").strip()
    if not q:
        return ""
    # 1) jangan ganggu command SA_SELECT_  (mirror of _build_sa_post_footer guard)
    if q.startswith(SA_POL.SERVICE_AGENT_PREFIX):
        return ""

    parts: list[str] = []

    # 2) quotation footer (mirror of _build_sa_post_footer lines 1605-1612)
    try:
        if is_quotation_request(q, language_code):
            ft = build_quotation_footer(language_code)
            if ft:
                parts.append(ft.strip())
    except Exception:
        pass

    return "\n\n".join([p for p in parts if p])


def _build_sa_post_footer(*, question: str, language_code: str, sa_state: dict) -> str:
    q = (question or "").strip()
    if not q:
        return ""

    # 1) jangan ganggu command SA_SELECT_
    if q.startswith(SA_POL.SERVICE_AGENT_PREFIX):
        return ""

    parts: list[str] = []

    # 2) quotation footer
    try:
        if is_quotation_request(q, language_code):
            ft = build_quotation_footer(language_code)
            if ft:
                parts.append(ft.strip())
    except Exception:
        pass

    # 3) OOC (freelance/partnership) footer — STRICT intent-phrase mode.
    #    Append-only: SA flow continues uninterrupted. The redirect link is
    #    shown as an alert alongside the SA reply when — and only when — the
    #    user's text contains an explicit "want to be / become / join as ..."
    #    phrase (e.g. "jadi mitra", "menjadi freelancer", "reseller program").
    #    Single-keyword matches like "kerja sama" NO LONGER trigger this
    #    footer mid-flow, avoiding the false-positive you saw earlier.
    try:
        from modules.out_of_context.ooc_policies import (
            classify_intent_phrase_strict, build_reply, OOCPolicies,
        )
        label = classify_intent_phrase_strict(q)
        if label in ("freelance", "partnership"):
            _pol = OOCPolicies()
            msg = build_reply(
                label,
                language_code=language_code,
                freelancer_url=_pol.freelancer_url,
                partner_url=_pol.partner_url,
            )
            if msg:
                parts.append(msg.strip())
    except Exception:
        pass

    return "\n\n".join([p for p in parts if p])

def _final_gate_choices(language_code: str | None) -> list[dict]:
    """Picker choices shown when explicit meeting intent is detected.

    Previously included a `START_NEW_CHAT` option; removed because Crisp's
    native "start a new chat" action handles reset. Now this returns only the
    `BOOK_A_MEETING` choice.
    """
    lc = (language_code or "").strip().lower()

    # Default (English)
    label = "Book a meeting"
    if lc.startswith("id"):
        label = "Jadwalkan meeting"
    elif lc.startswith("ms"):
        label = "Tempah mesyuarat"
    elif lc.startswith("th"):
        label = "นัดหมายการประชุม"
    elif lc.startswith("fr"):
        label = "Planifier une réunion"
    elif lc.startswith("ru"):
        label = "Назначить встречу"
    elif lc.startswith("ja"):
        label = "打ち合わせを予約"
    elif lc.startswith("zh"):
        label = "预约会议"
    elif lc.startswith("de"):
        label = "Meeting vereinbaren"
    elif lc.startswith("it"):
        label = "Prenota una riunione"
    elif lc.startswith("ro"):
        label = "Programează o întâlnire"

    return [
        {"value": "BOOK_A_MEETING", "label": label, "selected": False},
    ]


def _book_meeting_choice(language_code: str | None) -> dict:
    for choice in _final_gate_choices(language_code):
        if (choice.get("value") or "").upper() == "BOOK_A_MEETING":
            return {
                "value": "BOOK_A_MEETING",
                "label": choice.get("label") or "Book a meeting",
                "selected": False,
            }
    return {"value": "BOOK_A_MEETING", "label": "Book a meeting", "selected": False}


def _value_has_content(val) -> bool:
    if isinstance(val, str):
        return bool(val.strip())
    if isinstance(val, dict):
        for v in val.values():
            if isinstance(v, str) and v.strip():
                return True
            if v and not isinstance(v, str):
                return True
        return False
    if isinstance(val, list):
        for v in val:
            if isinstance(v, str) and v.strip():
                return True
            if v and not isinstance(v, str):
                return True
        return False
    return bool(val)


def _count_completed_sa_answers(answers: dict | None) -> int:
    if not isinstance(answers, dict):
        return 0
    total = 0
    for v in answers.values():
        if _value_has_content(v):
            total += 1
    return total


def _infer_question_index(current_step, state) -> int:
    try:
        answers = getattr(state, "answers", {}) or {}
    except Exception:
        answers = {}
    answered = _count_completed_sa_answers(answers)
    if answered > 0:
        return answered

    try:
        order_val = getattr(current_step, "order", None)
        if isinstance(order_val, (int, float)):
            order_int = int(order_val)
            if order_int > 0:
                return order_int
    except Exception:
        pass
    return 0

# ===== Cross-service bridge (Stage 3B v0 — 2026-05-08) =====
# When user asks about a DIFFERENT service while in mid-qualification, the chatbot
# previously said "tidak tahu / belum tersedia" because retrieval was pinned to
# the current service. This MVP fix:
#   1. Detect explicit mention of another service in user question (Q3=A: strict).
#   2. Fan-out retrieval across BOTH current + target service collections (Stage 3A
#      `retrieve_from_collections`).
#   3. Compose a brief answer using the combined context.
#   4. Append a stay/switch picker [SA_STAY, SA_SELECT_<target>] (Q1=B: optional —
#      user can ignore and free-form).
# State preservation (Q2=B-extended: paused_services for sales report) is a
# follow-up — current MVP just lets SA_SELECT_<target> reset state via existing
# handler. To be enhanced when multi-service lead aggregation lands.

def _detect_cross_service_target(
    user_question: str,
    current_service_code: str | None,
    current_service_label: str | None,
) -> dict | None:
    """Strict detector: user explicitly mentions a service that's NOT the current one.

    Returns {short_label, value_code, full_label, flow_code} or None.
    """
    q = (user_question or "").strip().lower()
    if not q:
        return None
    cur_code = (current_service_code or "").strip().upper()
    cur_label = (current_service_label or "").strip().lower()

    candidates: list[tuple[str, str, str, str, int]] = []
    # Build candidate list from SA policy maps. Priority: longer string match first
    # so "Background Check" beats accidental "EBS" substring inside
    # an unrelated word.
    for short_label, flow_code in (SA_POL.VALUE_TO_FLOW_CODE or {}).items():
        if not flow_code:
            continue
        # Skip current service
        if flow_code.upper() == cur_code:
            continue
        if (short_label or "").strip().lower() == cur_label:
            continue
        if short_label.strip().lower() == "general":
            continue  # general is not a pickable target
        value_code = (SA_POL.SERVICE_VALUE_CODE_MAP or {}).get(short_label)
        if not value_code:
            continue
        full_label = SERVICE_LABEL_CODE_MAP.get(value_code, short_label)
        # Each candidate gets a "match length" priority — longer string first
        for needle in (full_label, short_label):
            n_lower = (needle or "").strip().lower()
            if not n_lower:
                continue
            candidates.append((short_label, value_code, full_label, flow_code, len(n_lower)))

    # Sort by match length descending so we try longest needles first
    candidates.sort(key=lambda c: -c[4])
    seen_value_codes: set[str] = set()
    for short_label, value_code, full_label, flow_code, _length in candidates:
        if value_code in seen_value_codes:
            continue
        # Match either short or full label as substring (case-insensitive)
        for needle in (full_label, short_label):
            n_lower = (needle or "").strip().lower()
            if not n_lower:
                continue
            # Word-boundary-ish check: short labels (≤4 chars) must be word-bounded
            # to avoid false positives like "AST" inside "fast" — use simple regex.
            if len(n_lower) <= 4:
                import re as _re
                if _re.search(r"\b" + _re.escape(n_lower) + r"\b", q):
                    seen_value_codes.add(value_code)
                    return {
                        "short_label": short_label,
                        "value_code": value_code,
                        "full_label": full_label,
                        "flow_code": flow_code,
                    }
            else:
                if n_lower in q:
                    seen_value_codes.add(value_code)
                    return {
                        "short_label": short_label,
                        "value_code": value_code,
                        "full_label": full_label,
                        "flow_code": flow_code,
                    }
    return None


_SA_STAY_PREFIX = "SA_STAY_"


def _parse_sa_stay_value(value: str) -> tuple[str, str] | None:
    """Parse SA_STAY_<source_value_code>_to_<target_value_code>. Returns (source, target) or None.

    Examples:
      'SA_STAY_whistleblowing_hotline_to_background_check' →
        ('whistleblowing_hotline', 'background_check')
      'SA_STAY' (legacy) → None
      'SA_SELECT_x' → None
    """
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    if not v.startswith(_SA_STAY_PREFIX):
        return None
    body = v[len(_SA_STAY_PREFIX):]
    if "_to_" not in body:
        return None
    source, _, target = body.partition("_to_")
    source, target = source.strip(), target.strip()
    if not source or not target:
        return None
    return (source, target)


def _stay_ack_phrase(language_code: str | None, current_label: str) -> str:
    """Short, polite acknowledgement that user wants to stay in current service.

    Used when user clicks SA_STAY_* picker. Avoids LLM call — deterministic
    phrasing in user's language.
    """
    lc = (language_code or "").strip().lower()[:2]
    table = {
        "id": f"Baik, mari kita lanjutkan kualifikasi untuk {current_label}.",
        "ms": f"Baik, mari kita teruskan kelayakan untuk {current_label}.",
        "en": f"Sure, let's continue with the {current_label} qualification.",
        "fr": f"Très bien, continuons la qualification pour {current_label}.",
        "de": f"Gut, fahren wir mit der Qualifizierung für {current_label} fort.",
        "it": f"Bene, continuiamo la qualificazione per {current_label}.",
        "pt": f"Certo, vamos continuar com a qualificação de {current_label}.",
        "es": f"Bien, continuemos con la calificación de {current_label}.",
        "vi": f"Được, hãy tiếp tục quá trình xác định nhu cầu cho {current_label}.",
        "th": f"เยี่ยม มาดำเนินการคุณสมบัติสำหรับ {current_label} ต่อ",
        "da": f"Godt, lad os fortsætte med kvalificeringen for {current_label}.",
        "zh": f"好的，让我们继续 {current_label} 的资质评估。",
        "ja": f"承知しました、{current_label} の確認を続けましょう。",
        "ru": f"Хорошо, продолжим оценку для {current_label}.",
    }
    return table.get(lc, table["en"])


def _render_sa_stay_continuation(
    *,
    session_id: str,
    token_id: str | None,
    sa_state: dict,
    parsed_stay: tuple[str, str],
    summary_meta_cache: dict | None,
    request_started_at: float | None,
    turn_language_code: str,
    turn_language_name: str,
    resolved_nick: str | None,
) -> dict:
    """User clicked SA_STAY_<source>_to_<target> picker — they want to stay in
    current service. Ack + re-ask current qualification question. No LLM call;
    no state mutation (answers untouched, status unchanged)."""
    from modules.service_agent.sa_flows import FLOW_REGISTRY

    current_service_code = (sa_state.get("service_code") or "").strip()
    current_service_label = (sa_state.get("service_label") or "").strip()
    current_question_id = (sa_state.get("question_id") or "").strip()

    # Get current qualification question text
    current_q_text = ""
    try:
        flow = FLOW_REGISTRY.get(current_service_code) or {}
        step = flow.get(current_question_id)
        if step is not None:
            current_q_text = (getattr(step, "text", "") or "").strip()
    except Exception:
        pass

    language_code = (turn_language_code or "").strip() or "id"
    language_name = (turn_language_name or "").strip() or "Indonesia"

    ack = _stay_ack_phrase(language_code, current_service_label or current_service_code)
    full_text = f"{ack} {current_q_text}".strip()

    msg_obj = build_string_message(full_text)

    sm_in = int((summary_meta_cache or {}).get("input_tokens") or 0)
    sm_out = int((summary_meta_cache or {}).get("output_tokens") or 0)

    payload = build_chat_turn_payload(
        ts=datetime.now(WIB).isoformat(),
        question=f"{_SA_STAY_PREFIX}{parsed_stay[0]}_to_{parsed_stay[1]}",
        message=msg_obj,
        prompt_applied="(no LLM — SA_STAY deterministic ack)",
        language_name=language_name,
        user_nick=resolved_nick or "",
        route="sa_stay_continuation",
        related_services=[current_service_label] if current_service_label else [],
        docs_retrieved_count=0,
        respond_duration=0.0,
        input_token=0,
        output_token=0,
        input_total=sm_in,
        output_total=sm_out,
        summarization_meta=(summary_meta_cache or default_summarization_meta()),
        extra={
            "service_code": current_service_code,
            "service_label": current_service_label,
            "answers": (sa_state.get("extra") or {}).get("answers") or sa_state.get("answers") or {},
            "status": sa_state.get("status") or "",
            "sa_stay_routing": {"source": parsed_stay[0], "target": parsed_stay[1]},
        },
    )

    result = {"session_id": session_id, **payload}
    result = _finalize_result_language(result, language_code, language_name)
    if request_started_at is not None:
        _attach_request_total_duration(result, request_started_at)
    return result


def _stay_switch_labels(language_code: str | None, current_label: str, target_label: str) -> tuple[str, str]:
    """Picker labels in user's language. Falls back to English.

    Task 17 (2026-05-13): primary path reads from i18n loader (picker.stay_label
    + picker.switch_label); legacy `table` dict as defensive fallback.
    """
    lc = (language_code or "").strip().lower()[:2]
    try:
        from modules.i18n import t as _t
        stay = _t("picker.stay_label", lc, current_label=current_label)
        switch = _t("picker.switch_label", lc, target_label=target_label)
        return (stay, switch)
    except Exception:
        return (f"Continue {current_label}", f"Switch to {target_label}")
    # Task 19 (2026-05-13): legacy table dict dead code — superseded by i18n loader above
    table = {
        "id": (f"Lanjut {current_label}", f"Pindah ke {target_label}"),
        "ms": (f"Teruskan {current_label}", f"Tukar ke {target_label}"),
        "en": (f"Continue {current_label}", f"Switch to {target_label}"),
        "fr": (f"Continuer {current_label}", f"Passer à {target_label}"),
        "de": (f"{current_label} fortsetzen", f"Zu {target_label} wechseln"),
        "it": (f"Continua {current_label}", f"Passa a {target_label}"),
        "pt": (f"Continuar {current_label}", f"Mudar para {target_label}"),
        "es": (f"Continuar {current_label}", f"Cambiar a {target_label}"),
        "vi": (f"Tiếp tục {current_label}", f"Chuyển sang {target_label}"),
        "th": (f"ดำเนินการ {current_label} ต่อ", f"เปลี่ยนเป็น {target_label}"),
        "da": (f"Fortsæt {current_label}", f"Skift til {target_label}"),
        "zh": (f"继续 {current_label}", f"切换到 {target_label}"),
        "ja": (f"{current_label} を続ける", f"{target_label} に切り替え"),
        "ru": (f"Продолжить {current_label}", f"Перейти к {target_label}"),
    }
    return table.get(lc, table["en"])


def _render_sa_cross_service_bridge(
    *,
    session_id: str,
    token_id: str | None,
    user_question: str,
    resolved_nick: str | None,
    sa_state: dict,
    target: dict,
    summary_block_cache: str | None,
    summary_meta_cache: dict | None,
    request_started_at: float | None,
    turn_language_code: str,
    turn_language_name: str,
) -> dict:
    """Compose a bridge reply: briefly answers about target service using combined
    context, then offers stay/switch picker."""
    current_service_code = (sa_state.get("service_code") or "").strip()
    current_service_label = (sa_state.get("service_label") or "").strip()
    target_full_label = target["full_label"]
    target_short_label = target["short_label"]
    target_value_code = target["value_code"]

    # Resolve collection IDs for Stage 3A retrieve_from_collections
    from modules.system_detection import sd_vector_repo as _svr
    current_id = _svr._resolve_alias_to_service_id([current_service_code, current_service_label])
    target_id = _svr._resolve_alias_to_service_id([target_short_label, target_full_label])

    candidate_ids = [sid for sid in (current_id, target_id) if sid and sid in _svr._vectorstores]

    method = (getattr(cfg, "REDUNDANCY_METHOD", "normal") or "normal").strip().lower()
    rc_ctx = ResolutionContext(service_id=(target_id or current_id))

    # For the bridge path we use the TARGET service's vectorstore for the
    # strategy call (the user's question is about the target service).
    strategy_vs = _svr._vectorstores.get(target_id) if target_id else None
    strategy_result = retrieve_with_strategy(
        method, user_question, scope="fan_out", k=4,
        vectorstore=strategy_vs, ctx=rc_ctx,
    )

    if strategy_result is not None:
        docs = strategy_result
    elif len(candidate_ids) < 2:
        # Fallback: use legacy retrieval that combines aliases for both services.
        # Still gives the LLM both-service context, just via metadata filter.
        combined_aliases = list(_service_aliases(current_service_label) or []) + \
                          list(_service_aliases(target_full_label) or [])
        try:
            docs = retrieve_service_biased(user_question, combined_aliases, same_k=2, other_k=2)
        except Exception:
            docs = []
    else:
        docs = _svr.retrieve_from_collections(candidate_ids, user_question, total_k=4)

    ctx_str = render_context(docs[:4]) if docs else ""

    # Build language meta
    language_code = (turn_language_code or "").strip() or "id"
    language_name = (turn_language_name or "").strip() or "Indonesia"

    _method_br = (getattr(cfg, "REDUNDANCY_METHOD", "normal") or "normal").strip().lower()
    if _method_br != "normal" and not _is_explicit_recap(user_question, language_code) \
            and bool(getattr(cfg, "REDUNDANCY_RECAP_BYPASS", True)):
        from modules.system_detection.sd_repo import get_recent_chunk_ids
        recent_ids = get_recent_chunk_ids(session_id, token_id)
        if recent_ids:
            docs = _apply_recent_chunk_filter(docs, recent_ids, floor=4)

    # Compose bridge prompt
    bridge_prompt = (
        f"You are an AI consultant. The user is currently in the qualification flow for "
        f"'{current_service_label}'. They just asked about '{target_full_label}' — a DIFFERENT "
        f"service. Below is combined context from BOTH services' knowledge bases. Use it to "
        f"briefly answer about '{target_full_label}' (≤3 sentences), then in 1 final sentence "
        f"ask the user which service they would like to focus on next: continue with "
        f"'{current_service_label}' (current) or switch to '{target_full_label}'.\n\n"
        f"Reply STRICTLY in {language_name} as a SINGLE paragraph. Use formal 'Anda' if Indonesia/Malaysia. "
        f"Do NOT include any picker text — the UI will render the picker. Do NOT say 'tidak tahu' "
        f"or 'tidak tersedia' — the context below covers what's needed.\n\n"
        f"User question:\n{user_question}\n\n"
        f"Combined context (current + target service):\n{ctx_str}\n"
    )

    if _method_br != "normal":
        from modules.system_detection.sd_prompts import apply_dedup_guidelines
        bridge_prompt = apply_dedup_guidelines(bridge_prompt, language_name)

    from langchain_core.messages import SystemMessage, HumanMessage
    messages = [
        SystemMessage(content=bridge_prompt),
        HumanMessage(content=user_question),
    ]
    with audit_llm_call(
        route="system_detection",
        stage="sa_cross_service_bridge",
        session_id=session_id,
        token_id=token_id,
        prompt=messages,
        extras={"retrieval_method": _method_br},
    ) as ctx:
        msg = ASK_LLM.invoke(messages, config={"max_tokens": 400})
        ctx.set_response_from_message(msg)

    reply_text = normalize_single_paragraph(getattr(msg, "content", str(msg)))
    in_tok = ctx.input_tokens
    out_tok = ctx.output_tokens

    # Build picker.
    # SA_STAY value encodes BOTH current and target services for self-documenting
    # routing + audit clarity: "SA_STAY_<current_value_code>_to_<target_value_code>".
    # Pattern mirrors SA_SELECT_<value_code> — both are parseable from the value alone.
    # Source resolution: state.service_code is the SHORT flow code (e.g. "WBS").
    # SA_POL.SERVICE_VALUE_CODE_MAP keys ARE those short codes → value_code.
    current_value_code = (
        SA_POL.SERVICE_VALUE_CODE_MAP.get(current_service_code.strip())
        or SA_POL.SERVICE_VALUE_CODE_MAP.get(current_service_code.strip().upper())
        or (current_service_code or "").strip().lower()
    )
    sa_stay_value = f"SA_STAY_{current_value_code}_to_{target_value_code}"
    stay_label, switch_label = _stay_switch_labels(language_code, current_service_label, target_full_label)
    choices = [
        {"value": sa_stay_value, "label": stay_label, "selected": False},
        {"value": f"{SA_POL.SERVICE_AGENT_PREFIX}{target_value_code}", "label": switch_label, "selected": False},
    ]
    msg_obj = build_picker_message(text=reply_text, choices=choices, required=False)

    # Summary meta (passthrough)
    sm_in = int((summary_meta_cache or {}).get("input_tokens") or 0)
    sm_out = int((summary_meta_cache or {}).get("output_tokens") or 0)

    payload = build_chat_turn_payload(
        ts=datetime.now(WIB).isoformat(),
        question=user_question,
        message=msg_obj,
        prompt_applied=bridge_prompt,
        language_name=language_name,
        user_nick=resolved_nick or "",
        route="sa_cross_service_bridge",
        related_services=[current_service_label, target_full_label],
        docs_retrieved_count=len(docs[:4]),
        respond_duration=0.0,
        input_token=in_tok,
        output_token=out_tok,
        input_total=in_tok + sm_in,
        output_total=out_tok + sm_out,
        summarization_meta=(summary_meta_cache or default_summarization_meta()),
        extra={
            "service_code": current_service_code,
            "service_label": current_service_label,
            "answers": (sa_state.get("extra") or {}).get("answers") or sa_state.get("answers") or {},
            "status": sa_state.get("status") or "",
            "cross_service_target": {
                "value_code": target_value_code,
                "label": target_full_label,
                "flow_code": target["flow_code"],
            },
            "retrieval_method": _method_br,
        },
    )

    result = {"session_id": session_id, **payload}
    result = _finalize_result_language(result, language_code, language_name)
    if request_started_at is not None:
        _attach_request_total_duration(result, request_started_at)
    if _method_br != "normal" and not _is_explicit_recap(user_question, language_code) \
            and bool(getattr(cfg, "REDUNDANCY_RECAP_BYPASS", True)):
        from modules.system_detection.sd_repo import update_recent_chunk_ids
        update_recent_chunk_ids(session_id, token_id, _extract_chunk_ids_from_docs(docs[:4]))
    return result


def _lock_qualification_method(state) -> None:
    """Lock state.qualification_method on first call. Subsequent calls honor stored value.

    Called from the SA continuation dispatcher. If state has no field yet (legacy
    doc OR brand-new session), read QUALIFICATION_METHOD from env ONCE and write
    to state. After that, ignore env — protects in-flight sessions from mid-flight
    method switches when operator flips env.
    """
    if getattr(state, "qualification_method", None) is None:
        chosen = (os.getenv("QUALIFICATION_METHOD", "two_decision_tree") or "two_decision_tree").strip().lower()
        state.qualification_method = chosen


def _should_use_method_b(state) -> bool:
    """Returns True iff this state should use Method B (natural_qualification)."""
    return getattr(state, "qualification_method", None) == "natural_qualification"


def _render_sa_continue_via_sd(
    *,
    session_id: str,
    token_id: str | None,
    user_question: str,
    resolved_nick: str | None,
    first_turn: bool,
    sm: dict,
    sa_state: dict,
    summary_block_cache: str | None = None,
    summary_meta_cache: dict | None = None,
    request_started_at: float | None = None,
    turn_language_code: str = "",
    turn_language_name: str = "",
) -> dict:
    """
    Render prompt + panggil LLM + build payload untuk SA continue (ongoing / completed),
    tapi state transition tetap dikerjakan SA_ENGINE (sa_service.py).

    `turn_language_code` / `turn_language_name`: bahasa hasil deteksi Claude untuk
    INPUT TURN INI (fresh from `build_language_meta` di handle_chat). Mengontrol
    bahasa output reply per turn (post-2026-05-07 policy: per-turn detection
    wins, no first-turn lock). Empty = fallback ke state.language_code.
    """

    from modules.service_agent.sa_service import SA_ENGINE as SA_ENGINE

    # === Stage 4 (2026-05-12) — qualification method toggle ===
    # Lock state.qualification_method at first dispatch (no-op if already set).
    # Then route to Method B if state opted in; otherwise fall through to the
    # existing Method A code path below (untouched).
    _state_obj = SA_ENGINE.repo.get_state(session_id)
    if _state_obj is not None:
        _lock_qualification_method(_state_obj)
        if _should_use_method_b(_state_obj):
            from modules.service_agent.natural_qual import handle_turn as _nq_handle_turn
            from modules.system_detection.sd_repo import read_user_profile_from_sessions
            SA_ENGINE.repo.upsert_state(_state_obj)
            crisp_profile = read_user_profile_from_sessions(session_id) or {}
            turn_result = _nq_handle_turn(
                _state_obj,
                user_message=user_question,
                crisp_profile=crisp_profile,
                language_code=turn_language_code or _state_obj.language_code or "en",
                token_id=token_id,
            )
            SA_ENGINE.repo.upsert_state(_state_obj)
            # 2026-05-18: render a real picker (not a plain string) when
            # picker_offered=True so the user actually sees a BOOK_A_MEETING
            # button. Drives `MEETING_POPUP=N` cadence (cadence reason
            # `meeting_popup_cadence_*`) and the existing keyword / min-set
            # intent triggers uniformly.
            _b_lang_code = turn_language_code or _state_obj.language_code or "en"
            if turn_result.get("picker_offered"):
                msg_obj = build_picker_message(
                    text=turn_result["assistant_message"],
                    choices=[_book_meeting_choice(_b_lang_code)],
                    required=False,
                )
            else:
                msg_obj = build_string_message(turn_result["assistant_message"])
            payload = build_chat_turn_payload(
                question=user_question,
                message=msg_obj,
                prompt_applied=(turn_result.get("prompt_applied") or "(no LLM — Method B)"),
                language_name=turn_language_name or _state_obj.language_name or "English",
                user_nick=resolved_nick or "",
                route="qualification_b",
                related_services=[_state_obj.service_label],
                docs_retrieved_count=0,
                respond_duration=0.0,
                input_token=0,
                output_token=0,
                input_total=0,
                output_total=0,
                summarization_meta=None,
                extra={
                    "qualification_method": "natural_qualification",
                    "service_code": _state_obj.service_code,
                    "service_label": _state_obj.service_label,
                    "answers": dict(_state_obj.answers),
                    "status": _state_obj.status,
                    "target_field": turn_result.get("target_field"),
                    "intent_score": turn_result.get("intent_score"),
                    "rescue_fired": turn_result.get("rescue_fired"),
                    "rescue_field": turn_result.get("rescue_field"),
                    "fallback_skipped_fields": list(_state_obj.fallback_skipped_fields),
                    "picker_offered": turn_result.get("picker_offered"),
                    "picker_offer_reason": turn_result.get("picker_offer_reason"),
                    "min_set_complete": turn_result.get("min_set_complete"),
                    # Stage 4.5 audit additions (propagate from turn_result)
                    "interest_signal": turn_result.get("interest_signal"),
                    "verbatim_retry_fired": turn_result.get("verbatim_retry_fired"),
                    "field_writes_sources": turn_result.get("field_writes_sources"),
                    "consistency_warns_count": turn_result.get("consistency_warns_count"),
                    "fields_written": turn_result.get("fields_written"),
                    "dry_count_snapshot": turn_result.get("dry_count_snapshot"),
                    "popup_shown_counts": list(_state_obj.popup_shown_counts or []),
                },
            )
            result = {"session_id": session_id, **payload}
            result = _finalize_result_language(
                result,
                turn_language_code or _state_obj.language_code or "en",
                turn_language_name or _state_obj.language_name or "English",
            )
            if request_started_at is not None:
                _attach_request_total_duration(result, request_started_at)
            return result
    # ↓↓↓ Existing Method A code path resumes below — UNTOUCHED ↓↓↓

    # 0) load current SA step bundle (pure)
    bundle = SA_ENGINE.get_current_step_bundle(session_id)
    current_q_text = bundle["current_step"].text
    next_q_text = bundle.get("next_step_text") or current_q_text

    if not bundle.get("ok"):
        # fallback
        ...

    state = bundle["state"]
    step = bundle["current_step"]
    current_q_text = getattr(step, "text", "") or ""
    prev_q_text = current_q_text  # simpan snapshot sebelum commit

    # ── COMPLETED GATE: qualification selesai → langsung sodorkan BOOK_A_MEETING ──
    _sa_status_now = (getattr(state, "status", "") or "").lower()
    if _sa_status_now == "completed":
        _svc_lbl_c = (getattr(state, "service_label", "") or sa_state.get("service_label", "") or "").strip()
        # Policy 2026-05-07: per-turn fresh detection wins (parameter
        # `turn_language_code`/`turn_language_name` dari handle_chat). State
        # value (set di turn lampau) hanya fallback. Untuk input technical
        # (BOOK_A_MEETING dll) → fallback ke majority history.
        _lang_c = (turn_language_code or "").strip()
        _langn_c = (turn_language_name or "").strip()

        if not _lang_c:
            # Fallback: state, lalu sa_state, lalu majority/technical heuristic.
            _lang_c = (getattr(state, "language_code", "") or sa_state.get("language_code", "") or "").strip()
            _langn_c = (getattr(state, "language_name", "") or sa_state.get("language_name", "") or "").strip()

        if _is_technical_language_input(user_question or "") and not turn_language_code:
            _maj_c, _maj_n = _majority_language_from_history(session_id, token_id)
            _lang_c = _lang_c or _maj_c or ""
            _langn_c = _langn_c or _maj_n or ""

        if not _lang_c and _langn_c:
            low = _langn_c.lower()
            if "english" in low:
                _lang_c = "en"
            elif "indo" in low:
                _lang_c = "id"

        if not _langn_c and _lang_c:
            if _lang_c == "en":
                _langn_c = "English"
            elif _lang_c == "id":
                _langn_c = "Indonesia"

        if not _lang_c:
            _lang_c = "en"
        if not _langn_c:
            _langn_c = "English"

        history_block_c, summary_block_c, _ = _build_history_blocks(
            session_id, token_id,
            precomputed_summary_block=summary_block_cache,
            precomputed_summary_meta=summary_meta_cache,
        )

        rendered_prompt_c = render_serviceagent_prompt_final(
            language_name=_langn_c,
            service_label=_svc_lbl_c,
            user_answer=user_question,
            is_first_turn=first_turn,
            user_nick=resolved_nick,
            language_code=_lang_c,
            chat_history_block=history_block_c,
            chat_summary_block=summary_block_c,
        )
        _method_c = (getattr(cfg, "REDUNDANCY_METHOD", "normal") or "normal").strip().lower()
        if _method_c != "normal":
            from modules.system_detection.sd_prompts import apply_dedup_guidelines
            rendered_prompt_c = apply_dedup_guidelines(rendered_prompt_c, _langn_c)

        prompt_msgs_route_c = [SystemMessage(content=rendered_prompt_c), HumanMessage(content=user_question)]
        with audit_llm_call(
            route="system_detection",
            stage="route_c_compose",
            session_id=session_id,
            token_id=token_id,
            prompt=prompt_msgs_route_c,
            extras={"retrieval_method": _method_c},
        ) as ctx:
            _msg_c = BRIEF_LLM.invoke(prompt_msgs_route_c)
            ctx.set_response_from_message(_msg_c)
        _text_c = normalize_single_paragraph(getattr(_msg_c, "content", "") or "")
        _in_c    = ctx.input_tokens
        _out_c   = ctx.output_tokens
        _dur_c   = ctx.latency_ms / 1000.0

        _extra_c = dict(bundle.get("extra") or {})
        _extra_c = _ensure_dual_agent_meta(_extra_c)

        _msg_obj_c = build_picker_message(
            text=_text_c,
            choices=[_book_meeting_choice(_lang_c)],
            required=True,
        )

        _input_total_c  = _in_c  + int(sm.get("summary_input") or 0)
        _output_total_c = _out_c + int(sm.get("summary_output") or 0)

        _extra_c["retrieval_method"] = _method_c
        _payload_c = build_chat_turn_payload(
            question=user_question,
            message=_msg_obj_c,
            route=sa_state.get("route") or "agent_service_completed",
            language_name=_langn_c,
            user_nick=resolved_nick or "",
            prompt_applied=rendered_prompt_c,
            related_services=[_svc_lbl_c] if _svc_lbl_c else [],
            docs_retrieved_count=0,
            respond_duration=_dur_c,
            input_token=_in_c,
            output_token=_out_c,
            input_total=_input_total_c,
            output_total=_output_total_c,
            summarization_meta=sm,
            extra=_extra_c,
        )
        _result_c = {"session_id": session_id, **_payload_c}
        if request_started_at is not None:
            _attach_request_total_duration(_result_c, request_started_at)
        log_run(session_id, user_question, _result_c)
        _schedule_summary_refresh(
            session_id=session_id, token_id=token_id, language_name_hint=_langn_c
        )
        return _result_c
    # ── END COMPLETED GATE ──

    _method_sa = (getattr(cfg, "REDUNDANCY_METHOD", "normal") or "normal").strip().lower()

    extra = bundle.get("extra") or {}
    extra = _ensure_dual_agent_meta(extra)
    ia = extra["dual_agent_meta"]

    fast_mode = _fast_mode_on()

    # 1) TYPE classifier
    prompt_type = render_serviceagent_question_validation_prompt(
        user_question=user_question,
        current_question=current_q_text,
        service_code=getattr(state, "service_code", ""),
    )
    ia["prompt_type"] = prompt_type

    if fast_mode:
        type_label = _guess_type_label_fast(user_question)
        ia["input_token_pt"] = 0
        ia["output_token_pt"] = 0
    else:
        prompt_msgs_intent_type = [HumanMessage(content=prompt_type)]
        with audit_llm_call(
            route="system_detection",
            stage="intent_type",
            session_id=session_id,
            token_id=token_id,
            prompt=prompt_msgs_intent_type,
            extras={"retrieval_method": _method_sa},
        ) as ctx:
            type_raw = ASK_LLM.invoke(prompt_msgs_intent_type, config={"max_tokens": 32})
            ctx.set_response_from_message(type_raw)
        pt_in, pt_out = ctx.input_tokens, ctx.output_tokens
        ia["input_token_pt"] = pt_in
        ia["output_token_pt"] = pt_out
        type_label = _normalize_label(getattr(type_raw, "content", type_raw))

    if type_label not in ("answer_only", "question_only", "answer_and_question"):
        type_label = "question_only"
    ia["type"] = type_label

    # 2) question_count & next_question
    # Hanya "question_only" yang harus stay di pertanyaan kualifikasi saat ini.
    # "answer_and_question" = user menjawab + bertanya → tetap advance karena
    # user sudah memberi jawaban atas pertanyaan kualifikasi.
    if type_label == "question_only":
        if int(ia.get("question_count", 0)) == 0:
            # Klarifikasi pertama: stay, jawab klarifikasi, ulangi pertanyaan yang sama.
            ia["question_count"] = 1
            ia["next_question"] = False
        else:
            # User terus-menerus bertanya klarifikasi → force advance agar tidak looping.
            ia["question_count"] = 0
            ia["next_question"] = True
    else:
        # answer_only atau answer_and_question → advance ke pertanyaan berikutnya.
        ia["question_count"] = 0
        ia["next_question"] = True

    # 3) interest only if answer_only (kalau user bertanya, skip interest agent)
    if type_label == "answer_only":
        prompt_interest = render_serviceagent_interest_validation_prompt(
            user_question=user_question,
            prev_q=current_q_text,
        )
        ia["prompt_interest"] = prompt_interest

        if fast_mode:
            interest_label = _guess_interest_label_fast(user_question)
            ia["input_token_pi"] = 0
            ia["output_token_pi"] = 0
        else:
            prompt_msgs_intent_interest = [HumanMessage(content=prompt_interest)]
            with audit_llm_call(
                route="system_detection",
                stage="intent_interest",
                session_id=session_id,
                token_id=token_id,
                prompt=prompt_msgs_intent_interest,
                extras={"retrieval_method": _method_sa},
            ) as ctx:
                interest_raw = ASK_LLM.invoke(prompt_msgs_intent_interest, config={"max_tokens": 32})
                ctx.set_response_from_message(interest_raw)
            pi_in, pi_out = ctx.input_tokens, ctx.output_tokens
            ia["input_token_pi"] = pi_in
            ia["output_token_pi"] = pi_out
            interest_label = _normalize_label(getattr(interest_raw, "content", interest_raw))
            if interest_label not in ("valid", "not_interest"):
                interest_label = "not_interest"
        ia["interest_label"] = interest_label

        if interest_label == "not_interest":
            # Monotonic — grows without bound across the session. The
            # warnings_shown counter in dual_agent_meta controls when the
            # soft nudge + appended warning fire, via the formula
            # (invalid_count - 2 * warnings_shown) >= 2.
            ia["invalid_count"] = int(ia.get("invalid_count", 0)) + 1
    else:
        # SKIP interest agent
        ia["prompt_interest"] = "-"
        ia["input_token_pi"] = 0
        ia["output_token_pi"] = 0
        ia["interest_label"] = ""

    # meeting_arrangement is NO LONGER coupled to invalid_count. Previously
    # `ia["meeting_arrangement"] = bool(invalid_count >= 2)` auto-halted the
    # qualification flow on any two invalid answers — that was the closing-
    # message bug. Meeting intent routing happens upstream (keyword/LLM
    # detection) before SA is entered, so this flag stays False within SA.

    # 5) commit SA state (advance vs stay)
    from modules.service_agent.sa_service import SA_ENGINE
    advance = bool(ia.get("next_question") is True)
    extra = _ensure_dual_agent_meta(extra)
    SA_ENGINE.commit_turn(session_id=session_id, user_answer=user_question, extra=extra, advance=advance)

    # >>> REFRESH bundle after commit (biar answers & dual_agent_meta ikut ke response)
    bundle2 = SA_ENGINE.get_current_step_bundle(session_id)
    state2 = bundle2["state"]
    step2 = bundle2["current_step"]          # current step AFTER commit (kalau advance=True, ini sudah maju)
    extra2 = bundle2.get("extra") or {}
    extra2 = _ensure_dual_agent_meta(extra2)
    ia2 = extra2["dual_agent_meta"]

    new_current_q = getattr(step2, "text", "") or ""
    if advance:
        prev_q_for_prompt = prev_q_text
        next_q_for_prompt = new_current_q
    else:
        prev_q_for_prompt = prev_q_text
        next_q_for_prompt = prev_q_text

    # values for gating
    invalid = int(ia2.get("invalid_count", 0))
    qcount = int(ia2.get("question_count", 0))
    next_q_flag = ia2.get("next_question", True)
    meeting = ia2.get("meeting_arrangement", False)
    gate_shown = ia2.get("gate_shown", False) 

    service_label = getattr(state2, "service_label", "") or sa_state.get("service_label", "")

    # Policy 2026-05-07: per-turn fresh detection wins. Pakai `turn_language_*`
    # dari parameter (sumber kebenaran untuk turn ini); state hanya fallback.
    language_code = (turn_language_code or "").strip()
    language_name = (turn_language_name or "").strip()

    if not language_code:
        language_code = (getattr(state2, "language_code", "") or sa_state.get("language_code", "") or "").strip()
        language_name = (getattr(state2, "language_name", "") or sa_state.get("language_name", "") or "").strip()

    # Untuk input technical (BOOK_A_MEETING, picker tokens) yang tidak ada
    # turn_language → fallback ke majority history.
    if _is_technical_language_input(user_question or "") and not turn_language_code:
        _maj_c, _maj_n = _majority_language_from_history(session_id, token_id)
        language_code = language_code or _maj_c or ""
        language_name = language_name or _maj_n or ""

    # fallback terakhir, baru infer dari pasangan code/name
    if not language_code and language_name:
        low = language_name.lower()
        if "english" in low:
            language_code = "en"
        elif "indo" in low:
            language_code = "id"

    if not language_name and language_code:
        if language_code == "en":
            language_name = "English"
        elif language_code == "id":
            language_name = "Indonesia"

    if not language_code:
        language_code = "en"
    if not language_name:
        language_name = "English"

    # history/summary blocks (buat dipakai prompt)
    history_block, summary_block, _summary_meta2 = _build_history_blocks(
        session_id,
        token_id,
        precomputed_summary_block=summary_block_cache,
        precomputed_summary_meta=summary_meta_cache,
    )

    service_code = getattr(state2, "service_code", "") or sa_state.get("service_code", "") or ""
    service_code = service_code.strip()

    # RAG context untuk SA continue (jangan pakai user_answer mentah)
    # rag_query = f"{service_label}. {next_q_for_prompt}".strip() or service_code or "Acme Services service"
    type_now = (ia2.get("type") or "").strip()

    if type_now in ("question_only", "answer_and_question"):
        rag_query = f"{service_label}. {user_question}".strip() or service_code or "Acme Services service"
    else:
        rag_query = f"{service_label}. {next_q_for_prompt}".strip() or service_code or "Acme Services service"

    # Service-biased retrieval when the active service is known. The 4+2 split
    # gives the LLM strong domain context plus two best-pick docs from other
    # services for cross-reference.
    method = (getattr(cfg, "REDUNDANCY_METHOD", "normal") or "normal").strip().lower()
    rc_ctx = ResolutionContext(service_id=(service_label or None))
    _same_k = int(getattr(cfg, "CTX_DOCS_SAME_SERVICE", 4))
    _other_k = int(getattr(cfg, "CTX_DOCS_OTHER_SERVICE", 0))

    if (service_label or "").strip():
        _floor = _same_k + _other_k
        from modules.system_detection import sd_vector_repo as _svr
        target_id = _svr._resolve_alias_to_service_id(_service_aliases(service_label))
        strategy_vs = _svr._vectorstores.get(target_id) if target_id else None
        strategy_result = retrieve_with_strategy(
            method, rag_query, scope="service_biased", k=_floor,
            vectorstore=strategy_vs, ctx=rc_ctx,
        )
        if strategy_result is None:
            candidates = retrieve_service_biased(rag_query, _service_aliases(service_label), same_k=_same_k, other_k=_other_k)
        else:
            candidates = strategy_result
    else:
        _floor = int(getattr(cfg, "CTX_DOCS_FLOOR", 4))
        retriever = get_retriever()
        strategy_vs = getattr(retriever, "vectorstore", None)
        strategy_result = retrieve_with_strategy(
            method, rag_query, scope="unbiased", k=_floor,
            vectorstore=strategy_vs, ctx=rc_ctx,
        )
        if strategy_result is None:
            candidates = retrieve_candidates(retriever, rag_query)
        else:
            candidates = strategy_result

    _flag = (getattr(cfg, "FAQ_VERIFICATOR", "on") or "on").strip().lower()
    _verif_on = _flag in ("1", "true", "on", "yes")
    filtered = grade_and_filter_yes(GRADER, candidates, rag_query, session_id=session_id, token_id=token_id) if _verif_on else candidates

    filtered = _pad_to_floor(filtered, candidates, _floor)

    ctx_str = render_context(filtered)
    related_services = extract_related_services(filtered, top_k=len(filtered))

    # Anti-Redundancy: apply recent-chunks filter when method != normal AND
    # user is not explicitly asking for a recap.
    if _method_sa != "normal" and not _is_explicit_recap(user_question, turn_language_code) \
            and bool(getattr(cfg, "REDUNDANCY_RECAP_BYPASS", True)):
        from modules.system_detection.sd_repo import get_recent_chunk_ids
        recent_ids = get_recent_chunk_ids(session_id, token_id)
        if recent_ids:
            filtered = _apply_recent_chunk_filter(filtered, recent_ids, floor=_floor)
            ctx_str = render_context(filtered)
            related_services = extract_related_services(filtered, top_k=len(filtered))

    is_final_gate = False

    # Opener diversification state — last ≤3 Sentence-1 openers the assistant
    # used this session. Fed into the prompt as a ban list AND used by the
    # post-process safety net below to swap repeats/banned openers deterministically.
    _recent_openers: list[str] = list(getattr(state2, "recent_openers", []) or [])

    # Engagement nudge + appended warning — fires once every 2 cumulative
    # invalid answers via the formula `(invalid_count - 2*warnings_shown) >= 2`.
    # Qualification flow continues normally; we just add a soft in-prompt nudge
    # AND a post-process appended warning (blank-line separated) so the user
    # sees the signal as an escalation, not as the main reply.
    _warnings_shown: int = int(ia2.get("warnings_shown", 0) or 0)
    _should_warn: bool = (invalid - 2 * _warnings_shown) >= 2
    # Kept as `_engagement_nudge` local var because the renderer kwarg is
    # named `engagement_nudge`; semantics are now warnings_shown-driven.
    _engagement_nudge: bool = _should_warn

    # PRIORITAS 1: meeting gate (only when user EXPLICITLY asks for a meeting)
    if meeting and not gate_shown:
        rendered_prompt = render_serviceagent_prompt_final(
            language_name=language_name,
            service_label=service_label,
            user_answer=user_question,
            is_first_turn=first_turn,
            user_nick=resolved_nick,
            language_code=language_code,
            chat_history_block=history_block,
            chat_summary_block=summary_block,
        )
        if _method_sa != "normal":
            from modules.system_detection.sd_prompts import apply_dedup_guidelines
            rendered_prompt = apply_dedup_guidelines(rendered_prompt, language_name)
        is_final_gate = True
        # ⚠️ VERIFIKASI: pastikan flag ini benar-benar persist ke turn berikut.
        # Mutasi ia2 di sini terjadi SETELAH SA_ENGINE.commit_turn (line 1563),
        # jadi kemungkinan besar dead-write. Cek apakah SA_ENGINE punya method
        # untuk update state di luar commit_turn, atau pindahkan assignment
        # ini ke sebelum commit_turn, atau commit ulang.
        ia2["gate_shown"] = True
        ia["gate_shown"] = True  # defensive: tulis ke dict pre-commit juga

    elif meeting and gate_shown:
        # Meeting gate already shown once — answer in 2 sentences, continue qualification, no picker
        rendered_prompt = render_serviceagent_postgate_prompt(
            language_name=language_name,
            context=ctx_str,
            user_answer=user_question,
            next_q=next_q_for_prompt,
            is_first_turn=first_turn,
            user_nick=resolved_nick,
            language_code=language_code,
            max_chars=cfg.INPUT_MAX_PROMPT,
            chat_history_block=history_block,
            chat_summary_block=summary_block,
            recent_openers=_recent_openers,
            engagement_nudge=_engagement_nudge,
        )
        is_final_gate = False   # ← penting: tidak pakai picker

    elif type_now == "question_only":
        # stay + jawab klarifikasi + tanya ulang pertanyaan yang sama (Active Question)
        rendered_prompt = render_serviceagent_continue_question_prompt(
            language_name=language_name,
            context=ctx_str,
            user_answer=user_question,
            prev_q=prev_q_for_prompt,     # active question (sama)
            is_first_turn=first_turn,
            user_nick=resolved_nick,
            language_code=language_code,
            max_chars=cfg.INPUT_MAX_PROMPT,
            chat_history_block=history_block,
            chat_summary_block=summary_block,
            recent_openers=_recent_openers,
            engagement_nudge=_engagement_nudge,
        )

    elif type_now == "answer_and_question":
        # jawab + lanjut ke next qualification question
        rendered_prompt = render_serviceagent_continue_answerquestion_prompt(
            language_name=language_name,
            context=ctx_str,
            user_answer=user_question,
            prev_q=prev_q_for_prompt,
            next_q=next_q_for_prompt,
            is_first_turn=first_turn,
            user_nick=resolved_nick,
            language_code=language_code,
            max_chars=cfg.INPUT_MAX_PROMPT,
            chat_history_block=history_block,
            chat_summary_block=summary_block,
            recent_openers=_recent_openers,
            engagement_nudge=_engagement_nudge,
        )
        ia["question_count"] = 0
        ia["next_question"] = True

    else:
    # answer_only (normal)
        rendered_prompt = render_serviceagent_continue_prompt(
            language_name=language_name,
            context=ctx_str,
            user_answer=user_question,
            prev_q=prev_q_for_prompt,
            next_q=next_q_for_prompt,
            is_first_turn=first_turn,
            user_nick=resolved_nick,
            language_code=language_code,
            max_chars=cfg.INPUT_MAX_PROMPT,
            chat_history_block=history_block,
            chat_summary_block=summary_block,
            recent_openers=_recent_openers,
            engagement_nudge=_engagement_nudge,
        )
        is_final_gate = False
        ia["question_count"] = 0
        ia["next_question"] = True

    # warnings_shown will be incremented in the consolidated persistence block
    # below (AFTER the LLM reply and post-process append happen) so the counter
    # reflects a warning that actually landed in the user-visible reply.

    # ===== setelah rendered_prompt ditentukan (final gate / stay / advance) =====

    prompt_msgs_rag_main = [SystemMessage(content=rendered_prompt), HumanMessage(content=user_question)]
    with audit_llm_call(
        route="system_detection",
        stage="rag_main_reply",
        session_id=session_id,
        token_id=token_id,
        prompt=prompt_msgs_rag_main,
        extras={"retrieval_method": _method_sa},
    ) as ctx_rag_main:
        msg = BRIEF_LLM.invoke(prompt_msgs_rag_main)
        ctx_rag_main.set_response_from_message(msg)

    text = normalize_single_paragraph(getattr(msg, "content", "") or "")

    # Opener diversification safety net — swap banned/repeated openers deterministically
    # (no second LLM call). Persistence of the new opener happens in the
    # consolidated persistence block below, along with the dual_agent_meta flags.
    _new_opener: str | None = None
    if not is_final_gate:
        text = sanitize_opener(text, _recent_openers, language_code)
        _new_opener = extract_opener(text)

    # Escalation warning — appended with `\n\n` separator when invalid-count
    # threshold hits (see `_should_warn` above). Uses a small LLM pass to
    # translate the English base warning into the target language so the tone
    # stays natural. In-prompt soft nudge has already been injected above;
    # this appended block is the more visible escalation signal.
    _warning_appended: bool = False
    if _should_warn and not is_final_gate:
        try:
            text = append_invalid_warning(
                text,
                llm=BRIEF_LLM,
                language_code=language_code,
                language_name=language_name,
            )
            _warning_appended = True
        except Exception:
            # Warning is best-effort — never fail the turn if translation blows up.
            pass

    in_tok  = ctx_rag_main.input_tokens
    out_tok = ctx_rag_main.output_tokens

    popup_choices: list[dict] | None = None
    popup_every = int(getattr(cfg, "MEETING_POPUP", 0) or 0)
    _popup_shown_steps_updated = False
    _popup_shown_new_list: list[int] = []
    if not is_final_gate and popup_every > 0:
        question_index = _infer_question_index(step2, state2)
        # Parse the persisted "popup already shown at these steps" list — tolerate
        # legacy dicts where it's missing or non-list.
        _popup_shown_raw = ia2.get("popup_shown_steps") or []
        _popup_shown_set: set[int] = set()
        if isinstance(_popup_shown_raw, (list, tuple, set)):
            for _v in _popup_shown_raw:
                try:
                    _popup_shown_set.add(int(_v))
                except (TypeError, ValueError):
                    continue
        if (
            question_index > 0
            and question_index % popup_every == 0
            and question_index not in _popup_shown_set
        ):
            popup_choices = [_book_meeting_choice(language_code)]
            _popup_shown_set.add(question_index)
            _popup_shown_new_list = sorted(_popup_shown_set)
            ia2["popup_shown_steps"] = _popup_shown_new_list
            ia["popup_shown_steps"] = _popup_shown_new_list
            _popup_shown_steps_updated = True

    # Consolidated persistence — works around the dead-write bug noted at L1563.
    # Mutations to `ia`/`ia2` made AFTER SA_ENGINE.commit_turn don't persist to
    # Mongo on their own. We explicitly re-upsert state so flags survive to the
    # next turn: recent_openers, warnings_shown, gate_shown, popup_shown_steps.
    _needs_persist = (
        bool(_new_opener)
        or _warning_appended
        or is_final_gate
        or _popup_shown_steps_updated
    )
    if _needs_persist:
        try:
            _st_persist = SA_ENGINE.repo.get_state(session_id)
            if _st_persist is not None:
                if _new_opener:
                    _st_persist.recent_openers = (_recent_openers + [_new_opener])[-3:]
                _dm = dict(getattr(_st_persist, "dual_agent_meta", {}) or {})
                if _warning_appended:
                    # Bump the counter so the NEXT fire only happens after 2
                    # more cumulative invalids: (invalid - 2*warnings_shown) >= 2.
                    _dm["warnings_shown"] = _warnings_shown + 1
                if is_final_gate:
                    _dm["gate_shown"] = True
                if _popup_shown_steps_updated:
                    _dm["popup_shown_steps"] = _popup_shown_new_list
                _st_persist.dual_agent_meta = _dm
                SA_ENGINE.repo.upsert_state(_st_persist)
        except Exception:
            # Persistence failure should not break the reply path.
            pass

    # ambil token dual agent dari state TERBARU (ia2)
    pt_in  = int(ia2.get("input_token_pt") or 0)
    pt_out = int(ia2.get("output_token_pt") or 0)
    pi_in  = int(ia2.get("input_token_pi") or 0)
    pi_out = int(ia2.get("output_token_pi") or 0)

    input_total  = in_tok  + int(sm.get("summary_input") or 0) + pt_in + pi_in
    output_total = out_tok + int(sm.get("summary_output") or 0) + pt_out + pi_out
    dur_s = ctx_rag_main.latency_ms / 1000.0

    # name variation (optional)
    nick_plain, addr_formal = _address_forms_by_language(language_code, resolved_nick)
    seed_val = (hash(f"{session_id}:{user_question}") & 0xFFFFFFFF)
    text = enforce_name_variation(
        text, language_code, nick_plain, addr_formal,
        cadence=3, max_mentions_short=2, max_mentions_long=3, seed=seed_val
    )

    # message object: final gate pakai picker, else string
    if is_final_gate:
        msg_obj = build_picker_message(
            text=text,
            choices=_final_gate_choices(language_code),
            required=False,
        )
        route_name = sa_state.get("route") or "service_agent_final_gate"
    elif popup_choices:
        msg_obj = build_picker_message(
            text=text,
            choices=popup_choices,
            required=False,
        )
        route_name = sa_state.get("route") or "service_agent_continue"
    else:
        msg_obj = build_string_message(text)
        route_name = sa_state.get("route") or "service_agent_continue"

    extra2["retrieval_method"] = _method_sa
    payload = build_chat_turn_payload(
        question=user_question,
        message=msg_obj,
        route=route_name,
        language_name=language_name,
        user_nick=resolved_nick or "",
        prompt_applied=rendered_prompt,
        related_services=related_services,
        docs_retrieved_count=len(filtered),
        respond_duration=dur_s,
        input_token=in_tok,
        output_token=out_tok,
        input_total=input_total,
        output_total=output_total,
        summarization_meta=sm,
        extra=extra2,  # <<< penting: include answers + dual_agent_meta terbaru
    )

    result = {"session_id": session_id, **payload}
    result = _finalize_result_language(result, language_code, language_name)
    if request_started_at is not None:
        _attach_request_total_duration(result, request_started_at)
    log_run(session_id, user_question, result)
    _schedule_summary_refresh(
        session_id=session_id,
        token_id=token_id,
        language_name_hint=language_name,
    )
    # Anti-Redundancy: write back chunk IDs that actually appeared in Context.
    if _method_sa != "normal" and not _is_explicit_recap(user_question, turn_language_code) \
            and bool(getattr(cfg, "REDUNDANCY_RECAP_BYPASS", True)):
        from modules.system_detection.sd_repo import update_recent_chunk_ids
        update_recent_chunk_ids(session_id, token_id, _extract_chunk_ids_from_docs(filtered))
    return result

def _to_service_value_code(one: str | None) -> str | None:
    one = (one or "").strip()
    if not one:
        return None
    # kalau sudah value-code
    if one in SA_POL.SERVICE_CODE_TO_FLOW_CODE:
        return one
    # kalau label, map label -> value-code via SERVICE_VALUE_CODE_MAP
    # (SERVICE_VALUE_CODE_MAP ada di sa_policies.py):contentReference[oaicite:4]{index=4}
    val = SA_POL.SERVICE_VALUE_CODE_MAP.get(one)  # "Mystery Shopping" -> "mystery_shopping"
    if val:
        return val
    # kalau flow-code, pilih default value-code pertama yang match flow tsb
    # bangun invert map sekali saja:
    return None

def build_transcript(flow: dict, answers: dict) -> str:
    """
    Build Q/A transcript mirroring chat history prompt format:
    Q1: ...
    A1: ...
    Accepts QuestionStep objects or dicts from FLOW_REGISTRY.
    """
    if not flow:
        return ""

    def _clean(text: str | None) -> str:
        return (str(text or "").replace("\n", " ")).strip()

    def _step_attr(step, name: str):
        if hasattr(step, name):
            return getattr(step, name)
        if isinstance(step, dict):
            return step.get(name)
        return None

    steps = list(flow.values()) if isinstance(flow, dict) else list(flow or [])
    steps.sort(key=lambda st: (
        _step_attr(st, "order") if _step_attr(st, "order") is not None else 10**6,
        _step_attr(st, "id") or ""
    ))

    lines: list[str] = []
    idx = 1
    for step in steps:
        q = _clean(_step_attr(step, "text") or _step_attr(step, "question") or _step_attr(step, "question_text"))
        field = _step_attr(step, "field_name") or _step_attr(step, "field") or _step_attr(step, "id")
        raw_ans = answers.get(field) or answers.get(_step_attr(step, "id"))
        ans = _clean(raw_ans)
        if q and ans:
            lines.append(f"Q{idx}: {q}")
            lines.append(f"A{idx}: {ans}")
            idx += 1

    return "\n".join(lines).strip()

def _get_array_tail(session_id: str, token_id: str, tail_k: int = 3) -> list[dict]:
    """
    Ambil tail_k pasangan terakhir dari dokumen array chat_history untuk sessionId+tokenId.
    Return: list [{"question": ..., "message": ...}, ...] terurut lama→baru.
    """
    cli = MongoClient(cfg.MONGO_URI, connect=True)
    db  = cli[cfg.MONGO_DB]
    doc = db[cfg.CHAT_HISTORY_COLL].find_one({"sessionId": session_id, "tokenId": token_id}) or {}
    arr = doc.get("chat_history") or []
    if not isinstance(arr, list):
        return []
    # ambil pasangan terakhir (tiap item sudah berisi question & message ditambah metadata lain)
    tail = arr[-tail_k:] if tail_k > 0 else arr
    # normalize ke pair minimal
    # return [{"question": (it.get("question") or "").strip(),
    #          "message":  (it.get("message")  or "").strip()} for it in tail]
    out = []
    for it in tail:
        qtext = (it.get("question") or "").strip()
        mtext = _plain_from_message_field(it.get("message")).strip()
        out.append({"question": qtext, "message": mtext})
    return out

def _pairs_to_qa_dump(pairs: list[dict]) -> str:
    lines = []
    for i, p in enumerate(pairs, start=1):
        q = (p.get("question") or "").replace("\n", " ").strip()
        a = (p.get("message") or "").replace("\n", " ").strip()
        if not q and not a:
            continue
        lines.append(f"Q{i}: {q}")
        lines.append(f"A{i}: {a}")
    return "\n".join(lines).strip()


def build_final_convo_transcript(
    session_id: str,
    token_id: str,
    *,
    user_question_now: str,
    assistant_answer_now: str,
) -> str:
    # ambil semua chat_history pairs lama → baru
    pairs = _get_array_tail(session_id, token_id, tail_k=0)  # IMPORTANT
    # append turn terakhir (karena payload ini belum tentu kesimpan ke DB saat fungsi ini jalan)
    pairs.append({"question": user_question_now, "message": assistant_answer_now})
    return _pairs_to_qa_dump(pairs)

def _post_to_monday_webhook(final_convo: dict) -> dict:
    """
    Kirim final_convo ke MONDAY_PATH (webhook n8n/monday bridge).
    Return dict status untuk disimpan ke extra.monday_status.
    """
    url = (getattr(cfg, "MONDAY_PATH", "") or "").strip()
    if not url:
        return {"ok": False, "skipped": True, "error": "MONDAY_PATH is empty"}

    # board_id bisa string dari env → coba cast ke int kalau memungkinkan
    # board_id_raw = final_convo.get("board_id", "")
    board_id_raw = getattr(cfg, "BOARD_ID", "")
    try:
        board_id_val = int(board_id_raw) if str(board_id_raw).strip().isdigit() else board_id_raw
    except Exception:
        board_id_val = board_id_raw

    # group_id = final_convo.get("group_id") or final_convo.get("topics") or getattr(cfg, "MONDAY_GROUP_ID", "topics")
    group_id = getattr(cfg, "TOPICS", "")

    body = {
        "title": (final_convo.get("title") or "").strip(),
        "description": (final_convo.get("description") or "").strip(),
        "transcript": (final_convo.get("transcript") or "").strip(),
        "board_id": board_id_val,
        "group_id": group_id,
    }

    # ADD API KEY HEADER
    headers = {"Content-Type": "application/json"}
    hk = (getattr(cfg, "MONDAY_KEY", "") or "").strip()
    hv = (getattr(cfg, "MONDAY_VALUE", "") or "").strip()
    if hk and hv:
        headers[hk] = hv

    try:
        r = requests.post(url, json=body, headers=headers, timeout=15)
        try:
            data = r.json()
        except Exception:
            data = r.text

        return {
            "ok": bool(getattr(r, "ok", False)),
            "status_code": getattr(r, "status_code", None),
            "response": data,
            "request_body": body,
            # "request_headers_sent": {hk: ("***" if hv else "")} if hk else {},  # opsional buat debug aman
        }
    except Exception as e:
        return {
            "ok": False,
            "status_code": None,
            "error": str(e),
            "request_body": body,
        }

def _send_monday_item(final_convo: dict) -> dict:
    """
    Wrapper: uses existing _post_to_monday_webhook(final_convo)
    """
    try:
        return _post_to_monday_webhook(final_convo)
    except Exception as e:
        return {"ok": False, "status_code": None, "error": str(e), "request_body": final_convo}

def _ensure_dual_agent_meta(extra: dict) -> dict:
    extra = extra or {}
    ia = extra.get("dual_agent_meta")
    if not isinstance(ia, dict):
        ia = {}

    # prompt text (pakai "-" kalau skip)
    ia.setdefault("prompt_type", "-")
    ia.setdefault("input_token_pt", 0)
    ia.setdefault("output_token_pt", 0)
    ia.setdefault("type", "")

    ia.setdefault("question_count", 0)

    ia.setdefault("prompt_interest", "-")
    ia.setdefault("input_token_pi", 0)
    ia.setdefault("output_token_pi", 0)
    ia.setdefault("interest_label", "")

    ia.setdefault("invalid_count", 0)
    ia.setdefault("next_question", True)
    ia.setdefault("meeting_arrangement", False)
    ia.setdefault("gate_shown", False)
    # Number of times the invalid-count warning has fired this session. Drives
    # both the in-prompt soft nudge and the post-process appended warning via
    # the formula `(invalid_count - 2 * warnings_shown) >= 2` — i.e. fires
    # once every 2 cumulative invalid answers.
    ia.setdefault("warnings_shown", 0)
    # Qualification step indices where the BOOK_A_MEETING cadence popup has
    # already been shown this session. Prevents re-rendering the picker on
    # subsequent turns that stay on the same step (e.g. user asking clarifications).
    ia.setdefault("popup_shown_steps", [])

    extra["dual_agent_meta"] = ia
    return extra

def _normalize_label(txt: str) -> str:
    return (txt or "").strip().lower().replace(".", "").replace(",", "")

def _extract_tok(msg_obj) -> tuple[int, int]:
    usage = getattr(msg_obj, "usage_metadata", None) or getattr(msg_obj, "response_metadata", {}) or {}
    token_usage = usage.get("token_usage") or usage
    in_tok  = int(token_usage.get("input_tokens", 0) or token_usage.get("input", 0) or 0)
    out_tok = int(token_usage.get("output_tokens", 0) or token_usage.get("output", 0) or 0)
    return in_tok, out_tok

def _read_all_chat_pairs(session_id: str, token_id: str | None, limit: int = 5000) -> list[dict]:
    """
    Return list of chat turns WITH extra field, baca langsung dari MongoDB
    agar field 'extra' (termasuk meeting_arrangement.booking_completed) selalu tersedia.
    read_chat_history dari sd_repo tidak menjamin include 'extra', sehingga
    fungsi ini query langsung ke collection chat_history.
    """
    def _query_mongo(sid: str, tid: str | None) -> list[dict]:
        try:
            cli = MongoClient(cfg.MONGO_URI, connect=True)
            db  = cli[cfg.MONGO_DB]
            q_filter: dict = {"sessionId": sid}
            if tid:
                q_filter["tokenId"] = tid
            doc = db[cfg.CHAT_HISTORY_COLL].find_one(q_filter) or {}
            arr = doc.get("chat_history") or []
            if not isinstance(arr, list):
                return []
            tail = arr[-limit:] if limit > 0 else arr
            out = []
            for it in tail:
                out.append({
                    "question":         (it.get("question") or "").strip(),
                    "message":          _plain_from_message_field(it.get("message")).strip(),
                    "related_services": it.get("related_services") or [],
                    "extra":            it.get("extra") or {},
                    "route":            (it.get("route") or "").strip(),
                    "language_name":    (it.get("language_name") or "").strip(),
                    "language_code":    (it.get("language_code") or "").strip(),
                })
            return out
        except Exception:
            return []

    rows = _query_mongo(session_id, token_id)
    if not rows and token_id:
        rows = _query_mongo(session_id, None)
    return rows

def _value_code_to_label(value_code: str) -> str:
    """
    Convert service value_code (e.g. 'whistleblowing_hotline') -> human label.
    Safe terhadap format SERVICE_LABEL_CODE_MAP yang bisa string/dict.
    """
    from modules.service_agent import sa_policies as SA_POL

    v = (value_code or "").strip()
    if not v:
        return "-"

    raw = getattr(SA_POL, "SERVICE_LABEL_CODE_MAP", {}).get(v)
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        # coba beberapa key yang umum dipakai
        return (raw.get("label") or raw.get("name") or raw.get("title") or v)
    return v

def _guess_last_service_code(pairs: list[dict]) -> str:
    """
    Return flow code like 'WBS', 'FRI', etc.

    NOTE: sd_repo chat_history biasanya tidak menyimpan extra.service_code,
    jadi kita fallback ke:
    - route: 'agent_service_wbs' -> 'WBS'
    - question: 'SA_SELECT_whistleblowing_hotline' -> map ke flow code
    """
    from modules.service_agent import sa_policies as SA_POL

    # 1) route fallback (paling reliable di chat_history)
    for p in reversed(pairs or []):
        r = (p.get("route") or "").strip().lower()
        if r.startswith("agent_service_"):
            suffix = r.replace("agent_service_", "").strip()
            if suffix:
                return suffix.upper()

    # 2) selection question fallback
    #    contoh: SA_SELECT_whistleblowing_hotline -> value_code = 'whistleblowing_hotline'
    for p in reversed(pairs or []):
        q = (p.get("question") or "").strip()
        if q.startswith("SA_SELECT_"):
            value_code = q.replace("SA_SELECT_", "").strip().lower()
            # map value_code -> flow code via SERVICE_CODE_TO_FLOW_CODE
            flow = getattr(SA_POL, "SERVICE_CODE_TO_FLOW_CODE", {}).get(value_code)
            if flow:
                return str(flow).strip().upper()

    # 3) (opsional) kalau suatu saat sd_repo menyimpan extra.service_code lagi
    for p in reversed(pairs or []):
        extra = p.get("extra") or {}
        code = (extra.get("service_code") or "").strip()
        if code:
            return code.upper()

    return ""

def _map_related_service_to_value_code(service: str) -> tuple[str, str]:
    """
    Map related service (label / flow-code / SA_SELECT_* ) -> (value_code, label)
    - value_code: "whistleblowing_hotline" (TANPA prefix SA_SELECT_)
    - label: "Whistleblowing Hotline"
    """
    s = (service or "").strip()
    if not s:
        return ("", "")

    # 1) Already SA_SELECT_<value_code>
    if s.startswith(SA_POL.SERVICE_AGENT_PREFIX):  # "SA_SELECT_"
        suffix = s[len(SA_POL.SERVICE_AGENT_PREFIX):].strip()
        if not suffix:
            return ("", "")
        label = SERVICE_LABEL_CODE_MAP.get(suffix) or suffix.replace("_", " ").title()
        return (suffix, label)

    up = s.upper()

    # helper: invert SERVICE_CODE_TO_FLOW_CODE -> flow_code->value_code (best effort)
    _FLOW_TO_VALUE: dict[str, str] = {}
    try:
        for v, f in (SA_POL.SERVICE_CODE_TO_FLOW_CODE or {}).items():
            if isinstance(v, str) and isinstance(f, str) and f:
                _FLOW_TO_VALUE.setdefault(f.upper(), v)
    except Exception:
        pass

    # 2) If it's a FLOW CODE like "WBS", "MSG", etc.
    if up in _FLOW_TO_VALUE:
        value_code = _FLOW_TO_VALUE[up]
        label = SERVICE_LABEL_CODE_MAP.get(value_code) or value_code.replace("_", " ").title()
        return (value_code, label)

    # 3) If it's a label already (e.g. "Whistleblowing Hotline")
    # SERVICE_LABEL_CODE_MAP sekarang: value_code -> label (dipakai di tempat lain)
    # Jadi reverse match label -> value_code:
    try:
        for vc, lbl in (SERVICE_LABEL_CODE_MAP or {}).items():
            if (lbl or "").strip().lower() == s.lower():
                return (vc, lbl)
    except Exception:
        pass

    # 4) Try SERVICE_VALUE_CODE_MAP — handles short labels like "Parallel Trading"
    # (chunk metadata uses tab name from Sheet, which may differ from canonical
    # SERVICE_LABEL_CODE_MAP label, e.g. "Parallel Trading" vs "Parallel Trading Investigation").
    try:
        svcm = getattr(SA_POL, "SERVICE_VALUE_CODE_MAP", None) or {}
        for short_lbl, vc in svcm.items():
            if (short_lbl or "").strip().lower() == s.lower():
                # Resolve to display label via SERVICE_LABEL_CODE_MAP if available
                display_label = SERVICE_LABEL_CODE_MAP.get(vc) or short_lbl
                return (vc, display_label)
    except Exception:
        pass

    # no match
    return ("", "")

def _book_meeting_label(language_code: str | None) -> str:
    """Task 19 (2026-05-13): legacy if/elif chain deleted; uses i18n loader exclusively.
    Inline English baseline as defensive fallback if i18n loader fails."""
    lc = (language_code or "").strip().lower()[:2]
    try:
        from modules.i18n import t as _t
        return _t("picker.book_meeting.label", lc)
    except Exception:
        return "Schedule a meeting"
    # legacy if/elif chain DELETED Task 19 — superseded by i18n loader above
    lang = (language_code or "").lower()
    if lang.startswith("id"):
        return "Jadwalkan meeting"
    if lang.startswith("ms"):
        return "Jadualkan meeting"
    if lang.startswith("fr"):
        return "Planifier une réunion"
    if lang.startswith("de"):
        return "Meeting vereinbaren"
    if lang.startswith("it"):
        return "Fissa un meeting"
    if lang.startswith("es"):
        return "Programar una reunión"
    if lang.startswith("pt"):
        return "Agendar uma reunião"
    if lang.startswith("th"):
        return "จองการประชุม"
    if lang.startswith("ru"):
        return "Назначить встречу"
    if lang.startswith("vi"):
        return "Đặt lịch cuộc họp"
    if lang.startswith("da"):
        return "Book et møde"
    if lang.startswith("ja"):
        return "打ち合わせを予約"
    if lang.startswith("zh"):
        return "预约会议"
    return "Schedule a meeting"

def _other_services_label(language_code: str | None, batch_no: int) -> str:
    # Note: `batch_no` is intentionally unused in the visible label. Callers
    # still pass it for logic/state; display stays clean without the "(N)" suffix.
    # Task 19 (2026-05-13): legacy if/elif chain dead code; uses i18n loader exclusively.
    lc = (language_code or "").strip().lower()[:2]
    try:
        from modules.i18n import t as _t
        return _t("picker.other_services.label", lc)
    except Exception:
        return "Other Services"
    # legacy if/elif chain DEAD CODE Task 19 — superseded by i18n loader above
    lang = (language_code or "").lower()
    if lang.startswith("id"):
        return "Layanan Lainnya"
    if lang.startswith("ms"):
        return "Perkhidmatan Lain"
    if lang.startswith("fr"):
        return "Autres Services"
    if lang.startswith("de"):
        return "Weitere Dienstleistungen"
    if lang.startswith("it"):
        return "Altri Servizi"
    if lang.startswith("es"):
        return "Otros Servicios"
    if lang.startswith("pt"):
        return "Outros Serviços"
    if lang.startswith("th"):
        return "บริการอื่น ๆ"
    if lang.startswith("ru"):
        return "Другие Услуги"
    if lang.startswith("vi"):
        return "Dịch Vụ Khác"
    if lang.startswith("da"):
        return "Andre Tjenester"
    if lang.startswith("ja"):
        return "その他のサービス"
    if lang.startswith("zh"):
        return "其他服务"
    return "Other Services"

def _all_service_catalog_choices() -> list[dict]:
    """
    Full service catalog for service validation/reset.
    Exclude general_service.
    Keep deterministic order.

    2026-05-18: filter out services whose `value_code` does not resolve to a
    `FLOW_REGISTRY` entry — otherwise the post-pick SA_SELECT_ handler
    (sd_service.py:5324 → `SA_ENGINE.handle_from_question` → `start_flow`)
    raises `KeyError` on the unmapped flow code. Filtering keeps the picker
    honest: only flows the engine can actually run are offered. As of
    2026-05-18 (post KYC + CLI build), all 15 catalog entries resolve.
    """
    ordered_value_codes = [
        "background_check",
        "due_diligence",
        "mystery_shopping",
        "asset_verification",
        "contact_verification",
        "fraud_investigation",
        "claim_investigation",
        "market_research",
        "non-use_investigation",
        "anti-counterfeiting_investigation",
        "parallel_trading_investigation",
        "abms_eLearning",
        "trademark_investigation",
        "know_your_customer",
        "whistleblowing_hotline",
    ]

    out = []
    seen = set()

    for value_code in ordered_value_codes:
        vc = (value_code or "").strip()
        if not vc or vc == "general_service":
            continue
        label = (SERVICE_LABEL_CODE_MAP.get(vc) or "").strip()
        if not label:
            continue
        if vc in seen:
            continue
        # Skip value codes whose flow code is missing from FLOW_REGISTRY.
        flow_code = SA_POL.SERVICE_CODE_TO_FLOW_CODE.get(vc)
        if not flow_code or flow_code not in FLOW_REGISTRY:
            continue
        seen.add(vc)
        out.append({
            "value": f"{SA_POL.SERVICE_AGENT_PREFIX}{vc}",
            "label": label,
            "selected": False,
        })

    return out

def _dedupe_choices_by_value(choices: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for c in choices or []:
        val = (c.get("value") or "").strip()
        if not val or val in seen:
            continue
        seen.add(val)
        out.append(c)
    return out


def _build_related_service_batch_choices(
    *,
    related_services: list[str] | None,
    language_code: str | None,
    batch_index: int = 0,
    batch_size: int = RELATED_SERVICE_BATCH_SIZE,
) -> dict:
    """Build paginated picker choices for service validation.

    Unified-paginator design (post-2026-05-08 bug fix):
      - ordered_all = preferred (RAG-derived, flow-backed) + catalog_unseen
      - Paginate by `batch_size` (default 5).
      - Each non-last batch ends with `RS_OTHER_BATCH_<next>` button.
      - Last batch has no "Other Services" button.

    Bug this fixes: when `related_services` produces 0 flow-backed choices
    (e.g. only "General" + a service whose label doesn't resolve to a
    flow-backed value_code), pre-fix logic returned an empty batch 0 with
    only the "Layanan Lainnya" button — picker had no actual services to
    pick. Now batch 0 falls back to the first 5 catalog services.
    """
    batch_size = max(1, int(batch_size or 1))

    # Step 1: preferred choices from RAG-derived related_services
    preferred = build_service_choices(
        related_services or [],
        value_prefix=SA_POL.SERVICE_AGENT_PREFIX,
    )
    preferred = _dedupe_choices_by_value(preferred)
    preferred_values = {(c.get("value") or "").strip() for c in preferred}

    # Step 2: catalog services NOT already in preferred
    full_catalog = _all_service_catalog_choices()
    catalog_unseen = [
        c for c in full_catalog
        if (c.get("value") or "").strip() not in preferred_values
    ]

    # Step 3: unified ordered list — preferred first, then catalog
    ordered_all = list(preferred) + list(catalog_unseen)

    if not ordered_all:
        return {"choices": [], "batch_index": 0, "total_batches": 1}

    # Step 4: paginate
    total_batches = max(1, (len(ordered_all) + batch_size - 1) // batch_size)
    idx = max(0, min(int(batch_index or 0), total_batches - 1))
    start = idx * batch_size
    end = min(len(ordered_all), start + batch_size)
    chunk = [dict(c) for c in ordered_all[start:end]]

    # Step 5: append "more services" button only if not the last batch
    if idx < total_batches - 1:
        next_batch_no = idx + 1
        chunk.append({
            "value": f"{RELATED_SERVICE_BATCH_PREFIX}{next_batch_no}",
            "label": _other_services_label(language_code, next_batch_no),
            "selected": False,
        })

    return {
        "choices": chunk,
        "batch_index": idx,
        "total_batches": total_batches,
    }

def _build_related_service_batch_response(
    *,
    session_id: str,
    question: str,
    language_name: str,
    language_code: str | None,
    resolved_nick: str | None,
    related_services: list[str],
    rendered_prompt: str,
    response_text: str,
    docs_retrieved_count: int,
    summarization_meta: dict,
    batch_index: int,
    request_started_at: float | None = None,
) -> dict:
    batch_meta = _build_related_service_batch_choices(
        related_services=related_services,
        language_code=language_code,
        batch_index=batch_index,
        batch_size=RELATED_SERVICE_BATCH_SIZE,
    )

    msg_obj = build_picker_message(
        text=response_text,
        choices=batch_meta.get("choices") or [],
        required=True,
    )

    payload = build_chat_turn_payload(
        question=question,
        message=msg_obj,
        route="incontext_service_validation",
        language_name=language_name,
        user_nick=resolved_nick or "",
        prompt_applied=rendered_prompt,
        related_services=related_services,
        docs_retrieved_count=docs_retrieved_count,
        respond_duration=0.0,
        input_token=0,
        output_token=0,
        input_total=int((summarization_meta or {}).get("summary_input") or 0),
        output_total=int((summarization_meta or {}).get("summary_output") or 0),
        summarization_meta=(summarization_meta or {}),
        extra={
            "related_service_batch_index": batch_index,
        },
    )

    result = {"session_id": session_id, **payload}
    result = _finalize_result_language(result, language_code, language_name)
    if request_started_at is not None:
        _attach_request_total_duration(result, request_started_at)
    return result

def _build_reset_service_batch_choices(
    *,
    related_services: list[str] | None,
    language_code: str | None,
    exclude_value_codes: set[str] | None = None,
    batch_index: int = 0,
    batch_size: int = RELATED_SERVICE_BATCH_SIZE,
) -> dict:
    exclude_value_codes = {((x or "").strip().lower()) for x in (exclude_value_codes or set()) if (x or "").strip()}
    batch_size = max(1, int(batch_size or 1))

    first_batch_choices = build_service_choices(
        related_services or [],
        value_prefix=SA_POL.SERVICE_AGENT_PREFIX
    )
    first_batch_choices = _dedupe_choices_by_value(first_batch_choices)

    def _value_code_from_choice(c: dict) -> str:
        raw = (c.get("value") or "").strip()
        if raw.startswith(SA_POL.SERVICE_AGENT_PREFIX):
            return raw[len(SA_POL.SERVICE_AGENT_PREFIX):].strip().lower()
        return raw.lower()

    # exclude general + previous selected service
    first_batch_choices = [
        c for c in first_batch_choices
        if _value_code_from_choice(c) not in exclude_value_codes
    ]

    full_catalog = _all_service_catalog_choices()
    full_catalog = [
        c for c in full_catalog
        if _value_code_from_choice(c) not in exclude_value_codes
    ]

    first_values = {(c.get("value") or "").strip() for c in first_batch_choices}
    remaining_catalog = [
        c for c in full_catalog
        if (c.get("value") or "").strip() not in first_values
    ]

    if batch_index <= 0:
        chunk = [dict(c) for c in first_batch_choices]
        if remaining_catalog:
            chunk.append({
                "value": f"{RELATED_SERVICE_BATCH_PREFIX}1",
                "label": _other_services_label(language_code, 1),
                "selected": False,
            })
        return {
            "choices": chunk,
            "batch_index": 0,
            "total_batches": 1 + ((len(remaining_catalog) + batch_size - 1) // batch_size if remaining_catalog else 0),
        }

    idx = batch_index - 1   # batch 1 = halaman other pertama
    total_other_batches = (len(remaining_catalog) + batch_size - 1) // batch_size if remaining_catalog else 0

    if total_other_batches <= 0:
        return {
            "choices": [],
            "batch_index": batch_index,
            "total_batches": 1,
        }

    idx = min(max(0, idx), total_other_batches - 1)
    start = idx * batch_size
    end = min(len(remaining_catalog), start + batch_size)
    chunk = [dict(c) for c in remaining_catalog[start:end]]
    
    if idx < total_other_batches - 1:
        next_batch_no = idx + 2
        chunk.append({
            "value": f"{RELATED_SERVICE_BATCH_PREFIX}{next_batch_no}",
            "label": _other_services_label(language_code, next_batch_no),
            "selected": False,
        })

    return {
        "choices": chunk,
        "batch_index": batch_index,
        "total_batches": 1 + total_other_batches,
    }

def _append_book_meeting_choice(choices: list[dict], language_code: str | None) -> list[dict]:
    if any((c.get("value") or "").upper() == "BOOK_A_MEETING" for c in choices):
        return choices
    choices.append({
        "value": "BOOK_A_MEETING",
        "label": _book_meeting_label(language_code),
        "selected": False,
    })
    return choices


def _build_service_picker_choices(
    services: list[str],
    language_code: str | None,
    exclude_value_codes: set[str] | None = None,
    include_book_meeting: bool = False,
) -> list[dict]:
    exclude_value_codes = exclude_value_codes or set()
    choices = []
    for s in services:
        value_code, label = _map_related_service_to_value_code(s)
        if not value_code:
            continue
        if value_code in exclude_value_codes:
            continue

        choices.append({
            "value": f"SA_SELECT_{value_code}",
            "label": label,
            "selected": False,
        })

    if include_book_meeting:
        choices = _append_book_meeting_choice(choices, language_code)
    return choices

def _maybe_send_to_monday_final_gate(
    *,
    session_id: str,
    token_id: str | None,
    extra: dict | None = None,
    summarization_meta: dict | None = None,
    force: bool = False,
) -> dict:
    """
    Send monday once and store status in extra['monday_status'].
    Return the monday_status dict (not the whole extra).
    """
    target_extra = extra if isinstance(extra, dict) else {}
    monday_prev = target_extra.get("monday_status")
    if isinstance(monday_prev, dict) and monday_prev.get("ok") and not force:
        return monday_prev

    # prefer MONDAY_PATH (dipakai oleh _post_to_monday_webhook), fallback MONDAY_ENDPOINT bila ada
    url = (getattr(cfg, "MONDAY_PATH", "") or "").strip() or (getattr(cfg, "MONDAY_ENDPOINT", "") or "").strip()
    if not url:
        return {"ok": False, "skipped": True, "error": "MONDAY_PATH/MONDAY_ENDPOINT is empty"}

    sm = summarization_meta or {}
    chat_sum = (sm.get("chat_summarization") or "").strip()

    # transcript dari chat_history (pakai token_id dulu, fallback session-only)
    rows = _read_all_chat_pairs(session_id=session_id, token_id=token_id, limit=2000)
    lines = []
    for i, r in enumerate(rows, start=1):
        q = (r.get("question") or "").strip()
        ans = (r.get("message") or "").strip()
        if q:
            lines.append(f"Q{i}: {q}")
        if ans:
            lines.append(f"A{i}: {ans}")
    transcript = "\n".join(lines).strip()

    ma_ctx = (target_extra.get("meeting_arrangement") or {}) if target_extra else {}
    slot_ctx = ma_ctx.get("selected_slot") or {}
    service_label = (target_extra.get("service_label") or ma_ctx.get("service_label") or "").strip()
    sales_email = (target_extra.get("sales_email") or ma_ctx.get("sales_email") or "").strip()
    sales_name = (target_extra.get("sales_name") or ma_ctx.get("sales_name") or "").strip()
    timezone_label = (ma_ctx.get("timezone_label") or slot_ctx.get("tz_tag") or "").strip()
    timezone_name = (ma_ctx.get("timezone") or "").strip()
    user_ctx = (target_extra.get("user") or {}) if target_extra else {}
    user_nick = (user_ctx.get("nickname") or user_ctx.get("name") or "").strip()
    user_email = (user_ctx.get("email") or "").strip()
    user_phone = (user_ctx.get("phone") or "").strip()
    user_country = (user_ctx.get("country") or "").strip()
    user_city = (user_ctx.get("city") or "").strip()

    selected_slot_text = ""
    slot_date_iso = slot_ctx.get("date_iso")
    if slot_date_iso:
        try:
            slot_date_human = human_date(datetime.fromisoformat(slot_date_iso).date())
        except Exception:
            slot_date_human = slot_date_iso
        slot_label = slot_ctx.get("slot_label") or f"{slot_ctx.get('start', '')}-{slot_ctx.get('end', '')}"
        slot_label = slot_label.strip(" -")
        selected_slot_text = f"{slot_date_human} | {slot_label}"
        if timezone_label:
            selected_slot_text += f" ({timezone_label})"

    has_meeting_selection = bool(selected_slot_text and service_label)

    if has_meeting_selection:
        title = f"Meeting request - {service_label}"
        desc_lines = [
            f"Service: {service_label}",
            f"Selected Slot: {selected_slot_text}",
        ]
        if timezone_name:
            desc_lines.append(f"Timezone ID: {timezone_name}")
        if ma_ctx.get("first_date") and ma_ctx.get("second_date"):
            desc_lines.append(f"Window Range: {ma_ctx.get('first_date')} to {ma_ctx.get('second_date')}")
        if ma_ctx.get("slot_window_index") is not None:
            desc_lines.append(f"Slot Window Index: {ma_ctx.get('slot_window_index')}")
        if ma_ctx.get("other_pick_count"):
            desc_lines.append(f"'Other Slot' Requests: {ma_ctx.get('other_pick_count')} of {ma_ctx.get('max_other_picks')}")
        if sales_name or sales_email:
            desc_lines.append(f"Sales PIC: {sales_name or '-'} {f'({sales_email})' if sales_email else ''}".strip())
        if user_nick or user_email or user_phone:
            contact_parts = []
            if user_nick:
                contact_parts.append(f"Name: {user_nick}")
            if user_email:
                contact_parts.append(f"Email: {user_email}")
            if user_phone:
                contact_parts.append(f"Phone: {user_phone}")
            desc_lines.append("User Contact: " + ", ".join(contact_parts))
        if user_country or user_city:
            desc_lines.append(f"User Location: {user_city}, {user_country}".strip(", "))
        desc_lines.append(f"Session ID: {session_id}")
        if token_id:
            desc_lines.append(f"Token ID: {token_id}")
        if chat_sum:
            desc_lines.extend(["", "Chat Summary:", chat_sum])
        description = "\n".join([line for line in desc_lines if line])
    else:
        title = "Reset conversation / follow-up lead"
        description = chat_sum or "User requested to reset conversation. Please follow up."

    final_convo = {
        "title": title,
        "description": description,
        "transcript": transcript,
        "board_id": getattr(cfg, "MONDAY_BOARD_ID", ""),
        "topics": getattr(cfg, "MONDAY_GROUP_ID", "topics"),
    }

    status = _send_monday_item(final_convo)
    if target_extra is not None:
        target_extra["monday_status"] = status
        if has_meeting_selection:
            ma_ctx["monday_meeting_sent"] = bool(status.get("ok"))
            target_extra["meeting_arrangement"] = ma_ctx
    return status

def _render_reset_text(
    *,
    language_name: str,
    prev_service_label: str,
    related_labels: list[str] | None = None,
    other_related_services: list[str] | None = None,  # <-- alias untuk backward-compat
) -> tuple[str, str]:
    # backward-compat: kalau caller masih kirim other_related_services
    related_labels = (related_labels or []) or (other_related_services or [])

    lang = (language_name or "English").strip()
    prev = (prev_service_label or "").strip()
    rel = ", ".join([x.strip() for x in (related_labels or []) if str(x).strip()]) or "-"

    base = (
        "You are an AI Assistant acting as a professional, instructional, persuasive, and trustworthy business consultant "
        "providing accurate and up-to-date information about Acme Services’s services.\n"
        f"Target language: {lang}. Use the context only if directly relevant; otherwise keep it concise.\n\n"
        "Guidelines:\n"
        "- Your reply MUST be EXACTLY 2–3 sentences in a SINGLE paragraph.\n"
        "- Thank the user for their interest in the previous service, then mention there may be other relevant services.\n"
        "- Ask the user to pick one service from the provided choices.\n"
        "- Do NOT include any internal labels.\n"
        "\n\n"
        "---- reset_text_prompt ----\n"
        "You are a professional business consultant chatbot.\n"
        f"Target language: {lang}.\n\n"
        f"User previously discussed service: {prev}\n"
        f"Other related services detected: {rel}\n\n"
        "Write EXACTLY 2 sentences in ONE paragraph:\n"
        "- Sentence 1: thank the user and confirm we can reset the conversation.\n"
        "- Sentence 2: say we detected other related services and ask the user to choose one of those.\n"
        "No bullets, no markdown.\n"
    )

    prompt = base

    # IMPORTANT: Anthropic sering error kalau cuma SystemMessage; jadi kirim juga HumanMessage.
    prompt_msgs_reset = [SystemMessage(content=prompt), HumanMessage(content="Generate the reset message text.")]
    with audit_llm_call(
        route="system_detection",
        stage="reset_message",
        session_id="",  # TODO(audit): plumb session_id
        token_id=None,
        prompt=prompt_msgs_reset,
    ) as ctx:
        msg = BRIEF_LLM.invoke(prompt_msgs_reset)
        ctx.set_response_from_message(msg)
    text = normalize_single_paragraph(getattr(msg, "content", "") or "")

    return prompt, text

def _service_value_code_from_flow_code(flow_code: str) -> str:
    """
    Convert SA flow_code (mis. 'WBS') -> service_value_code (mis. 'whistleblowing_hotline')
    via inverse lookup of SA_POL.SERVICE_CODE_TO_FLOW_CODE.
    """
    fc = (flow_code or "").strip()
    if not fc:
        return ""
    for svc_val, mapped_fc in (SA_POL.SERVICE_CODE_TO_FLOW_CODE or {}).items():
        if mapped_fc == fc:
            return svc_val
    return ""


def _service_label_from_flow_code(flow_code: str) -> str:
    """
    Convert SA flow_code -> human label (e.g., 'Whistleblowing Hotline')
    using SERVICE_LABEL_CODE_MAP (service_value_code -> label).
    """
    svc_val = _service_value_code_from_flow_code(flow_code)
    if svc_val:
        return SA_POL.SERVICE_LABEL_CODE_MAP.get(svc_val, svc_val)
    # fallback terakhir: balikin flow_code aja
    return (flow_code or "").strip()

def _get_first_flow_question_text(flow_code: str | None) -> str:
    """
    Ambil text pertanyaan pertama langsung dari FLOW_REGISTRY.
    """
    fc = (flow_code or "").strip()
    if not fc:
        return "-"

    flow = FLOW_REGISTRY.get(fc) or {}
    if not isinstance(flow, dict) or not flow:
        return "-"

    def _order_of(step):
        try:
            return int(getattr(step, "order", None) or (step.get("order") if isinstance(step, dict) else 10**6))
        except Exception:
            return 10**6

    def _text_of(step):
        if hasattr(step, "text"):
            return getattr(step, "text", "") or ""
        if isinstance(step, dict):
            return step.get("text") or step.get("question") or ""
        return ""

    steps = list(flow.values())
    steps.sort(key=lambda st: (_order_of(st), getattr(st, "id", "") if hasattr(st, "id") else (st.get("id", "") if isinstance(st, dict) else "")))

    for st in steps:
        txt = (_text_of(st) or "").strip()
        if txt:
            return txt

    return "-"

def _mark_followup_stage(extra_ctx: dict | None, stage: str) -> dict:
    extra_ctx = dict(extra_ctx or {})
    ma_state = dict((extra_ctx.get("meeting_arrangement") or {}))
    ma_state["followup_stage"] = stage
    extra_ctx["meeting_arrangement"] = ma_state
    return extra_ctx

def _pick_natural_lang(rows: list[dict]) -> tuple[str | None, str | None]:
    """
    Ambil bahasa dari message-message sebelumnya yang natural.
    Skip value teknis seperti:
    - PICKED_SLOT_*
    - BOOK_A_MEETING
    - SA_SELECT_*
    """
    for row in reversed(rows):
        q_prev = (row.get("question") or "").strip()
        if not q_prev:
            continue

        if (
            q_prev.startswith("PICKED_SLOT_")
            or q_prev == "BOOK_A_MEETING"
            or q_prev.startswith("SA_SELECT_")
            or q_prev == "OTHER_PICKED_SLOT"
        ):
            continue

        ln = (row.get("language_name") or "").strip()
        if not ln:
            continue

        low = ln.lower()
        if "indo" in low:
            return "id", ln
        if "english" in low:
            return "en", ln
        if "thai" in low:
            return "th", ln
        if "malay" in low:
            return "ms", ln
        if "french" in low:
            return "fr", ln
        if "german" in low or "deutsch" in low:
            return "de", ln
        if "dutch" in low or "nederlands" in low:
            return "nl", ln
        if "romanian" in low or "română" in low or "romana" in low:
            return "ro", ln
        if "japanese" in low or "日本語" in low:
            return "ja", ln
        if "russian" in low or "рус" in low:
            return "ru", ln
        if "italian" in low or "italiano" in low:
            return "it", ln
        if "chinese" in low or "mandarin" in low or "中文" in low:
            return "zh", ln
        if "vietnamese" in low or "tiếng việt" in low or "viet" in low:
            return "vi", ln

    return None, None

# Removed 2026-05-07: duplicate `_is_technical_language_input` definition
# (canonical version at line ~1256). Both bodies were equivalent.

# Removed 2026-05-07: duplicate `_get_locked_language_from_history` definition.
# Original had "lock to first natural turn" semantics — caused user-reported
# bug (reply language stuck at first turn even after user switched). Now the
# canonical version at line ~1343 is a deprecated alias to
# `_majority_language_from_history` (line ~1300). New code should call the
# majority helper directly.

# _handle_reset_conversation removed — Crisp handles "start a new chat" natively.

def _i18n_text(language_code: str | None, *, id_text: str, en_text: str) -> str:
    lc = (language_code or "").strip().lower()
    if lc.startswith("id"):
        return id_text
    return en_text

def _finalize_result_language(result: dict, language_code: str | None, language_name: str | None) -> dict:
    result["language_code"] = (language_code or "").strip()
    result["language_name"] = (language_name or "").strip()
    return result

def handle_chat(session_id: str, question: str, token_id: str | None = None) -> Dict[str, Any]:
    from modules.service_agent.sa_service import SA_ENGINE
    request_t0 = time.monotonic()
    # bikin summarization_meta (first_turn SA biasanya False karena sudah ada history SD)
    first_turn = not has_any_history(session_id, token_id)

    # # RESOLVE NICKNAME — satu-satunya sumber: crisp_sessions
    # resolved_nick = read_user_nick_from_sessions(session_id)  # bisa None jika belum diset

    website_id = token_id or session_id  # sesuai catatan kamu: pakai dari awal, bukan generate baru

    user_profile = fetch_user_profile(session_id=session_id, website_id=website_id) or {}
    resolved_nick = (user_profile.get("nickname") or "").strip() or None
    user_timezone = (user_profile.get("timezone") or "").strip()
    user_email = (user_profile.get("email") or "").strip()
    user_phone = (user_profile.get("phone") or "").strip()

    # # (opsional) simpan ke chat_history/ run_logs agar mudah dilihat di log
    # if resolved_nick:
    #     ensure_user_nick_in_sessions(session_id, resolved_nick)  # tidak mengubah crisp_sessions

    # 1) Language meta — per-turn fresh Claude detection (no cache, no lock).
    # Policy 2026-05-07: bahasa reply mengikuti input PER TURN. Untuk input
    # technical (BOOK_A_MEETING, picker tokens, dll) yang tidak punya bahasa
    # natural, fallback ke majority bahasa dari history.
    q_stripped = (question or "").strip()
    detected_language_code, detected_language_name = build_language_meta(question)

    if _is_technical_language_input(q_stripped):
        majority_code, majority_name = _majority_language_from_history(session_id, token_id)
        language_code = majority_code or detected_language_code
        language_name = majority_name or detected_language_name
    else:
        # Natural input → per-turn detection wins. No history override.
        language_code = detected_language_code
        language_name = detected_language_name

    empty_sm = {
        "summary_applied": "-",
        "summary_input": 0,
        "summary_output": 0,
        "chat_summarization": "-",
    }

    other_batch_match = RELATED_SERVICE_BATCH_RE.match(q_stripped)
    if other_batch_match:
        batch_no = max(1, int(other_batch_match.group(1)))

        # command/value bukan bahasa natural → warisi bahasa dari history
        prev_code, prev_name = _fallback_language_from_history(session_id, token_id)
        language_code = prev_code or language_code
        language_name = prev_name or language_name

        # 2026-05-18: use read_chat_history_full so r.get("message") returns the
        # raw picker dict (read_chat_history strips it to plain text via
        # extract_message_text, breaking the picker.choices base-turn detection
        # for paths that store empty related_services like the meeting-intent
        # initial picker added 2026-05-18).
        rows = read_chat_history_full(session_id=session_id, token_id=token_id, limit=30) or []
        if not rows and token_id:
            rows = read_chat_history_full(session_id=session_id, token_id=None, limit=30) or []

        base_turn = None
        for r in reversed(rows):
            q_prev = (r.get("question") or "").strip()

            # skip command other-batch itu sendiri
            if RELATED_SERVICE_BATCH_RE.match(q_prev):
                continue

            choices_prev = _picker_choices_from_message(r.get("message"))
            has_other_button = any(
                (c.get("value") or "").strip().startswith(RELATED_SERVICE_BATCH_PREFIX)
                for c in choices_prev
            )

            has_related = bool(r.get("related_services") or [])
            has_text = bool(_plain_from_message_field(r.get("message")).strip())

            # picker service validation sebelumnya
            if has_other_button or (has_related and has_text):
                base_turn = r
                break

        if not base_turn:
            fallback_msg = build_string_message(
                _i18n_text(
                    language_code,
                    id_text="Silakan kirim ulang pertanyaan Anda agar saya bisa menampilkan pilihan layanan yang relevan.",
                    en_text="Please resend your question so I can show the relevant service options.",
                )
            )
            payload = build_chat_turn_payload(
                question=question,
                message=fallback_msg,
                route="incontext_service_validation",
                language_name=language_name,
                user_nick=resolved_nick or "",
                prompt_applied="",
                related_services=[],
                docs_retrieved_count=0,
                respond_duration=0.0,
                input_token=0,
                output_token=0,
                input_total=int(empty_sm.get("summary_input") or 0),
                output_total=int(empty_sm.get("summary_output") or 0),
                summarization_meta=empty_sm,
                extra={},
            )
            result = {"session_id": session_id, **payload}
            result = _finalize_result_language(result, language_code, language_name)
            _attach_request_total_duration(result, request_t0)
            log_run(session_id, question, result)
            return result

        prev_language_name = (base_turn.get("language_name") or language_name or "English").strip()
        prev_related_services = base_turn.get("related_services") or []
        prev_prompt = base_turn.get("prompt_applied") or ""
        prev_docs_count = int(base_turn.get("docs_retrieved_count") or 0)

        prev_message = base_turn.get("message") or {}
        prev_text = _plain_from_message_field(prev_message).strip()

        base_extra = base_turn.get("extra") or {}
        prev_service_label = (base_extra.get("previous_service_label") or "").strip()
        prev_service_label = _service_label_from_flow_code(prev_service_label) or "-"

        language_name = prev_language_name or language_name

        last_flow_code = _guess_last_service_code(rows)

        # Reset-mode branch removed — Crisp handles "start a new chat" natively,
        # so the batch-service-picker shown in reset mode is no longer reachable.

        result = _build_related_service_batch_response(
            session_id=session_id,
            question=question,
            language_name=language_name,
            language_code=language_code,
            resolved_nick=resolved_nick,
            related_services=prev_related_services,
            rendered_prompt=prev_prompt,
            response_text=prev_text,
            docs_retrieved_count=prev_docs_count,
            summarization_meta=empty_sm,
            batch_index=batch_no,
            request_started_at=request_t0,
        )
        log_run(session_id, question, result)
        return result

    # BOOK_A_MEETING / action value bukan natural language,
    # jadi wajib mewarisi bahasa dari history agar konsisten.
    if q_stripped == "BOOK_A_MEETING":
        prev_code, prev_name = _fallback_language_from_history(session_id, token_id)
        if prev_name:
            language_name = prev_name
        if prev_code:
            language_code = prev_code

    # setelah first_turn dihitung
    prechecked_sa_active: bool | None = None
    if _parallel_prep_on():
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_summary = pool.submit(
                _maybe_build_summary_meta,
                session_id=session_id,
                token_id=token_id,
                first_turn=first_turn,
                language_name_hint=language_name,
            )
            f_sa_active = pool.submit(_sa_is_active, session_id)
            summary_block_cache, sm = f_summary.result()
            prechecked_sa_active = f_sa_active.result()
    else:
        summary_block_cache, sm = _maybe_build_summary_meta(
            session_id=session_id,
            token_id=token_id,
            first_turn=first_turn,
            language_name_hint=language_name,
        )
    summary_meta_cache = _summary_meta_from_sm(sm)

    # Previous RESET_CONVERSATION / RESET_CONVERSATION_AFTER_MEETING handlers
    # were removed — Crisp handles "start a new chat" natively.

    if q_stripped == "CONTINUE_QUALIFICATION":
        # kalau kamu sudah punya existing logic untuk lanjut, biarkan pakai yang sekarang.
        # (biasanya cukup panggil _render_sa_continue_via_sd / SA_ENGINE.commit_turn(advance=True))
        pass

    pre_meeting_intent = (
        q_stripped == "BOOK_A_MEETING"
        or is_meeting_request(question, language_code)
    )

    if pre_meeting_intent:
        # ── DIRECT CHECK via _find_existing_booked_meeting ──
        # Selalu baca booking dari history langsung (baca MongoDB via _read_all_chat_pairs
        # yang sudah di-fix untuk include field 'extra'), bukan dari ctx yang bisa sudah
        # ter-overwrite oleh service baru (FRI) setelah reset.
        _direct_booked = _find_existing_booked_meeting(
            session_id=session_id, token_id=token_id
        )

        if _direct_booked:
            # ── Ada booking sebelumnya: build already_picked_validation ──
            # Ambil info dari booking LAMA (WBS), bukan current context (FRI)
            _db_extra   = dict((_direct_booked.get("extra") or {}))
            _db_ma      = dict((_db_extra.get("meeting_arrangement") or {}))
            _db_slot    = dict((_db_ma.get("selected_slot") or {}))

            # service_label HARUS dari booking lama, bukan current FRI context
            _booked_svc_lbl  = (_direct_booked.get("service_label") or _db_extra.get("service_label") or "").strip()
            _booked_svc_email= (_direct_booked.get("sales_email")   or _db_extra.get("sales_email")   or "").strip()
            _booked_svc_name = (_direct_booked.get("sales_name")    or _db_extra.get("sales_name")    or "").strip()

            _tz   = (_db_ma.get("timezone") or "Asia/Jakarta").strip() or "Asia/Jakarta"
            try:
                _zone = ZoneInfo(_tz)
            except Exception:
                _zone = ZoneInfo("Asia/Jakarta")
                _tz   = "Asia/Jakarta"

            from modules.system_detection.meeting_arrangement.ma_service import (
                _tz_label as _ma_tz_label,
                _format_existing_booking_texts,
            )
            _tz_lbl, _ = _ma_tz_label(_tz)

            _booked_date_txt, _booked_slot_txt = _format_existing_booking_texts(
                date_iso=_db_slot.get("date_iso", ""),
                start=_db_slot.get("start", ""),
                end=_db_slot.get("end", ""),
                tz_label=_tz_lbl,
                timezone_name=_tz,
            )

            from modules.system_detection.meeting_arrangement.ma_prompts import (
                render_existing_meeting_warning_prompt,
            )
            _now_local = datetime.now(_zone)

            _warn_prompt = render_existing_meeting_warning_prompt(
                language_name=language_name,
                language_code=language_code,
                is_first_turn=False,
                user_nick=resolved_nick,
                user_email=None,
                # ← pakai service dari booking LAMA (WBS), bukan current (FRI)
                service_label=_booked_svc_lbl,
                booked_date_txt=_booked_date_txt,
                booked_slot_txt=_booked_slot_txt,
                tz_label=_tz_lbl,
                current_hour_24=_now_local.hour,
                max_chars=getattr(cfg, "INPUT_MAX_PROMPT", 1200),
                chat_history_block=None,
                chat_summary_block=None,
            )

            prompt_msgs_route_g = [
                SystemMessage(content=_warn_prompt),
                HumanMessage(content=question or "User is asking for another meeting.")
            ]
            with audit_llm_call(
                route="system_detection",
                stage="route_g_compose",
                session_id=session_id,
                token_id=token_id,
                prompt=prompt_msgs_route_g,
            ) as ctx:
                _llm_g = BRIEF_LLM.invoke(prompt_msgs_route_g)
                ctx.set_response_from_message(_llm_g)
            _warn_text = normalize_single_paragraph(getattr(_llm_g, "content", "") or "")
            _in_g    = ctx.input_tokens
            _out_g   = ctx.output_tokens
            _dur_g   = ctx.latency_ms / 1000.0

            # bahasa dari history (bukan dari command teknis)
            _ab_code = language_code
            try:
                _hr = read_language_history(session_id, token_id=token_id, limit=6) or []
                _ac, _an = _pick_natural_lang(_hr)
                if _ac:
                    _ab_code = _ac
            except Exception:
                pass

            _db_ma["booking_completed"] = True
            _db_ma["followup_stage"]    = "already_booked_warning"
            _db_extra["meeting_arrangement"] = _db_ma

            # Crisp handles reset natively — string, not picker.
            _msg_g = build_string_message(_warn_text)
            _payload_g = build_chat_turn_payload(
                question=question,
                message=_msg_g,
                route="meeting_arrangement_already_picked_validation",
                language_name=language_name,
                user_nick=resolved_nick or "",
                prompt_applied=_warn_prompt,
                related_services=[_booked_svc_lbl] if _booked_svc_lbl else [],
                docs_retrieved_count=0,
                respond_duration=_dur_g,
                input_token=_in_g,
                output_token=_out_g,
                input_total=_in_g + int(sm.get("summary_input") or 0),
                output_total=_out_g + int(sm.get("summary_output") or 0),
                summarization_meta=sm,
                extra=_db_extra,
            )
            _result_g = {"session_id": session_id, **_payload_g}
            _attach_request_total_duration(_result_g, request_t0)
            log_run(session_id, question, _result_g)
            _cache_meeting_context_entry(
                session_id,
                service_label=_booked_svc_lbl,
                sales_email=_booked_svc_email,
                sales_name=_booked_svc_name,
                extra=_db_extra,
            )
            _schedule_summary_refresh(
                session_id=session_id, token_id=token_id, language_name_hint=language_name
            )
            return _result_g

        # ── Belum ada booking: lanjut ke flow normal ──
        ctx_guard = _load_meeting_context(session_id=session_id, token_id=token_id)
        extra_guard = dict((ctx_guard.get("extra") or {}))

        service_label_guard = (
            (ctx_guard.get("service_label") or "").strip()
            or (extra_guard.get("service_label") or "").strip()
        )
        sales_email_guard = (
            (ctx_guard.get("sales_email") or "").strip()
            or (extra_guard.get("sales_email") or "").strip()
        )
        sales_name_guard = (
            (ctx_guard.get("sales_name") or "").strip()
            or (extra_guard.get("sales_name") or "").strip()
        )

        if not service_label_guard:
            _rows_scan = _read_all_chat_pairs(session_id=session_id, token_id=token_id, limit=500) or []
            if not _rows_scan and token_id:
                _rows_scan = _read_all_chat_pairs(session_id=session_id, token_id=None, limit=500) or []
            for _row in reversed(_rows_scan):
                _ex = _row.get("extra") or {}
                _ma = _ex.get("meeting_arrangement") or {}
                if bool(_ma.get("booking_completed")) and _ma.get("selected_slot"):
                    service_label_guard = (_ex.get("service_label") or "").strip() or service_label_guard
                    sales_email_guard   = (_ex.get("sales_email") or "").strip()   or sales_email_guard
                    sales_name_guard    = (_ex.get("sales_name") or "").strip()    or sales_name_guard
                    break

        if service_label_guard and not sales_email_guard:
            try:
                pic = fetch_sales_pic_by_service(service_label_guard) or {}
            except Exception:
                pic = {}
            sales_email_guard = (pic.get("sales_email") or pic.get("email") or "").strip()
            if sales_email_guard:
                extra_guard["sales_email"] = sales_email_guard
            if not sales_name_guard:
                sales_name_guard = (pic.get("sales_name") or pic.get("name") or "").strip()
                if sales_name_guard:
                    extra_guard["sales_name"] = sales_name_guard

        if service_label_guard and sales_email_guard:
            guard_plan = build_meeting_choices_now(
                session_id=session_id,
                website_id=token_id or session_id,
                token_id=token_id,
                service_label=service_label_guard,
                sales_email=sales_email_guard,
                sales_name=sales_name_guard,
                language_name=language_name,
                language_code=language_code,
                user_nick=resolved_nick,
                is_first_turn=first_turn,
                last_extra=extra_guard,
                max_other_picks=MAX_OTHER_SLOT_PICKS,
                slot_window_index=int(((extra_guard.get("meeting_arrangement") or {}).get("slot_window_index") or 0)),
            )

            already_booked_result = _maybe_build_already_booked_result(
                slot_plan=guard_plan,
                question=question,
                session_id=session_id,
                request_t0=request_t0,
                token_id=token_id,
                language_name=language_name,
                resolved_nick=resolved_nick,
                related_services=[service_label_guard] if service_label_guard else [],
                summarization_meta=sm,
                service_label=service_label_guard,
                sales_email=sales_email_guard,
                sales_name=sales_name_guard,
            )
            if already_booked_result:
                return already_booked_result

    force_book_meeting = q_stripped == "BOOK_A_MEETING"
    meeting_check_text = question
    meeting_detected = force_book_meeting or is_meeting_request(meeting_check_text, language_code)

    rows_recent = read_chat_history(session_id=session_id, token_id=token_id, limit=20) or []
    if not rows_recent and token_id:
        rows_recent = read_chat_history(session_id=session_id, token_id=None, limit=20) or []

    reset_ready = False
    for r in reversed(rows_recent):
        extra_r = r.get("extra") or {}
        ma_r = extra_r.get("meeting_arrangement") or {}
        if ma_r.get("reset_ready") is True:
            reset_ready = True
            break

    if reset_ready and not force_book_meeting:
        meeting_detected = False

    last_extra: dict | None = None

    last_extra: dict | None = None
    # === MEETING ARRANGEMENT (direct picker) ===
    if meeting_detected:
        ctx = _load_meeting_context(session_id=session_id, token_id=token_id)
        ctx_extra = ctx.get("extra") if isinstance(ctx.get("extra"), dict) else {}
        if ctx_extra is None:
            ctx_extra = {}
        ctx_extra = dict(ctx_extra)
        ma_state_ctx = dict((ctx_extra.get("meeting_arrangement") or {}))
        ctx_extra["meeting_arrangement"] = ma_state_ctx
        service_label_ctx = (ctx.get("service_label") or "").strip()
        sales_email_ctx = (ctx.get("sales_email") or "").strip()
        sales_name_ctx = (ctx.get("sales_name") or "").strip()
        if service_label_ctx and not ctx_extra.get("service_label"):
            ctx_extra["service_label"] = service_label_ctx
        if sales_email_ctx and not ctx_extra.get("sales_email"):
            ctx_extra["sales_email"] = sales_email_ctx
        if sales_name_ctx and not ctx_extra.get("sales_name"):
            ctx_extra["sales_name"] = sales_name_ctx
        last_extra = ctx_extra

        history_block = None
        summary_block = None
        related_services: list[str] = []
        filtered: list[str] = []
        sm = sm or {}

        service_label = (ctx_extra.get("service_label") or "").strip()
        sales_email = (ctx_extra.get("sales_email") or "").strip()
        sales_name = (ctx_extra.get("sales_name") or "").strip()
        try:
            window_index_ctx = int(ma_state_ctx.get("slot_window_index") or 0)
        except Exception:
            window_index_ctx = 0
        try:
            service_batch_index_ctx = int(ma_state_ctx.get("service_batch_index") or 0)
        except Exception:
            service_batch_index_ctx = 0

        if service_label and not sales_email:
            try:
                pic = fetch_sales_pic_by_service(service_label) or {}
            except Exception:
                pic = {}
            sales_email = (pic.get("sales_email") or pic.get("email") or "").strip()
            if sales_email:
                ctx_extra["sales_email"] = sales_email
            if not sales_name:
                sales_name = (pic.get("sales_name") or pic.get("name") or "").strip()
                if sales_name:
                    ctx_extra["sales_name"] = sales_name

        if service_label and sales_email:
            website_id = token_id or session_id
            slot_plan = build_meeting_choices_now(
                session_id=session_id,
                website_id=website_id,
                token_id=token_id,
                service_label=service_label,
                sales_email=sales_email,
                sales_name=sales_name,
                language_name=language_name,
                language_code=language_code,
                user_nick=resolved_nick,
                is_first_turn=first_turn,
                last_extra=ctx_extra,
                max_other_picks=MAX_OTHER_SLOT_PICKS,
                slot_window_index=window_index_ctx,
            )

            already_booked_result = _maybe_build_already_booked_result(
                slot_plan=slot_plan,
                question=question,
                session_id=session_id,
                request_t0=request_t0,
                token_id=token_id,
                language_name=language_name,
                resolved_nick=resolved_nick,
                related_services=[service_label] if service_label else [],
                summarization_meta=sm,
                service_label=service_label,
                sales_email=sales_email,
                sales_name=sales_name,
            )
            if already_booked_result:
                return already_booked_result

            if slot_plan.get("message") and slot_plan.get("route") == "meeting_arrangement_no_slots":
                msg_text = (
                    (((slot_plan.get("message") or {}).get("content") or {}).get("text"))
                    or "We’re preparing your meeting options. Please share your preferred time window."
                )
                msg_obj = build_string_message(msg_text)
                _cache_meeting_context_entry(
                    session_id,
                    service_label=service_label,
                    sales_email=sales_email,
                    sales_name=sales_name,
                    extra=slot_plan.get("extra") or {},
                )
                payload = build_chat_turn_payload(
                    question=question,
                    message=msg_obj,
                    route=slot_plan.get("route", "meeting_arrangement_no_slots"),
                    language_name=language_name,
                    user_nick=resolved_nick,
                    prompt_applied="",
                    related_services=[service_label] if service_label else [],
                    docs_retrieved_count=0,
                    respond_duration=0.0,
                    input_token=0,
                    output_token=0,
                    input_total=int((sm or {}).get("summary_input") or 0),
                    output_total=int((sm or {}).get("summary_output") or 0),
                    summarization_meta=sm,
                    extra=slot_plan.get("extra") or {},
                )
                result = {"session_id": session_id, **payload}
                result = _finalize_result_language(result, language_code, language_name)
                _attach_request_total_duration(result, request_t0)
                log_run(session_id, question, result)
                _schedule_summary_refresh(session_id=session_id, token_id=token_id, language_name_hint=language_name)
                return result

            picker_choices = slot_plan["choices"]
            picker_text = build_meeting_picker_preamble(
                language_code=language_code,
                service_label=service_label,
                nickname=resolved_nick,
            )
            in_tok = 0
            out_tok = 0
            dur = 0.0
            input_total = int(sm.get("summary_input") or 0)
            output_total = int(sm.get("summary_output") or 0)

            msg_obj = build_picker_message(text=picker_text, choices=picker_choices, required=True)
            _cache_meeting_context_entry(
                session_id,
                service_label=service_label,
                sales_email=sales_email,
                sales_name=sales_name,
                extra=slot_plan.get("extra") or {},
            )
            payload = build_chat_turn_payload(
                question=question,
                message=msg_obj,
                route=slot_plan["route"],
                language_name=language_name,
                user_nick=resolved_nick,
                prompt_applied="",
                related_services=[service_label] if service_label else [],
                docs_retrieved_count=0,
                respond_duration=dur,
                input_token=in_tok,
                output_token=out_tok,
                input_total=input_total,
                output_total=output_total,
                summarization_meta=sm,
                extra=slot_plan.get("extra"),
            )
            result = {"session_id": session_id, **payload}
            result = _finalize_result_language(result, language_code, language_name)
            _attach_request_total_duration(result, request_t0)
            log_run(session_id, question, result)
            _schedule_summary_refresh(session_id=session_id, token_id=token_id, language_name_hint=language_name)
            return result

        # 2026-05-18: when meeting requested but no specific service yet, show the
        # SA validation picker (SA_SELECT_* + clean "Other Services" via RS_OTHER_BATCH_*)
        # instead of the MA picker. After pick, the existing SA_SELECT_ handler routes
        # to qualification — meeting popup will appear later once min-set is collected.
        plan = plan_meeting_service_picker(
            language_name=language_name,
            language_code=language_code,
            is_first_turn=first_turn,
            user_nick=resolved_nick,
            user_email=(user_profile.get("email") if user_profile else None),
            service_label=(last_extra.get("service_label") if last_extra else None),
            chat_history_block=history_block,
            chat_summary_block=summary_block,
            max_prompt_chars=cfg.INPUT_MAX_PROMPT,
            service_batch_index=service_batch_index_ctx,
        )

        rendered_prompt = plan["prompt"]
        validation_batch_meta = _build_related_service_batch_choices(
            related_services=[],
            language_code=language_code,
            batch_index=service_batch_index_ctx,
            batch_size=RELATED_SERVICE_BATCH_SIZE,
        )
        choices = validation_batch_meta.get("choices") or []
        ma_state_ctx["stage"] = "select_service"
        ma_state_ctx["service_batch_index"] = validation_batch_meta.get("batch_index", service_batch_index_ctx)
        ma_state_ctx["service_total_batches"] = validation_batch_meta.get("total_batches", 1)
        ma_state_ctx["followup_stage"] = "qualification_ongoing"
        ctx_extra["meeting_arrangement"] = ma_state_ctx
        ctx_extra["user"] = user_profile or ctx_extra.get("user") or {}
        last_extra = ctx_extra

        prompt_msgs_rag_main_v2 = [SystemMessage(content=rendered_prompt), HumanMessage(content=question)]
        with audit_llm_call(
            route="system_detection",
            stage="rag_main_reply_v2",
            session_id=session_id,
            token_id=token_id,
            prompt=prompt_msgs_rag_main_v2,
        ) as ctx:
            msg = BRIEF_LLM.invoke(prompt_msgs_rag_main_v2)
            ctx.set_response_from_message(msg)
        text = normalize_single_paragraph(getattr(msg, "content", "") or "")
        in_tok = ctx.input_tokens
        out_tok = ctx.output_tokens
        input_total = in_tok + int(sm.get("summary_input") or 0)
        output_total = out_tok + int(sm.get("summary_output") or 0)
        dur = ctx.latency_ms / 1000.0

        msg_obj = build_picker_message(text=text, choices=choices, required=True)

        payload = build_chat_turn_payload(
            question=question,
            message=msg_obj,
            route="incontext_service_validation",
            language_name=language_name,
            user_nick=resolved_nick,
            prompt_applied=rendered_prompt,
            related_services=related_services,
            docs_retrieved_count=0,
            respond_duration=dur,
            input_token=in_tok,
            output_token=out_tok,
            input_total=input_total,
            output_total=output_total,
            summarization_meta=sm,
            extra=ctx_extra,
        )

        result = {"session_id": session_id, **payload}
        result = _finalize_result_language(result, language_code, language_name)
        _attach_request_total_duration(result, request_t0)
        log_run(session_id, question, result)
        _cache_meeting_context_entry(
            session_id,
            service_label=(ctx_extra.get("service_label") or "").strip(),
            sales_email=(ctx_extra.get("sales_email") or "").strip(),
            sales_name=(ctx_extra.get("sales_name") or "").strip(),
            extra=ctx_extra,
        )
        _schedule_summary_refresh(session_id=session_id, token_id=token_id, language_name_hint=language_name)
        return result

    # user picked service for meeting arrangement ===
    if _is_ma_service_choice(question):
        other_batch_match = _OTHER_SERVICE_BATCH_RE.match(q_stripped)
        if other_batch_match:
            batch_index = max(0, int(other_batch_match.group(1)) - 1)
            ctx = _load_meeting_context(session_id=session_id, token_id=token_id)
            extra_ctx = ctx.get("extra") if isinstance(ctx.get("extra"), dict) else {}
            if extra_ctx is None:
                extra_ctx = {}
            extra_ctx = dict(extra_ctx)
            ma_state = dict((extra_ctx.get("meeting_arrangement") or {}))
            extra_ctx["meeting_arrangement"] = ma_state
            ma_state["stage"] = "select_service"
            ma_state["service_batch_index"] = batch_index
            ma_state["followup_stage"] = "qualification_ongoing"
            extra_ctx["user"] = user_profile or extra_ctx.get("user") or {}

            plan = plan_meeting_service_picker(
                language_name=language_name,
                language_code=language_code,
                is_first_turn=False,
                user_nick=resolved_nick,
                user_email=(user_profile.get("email") if user_profile else None),
                service_label=(extra_ctx.get("service_label") or None),
                chat_history_block=None,
                chat_summary_block=None,
                max_prompt_chars=cfg.INPUT_MAX_PROMPT,
                service_batch_index=batch_index,
            )
            ma_state["service_batch_index"] = plan.get("batch_index", batch_index)
            ma_state["service_total_batches"] = plan.get("total_batches", 1)
            extra_ctx["meeting_arrangement"] = ma_state

            prompt_text = plan["prompt"]
            picker_choices = plan["choices"]
            prompt_msgs_rag_main_v3 = [SystemMessage(content=prompt_text), HumanMessage(content=question)]
            with audit_llm_call(
                route="system_detection",
                stage="rag_main_reply_v3",
                session_id=session_id,
                token_id=token_id,
                prompt=prompt_msgs_rag_main_v3,
            ) as ctx:
                llm_msg = BRIEF_LLM.invoke(prompt_msgs_rag_main_v3)
                ctx.set_response_from_message(llm_msg)
            picker_text = normalize_single_paragraph(getattr(llm_msg, "content", "") or "")
            in_tok = ctx.input_tokens
            out_tok = ctx.output_tokens
            dur = ctx.latency_ms / 1000.0
            input_total = in_tok + int((sm or {}).get("summary_input") or 0)
            output_total = out_tok + int((sm or {}).get("summary_output") or 0)

            msg_obj = build_picker_message(text=picker_text, choices=picker_choices, required=True)
            payload = build_chat_turn_payload(
                question=question,
                message=msg_obj,
                route="meeting_arrangement_select_service",
                language_name=language_name,
                user_nick=resolved_nick or "",
                prompt_applied=prompt_text,
                related_services=[],
                docs_retrieved_count=0,
                respond_duration=dur,
                input_token=in_tok,
                output_token=out_tok,
                input_total=input_total,
                output_total=output_total,
                summarization_meta=(sm or {}),
                extra=extra_ctx,
            )
            result = {"session_id": session_id, **payload}
            result = _finalize_result_language(result, language_code, language_name)
            _attach_request_total_duration(result, request_t0)
            log_run(session_id, question, result)
            _cache_meeting_context_entry(
                session_id,
                service_label=(extra_ctx.get("service_label") or "").strip(),
                sales_email=(extra_ctx.get("sales_email") or "").strip(),
                sales_name=(extra_ctx.get("sales_name") or "").strip(),
                extra=extra_ctx,
            )
            _schedule_summary_refresh(session_id=session_id, token_id=token_id, language_name_hint=language_name)
            return result

        plan = handle_meeting_service_selected(
            session_id=session_id,
            question=question,
            last_extra=(last_extra or {}),
        )

        extra_after = plan.get("extra") or {}
        ma_state_after = dict((extra_after.get("meeting_arrangement") or {}))
        ma_state_after["followup_stage"] = "qualification_ongoing"
        extra_after["meeting_arrangement"] = ma_state_after
        service_label = (plan.get("service_label") or extra_after.get("service_label") or "").strip()
        sales_email = (plan.get("sales_email") or extra_after.get("sales_email") or "").strip()
        sales_name = (plan.get("sales_name") or extra_after.get("sales_name") or "").strip()
        try:
            window_index_after = int(ma_state_after.get("slot_window_index") or 0)
        except Exception:
            window_index_after = 0

        if service_label and sales_email:
            website_id = token_id or session_id
            slot_plan = build_meeting_choices_now(
                session_id=session_id,
                website_id=website_id,
                token_id=token_id,
                service_label=service_label,
                sales_email=sales_email,
                sales_name=sales_name,
                language_name=language_name,
                language_code=language_code,
                user_nick=resolved_nick,
                is_first_turn=first_turn,
                last_extra=extra_after,
                max_other_picks=MAX_OTHER_SLOT_PICKS,
                slot_window_index=window_index_after,
            )
            already_booked_result = _maybe_build_already_booked_result(
                slot_plan=slot_plan,
                question=question,
                session_id=session_id,
                request_t0=request_t0,
                token_id=token_id,
                language_name=language_name,
                resolved_nick=resolved_nick,
                related_services=[service_label] if service_label else [],
                summarization_meta=sm,
                service_label=service_label,
                sales_email=sales_email,
                sales_name=sales_name,
            )
            if already_booked_result:
                return already_booked_result
            if slot_plan.get("message") and slot_plan.get("route") == "meeting_arrangement_no_slots":
                msg_text = (
                    (((slot_plan.get("message") or {}).get("content") or {}).get("text"))
                    or "We’re preparing meeting options. Please share your preferred schedule."
                )
                msg_obj = build_string_message(msg_text)
                _cache_meeting_context_entry(
                    session_id,
                    service_label=service_label,
                    sales_email=sales_email,
                    sales_name=sales_name,
                    extra=slot_plan.get("extra") or {},
                )
                payload = build_chat_turn_payload(
                    question=question,
                    message=msg_obj,
                    route=slot_plan.get("route", "meeting_arrangement_no_slots"),
                    language_name=language_name,
                    user_nick=resolved_nick or "",
                    prompt_applied="",
                    related_services=[service_label],
                    docs_retrieved_count=0,
                    respond_duration=0.0,
                    input_token=0,
                    output_token=0,
                    input_total=int((sm or {}).get("summary_input") or 0),
                    output_total=int((sm or {}).get("summary_output") or 0),
                    summarization_meta=(sm or {}),
                    extra=slot_plan.get("extra") or {},
                )
                result = {"session_id": session_id, **payload}
                result = _finalize_result_language(result, language_code, language_name)
                _attach_request_total_duration(result, request_t0)
                log_run(session_id, question, result)
                _schedule_summary_refresh(session_id=session_id, token_id=token_id, language_name_hint=language_name)
                return result

            picker_choices = slot_plan["choices"]
            picker_text = build_meeting_picker_preamble(
                language_code=language_code,
                service_label=service_label,
                nickname=resolved_nick,
            )
            sm = sm or {}
            in_tok = 0
            out_tok = 0
            dur = 0.0
            input_total = int(sm.get("summary_input") or 0)
            output_total = int(sm.get("summary_output") or 0)

            msg_obj = build_picker_message(text=picker_text, choices=picker_choices, required=True)
            _cache_meeting_context_entry(
                session_id,
                service_label=service_label,
                sales_email=sales_email,
                sales_name=sales_name,
                extra=slot_plan.get("extra") or {},
            )
            payload = build_chat_turn_payload(
                question=question,
                message=msg_obj,
                route=slot_plan["route"],
                language_name=language_name,
                user_nick=resolved_nick or "",
                prompt_applied="",
                related_services=[service_label],
                docs_retrieved_count=0,
                respond_duration=dur,
                input_token=in_tok,
                output_token=out_tok,
                input_total=input_total,
                output_total=output_total,
                summarization_meta=sm,
                extra=slot_plan.get("extra") or {},
            )
            result = {"session_id": session_id, **payload}
            result = _finalize_result_language(result, language_code, language_name)
            _attach_request_total_duration(result, request_t0)
            log_run(session_id, question, result)
            _schedule_summary_refresh(session_id=session_id, token_id=token_id, language_name_hint=language_name)
            return result

        if (language_code or "").lower().startswith("id"):
            text = "Baik, saya sudah catat layanan yang ingin Anda bahas. Saya akan siapkan jadwal meeting yang tersedia."
        else:
            text = "Okay, I’ve noted the service you’d like to discuss. I’ll prepare the available meeting schedule."

        msg_obj = build_string_message(text)

        payload = build_chat_turn_payload(
            question=question,
            message=msg_obj,
            route="ma_getting_sales_email",
            language_name=language_name,
            user_nick=resolved_nick or "",
            prompt_applied="",
            related_services=[],
            docs_retrieved_count=0,
            respond_duration=0.0,
            input_token=0,
            output_token=0,
            input_total=int((sm or {}).get("summary_input") or 0),
            output_total=int((sm or {}).get("summary_output") or 0),
            summarization_meta=(sm or {}),
            extra=extra_after,
        )

        result = {"session_id": session_id, **payload}
        result = _finalize_result_language(result, language_code, language_name)
        _attach_request_total_duration(result, request_t0)
        log_run(session_id, question, result)
        _schedule_summary_refresh(session_id=session_id, token_id=token_id, language_name_hint=language_name)
        return result

    if _is_ma_slot_choice(question):
        ctx = _load_meeting_context(session_id=session_id, token_id=token_id)
        extra_ctx = ctx.get("extra") if isinstance(ctx.get("extra"), dict) else {}
        if extra_ctx is None:
            extra_ctx = {}
        extra_ctx = dict(extra_ctx)
        service_label_ctx = (ctx.get("service_label") or "").strip()
        if service_label_ctx and not extra_ctx.get("service_label"):
            extra_ctx["service_label"] = service_label_ctx
        sales_email_ctx = (ctx.get("sales_email") or "").strip()
        if sales_email_ctx and not extra_ctx.get("sales_email"):
            extra_ctx["sales_email"] = sales_email_ctx
        sales_name_ctx = (ctx.get("sales_name") or "").strip()
        if sales_name_ctx and not extra_ctx.get("sales_name"):
            extra_ctx["sales_name"] = sales_name_ctx

        service_label = (extra_ctx.get("service_label") or "").strip()
        sales_email = (extra_ctx.get("sales_email") or "").strip()
        sales_name = (extra_ctx.get("sales_name") or "").strip()

        ma_state = dict((extra_ctx.get("meeting_arrangement") or {}))
        extra_ctx["meeting_arrangement"] = ma_state

        if not service_label or not sales_email:
            fallback_text = build_meeting_footer(language_code)
            msg_obj = build_string_message(fallback_text)
            payload = build_chat_turn_payload(
                question=question,
                message=msg_obj,
                route="meeting_arrangement_missing_context",
                language_name=language_name,
                user_nick=resolved_nick or "",
                prompt_applied="",
                related_services=[],
                docs_retrieved_count=0,
                respond_duration=0.0,
                input_token=0,
                output_token=0,
                input_total=int((sm or {}).get("summary_input") or 0),
                output_total=int((sm or {}).get("summary_output") or 0),
                summarization_meta=(sm or {}),
                extra=extra_ctx,
            )
            result = {"session_id": session_id, **payload}
            result = _finalize_result_language(result, language_code, language_name)
            _attach_request_total_duration(result, request_t0)
            log_run(session_id, question, result)
            _schedule_summary_refresh(session_id=session_id, token_id=token_id, language_name_hint=language_name)
            return result

        if q_stripped == "OTHER_PICKED_SLOT":
            limit = int(ma_state.get("max_other_picks") or MAX_OTHER_SLOT_PICKS)
            count = int(ma_state.get("other_pick_count") or 0) + 1
            ma_state["other_pick_count"] = count

            try:
                current_window_index = int(ma_state.get("slot_window_index") or 0)
            except Exception:
                current_window_index = 0
            next_window_index = current_window_index + 1
            ma_state["slot_window_index"] = next_window_index
            extra_ctx["meeting_arrangement"] = ma_state

            is_boundary = (count >= limit)
            website_id = token_id or session_id

            slot_plan = build_meeting_choices_now(
                session_id=session_id,
                website_id=website_id,
                token_id=token_id,
                service_label=service_label,
                sales_email=sales_email,
                sales_name=sales_name,
                language_name=language_name,
                language_code=language_code,
                user_nick=resolved_nick,
                is_first_turn=False,
                last_extra=extra_ctx,
                max_other_picks=limit,
                slot_window_index=next_window_index,
                include_other=(not is_boundary),
            )

            already_booked_result = _maybe_build_already_booked_result(
                slot_plan=slot_plan,
                question=question,
                session_id=session_id,
                request_t0=request_t0,
                token_id=token_id,
                language_name=language_name,
                resolved_nick=resolved_nick,
                related_services=[service_label] if service_label else [],
                summarization_meta=sm,
                service_label=service_label,
                sales_email=sales_email,
                sales_name=sales_name,
            )
            if already_booked_result:
                return already_booked_result

            # Edge case: no slots available for the next window.
            # Non-boundary: emit the existing no-slots payload as-is.
            # Boundary: fall back to text-only footer (Sales redirect) under meeting_arrangement_other_limit.
            if slot_plan.get("message"):
                if is_boundary:
                    _cache_meeting_context_entry(
                        session_id,
                        service_label=service_label,
                        sales_email=sales_email,
                        sales_name=sales_name,
                        extra=slot_plan.get("extra") or extra_ctx,
                    )
                    footer_text = build_meeting_footer(language_code)
                    msg_obj = build_string_message(footer_text)
                    payload = build_chat_turn_payload(
                        question=question,
                        message=msg_obj,
                        route="meeting_arrangement_other_limit",
                        language_name=language_name,
                        user_nick=resolved_nick or "",
                        prompt_applied="",
                        related_services=[service_label] if service_label else [],
                        docs_retrieved_count=0,
                        respond_duration=0.0,
                        input_token=0,
                        output_token=0,
                        input_total=int((sm or {}).get("summary_input") or 0),
                        output_total=int((sm or {}).get("summary_output") or 0),
                        summarization_meta=(sm or {}),
                        extra=slot_plan.get("extra") or extra_ctx,
                    )
                    result = {"session_id": session_id, **payload}
                    result = _finalize_result_language(result, language_code, language_name)
                    _attach_request_total_duration(result, request_t0)
                    log_run(session_id, question, result)
                    _schedule_summary_refresh(session_id=session_id, token_id=token_id, language_name_hint=language_name)
                    return result
                _cache_meeting_context_entry(
                    session_id,
                    service_label=service_label,
                    sales_email=sales_email,
                    sales_name=sales_name,
                    extra=slot_plan.get("extra") or {},
                )
                return _attach_request_total_duration(slot_plan, request_t0)

            # Normal path: emit picker with localized preamble (non-boundary) or
            # localized Sales-redirect footer (boundary).
            picker_choices = slot_plan["choices"]
            picker_text = (
                build_meeting_footer(language_code)
                if is_boundary
                else build_meeting_picker_preamble(
                    language_code=language_code,
                    service_label=service_label,
                    nickname=resolved_nick,
                )
            )
            sm_local = sm or {}
            route = "meeting_arrangement_other_limit" if is_boundary else "meeting_arrangement_pick_slot"

            msg_obj = build_picker_message(text=picker_text, choices=picker_choices, required=True)
            _cache_meeting_context_entry(
                session_id,
                service_label=service_label,
                sales_email=sales_email,
                sales_name=sales_name,
                extra=slot_plan.get("extra") or {},
            )
            payload = build_chat_turn_payload(
                question=question,
                message=msg_obj,
                route=route,
                language_name=language_name,
                user_nick=resolved_nick or "",
                prompt_applied="",
                related_services=[service_label] if service_label else [],
                docs_retrieved_count=0,
                respond_duration=0.0,
                input_token=0,
                output_token=0,
                input_total=int(sm_local.get("summary_input") or 0),
                output_total=int(sm_local.get("summary_output") or 0),
                summarization_meta=sm_local,
                extra=slot_plan.get("extra") or {},
            )
            result = {"session_id": session_id, **payload}
            result = _finalize_result_language(result, language_code, language_name)
            _attach_request_total_duration(result, request_t0)
            log_run(session_id, question, result)
            _schedule_summary_refresh(session_id=session_id, token_id=token_id, language_name_hint=language_name)
            return result

        parsed = _parse_slot_choice_value(q_stripped)
        tz_label = ma_state.get("timezone_label") or "UTC+7"
        slot_summary_text = ""
        slot_start_dt = None
        slot_end_dt = None
        calendar_status = None
        if parsed:
            ma_state["selected_slot"] = parsed
            extra_ctx["meeting_arrangement"] = ma_state
            try:
                date_txt = datetime.fromisoformat(parsed["date_iso"]).strftime("%d %B %Y")
            except Exception:
                date_txt = parsed["date_iso"]
            slot_txt = f"{parsed['start']}-{parsed['end']}"
            slot_summary_text = f"{date_txt} | {slot_txt}"
            try:
                slot_start_dt, slot_end_dt = _slot_choice_datetimes(parsed, ma_state.get("timezone"))
            except Exception as slot_err:
                calendar_status = {"status": "error", "msg": f"slot_time_parse: {slot_err}"}
        else:
            date_txt = ma_state.get("first_date") or ""
            slot_txt = ""

        monday_status = _maybe_send_to_monday_final_gate(
            session_id=session_id,
            token_id=token_id,
            extra=extra_ctx,
            summarization_meta=sm,
            force=True,
        )
        if isinstance(monday_status, dict):
            extra_ctx["monday_status"] = monday_status
            ma_state["monday_meeting_sent"] = bool(monday_status.get("ok"))
            extra_ctx["meeting_arrangement"] = ma_state

        # if (language_code or "").lower().startswith("id"):
        #     ack_text = (
        #         f"Terima kasih, saya catat jadwal {date_txt} pukul {slot_txt} ({tz_label}). "
        #         "Saya akan menindaklanjuti untuk mengonfirmasi pertemuan ini."
        #     )
        # else:
        #     ack_text = (
        #         f"Thanks, I have noted {date_txt} at {slot_txt} ({tz_label}). "
        #         # "I will follow up shortly to confirm the meeting."
        #         "I have sent the meeting invitation to your email. Please confirm."
        #     )

        if slot_start_dt and slot_end_dt:
            try:
                calendar_payload = build_calendar_payload_draft(
                    session_id=session_id,
                    selected_sales_email=sales_email or None,
                    start_wib=slot_start_dt,
                    end_wib=slot_end_dt,
                    language_code=language_code or "en",
                    service_label=service_label,
                    slot_text=slot_summary_text,
                    timezone_label=tz_label,
                    time_zone=ma_state.get("timezone") or None,
                )
                save_calendar_payload(
                    session_id=session_id,
                    token_id=token_id,
                    payload=calendar_payload,
                    status="draft",
                )
                calendar_status = send_calendar_booking(session_id=session_id, token_id=token_id)
            except Exception as cal_err:
                calendar_status = {"status": "error", "msg": str(cal_err)}

        if calendar_status:
            extra_ctx["calendar_status"] = calendar_status
            ma_state["calendar_sent_ok"] = bool(str(calendar_status.get("status", "")).lower() == "success")
            extra_ctx["meeting_arrangement"] = ma_state

        calendar_ok = bool(
            str((calendar_status or {}).get("status", "")).lower() == "success"
        )

        monday_ok = bool((monday_status or {}).get("ok"))

        # booking_completed di-set True segera saat user memilih slot (parsed tidak None),
        # terlepas dari status calendar/monday — keduanya adalah side-effect async,
        # bukan penentu apakah user sudah booking atau belum.
        if parsed:
            ma_state["booking_completed"] = True
            ma_state["reset_ready"] = True
            ma_state["followup_stage"] = "post_booking"
            extra_ctx["meeting_arrangement"] = ma_state
        elif calendar_ok and monday_ok:
            # fallback: kalau parsed None tapi calendar & monday sukses
            ma_state["booking_completed"] = True
            ma_state["reset_ready"] = True
            ma_state["followup_stage"] = "post_booking"
            extra_ctx["meeting_arrangement"] = ma_state

        # --- language fallback khusus setelah user pilih slot ---
        # alasan:
        # q_stripped = PICKED_SLOT_* adalah value teknis, bukan bahasa natural
        # jadi jangan percaya language_code aktif saat ini
        ack_language_code = language_code
        ack_language_name = language_name

        try:
            hist_rows = read_language_history(session_id, token_id=token_id, limit=6) or []
        except Exception:
            hist_rows = []

        hist_code, hist_name = _pick_natural_lang(hist_rows)

        # fallback terakhir ke helper lama kalau belum ketemu
        if not hist_code and not hist_name:
            prev_code, prev_name = _fallback_language_from_history(session_id, token_id)
            hist_code = hist_code or prev_code
            hist_name = hist_name or prev_name

        if hist_code:
            ack_language_code = hist_code
        if hist_name:
            ack_language_name = hist_name

        if calendar_ok:
            ack_text = render_meeting_invite_confirmation(
                language_code=ack_language_code,
                date_txt=date_txt,
                slot_txt=slot_txt,
                tz_label=tz_label,
            )
        else:
            ack_text = render_meeting_invite_pending(
                language_code=ack_language_code,
                date_txt=date_txt,
                slot_txt=slot_txt,
                tz_label=tz_label,
            )

        # Crisp handles reset natively — string, not picker.
        msg_obj = build_string_message(ack_text)
        payload = build_chat_turn_payload(
            question=question,
            message=msg_obj,
            route="meeting_arrangement_slot_selected",
            language_name=ack_language_name,
            user_nick=resolved_nick or "",
            prompt_applied="",
            related_services=[service_label],
            docs_retrieved_count=0,
            respond_duration=0.0,
            input_token=0,
            output_token=0,
            input_total=int((sm or {}).get("summary_input") or 0),
            output_total=int((sm or {}).get("summary_output") or 0),
            summarization_meta=(sm or {}),
            extra=extra_ctx,
        )
        _cache_meeting_context_entry(
            session_id,
            service_label=service_label,
            sales_email=sales_email,
            sales_name=sales_name,
            extra=extra_ctx,
        )
        result = {"session_id": session_id, **payload}
        result = _finalize_result_language(result, language_code, language_name)
        _attach_request_total_duration(result, request_t0)
        log_run(session_id, question, result)
        _schedule_summary_refresh(session_id=session_id, token_id=token_id, language_name_hint=language_name)
        return result

    # === existing SA_SELECT handler ===
    if q_stripped.startswith(SA_POL.SERVICE_AGENT_PREFIX):  # "SA_SELECT_"
        from modules.service_agent.sa_service import SA_ENGINE  # lazy import, aman
        # SA_SELECT bukan bahasa natural → fallback ke bahasa percakapan sebelumnya
        prev_code, prev_name = _fallback_language_from_history(session_id, token_id)
        if prev_name:
            language_name = prev_name
        if prev_code:
            language_code = prev_code

        t0 = time.monotonic()

        # 1) Minta SA men-start flow & balikin seed step pertama + extra state (NO LLM)
        sa_state = SA_ENGINE.handle_from_question(
            session_id=session_id,
            question=q_stripped,
            token_id=token_id,
            handoff_bundle={"language_code": language_code, "language_name": language_name},
        )

        # 1) init aman
        extra = sa_state.get("extra") or {}
        # service_label = (sa_state.get("service_label") or extra.get("service_label") or "").strip()
        # service_code  = (sa_state.get("service_code")  or extra.get("service_code")  or "").strip()
        service_label = (sa_state.get("service_label") or (sa_state.get("extra") or {}).get("service_label") or "").strip()
        service_code  = (sa_state.get("service_code")  or (sa_state.get("extra") or {}).get("service_code")  or "").strip()

        # 2) persist service info ke extra
        if service_label and not extra.get("service_label"):
            extra["service_label"] = service_label
        if service_code and not extra.get("service_code"):
            extra["service_code"] = service_code

        # 3) fetch PIC
        try:
            if service_label and not (extra.get("sales_email") or extra.get("sales_name")):
                pic = fetch_sales_pic_by_service(service_label) or {}
                if pic.get("sales_email"):
                    extra["sales_email"] = pic["sales_email"]
                if pic.get("sales_name"):
                    extra["sales_name"] = pic["sales_name"]
        except Exception:
            pass

        # 4) write back
        sa_state["extra"] = extra



        # RAG query khusus SA_SELECT (jangan pakai value choice)
        rag_query = f"What is {service_label} and what are its key features and benefits?"

        # 2) RAG + context (seperti incontext)
        retriever = get_retriever()
        # candidates = retrieve_candidates(retriever, q_stripped)
        candidates = retrieve_candidates(retriever, rag_query)

        # Service-biased retrieval — SA_SELECT path always has a known service.
        _same_k = int(getattr(cfg, "CTX_DOCS_SAME_SERVICE", 4))
        _other_k = int(getattr(cfg, "CTX_DOCS_OTHER_SERVICE", 0))
        if (service_label or "").strip():
            candidates = retrieve_service_biased(rag_query, _service_aliases(service_label), same_k=_same_k, other_k=_other_k)
            _floor = _same_k + _other_k
        else:
            _floor = int(getattr(cfg, "CTX_DOCS_FLOOR", 4))

        _flag = (getattr(cfg, "FAQ_VERIFICATOR", "on") or "on").strip().lower()
        _verif_on = _flag in ("1", "true", "on", "yes")
        # filtered = grade_and_filter_yes(GRADER, candidates, q_stripped) if _verif_on else candidates
        filtered = grade_and_filter_yes(GRADER, candidates, rag_query, session_id=session_id, token_id=token_id) if _verif_on else candidates

        filtered = _pad_to_floor(filtered, candidates, _floor)

        ctx_str = render_context(filtered)
        related_services = extract_related_services(filtered, top_k=len(filtered))
        related_str = "\n".join(related_services) if related_services else "(none)"

        # 3) history/summary blocks (supaya prompt_applied auditable)
        history_block, summary_block, _summary_meta2 = _build_history_blocks(
            session_id,
            token_id,
            precomputed_summary_block=summary_block_cache,
            precomputed_summary_meta=summary_meta_cache,
        )

        flow_code_seed = (
            sa_state.get("service_code")
            or (sa_state.get("extra") or {}).get("service_code")
            or ""
        )

        seed_q = (
            sa_state.get("step_text")
            or sa_state.get("next_step_text")
            or _get_first_flow_question_text(flow_code_seed)
            or "-"
        )

        # 4) Render prompt SA (dari sa_prompts.py, sesuai request kamu)
        rendered_prompt = render_serviceagent_prompt_01(
            language_name=language_name,
            related_services=related_str,
            context=ctx_str,
            question=rag_query,
            is_first_turn=first_turn,
            user_nick=resolved_nick,
            language_code=language_code,
            max_chars=cfg.INPUT_MAX_PROMPT,
            chat_history_block=history_block,
            chat_summary_block=summary_block,
            next_q_enabled=True,
            next_q_seed=seed_q,   # seed step pertama dari SA flow
            service_validation_enabled=False,
            service_validation_seed="-",
        )

        # 5) Call LLM
        messages = [SystemMessage(content=rendered_prompt), HumanMessage(content=q_stripped)]
        with audit_llm_call(
            route="system_detection",
            stage="qualification_reply",
            session_id=session_id,
            token_id=token_id,
            prompt=messages,
        ) as ctx_qual:
            msg = BRIEF_LLM.invoke(messages)
            ctx_qual.set_response_from_message(msg)

        text = normalize_single_paragraph(getattr(msg, "content", str(msg)))
        in_tok  = ctx_qual.input_tokens
        out_tok = ctx_qual.output_tokens

        input_total  = in_tok  + int(sm.get("summary_input") or 0)
        output_total = out_tok + int(sm.get("summary_output") or 0)
        dur_s = ctx_qual.latency_ms / 1000.0

        # 6) name variation (opsional, konsisten dengan route lain)
        nick_plain, addr_formal = _address_forms_by_language(language_code, resolved_nick)
        seed_val = (hash(f"{session_id}:{q_stripped}") & 0xFFFFFFFF)
        text = enforce_name_variation(text, language_code, nick_plain, addr_formal,
                                    cadence=3, max_mentions_short=2, max_mentions_long=3, seed=seed_val)

        # 7) Build payload final SD
        msg_obj = build_string_message(text)
        extra_payload = dict(sa_state.get("extra") or {})
        # Inject meeting_arrangement booking dari session sebelumnya agar guard
        # bisa mendeteksi booking lintas service (misal WBS → FRI)
        if not (extra_payload.get("meeting_arrangement") or {}).get("booking_completed"):
            _sa_booked_rows = _read_all_chat_pairs(session_id=session_id, token_id=token_id, limit=500) or []
            for _sbr in reversed(_sa_booked_rows):
                _sbr_ex = _sbr.get("extra") or {}
                _sbr_ma = _sbr_ex.get("meeting_arrangement") or {}
                if bool(_sbr_ma.get("booking_completed")) and _sbr_ma.get("selected_slot"):
                    extra_payload["meeting_arrangement"] = dict(_sbr_ma)
                    break
        _cache_meeting_context_entry(
            session_id,
            service_label=(extra_payload.get("service_label") or "").strip(),
            sales_email=(extra_payload.get("sales_email") or "").strip(),
            sales_name=(extra_payload.get("sales_name") or "").strip(),
            extra=extra_payload,
        )
        payload = build_chat_turn_payload(
            question=q_stripped,
            message=msg_obj,
            route=sa_state.get("route") or "agent_service",
            language_name=language_name,
            user_nick=resolved_nick or "",
            prompt_applied=rendered_prompt,
            related_services=related_services,
            docs_retrieved_count=len(filtered),
            respond_duration=dur_s,
            input_token=in_tok,
            output_token=out_tok,
            input_total=input_total,
            output_total=output_total,
            summarization_meta=sm,
            extra=extra_payload,
        )
        result = {"session_id": session_id, **payload}
        result = _finalize_result_language(result, language_code, language_name)
        _attach_request_total_duration(result, request_t0)
        log_run(session_id, q_stripped, result)
        _schedule_summary_refresh(
            session_id=session_id,
            token_id=token_id,
            language_name_hint=language_name,
        )
        return result

    sa_active_now = prechecked_sa_active if prechecked_sa_active is not None else _sa_is_active(session_id)

    if sa_active_now and is_meeting_request(q_stripped, language_code):
        ctx = _load_meeting_context(session_id=session_id, token_id=token_id)
        extra_ctx = dict((ctx.get("extra") or {}))
        service_label_ctx = (ctx.get("service_label") or extra_ctx.get("service_label") or "").strip()
        sales_email_ctx = (ctx.get("sales_email") or extra_ctx.get("sales_email") or "").strip()
        sales_name_ctx = (ctx.get("sales_name") or extra_ctx.get("sales_name") or "").strip()

        if service_label_ctx and sales_email_ctx:
            meeting_plan = build_meeting_choices_now(
                session_id=session_id,
                website_id=website_id,
                token_id=token_id,
                service_label=service_label_ctx,
                sales_email=sales_email_ctx,
                sales_name=sales_name_ctx,
                language_name=language_name,
                language_code=language_code,
                user_nick=resolved_nick,
                is_first_turn=False,
                last_extra=extra_ctx,
                max_other_picks=MAX_OTHER_SLOT_PICKS,
            )

            if meeting_plan.get("route") == "meeting_arrangement_already_booked":
                rendered_prompt = meeting_plan.get("prompt") or ""
                extra_payload = meeting_plan.get("extra") or extra_ctx

                prompt_msgs_sa_path_1 = [SystemMessage(content=rendered_prompt), HumanMessage(content=q_stripped)]
                with audit_llm_call(
                    route="system_detection",
                    stage="sa_path_1",
                    session_id=session_id,
                    token_id=token_id,
                    prompt=prompt_msgs_sa_path_1,
                ) as ctx:
                    msg_sa = BRIEF_LLM.invoke(prompt_msgs_sa_path_1)
                    ctx.set_response_from_message(msg_sa)
                text = normalize_single_paragraph(getattr(msg_sa, "content", "") or "")
                in_tok = ctx.input_tokens
                out_tok = ctx.output_tokens
                dur_s = ctx.latency_ms / 1000.0

                # Crisp handles reset natively — string, not picker.
                _ab_lang_name = language_name
                try:
                    _hist_rows_ab = read_language_history(session_id, token_id=token_id, limit=6) or []
                    _ab_hist_code, _ab_hist_name = _pick_natural_lang(_hist_rows_ab)
                    if _ab_hist_name:
                        _ab_lang_name = _ab_hist_name
                except Exception:
                    pass

                msg_obj = build_string_message(text)

                payload = build_chat_turn_payload(
                    question=q_stripped,
                    message=msg_obj,
                    route="meeting_arrangement_already_picked_validation",
                    language_name=_ab_lang_name,
                    user_nick=resolved_nick or "",
                    prompt_applied=rendered_prompt,
                    related_services=[service_label_ctx] if service_label_ctx else [],
                    docs_retrieved_count=0,
                    respond_duration=dur_s,
                    input_token=in_tok,
                    output_token=out_tok,
                    input_total=in_tok + int(sm.get("summary_input") or 0),
                    output_total=out_tok + int(sm.get("summary_output") or 0),
                    summarization_meta=sm,
                    extra=extra_payload,
                )

                result = {"session_id": session_id, **payload}
                result = _finalize_result_language(result, language_code, language_name)
                _attach_request_total_duration(result, request_t0)
                log_run(session_id, q_stripped, result)
                _cache_meeting_context_entry(
                    session_id,
                    service_label=service_label_ctx,
                    sales_email=sales_email_ctx,
                    sales_name=sales_name_ctx,
                    extra=extra_payload,
                )
                return result

            if meeting_plan.get("route") == "meeting_arrangement_pick_slot":
                rendered_prompt = meeting_plan.get("prompt") or ""
                choices = meeting_plan.get("choices") or []
                extra_payload = meeting_plan.get("extra") or extra_ctx

                prompt_msgs_sa_path_2 = [SystemMessage(content=rendered_prompt), HumanMessage(content=q_stripped)]
                with audit_llm_call(
                    route="system_detection",
                    stage="sa_path_2",
                    session_id=session_id,
                    token_id=token_id,
                    prompt=prompt_msgs_sa_path_2,
                ) as ctx:
                    msg_sa = BRIEF_LLM.invoke(prompt_msgs_sa_path_2)
                    ctx.set_response_from_message(msg_sa)
                text = normalize_single_paragraph(getattr(msg_sa, "content", "") or "")
                in_tok = ctx.input_tokens
                out_tok = ctx.output_tokens
                dur_s = ctx.latency_ms / 1000.0

                msg_obj = build_picker_message(text=text, choices=choices, required=True)

                payload = build_chat_turn_payload(
                    question=q_stripped,
                    message=msg_obj,
                    route="meeting_arrangement_pick_slot",
                    language_name=language_name,
                    user_nick=resolved_nick or "",
                    prompt_applied=rendered_prompt,
                    related_services=[service_label_ctx],
                    docs_retrieved_count=0,
                    respond_duration=dur_s,
                    input_token=in_tok,
                    output_token=out_tok,
                    input_total=in_tok + int(sm.get("summary_input") or 0),
                    output_total=out_tok + int(sm.get("summary_output") or 0),
                    summarization_meta=sm,
                    extra=extra_payload,
                )

                result = {"session_id": session_id, **payload}
                result = _finalize_result_language(result, language_code, language_name)
                _attach_request_total_duration(result, request_t0)
                log_run(session_id, q_stripped, result)
                _cache_meeting_context_entry(
                    session_id,
                    service_label=service_label_ctx,
                    sales_email=sales_email_ctx,
                    sales_name=sales_name_ctx,
                    extra=extra_payload,
                )
                return result

    if sa_active_now and not q_stripped.startswith(SA_POL.SERVICE_AGENT_PREFIX):
        from modules.service_agent.sa_service import SA_ENGINE

        # Stage 3B v0+ (2026-05-08): user clicked SA_STAY_<source>_to_<target> picker
        # from a cross-service bridge turn. Just ack + re-ask current Q. Don't go
        # through SA_ENGINE.handle_from_question (which would treat "SA_STAY_..."
        # as user input and run classifier on it).
        _parsed_stay = _parse_sa_stay_value(q_stripped)
        if _parsed_stay is not None:
            _stay_state = SA_ENGINE.repo.get_state(session_id)
            if _stay_state is not None:
                stay_state_dict = {
                    "service_code": getattr(_stay_state, "service_code", "") or "",
                    "service_label": getattr(_stay_state, "service_label", "") or "",
                    "question_id": getattr(_stay_state, "question_id", "") or "",
                    "answers": getattr(_stay_state, "answers", {}) or {},
                    "status": getattr(_stay_state, "status", "") or "",
                    "extra": {},
                }
                # SA_STAY_* is technical input — Latin-only token tricks language
                # detection into "en". Resolve to majority history language so the
                # ack matches user's actual conversation language (Stage 2A pattern).
                _maj_c, _maj_n = _majority_language_from_history(session_id, token_id)
                stay_lang_code = _maj_c or language_code or "id"
                stay_lang_name = _maj_n or language_name or "Indonesia"
                stay_result = _render_sa_stay_continuation(
                    session_id=session_id,
                    token_id=token_id,
                    sa_state=stay_state_dict,
                    parsed_stay=_parsed_stay,
                    summary_meta_cache=summary_meta_cache,
                    request_started_at=request_t0,
                    turn_language_code=stay_lang_code,
                    turn_language_name=stay_lang_name,
                    resolved_nick=resolved_nick,
                )
                return _attach_request_total_duration(stay_result, request_t0)

        sa_state = SA_ENGINE.handle_from_question(
            session_id=session_id,
            question=q_stripped,
            token_id=token_id,
        )

        # Stage 3B v0 (2026-05-08): cross-service intent detection.
        # If user explicitly mentions a DIFFERENT service while in qualification,
        # divert to bridge handler that fans out retrieval (current + target),
        # answers using combined context, and offers a stay/switch picker.
        # Strict mode (Q3=A) — only fires on explicit service-name match.
        # Skip technical inputs (SA_STAY, SA_SELECT_, BOOK_A_MEETING, etc.).
        cs_target = None
        if not _is_technical_language_input(q_stripped) and q_stripped.upper() != "SA_STAY":
            cs_target = _detect_cross_service_target(
                user_question=q_stripped,
                current_service_code=sa_state.get("service_code") or "",
                current_service_label=sa_state.get("service_label") or "",
            )
        if cs_target is not None:
            bridge_result = _render_sa_cross_service_bridge(
                session_id=session_id,
                token_id=token_id,
                user_question=q_stripped,
                resolved_nick=resolved_nick,
                sa_state=sa_state,
                target=cs_target,
                summary_block_cache=summary_block_cache,
                summary_meta_cache=summary_meta_cache,
                request_started_at=request_t0,
                turn_language_code=language_code or "",
                turn_language_name=language_name or "",
            )
            return _attach_request_total_duration(bridge_result, request_t0)

        result = _render_sa_continue_via_sd(
            session_id=session_id,
            token_id=token_id,
            user_question=q_stripped,
            resolved_nick=resolved_nick,
            first_turn=first_turn,
            sm=sm,
            sa_state=sa_state,
            summary_block_cache=summary_block_cache,
            summary_meta_cache=summary_meta_cache,
            request_started_at=request_t0,
            # Pass per-turn fresh language detection (from build_language_meta
            # earlier in handle_chat) — drives reply language regardless of
            # state.language_code from previous SA turns.
            turn_language_code=language_code or "",
            turn_language_name=language_name or "",
        )

        # === STAGE 0 OOC Orchestrator at MID-FLOW (Task 21 wire-up — 2026-05-13) ===
        # Post-SA intercept: SA already produced its reply. If Stage 0 OOC fires,
        # composite REPLACES the SA reply (3-paragraph mid_flow_* shape per spec).
        # If non-OOC, state mutations applied + SA reply preserved.
        # If suppression-fallthrough (counter > 0), dispatcher closure returns the
        # SA reply text — counter decrements, audit written, no text change.
        #
        # Wasted-compute on OOC mid-flow turns: SA LLM call ran but its reply is
        # discarded. Accepted Phase 0 design cost per Decision 3 (spec Q#5).
        # Phase 1 optimization: pre-SA classifier to skip SA compute on OOC turns.
        # See docs/modules/out_of_context.md "Phase 1 optimization opportunities".
        _stage_0_replaced_sa_at_midflow = False
        if cfg.OOC_AGENT_ENABLED:
            from modules.system_detection.sd_orchestrator import (
                process_user_message_with_ooc as _stage_0_process_message,
            )
            from modules.service_agent.sa_types import AgentSessionState as _AgentSessionState

            # Load pydantic state from SA repo (Item 3 nuance — separate from `sa_state` dict).
            # None handling: fall back to fresh AgentSessionState with defaults.
            _stage_0_state = SA_ENGINE.repo.get_state(session_id) or _AgentSessionState(
                session_id=session_id,
                service_code="",
                question_id="",
            )
            # Capture already-produced SA reply text for suppression dispatcher closure
            try:
                _sa_reply_text_for_dispatcher = (
                    result.get("message", {}).get("content", {}).get("text") or ""
                )
            except Exception:
                _sa_reply_text_for_dispatcher = ""

            def _mid_flow_dispatcher(_text, _state):
                # Suppression-fallthrough: SA reply already exists, return it as-is.
                return ("sa_continuation", _sa_reply_text_for_dispatcher)

            _stage_0_response = _stage_0_process_message(
                text=q_stripped,
                state=_stage_0_state,
                dispatcher=_mid_flow_dispatcher,
                return_none_on_non_ooc_passthrough=True,
                downstream_sd_stage_hint="sa_compose",
            )

            # Unconditional save — orchestrator may have mutated state even when
            # returning None (streak reset, lang update, counter decrement).
            try:
                SA_ENGINE.repo.upsert_state(_stage_0_state)
            except Exception as e:
                import logging as _logging
                _logging.getLogger(__name__).error(
                    "stage_0_midflow_state_persist_failure",
                    extra={"session_id": session_id, "error": str(e)},
                )

            # Replace SA reply only when Stage 0 returned a composite distinct from SA reply.
            # When response == _sa_reply_text_for_dispatcher: suppression-fallthrough returned
            # the SA reply (counter decremented, audit written), no text change needed.
            # When response is None: non-OOC, SA reply preserved.
            if (
                _stage_0_response is not None
                and _stage_0_response != _sa_reply_text_for_dispatcher
            ):
                try:
                    result["message"]["content"]["text"] = _stage_0_response
                    _stage_0_replaced_sa_at_midflow = True
                except Exception:
                    pass

        # === Footer gating per Decision 5 + Task 21 user-corrected logic ===
        #   flag=on:  NEW _build_sa_quotation_footer runs (quotation preserved).
        #             OLD _build_sa_post_footer SKIPPED (Stage 0 owns OOC layer;
        #             prevents double-fire between Stage 0 composite + legacy footer).
        #   flag=off: NEW _build_sa_quotation_footer SKIPPED. OLD _build_sa_post_footer
        #             runs unchanged (byte-identical to pre-Task-21 legacy behavior).
        if cfg.OOC_AGENT_ENABLED:
            footer = _build_sa_quotation_footer(
                question=q_stripped,
                language_code=(sa_state.get("language_code") or language_code or "id"),
                sa_state=sa_state,
            )
        else:
            # Legacy path — byte-identical to pre-Task-21 behavior per Decision 4 rollback.
            footer = _build_sa_post_footer(
                question=q_stripped,
                language_code=(sa_state.get("language_code") or language_code or "id"),
                sa_state=sa_state,
            )
        if footer:
            try:
                txt = result["message"]["content"]["text"] or ""
                result["message"]["content"]["text"] = (txt.rstrip() + "\n\n" + footer).strip()
            except Exception:
                pass

        return _attach_request_total_duration(result, request_t0)

    # === STAGE 0 OOC Orchestrator (Task 20 wire-up — 2026-05-13) ===========
    # When cfg.OOC_AGENT_ENABLED is on: route through process_user_message_with_ooc.
    # When off: fall through to legacy :5701-5737 OOCService.maybe_handle() block
    # (byte-identical observable behavior to pre-Task-20 per Decision 4 rollback).
    #
    # Per spec Appendix D.6 Phase 0 limitations:
    #   - OOC state (streak counter, session_fallback_language, suppression counter)
    #     is FRESH PER MESSAGE in Phase 0 — no Mongo persistence wired yet. Each
    #     cold-start message starts with default state. Phase 1 adds persistence.
    #   - Suppression-fallthrough at cold-start (state.ooc_escalation_suppression_remaining
    #     > 0) writes phase0_legacy_fallback=true audit row and falls through to
    #     RAG without invoking either Stage 0 orchestrator or legacy maybe_handle.
    #     Only reachable once persistence lands; defensive code kept for forward-compat.
    _stage_0_attempted = False
    t0 = perf_counter()
    if cfg.OOC_AGENT_ENABLED:
        _stage_0_attempted = True
        from modules.system_detection.sd_orchestrator import (
            process_user_message_with_ooc as _stage_0_process_message,
        )
        from modules.service_agent.sa_types import AgentSessionState as _AgentSessionState
        from core.app_audit import record_audit_row as _record_audit_row

        # Build fresh AgentSessionState per message (Phase 0 limitation: no persistence yet).
        # Cold-start path → service_code="" + question_id="" + answers={} (no SA active).
        _stage_0_state = _AgentSessionState(
            session_id=session_id,
            service_code="",
            question_id="",
            language_code=language_code or "",
            language_name=language_name or "",
            session_fallback_language=language_code if language_code else "en",
        )

        if _stage_0_state.ooc_escalation_suppression_remaining > 0:
            # Phase 0 limitation fallback (Friction B option B.ii) — write telemetry + fall through.
            _record_audit_row(
                stage="ooc_suppression_fallthrough",
                session_id=session_id,
                extras={
                    "user_text": (question or "")[:200],
                    "suppression_remaining_pre": _stage_0_state.ooc_escalation_suppression_remaining,
                    "suppression_remaining_post": max(0, _stage_0_state.ooc_escalation_suppression_remaining - 1),
                    "downstream_route": "phase0_legacy_passthrough",
                    "downstream_sd_stage": None,
                    "posthoc_classifier_sampled": False,
                    "posthoc_classifier_would_have_classified": None,
                    "posthoc_classifier_confidence": None,
                    "posthoc_classifier_mode": None,
                    "phase0_legacy_fallback": True,
                },
            )
            # SKIP both Stage 0 orchestrator AND legacy maybe_handle; fall through to :5739+
        else:
            _stage_0_response = _stage_0_process_message(
                text=question,
                state=_stage_0_state,
                return_none_on_non_ooc_passthrough=True,
            )
            if _stage_0_response is not None:
                # OOC handled by Stage 0 — wrap in chat-turn payload and early-return.
                t1 = perf_counter()
                respond_duration = t1 - t0
                now_iso_wib = datetime.now(WIB).isoformat()
                _msg_obj = build_string_message(_stage_0_response)
                result = build_chat_turn_payload(
                    ts=now_iso_wib,
                    question=question,
                    message=_msg_obj,
                    prompt_applied="",
                    language_name=language_name,
                    user_nick=resolved_nick,
                    route="ooc_agent_stage_0",   # distinguish from legacy "ooc_agent" route
                    related_services=[],
                    docs_retrieved_count=0,
                    respond_duration=respond_duration,
                    input_token=0,
                    output_token=0,
                    input_total=int(sm.get("summary_input") or 0),
                    output_total=int(sm.get("summary_output") or 0),
                    summarization_meta=sm,
                )
                return _attach_request_total_duration(result, request_t0)
            # else: Stage 0 ran but classified non-OOC; state mutations applied
            # (but discarded in Phase 0 since no persistence). Fall through to :5739+
            # SKIPPING the legacy maybe_handle block below.

    # === LEGACY OOC Agent — only runs when OOC_AGENT_ENABLED=off ===========
    # When Stage 0 attempted, this block is skipped (Stage 0 owns OOC handling).
    # When OOC_AGENT_ENABLED=off, this block runs as before — byte-identical to
    # pre-Task-20 observable behavior per Decision 4 rollback contract.
    if not _stage_0_attempted:
        ooc = OOCService().maybe_handle(user_text=question, language_code=language_code)
        if ooc:
            t1 = perf_counter()
            duration = round(t1 - t0, 4)

            msg_obj = build_string_message(ooc.message)

            # totals = llm tokens + summary tokens (ooc keyword mode: 0)
            input_total  = 0 + int(sm.get("summary_input") or 0)
            output_total = 0 + int(sm.get("summary_output") or 0)

            now_iso_wib = datetime.now(WIB).isoformat()

            t1 = time.perf_counter()
            respond_duration = t1 - t0

            result = build_chat_turn_payload(   # dari payload_builder.py
                ts=now_iso_wib,
                question=question,
                message=msg_obj,                       # ChatMessage object / dict sesuai helper
                prompt_applied=ooc.prompt_applied or "",
                language_name=language_name,
                user_nick=resolved_nick,
                route="ooc_agent",
                related_services=[],
                docs_retrieved_count=0,
                respond_duration=respond_duration,
                input_token=0,
                output_token=0,
                input_total=0,
                output_total=0,
                summarization_meta=sm,
                # extra={},
            )

            return _attach_request_total_duration(result, request_t0)
    # === END OOC Agent =====================================================\

    # 0.9) Self Greeting guard
    # Feedback #4: on the first turn, ALWAYS route through RAG + service
    # validation picker — never short-circuit into the self-introduction reply.
    if not first_turn and is_self_introduction(question):
        history_block, summary_block, summary_meta = _build_history_blocks(
            session_id,
            token_id,
            precomputed_summary_block=summary_block_cache,
            precomputed_summary_meta=summary_meta_cache,
        )

        rendered_intro = render_intro_prompt(
            language_name=language_name,
            user_text=question,
            user_nick=resolved_nick,
            language_code=language_code,
            is_first_turn=first_turn,
            max_chars=cfg.PROMPT_MAX_CHARS,
            chat_history_block=history_block,
            chat_summary_block=summary_block,
        )

        messages = [
            SystemMessage(content=rendered_intro),
            HumanMessage(content=question)
        ]

        with audit_llm_call(
            route="system_detection",
            stage="ask_long",
            session_id=session_id,
            token_id=token_id,
            prompt=messages,
        ) as ctx_ask_long:
            msg = ASK_LLM.invoke(messages, config={"max_tokens": 1000})
            ctx_ask_long.set_response_from_message(msg)

        text = normalize_single_paragraph(getattr(msg, "content", str(msg)))
        in_tok  = ctx_ask_long.input_tokens
        out_tok = ctx_ask_long.output_tokens

        input_total  = in_tok + int(sm.get("summary_input") or 0)
        output_total = out_tok + int(sm.get("summary_output") or 0)
        dur_s = ctx_ask_long.latency_ms / 1000.0

        msg_obj = build_string_message(text)

        payload = build_chat_turn_payload(
            question=question,
            message=msg_obj,
            route="self_introduction",
            language_name=language_name,
            user_nick=resolved_nick,
            prompt_applied=rendered_intro,
            related_services=[],
            docs_retrieved_count=0,
            respond_duration=dur_s,
            input_token=in_tok,
            output_token=out_tok,
            input_total=input_total,
            output_total=output_total,
            summarization_meta=sm,
        )

        result = {"session_id": session_id, **payload}
        result = _finalize_result_language(result, language_code, language_name)
        _attach_request_total_duration(result, request_t0)
        log_run(session_id, question, result)
        _schedule_summary_refresh(
            session_id=session_id,
            token_id=token_id,
            language_name_hint=language_name,
        )
        return result

    # 1) Greeting guard — tetap ada (kalau bukan meeting)
    # Feedback #4: on the first turn, force the user through the service
    # validation picker even for pure greetings ("hai", "halo").
    if not first_turn and is_greeting(question):
        # history_block, summary_block = _build_history_blocks(session_id, token_id)
        history_block, summary_block, summary_meta = _build_history_blocks(
            session_id,
            token_id,
            precomputed_summary_block=summary_block_cache,
            precomputed_summary_meta=summary_meta_cache,
        )
        rendered_greet = render_greeting_prompt(
            language_name=language_name,
            user_text=question,
            user_nick=resolved_nick,
            language_code=language_code,
            max_chars= cfg.PROMPT_MAX_CHARS,
            is_first_turn=first_turn,
            chat_history_block=history_block,     # bisa None
            chat_summary_block=summary_block,     # bisa None
        )
        messages = [
            SystemMessage(content=rendered_greet),
            HumanMessage(content=question)   # atau content=question kalau kamu mau
        ]
        # msg = ASK_LLM.invoke(messages)
        # text = getattr(msg, "content", str(msg))
        with audit_llm_call(
            route="system_detection",
            stage="ask_long_v2",
            session_id=session_id,
            token_id=token_id,
            prompt=messages,
        ) as ctx_ask_long_v2:
            msg = ASK_LLM.invoke(messages, config={"max_tokens": 1000})
            ctx_ask_long_v2.set_response_from_message(msg)

        # text = getattr(msg, "content", str(msg))
        text = getattr(msg, "content", str(msg))
        text = normalize_single_paragraph(text)

        in_tok  = ctx_ask_long_v2.input_tokens
        out_tok = ctx_ask_long_v2.output_tokens

        # ---- ambil meta summary kalau ada (schema=allsum) ----
        summary_applied = None
        summary_input = 0
        summary_output = 0
        chat_summarization = "-"

        if summary_meta:
            summary_applied   = summary_meta.get("prompt")
            summary_input     = int(summary_meta.get("input_tokens") or 0)
            summary_output    = int(summary_meta.get("output_tokens") or 0)
            chat_summarization = summary_meta.get("summary_text") or "-"

        input_total  = in_tok  + int(sm.get("summary_input") or 0)
        output_total = out_tok + int(sm.get("summary_output") or 0)

        dur_s   = ctx_ask_long_v2.latency_ms / 1000.0

        msg_obj = build_string_message(text)

        payload = build_chat_turn_payload(
            question=question,
            message=msg_obj,
            route="greeting",
            language_name=language_name,
            user_nick=resolved_nick,
            prompt_applied=rendered_greet,
            related_services=[],
            docs_retrieved_count=0,
            respond_duration=dur_s,
            input_token=in_tok,
            output_token=out_tok,
            input_total=input_total,
            output_total=output_total,
            summarization_meta=sm,
        )

        result = {"session_id": session_id, **payload}
        result = _finalize_result_language(result, language_code, language_name)
        _attach_request_total_duration(result, request_t0)
        log_run(session_id, question, result)
        _schedule_summary_refresh(
            session_id=session_id,
            token_id=token_id,
            language_name_hint=language_name,
        )
        return result

    # 3) RAG pipeline
    if _parallel_prep_on():
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_rag = pool.submit(
                _prepare_rag_context, question,
                session_id=session_id, token_id=token_id, turn_language_code=language_code,
            )
            f_history = pool.submit(
                _build_history_blocks,
                session_id,
                token_id,
                precomputed_summary_block=summary_block_cache,
                precomputed_summary_meta=summary_meta_cache,
            )
            filtered, ctx_str, related_services = f_rag.result()
            history_block, summary_block, summary_meta = f_history.result()
    else:
        filtered, ctx_str, related_services = _prepare_rag_context(
            question,
            session_id=session_id, token_id=token_id, turn_language_code=language_code,
        )
        history_block, summary_block, summary_meta = _build_history_blocks(
            session_id,
            token_id,
            precomputed_summary_block=summary_block_cache,
            precomputed_summary_meta=summary_meta_cache,
        )

    # === Decide SA handoff based on related_services ===
    sa_decision = decide_sa_handoff(related_services or [])

    related_str = "\n".join(related_services) if related_services else "(none)"

    # 3) Routing → render prompt blok (in/out) + invoke
    is_in = len(filtered) > DOCS_THRESHOLD
    route_key = "incontext" if is_in else "outcontext"

    summary_applied = None
    summary_input = 0
    summary_output = 0
    chat_summarization = "-"
    if summary_meta:
        summary_applied = summary_meta.get("prompt")
        summary_input = int(summary_meta.get("input_tokens") or 0)
        summary_output = int(summary_meta.get("output_tokens") or 0)
        chat_summarization = summary_meta.get("summary_text") or "-"

    # 1) Default: Next Qualification mode
    next_q_kwargs = dict(
        next_q_enabled=True,
        next_q_seed="-",
        service_validation_enabled=False,
        service_validation_seed="-",
    )

    flow_code = None
    one = None

    direct_flow_code = None
    if related_services and len(related_services) == 1:
        one = (related_services[0] or "").strip()

        # A) kalau sudah flow code (EBS/WBS/MSG/...)
        if one in FLOW_REGISTRY:
            flow_code = one

        # B) kalau berupa service value code (mystery_shopping, whistleblowing_hotline, general_service, ...)
        if not flow_code and one in SA_POL.SERVICE_CODE_TO_FLOW_CODE:
            flow_code = SA_POL.SERVICE_CODE_TO_FLOW_CODE[one]  # mystery_shopping -> MSG

        # C) kalau berupa label ("Mystery Shopping", "General", ...)
        if not flow_code:
            mapped = SA_POL.VALUE_TO_FLOW_CODE.get(one)        # "Mystery Shopping" -> MSG
            if mapped:
                flow_code = mapped

        direct_flow_code = None
        # D) hanya ambil seed kalau valid
        if flow_code and flow_code in FLOW_REGISTRY:
            from modules.service_agent.sa_service import SA_ENGINE  # lazy import aman
            direct_flow_code = flow_code
            seed = SA_ENGINE.get_first_question_seed(direct_flow_code)
            next_q_kwargs["next_q_seed"] = (seed.get("seed") or "-")
        else:
            flow_code = None   # penting: jangan paksa seed untuk general/value-code yg bukan flow

    # 2) Tentukan unique related services
    unique_rs = []
    seen = set()
    for s in related_services or []:
        s = (s or "").strip()
        if s and s not in seen:
            seen.add(s)
            unique_rs.append(s)

    # 3) Decide whether to show a service-validation picker.
    #
    # Cases:
    #   (a) Multi-service RAG hit → picker of those RAG services + "Other Services"
    #       button to explore the rest of the catalog.
    #   (b) RAG hit only "General" (or nothing) → no specific service was detected,
    #       so show the FULL catalog paginated, starting at batch 1 (full-catalog
    #       page 1) since batch 0's "related services" would be useless here.
    #   (c) RAG hit exactly one specific service → direct SA handoff (handled
    #       above); no picker.
    _general_tokens = {"general", "general_service", "general service"}
    is_general_only_rs = (
        len(unique_rs) >= 1
        and all((s or "").strip().lower() in _general_tokens for s in unique_rs)
    )
    is_empty_rs = len(unique_rs) == 0

    service_batch_meta = None
    if len(unique_rs) > 1 or is_general_only_rs or is_empty_rs:
        if is_general_only_rs or is_empty_rs:
            # Start at batch 1 directly so the user sees the first 5 services
            # from the full catalog (General is excluded from the catalog) plus
            # an "Other Services (2)" button to paginate through the rest.
            service_batch_meta = _build_related_service_batch_choices(
                related_services=[],
                language_code=language_code,
                batch_index=1,
                batch_size=RELATED_SERVICE_BATCH_SIZE,
            )
        else:
            service_batch_meta = _build_related_service_batch_choices(
                related_services=unique_rs,
                language_code=language_code,
                batch_index=0,
                batch_size=RELATED_SERVICE_BATCH_SIZE,
            )

        next_q_kwargs["next_q_enabled"] = False
        next_q_kwargs["next_q_seed"] = "-"
        next_q_kwargs["service_validation_enabled"] = True
        next_q_kwargs["service_validation_seed"] = (
            "To help me guide you better, which service are you exploring today?"
        )

    # 4) Kalau unik 1 service & direct handoff → ambil seed SA pertanyaan pertama
    direct_code = None
    if sa_decision.mode == "direct" and sa_decision.flow_code:
        direct_code = sa_decision.flow_code
    elif direct_flow_code:
        direct_code = direct_flow_code

    if (not direct_code) and sa_decision.mode == "direct" and sa_decision.flow_code:
        seed = SA_ENGINE.get_first_question_seed(sa_decision.flow_code)
        next_q_kwargs["next_q_seed"] = (seed.get("seed") or "-")

    if direct_code:
        from modules.service_agent.sa_service import SA_ENGINE

        raw_code = direct_code
        one = (related_services[0] if related_services else None)

        service_value_code = _to_service_value_code(one) or (
            raw_code if raw_code in SA_POL.SERVICE_CODE_TO_FLOW_CODE else None
        )

        flow_code_sa = None
        if raw_code in FLOW_REGISTRY:
            flow_code_sa = raw_code
        elif raw_code in SA_POL.SERVICE_CODE_TO_FLOW_CODE:
            flow_code_sa = SA_POL.SERVICE_CODE_TO_FLOW_CODE[raw_code]
        else:
            mapped = SA_POL.VALUE_TO_FLOW_CODE.get(one)
            if mapped:
                flow_code_sa = mapped

        sa_start = SA_ENGINE.start_flow_for_sd(session_id=session_id, service_code=flow_code_sa)

        next_q = (
            (sa_start.get("extra") or {}).get("status_text")
            or sa_start.get("step_text")
            or sa_start.get("next_step_text")
        )

        if not (next_q or "").strip():
            next_q = _get_first_flow_question_text(flow_code_sa)

        next_q = (next_q or "-").strip()

        rendered_prompt = render_serviceagent_prompt_01(
            language_name=language_name,
            related_services=related_str,
            context=ctx_str,
            question=question,
            is_first_turn=first_turn,
            user_nick=resolved_nick,
            language_code=language_code,
            max_chars=cfg.INPUT_MAX_PROMPT,
            chat_history_block=history_block,
            chat_summary_block=summary_block,
            next_q_enabled=True,
            next_q_seed=next_q,
            service_validation_enabled=False,
            service_validation_seed="-",
        )

        prompt_msgs_sa_compose = [SystemMessage(content=rendered_prompt), HumanMessage(content=question)]
        with audit_llm_call(
            route="system_detection",
            stage="sa_compose",
            session_id=session_id,
            token_id=token_id,
            prompt=prompt_msgs_sa_compose,
        ) as ctx:
            msg_sa = BRIEF_LLM.invoke(prompt_msgs_sa_compose)
            ctx.set_response_from_message(msg_sa)
        text = normalize_single_paragraph(getattr(msg_sa, "content", "") or "")
        in_tok_sa = ctx.input_tokens
        out_tok_sa = ctx.output_tokens

        input_total_sa = in_tok_sa + int(sm.get("summary_input") or 0)
        output_total_sa = out_tok_sa + int(sm.get("summary_output") or 0)
        dur_sa = ctx.latency_ms / 1000.0

        nick_plain, addr_formal = _address_forms_by_language(language_code, resolved_nick)
        seed_val = (hash(f"{session_id}:{question}") & 0xFFFFFFFF)
        text = enforce_name_variation(
            text, language_code, nick_plain, addr_formal,
            cadence=3, max_mentions_short=2, max_mentions_long=3, seed=seed_val
        )

        msg_obj = build_string_message(text)
        route_base = (service_value_code or flow_code_sa or "service").lower()
        route_name = f"agent_service_{route_base}"
        extra = sa_start.get("extra") or {}
        extra.update({"service_value_code": service_value_code})

        service_label_direct = (
            sa_start.get("service_label")
            or extra.get("service_label")
            or _service_label_from_flow_code(flow_code_sa)
            or ""
        ).strip()

        service_code_direct = (
            sa_start.get("service_code")
            or extra.get("service_code")
            or flow_code_sa
            or ""
        ).strip()

        if service_label_direct and not extra.get("service_label"):
            extra["service_label"] = service_label_direct
        if service_code_direct and not extra.get("service_code"):
            extra["service_code"] = service_code_direct

        try:
            if service_label_direct and not (extra.get("sales_email") or extra.get("sales_name")):
                pic = fetch_sales_pic_by_service(service_label_direct) or {}
                if pic.get("sales_email"):
                    extra["sales_email"] = pic["sales_email"]
                if pic.get("sales_name"):
                    extra["sales_name"] = pic["sales_name"]
        except Exception:
            pass

        _cache_meeting_context_entry(
            session_id,
            service_label=(extra.get("service_label") or "").strip(),
            sales_email=(extra.get("sales_email") or "").strip(),
            sales_name=(extra.get("sales_name") or "").strip(),
            extra=extra,
        )

        payload = build_chat_turn_payload(
            question=question,
            message=msg_obj,
            route=route_name,
            language_name=language_name,
            user_nick=resolved_nick,
            prompt_applied=rendered_prompt,
            related_services=related_services,
            docs_retrieved_count=len(filtered),
            respond_duration=dur_sa,
            input_token=in_tok_sa,
            output_token=out_tok_sa,
            input_total=input_total_sa,
            output_total=output_total_sa,
            summarization_meta=sm,
            extra=extra,
        )
        result = {"session_id": session_id, **payload}
        result = _finalize_result_language(result, language_code, language_name)
        _attach_request_total_duration(result, request_t0)
        log_run(session_id, question, result)
        _schedule_summary_refresh(
            session_id=session_id,
            token_id=token_id,
            language_name_hint=language_name,
        )
        return result

    _method = (getattr(cfg, "REDUNDANCY_METHOD", "normal") or "normal").strip().lower()

    if is_in:
        rendered_prompt = render_incontext_prompt(
            language_name=language_name,
            related_services=related_str,
            context=ctx_str,
            question=question,
            user_nick=resolved_nick,
            language_code=language_code,
            max_chars= cfg.INPUT_MAX_PROMPT,
            is_first_turn=first_turn,
            chat_history_block=history_block,     # bisa None
            chat_summary_block=summary_block,     # bisa None
            MEETING_HANDOFF_NOTE_EN=MEETING_HANDOFF_NOTE_EN,
            **next_q_kwargs,
        )

    else:
        rendered_prompt = render_outcontext_prompt(
            language_name=language_name,
            related_services=related_str,
            context=ctx_str,
            question=question,
            user_nick=resolved_nick,
            language_code=language_code,
            max_chars= cfg.INPUT_MAX_PROMPT,
            is_first_turn=first_turn,
            chat_history_block=history_block,     # bisa None
            chat_summary_block=summary_block,     # bisa None
        )

    # Anti-Redundancy: wrap rendered prompt with dedup guidelines when method != normal.
    if _method != "normal":
        from modules.system_detection.sd_prompts import apply_dedup_guidelines
        rendered_prompt = apply_dedup_guidelines(rendered_prompt, language_name)

    messages = [
    SystemMessage(content=rendered_prompt),
    HumanMessage(content=question)  # atau content=question
    ]
    with audit_llm_call(
        route="system_detection",
        stage="misc_compose_1",
        session_id=session_id,
        token_id=token_id,
        prompt=messages,
        extras={"retrieval_method": _method},
    ) as ctx_misc_1:
        msg = BRIEF_LLM.invoke(messages)
        ctx_misc_1.set_response_from_message(msg)

    # text = getattr(msg, "content", str(msg))
    text = getattr(msg, "content", str(msg))
    text = normalize_single_paragraph(text)

    in_tok  = ctx_misc_1.input_tokens
    out_tok = ctx_misc_1.output_tokens

    # ---- ambil meta summary kalau ada (schema=allsum) ----
    summary_applied = None
    summary_input = 0
    summary_output = 0
    chat_summarization = "-"

    if summary_meta:
        summary_applied   = summary_meta.get("prompt")
        summary_input     = int(summary_meta.get("input_tokens") or 0)
        summary_output    = int(summary_meta.get("output_tokens") or 0)
        chat_summarization = summary_meta.get("summary_text") or "-"

    input_total  = in_tok  + summary_input
    output_total = out_tok + summary_output
    dur_s   = ctx_misc_1.latency_ms / 1000.0
    nick_plain, addr_formal = _address_forms_by_language(language_code, resolved_nick)
    seed_val = (hash(f"{session_id}:{question}") & 0xFFFFFFFF)
    text = enforce_name_variation(
        text, language_code, nick_plain, addr_formal,
        cadence=3, max_mentions_short=2, max_mentions_long=3, seed=seed_val
    )

    # ✉️ Post-processing khusus untuk permintaan quotation
    try:
        if is_quotation_request(question, language_code):
            footer = build_quotation_footer(language_code)
            if footer:
                base_marker = footer.split(".")[0]
                if base_marker not in text:
                    if not text.strip().endswith((".", "!", "?", "…")):
                        text = text.rstrip() + "."
                    text = text.rstrip() + " " + footer
    except Exception:
        # Jangan sampai error kecil di sensor quotation memutus seluruh flow
        pass

    # Post-processing khusus untuk permintaan meeting / appointment
    try:
        if is_meeting_request(question, language_code):
            meet_footer = build_meeting_footer(language_code)
            if meet_footer:
                base_marker = meet_footer.split(".")[0]
                if base_marker not in text:
                    if not text.strip().endswith((".", "!", "?", "…")):
                        text = text.rstrip() + "."
                    text = text.rstrip() + " " + meet_footer
    except Exception:
        # Sensor meeting juga tidak boleh menjatuhkan route utama
        pass

    # === MULTI-SERVICE: return picker untuk validasi service ===
    if service_batch_meta and (service_batch_meta.get("choices") or []):
        msg_obj = build_picker_message(
            text=text,
            choices=service_batch_meta.get("choices") or [],
            required=True
        )

        payload = build_chat_turn_payload(
            question=question,
            message=msg_obj,
            route=f"{route_key}_service_validation",
            language_name=language_name,
            user_nick=resolved_nick,
            prompt_applied=rendered_prompt,
            related_services=related_services,
            docs_retrieved_count=len(filtered),
            respond_duration=dur_s,
            input_token=in_tok,
            output_token=out_tok,
            input_total=input_total,
            output_total=output_total,
            summarization_meta=sm,
            extra={
                "related_service_batch_index": service_batch_meta.get("batch_index", 0),
                "related_service_total_batches": service_batch_meta.get("total_batches", 1),
                "retrieval_method": _method,
            },
        )

        result = {"session_id": session_id, **payload}
        result = _finalize_result_language(result, language_code, language_name)
        _attach_request_total_duration(result, request_t0)
        log_run(session_id, question, result)
        if _method != "normal" and not _is_explicit_recap(question, language_code):
            from modules.system_detection.sd_repo import update_recent_chunk_ids
            update_recent_chunk_ids(session_id, token_id, _extract_chunk_ids_from_docs(filtered))
        _schedule_summary_refresh(
            session_id=session_id,
            token_id=token_id,
            language_name_hint=language_name,
        )
        return result

    msg_obj = build_string_message(text)

    payload = build_chat_turn_payload(
        question=question,
        message=msg_obj,
        route=route_key,
        language_name=language_name,
        user_nick=resolved_nick,
        prompt_applied=rendered_prompt,
        related_services=related_services,
        docs_retrieved_count=len(filtered),
        respond_duration=dur_s,
        input_token=in_tok,
        output_token=out_tok,
        input_total=in_tok + int(sm.get("summary_input") or 0),
        output_total=out_tok + int(sm.get("summary_output") or 0),
        summarization_meta=sm,
        extra={"retrieval_method": _method},
    )

    result = {"session_id": session_id, **payload}
    result = _finalize_result_language(result, language_code, language_name)
    _attach_request_total_duration(result, request_t0)
    log_run(session_id, question, result)
    if _method != "normal" and not _is_explicit_recap(question, language_code):
        from modules.system_detection.sd_repo import update_recent_chunk_ids
        update_recent_chunk_ids(session_id, token_id, _extract_chunk_ids_from_docs(filtered))
    _schedule_summary_refresh(
        session_id=session_id,
        token_id=token_id,
        language_name_hint=language_name,
    )
    return result

# Chat With History

def handle_chat_history(session_id: str, token_id: str, utilizer: str, question: str) -> Dict[str, Any]:
    """
    Generic chat-with-history entry (tanpa RAG/meeting). Ini akan menyusun pesan dengan
    summary + Chat history: (Q/A pairs) + pertanyaan sekarang + task-instruksi default.
    """
    window = cwh.get_history_window(session_id)
    build = cwhp.build_messages_for_sd(
        window, question,
        task_instr="Detect intent, answer briefly, or ask one clarifying question if needed.",
        include_history_block=True
    )
    # panggil LLM; gunakan BRIEF_LLM agar output singkat
    prompt_msgs_misc_2 = [
        SystemMessage(content=m["content"]) if m["role"] == "system"
        else HumanMessage(content=m["content"])
        for m in build["messages"]
    ]
    with audit_llm_call(
        route="system_detection",
        stage="misc_compose_2",
        session_id=session_id,
        token_id=token_id,
        prompt=prompt_msgs_misc_2,
    ) as ctx:
        msg = BRIEF_LLM.invoke(prompt_msgs_misc_2)
        ctx.set_response_from_message(msg)
    answer = getattr(msg, "content", "") or ""
