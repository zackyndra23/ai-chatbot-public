from __future__ import annotations

import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from core.app_config import Config
from modules.chat_payload.payload_builder import build_chat_turn_payload, build_string_message
from modules.late_response_followup.lrf_prompts import late_followup_prompt
from modules.late_response_followup.lrf_repo import LRFMongoRepo
from modules.system_detection.sd_repo import log_run

cfg = Config()


FOLLOWUP_LLM = ChatAnthropic(
    model=cfg.ANTHROPIC_MODEL,
    anthropic_api_key=cfg.ANTHROPIC_API_KEY,
    max_tokens=max(128, int(cfg.MAX_TOKENS_ASK or 256)),
    temperature=cfg.LLM_TEMPERATURE,
)


def _wib_now_iso() -> str:
    return datetime.now(ZoneInfo(cfg.TIMEZONE or "Asia/Jakarta")).isoformat()


def _normalize_text(text: str) -> str:
    return " ".join((text or "").strip().split())


def _safe_lang_name(name: str | None) -> str:
    x = (name or "").strip()
    return x or "English"


def _safe_services(services: list[str] | None) -> str:
    arr = [str(x).strip() for x in (services or []) if str(x).strip()]
    return ", ".join(arr) if arr else "(none)"


def _build_stage_instruction(candidate: dict[str, Any]) -> tuple[str, str]:
    meeting_arranged = bool(candidate.get("meeting_arranged"))
    related_services = candidate.get("last_related_services") or []
    last_route = candidate.get("last_route") or ""

    if meeting_arranged:
        stage_name = "meeting_arrangement_done"
        stage_instruction = (
            "The conversation already reached meeting arrangement. "
            "Write a polite follow-up that continues naturally from the latest discussion. "
            "Do not ask the user to book a meeting again. "
            "You may ask whether they need anything else before the meeting or whether they also want to explore a related service."
        )
        last_topic = (
            f"Meeting arrangement already happened. "
            f"Last route: {last_route}. "
            f"Relevant services: {_safe_services(related_services)}."
        )
        return stage_name, stage_instruction + f"\nLast assistant topic:\n{last_topic}"

    stage_name = "qualification_ongoing"
    stage_instruction = (
        "The user is still in the qualification/discovery stage and has not completed meeting arrangement yet. "
        "Continue naturally from the latest topic. "
        "Invite them to continue the discussion or ask about a related service. "
        "Do not push too hard and do not force a meeting unless it fits the existing context."
    )
    last_topic = (
        f"Qualification is still ongoing. "
        f"Last route: {last_route}. "
        f"Relevant services: {_safe_services(related_services)}."
    )
    return stage_name, stage_instruction + f"\nLast assistant topic:\n{last_topic}"


def _build_prompt(candidate: dict[str, Any]) -> str:
    language_name = _safe_lang_name(candidate.get("last_language_name"))
    related_services = _safe_services(candidate.get("last_related_services"))
    last_question = _normalize_text(candidate.get("last_question") or "")
    last_answer = _normalize_text(candidate.get("last_answer") or "")
    stage_name, stage_block = _build_stage_instruction(candidate)

    base = late_followup_prompt.format(
        language_name=language_name,
        related_services=related_services,
        last_topic=stage_block,
    ).strip()

    continuation_block = f"""
Conversation stage:
{stage_name}

Continue from the most recent exchange below.

Last user message:
{last_question or "-"}

Last assistant reply:
{last_answer or "-"}

Extra rules:
- The follow-up must feel like a natural continuation of the last assistant reply.
- Do not restart the conversation from zero.
- Do not repeat the same wording from the previous assistant reply.
- Keep it concise and human.
""".strip()

    return f"{base}\n\n{continuation_block}"


def _build_followup_payload(
    *,
    candidate: dict[str, Any],
    text: str,
    prompt_applied: str,
    respond_duration: float,
    input_token: int,
    output_token: int,
) -> dict[str, Any]:
    msg_obj = build_string_message(text)

    extra = {
        "system_generated": True,
        "outbound_kind": "late_response_followup",
        "source_last_chat_ts": candidate.get("last_chat_ts"),
        "source_last_route": candidate.get("last_route"),
        "meeting_arranged": bool(candidate.get("meeting_arranged")),
    }

    return build_chat_turn_payload(
        ts=_wib_now_iso(),
        question="[AUTO_LATE_RESPONSE_FOLLOWUP]",
        message=msg_obj,
        prompt_applied=prompt_applied,
        language_name=_safe_lang_name(candidate.get("last_language_name")),
        user_nick="",
        route="late_response_followup",
        related_services=candidate.get("last_related_services") or [],
        docs_retrieved_count=0,
        respond_duration=respond_duration,
        input_token=input_token,
        output_token=output_token,
        input_total=input_token,
        output_total=output_token,
        summarization_meta={
            "summary_applied": "-",
            "summary_input": 0,
            "summary_output": 0,
            "chat_summarization": "-",
        },
        extra=extra,
    )


