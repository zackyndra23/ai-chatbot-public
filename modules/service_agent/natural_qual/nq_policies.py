"""Method B policies — rescue templates, picker decision, dry_count update."""
from __future__ import annotations
from typing import Dict, List, Optional, Tuple


# DEPRECATED 2026-05-13 (Task 16): rescue soft-bridge migrated to centralized i18n
# loader. See `modules/i18n/strings/{lang}.yaml::natural_qual.rescue_soft_bridge`.
# Kept as runtime fallback in case i18n loader is unavailable. To be removed in Task 19.
# Reference: docs/superpowers/specs/2026-05-13-ooc-response-engine-design.md §4.6 Step 5.
RESCUE_SOFT_BRIDGE: Dict[str, str] = {
    "en": "To keep this moving, let me ask directly — {q}",
    "id": "Biar saya bisa lanjut bantu, boleh saya konfirmasi langsung — {q}",
    "ms": "Untuk saya bantu seterusnya, boleh saya tanya secara langsung — {q}",
    "th": "เพื่อให้ดำเนินการต่อได้ ขออนุญาตถามตรง ๆ — {q}",
    "vi": "Để tiếp tục, cho phép tôi hỏi trực tiếp — {q}",
    "da": "For at komme videre, lad mig spørge direkte — {q}",
    "de": "Um voranzukommen, lassen Sie mich direkt fragen — {q}",
    "es": "Para avanzar, permítame preguntarle directamente — {q}",
    "fr": "Pour avancer, permettez-moi de demander directement — {q}",
    "it": "Per procedere, mi permetta di chiederLe direttamente — {q}",
    "ja": "進めるために、直接お伺いさせてください — {q}",
    "pt": "Para prosseguir, permita-me perguntar diretamente — {q}",
    "ru": "Чтобы продвинуться дальше, позвольте спросить напрямую — {q}",
    "zh": "为了继续协助您,请允许我直接询问 — {q}",
}


def render_rescue_message(language_code: str, decision_tree_text: str) -> str:
    """Render the rescue soft-bridge in the requested language.

    `language_code` is normalized (case-insensitive prefix-match — e.g. "id-ID"
    → "id"). Unknown / unsupported language → fall back to English template.

    Task 16 (2026-05-13): primary path reads from i18n loader. Legacy
    `RESCUE_SOFT_BRIDGE` dict kept as defensive fallback during Phase 0.
    """
    lc = (language_code or "").strip().lower()[:2] or "en"

    # Primary path: i18n loader (Task 16)
    try:
        from modules.i18n import t
        return t("natural_qual.rescue_soft_bridge", lc, q=decision_tree_text)
    except Exception:
        # Legacy fallback (DEPRECATED — Task 19 deletes the dict)
        template = RESCUE_SOFT_BRIDGE.get(lc, RESCUE_SOFT_BRIDGE["en"])
        return template.format(q=decision_tree_text)


def update_dry_count(
    current: Dict[str, int],
    min_set_fields: List[str],
    answers: Dict[str, str],
    target_field: Optional[str],
) -> Dict[str, int]:
    """Apply frozen-not-reset semantics to dry_count for all min-set fields.

    Per spec (Fine-tune A):
        if answers[X] != "" → dry_count[X] = 0          (progress = reset)
        elif target_field == X → dry_count[X] += 1       (dry = increment)
        else (target != X, still empty) → freeze         (no change)

    Returns a NEW dict (callers responsible for assigning back to state).
    """
    new = dict(current)
    for fname in min_set_fields:
        if not fname:
            continue
        val = answers.get(fname, "")
        if isinstance(val, str) and val.strip():
            new[fname] = 0
        elif target_field == fname:
            new[fname] = new.get(fname, 0) + 1
        # else: freeze (no change)
    return new


def compute_picker_decision(
    *,
    keyword_fires: bool,
    keyword_kind: Optional[str],         # "explicit" | "implicit" | None
    min_set_complete: bool,
    intent_score: str,                   # "low" | "medium" | "high"
    turn_index: int,
    last_picker_offer_turn: Optional[int],
    cooldown_turns: int = 2,
) -> Tuple[bool, str]:
    """Decide whether to offer the meeting picker this turn.

    Returns (should_offer, reason_code).

    Reason codes:
        keyword_explicit       — generic English keyword fired
        keyword_implicit       — language-specific keyword fired
        min_set_intent_medium  — min_set complete, intent_score=medium, cooldown_ok
        min_set_intent_high    — min_set complete, intent_score=high, cooldown_ok
        cooldown_blocked       — would have fired but cooldown active
        none                   — no offer this turn
    """
    # Keyword path bypasses cooldown by formula structure
    if keyword_fires:
        if keyword_kind == "explicit":
            return True, "keyword_explicit"
        return True, "keyword_implicit"

    # Min-set + intent path requires cooldown_ok
    intent_satisfies = intent_score in ("medium", "high")
    if not (min_set_complete and intent_satisfies):
        return False, "none"

    cooldown_ok = (
        last_picker_offer_turn is None
        or (turn_index - last_picker_offer_turn) >= cooldown_turns
    )
    if not cooldown_ok:
        return False, "cooldown_blocked"

    return True, f"min_set_intent_{intent_score}"
