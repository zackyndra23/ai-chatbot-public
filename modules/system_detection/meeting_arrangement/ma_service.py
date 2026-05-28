from __future__ import annotations
import json, os, re, hashlib, random
import time
from typing import List, Dict, Any, Tuple
from datetime import datetime, timedelta, date, time as dt_time, timezone as dt_timezone
import math
from zoneinfo import ZoneInfo
import requests
from infra.app_repo import get_mongo_client
from bson import ObjectId

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_anthropic import ChatAnthropic
# gunakan sd_repo untuk baca data session & chat
from modules.system_detection.sd_repo import (
    read_user_profile_from_sessions,   # -> dict user {nickname,email,phone,country,region,city,...}
    read_chat_history,                 # -> list of {question,message,related_services,ts}
)
from .ma_repo import (
    list_distinct_sales_emails, get_sales_slots_for_date, _parse_label_to_wib, log_meeting_debug, summarize_weekly_availability,
    free_labels_for_date, upsert_ma_confirmation, get_sales_available_from_sheet, pick_least_available_weekly_from_sheet,
    get_count_from_summary, pick_most_available_weekly_from_sheet, get_weekly_availability_counts, fetch_sales_pic_by_service,
    fetch_sales_availability, fetch_user_profile,
)
from core.app_audit import audit_llm_call
from .ma_utils import (
    parse_date, parse_time_range, to_wib, violates_business_rules, WIB, windows_from_intervals, 
    human_date, human_time_range, business_hours_text, suggest_within_business,
)
from .ma_prompts import (
    render_meeting_start_prompt, render_desc_summary_prompt, MEETING_SLOT_PARSE_SYSTEM, render_meeting_slot_parse_human,
    render_alt_text_prompt, render_date_headers_prompt, render_available_text_prompt, render_meeting_start_note_prompt,
    render_meeting_title_prompt, render_service_picker_prompt,
)
from .ma_policies import parse_meeting_command, detect_meeting_intent
from modules.system_detection.sd_prompts import _address_forms_by_language
from modules.system_detection.sd_repo import read_user_country_from_sessions, log_run, read_user_nick_from_sessions, ensure_user_nick_in_sessions

from modules.chat_with_history import cwh_history as cwh
from modules.chat_with_history import cwh_prompt as cwhp

# CWH: ambil pasangan Q/A & bangun prompt ringkasan
from modules.chat_with_history.cwh_history import get_history_pairs, build_chat_summarization_block
from modules.chat_with_history.cwh_prompt import build_history_summarize_prompt, format_chat_history_block
from .ma_repo import save_calendar_payload
from modules.service_agent import sa_policies as SA_POL
from modules.chat_payload.payload_builder import build_picker_message  # kalau ada helper
from modules.chat_payload.payload_builder import build_string_message  # optional
from core.app_config import Config
cfg = Config()

MORNING_WINDOW = (8 * 60 + 30, 12 * 60)
AFTERNOON_WINDOW = (13 * 60, 18 * 60 + 30)
_SLOT_RANGE_RE = re.compile(r"\s*(\d{1,2}):(\d{2})\s*[-\u2013\u2014]\s*(\d{1,2}):(\d{2})\s*")
_WORKING_WEEKDAYS = {0, 1, 2, 3, 4}
_DEFAULT_HOST_ZONE = ZoneInfo("Asia/Jakarta")

# ===== Helpers =====

MA_PREFIX = "MA_ARRANGEMENT_"
SERVICE_PICKER_BATCH_SIZE = 5

def _slug_service_label(label: str) -> str:
    s = (label or "").strip().lower()
    s = re.sub(r"\s+", "_", s)
    # keep underscore + hyphen, remove other punctuations
    s = re.sub(r"[^a-z0-9_-]+", "", s)
    return s

# fallback map kalau sa_policies yang terbaca ternyata singkatan
_ABBR_TO_LABEL = {
    "EBS": "Background Check",
    "WBS": "Whistleblowing Hotline",
    "DD": "Due Diligence",
    "GENERAL": "General Service",
    "GENERAL SERVICE": "General Service",
    "ANTI-COUNTERFEITING": "Anti-Counterfeiting Investigation",
    "PARALLEL TRADING": "Parallel Trading Investigation",
}


def _slot_bounds(slot_label: str) -> tuple[int, int, int, int] | None:
    label = (slot_label or "").replace("\u2013", "-").replace("\u2014", "-")
    m = _SLOT_RANGE_RE.match(label)
    if not m:
        return None
    sh, sm, eh, em = map(int, m.groups())
    return sh, sm, eh, em


def _slot_start_minutes(slot_label: str) -> int | None:
    bounds = _slot_bounds(slot_label)
    if not bounds:
        return None
    sh, sm, *_ = bounds
    return sh * 60 + sm


def _slot_label_for_picker(
    day_iso: str,
    slot_label: str,
    tz_label: str,
) -> tuple[str, str]:
    bounds = _slot_bounds(slot_label)
    if not bounds:
        raise ValueError(f"invalid slot label: {slot_label}")
    sh, sm, eh, em = bounds
    day_dt = datetime.fromisoformat(day_iso)
    date_text = day_dt.strftime("%d %B %Y")
    time_text = f"{sh:02d}:{sm:02d}\u2013{eh:02d}:{em:02d}"
    value = f"PICKED_SLOT_{day_dt.strftime('%d%m%Y')}_{sh:02d}h{sm:02d}-{eh:02d}h{em:02d}_{tz_label.replace('UTC', 'utc').replace(':', '').replace('+', '').replace(' ', '').lower()}"
    label = f"{date_text} | {time_text} ({tz_label})"
    return value, label


def _tz_label(tz_name: str) -> tuple[str, ZoneInfo]:
    try:
        zone = ZoneInfo(tz_name)
    except Exception:
        zone = ZoneInfo("Asia/Jakarta")
    now = datetime.now(zone)
    offset = now.utcoffset() or timedelta()
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    minutes = abs(minutes)
    hours = minutes // 60
    mins = minutes % 60
    if mins:
        label = f"UTC{sign}{hours}:{mins:02d}"
    else:
        label = f"UTC{sign}{hours}"
    return label.replace("+-", "-").replace("--", "-"), zone

def _safe_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _extract_existing_booking(last_extra: dict | None) -> dict:
    """
    Ambil info booking meeting sebelumnya dari extra.meeting_arrangement.
    Return {} kalau belum ada booking valid.
    """
    extra = dict(last_extra or {})
    ma_state = dict((extra.get("meeting_arrangement") or {}))

    booking_completed = bool(ma_state.get("booking_completed"))
    followup_stage = (ma_state.get("followup_stage") or "").strip().lower()
    selected_slot = dict((ma_state.get("selected_slot") or {}))

    if not booking_completed:
        return {}

    if not selected_slot:
        return {}

    date_iso = (selected_slot.get("date_iso") or "").strip()
    start = (selected_slot.get("start") or "").strip()
    end = (selected_slot.get("end") or "").strip()
    slot_label = (selected_slot.get("slot_label") or "").strip()

    if not date_iso or not start or not end:
        return {}

    return {
        "booking_completed": True,
        "followup_stage": followup_stage,
        "date_iso": date_iso,
        "start": start,
        "end": end,
        "slot_label": slot_label or f"{start} - {end}",
    }


def _read_existing_booking_from_history(session_id: str, token_id: str | None) -> dict:
    rows = read_chat_history(session_id=session_id, token_id=token_id, limit=200) or []
    if not rows and token_id:
        rows = read_chat_history(session_id=session_id, token_id=None, limit=200) or []

    for row in reversed(rows):
        extra = row.get("extra") or {}
        booked = _extract_existing_booking(extra)
        if booked:
            return {
                "extra": extra,
                "booked": booked,
            }
    return {}

def _format_existing_booking_texts(
    *,
    date_iso: str,
    start: str,
    end: str,
    tz_label: str,
    timezone_name: str,
) -> tuple[str, str]:
    """
    Return (date_txt, slot_txt) untuk dipakai prompt warning.
    """
    try:
        day_dt = datetime.fromisoformat(date_iso)
        date_txt = day_dt.strftime("%d %B %Y")
    except Exception:
        date_txt = date_iso

    slot_txt = f"{start}-{end}"
    return date_txt, slot_txt


def _build_existing_meeting_warning(
    *,
    session_id: str,
    website_id: str,
    language_name: str,
    language_code: str | None,
    user_nick: str | None,
    service_label: str,
    sales_email: str,
    sales_name: str,
    last_extra: dict | None,
) -> dict | None:
    """
    Kalau session ini sudah pernah booking meeting, return payload planning untuk warning.
    """
    extra_base = dict(last_extra or {})
    ma_state = dict((extra_base.get("meeting_arrangement") or {}))
    booked = _extract_existing_booking(extra_base)

    if not booked:
        # Coba dengan website_id (token_id) dulu, baru fallback ke session-only
        hist = _read_existing_booking_from_history(session_id=session_id, token_id=website_id or None)
        if not hist:
            hist = _read_existing_booking_from_history(session_id=session_id, token_id=None)
        if hist:
            extra_base = dict(hist.get("extra") or extra_base)
            ma_state = dict((extra_base.get("meeting_arrangement") or {}))
            booked = dict(hist.get("booked") or {})

    if not booked:
        return None

    user = fetch_user_profile(session_id=session_id, website_id=website_id) or {}
    tz = (ma_state.get("timezone") or user.get("timezone") or "Asia/Jakarta").strip() or "Asia/Jakarta"
    tz_label, zone = _tz_label(tz)

    try:
        now_local = datetime.now(zone)
    except Exception:
        zone = ZoneInfo("Asia/Jakarta")
        now_local = datetime.now(zone)

    booked_date_txt, booked_slot_txt = _format_existing_booking_texts(
        date_iso=booked["date_iso"],
        start=booked["start"],
        end=booked["end"],
        tz_label=tz_label,
        timezone_name=tz,
    )

    final_nick = (user.get("nickname") or user_nick or "").strip() or None

    from .ma_prompts import render_existing_meeting_warning_prompt

    prompt = render_existing_meeting_warning_prompt(
        language_name=language_name,
        language_code=language_code,
        is_first_turn=False,
        user_nick=final_nick,
        user_email=(user.get("email") or "").strip() or None,
        service_label=service_label,
        booked_date_txt=booked_date_txt,
        booked_slot_txt=booked_slot_txt,
        tz_label=tz_label,
        current_hour_24=now_local.hour,
        max_chars=getattr(cfg, "INPUT_MAX_PROMPT", 1200),
        chat_history_block=None,
        chat_summary_block=None,
    )

    ma_state.update({
        "detected": True,
        "booking_completed": True,
        "followup_stage": "already_booked_warning",
        "timezone": tz,
        "timezone_label": tz_label,
        "selected_slot": {
            "date_iso": booked["date_iso"],
            "start": booked["start"],
            "end": booked["end"],
            "slot_label": booked["slot_label"],
        },
    })

    extra_base["meeting_arrangement"] = ma_state
    extra_base["service_label"] = service_label
    extra_base["sales_email"] = sales_email
    extra_base["sales_name"] = sales_name
    extra_base["user"] = user

    return {
        "route": "meeting_arrangement_already_booked",
        "language_name": language_name,
        "prompt": prompt,
        "booked_date_txt": booked_date_txt,
        "booked_slot_txt": booked_slot_txt,
        "tz_label": tz_label,
        "extra": extra_base,
    }


