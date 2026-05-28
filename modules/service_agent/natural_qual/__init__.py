"""Natural-conversation qualification method (Stage 2026-05-12).

Method B = single-agent collector for SA qualification flows. Opt-in via
`QUALIFICATION_METHOD=natural_qualification` env knob. See
`docs/superpowers/specs/2026-05-12-qualification-method-toggle-design.md`.

Public API:
    handle_turn(state, user_message, crisp_profile, language_code, token_id=None)
"""
from modules.service_agent.natural_qual.nq_orchestrator import handle_turn

__all__ = ["handle_turn"]
