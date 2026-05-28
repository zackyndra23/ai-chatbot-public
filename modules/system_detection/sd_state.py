# system_detection/sd_state.py
from pydantic import BaseModel, Field
from typing import List, Optional

class ChatRequest(BaseModel):
    session_id: str
    question: str
    website_id: Optional[str] = None

class ChatResult(BaseModel):
    session_id: str
    route: str  # greeting | incontext | outcontext
    language_name: str
    related_services: List[str] = Field(default_factory=list)
    docs_retrieved_count: int = 0
    message: str
    prompt_applied: str | None = None