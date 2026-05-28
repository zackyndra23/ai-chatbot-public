"""
ssu_repo.py — MongoDB repository and aggregation logic.

Responsibilities:
    - Connect to the target MongoDB collection (sales slots).
    - Query distinct dates within a range.
    - Aggregate available slot counts per date and slot label.
    - Return data structures ready for sheet formatting.

This layer isolates all database access so higher-level services remain
purely business-oriented and easily testable.
"""

from __future__ import annotations
from datetime import datetime
from typing import Dict, List, Tuple, Set
from pymongo import MongoClient, ASCENDING, DESCENDING
from bson.son import SON

from .ssu_policies import CANONICAL_SLOTS
from .ssu_utils import WIB

class SalesSlotsRepo:
    def __init__(self, uri: str, db: str, collection: str, log_collection: str | None = None):
        self.client = MongoClient(uri)
        self.col = self.client[db][collection]
        # Optional log collection (for run history / last status)
        self.log_col = self.client[db][log_collection] if log_collection else None
        if self.log_col is not None:
            # helpful indexes
            try:
                self.log_col.create_index([("created_at", DESCENDING)], background=True)
                self.log_col.create_index([("status", ASCENDING), ("created_at", DESCENDING)], background=True)
            except Exception:
                pass

    def distinct_dates_in_range(self, start: datetime, end: datetime) -> List[datetime]:
        """
        Ambil daftar tanggal unik (UTC) di rentang [start, end).
        """
        cursor = self.col.aggregate([
            {"$match": {"date": {"$gte": start, "$lt": end}}},
            {"$group": {"_id": "$date"}},
            {"$sort": SON([("_id", 1)])}
        ])
        return [doc["_id"] for doc in cursor]

    def build_matrix_counts(
        self, start: datetime, end: datetime
    ) -> Tuple[List[str], List[str], Dict[Tuple[str, str], int]]:
        """
        Return:
          - rows = slot labels (CANONICAL_SLOTS)
          - cols = list tanggal (YYYY-MM-DD, WIB)
          - matrix dict: key (slot_label, col_date_str) -> count sales available
        """
        rows = list(CANONICAL_SLOTS)
        # Tarik semua doc dalam rentang
        docs = list(self.col.find({"date": {"$gte": start, "$lt": end}}))

        # Siapkan kolom (tanggal) menurut data yang ada
        unique_dates_wib: List[str] = []
        seen: Set[str] = set()
        for d in sorted({doc["date"] for doc in docs}):
            # representasi kolom pakai tanggal WIB agar konsisten dengan user
            d_wib = d.astimezone(WIB)
            key = d_wib.strftime("%Y-%m-%d")
            if key not in seen:
                seen.add(key)
                unique_dates_wib.append(key)

        # Hitung count per (slot, tanggal_wib)
        matrix: Dict[Tuple[str, str], int] = {}
        # (slot, tanggal) -> set of salesEmail agar distinct
        pair_to_sales: Dict[Tuple[str, str], Set[str]] = {}

        for doc in docs:
            sales = doc.get("salesEmail")
            slots = (doc.get("slots") or {})
            d_wib = doc["date"].astimezone(WIB).strftime("%Y-%m-%d")

            # Weekend/dayoff: slots == {} -> semua 0, tidak menambah apapun
            for slot in CANONICAL_SLOTS:
                st = slots.get(slot)
                if st and st.get("available") is True:
                    pair = (slot, d_wib)
                    if pair not in pair_to_sales:
                        pair_to_sales[pair] = set()
                    pair_to_sales[pair].add(sales)

        for pair, sset in pair_to_sales.items():
            matrix[pair] = len(sset)

        # Pastikan semua cell terdefinisi (jadi nol kalau tidak ada)
        for slot in rows:
            for col in unique_dates_wib:
                matrix.setdefault((slot, col), 0)

        return rows, unique_dates_wib, matrix
    
    # Pembuatan fungsi baru untuk individual availability reports
    def build_individual_matrix(
        self, start: datetime, end: datetime
    ) -> Tuple[List[tuple], List[str], Dict[tuple, int]]:
        """
        Rows: list of (salesEmail, slot_label)
        Cols: list tanggal (YYYY-MM-DD, WIB)
        Matrix: key (salesEmail, slot_label, col_date_str) -> 0/1 (available?)
        """
        docs = list(self.col.find({"date": {"$gte": start, "$lt": end}}))

        # Kumpulkan tanggal kolom (WIB)
        unique_dates_wib: List[str] = []
        seen_dates: Set[str] = set()
        for d in sorted({doc["date"] for doc in docs}):
            d_wib = d.astimezone(WIB).strftime("%Y-%m-%d")
            if d_wib not in seen_dates:
                seen_dates.add(d_wib)
                unique_dates_wib.append(d_wib)

        # Kumpulkan distinct sales dalam window
        sales_order: List[str] = []
        seen_sales: Set[str] = set()
        for doc in docs:
            s = (doc.get("salesEmail") or "").strip()
            if s and s not in seen_sales:
                seen_sales.add(s)
                sales_order.append(s)

        # Susun rows: urut per sales lalu per slot kanonik
        rows: List[tuple] = []
        for s in sorted(sales_order):
            for slot in CANONICAL_SLOTS:
                rows.append((s, slot))

        # Bangun matrix 0/1
        matrix: Dict[tuple, int] = {}
        # Inisialisasi 0 untuk semua kombinasi
        for (s, slot) in rows:
            for col in unique_dates_wib:
                matrix[(s, slot, col)] = 0

        # Isi 1 jika available=True
        for doc in docs:
            s = (doc.get("salesEmail") or "").strip()
            if not s:
                continue
            slots = (doc.get("slots") or {})
            d_wib = doc["date"].astimezone(WIB).strftime("%Y-%m-%d")
            for slot in CANONICAL_SLOTS:
                st = slots.get(slot)
                if st and (st.get("available") is True) and (st.get("booked") is False):
                    key = (s, slot, d_wib)
                    if key in matrix:
                        matrix[key] = 1

        return rows, unique_dates_wib, matrix 
    
    # ---------------------------
    # Logging utilities (optional)
    # ---------------------------
    def log_append(self, doc: dict) -> str | None:
        """Append a run log (history mode)."""
        if self.log_col is None:
            return None
        from datetime import timezone
        doc.setdefault("created_at", datetime.now(timezone.utc))
        res = self.log_col.insert_one(doc)
        return str(res.inserted_id)

    def log_upsert_last(self, doc: dict) -> None:
        """Overwrite a single fixed document (last status mode)."""
        if self.log_col is None:
            return
        from datetime import timezone
        doc.setdefault("updated_at", datetime.now(timezone.utc))
        self.log_col.update_one({"_id": "last_update"}, {"$set": doc}, upsert=True)

    def log_fetch_recent(self, limit: int = 50) -> list[dict]:
        """Fetch recent run logs (history mode)."""
        if self.log_col is None:
            return []
        cur = self.log_col.find({}).sort("created_at", DESCENDING).limit(int(limit))
        return list(cur)