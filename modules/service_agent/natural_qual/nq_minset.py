"""Method B minimum-set resolution.

Per-flow declaration of which fields constitute the "minimum to book" subset.
Used by the picker decision (step 9 of orchestrator) — picker fires when
min-set complete AND intent_score >= medium.

10 of 13 flows follow the canonical suffix convention:
    user_role       → *_user_role
    main_objective  → *_main_objective
    company_profile → *_client_company_profile (or *_company_profile naming variant)

3 flows have explicit declarations for semantic gaps audited via runtime
FLOW_REGISTRY introspection on 2026-05-12. See spec Section 4 for rationale.
"""
from __future__ import annotations
from typing import Any, Dict


# Per-flow explicit overrides. Only includes flows where the canonical suffix
# resolution would fail or pick a semantically wrong field.
MIN_SET_PER_FLOW: Dict[str, Dict[str, str]] = {
    "WBS": {
        "user_role":       "wbs_case_handlers",     # buyer-role field absent; case_handlers
                                                    # is closest decision-maker-adjacent slot
        "main_objective":  "wbs_main_objective",
        "company_profile": "wbs_company_profile",
    },
    "EBS": {
        "user_role":       "ebs_user_role",
        "main_objective":  "ebs_project_type",      # main_objective field absent; project_type
                                                    # (one-shot vs ongoing) is natural 'what' slot
        "company_profile": "ebs_company_profile",
    },
}

# Suffix priority per slot. First match wins. Used for the 11 flows not in
# MIN_SET_PER_FLOW.
_SUFFIX_PRIORITY: Dict[str, tuple] = {
    "user_role":       ("user_role",),
    "main_objective":  ("main_objective",),
    "company_profile": ("client_company_profile", "company_profile"),
}


def resolve_min_set(flow_code: str, flow: Dict[str, Any]) -> Dict[str, str]:
    """Resolve min-set field names for one service flow.

    Args:
        flow_code: e.g. "WBS", "ABMS"
        flow: FLOW_REGISTRY[flow_code] — a dict {step_id: QuestionStep}

    Returns:
        {"user_role": <field_name>, "main_objective": <field_name>,
         "company_profile": <field_name>}
        Each value is the actual field_name in this flow's answers schema.
        Falls back to "" if no match (shouldn't happen for the 13 canonical
        flows — guard for future flows being added without min-set declaration).
    """
    if flow_code in MIN_SET_PER_FLOW:
        return dict(MIN_SET_PER_FLOW[flow_code])

    # Default resolution: suffix priority over active fields
    active_fields = {
        getattr(step, "field_name", None)
        for step in flow.values()
        if getattr(step, "field_name", None)
    }

    result: Dict[str, str] = {}
    for slot, suffixes in _SUFFIX_PRIORITY.items():
        match = ""
        for suffix in suffixes:
            for f in active_fields:
                if f.endswith("_" + suffix):
                    match = f
                    break
            if match:
                break
        result[slot] = match
    return result


def is_min_set_complete(min_set: Dict[str, str], answers: Dict[str, Any]) -> bool:
    """True iff every field in min_set has a non-empty value in answers.

    Args:
        min_set: output of resolve_min_set()
        answers: state.answers dict

    Returns:
        True iff all 3 slots' field names map to a non-empty value in answers.
        Empty string, None, or missing key all count as not-filled.
    """
    for field_name in min_set.values():
        if not field_name:
            return False
        v = answers.get(field_name)
        if v is None or (isinstance(v, str) and not v.strip()):
            return False
    return True
