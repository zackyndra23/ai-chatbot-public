import logging, sys, json, os
import datetime
from pymongo import MongoClient



class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)

def setup_logging():
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

_LOGGING_READY = False

def get_logger(name: str = "rag_chatbot"):
    """
    Return a configured logger. Safe to call many times.
    """
    global _LOGGING_READY
    if not _LOGGING_READY:
        setup_logging()
        _LOGGING_READY = True
    return logging.getLogger(name)

class MeetingLogger:
    def __init__(self, mongo_uri, db_name):
        self.cli = MongoClient(mongo_uri)
        self.col = self.cli[db_name]["meeting_logs"]
        # indeks berguna
        self.col.create_index([("sessionId", 1), ("tokenId", 1), ("ts", -1)])

    def log_meeting_event(self, session_id, token_id, phase, data):
        doc = {
            "sessionId": session_id,
            "tokenId": token_id,
            "phase": phase,               # parse | business_check | proposal | selection | booking | fallback
            "data": data,                 # bebas – dict
            "ts": datetime.datetime.utcnow().isoformat() + "Z"
        }
        self.col.insert_one(doc)

