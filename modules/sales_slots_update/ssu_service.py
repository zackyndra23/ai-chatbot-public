"""
ssu_service.py — Core business logic for the Sales Slots Update system.

Responsibilities:
    - Instantiate and orchestrate Mongo → Matrix → Google Sheet pipeline.
    - Compute matrix of available sales counts per slot and date.
    - Handle Google Sheets authentication via service account.
    - Create or update the target worksheet with formatted data.
    - Write LAST UPDATED info to a dedicated META sheet.
    - Log run results to Mongo (append or upsert-last), selectable via SSU_LOG_MODE.
    - Provide run_once() as the main callable method for one complete update cycle.

This is the heart of the SSU module — it ensures up-to-date visibility
of all sales availability schedules inside Google Sheets.
"""

from __future__ import annotations
from typing import List
from datetime import datetime, timedelta

import gspread
from google.oauth2.service_account import Credentials

from .ssu_repo import SalesSlotsRepo
from .ssu_utils import read_env_config, parse_hhmm, now_wib, WIB

import json
import os
from pathlib import Path

SCOPE = ["https://www.googleapis.com/auth/spreadsheets"]

class SalesSlotsUpdateService:
    def __init__(self):
        cfg = read_env_config()
        self.cfg = cfg
        self.repo = SalesSlotsRepo(
            cfg["MONGO_URI"],
            cfg["MONGO_DB"],
            cfg["SALES_SLOTS_COLL"],
            log_collection=cfg.get("SSU_LOG_COLL"),
        )
        # accept either GOOGLE_SERVICE_ACCOUNT or GOOGLE_SA_PATH
        sa_path = cfg.get("GOOGLE_SERVICE_ACCOUNT") or cfg.get("GOOGLE_SA_PATH")
        self.gc = self._init_gspread(sa_path)

        # open 2 worksheets dalam 1 Spreadsheet ID yang sama
        sheet_id = cfg["SALES_SHEET_ID"]
        self.ws = self._open_worksheet(sheet_id, cfg["SALES_SHEET_NAME"])               
        self.ws_indv = self._open_worksheet(sheet_id, cfg["INDV_SALES_SHEET_NAME"])      
        # cache log mode once
        self._log_mode = str(cfg.get("SSU_LOG_MODE", "upsert")).lower()
        

    # def _init_gspread(self, sa_path: str):
    #     creds = Credentials.from_service_account_file(sa_path, scopes=SCOPE)
    #     return gspread.authorize(creds)

    def _init_gspread(self, sa_raw: str):
        if not sa_raw:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT is empty")
        sa_raw = sa_raw.strip()
        # JSON inline
        if sa_raw.lstrip().startswith("{"):
            try:
                info = json.loads(sa_raw)
            except Exception as e:
                raise RuntimeError(f"Invalid GOOGLE_SERVICE_ACCOUNT JSON: {e}")
            creds = Credentials.from_service_account_info(info, scopes=SCOPE)
            return gspread.authorize(creds)
        # Path file
        p = Path(sa_raw)
        if not p.is_absolute():
            # coba relatif ke CWD dan project root
            candidates = [
                Path(sa_raw),
                Path.cwd() / sa_raw,
                Path(__file__).resolve().parents[2] / sa_raw,           # project root heuristic
                Path(__file__).resolve().parents[2] / "secrets" / "sa.json",
            ]
            for c in candidates:
                if c.exists():
                    p = c
                    break
        if not p.exists():
            raise RuntimeError(f"Service account file not found: {sa_raw}")
        creds = Credentials.from_service_account_file(str(p), scopes=SCOPE)
        return gspread.authorize(creds)

    def _open_worksheet(self, sheet_id: str, sheet_name: str):
        sh = self.gc.open_by_key(sheet_id)
        try:
            return sh.worksheet(sheet_name)
        except gspread.WorksheetNotFound:
            return sh.add_worksheet(title=sheet_name, rows="200", cols="30")

    def compute_window(self):
        days_ahead = int(self.cfg["SSU_DAYS_AHEAD"])
        # Window: today WIB 00:00 → today+days_ahead 00:00 (UTC boundary-safe)
        today_wib = now_wib().date()
        start_wib = datetime.combine(today_wib, datetime.min.time(), tzinfo=WIB)
        end_wib = start_wib + timedelta(days=days_ahead+1)  # +1 agar kolom besok juga aman
        # ke UTC untuk query Mongo
        start_utc = start_wib.astimezone(tz=None)
        end_utc = end_wib.astimezone(tz=None)
        return start_utc, end_utc

    def build_matrix(self):
        start_utc, end_utc = self.compute_window()
        return self.repo.build_matrix_counts(start_utc, end_utc)

    def write_matrix_to_sheet(self, rows: List[str], cols: List[str], matrix):
        """
        Layout:
          A1 = "Slot"
          B1.. = tanggal (YYYY-MM-DD)
          A2.. = slot labels
          data[i][j] = count
        """
        # Header
        header = ["Slot", *cols]
        data = []
        for slot in rows:
            row_vals = [slot]
            for c in cols:
                row_vals.append(matrix[(slot, c)])
            data.append(row_vals)

        # Clear dan tulis ulang (idempotent & sederhana)
        self.ws.clear()
        # Update batch
        self.ws.update("A1", [header] + data)

        # Freeze header & kolom pertama
        self.ws.freeze(rows=1, cols=1)

        # Number format: semua kolom angka menjadi INTEGER
        try:
            fmt = {
                "numberFormat": {"type": "NUMBER", "pattern": "0"}
            }
            # Terapkan mulai dari kolom 2 s/d akhir
            ncols = len(header)
            if ncols > 1:
                rng = gspread.utils.rowcol_to_a1(2, 2) + ":" + gspread.utils.rowcol_to_a1(len(data)+1, ncols)
                self.ws.format(rng, fmt)
        except Exception:
            # Format optional; jangan gagalkan job
            pass

    def write_individual_matrix_to_sheet(self, rows, cols, matrix):
        """
        Layout:
          A1 = "Sales / Slot"
          B1.. = tanggal (YYYY-MM-DD)
          A2.. = "email — slot"
          data[i][j] = 0/1
        """
        if not self.ws_indv:
            return  # tidak di-config, lewati

        header = ["Sales / Slot", *cols]
        data = []
        for (email, slot) in rows:
            label = f"{email} — {slot}"
            row_vals = [label]
            for c in cols:
                row_vals.append(matrix[(email, slot, c)])
            data.append(row_vals)

        self.ws_indv.clear()
        self.ws_indv.update("A1", [header] + data)
        self.ws_indv.freeze(rows=1, cols=1)

        try:
            fmt = {"numberFormat": {"type": "NUMBER", "pattern": "0"}}
            ncols = len(header)
            if ncols > 1:
                rng = gspread.utils.rowcol_to_a1(2, 2) + ":" + gspread.utils.rowcol_to_a1(len(data)+1, ncols)
                self.ws_indv.format(rng, fmt)
        except Exception:
            pass

    # API publik utama
    def run_once(self) -> dict:
        started = datetime.utcnow()
        try:
            ws = parse_hhmm(self.cfg["WORK_START"])
            we = parse_hhmm(self.cfg["WORK_END"])
            t = now_wib().time()
            within_hours = (t >= ws) and (t <= we)
        except Exception:
            within_hours = True

        try:
            # 1) Matriks agregat (count per slot × tanggal)
            rows, cols, matrix = self.build_matrix()
            cols = cols or []
            self.write_matrix_to_sheet(rows, cols, matrix)

            # 2) Matriks individual (0/1 per (salesEmail, slot) × tanggal)
            start_utc, end_utc = self.compute_window()
            indv_rows, indv_cols, indv_matrix = self.repo.build_individual_matrix(start_utc, end_utc)

            # Samakan urutan kolom dengan sheet agregat (biar konsisten)
            if cols:
                indv_cols = cols
            else:
                indv_cols = indv_cols  # kalau agregat kosong, pakai milik individual

            self.write_individual_matrix_to_sheet(indv_rows, indv_cols, indv_matrix)

            duration_ms = int((datetime.utcnow() - started).total_seconds() * 1000)
            log_doc = {
                "status": "ok",
                "rows": len(rows),
                "cols": len(cols),
                "duration_ms": duration_ms,
                "window_days": int(self.cfg["SSU_DAYS_AHEAD"]),
                "slots_update_duration": int(self.cfg["SLOTS_UPDATE_DURATION"]),
                "within_work_hours": within_hours,
                "feature_on": bool(self.cfg["SSU_FEATURE_ON"]),
                "sheet_id": self.cfg["SALES_SHEET_ID"],
                "sheet_name": self.cfg["SALES_SHEET_NAME"],
                "indv_sheet_name": self.cfg.get("INDV_SALES_SHEET_NAME"),
                "last_run_wib": now_wib().isoformat(),
            }
            if self._log_mode == "upsert":
                self.repo.log_upsert_last(log_doc)
            else:
                self.repo.log_append(log_doc)

            return {
                "rows": len(rows),
                "cols": len(cols),
                "last_run_wib": now_wib().isoformat(),
                "duration_ms": duration_ms,
            }

        except Exception as e:
            duration_ms = int((datetime.utcnow() - started).total_seconds() * 1000)
            err_doc = {
                "status": "error",
                "error": str(e),
                "duration_ms": duration_ms,
                "window_days": int(self.cfg["SSU_DAYS_AHEAD"]),
                "slots_update_duration": int(self.cfg["SLOTS_UPDATE_DURATION"]),
                "within_work_hours": within_hours,
                "feature_on": bool(self.cfg["SSU_FEATURE_ON"]),
                "sheet_id": self.cfg["SALES_SHEET_ID"],
                "sheet_name": self.cfg["SALES_SHEET_NAME"],
                "indv_sheet_name": self.cfg.get("INDV_SALES_SHEET_NAME"),
                "last_run_wib": now_wib().isoformat(),
            }
            try:
                if self._log_mode == "upsert":
                    self.repo.log_upsert_last(err_doc)
                else:
                    self.repo.log_append(err_doc)
            except Exception:
                pass
            raise