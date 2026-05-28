from __future__ import annotations
from typing import Iterable, List, Tuple, Optional, Dict
import re
import textwrap
import json
import os
from pathlib import Path
import unicodedata


# === service_id slug generation ===
def make_service_id(name: str) -> str:
    """Convert raw sheet-tab title to URL-safe stable slug.

    Rules: ASCII-fold (NFKD) -> lowercase -> non-alnum -> "-" -> collapse repeats -> strip "-".
    Raises ValueError if the result is empty.

    Examples:
        "Whistleblowing Hotline"        -> "whistleblowing-system"
        "Service & Audit"              -> "service-audit"
        "Café Survey"                  -> "cafe-survey"
        "FAQ for Vertex AI Metabot"    -> "faq-for-vertex-ai-metabot"
    """
    if not name or not name.strip():
        raise ValueError("service name is empty")
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    lowered = folded.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered)
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug:
        raise ValueError(f"slug is empty for service name: {name!r}")
    return slug


def _check_collisions(services: list[tuple[str, str]]) -> None:
    """Raise ValueError if two services produce the same service_id.

    services: list of (service_id, service_name) pairs.

    Example error message: "service_id collisions detected: {'market-survey': ['Market Research', 'market research']}"
    """
    from collections import defaultdict
    by_id: dict[str, list[str]] = defaultdict(list)
    for sid, sname in services:
        by_id[sid].append(sname)
    collisions = {sid: names for sid, names in by_id.items() if len(names) > 1}
    if collisions:
        raise ValueError(f"service_id collisions detected: {dict(collisions)}")


# === Google Sheets auth (service account) ===
from google.oauth2.service_account import Credentials
import gspread

from core.app_config import Config
cfg = Config()
gc = gspread.authorize(cfg.build_google_credentials())  # read or write scopes sesuai kebutuhan

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

def _resolve_sa_path(raw: str | None) -> Optional[str]:
    """
    Cari file service account secara fleksibel:
      - absolute path
      - relative ke project root
      - relative ke CWD
      - fallback: <project_root>/secrets/sa.json
    """
    if not raw:
        return None
    prj = Path(__file__).resolve().parents[3]  # .../rag_chatbot_v01/ (kira2)
    cand: list[Path] = []
    p = Path(raw)
    if p.is_absolute():
        cand.append(p)
    else:
        cand += [
            (prj / raw).resolve(),
            (Path.cwd() / raw).resolve(),
            (prj / "secrets" / "sa.json").resolve(),
        ]
    for c in cand:
        if c.exists():
            return str(c)
    return None

def _get_gspread_client(sa_raw: str) -> gspread.Client:
    """
    Buat gspread client dari service account:
      - Jika sa_raw diawali '{' → JSON inline (from_service_account_info)
      - Jika bukan → dianggap path file (from_service_account_file) dgn resolver
    """
    if not sa_raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT is empty")

    sa_raw = sa_raw.strip()
    if sa_raw.lstrip().startswith("{"):            # JSON inline
        try:
            info = json.loads(sa_raw)
        except Exception as e:
            raise RuntimeError(f"Invalid GOOGLE_SERVICE_ACCOUNT JSON: {e}")
        creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
        return gspread.authorize(creds)

    # Path file
    cred_path = _resolve_sa_path(sa_raw)
    if not cred_path:
        raise RuntimeError(f"Service account file not found: {sa_raw}")
    creds = Credentials.from_service_account_file(cred_path, scopes=_SCOPES)
    return gspread.authorize(creds)

# === Sheet reader (deteksi kolom Q/A dari header) ===
_QUESTION_HEADERS = {"q", "question", "pertanyaan", "faq"}
_ANSWER_HEADERS   = {"a", "answer", "jawaban"}

