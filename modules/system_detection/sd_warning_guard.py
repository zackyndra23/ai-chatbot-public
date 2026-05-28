"""Post-process appended warning for qualification disengagement.

Fires at each escalation tick (every 2 cumulative invalids, driven by the
`warnings_shown` counter in `dual_agent_meta`). Appends a soft warning block
to the assistant's reply, separated by a blank line (`\n\n`) so the user
sees it as an escalation signal distinct from the main qualification reply.

The warning text is translated into the user's target language via a small
LLM call (the same `BRIEF_LLM` the main path uses) so it sounds natural in
each language. Falls back to English on any LLM failure.

Design: takes the LLM as a parameter to avoid a circular import and to keep
`sd_service.py` in charge of LLM configuration.
"""
from __future__ import annotations

from langchain_core.messages import SystemMessage, HumanMessage

# Base English template — intentionally soft + non-judgmental. Phrased as
# the assistant's uncertainty (my questions may not have been clear) rather
# than pointing at the user's answers. Keep it short so the LLM can
# translate it naturally without padding.
_BASE_EN_WARNING = (
    "If any of my recent questions weren't quite clear, please feel free to "
    "ask. And if you'd like to share a bit more about what matters most for "
    "your situation, it will help me recommend the right approach."
)


def _translate_warning(llm, language_code: str, language_name: str) -> str:
    """Translate `_BASE_EN_WARNING` into `language_name` via a single LLM call.

    Returns the English base on: empty/English language_code, LLM failure,
    or empty translation result. The translator is instructed to keep a
    soft, warm, non-judgmental tone — matching the sales-consultant voice
    used elsewhere in qualification prompts.
    """
    lc = (language_code or "").strip().lower()
    if not lc or lc.startswith("en"):
        return _BASE_EN_WARNING

    target = (language_name or language_code).strip() or language_code
    try:
        from core.app_audit import audit_llm_call
        system = (
            f"You are a translator. Translate the user's message into {target} "
            "with a SOFT, WARM, non-judgmental tone — as a sales consultant "
            "would speak. Keep the length similar to the original. Do NOT add "
            "greetings, signatures, or explanations — return ONLY the "
            "translated text, nothing else."
        )
        prompt_msgs = [
            SystemMessage(content=system),
            HumanMessage(content=_BASE_EN_WARNING),
        ]
        with audit_llm_call(
            route="system_detection",
            stage="warning_translate",
            session_id="",          # not available in this helper; see note
            token_id=None,
            prompt=prompt_msgs,
            extras={"language_code": language_code, "language_name": language_name},
        ) as ctx:
            msg = llm.invoke(prompt_msgs)
            ctx.set_response_from_message(msg)
        translated = (getattr(msg, "content", "") or "").strip()
        return translated or _BASE_EN_WARNING
    except Exception:
        return _BASE_EN_WARNING


def append_invalid_warning(
    text: str,
    *,
    llm,
    language_code: str,
    language_name: str,
) -> str:
    """Append the translated invalid-count warning to ``text``.

    Separator is a blank line (``\n\n``) so the user sees the warning as a
    distinct block rather than a continuation of the main reply.
    """
    warning = _translate_warning(llm, language_code, language_name)
    base = (text or "").rstrip()
    return f"{base}\n\n{warning}" if base else warning
