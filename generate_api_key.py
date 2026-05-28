import hashlib, uuid
from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB = os.getenv("MONGO_DB", "rag_app2_logs")
WEBSITE_ID = os.getenv("WEBSITE_ID", "default-site")

# Koneksi MongoDB
client = MongoClient(MONGO_URI)
db = client[MONGO_DB]
keys_collection = db["api_keys"]

# Generate API key
api_key = str(uuid.uuid4())

# Simpan ke database
keys_collection.insert_one({
    "website_id": WEBSITE_ID,
    "api_key_hash": api_key,
    "status": "active"
})

print(f"Generated API key for {WEBSITE_ID}: {api_key}")