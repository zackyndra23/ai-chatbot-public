from __future__ import annotations
import os, re
from datetime import datetime, date, time, timedelta, timezone
from typing import Optional, Tuple, List

WIB = timezone(timedelta(hours=7))

def _parse_hhmm(x: str) -> time:
    dt = datetime.strptime(x.strip(), "%H:%M")
    return time(dt.hour, dt.minute)

# Jam operasional dari ENV (default 09:00–17:00)
BUSINESS_START = _parse_hhmm(os.getenv("WORK_START", "09:00"))
BUSINESS_END   = _parse_hhmm(os.getenv("WORK_END", "17:00"))

DATE_RX = re.compile(
    r'\b(?P<d>\d{1,2})[\/\-\s](?P<m>\d{1,2}|[A-Za-zÀ-ÿ]{3,12})(?:[\/\-\s](?P<y>\d{4}))?\b',
    re.I
)
TIME_RANGE_RX = re.compile(r'\b(\d{1,2}:\d{2})(?:\s*[\-–]\s*(\d{1,2}:\d{2}))?\b')
MONTHS = {
    # EN short
    "jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
    # EN long
    "january":1,"february":2,"march":3,"april":4,"june":6,"july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
    # ID long
    "januari":1,"februari":2,"maret":3,"april":4,"mei":5,"juni":6,"juli":7,"agustus":8,"september":9,"oktober":10,"november":11,"desember":12,
    # ID short umum
    "mei":5,"agu":8,"okt":10,"des":12,"sept":9
}

MONTHS_ID_FULL = [
    "", "Januari","Februari","Maret","April","Mei","Juni",
    "Juli","Agustus","September","Oktober","November","Desember"
]

def iso_wib(dt: datetime) -> str:
    """ISO-8601 dengan offset +07:00 (WIB)."""
    return dt.astimezone(WIB).isoformat()

def parse_date(text: str, today: Optional[date] = None) -> Optional[date]:
    if not today:
        today = datetime.now(WIB).date()
    m = DATE_RX.search(text or "")
    if not m:
        return None
    dd = int(m.group("d"))
    mm_raw = (m.group("m") or "").strip().lower().strip(".")
    yyyy = int(m.group("y")) if m.group("y") else today.year

    if mm_raw.isdigit():
        mm = int(mm_raw)
    else:
        # coba full key dulu, kalau tidak ada coba 3 huruf awal
        mm = MONTHS.get(mm_raw) or MONTHS.get(mm_raw[:3])
    if not mm or not (1 <= mm <= 12):
        return None
    try:
        return date(yyyy, mm, dd)
    except ValueError:
        return None

def _parse_hm(s: str) -> Optional[time]:
    try:
        dt = datetime.strptime(s.strip(), "%H:%M")
        return time(dt.hour, dt.minute)
    except Exception:
        return None

def parse_time_range(text: str, default_duration_min: int = 30) -> Tuple[Optional[time], Optional[time], int]:
    """Bebas: single time (auto +default) atau rentang HH:MM–HH:MM."""
    m = TIME_RANGE_RX.search(text or "")
    if not m: return None, None, default_duration_min
    start = _parse_hm(m.group(1))
    if not start: return None, None, default_duration_min
    if m.group(2):
        end = _parse_hm(m.group(2))
        dur = None if not end else int((datetime.combine(date.min,end) - datetime.combine(date.min,start)).seconds/60)
        return start, end, dur if dur is not None else default_duration_min
    end_dt = (datetime.combine(date.min, start) + timedelta(minutes=default_duration_min)).time()
    return start, end_dt, default_duration_min

def to_wib(dt: datetime) -> datetime:
    return dt.replace(tzinfo=WIB)

def violates_business_rules(start_dt: datetime, end_dt: datetime) -> tuple[bool, str]:
    """
    Tanpa lunch: cek bahwa window berada di dalam jam kerja & start < end.
    Normalisasi ke WIB lalu bandingkan sebagai time naive (tanpa tzinfo).
    """
    s = start_dt.astimezone(WIB).time().replace(tzinfo=None)
    e = end_dt.astimezone(WIB).time().replace(tzinfo=None)

    ok = (BUSINESS_START <= s <= BUSINESS_END) and \
         (BUSINESS_START <= e <= BUSINESS_END) and \
         (s < e)

    return (not ok, "outside_hours" if not ok else "ok")

def label_slot(start_dt: datetime, end_dt: datetime) -> str:
    return f"{start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}"

def human_date(dt: date) -> str:
    # 15 Oktober 2025
    return f"{dt.day} {MONTHS_ID_FULL[dt.month]} {dt.year}"

def human_time_range(start_dt: datetime, end_dt: datetime) -> str:
    # gunakan tanda minus '-'
    return f"{start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')} WIB"

def business_hours_text() -> str:
    return f"{BUSINESS_START.strftime('%H:%M')}–{BUSINESS_END.strftime('%H:%M')} WIB"

