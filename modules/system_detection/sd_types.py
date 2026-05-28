# (Placeholder untuk type hints/aliases jika diperlukan)
from typing import TypedDict, List

class RetrievalHit(TypedDict):
    id: str
    doc_id: str
    chunk_index: int
    content: str