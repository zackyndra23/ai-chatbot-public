from __future__ import annotations
from typing import List, Literal, Optional, Any, Dict

try:
    # from langchain_core.pydantic_v1 import BaseModel, Field
    from pydantic import BaseModel, Field
except Exception:
    from pydantic import BaseModel, Field


MessageType = Literal["string", "picker"]


class PickerChoice(BaseModel):
    value: str
    label: str
    selected: bool = False


class StringContent(BaseModel):
    text: str


class PickerContent(BaseModel):
    id: str
    type: MessageType
    text: str
    required: bool = False
    choices: List[PickerChoice]


class ChatMessage(BaseModel):
    type: MessageType
    content: Dict[str, Any]  # biar fleksibel (atau Union[StringContent, PickerContent])

class SummarizationMeta(BaseModel):
    summary_applied: str = "-"
    summary_input: int = 0
    summary_output: int = 0
    chat_summarization: str = "-"


class ChatTurn(BaseModel):
    ts: str
    question: str
    message: ChatMessage
    user_nick: str = ""
    prompt_applied: str = ""
    language_name: str = ""
    route: str = ""
    related_services: List[str] = []
    docs_retrieved_count: int = 0
    respond_duration: float = 0.0

    # token fields (biar kompatibel sama existing)
    input_token: int = 0
    output_token: int = 0
    input_total: Optional[int] = None
    output_total: Optional[int] = None

    summarization_meta: SummarizationMeta = Field(default_factory=SummarizationMeta)

    # extra flexible metadata
    extra: Dict[str, Any] = Field(default_factory=dict)