from __future__ import annotations

from typing import Literal, Optional, Dict, List, Any
from pydantic import BaseModel, Field

QuestionType = Literal["picker", "free_text", "confirm"]

# =========================
# Choice untuk picker
# =========================
class Choice(BaseModel):
    value: str
    label: str
    selected: bool = False

# =========================
# QuestionStep (INTI MASALAH)
# =========================
class QuestionStep(BaseModel):
    # identity
    id: str
    text: str

    # flow metadata
    order: Optional[int] = None
    field_name: Optional[str] = None
    is_question: bool = True

    # picker
    choices: Optional[List[Choice]] = None
    required: bool = False

    # routing
    next_if: Dict[str, str] = Field(default_factory=dict)
    default_next: Optional[str] = None

    # UI / meta
    service_label: Optional[str] = None


# =========================
# Agent Session State
# =========================
class AgentSessionState(BaseModel):
    session_id: str
    service_code: str
    service_label: str = ""
    question_id: str
    answers: Dict[str, Any] = Field(default_factory=dict)
    status: str = "ongoing"
    language_code: str = ""
    language_name: str = ""
    dual_agent_meta: Dict[str, Any] = Field(default_factory=dict)
    # Last ≤3 Sentence-1 openers used by the assistant this session.
    # Drives prompt-side ban list + post-process opener rotation.
    recent_openers: List[str] = Field(default_factory=list)

    # =========================
    # Method B extensions (Stage 2026-05-12)
    # =========================
    # `None` = unset (treated as "two_decision_tree" by dispatcher).
    # Locked at first call to _render_sa_continue_via_sd when None — env read once,
    # written to state, persisted. In-flight sessions stay on whichever method
    # they started with.
    qualification_method: Optional[Literal["two_decision_tree", "natural_qualification"]] = None

    # Per-handle_turn counter, incremented at start of each Method B turn.
    turn_index: int = 0

    # Per-min-set-field counter, frozen-not-reset semantics:
    #   filled → reset to 0
    #   target == X and still empty → increment
    #   target != X and still empty → freeze (no change)
    dry_count: Dict[str, int] = Field(default_factory=dict)

    # Fields that already got their rescue turn. Cleared on commit (success)
    # or moved to fallback_skipped_fields (rescue failed).
    rescue_attempted: List[str] = Field(default_factory=list)

    # Fields permanently skipped after rescue failed. Sales sees these in
    # lead profile as explicit "user declined to provide" signal.
    fallback_skipped_fields: List[str] = Field(default_factory=list)

    # Last intent_score emitted by Method B agent (telemetry).
    last_intent_score: Optional[str] = None

    # Turn index at which picker was last offered. Used for 2-turn cooldown.
    last_picker_offer_turn: Optional[int] = None

    # Last interest_signal emitted by Method B agent (telemetry parity with
    # last_intent_score). Stage 4.5.
    last_interest_signal: Optional[str] = None

    # 2026-05-18: MEETING_POPUP cadence tracking for Method B (mirrors
    # `dual_agent_meta["popup_shown_steps"]` used by Method A). Records the
    # `answered_count` values at which the meeting picker has already been
    # rendered — prevents re-firing the picker at the same milestone on
    # subsequent clarification turns where the count doesn't advance.
    popup_shown_counts: List[int] = Field(default_factory=list)

    # =========================
    # Stage 0 OOC additions (2026-05-13)
    # =========================
    # See docs/superpowers/specs/2026-05-13-ooc-response-engine-design.md §7.1
    ooc_excursion_count: int = Field(default=0, ge=0)
    previous_user_ooc_categories: List[str] = Field(default_factory=list)
    previous_system_meta_actions: List[str] = Field(default_factory=list)
    session_fallback_language: str = Field(default="en")
    ooc_escalation_suppression_remaining: int = Field(default=0, ge=0)