# --- sederhanakan example_lines: 1 contoh saja, full-ID ---
def example_lines(language_code: str, today: Optional[date] = None) -> list[str]:
    if not today:
        today = datetime.now(WIB).date()
    besok = today + timedelta(days=1)
    # contoh 1: bulan Indonesia lengkap 11:00-12:00
    ex1 = f"{human_date(besok)} 11:00-12:00 WIB"
    # contoh 2: numeric DD-MM-YYYY 14:30-15:30
    ex2 = f"{besok.day:02d}-{besok.month:02d}-{besok.year} 14:00-15:00 WIB"
    # satu kalimat saja (biar tidak dobel/berulang)
    return [f"Please follow this example: {ex1} or {ex2}."]
    
# --- di bawah helper yang sudah ada ---
def duration_minutes(start_dt: datetime, end_dt: datetime) -> int:
    return int((end_dt - start_dt).total_seconds() // 60)

def suggest_within_business(day: date, start_wib: datetime, end_wib: datetime, k: int = 2):
    """
    Balikkan sampai k saran (start,end) yang:
    - durasi sama seperti permintaan user
    - ditarik masuk ke WORK_START–WORK_END kalau di luar pagar
    Heuristik sederhana & deterministik.
    """
    from datetime import datetime as _dt, timedelta as _td
    dur = max(15, duration_minutes(start_wib, end_wib))   # minimal 15 menit biar masuk akal

    day_start = _dt(day.year, day.month, day.day, BUSINESS_START.hour, BUSINESS_START.minute, tzinfo=WIB)
    day_end   = _dt(day.year, day.month, day.day, BUSINESS_END.hour,   BUSINESS_END.minute,   tzinfo=WIB)

    # Kalau durasi lebih panjang dari rentang operasional, potong ke DUR= (WORK_END - WORK_START)
    max_dur = duration_minutes(day_start, day_end)
    if dur > max_dur:
        dur = max_dur

    out = []

    # Saran-1: "clamp" permintaan ke dalam pagar
    s1 = max(day_start, min(start_wib, day_end - _td(minutes=dur)))
    e1 = s1 + _td(minutes=dur)
    out.append((s1, e1))

    if k <= 1:
        return out

    # Saran-2: geser sedikit (±30m atau pindah ke tengah hari jika tabrakan batas)
    step = _td(minutes=30 if dur >= 30 else 15)
    s2 = s1 + step
    if s2 + _td(minutes=dur) > day_end:
        # kalau lewat, geser ke tengah jam kerja (mis. 14:00)
        mid_h = 14 if BUSINESS_START.hour <= 14 <= BUSINESS_END.hour else (BUSINESS_START.hour + BUSINESS_END.hour) // 2
        s2 = _dt(day.year, day.month, day.day, mid_h, 0, tzinfo=WIB)
    s2 = max(day_start, min(s2, day_end - _td(minutes=dur)))
    e2 = s2 + _td(minutes=dur)
    if (s2, e2) != (s1, e1):
        out.append((s2, e2))

    return out[:k]

# ----- Schedule Recommendation system
def merge_free_intervals(slots: list[dict]) -> list[tuple[datetime, datetime]]:
    """Gabungkan slot 'free' yang tumpang tindih agar jadi interval kontigu."""
    iv = [(s["start"], s["end"]) for s in slots if s.get("status") == "free"]
    if not iv:
        return []
    iv.sort(key=lambda x: x[0])
    merged = [list(iv[0])]
    for s, e in iv[1:]:
        last_s, last_e = merged[-1]
        if s <= last_e:
            if e > last_e:
                merged[-1][1] = e
        else:
            merged.append([s, e])
    return [(a, b) for a, b in merged]

def interval_covers(window_s: datetime, window_e: datetime,
                    free_intervals: list[tuple[datetime, datetime]]) -> bool:
    """True jika ada interval free yang sepenuhnya menutupi [window_s, window_e]."""
    for s, e in free_intervals:
        if s <= window_s and e >= window_e:
            return True
    return False

def windows_from_intervals(free_intervals: list[tuple[datetime, datetime]],
                           duration_min: int,
                           step_min: int = 15) -> list[tuple[datetime, datetime]]:
    """Buat kandidat window berdurasi sama dengan step geser (default 15 menit)."""
    out = []
    dur = timedelta(minutes=max(15, duration_min))
    step = timedelta(minutes=step_min)
    for s, e in free_intervals:
        cur = s
        while cur + dur <= e:
            out.append((cur, cur + dur))
            cur += step
    return out

def nearest_k(windows: list[tuple[datetime, datetime]],
              target_start: datetime,
              k: int = 3) -> list[tuple[datetime, datetime]]:
    """Ambil k window terdekat terhadap start yang diminta user (abs distance)."""
    scored = [ (abs((ws - target_start).total_seconds()), ws, we) for ws, we in windows ]
    scored.sort(key=lambda x: x[0])
    return [ (ws, we) for _, ws, we in scored[:k] ]

def dedup_windows(windows: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    seen = set()
    out = []
    for s,e in sorted(windows, key=lambda x: (x[0], x[1])):
        key = (s.isoformat(), e.isoformat())
        if key not in seen:
            seen.add(key); out.append((s,e))
    return out