def _parse_host_timezone(spec: str):
    host = (spec or "").strip()
    if not host:
        return _DEFAULT_HOST_ZONE
    try:
        return ZoneInfo(host)
    except Exception:
        upper = host.upper().replace(" ", "")
        m = re.match(r"UTC([+-]?)(\d{1,2})(?::?(\d{2}))?$", upper)
        if m:
            sign = -1 if m.group(1) == "-" else 1
            hours = int(m.group(2))
            minutes = int(m.group(3) or 0)
            delta = timedelta(hours=hours, minutes=minutes)
            if sign < 0:
                delta = -delta
            return dt_timezone(delta)
    return _DEFAULT_HOST_ZONE


def _parse_time_border(val: str) -> dt_time:
    txt = (val or "").strip()
    if not txt:
        return dt_time(15, 0)
    try:
        parts = txt.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        second = int(parts[2]) if len(parts) > 2 else 0
        hour = max(0, min(23, hour))
        minute = max(0, min(59, minute))
        second = max(0, min(59, second))
        return dt_time(hour, minute, second)
    except Exception:
        return dt_time(15, 0)


def _picker_seed(*values: str) -> int:
    joined = "|".join(values)
    digest = hashlib.sha256(joined.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


def _pick_slot_for_window(
    slots: list[str],
    day_iso: str,
    window: tuple[int, int],
    used: set[tuple[str, str]],
    rnd: random.Random,
) -> str | None:
    if not slots:
        return None
    start_min, end_min = window
    def _eligible(candidate: str) -> bool:
        mins = _slot_start_minutes(candidate)
        if mins is None:
            return False
        return start_min <= mins < end_min
    primary = [s for s in slots if _eligible(s) and (day_iso, s) not in used]
    pool = primary or [s for s in slots if (day_iso, s) not in used]
    if not pool:
        return None
    return rnd.choice(pool)


def _select_priority_slots(
    slot_map: dict[str, list[str]],
    first_date: str,
    second_date: str,
    rnd: random.Random,
) -> list[tuple[str, str]]:
    picks: list[tuple[str, str]] = []
    used: set[tuple[str, str]] = set()
    plan = [
        (first_date, MORNING_WINDOW),
        (first_date, AFTERNOON_WINDOW),
        (second_date, MORNING_WINDOW),
        (second_date, AFTERNOON_WINDOW),
    ]
    for day_iso, window in plan:
        slot = _pick_slot_for_window(slot_map.get(day_iso, []), day_iso, window, used, rnd)
        if slot:
            used.add((day_iso, slot))
            picks.append((day_iso, slot))
    return picks

def _resolve_service_codes(service_label: str) -> tuple[str | None, str | None]:
    """Return (service_value_code, service_code/flow) for a picker label."""
    clean = (service_label or "").strip()
    if not clean:
        return None, None

    clean_cf = clean.casefold()
    value_code: str | None = None

    for val_code, label in SA_POL.SERVICE_LABEL_CODE_MAP.items():
        if (label or "").strip().casefold() == clean_cf:
            value_code = val_code
            break

    if not value_code:
        for label, val_code in SA_POL.SERVICE_VALUE_CODE_MAP.items():
            if (label or "").strip().casefold() == clean_cf:
                value_code = val_code
                break

    flow_code = SA_POL.SERVICE_CODE_TO_FLOW_CODE.get(value_code) if value_code else None
    return value_code, flow_code


def _other_slot_label(language_code: str | None) -> str:
    from modules.system_detection.sd_meeting import build_other_slot_label
    return build_other_slot_label(language_code)


def _next_workday(start_date: date, min_delta_days: int = 0) -> date:
    target = start_date + timedelta(days=max(0, min_delta_days))
    while target.weekday() not in _WORKING_WEEKDAYS:
        target += timedelta(days=1)
    return target


def _next_n_workdays(start_date: date, min_delta_days: int, count: int) -> list[date]:
    result: list[date] = []
    cur_base = _next_workday(start_date, min_delta_days)
    while len(result) < count:
        result.append(cur_base)
        cur_base = _next_workday(cur_base, 1)
    return result

def _nth_workday_after(base_date: date, workday_offset: int) -> date:
    """
    Return the date that is `workday_offset` business days after `base_date`.
    Offset counts only Mon-Fri and starts at 1 => next workday.
    """
    offset = max(0, workday_offset)
    current = base_date
    advanced = 0
    while advanced < offset:
        current += timedelta(days=1)
        if current.weekday() in _WORKING_WEEKDAYS:
            advanced += 1
    return current

def _resolve_service_codes(service_label: str) -> tuple[str | None, str | None]:
    """
    Translate picker labels into (service_value_code, service_code/flow code).
    """
    clean = (service_label or "").strip().lower()
    if not clean:
        return None, None

    value_code: str | None = None
    for code, label in SA_POL.SERVICE_LABEL_CODE_MAP.items():
        if (label or "").strip().lower() == clean:
            value_code = code
            break

    flow_code = SA_POL.SERVICE_CODE_TO_FLOW_CODE.get(value_code) if value_code else None
    return value_code, flow_code

def _get_service_labels_from_sa_policies() -> list[str]:
    """
    Cari daftar label service FULL NAME dari sa_policies.py.
    - Prioritas: list/tuple label full.
    - Kalau yang ketemu dict mapping dan key-nya singkatan, kita expand pakai _ABBR_TO_LABEL.
    """
    # 1) coba beberapa nama variabel yang umum ada
    for attr in [
        "SERVICE_LABELS",
        "SERVICE_LABELS_ORDERED",
        "SERVICE_LABEL_LIST",
        "SERVICE_CATALOG_LABELS",
        "SERVICE_CHOICES_LABELS",
    ]:
        v = getattr(SA_POL, attr, None)
        if isinstance(v, (list, tuple)) and v:
            return [str(x).strip() for x in v if str(x).strip()]

    # 2) coba ambil dari policy object (kalau sa_policies punya SA_POL/POL)
    pol_obj = (
        getattr(SA_POL, "SA_POL", None)
        or getattr(SA_POL, "POL", None)
        or getattr(SA_POL, "SA_POLICY", None)
        or None
    )
    if pol_obj is not None:
        for attr in [
            "SERVICE_LABELS",
            "SERVICE_LABELS_ORDERED",
            "SERVICE_LABEL_LIST",
            "SERVICE_CATALOG_LABELS",
            "SERVICE_CHOICES_LABELS",
        ]:
            v = getattr(pol_obj, attr, None)
            if isinstance(v, (list, tuple)) and v:
                return [str(x).strip() for x in v if str(x).strip()]

    # 3) fallback: ambil keys dari VALUE_TO_FLOW_CODE, tapi normalize singkatan
    value_to_flow = (
        getattr(SA_POL, "VALUE_TO_FLOW_CODE", None)
        or (getattr(pol_obj, "VALUE_TO_FLOW_CODE", None) if pol_obj else None)
        or {}
    )
    if isinstance(value_to_flow, dict) and value_to_flow:
        labels = []
        for k in value_to_flow.keys():
            key = str(k).strip()
            up = key.upper()
            labels.append(_ABBR_TO_LABEL.get(up, key))  # expand kalau singkatan
        # buang duplikat, pertahankan urutan
        seen = set()
        out = []
        for x in labels:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    return []

def build_ma_service_choices() -> list[dict]:
    labels = _get_service_labels_from_sa_policies()
    if not labels:
        raise RuntimeError("No service labels found from sa_policies.")

    # 1) normalisasi + buang general di level label
    cleaned = []
    for lab in labels:
        lab_norm = (lab or "").strip()
        if not lab_norm:
            continue
        if lab_norm.casefold() == "general service":
            continue
        cleaned.append(lab_norm)

    # 2) build choices
    choices = [
        {"value": f"{MA_PREFIX}{_slug_service_label(lab)}", "label": lab, "selected": False}
        for lab in cleaned
    ]

    # 3) safety net: buang general di level value juga (kalau ada jalur lain nyelip)
    choices = [
        c for c in choices
        if c.get("value") not in {"MA_ARRANGEMENT_general", "MA_ARRANGEMENT_general_service"}
    ]

    return choices

def build_ma_service_batch_choices(batch_index: int = 0,
                                   batch_size: int = SERVICE_PICKER_BATCH_SIZE) -> dict:
    """
    Split service choices into batches for UI limitations.
    """
    batch_size = max(1, int(batch_size or 1))
    all_choices = build_ma_service_choices()
    total = len(all_choices)
    if total == 0:
        return {"choices": [], "batch_index": 0, "total_batches": 0}

    total_batches = max(1, math.ceil(total / batch_size))
    idx = min(max(0, batch_index), total_batches - 1)
    start = idx * batch_size
    end = min(total, start + batch_size)
    chunk = [dict(all_choices[i]) for i in range(start, end)]

    if idx < total_batches - 1:
        chunk.append({
            "value": f"{MA_PREFIX}other_batch{idx + 2}",
            "label": f"Other Services ({idx + 2})",
            "selected": False,
        })

    return {
        "choices": chunk,
        "batch_index": idx,
        "total_batches": total_batches,
    }

def plan_meeting_service_picker(
    *,
    language_name: str,
    language_code: str,
    is_first_turn: bool,
    user_nick: str | None,
    user_email: str | None,
    service_label: str | None,
    chat_history_block: str | None,
    chat_summary_block: str | None,
    max_prompt_chars: int,
    service_batch_index: int = 0,
) -> dict:
    prompt = render_service_picker_prompt(
        language_name=language_name,
        language_code=language_code,
        is_first_turn=is_first_turn,
        user_nick=user_nick,
        user_email=user_email,
        service_label=service_label,
        max_chars=max_prompt_chars,
        chat_history_block=chat_history_block,
        chat_summary_block=chat_summary_block,
    )
    batch_meta = build_ma_service_batch_choices(batch_index=service_batch_index)
    return {
        "prompt": prompt,
        "choices": batch_meta.get("choices") or [],
        "batch_index": batch_meta.get("batch_index", service_batch_index),
        "total_batches": batch_meta.get("total_batches", 1),
    }

def build_meeting_choices_now(
    *,
    session_id: str,
    website_id: str,
    token_id: str | None,
    service_label: str,
    sales_email: str,
    sales_name: str,
    language_name: str,
    language_code: str | None,
    user_nick: str | None,
    is_first_turn: bool,
    last_extra: dict | None = None,
    max_other_picks: int = 5,
    slot_window_index: int | None = None,
    include_other: bool = True,
) -> dict:
    """
    Direct meeting arrangement: fetch user timezone, fetch availability, plan picker prompt & choices.
    slot_window_index controls which pair of future workdays to use (0 => +1/+2 or +2/+3 workdays ahead depending on chat time).
    """

    # --- EARLY EXIT: session ini sudah pernah booking meeting ---
    existing_warning = _build_existing_meeting_warning(
        session_id=session_id,
        website_id=website_id,
        language_name=language_name,
        language_code=language_code,
        user_nick=user_nick,
        service_label=service_label,
        sales_email=sales_email,
        sales_name=sales_name,
        last_extra=last_extra,
    )
    if existing_warning:
        return existing_warning

    user = fetch_user_profile(session_id=session_id, website_id=website_id) or {}
    tz = (user.get("timezone") or "").strip() or "Asia/Jakarta"
    tz_label, zone = _tz_label(tz)
    try:
        now_local = datetime.now(zone)
    except Exception:
        zone = ZoneInfo("Asia/Jakarta")
        tz = "Asia/Jakarta"
        tz_label, _ = _tz_label(tz)
        now_local = datetime.now(zone)

    extra_base = dict(last_extra or {})
    ma_state = dict((extra_base.get("meeting_arrangement") or {}))

    host_zone = _parse_host_timezone(getattr(cfg, "HOST_TIME_FORMAT", "UTC+7"))
    try:
        now_host = now_local.astimezone(host_zone)
    except Exception:
        try:
            now_host = datetime.now(host_zone)
        except Exception:
            now_host = now_local

    border_time = _parse_time_border(getattr(cfg, "TIME_CHAT_BORDER", "15:00"))
    host_time_naive = now_host.timetz().replace(tzinfo=None)
    before_border = host_time_naive < border_time if border_time else False

    anchor_iso = (ma_state.get("window_anchor_date") or "").strip()
    if anchor_iso:
        try:
            anchor_date = datetime.fromisoformat(anchor_iso).date()
        except Exception:
            anchor_date = now_host.date()
            ma_state["window_anchor_date"] = anchor_date.isoformat()
    else:
        anchor_date = now_host.date()
        ma_state["window_anchor_date"] = anchor_date.isoformat()

    if slot_window_index is None:
        try:
            window_index = int(ma_state.get("slot_window_index") or 0)
        except Exception:
            window_index = 0
    else:
        try:
            window_index = max(0, int(slot_window_index))
        except Exception:
            window_index = 0

    try:
        base_offset = int(ma_state.get("slot_window_base_offset") or 0)
    except Exception:
        base_offset = 0
    if base_offset <= 0:
        base_offset = 1 if before_border else 2
        ma_state["slot_window_base_offset"] = base_offset

    first_offset = base_offset + window_index * 2
    second_offset = first_offset + 1
    first_date_dt = _nth_workday_after(anchor_date, first_offset)
    second_date_dt = _nth_workday_after(anchor_date, second_offset)
    first_date = first_date_dt.isoformat()
    second_date = second_date_dt.isoformat()
    target_days = {first_date, second_date}

    avail = fetch_sales_availability(
        first_date=first_date,
        second_date=second_date,
        email=sales_email,
        timezone=tz,
    ) or {}
    available_slots = avail.get("available_slots") or []

    slot_map: dict[str, list[str]] = {}
    for day in available_slots:
        d = (day.get("date") or "").strip()
        slots = [str(s).strip() for s in (day.get("slots") or []) if str(s).strip()]
        if d in target_days and slots:
            slot_map[d] = slots

    seed = _picker_seed(session_id, sales_email, first_date, second_date)
    rnd = random.Random(seed)
    selections = _select_priority_slots(slot_map, first_date, second_date, rnd)

    if not selections:
        txt = (
            f"Baik, saya bantu jadwalkan meeting untuk layanan {service_label}. "
            f"Namun jadwal {sales_name or 'konsultan kami'} belum tersedia untuk {first_date}-{second_date}. "
            f"Silakan sebutkan preferensi tanggal dan jam (timezone {tz})."
        )
        ma_state.update({
            "detected": True,
            "timezone": tz,
            "timezone_label": tz_label,
            "first_date": first_date,
            "second_date": second_date,
            "sales_email": sales_email,
            "sales_name": sales_name,
            "availability_raw": avail,
            "available_slot_map": slot_map,
            "max_other_picks": max_other_picks,
            "other_pick_count": int(ma_state.get("other_pick_count") or 0),
            "slot_window_index": window_index,
            "slot_window_base_offset": base_offset,
        })
        extra_base["meeting_arrangement"] = ma_state
        extra_base["service_label"] = service_label
        extra_base["sales_email"] = sales_email
        extra_base["sales_name"] = sales_name
        extra_base["user"] = user
        return {
            "route": "meeting_arrangement_no_slots",
            "language_name": language_name,
            "message": {"type": "string", "content": {"id": "m-meeting-noslots", "text": txt, "choices": None, "required": None}},
            "extra": extra_base,
        }

    choices: list[dict] = []
    for day_iso, slot_label in selections:
        try:
            value, label = _slot_label_for_picker(day_iso, slot_label, tz_label)
        except ValueError:
            continue
        choices.append({"value": value, "label": label, "selected": False})

    if not choices:
        return {
            "route": "meeting_arrangement_no_slots",
            "language_name": language_name,
            "message": {"type": "string", "content": {"id": "m-meeting-noslots", "text": f"Tidak ada jadwal untuk {service_label}.", "choices": None, "required": None}},
            "extra": extra_base,
        }

    if include_other:
        choices.append({
            "value": "OTHER_PICKED_SLOT",
            "label": _other_slot_label(language_code),
            "selected": False,
        })

    ma_state.update({
        "detected": True,
        "timezone": tz,
        "timezone_label": tz_label,
        "first_date": first_date,
        "second_date": second_date,
        "sales_email": sales_email,
        "sales_name": sales_name,
        "availability_raw": avail,
        "available_slot_map": slot_map,
        "max_other_picks": max_other_picks,
        "other_pick_count": int(ma_state.get("other_pick_count") or 0),
        "slot_window_index": window_index,
        "window_anchor_date": ma_state.get("window_anchor_date") or anchor_date.isoformat(),
        "slot_window_base_offset": base_offset,
    })
    extra_base["meeting_arrangement"] = ma_state
    extra_base["service_label"] = service_label
    extra_base["sales_email"] = sales_email
    extra_base["sales_name"] = sales_name
    extra_base["user"] = user

    return {
        "route": "meeting_arrangement_pick_slot",
        "language_name": language_name,
        "choices": choices,
        "extra": extra_base,
    }

def _has_cover_range(slots: List[dict], start_wib: datetime, end_wib: datetime) -> bool:
    """True jika [start_wib,end_wib) bisa ditutupi chain slot 'free' berurutan (30m/60m sama-sama aman)."""
    step = timedelta(minutes=30)
    t = start_wib
    while t < end_wib:
        nxt = min(t + step, end_wib)
        ok = any(
            s["status"] == "free" and s["start"] <= t and s["end"] >= nxt
            for s in slots
        )
        if not ok:
            return False
        t = nxt
    return True

def _pick_primary_candidate(emails: List[str], target_date, start_wib, end_wib):
    """Urutkan kandidat: bisa-cover dulu → booked lebih sedikit → email asc."""
    candidates = []
    for em in emails:
        slots = get_sales_slots_for_date(em, target_date)
        booked = sum(1 for s in slots if s["status"] == "booked")
        has_cover = _has_cover_range(slots, start_wib, end_wib) if slots else False
        candidates.append({"email": em, "slots": slots, "booked": booked, "has_cover": has_cover})
    candidates.sort(key=lambda c: (not c["has_cover"], c["booked"], c["email"]))
    return candidates, (candidates[0] if candidates else None)

# ambil 2 label terdekat per sales untuk hari tertentu, hanya yang durasinya sama ---
def _nearest_free_by_sales(emails: List[str], day: datetime.date,
                           target_start: datetime, duration_min: int,
                           k_per_sales: int = 2) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for em in emails:
        labels = free_labels_for_date(em, day)
        scored = []
        for lab in labels:
            parsed = _parse_label_to_wib(day, lab)
            if not parsed:
                continue
            s, e = parsed
            dur = int((e - s).total_seconds() // 60)
            if dur != duration_min:
                continue  # jaga konsistensi durasi dengan permintaan user
            dist = abs((s - target_start).total_seconds())
            scored.append((dist, s, e, lab))
        scored.sort(key=lambda x: x[0])
        picks = []
        for _, s, e, lab in scored[:k_per_sales]:
            # tampilkan sesuai label asli, tambahkan WIB
            picks.append(f"{lab} WIB")
        if picks:
            out[em] = picks
    return out

def _format_alt_lines_by_day(alts: list[tuple[datetime, datetime]]) -> list[str]:
    from collections import defaultdict
    by_day: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    for s, e in alts:
        key = human_date(s.astimezone(WIB).date())
        by_day[key].append((s, e))
    lines = []
    for day_key, arr in by_day.items():
        arr.sort(key=lambda x: x[0])  # urut kronologis
        times = [human_time_range(s, e) for s, e in arr]
        lines.append(f"{day_key}: " + ", ".join(times))
    return lines

def _free_intervals_from_slots(slots: List[dict]) -> List[tuple[datetime, datetime]]:
    """Ambil interval FREE panjang dari list slots per-hari (status=free), sudah di-WIB (tuple-based)."""
    free = [(s["start"], s["end"]) for s in slots if s.get("status") == "free"]
    if not free:
        return []
    free.sort(key=lambda x: x[0])
    merged: list[tuple[datetime, datetime]] = []
    cur_s, cur_e = free[0]
    for s, e in free[1:]:
        if s <= cur_e:
            if e > cur_e:
                cur_e = e
        else:
            merged.append((cur_s, cur_e))
            cur_s, cur_e = s, e
    merged.append((cur_s, cur_e))
    return merged

def _collect_alts_across_sales(
    emails: List[str],
    day: date,
    target_start: datetime,
    duration_min: int,
    k_total: int | None = None,
    allow_leniency: bool = True
) -> list[tuple[datetime, datetime]]:
    """
    Gabungkan interval FREE lintas sales → jadikan window berdurasi 'duration_min'
    (dengan toleransi ±30m bila perlu). Hasil diurutkan KRONOLOGIS sepanjang hari.
    Dedup antar sales supaya window sama tidak dobel.
    """
    if k_total is None:
        try:
            k_total = int(os.getenv("MEETING_ALT_LIMIT", "96"))
        except Exception:
            k_total = 96

    seen: set[tuple[str, str]] = set()
    cand: list[tuple[datetime, datetime]] = []

    for em in emails:
        slots = get_sales_slots_for_date(em, day)          # WIB
        intervals = _free_intervals_from_slots(slots)      # [(s,e)]
        wins = windows_from_intervals(intervals, duration_min)
        if not wins and allow_leniency:
            for dl in (30, -30):
                if duration_min + dl > 0:
                    wins += windows_from_intervals(intervals, duration_min + dl)

        for s, e in wins:
            key = (s.isoformat(), e.isoformat())
            if key in seen:
                continue
            seen.add(key)
            cand.append((s, e))

    # urutkan KRONOLOGIS by start time agar muncul hingga sore
    cand.sort(key=lambda x: x[0])
    return cand[:k_total]

def _compose_unavailable_with_alternatives(language_code: str,
                                           nick_plain: str,
                                           addr_formal: str,
                                           day: date,
                                           start_wib: datetime,
                                           end_wib: datetime,
                                           alternatives: list[tuple[datetime, datetime]]) -> str:
    who = (addr_formal or nick_plain or "").strip()
    head = (f"{who}, jendela waktu yang diminta tidak tersedia untuk semua sales."
            if (language_code or "").lower().startswith("id")
            else f"{who}, the requested window isn’t available for all sales.")
    lines = _format_alt_lines_by_day(alternatives)
    tail  = ("Silakan pilih salah satu opsi di atas atau ajukan waktu lain."
             if (language_code or "").lower().startswith("id")
             else "Please pick one option above or propose another time.")
    return "\n".join([head, *lines, tail])

def _compose_outside_hours_message(language_code: str, nick: str | None, addr_formal: str | None,
                                   day, start_wib, end_wib) -> str:
    # ... (tetap seperti versi kamu sekarang) ...
    req_str = f"{human_date(day)} {human_time_range(start_wib, end_wib)}"
    hours = business_hours_text()
    suggestions = suggest_within_business(day, start_wib, end_wib, k=2)
    sug_txt = "; ".join(human_time_range(s, e) for s, e in suggestions) if suggestions else ""
    who = (addr_formal or nick or "").strip()
    if (language_code or "").lower().startswith("en"):
        base = (f"{who}, the requested window {req_str} is outside our working hours. "
                f"Our business hours are {hours}.")
        if sug_txt:
            base += f" You can try: {sug_txt}."
        base += " Please pick one or propose another time within working hours."
        return base
    else:
        base = (f"{who}, rentang {req_str} berada di luar jam kerja kami. "
                f"Jam operasional: {hours}.")
        if sug_txt:
            base += f" Anda bisa memilih salah satu alternatif berikut: {sug_txt}."
        base += " Silakan pilih salah satu atau ajukan waktu lain di dalam jam kerja."
        return base

def _compose_proposal(language_code: str, nick_plain: str, addr_formal: str,
                      target_date, start_wib, end_wib, primary,
                      emails_if_all_fail: List[str]) -> str:
    """Jika primary bisa cover → tawarkan konfirmasi; jika tidak → fallback lintas sales (hari ini & besok)."""
    when = f"{human_date(target_date)} {human_time_range(start_wib, end_wib)}"
    mention = addr_formal or nick_plain or ""
    if primary and primary.get("has_cover"):
        if (language_code or "").lower().startswith("en"):
            return (f"{mention}, I can schedule your meeting on {when}. "
                    f"Does this time work? If yes, I’ll confirm and send a calendar invite.")
        else:
            return (f"{mention}, saya dapat menjadwalkan pertemuan pada {when}. "
                    f"Apakah waktu tersebut sesuai? Jika ya, saya akan konfirmasi dan mengirim undangan kalender.")

    # kumpulkan alternatif dari semua sales (hari yang sama dan besok) dengan durasi sama
    dur_min = int((end_wib - start_wib).total_seconds() // 60)
    tomorrow = target_date + timedelta(days=1)

    alts_today = _collect_alts_across_sales(
        emails_if_all_fail, target_date, start_wib, dur_min, k_total=None
    )
    target_tom_same = to_wib(datetime(
        tomorrow.year, tomorrow.month, tomorrow.day, start_wib.hour, start_wib.minute
    ))
    alts_tom = _collect_alts_across_sales(
        emails_if_all_fail, tomorrow, target_tom_same, dur_min, k_total=None
    )
    alternatives = alts_today + alts_tom

    # LOG: alternatif yang ditawarkan (tanpa email)
    try:
        from .ma_repo import log_meeting_debug
        log_meeting_debug(
            session_id=os.getenv("CURRENT_SESSION_ID",""),
            token_id=os.getenv("CURRENT_TOKEN_ID"),
            stage="alternatives",
            payload={
                "date": str(target_date),
                "requested": {"start": start_wib.isoformat(), "end": end_wib.isoformat()},
                "alts": [{"start": s.isoformat(), "end": e.isoformat()} for s, e in alternatives][:100]
            }
        )
    except Exception:
        pass

    # ===== Fallback baru: 7 hari ke depan mulai besok =====
    return _compose_unavailable_weekly(
        language_code, nick_plain, addr_formal,
        target_date, start_wib, end_wib, emails_if_all_fail,
    )

# Meeting arrangement helper

# --- Pilih sales dengan "jadwal tersedikit" selama 1 minggu target (free slot paling SEDIKIT) ---
def _monday_of(dt: date) -> date:
    return dt - timedelta(days=dt.weekday())

def _weekly_free_slots_count(email: str, monday: date, days: int = 7) -> int:
    """Hitung banyaknya label FREE sepanjang minggu (Mon..Sun) untuk 1 sales."""
    total = 0
    for i in range(days):
        d = monday + timedelta(days=i)
        try:
            labels = free_labels_for_date(email, d) or []
            total += len(labels)
        except Exception:
            pass
    return total

def pick_least_free_weekly(ok_emails: list[str], target_date: date) -> str | None:
    """Pilih sales dengan FREE paling sedikit (jadwal tersedikit) minggu target_date.
       Kalau seri, urutkan alfabetis agar deterministik."""
    if not ok_emails:
        return None
    monday = _monday_of(target_date)
    scored = []
    for em in ok_emails:
        free_cnt = _weekly_free_slots_count(em, monday, days=7)
        scored.append((free_cnt, em))
    scored.sort(key=lambda x: (x[0], x[1]))  # free paling sedikit → prioritas, lalu email asc
    return scored[0][1]

# --- util: daftar 7 hari kerja mulai BESOK (bukan termasuk hari diminta)
def _working_days_list_inclusive(start_date: date, n_days: int) -> list[date]:
    out = []
    cur = start_date
    while len(out) < int(n_days):
        if cur.weekday() < 5:  # Mon..Fri
            out.append(cur)
        cur = cur + timedelta(days=1)
    return out

# --- ambil label union lintas sales untuk 1 tanggal (pakai repo existing free_labels_for_date)
def _union_labels_for_date(emails: list[str], d: date) -> list[str]:
    seen = set()
    for em in emails:
        try:
            for lab in (free_labels_for_date(em, d) or []):
                seen.add(lab)
        except Exception:
            pass
    # urutkan "HH:MM - HH:MM"
    return sorted(seen, key=lambda s: (int(s[:2])*60 + int(s[3:5])))

def _limit_words(s: str | None, n: int) -> str | None:
    if not s:
        return s
    w = s.strip().split()
    return " ".join(w) if len(w) <= n else " ".join(w[:n]) + "…"

def _compose_available_confirm_i18n(
    *, ask_llm, language_code: str, when_txt: str,
    date_txt: str, slot_txt: str, title_txt: str | None, recap_txt: str | None
) -> tuple[str, dict]:
    from langchain_core.messages import SystemMessage, HumanMessage
    from .ma_prompts import render_available_confirm_prompt

    sys_json = SystemMessage(content="Return valid JSON only. No markdown.")
    human    = HumanMessage(content=render_available_confirm_prompt(language_code, when_txt))
    # TODO(audit): plumb session_id
    prompt_msgs_propose_compose = [sys_json, human]
    with audit_llm_call(
        route="meeting_arrangement",
        stage="propose_compose",
        session_id="",
        token_id=None,
        prompt=prompt_msgs_propose_compose,
    ) as ctx:
        msg = ask_llm.invoke(prompt_msgs_propose_compose)
        ctx.set_response_from_message(msg)

    raw = getattr(msg, "content", "{}") or "{}"
    try:
        data = json.loads(raw)
    except Exception:
        data = {}

    is_id = (language_code or "").lower().startswith("id")
    intro = (data.get("available_intro") or ("Waktu yang Anda minta pada {when_txt} tersedia." if is_id else "The time you requested on {when_txt} is available.")).replace("{when_txt}", when_txt)
    askln = data.get("confirm_line") or ("Jika sesuai, saya akan konfirmasi dan mengirim undangan kalender." if is_id else "If that works, I will confirm and send a calendar invite.")
    hdr   = data.get("confirm_header") or ("Mohon konfirmasi detail berikut:" if is_id else "Please confirm the details below:")
    l_date= data.get("label_date") or ("Tanggal:" if is_id else "Date:")
    l_time= data.get("label_time") or ("Waktu:" if is_id else "Time:")
    l_ag  = data.get("label_agenda") or ("Ringkasan agenda:" if is_id else "Agenda summary:")
    lead  = data.get("recap_lead") or ("Dari percakapan kita:" if is_id else "From our conversation:")

    # pagar token: agenda ≤12 kata, recap ≤40 kata
    title_txt = _limit_words(title_txt, 12) if title_txt else None
    recap_txt = _limit_words(recap_txt, 40) if recap_txt else None

    lines = [
        intro,                # 1) intro / available
        "",                   # spacer
        hdr,                  # 2) header konfirmasi
        f"- {l_date} {date_txt}",
        f"- {l_time} {slot_txt}",
    ]
    if title_txt:
        lines.append(f"- {l_ag} {title_txt}")

    if recap_txt:
        lines += ["", f"{lead} {recap_txt}"]   # 3) recap LLM 30–40 kata

    # 4) confirm line di PALING AKHIR
    lines += ["", askln]

    parts = {
        "available_confirm_prompt": human.content,
        "_usage": {
            "input_tokens":  ctx.input_tokens,
            "output_tokens": ctx.output_tokens,
            "duration":      ctx.latency_ms / 1000.0,
        }
    }
    return "\n".join(lines).strip(), parts

# === Compose AVAILABLE (i18n) =========================================
def _compose_available_i18n(*, ask_llm, language_code: str, when_txt: str):
    """
    Kembalikan tuple (text, parts) di mana:
      - text: kalimat konfirmasi ringkas dalam bahasa target
      - parts: dict dengan 'available_text_prompt' (human-readable) dan '_usage' (token metrics)
    """
    from langchain_core.messages import SystemMessage, HumanMessage
    from .ma_prompts import render_available_text_prompt

    sys_json = SystemMessage(content="Return valid JSON only. No markdown.")
    human    = HumanMessage(content=render_available_text_prompt(language_code, when_txt))
    # TODO(audit): plumb session_id
    prompt_msgs_propose_compose_v2 = [sys_json, human]
    with audit_llm_call(
        route="meeting_arrangement",
        stage="propose_compose_v2",
        session_id="",
        token_id=None,
        prompt=prompt_msgs_propose_compose_v2,
    ) as ctx:
        msg = ask_llm.invoke(prompt_msgs_propose_compose_v2)
        ctx.set_response_from_message(msg)

    raw = getattr(msg, "content", "{}") or "{}"
    try:
        data = json.loads(raw)
    except Exception:
        data = {}
    intro = (data.get("available_intro") or "The time you requested on {when_txt} is available.").replace("{when_txt}", when_txt)
    ask   = (data.get("confirm_line") or "If that works, I will confirm and send a calendar invite.")
    # Versi ID ringan
    if (language_code or "").lower().startswith("id"):
        intro = intro.replace("The time you requested on", "Waktu yang Anda minta pada")
        ask   = "Jika sesuai, saya akan konfirmasi dan mengirim undangan kalender."

    parts = {
        "available_text_prompt": human.content,
        "_usage": {
            "input_tokens":  ctx.input_tokens,
            "output_tokens": ctx.output_tokens,
            "duration":      ctx.latency_ms / 1000.0,
        },
    }
    return f"{intro} {ask}", parts

def _compose_unavailable_grouped_i18n(*, ask_llm, language_code: str, when_txt: str,
                                      emails: list[str], start_date: date, n_days: int):
    """
    Hasil akhir (text) seperti:
    "Maaf, jadwal {when_txt} tidak tersedia. Berikut ...:
     [Rabu, 29 Oktober 2025]
     jadwal yang tersedia:
     10:00-11:00 WIB
     ..."
    """
    # 1) Konstruksi daftar hari kerja (inclusive)
    days = _working_days_list_inclusive(start_date, int(n_days))

    # 2) Ambil slots tersedia per-hari via mirror sheet summary (Sales_Slots2)
    #    (gunakan util yang sudah kamu pakai: summarize_weekly_availability atau langsung repo sheet)
    #    Di sini kita langsung polling sheet per label agar 100% sinkron dengan "count sales".
    all_rows = []   # [(day_iso, "HH:MM - HH:MM", count)]
    labels = [
        "09:00 - 10:00","10:00 - 11:00","11:00 - 12:00","12:00 - 13:00",
        "13:00 - 14:00","14:00 - 15:00","15:00 - 16:00","16:00 - 17:00"
    ]
    # for d in days:
    #     day_iso = d.strftime("%Y-%m-%d")
    #     for lab in labels:
    #         ok_emails = get_sales_available_from_sheet(day_iso, lab)  # <-- sudah kamu punya
    #         cnt = len(ok_emails)
    #         if cnt > 0:
    #             all_rows.append((d, lab.replace(" - ", "-").replace(" ", ""), cnt))

    for d in days:
        day_iso = d.strftime("%Y-%m-%d")
        for lab in labels:
            # Gunakan ringkasan count dari tab Sales_Slots2 (atau sesuai ENV)
            cnt = get_count_from_summary(day_iso, lab)
            if cnt > 0:
                # tampilkan label apa adanya agar konsisten dengan UI/Sheet
                all_rows.append((d, lab, cnt))

    # 3) Jika semuanya kosong → balasan tetap harus muncul
    #    (kasus langka: semua penuh/holiday); tetap tampilkan header + "—"
    slots_by_day: dict[date, list[str]] = {d: [] for d in days}
    for d, lab, _cnt in all_rows:
        # normalize "HH:MM-HH:MM WIB"
        slots_by_day[d].append(lab + " WIB")

    # 4) Buat header tanggal i18n via prompt kecil
    #    (pakai date_headers_prompt supaya "[Rabu, 29 Oktober 2025]" sesuai bahasa)
    dates_json = [d.strftime("%Y-%m-%d") for d in days]
    headers_prompt = render_date_headers_prompt(language_code, dates_json)
    sys_json = SystemMessage(content="Return ONLY JSON with {\"headers\": [\"...[..]\", ...]}")
    # TODO(audit): plumb session_id
    prompt_msgs_headers_compose = [sys_json, HumanMessage(content=headers_prompt)]
    with audit_llm_call(
        route="meeting_arrangement",
        stage="headers_compose",
        session_id="",
        token_id=None,
        prompt=prompt_msgs_headers_compose,
    ) as ctx:
        hdr_resp = ask_llm.invoke(prompt_msgs_headers_compose)
        ctx.set_response_from_message(hdr_resp)
    # Sum tokens across both LLM calls in this composer to preserve the
    # aggregate `_usage` metric the legacy code emitted into prompt_parts.
    _agg_in = ctx.input_tokens
    _agg_out = ctx.output_tokens
    hdr_text = getattr(hdr_resp, "content", "") or "{" + "\"headers\": []}"
    try:
        headers = json.loads(hdr_text).get("headers", [])
    except Exception:
        headers = [f"[{human_date(d)}]" for d in days]  # fallback

    # 5) Alt text (lead, subheader, footer) i18n (tanpa JSON escape di prompt_applied)
    alt_prompt = render_alt_text_prompt(language_code, when_txt, n_days)
    alt_sys = SystemMessage(content="Return ONLY JSON keys lead_sentence,label_available_slots,label_no_slots,header_unavailable,subheader_alternatives,footer_choose")
    # TODO(audit): plumb session_id
    prompt_msgs_alt_compose = [alt_sys, HumanMessage(content=alt_prompt)]
    with audit_llm_call(
        route="meeting_arrangement",
        stage="alt_compose",
        session_id="",
        token_id=None,
        prompt=prompt_msgs_alt_compose,
    ) as ctx:
        alt_resp = ask_llm.invoke(prompt_msgs_alt_compose)
        ctx.set_response_from_message(alt_resp)
    _agg_in += ctx.input_tokens
    _agg_out += ctx.output_tokens
    alt_raw = getattr(alt_resp, "content", "") or "{}"
    try:
        alt = json.loads(alt_raw)
    except Exception:
        alt = {}

    lead   = alt.get("lead_sentence", "").strip() or "Setelah memvalidasi jadwal kami"
    unav   = alt.get("header_unavailable", "").strip() or f"Maaf, jadwal {when_txt} tidak tersedia."
    unav = unav.replace("{when_txt}", when_txt).replace("{{when_txt}}", when_txt)
    sub    = alt.get("subheader_alternatives", "").strip() or "Berikut jadwal alternatif yang tersedia untuk 7 hari kerja dimulai dari tanggal penawaran:"
    availL = alt.get("label_available_slots", "").strip() or "jadwal yang tersedia:"
    noneL  = alt.get("label_no_slots", "").strip() or "(—)"
    foot   = alt.get("footer_choose", "").strip() or "Silakan pilih salah satu waktu yang tersedia di atas."

    # 6) Rakitan final
    lines = [f"{lead}. {unav}", f"{sub}", ""]
    for i, d in enumerate(days):
        hdr = headers[i] if i < len(headers) else f"[{human_date(d)}]"
        lines.append(hdr)
        slots = slots_by_day.get(d, []) or []
        lines.append(f"{availL}")
        if slots:
            lines.extend(slots)
        else:
            lines.append(noneL)
        lines.append("")  # spacer antar hari
    lines.append(foot)

    # 7) kumpulkan "prompt parts" + usage untuk prompt_applied & metrik
    prompt_parts = {
        "alt_text_prompt": alt_prompt,
        "date_headers_prompt": headers_prompt,
        "_usage": {
            "input_tokens": _agg_in,
            "output_tokens": _agg_out,
        }
    }
    return "\n".join(lines).strip(), prompt_parts


def _summarize_title(ask_llm, language_name: str, chat_snips: list[dict]) -> str | None:
    # judul ringkas dari chat history (≤ 80 chars)
    summ = "\n".join([s.get("content","") for s in chat_snips][-8:])
    sys = SystemMessage(content=f"You are a helpful assistant. Language: {language_name}. Return a short meeting title (<= 80 chars). No quotes.")
    hm  = HumanMessage(content=f"Chat summary notes:\n{summ}\n\nTitle:")
    try:
        # TODO(audit): plumb session_id
        prompt_msgs_confirm_compose = [sys, hm]
        with audit_llm_call(
            route="meeting_arrangement",
            stage="confirm_compose",
            session_id="",
            token_id=None,
            prompt=prompt_msgs_confirm_compose,
        ) as ctx:
            resp = ask_llm.invoke(prompt_msgs_confirm_compose)
            ctx.set_response_from_message(resp)
        title = (getattr(resp, "content", "") or "").strip()
        return title[:80] if title else None
    except Exception:
        return None

def _build_booking_payload_base(*, selected_sales_email: str | None,
                                start_wib: datetime, end_wib: datetime,
                                session_id: str, time_zone: str,
                                calendar_id_override: str | None) -> dict:
    prof = read_user_profile_from_sessions(session_id) or {}
    user_email = (prof.get("email") or "").strip()

    cal_id = (calendar_id_override or (selected_sales_email or user_email))
    attendees = _build_attendees_list(user_email=user_email, sales_email=selected_sales_email)

    return {
        "calendarId": cal_id,
        "summary": "",          # ← diisi di sd_service setelah summarization
        "description": "",      # ← diisi di sd_service setelah summarization
        "start": start_wib.isoformat(),
        "end": end_wib.isoformat(),
        "timeZone": time_zone,
        "attendees": attendees,
        "eventType": "default",
    }

def _build_booking_payload_final(*, selected_sales_email: str | None, start_wib: datetime, end_wib: datetime,
                                 session_id: str, token_id: str | None, ask_llm, language_name: str,
                                 time_zone: str, calendar_id_override: str | None) -> dict:
    # user email dari crisp_sessions
    prof = read_user_profile_from_sessions(session_id) or {}
    user_email = (prof.get("email") or "").strip()

    # chat history untuk summary/description
    hist_items = read_chat_history(session_id, token_id=token_id) or []
    window_text = f"{human_date(start_wib.date())} {human_time_range(start_wib, end_wib)}"

    # description: full chat summarization (pakai fungsi yg sudah ada)
    description = _summarize_desc(
        ask_llm=ask_llm,
        language_name=language_name,
        user_profile=prof,
        chat_snips=hist_items,
        window_text=window_text,
        related_services=_collect_services_from_history(hist_items),
    ) or "—"

    # summary: ringkas (title) dari chat summarization
    summary = _summarize_title(ask_llm, language_name, hist_items) or "Meeting with Client"

    # calendarId override jika ada
    cal_id = (calendar_id_override or (selected_sales_email or user_email))

    # attendees: user + sales (jika ada)
    attendees = _build_attendees_list(user_email=user_email, sales_email=selected_sales_email)

    payload = {
        "calendarId": cal_id,
        "summary": summary,
        "description": description,
        "start": start_wib.isoformat(),   # sudah +07:00 dari to_wib()
        "end":   end_wib.isoformat(),
        "timeZone": time_zone,
        "attendees": attendees,
        "eventType": "default",
    }

    # Simpan juga endpoint POST jika perlu dipakai caller
    booked_api = os.getenv("BOOKED_PATH_API", "").strip()
    if booked_api:
        payload["_post_to"] = booked_api

    return payload

def _llm_run_plain(ask_llm, prompt: str) -> str:
    """Jembatan: CWH mem-passing prompt string; kita invoke LLM dan balikin teks polos."""
    try:
        # TODO(audit): plumb session_id
        prompt_msgs_summary_compose = [SystemMessage(content="Return only the summary text."), HumanMessage(content=prompt)]
        with audit_llm_call(
            route="meeting_arrangement",
            stage="summary_compose",
            session_id="",
            token_id=None,
            prompt=prompt_msgs_summary_compose,
        ) as ctx:
            resp = ask_llm.invoke(prompt_msgs_summary_compose)
            ctx.set_response_from_message(resp)
        return (getattr(resp, "content", "") or "").strip()
    except Exception:
        return ""

def _summarize_with_cwh(*, session_id: str, token_id: str | None, ask_llm, include_current_turn: dict | None = None) -> tuple[str, str]:
    """
    Pakai CWH untuk merangkum full chat:
    - pairs = get_history_pairs(session_id, token_id)
    - kalau include_current_turn ada → append ke pairs (opsional)
    - bangun prompt via CWH → panggil LLM
    - title = baris pertama ringkasan (<=80 chars)
    """
    cached_hist = read_chat_history(session_id=session_id, token_id=token_id) or []
    cached_summary = _latest_chat_summary(cached_hist)
    if cached_summary:
        first_line = (cached_summary.split("\n", 1)[0] or "").strip() or "Meeting with Client"
        return cached_summary, first_line[:80]

    pairs = get_history_pairs(session_id, token_id=token_id) or []  # :contentReference[oaicite:4]{index=4}
    if include_current_turn:
        pairs = pairs + [include_current_turn]

    prompt = build_history_summarize_prompt(pairs, max_chars=cfg.HISTORY_SUMMARY_MAX_CHARS)  # :contentReference[oaicite:5]{index=5}
    full = _llm_run_plain(ask_llm, prompt)
    if len(full) > cfg.HISTORY_SUMMARY_MAX_CHARS:
        full = full[:cfg.HISTORY_SUMMARY_MAX_CHARS] + "…"

    title = (full.split("\n", 1)[0] if full else "Meeting with Client")[:80]
    return full, title

def send_calendar_booking(session_id: str, token_id: str) -> dict:
    url = cfg.BOOKED_PATH_API
    token = cfg.BEARER_TOKEN_CALENDAR_API

    col_name = cfg.PAYLOAD_CALENDAR_COL
    mongo = get_mongo_client()
    coll  = mongo[col_name]

    # 🔧 Ambil draft TERBARU untuk session+token
    doc = coll.find_one(
        {"sessionId": session_id, "tokenId": token_id, "status": "draft"},
        sort=[("created_at", -1), ("_id", -1)]
    )
    if not doc:
        print("[CALENDAR][WARN] Tidak ditemukan draft calendar_payload yang sesuai")
        return {"status": "error", "msg": "No draft payload found"}

    payload = (doc.get("payload") or {}).copy()

    website_id = (token_id or session_id or "").strip()
    if not website_id:
        website_id = session_id or ""
    payload["websiteId"] = website_id
    payload["sessionId"] = session_id

    # Pastikan attendees unik & rapi (tanpa menambah organizer)
    attendees = payload.get("attendees") or []
    seen = set()
    clean = []
    for a in attendees:
        em = (a or {}).get("email")
        if not em:
            continue
        em = em.strip().lower()
        if em in seen:
            continue
        seen.add(em)
        clean.append({"email": em})
    payload["attendees"] = clean

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # === DEBUG LOG BODY KALENDER ===
    try:
        print("\n[CALENDAR][DEBUG] === PAYLOAD YANG DIKIRIM ===")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        print("[CALENDAR][DEBUG] === HEADER ===")
        print(json.dumps(headers, indent=2))
        print("[CALENDAR][DEBUG] === END PAYLOAD ===\n")
    except Exception as e:
        print(f"[CALENDAR][DEBUG][ERROR_PRINT]: {e}")

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        ok = resp.status_code in (200, 201)
        now = datetime.utcnow()

        if ok:
            coll.update_one(
                {"_id": doc["_id"]},
                {"$set": {
                    "status": "sent",
                    "payload": payload,              # simpan payload final yang benar-benar dikirim
                    "sent_at": now,
                    "updated_at": now,
                    "http_status": resp.status_code,
                    "api_response": resp.text  # perbesar sedikit agar cukup
                }}
            )
            print(f"[CALENDAR] ✅ Draft updated to status=sent (no extra doc)")
            return {"status": "success", "http_status": resp.status_code, "response": resp.text}
        else:
            coll.update_one(
                {"_id": doc["_id"]},
                {"$set": {"status": "failed", "updated_at": now, "http_status": resp.status_code}}
            )
            print(f"[CALENDAR][FAIL] Status code {resp.status_code} — updated draft to failed")
            return {"status": "failed", "http_status": resp.status_code, "response": resp.text}

    except Exception as e:
        print("[CALENDAR][EXCEPTION]", str(e))
        return {"status": "error", "msg": str(e)}

# ===== Entry point =====

def handle_meeting_flow(
    *,
    session_id: str,
    question: str,
    token_id: str | None = None,
    language_code: str,
    language_name: str,
    is_first_turn: bool,
    user_nick: str | None,
    ask_llm,
    chat_history_block: str | None = None,   
    chat_summary_block: str | None = None,   
) -> Dict[str, Any] | None:
    """
    - Trigger via command/keywords → tampilkan prompt contoh format & jam kerja.
    - Jika user sudah memberi tanggal/jam → parse & validasi.
    - Jika di luar jam → pesan kontekstual + saran terdekat.
    - Jika valid → gate ke Sheet, pilih sales (IDV sheet), lalu rangkai balasan.
    """
    # 1) Trigger?
    history_block = chat_history_block or ""
    summary_block = chat_summary_block or ""
    is_cmd, cmd = parse_meeting_command(question)
    is_meet, _why = detect_meeting_intent(question)
    if is_cmd:
        # token_id = getattr(ask_llm, "token_id", os.getenv("CURRENT_TOKEN_ID"))
        token_id=token_id
        # (opsional) embed ringkasan CWH ke prompt_applied seperti sebelumnya
        pairs = get_history_pairs(session_id, token_id=token_id) or []
        prompt_sum = build_history_summarize_prompt(pairs, max_chars=cfg.HISTORY_SUMMARY_MAX_CHARS)
        try:
            prompt_msgs_recap_summary = [
                SystemMessage(content=f"Return ONLY a plain summary text in {language_name}. No titles, no quotes, no markdown."),
                HumanMessage(content=prompt_sum),
            ]
            with audit_llm_call(
                route="meeting_arrangement",
                stage="recap_summary",
                session_id=session_id,
                token_id=token_id,
                prompt=prompt_msgs_recap_summary,
            ) as ctx:
                sum_resp = ask_llm.invoke(prompt_msgs_recap_summary)
                ctx.set_response_from_message(sum_resp)
            brief_sum = (getattr(sum_resp, "content", "") or "").strip()
        except Exception:
            brief_sum = ""

        # 1h slot windows (09–17) → buat CSV untuk prompt i18n NOTE
        start_hour, end_hour = 9, 17
        slots = [f"{h:02d}:00–{h+1:02d}:00 WIB" for h in range(start_hour, end_hour)]
        slot_windows_csv = ", ".join(slots)

        # Panggil micro-prompt NOTE agar bahasanya mengikuti language_code
        note_prompt = render_meeting_start_note_prompt(language_code, start_hour, end_hour, slot_windows_csv)
        prompt_msgs_recap_note = [SystemMessage(content="Return a single sentence. No quotes."),
                                    HumanMessage(content=note_prompt)]
        with audit_llm_call(
            route="meeting_arrangement",
            stage="recap_note",
            session_id=session_id,
            token_id=token_id,
            prompt=prompt_msgs_recap_note,
        ) as ctx:
            note_resp = ask_llm.invoke(prompt_msgs_recap_note)
            ctx.set_response_from_message(note_resp)
        note_constraints = (getattr(note_resp, "content", "") or "").strip()
        if not note_constraints:
            if (language_code or "").lower().startswith("id"):
                note_constraints = f"Catatan: meeting berdurasi 1 jam antara 09:00–17:00 WIB. Opsi: {slot_windows_csv}."
            else:
                note_constraints = f"Note: meetings are 1-hour between 09:00–17:00 WIB. Options: {slot_windows_csv}."

        # # Ambil CWH blocks supaya prompt_applied berisi history+summary
        # history_block, summary_block = _build_history_blocks(session_id, token_id)

        rendered = render_meeting_start_prompt(
            language_name=language_name,
            is_first_turn=is_first_turn,
            user_nick=user_nick,
            language_code=language_code,
            business_hours="09:00–17:00 WIB",
            note_constraints=note_constraints,     # ← masuk ke prompt
            chat_history_block=history_block,
            chat_summary_block=summary_block,
        )

        BASE_LLM = ChatAnthropic(
            model=cfg.ANTHROPIC_MODEL,
            anthropic_api_key=cfg.ANTHROPIC_API_KEY,
            max_tokens=cfg.MAX_OUTPUT_TOKENS,
            temperature=cfg.LLM_TEMPERATURE,
        )
        BRIEF_LLM = BASE_LLM.bind(max_tokens=cfg.MAX_TOKENS_BRIEF if hasattr(cfg, "MAX_TOKENS_BRIEF") else cfg.MAX_TOKENS_BRIEF)

        prompt_msgs_propose_inline = [SystemMessage(content=rendered), HumanMessage(content=question)]
        with audit_llm_call(
            route="meeting_arrangement",
            stage="propose_inline",
            session_id=session_id,
            token_id=token_id,
            prompt=prompt_msgs_propose_inline,
        ) as ctx:
            msg = BRIEF_LLM.invoke(prompt_msgs_propose_inline)
            ctx.set_response_from_message(msg)

        text = getattr(msg, "content", "") or ""

        # Pastikan NOTE tampil walau model lupa
        if note_constraints and (note_constraints not in text):
            text = text + "\n\n" + note_constraints

        # Rapikan jeda baris: 2 newline sebelum NOTE dan sebelum contoh
        if (language_code or "").lower().startswith("id"):
            note_mark = "Catatan:"
            ex_mark   = "Contoh"
        else:
            note_mark = "Note:"
            ex_mark   = "Example"

        def _ensure_block_spacing(s: str, marker: str) -> str:
            if marker in s:
                s = s.replace(marker, f"\n\n{marker}")
                # Hilangkan potensi triple-newline berurutan
                s = s.replace("\n\n\n", "\n\n")
            return s

        text = _ensure_block_spacing(text, note_mark)
        text = _ensure_block_spacing(text, ex_mark)

        # Jika model tidak menyebutkan note/opsi → tambahkan deterministik
        if note_constraints and (note_constraints not in text):
            # Pastikan opsi slot ikut disebut JELAS
            extra = f"\n\n{note_constraints}"
            if slot_windows_csv not in note_constraints:
                extra += f" {('Opsi: ' + slot_windows_csv) if (language_code or '').lower().startswith('id') else ('Options: ' + slot_windows_csv)}."
            text = text.strip() + extra

        # Variasi penyebutan → pakai user_nick (bukan resolved_nick)
        nick_plain, addr_formal = _address_forms_by_language(language_code, user_nick)
        seed_val = (hash(f"{session_id}:{question}") & 0xFFFFFFFF)
        # text = enforce_name_variation(
        #     text, language_code, nick_plain, addr_formal,
        #     cadence=3, max_mentions_short=2, max_mentions_long=3, seed=seed_val
        # )

        result = {
            "session_id": session_id,
            "token_id": token_id,
            "user_nick": user_nick,
            "question": question,
            "message": text,
            "prompt_applied": rendered,         # ← sudah memuat chat_summary_block
            "route": "meeting_start",
            "language_name": language_name,
            "respond_duration": ctx.latency_ms / 1000.0,
            "input_token": ctx.input_tokens,
            "output_token": ctx.output_tokens,
        }
        log_run(session_id, question, result)
        return result

    # 2) Intent meeting?
    is_meet, _why = detect_meeting_intent(question)
    _d = parse_date(question)
    _ts, _te, _ = parse_time_range(question)
    if not is_meet and _d and _ts:
        is_meet = True
    if not is_meet:
        return None

    # 3) Parse tanggal & jam (LLM minimal 3-field → fallback rule-based)
    prefer_llm = os.getenv("PREFER_LLM_PARSE", "false").lower() == "true"
    start_wib = end_wib = None
    d = None

    if prefer_llm:
        norm = llm_parse_day_and_slot(ask_llm, question)
        if norm and not norm.get("incomplete") and norm.get("day_iso") and norm.get("slot_label"):
            d_iso = norm["day_iso"]
            slot_label = norm["slot_label"]
            try:
                y, m, dd = map(int, d_iso.split("-"))
                d = date(y, m, dd)
                parsed = _parse_label_to_wib(d, slot_label)
                if parsed:
                    start_wib, end_wib = parsed
            except Exception:
                d = None
                start_wib = end_wib = None

    if not (d and start_wib and end_wib):
        # fallback parser lama
        d2 = parse_date(question)
        ts, te, dur = parse_time_range(question)
        if not d2 or not ts:
            rendered = render_meeting_start_prompt(
                language_name=language_name, is_first_turn=is_first_turn,
                user_nick=user_nick, language_code=language_code
            )
            prompt_msgs_qualification_inline = [SystemMessage(content=rendered), HumanMessage(content=question)]
            with audit_llm_call(
                route="meeting_arrangement",
                stage="qualification_inline",
                session_id=session_id,
                token_id=token_id,
                prompt=prompt_msgs_qualification_inline,
            ) as ctx:
                msg = ask_llm.invoke(prompt_msgs_qualification_inline)
                ctx.set_response_from_message(msg)
            text = getattr(msg, "content", str(msg))
            result = {"route": "meeting_start", "language_name": language_name, "message": text, "prompt_applied": rendered}
            log_run(session_id, question, result)
            return result
        d = d2
        start_wib = to_wib(datetime(d.year, d.month, d.day, ts.hour, ts.minute))
        end_wib   = to_wib(datetime(d.year, d.month, d.day, te.hour, te.minute))

    # LOG (a): parse
    try:
        log_meeting_debug(session_id, getattr(ask_llm, "token_id", None), "parse", {
            "raw": question, "date": str(d),
            "start": start_wib.isoformat(), "end": end_wib.isoformat(),
            "parser": ("llm_minimal" if prefer_llm else "rule_based")
        })
    except Exception:
        pass

    # 4) Business rules
    bad, reason = violates_business_rules(start_wib, end_wib)
    if bad:
        nick_plain, addr_formal = _address_forms_by_language(language_code, user_nick)
        msg_txt = _compose_outside_hours_message(language_code, nick_plain, addr_formal, d, start_wib, end_wib)
        result = {"route": "meeting_start", "language_name": language_name, "message": msg_txt, "prompt_applied": "business_rules_guard"}
        log_run(session_id, question, result)
        return result
    try:
        log_meeting_debug(session_id, getattr(ask_llm, "token_id", None), "business_check", {"ok": not bad, "reason": reason})
    except Exception:
        pass

    # 5) Kandidat sales (by country)
    user_cc = read_user_country_from_sessions(session_id) or ""
    emails = list_distinct_sales_emails(user_cc)

    # 6) Gate availability & pilih sales dari Google Sheet
    slot_label = f"{start_wib:%H:%M} - {end_wib:%H:%M}"
    day_iso = d.strftime("%Y-%m-%d")

    ok_emails_sheet = get_sales_available_from_sheet(day_iso, slot_label)
    matched_count = len(ok_emails_sheet)

    is_weekend = d.weekday() >= 5
    status = "available" if matched_count > 0 else ("day_off" if is_weekend else "booked")

    selected_email = None
    sales_accumulation = {}

    if len(ok_emails_sheet) == 1:
        selected_email = ok_emails_sheet[0]
    elif len(ok_emails_sheet) >= 2:
        sales_accumulation = get_weekly_availability_counts(d, ok_emails_sheet, days=7) or {}
        ranked = sorted(sales_accumulation.items(), key=lambda x: (-x[1], x[0]))
        selected_email = ranked[0][0] if ranked else None

    if matched_count == 1:
        selected_email = ok_emails_sheet[0]
    elif matched_count >= 2:
        selected_email, sales_accumulation = pick_most_available_weekly_from_sheet(d, ok_emails_sheet, n_workdays=7)
        print("[DEBUG] matched_count:", matched_count)
        print("[DEBUG] ok_emails_sheet:", ok_emails_sheet)
        print("[DEBUG] selected_email:", selected_email)
        print("[DEBUG] sales_accumulation:", sales_accumulation)


    # 7) Simpan ringkasan (ma_confirmation)
    prof = read_user_profile_from_sessions(session_id) or {}
    user_email = (prof.get("email") or "").strip()
    # token_id = getattr(ask_llm, "token_id", os.getenv("CURRENT_TOKEN_ID"))
    token_id=token_id
    try:
        upsert_ma_confirmation(
            session_id=session_id,
            token_id=token_id,
            user_email=user_email,
            day=d,
            start_wib=start_wib,
            end_wib=end_wib,
            selected_sales_email=selected_email,
            status=status
        )
    except Exception:
        pass

    # 8) Logging ranking legacy (untuk audit; tidak mempengaruhi balasan)
    candidates, primary = _pick_primary_candidate(emails, d, start_wib, end_wib)
    try:
        log_meeting_debug(
            session_id=session_id,
            token_id=token_id,
            stage="selection",
            payload={
                "considered_sales": emails,
                "ranked": [{"email": c["email"], "booked": c["booked"], "has_cover": c["has_cover"]} for c in candidates],
                "ok_emails_sheet": ok_emails_sheet,
                "selected_by_sheet": selected_email,
                "sales_accumulation": sales_accumulation or {},
            }
        )
    except Exception:
        pass

    # 9) Compose message
    nick_plain, addr_formal = _address_forms_by_language(language_code, user_nick)
    when_text = f"{human_date(d)} {human_time_range(start_wib, end_wib)}"

    # # --- Tambahkan default agar tidak error saat UNAVAILABLE ---
    # summary_text = "Meeting discussion and next steps"
    # desc_text = "Meeting details and discussion summary not available."

    if matched_count > 0:
        # 1) Siapkan teks waktu manusiawi
        when_text = f"{human_date(d)} {human_time_range(start_wib, end_wib)}"

        # 2) Generate RECAP 30–40 kata (pakai chat_summary_block yang sudah kamu passing ke handle_meeting_flow)
        recap_txt = ""
        try:
            from .ma_prompts import render_recap_3040_prompt
            recap_prompt = render_recap_3040_prompt(language_code, chat_summary_block or "")
            prompt_msgs_recap_compose = [
                SystemMessage(content="Return ONLY the single-sentence recap. No markdown."),
                HumanMessage(content=recap_prompt),
            ]
            with audit_llm_call(
                route="meeting_arrangement",
                stage="recap_compose",
                session_id=session_id,
                token_id=token_id,
                prompt=prompt_msgs_recap_compose,
            ) as ctx:
                recap_msg = ask_llm.invoke(prompt_msgs_recap_compose)
                ctx.set_response_from_message(recap_msg)
            recap_txt = (getattr(recap_msg, "content", "") or "").strip()
        except Exception:
            recap_txt = ""

        # 3) Title ringkas untuk agenda (sudah kamu pegang via proses title/summary payload) → batasi 12 kata
        agenda_title = short_title if short_title else "Agenda konsultasi"

        # 4) Susun pesan konfirmasi lengkap (intro → detail → recap → confirm)
        text, parts_confirm = _compose_available_confirm_i18n(
            ask_llm=ask_llm,
            language_code=language_code,
            when_txt=when_text,
            date_txt=human_date(d),
            slot_txt=human_time_range(start_wib, end_wib),
            title_txt=agenda_title,
            recap_txt=recap_txt
        )

        # 5) Build & simpan payload kalender FINAL (sudah kamu lakukan; ini contoh jika belum)
        calendar_payload = _build_booking_payload_final(
            selected_sales_email=selected_email,
            start_wib=start_wib,
            end_wib=end_wib,
            session_id=session_id,
            token_id=token_id,
            ask_llm=ask_llm,
            language_name=language_name,
            time_zone=os.getenv("USER_TIMEZONE", "Asia/Jakarta"),
            calendar_id_override=os.getenv("CALENDAR_ID_OVERRIDE")  # None jika ENV kosong
        )

        prompt_applied = (
            "composer: compose_available_confirm_i18n\n"
            "---- available_confirm_prompt -----------\n"
            f"{parts_confirm.get('available_confirm_prompt','')}\n"
            "----------------------------------------\n"
            "---- recap_30_40_prompt -----------------\n"
            f"{recap_prompt}\n"
            "----------------------------------------"
        )

        text_output = text  # gunakan teks konfirmasi yang baru

    else:
        # UNAVAILABLE → composer i18n deterministik (mulai dari tanggal user, inclusive)
        t0 = time.monotonic()
        text, prompt_parts = _compose_unavailable_grouped_i18n(
            ask_llm=ask_llm,
            language_code=language_code,
            when_txt=when_text,
            emails=emails,
            start_date=d,                  # <-- inclusive dari HARI INI yang ditanyakan
            n_days=cfg.DAYS_PROPOSAL       # <-- dari ENV
        )
        t1 = time.monotonic()

        # prompt_applied: human-readable, bukan JSON escaped
        prompt_applied = (
            "composer: compose_unavailable_grouped_i18n\n"
            "---- alt_text_prompt ----------------------\n"
            f"{prompt_parts.get('alt_text_prompt','').strip()}\n"
            "---- date_headers_prompt ------------------\n"
            f"{prompt_parts.get('date_headers_prompt','').strip()}\n"
            "-------------------------------------------"
        )

        # rekam metrik LLM (kalau ada panggilan LLM dalam composer)
        usage = prompt_parts.get("_usage", {})
        in_tok  = int(usage.get("input_tokens",  0))
        out_tok = int(usage.get("output_tokens", 0))
        dur_s   = round(t1 - t0, 3)
        try:
            log_meeting_debug(session_id, getattr(ask_llm, "token_id", None), "proposal_compose_metrics",
                            {"input_token": in_tok, "output_token": out_tok, "duration": dur_s})
        except Exception:
            pass

    # 10) Payload downstream (FINAL)

    # === Full conversation summary for payload (CWH) ===
    # Sertakan turn ini sebagai konteks kalau mau (opsional)
    include_turn = {"question": question, "message": ""}

    full_desc, first_line_title = _summarize_with_cwh(
        session_id=session_id,
        token_id=token_id,
        ask_llm=ask_llm,
        include_current_turn=include_turn
    )

    # 10a) LLM title 8–10 kata dari summary (pakai full_desc)
    try:
        title_prompt = render_meeting_title_prompt(language_code or "en", full_desc)
        prompt_msgs_title_compose = [
            SystemMessage(content="Return ONLY the title text, no quotes."),
            HumanMessage(content=title_prompt),
        ]
        with audit_llm_call(
            route="meeting_arrangement",
            stage="title_compose",
            session_id=session_id,
            token_id=token_id,
            prompt=prompt_msgs_title_compose,
        ) as ctx:
            title_resp = ask_llm.invoke(prompt_msgs_title_compose)
            ctx.set_response_from_message(title_resp)
        llm_title = (getattr(title_resp, "content", "") or "").strip()
    except Exception:
        llm_title = ""

    def _clean_title(s: str) -> str:
        s = s.replace("\n", " ").strip()
        if s.endswith("."): s = s[:-1]
        return s[:85]

    # fallback ke baris pertama CWH bila LLM kosong
    short_title = _clean_title(llm_title) if llm_title else _clean_title(first_line_title or "Client discussion and next steps")

    # 10b) attendees (email user + sales terpilih)
    user_profile = read_user_profile_from_sessions(session_id) or {}
    user_email = (user_profile.get("email") or "").strip()
    attendees = []
    if user_email: attendees.append({"email": user_email})
    if selected_email: attendees.append({"email": selected_email})

    # 10c) payload final + simpan draft
    cal_id   = (os.getenv("CALENDAR_ID_OVERRIDE", "").strip() or selected_email or "")
    time_zone= os.getenv("USER_TIMEZONE", "Asia/Jakarta")
    post_to  = os.getenv("BOOKED_PATH_API", "").strip()

    calendar_payload_final = {
        "calendarId": cal_id,
        "summary": short_title,    # dari langkah 2
        "description": full_desc,  # dari langkah 2 (sudah dipotong dalam _summarize_with_cwh)
        "start": start_wib.isoformat(),
        "end":   end_wib.isoformat(),
        "timeZone": time_zone,
        "attendees": attendees,
        # "_post_to": post_to,
    }

    # d) simpan payload ke koleksi payload kalender (draft), TANPA menembak API
    try:
        save_calendar_payload(
            session_id=session_id,
            token_id=token_id,
            payload=calendar_payload_final,
            status="draft",
            sales_accumulation=sales_accumulation or {}
        )
    except Exception:
        pass

    # e) ranked (legacy logging)
    ranked = [
        {"email": c["email"], "has_cover": bool(c["has_cover"]), "booked_today": int(c["booked"])}
        for c in candidates
    ]

    result = {
        "route": "meeting_proposal",
        "language_name": language_name,
        "message": text_output,
        "prompt_applied": prompt_applied,
        "meeting_target": {
            "date": str(d),
            "start": start_wib.isoformat(),
            "end": end_wib.isoformat(),
            "selected_sales_email": selected_email,
            "candidate_email": selected_email,  # legacy
            "ranked_candidates": ranked,
            "considered_sales": emails,
            "selection_rule": "sheet_idv_least_avail_7_workdays_then_alpha",
        },
        # versi final yang akan ditembak oleh worker ops-mu (bila diperlukan)
        "calendar_payload": calendar_payload_final,
        "sales_accumulation": sales_accumulation or {},
    }

    log_run(session_id, question, result)

    try:
        log_meeting_debug(
            session_id=session_id,
            token_id=token_id,
            stage="final",
            payload={
                "meeting_target": result.get("meeting_target"),
                "calendar_payload": result.get("calendar_payload", {}),
            }
        )
    except Exception:
        pass

    return result

def handle_meeting_service_selected(
    *,
    session_id: str,
    question: str,
    last_extra: dict | None,
) -> dict:
    """
    Handler saat user klik pilihan service meeting: MA_ARRANGEMENT_*
    Output: dict plan berisi:
      - service_label
      - sales_email, sales_name (kalau ketemu)
      - extra (updated)
      - stage next
    NOTE: Sengaja DI SINI hanya "plan", supaya build payload tetap di sd_service.py
          (menghindari circular import).
    """
    picked_value = (question or "").strip()

    # 1) resolve label dari value memakai sumber yang sama dengan picker
    service_label = None
    for ch in build_ma_service_choices():  # fungsi yang sudah kamu pakai untuk choices
        if (ch.get("value") or "") == picked_value:
            service_label = (ch.get("label") or "").strip()
            break

    extra = dict(last_extra or {})
    ma = dict(extra.get("meeting_arrangement") or {})
    ma["stage"] = "selected_service"
    extra["meeting_arrangement"] = ma

    service_value_code = None
    service_code = None
    if service_label:
        extra["service_label"] = service_label
        service_value_code, service_code = _resolve_service_codes(service_label)
        if service_value_code:
            extra["service_value_code"] = service_value_code
        if service_code:
            extra["service_code"] = service_code

    # 2) fetch sales PIC by service_label (pakai cara yang sudah kamu buat sebelumnya)
    sales_email = None
    sales_name = None
    if service_label:
        pic = fetch_sales_pic_by_service(service_label) or {}
        sales_email = (pic.get("sales_email") or pic.get("email") or "").strip() or None
        sales_name = (pic.get("sales_name") or pic.get("name") or "").strip() or None

    if sales_email:
        extra["sales_email"] = sales_email
    if sales_name:
        extra["sales_name"] = sales_name

    # 3) stage berikutnya
    ma["stage"] = "got_sales_pic" if sales_email else "need_sales_pic"
    extra["meeting_arrangement"] = ma

    return {
        "service_label": service_label,
        "service_code": service_code,
        "sales_email": sales_email,
        "sales_name": sales_name,
        "extra": extra,
        "stage": ma["stage"],
    }

# ------ Build payload and chat history summarization

def _collect_services_from_history(items: List[Dict[str, Any]], max_items: int = 30) -> List[str]:
    sv = []
    for it in items[:max_items]:
        for s in it.get("related_services") or []:
            if s and s not in sv:
                sv.append(s)
    return sv


def _latest_chat_summary(items: List[Dict[str, Any]]) -> str:
    """Ambil ringkasan percakapan (jika sudah dibuat oleh summarizer)."""
    for it in reversed(items):
        meta = it.get("summarization_meta") or {}
        for key in ("chat_summarization", "summary_result", "summary_text"):
            summary = meta.get(key)
            if isinstance(summary, str):
                summary = summary.strip()
                if summary:
                    return summary
    return ""

def _summarize_conversation_plain(items: List[Dict[str, Any]], max_pairs: int = 5) -> str:
    """Ringkasan deterministik (tanpa LLM). Ambil beberapa Q/A terakhir dan related_services."""
    pairs = []
    for it in items[-max_pairs:]:
        q = (it.get("question") or "").strip()
        a = (it.get("message") or "").strip()
        if q:
            pairs.append(f"- Q: {q}")
        if a:
            clean_a = a[:240].replace('\n', ' ')
            pairs.append(f"  A: {clean_a}{'…' if len(a) > 240 else ''}")
    return "\n".join(pairs)

def _build_attendees_list(*, user_email: str | None, sales_email: str | None) -> list[dict]:
    seen: set[str] = set()
    attendees: list[dict] = []

    def _add(email: str | None):
        if not email:
            return
        em = email.strip()
        if not em:
            return
        key = em.lower()
        if key in seen:
            return
        seen.add(key)
        attendees.append({"email": em})

    _add(cfg.ORGANIZER_EMAIL)
    _add(user_email)
    _add(sales_email)
    return attendees

def build_calendar_payload_draft(*,
    session_id: str,
    selected_sales_email: str | None,
    start_wib: datetime,
    end_wib: datetime,
    language_code: str,
    service_label: str | None = None,
    slot_text: str | None = None,
    timezone_label: str | None = None,
    time_zone: str | None = None,
) -> Dict[str, Any]:
    prof = read_user_profile_from_sessions(session_id) or {}
    nick = prof.get("nickname") or ""
    email = prof.get("email") or ""
    phone = prof.get("phone") or ""
    country = prof.get("country") or ""
    region  = prof.get("region") or ""
    city    = prof.get("city") or ""
    tz_name = (time_zone or "Asia/Jakarta").strip() or "Asia/Jakarta"

    hist = read_chat_history(session_id) or []
    services = _collect_services_from_history(hist)
    chosen_service = (service_label or (services[0] if services else None))
    requested_service = chosen_service or "General Inquiry"

    summary = (f"Consultation with {nick or 'Client'} — {requested_service}"
               if (language_code or "").lower().startswith("en")
               else f"Konsultasi dengan {nick or 'Klien'} — {requested_service}")

    convo_summary = _latest_chat_summary(hist) or (
        _summarize_conversation_plain(hist, max_pairs=5) or "(no recent messages)"
    )

    desc_lines = []
    if service_label:
        desc_lines.append(f"Service: {service_label}")
    if slot_text:
        slot_line = f"Slot: {slot_text}"
        if timezone_label:
            slot_line += f" ({timezone_label})"
        desc_lines.append(slot_line)
    desc_lines.extend([
        f"Client: {nick} <{email}>  |  Phone: {phone}",
        f"Location: {city}, {region}, {country}",
        f"Requested service: {requested_service}",
        "",
        "Conversation summary:",
        convo_summary,
    ])
    description = "\n".join(desc_lines)

    calendar_id = os.getenv("CALENDAR_ID_OVERRIDE") or selected_sales_email or ""
    attendees = _build_attendees_list(user_email=email, sales_email=selected_sales_email)

    return {
        "calendarId": calendar_id,
        "summary": summary,
        "description": description,
        "start": start_wib.isoformat(),
        "end":   end_wib.isoformat(),
        "timeZone": tz_name,
        "attendees": attendees,
        "eventType": "default",
    }

#Summarize
def _summarize_desc(
    ask_llm, language_name: str, user_profile: dict,
    chat_snips: list[dict], window_text: str, related_services: list[str]
) -> str:
    try:
        prompt = render_desc_summary_prompt(
            language_name=language_name,
            user_profile=user_profile,
            chat_snippets=chat_snips,
            window_text=window_text,
            related_services=related_services,
        )
        # TODO(audit): plumb session_id
        prompt_msgs_intent_check = [SystemMessage(content=prompt)]
        with audit_llm_call(
            route="meeting_arrangement",
            stage="intent_check",
            session_id="",
            token_id=None,
            prompt=prompt_msgs_intent_check,
        ) as ctx:
            msg = ask_llm.invoke(prompt_msgs_intent_check)
            ctx.set_response_from_message(msg)
        desc = (getattr(msg, "content", "") or "").strip()
        if desc:
            return desc
    except Exception:
        pass
    # fallback kalau LLM gagal
    pieces = []
    nick = (user_profile.get("nickname") or "Client").strip()
    if user_profile.get("email"): pieces.append(f"Email {user_profile['email']}")
    if user_profile.get("phone"): pieces.append(f"Phone {user_profile['phone']}")
    contact = "; ".join(pieces)
    return f"Meeting with {nick}. Window: {window_text}. {('Contact: ' + contact) if contact else ''}".strip()

# ganti jadi seminggu kedepan
def _compose_unavailable_weekly(language_code: str,
                                nick_plain: str,
                                addr_formal: str,
                                target_date: date,
                                start_wib: datetime,
                                end_wib: datetime,
                                emails: list[str]) -> str:
    dur_min = int((end_wib - start_wib).total_seconds() // 60)
    weekly = summarize_weekly_availability(emails, target_date, dur_min, days_ahead=7, step_min=30)

    who = (addr_formal or nick_plain or "").strip()
    head = (f"{who}, jendela waktu yang diminta tidak tersedia. Berikut rekomendasi 7 hari ke depan:"
            if (language_code or "").lower().startswith("id")
            else f"{who}, the requested window isn’t available. Here are recommendations for the next 7 days:")

    # build markdown table
    lines = ["", "| Tanggal | Jam | #Sales |", "|---|---|---|"]
    for d, items in weekly.items():
        if not items:
            continue
        for it in items:
            jam = human_time_range(it["start"], it["end"])  # 13:00-14:00 WIB :contentReference[oaicite:4]{index=4}
            lines.append(f"| {human_date(d)} | {jam} | {it['count_sales']} |")  # 15 Oktober 2025, dst :contentReference[oaicite:5]{index=5}

    if len(lines) == 3:  # tidak ada satupun opsi
        tail = ("Belum ada slot yang cocok pada 7 hari ke depan. Silakan ajukan waktu lain di jam kerja."
                if (language_code or "").lower().startswith("id")
                else "No matching options in the next 7 days. Please propose another time within business hours.")
        return head + " " + tail

    prompt_tail = ("Silakan pilih salah satu opsi pada tabel di atas atau ajukan waktu lain."
                   if (language_code or "").lower().startswith("id")
                   else "Please pick one of the options above or propose another time.")
    return "\n".join([head, *lines, "", prompt_tail])

# Chat with history

def compose_meeting_reply(session_id, token_id, utilizer, user_utterance: str, instr: str, ask_llm=None):
    window = cwh.get_history_window(session_id)
    build = cwhp.build_messages_for_ma(window, user_utterance, instr, include_history_block=True)
    if ask_llm is None:
        from modules.system_detection.sd_service import BRIEF_LLM as _LLM
        ask_llm = _LLM
    prompt_msgs_slot_compose = [
        SystemMessage(content=m["content"]) if m["role"]=="system" else HumanMessage(content=m["content"])
        for m in build["messages"]
    ]
    with audit_llm_call(
        route="meeting_arrangement",
        stage="slot_compose",
        session_id=session_id,
        token_id=token_id,
        prompt=prompt_msgs_slot_compose,
    ) as ctx:
        msg = ask_llm.invoke(prompt_msgs_slot_compose)
        ctx.set_response_from_message(msg)
    answer = getattr(msg, "content", "") or ""

    return answer

# Meeting arrangement, sincronize with googlesheet
def llm_parse_day_and_slot(ask_llm, user_text: str):
    today_wib = datetime.now(WIB).date().isoformat()
    sys = SystemMessage(content=MEETING_SLOT_PARSE_SYSTEM)
    hum = HumanMessage(content=render_meeting_slot_parse_human(today_wib) + "\n\nUser: " + user_text)
    # TODO(audit): plumb session_id
    prompt_msgs_slot_compose_v2 = [sys, hum]
    with audit_llm_call(
        route="meeting_arrangement",
        stage="slot_compose_v2",
        session_id="",
        token_id=None,
        prompt=prompt_msgs_slot_compose_v2,
    ) as ctx:
        resp = ask_llm.invoke(prompt_msgs_slot_compose_v2)
        ctx.set_response_from_message(resp)
    return json.loads(getattr(resp, "content", "{}"))
