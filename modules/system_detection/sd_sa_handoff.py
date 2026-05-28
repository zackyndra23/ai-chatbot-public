from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple

from modules.service_agent.sa_policies import (
    SERVICE_VALUE_CODE_MAP,
    SERVICE_LABEL_CODE_MAP,
    VALUE_TO_FLOW_CODE,
    SERVICE_AGENT_PREFIX,
)

# NOTE:
# - related_services dari SD biasanya berupa label (contoh: "Skip Tracing", "Due Diligence", dst)
# - Kita map -> value_code (snake-ish) -> flow_code (EBS/DDC/...)
# - Kalau len==1: direct start flow
# - Kalau len>1: required picker (choices = related_services saja)


@dataclass
class SAHandoffDecision:
    mode: str  # "none" | "direct" | "confirm"
    # direct:
    service_label: Optional[str] = None
    service_value: Optional[str] = None         # e.g. "skip_tracing"
    flow_code: Optional[str] = None             # e.g. "SKT"
    # confirm:
    choices: Optional[List[Dict[str, Any]]] = None  # [{"label":..., "value":...}, ...]
    required: bool = False

    # for logging/sheet
    multiple_choice_labels: Optional[List[str]] = None


def _uniq_preserve(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in items or []:
        s = (x or "").strip()
        if not s:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    return out


def _label_to_value_code(label: str) -> Optional[str]:
    """
    Map label -> value_code via SERVICE_VALUE_CODE_MAP
    Fallback: try reverse map from SERVICE_LABEL_CODE_MAP (if label equals canonical).
    """
    if not label:
        return None
    label = label.strip()

    # primary map (your current design)
    v = SERVICE_VALUE_CODE_MAP.get(label)
    if v:
        return v

    # fallback: label might already be the canonical label from SERVICE_LABEL_CODE_MAP
    # Build reverse: canonical_label -> value_code
    rev = {v2: k2 for k2, v2 in (SERVICE_LABEL_CODE_MAP or {}).items()}
    maybe = rev.get(label)
    if maybe:
        return maybe

    return None


def _value_to_flow(value_code: str) -> Optional[str]:
    """
    Map value_code -> flow_code using VALUE_TO_FLOW_CODE.
    However your VALUE_TO_FLOW_CODE currently maps some human keys -> flow.
    So we do a tolerant mapping:
      - try direct (if you already keep it)
      - else, try lookup via SERVICE_LABEL_CODE_MAP/value normalization
    """
    if not value_code:
        return None

    # common case: you store VALUE_TO_FLOW_CODE with value_code keys
    direct = VALUE_TO_FLOW_CODE.get(value_code)
    if direct:
        return direct

    # if VALUE_TO_FLOW_CODE uses short keys (EBS, DD, etc) - skip
    # we can try to map via SERVICE_LABEL_CODE_MAP -> label -> then search in VALUE_TO_FLOW_CODE
    canon_label = SERVICE_LABEL_CODE_MAP.get(value_code)
    if canon_label:
        alt = VALUE_TO_FLOW_CODE.get(canon_label)
        if alt:
            return alt

    return None


def decide_sa_handoff(related_services: List[str]) -> SAHandoffDecision:
    raw = _uniq_preserve(related_services or [])
    _general_tokens = {"general", "general service", "general_service"}
    has_general = any((x or "").strip().lower() in _general_tokens for x in raw)
    # Specific-service labels (General stripped out).
    labels = [x for x in raw if (x or "").strip().lower() not in _general_tokens]

    if not labels:
        return SAHandoffDecision(mode="none")

    # Auto-handoff only when the query points unambiguously at ONE specific
    # service AND General was NOT also present. If General co-occurs, the
    # user's intent is broad ("what services do you offer"-ish) — show a
    # picker so the user can confirm/choose, not auto-start a flow.
    if len(labels) == 1 and not has_general:
        label = labels[0]
        value_code = _label_to_value_code(label)
        if not value_code:
            return SAHandoffDecision(mode="none")

        flow_code = _value_to_flow(value_code)
        if not flow_code:
            return SAHandoffDecision(mode="none")

        return SAHandoffDecision(
            mode="direct",
            service_label=SERVICE_LABEL_CODE_MAP.get(value_code, label),
            service_value=value_code,
            flow_code=flow_code,
            multiple_choice_labels=None,
            required=False,
        )

    # Either >1 specific services, OR 1 specific + General → confirm picker (required)
    choices = []
    picked_labels = []
    for lb in labels:
        value_code = _label_to_value_code(lb)
        if not value_code:
            continue
        # build picker value that SD will detect later
        picker_value = f"{SERVICE_AGENT_PREFIX}{value_code}"
        label_final = SERVICE_LABEL_CODE_MAP.get(value_code, lb)
        choices.append({"label": label_final, "value": picker_value, "selected": False})
        picked_labels.append(label_final)

    if not choices:
        return SAHandoffDecision(mode="none")

    return SAHandoffDecision(
        mode="confirm",
        choices=choices,
        required=True,
        multiple_choice_labels=picked_labels,
    )


def compose_confirm_question(language_code: str) -> str:
    lc = (language_code or "").lower()
    if lc.startswith("id"):
        return "Yuk, biar saya bantu lebih akurat — layanan apa yang sedang Anda cari?"
    return "To help you better, which service are you exploring today?"