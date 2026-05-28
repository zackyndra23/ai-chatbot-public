from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from .payload_types import (
    ChatMessage, PickerChoice, SummarizationMeta
)

WIB = timezone(timedelta(hours=7))

def now_wib_iso() -> str:
    return datetime.now(WIB).isoformat()

def build_string_message(
        text: str, 
        *, 
        message_id: Optional[str] = None,
        choices: list[str] | None = None,
        required: bool | None = None,
    ) -> ChatMessage:
    """
    StringTypePayload:
      { id, type: "string", text }
    Dibungkus ke ChatMessage:
      { type: "string", content: {...} }
    """
    mid = message_id or f"m-{uuid.uuid4().hex[:8]}"
    return ChatMessage(
        type="string",
        content={
            "id": mid,
            "text": text,
            "choices": choices,
            "required": required,
        }
    )

def build_picker_message(
    text: str,
    choices: List[dict],
    *,
    required: bool = False,
    picker_id: Optional[str] = None,
) -> ChatMessage:
    cid = picker_id or f"q-{uuid.uuid4().hex[:8]}"
    norm = []
    for c in choices:
        norm.append(PickerChoice(
            value=str(c["value"]),
            label=str(c["label"]),
            selected=bool(c.get("selected", False)),
        ))

    return ChatMessage(
        type="picker",
        content={
            "id": cid,
            "text": text,
            "required": required,
            "choices": [x.dict() for x in norm],
        }
    )

def build_lockpicker_message(
    text: str,
    choices: List[dict],
    *,
    required: bool = True,
    picker_id: Optional[str] = None,
) -> ChatMessage:
    cid = picker_id or f"q-{uuid.uuid4().hex[:8]}"
    norm = []
    for c in choices:
        norm.append(PickerChoice(
            value=str(c["value"]),
            label=str(c["label"]),
            selected=bool(c.get("selected", False)),
        ))

    return ChatMessage(
        type="picker",
        content={
            "id": cid,
            "text": text,
            "required": required,
            "choices": [x.dict() for x in norm],
        }
    )

def default_summarization_meta(summary_prompt: str = "-") -> SummarizationMeta:
    return SummarizationMeta(
        summary_applied=summary_prompt or "-",
        summary_input=0,
        summary_output=0,
        chat_summarization="-",
    )

def build_chat_turn_payload(
    *,
    question: str,
    message,
    route: str,
    language_name: str,
    user_nick: str = "",
    prompt_applied: str = "",
    related_services=None,
    docs_retrieved_count: int = 0,
    respond_duration: float = 0.0,
    input_token: int = 0,
    output_token: int = 0,
    input_total=None,
    output_total=None,
    summarization_meta=None,
    extra=None,
    ts: str | None = None,
    choices: list[str] | None = None,
    required: bool | None = None,
) -> dict:
    # normalize summarization_meta
    if summarization_meta is None:
        sm = default_summarization_meta()
    elif isinstance(summarization_meta, dict):
        sm = SummarizationMeta(**summarization_meta)
    else:
        sm = summarization_meta  # assume SummarizationMeta

    return {
        "ts": ts or now_wib_iso(),  # <--- USE OVERRIDE
        "question": question,
        "message": message.dict(),
        "user_nick": user_nick or "",
        "prompt_applied": prompt_applied or "",
        "language_name": language_name or "",
        "route": route or "",
        "related_services": related_services or [],
        "docs_retrieved_count": int(docs_retrieved_count or 0),
        "respond_duration": float(respond_duration or 0.0),
        "input_token": int(input_token or 0),
        "output_token": int(output_token or 0),
        "input_total": input_total,
        "output_total": output_total,
        "summarization_meta": sm.dict(),  # <--- ALWAYS NESTED
        "extra": extra or {},
    }