class LateResponseFollowupService:
    def __init__(self, repo: LRFMongoRepo | None = None) -> None:
        self.repo = repo or LRFMongoRepo()

    def _eligible(self, candidate: dict[str, Any], tracked: dict[str, Any] | None) -> tuple[bool, str]:
        if not candidate.get("sessionId"):
            return False, "missing_session"

        if tracked is None:
            return True, "fresh"

        tracked_last_ts = tracked.get("last_chat_ts")
        current_last_ts = candidate.get("last_chat_ts")

        if tracked_last_ts != current_last_ts:
            return True, "new_activity"

        followup_count = int(tracked.get("followup_count") or 0)
        if followup_count >= int(cfg.LATE_RESPONDS_MAX_PER_SESSION or 1):
            return False, "max_reached"

        if tracked.get("followup_sent") is True:
            return False, "already_sent_same_last_chat"

        return True, "retry_pending"

    def generate_followup_text(self, candidate: dict[str, Any]) -> tuple[str, str, int, int, float]:
        from core.app_audit import audit_llm_call

        prompt = _build_prompt(candidate)
        prompt_msgs = [
            SystemMessage(content=prompt),
            HumanMessage(content="Generate the follow-up message now."),
        ]

        with audit_llm_call(
            route="late_response_followup",
            stage="lrf_compose",
            session_id=str(candidate.get("sessionId") or ""),
            token_id=candidate.get("tokenId"),
            prompt=prompt_msgs,
        ) as ctx:
            msg = FOLLOWUP_LLM.invoke(prompt_msgs)
            ctx.set_response_from_message(msg)

        text = _normalize_text(getattr(msg, "content", "") or "")
        return text, prompt, ctx.input_tokens, ctx.output_tokens, ctx.latency_ms / 1000.0

    def process_one(self, candidate: dict[str, Any]) -> dict[str, Any]:
        tracked = self.repo.get_followup_log(candidate["sessionId"], candidate.get("tokenId"))
        ok, reason = self._eligible(candidate, tracked)
        if not ok:
            if tracked:
                self.repo.mark_skipped(
                    session_id=candidate["sessionId"],
                    token_id=candidate.get("tokenId"),
                    reason=reason,
                )
            return {
                "sessionId": candidate["sessionId"],
                "tokenId": candidate.get("tokenId"),
                "status": "skipped",
                "reason": reason,
            }

        pending = self.repo.upsert_pending_log(candidate)

        text, prompt_applied, in_tok, out_tok, dur = self.generate_followup_text(candidate)
        payload = _build_followup_payload(
            candidate=candidate,
            text=text,
            prompt_applied=prompt_applied,
            respond_duration=dur,
            input_token=in_tok,
            output_token=out_tok,
        )

        self.repo.append_followup_to_chat_history(
            session_id=candidate["sessionId"],
            token_id=candidate.get("tokenId"),
            payload=payload,
        )

        self.repo.mark_sent(
            session_id=candidate["sessionId"],
            token_id=candidate.get("tokenId"),
            followup_text=text,
            payload=payload,
        )

        result = {
            "session_id": candidate["sessionId"],
            **payload,
        }
        log_run(candidate["sessionId"], "[AUTO_LATE_RESPONSE_FOLLOWUP]", result)

        return {
            "sessionId": candidate["sessionId"],
            "tokenId": candidate.get("tokenId"),
            "status": "sent",
            "followup_text": text,
            "followup_log_before": pending,
        }

    def run_scan(self, limit: int = 100) -> dict[str, Any]:
        if cfg.LATE_RESPONDS_FEATURE not in ("1", "true", "yes", "on"):
            return {
                "ok": True,
                "feature": "off",
                "scanned": 0,
                "sent": 0,
                "items": [],
            }

        candidates = self.repo.find_idle_candidates(limit=limit)
        items: list[dict[str, Any]] = []
        sent = 0

        for candidate in candidates:
            item = self.process_one(candidate)
            items.append(item)
            if item.get("status") == "sent":
                sent += 1

        return {
            "ok": True,
            "feature": "on",
            "scanned": len(candidates),
            "sent": sent,
            "items": items,
        }