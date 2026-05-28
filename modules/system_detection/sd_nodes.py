# system_detection/sd_nodes.py
from typing import List
from langchain_core.documents import Document
from collections import OrderedDict
import re
from langchain_core.prompts import ChatPromptTemplate
# from langchain_core.pydantic_v1 import BaseModel, Field
from pydantic import BaseModel, Field

# ===== Retrieval =====
def retrieve_candidates(retriever, question: str) -> List[Document]:
    return retriever.invoke(question)

# ===== Grader =====
class GradeDocuments(BaseModel):
    binary_score: str = Field(description="'yes' or 'no'")

def build_grader(llm):
    system = (
        "You are a grader checking if a document is relevant to a user’s question. "
        "Be very strict. If the document has words or meanings related to the question, answer 'yes', otherwise 'no'."
    )
    grade_prompt = ChatPromptTemplate.from_messages([
        ("system", system),
        ("human", "Retrieved document:\n\n{document}\n\nUser question:\n{question}")
    ])
    structured = llm.with_structured_output(GradeDocuments)
    return grade_prompt | structured

def _grade_one_doc(
    grader,
    doc: Document,
    question: str,
    doc_index: int,
    *,
    session_id: str,
    token_id: str | None,
    model: str,
):
    """Grade a single doc + write audit row. Returns (doc, is_yes) tuple.
    Errors are caught — failing grader on one doc doesn't break the batch."""
    import time as _time
    from core.app_audit import record_llm_call

    def _is_yes(x: str) -> bool:
        return str(x or "").strip().lower().startswith("y")

    t0 = _time.perf_counter()
    err: str | None = None
    score = ""
    try:
        res = grader.invoke({"document": doc.page_content, "question": question})
        score = getattr(res, "binary_score", "") or ""
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    latency_ms = int((_time.perf_counter() - t0) * 1000)

    record_llm_call(
        route="system_detection",
        stage="doc_grader",
        session_id=session_id,
        token_id=token_id,
        prompt={"document": doc.page_content, "question": question},
        response=str(score),
        model=model,
        latency_ms=latency_ms,
        input_tokens=0,
        output_tokens=0,
        extras={"doc_index": doc_index, "structured_output": True},
        error=err,
    )

    return doc, (_is_yes(score) if err is None else False)


def grade_and_filter_yes(
    grader,
    docs: List[Document],
    question: str,
    *,
    session_id: str = "",
    token_id: str | None = None,
) -> List[Document]:
    """Grade docs in parallel via ThreadPoolExecutor.

    Each doc's grader call is independent — a per-doc LLM round-trip with
    structured-output. Sequential mode wastes wall-clock time waiting on
    network. Threading parallelizes I/O (Anthropic API), keeping the
    user-facing latency near max-of-K instead of sum-of-K.

    Order is preserved relative to input `docs` (filtering only).
    Per-doc audit rows still written (one row per call). Token count = same
    as sequential — only latency changes.
    """
    if not docs:
        return []

    from concurrent.futures import ThreadPoolExecutor
    from core.app_config import Config
    cfg = Config()
    grader_model = (cfg.GRADER_MODEL or cfg.ANTHROPIC_MODEL).strip() if hasattr(cfg, "GRADER_MODEL") else cfg.ANTHROPIC_MODEL

    # Cap workers to avoid hammering the API; default 6 is plenty for K<=10.
    import os as _os
    max_workers = min(len(docs), int(_os.getenv("DOC_GRADER_PARALLEL", "6") or 6))

    results: list[tuple[Document, bool]] = [(d, False) for d in docs]
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="doc-grader") as pool:
        futs = {
            pool.submit(
                _grade_one_doc,
                grader,
                d,
                question,
                i,
                session_id=session_id,
                token_id=token_id,
                model=grader_model,
            ): i
            for i, d in enumerate(docs)
        }
        for fut in futs:
            i = futs[fut]
            try:
                results[i] = fut.result()
            except Exception:
                # _grade_one_doc swallows already; this is paranoia.
                results[i] = (docs[i], False)

    return [d for d, is_yes in results if is_yes]

# ===== Context render =====
def render_context(docs: List[Document]) -> str:
    return "\n\n---\n\n".join(d.page_content for d in docs) if docs else ""

# ===== Related services extraction =====
SERVICE_RE = re.compile(r'^\s*S:\s*(.+?)\s*$', flags=re.MULTILINE)

def extract_service_from_doc(doc: Document):
    # 1) from metadata
    svc = (doc.metadata or {}).get("service")
    if isinstance(svc, str) and svc.strip():
        return svc.strip()
    # 2) parse "S: ..."
    m = SERVICE_RE.search(doc.page_content or "")
    return m.group(1).strip() if m else None

def extract_related_services(docs: List[Document], top_k=4, max_services=None):
    seen = OrderedDict()
    for d in docs[:top_k]:
        svc = extract_service_from_doc(d)
        if svc:
            seen[svc] = seen.get(svc, 0) + 1
    related = list(seen.keys())
    if max_services:
        related = related[:max_services]
    return related