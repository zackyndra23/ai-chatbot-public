import os
from pathlib import Path
from langchain_chroma import Chroma
from core.app_config import Config
from .sd_policies import RETRIEVAL_K

cfg = Config()

_vectorstore = None
_retriever = None


def _bool_env(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _resolve_hf_device() -> str:
    """
    CPU-first resolution:
    - If USE_GPU is false -> cpu
    - If USE_GPU true and want cuda -> cuda only if torch.cuda.is_available()
    - If torch missing/error -> cpu
    """
    use_gpu = _bool_env("USE_GPU", "false")  # CPU-only default
    want = os.getenv("EMBEDDING_DEVICE", "cpu").strip().lower()  # cpu default

    if not use_gpu:
        return "cpu"

    if want != "cuda":
        return "cpu"

    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _build_embeddings():
    """
    Embeddings provider:
    - EMBEDDINGS_PROVIDER=openai  -> remote (no GPU usage)
    - EMBEDDINGS_PROVIDER=hf      -> local (CPU/GPU depending env)
    """
    provider = os.getenv("EMBEDDINGS_PROVIDER", "openai").strip().lower()

    if provider == "openai":
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(api_key=cfg.OPENAI_API_KEY, model=cfg.EMBED_MODEL)

    # provider == "hf"
    from langchain_community.embeddings import HuggingFaceEmbeddings

    model_name = os.getenv(
        "EMBEDDING_MODEL_NAME",
        "sentence-transformers/all-MiniLM-L6-v2"
    ).strip()

    device = _resolve_hf_device()
    batch_size = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))

    return HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={"device": device},
        encode_kwargs={"batch_size": batch_size, "normalize_embeddings": True},
    )


def bootstrap_vectorstore():
    """Load retriever dari snapshot CURRENT yang dibuat oleh vb_service."""
    global _vectorstore, _retriever

    persist_dir = cfg.VECTOR_CURRENT_SYMLINK  # titik kebenaran
    Path(persist_dir).mkdir(parents=True, exist_ok=True)

    embeddings = _build_embeddings()

    _vectorstore = Chroma(
        collection_name=cfg.CHROMA_COLLECTION,
        persist_directory=persist_dir,
        embedding_function=embeddings,
    )
    _retriever = _vectorstore.as_retriever(search_kwargs={"k": RETRIEVAL_K})


def get_retriever():
    if _retriever is None:
        bootstrap_vectorstore()
    return _retriever