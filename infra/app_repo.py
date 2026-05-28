from types import SimpleNamespace
from modules.faq_automation.faq_repo import FAQRepo
from modules.faq_automation.faq_mongo_repo import FAQMongoRepo
from pymongo import MongoClient
from core.app_config import Config

cfg = Config()
_mongo_client = None


def build_faq_repo(cfg) -> FAQRepo:
    """Factory selecting FAQ repository implementation by `cfg.DB_BACKEND`.

    `mongo` (default) → FAQMongoRepo with per-service docs.
    `postgres` (reserved) → raises NotImplementedError.
    """
    backend = (getattr(cfg, "DB_BACKEND", "mongo") or "mongo").strip().lower()
    if backend == "mongo":
        return FAQMongoRepo(
            uri=cfg.MONGO_URI,
            dbname=cfg.MONGO_DB,
            coll_name=cfg.MONGO_FAQ_UPDATE,
            timezone=cfg.TIMEZONE,
        )
    if backend == "postgres":
        raise NotImplementedError(
            "DB_BACKEND=postgres reserved; not implemented in this stage"
        )
    raise ValueError(f"unknown DB_BACKEND={backend!r}")


def build_repos(cfg):
    """Backward-compat: returns SimpleNamespace(store=<FAQRepo>) like before.
    New code should call build_faq_repo(cfg) directly.
    """
    faq_repo = build_faq_repo(cfg)
    return SimpleNamespace(store=faq_repo)

def get_mongo_client():
    """Lazy singleton untuk koneksi Mongo"""
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = MongoClient(cfg.MONGO_URI)
    return _mongo_client[cfg.MONGO_DB]