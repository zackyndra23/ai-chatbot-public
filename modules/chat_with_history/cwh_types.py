from typing import List, Dict, TypedDict, Optional

class HistoryTurn(TypedDict):
    role: str
    content: str

class HistoryWindow(TypedDict):
    summary: str
    tail: List[HistoryTurn]

class BuildResult(TypedDict):
    messages: List[Dict[str, str]]
    used_history_turns: int
    truncated: bool

class AppendResult(TypedDict):
    ok: bool