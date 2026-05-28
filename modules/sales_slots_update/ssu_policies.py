"""
ssu_policies.py — Policy definitions and default constants for Sales Slots Update.

Contains:
    - Canonical slot labels used across modules.
    - Default working hours for scheduler guard (WIB time).
    - Default look-ahead horizon (number of days to include in the summary).
    
These constants ensure consistent behavior between meeting arrangement
and automatic sheet updates.
"""


from datetime import time

# Canonical slot labels (urut). Pastikan konsisten dengan MA & data di Mongo.
CANONICAL_SLOTS = [
    "09:00 - 10:00",
    "10:00 - 11:00",
    "11:00 - 12:00",
    "12:00 - 13:00",
    "13:00 - 14:00",
    "14:00 - 15:00",
    "15:00 - 16:00",
    "16:00 - 17:00",
]

# Guard jam kerja WIB (default)
DEFAULT_WORK_START = time(hour=9, minute=0)
DEFAULT_WORK_END   = time(hour=17, minute=0)

# Horizon tanggal (opsional agar sheet tidak membengkak)
DEFAULT_DAYS_AHEAD = 14
