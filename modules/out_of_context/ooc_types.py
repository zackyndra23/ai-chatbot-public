"""Pydantic types for the OOC (Out-of-Context) engine.

Stage 0 (2026-05-13) extension to the pre-existing module — see
docs/superpowers/specs/2026-05-13-ooc-response-engine-design.md §2.1 + §7.8.

Backward-compatibility guarantee (Approach 3 EXTEND strategy):
- Legacy `OOCLabel` (3-value Literal) preserved as alias for existing callers
- Legacy fields on `OOCDecision` / `OOCResult` preserved with defaults
- New types (`OOCContext`, `OOCAuditMetadata`, `OOCCategory`, `ShapeUsed`) added
- LEGACY_LABEL_MAP translates old → new for migrating call sites
"""
from __future__ import annotations
from typing import Literal, Optional, List, Dict, Any

from pydantic import BaseModel, Field


# ============================================================================
# Legacy types (pre-Stage-0) — preserved for backward compat
# ============================================================================

OOCLabel = Literal["freelance", "partnership", "none"]
"""Pre-Stage-0 label set. Kept for callers of `OOCService.maybe_handle()`."""


# ============================================================================
# Stage 0 additions
# ============================================================================

OOCCategory = Literal[
    "OOC-PARTNERSHIP",
    "OOC-FREELANCE",
    "OOC-MYSTERY-SHOPPER-APPLY",
    "OOC-CAREERS",
    "OOC-ADJACENT-SERVICE",
    "OOC-ADJACENT-ISO",
    "OOC-PRESS-MEDIA",
    "OOC-VENDOR-SUPPLIER",
    "OOC-COMPLAINT",
    "OOC-PERSONAL-ADVICE",
    "OOC-CHITCHAT",
    "OOC-UNCLEAR",
    "OOC-CATCHALL",
    "ESCALATION-CONSECUTIVE-OOC",
]
"""14 values: 13 user-facing OOC categories + 1 system-meta escalation label.
"13 OOC categories" in design discussion refers to user-facing only."""

ShapeUsed = Literal[
    "cold_start",
    "mid_flow_standard",
    "mid_flow_high_stakes",
    "mid_flow_pre_data",
    "escalation_handover",
]

LEGACY_LABEL_MAP: dict[str, Optional[str]] = {
    "freelance": "OOC-FREELANCE",
    "partnership": "OOC-PARTNERSHIP",
    "none": None,
}
"""Translation table for migrating legacy OOCLabel callers to OOCCategory."""


class OOCContext(BaseModel):
    """Input contract: orchestrator (Layer A) → OOCService.handle() (Layer B).

    Built by `sd_service.py` from `AgentSessionState` + per-turn detection.
    Self-contained — does not couple OOC module to AgentSessionState schema.

    See spec §2.1.1 + §7.2 for field semantics.
    """

    # User input + language resolution (per spec Q#4)
    user_text: str
    user_detected_language: str
    raw_detected_language: str
    raw_detection_confidence: float = Field(ge=0.0, le=1.0)
    session_fallback_language: str = "en"

    # SA state snapshot
    active_service: Optional[str] = None
    current_field_id: Optional[str] = None
    last_question_text: Optional[str] = None
    pre_data: bool = False
    high_stakes_intake: bool = False

    # Session-streak tracking
    previously_seen_OOC_in_session: int = Field(default=0, ge=0)
    previous_user_ooc_categories: List[str] = Field(default_factory=list)
    previous_system_meta_actions: List[str] = Field(default_factory=list)

    # Escalation suppression state
    ooc_escalation_suppression_remaining: int = Field(default=0, ge=0)


class OOCAuditMetadata(BaseModel):
    """Typed audit metadata for `query_recording.extras`.

    Replaces Dict[str, Any] per spec Refinement #4 (typed schema = forensic
    integrity). Fields named to match operator MongoDB queries in spec §9.
    """

    classifier_confidence: float = Field(ge=0.0, le=1.0)
    classifier_mode: Literal["keyword", "hybrid", "llm"]
    extracted_mention: Optional[str] = None
    extracted_hint: Optional[str] = None
    ooc_excursion_count_post: int = Field(default=0, ge=0)
    previous_categories_chain: List[str] = Field(default_factory=list)
    raw_detected_language: Optional[str] = None
    raw_detection_confidence: Optional[float] = None
    effective_language_diverged_from_raw: bool = False
    pre_data: bool = False
    high_stakes_intake: bool = False
    active_service: Optional[str] = None
    template_variant_used: Optional[str] = None
    bidi_wrap_applied: bool = False
    trigger: Optional[str] = None
    streak_length: Optional[int] = None


class OOCDecision(BaseModel):
    """Classifier output.

    Backward-compatible extension: legacy callers using `label: OOCLabel`
    continue to work when `label` is one of the legacy values; new callers
    use the OOCCategory values. Runtime values come from
    OOCCategory ∪ legacy OOCLabel; strict typing done at use sites.
    """

    yes: bool = Field(description="True if classified OOC.")
    # `label` widened from OOCLabel to str. Validate at use sites.
    label: Optional[str] = Field(default=None, description="OOCCategory or legacy OOCLabel.")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: Optional[str] = None
    classifier_mode: Literal["keyword", "hybrid", "llm"] = "hybrid"

    # Extracted variables for template rendering (Stage 0 additions)
    extracted_mention: Optional[str] = None  # for OOC-ADJACENT-SERVICE
    extracted_hint: Optional[str] = None     # polymorphic: OOC-CAREERS or OOC-COMPLAINT


class OOCResult(BaseModel):
    """Output contract from `OOCService.handle()`.

    Orchestrator owns all state mutation semantics (including
    session_fallback_language updates per T1-OOC exception per spec §7.2).
    OOCResult signals intent via `set_escalation_suppression` +
    `streak_classification` only.

    NOTE: `update_session_fallback_language` field is intentionally NOT
    present (removed during spec revision per Minor #1) — orchestrator
    decides language-state mutations based on raw_detection_confidence +
    T1-OOC cold-start exception, not based on OOCResult flags.
    """

    # === Stage 0 fields ===
    message: str = ""
    category: Optional[str] = None
    shape_used: Optional[str] = None
    language_used: Optional[str] = None
    set_escalation_suppression: bool = False
    streak_classification: Literal["user_ooc", "system_meta"] = "user_ooc"
    audit_metadata: Optional[OOCAuditMetadata] = None

    # === Legacy fields (preserved for backward-compat with maybe_handle()) ===
    triggered: bool = False
    decision: Optional[OOCDecision] = None
    route: str = "out_of_context_agent"
    prompt_applied: Optional[str] = None
    debug: Dict[str, Any] = Field(default_factory=dict)
