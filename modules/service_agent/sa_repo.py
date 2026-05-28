from typing import Optional
from .sa_types import AgentSessionState

class ServiceAgentRepo:
    def __init__(self, mongo_client):
        self._col = mongo_client["rag_assistant_chatbot"]["service_agent_state"]

    def get_state(self, session_id: str) -> Optional[AgentSessionState]:
        doc = self._col.find_one({"session_id": session_id})
        return AgentSessionState(**doc) if doc else None

    def upsert_state(self, state: AgentSessionState) -> None:
        self._col.update_one(
            {"session_id": state.session_id},
            {"$set": state.model_dump()},
            upsert=True,
        )

    def delete_state(self, session_id: str) -> None:
        self._col.delete_one({"session_id": session_id})