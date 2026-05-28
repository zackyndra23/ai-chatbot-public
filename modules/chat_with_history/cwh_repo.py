from pymongo import MongoClient
from core.app_config import Config
cfg = Config()

def get_collections(app_repo):
    """
    Return (coll_history, coll_threads, coll_runlogs).
    - Jika app_repo ada & punya .mongo(), gunakan itu.
    - Kalau tidak ada, fallback langsung ke Mongo berdasar .env (MONGO_URI/MONGO_DB).
    """
    if app_repo and hasattr(app_repo, "mongo"):
        db = app_repo.mongo()
        # gunakan nama koleksi dari env untuk chat_history; threads & run_logs pakai default
        return db[cfg.CHAT_HISTORY_COLL], db.chat_threads, db.run_logs

    # Fallback tanpa app_repo:
    cli = MongoClient(cfg.MONGO_URI, connect=True)
    db = cli[cfg.MONGO_DB]
    return db[cfg.CHAT_HISTORY_COLL], db.get_collection("chat_threads"), db.get_collection("run_logs")