def _normalize(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").strip().lower())

def _find_columns(header_row: List[str]) -> Tuple[int, int]:
    """
    Temukan index kolom Q dan A dari header baris pertama.
    Fallback: (0, 1) jika tak ditemukan.
    """
    q_idx = a_idx = None
    for i, h in enumerate(header_row):
        hnorm = _normalize(h)
        if q_idx is None and hnorm in _QUESTION_HEADERS:
            q_idx = i
        if a_idx is None and hnorm in _ANSWER_HEADERS:
            a_idx = i
    if q_idx is None: q_idx = 0
    if a_idx is None: a_idx = 1 if len(header_row) > 1 else 0
    return q_idx, a_idx

def _read_sheet(client: gspread.Client, sheet_id: str, include_sheets: Optional[Iterable[str]] = None
               ) -> List[Tuple[str, List[Tuple[str, str]]]]:
    """
    Return: List[(sheet_title, [(q, a), ...])].
    Hanya sheet yang ada datanya (minimal satu baris Q/A).
    """
    sh = client.open_by_key(sheet_id)
    out: List[Tuple[str, List[Tuple[str, str]]]] = []
    for ws in sh.worksheets():
        if include_sheets and ws.title not in include_sheets:
            continue
        rows = ws.get_all_values()
        if not rows:
            continue
        q_idx, a_idx = _find_columns(rows[0])
        qa_pairs: List[Tuple[str, str]] = []
        for r in rows[1:]:
            if not any(r):  # skip baris kosong total
                continue
            q = (r[q_idx] if q_idx < len(r) else "").strip()
            a = (r[a_idx] if a_idx < len(r) else "").strip()
            if q or a:
                qa_pairs.append((q, a))
        if qa_pairs:
            out.append((ws.title, qa_pairs))
    return out

# === Formatter S/Q/A (gabungkan semua sheet) ===
def _to_txt(title: str, data: List[Tuple[str, List[Tuple[str, str]]]], wrap_width: int = 0) -> str:
    lines: List[str] = [title.strip(), ""]
    """
    data: [(sheet_name, [(q, a), ...]), ...]
    Output: judul polos (tanpa '# ') + satu baris kosong,
            lalu blok S/Q/A untuk seluruh sheet.
    """

    for sheet_name, pairs in data:
        for q, a in pairs:
            if wrap_width and wrap_width > 0:
                if q: q = "\n".join(textwrap.wrap(q, width=wrap_width))
                if a: a = "\n".join(textwrap.wrap(a, width=wrap_width))
            lines.append(f"S: {sheet_name}")
            lines.append(f"Q: {q or ''}")
            lines.append(f"A: {a or ''}")
            lines.append("")  # spacer antar QA
        lines.append("")      # spacer antar sheet

    return "\n".join(lines).strip() + "\n"


def _to_txt_single_service(
    sheet_name: str,
    qa_pairs: List[Tuple[str, str]],
    wrap_width: int = 0,
) -> str:
    """Build the S/Q/A blob for a SINGLE sheet tab (one service).

    Equivalent to _to_txt but restricted to one (sheet_name, qa_pairs) entry.
    Returned text is suitable for `_chunk_text_qa` to parse into chunks
    that all carry `service == sheet_name`.
    """
    lines: List[str] = []
    for q, a in qa_pairs:
        if wrap_width and wrap_width > 0:
            if q:
                q = "\n".join(textwrap.wrap(q, width=wrap_width))
            if a:
                a = "\n".join(textwrap.wrap(a, width=wrap_width))
        lines.append(f"S: {sheet_name}")
        lines.append(f"Q: {q or ''}")
        lines.append(f"A: {a or ''}")
        lines.append("")
    return "\n".join(lines).strip() + ("\n" if lines else "")


# === Chunker S/Q/A → potongan per QA ===
def _chunk_text_qa(raw_text: str) -> List[Dict]:
    """
    Parse blok S/Q/A menjadi potongan per QA.
    Setiap chunk memuat: service (S), Q, dan A (multi-line boleh).
    """
    chunks: List[Dict] = []
    service = None
    q = None
    a_lines: List[str] = []
    idx = 0

    def flush():
        nonlocal idx, q, a_lines, service
        if q is None:
            return
        a = "\n".join(a_lines).strip()
        chunks.append({
            "chunk_index": idx,
            "service": service,
            "text": f"S: {service}\nQ: {q}\nA: {a}"
        })
        idx += 1

    for raw in raw_text.splitlines():
        line = raw.strip()
        if line.startswith("S:"):
            # tutup QA sebelumnya jika ada Q aktif
            if q is not None:
                flush()
                q, a_lines = None, []
            service = line[2:].strip()
        elif line.startswith("Q:"):
            if q is not None:
                flush()
            q = line[2:].strip()
            a_lines = []
        elif line.startswith("A:"):
            a_lines = [line[2:].strip()]
        else:
            if q is not None:
                a_lines.append(line)

    if q is not None:
        flush()

    return chunks

def _normalize_chunks_ensure_sqa(chunks: List[Dict]) -> List[Dict]:
    out = []
    for ch in chunks:
        service = ch.get("service") or "General"
        text = ch.get("text") or ""
        # Jika belum mengandung pola S: di awal, rakit ulang
        if not text.startswith("S:"):
            q = ""
            a = ""
            # fallback ekstraksi sederhana dari ch.get("q"), ch.get("a") jika ada
            if "q" in ch and "a" in ch:
                q, a = ch["q"], ch["a"]
                text = f"S: {service}\nQ: {q}\nA: {a}".strip()
            else:
                # minimal tetap prefix S: agar retriever menyimpan konteks service
                text = f"S: {service}\n{text}".strip()
        out.append({**ch, "service": service, "text": text})
    return out

# === API publik yang dipanggil Service ===
def build_text(cfg) -> str:
    """
    1) Auth SA → gspread
    2) Baca sheet (opsional filter include_sheets)
    3) Gabungkan menjadi blok S/Q/A
    """
    client = _get_gspread_client(cfg.CREDS_PATH)
    data = _read_sheet(client, cfg.SHEET_ID, cfg.INCLUDE_SHEETS or None)
    if not data:
        raise RuntimeError("Tidak ada data terbaca dari Google Sheet.")
    return _to_txt(cfg.OUTPUT_TITLE, data, wrap_width=cfg.WRAP_WIDTH)

def chunk(raw_text: str) -> List[Dict]:
    return _chunk_text_qa(raw_text)

def save_latest(store, txt: str, chunks: List[Dict]) -> Dict:
    return store.save_latest(full_text=txt, chunks=chunks)


from dataclasses import dataclass, field


@dataclass
class ServiceBundle:
    """One Sheet tab → one bundle. Used as input to FAQRepo.upsert_service."""
    service_id: str
    service_name: str
    text: str
    chunks: List[Dict] = field(default_factory=list)


def build_service_bundles(cfg) -> List[ServiceBundle]:
    """Read Sheet, split per-tab into ServiceBundles. Detects slug collisions
    BEFORE any downstream processing (raises ValueError if any).

    Each bundle's `chunks` are normalized via `_normalize_chunks_ensure_sqa`
    so they all carry the correct `service` field.

    Replaces the old single-blob flow (`build_text` → `chunk` → save_latest).
    """
    client = _get_gspread_client(cfg.CREDS_PATH)
    data = _read_sheet(client, cfg.SHEET_ID, cfg.INCLUDE_SHEETS or None)
    if not data:
        raise RuntimeError("Tidak ada data terbaca dari Google Sheet.")

    # Collision check BEFORE any per-bundle work
    pairs = [(make_service_id(name), name) for name, _ in data]
    _check_collisions(pairs)

    bundles: List[ServiceBundle] = []
    for sheet_name, qa_pairs in data:
        svc_id = make_service_id(sheet_name)
        svc_text = _to_txt_single_service(sheet_name, qa_pairs, wrap_width=cfg.WRAP_WIDTH)
        svc_chunks = _normalize_chunks_ensure_sqa(_chunk_text_qa(svc_text))
        bundles.append(ServiceBundle(
            service_id=svc_id,
            service_name=sheet_name,
            text=svc_text,
            chunks=svc_chunks,
        ))
    return bundles