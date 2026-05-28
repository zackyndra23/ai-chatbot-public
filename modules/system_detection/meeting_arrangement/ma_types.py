from __future__ import annotations
from typing import TypedDict, Literal, List, Optional
from datetime import datetime, date

Status = Literal["free", "booked", "busy"]

class Slot(TypedDict):
    start: datetime       # tz-aware (WIB)
    end: datetime         # tz-aware (WIB)
    status: Status        # "free" | "booked" | "busy"
    label: str            # "HH:MM - HH:MM"

class Candidate(TypedDict):
    email: str
    booked: int
    has_cover: bool
    slots: List[Slot]

class ParseResult(TypedDict):
    ok: bool
    reason: str                    # "ok"|"no_date"|"bad_range"|"violates_lunch"|"outside_hours"
    target_date: Optional[date]
    start_wib: Optional[datetime]
    end_wib: Optional[datetime]
    duration_min: Optional[int]