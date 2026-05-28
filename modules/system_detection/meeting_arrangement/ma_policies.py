import re

# ==== Triggers (copy dari versi kamu saat ini) ====
MEETING_COMMAND_RX = re.compile(
    r"""
    ^\s*
    (?:
        (?P<emoji>📅|🗓️)(?:\s*(?P<args_emoji>[:\-]\s*.*))?
      |
        (?P<prefix>[\/!#])?\s*
        (?P<cmd>
            m|meet|mtg|appt|meeting
            |jadwal|jadwalin|temu|janji(?:_|\s*)temu|rapat
            |temujanji|mesyuarat|janji(?:_|\s*)temu
            |rdv|reunion|réunion|rendez(?:\-|\s*)vous
            |นัด|นัดหมาย|ประชุม|ตาราง
            |termin|besprechung|sitzung
            |встреча|совещание|митинг
        )
        (?:\s*(?P<args_cmd>[:\-]\s*.*))?
    )
    \s*$
    """, re.I | re.U | re.VERBOSE
)

_MEETING_CMD_CANON = {
    "m":"meeting","meet":"meeting","mtg":"meeting","appt":"meeting","meeting":"meeting",
    "jadwal":"meeting","jadwalin":"meeting","temu":"meeting","janji temu":"meeting","janji_temu":"meeting","rapat":"meeting",
    "temujanji":"meeting","mesyuarat":"meeting",
    "rdv":"meeting","reunion":"meeting","réunion":"meeting","rendez-vous":"meeting","rendez vous":"meeting",
    "นัด":"meeting","นัดหมาย":"meeting","ประชุม":"meeting","ตาราง":"meeting",
    "termin":"meeting","besprechung":"meeting","sitzung":"meeting",
    "встреча":"meeting","совещание":"meeting","митинг":"meeting",
    "📅":"meeting","🗓️":"meeting",
}

# ==== Keyword intent (copy versi kamu yang lengkap multilingual) ====
from modules.system_detection.sd_policies import MEETING_KEYWORDS_RX  # reuse yang sudah ada

def parse_meeting_command(text: str):
    if not text: return False, None
    m = MEETING_COMMAND_RX.search(text)
    if not m: return False, None
    emoji = m.group("emoji")
    if emoji:
        args = (m.group("args_emoji") or "").lstrip(":-").strip()
        return True, {"trigger_type":"emoji","cmd_raw":emoji,"cmd_normalized":_MEETING_CMD_CANON.get(emoji,"meeting"),"args":args}
    cmd_raw = (m.group("cmd") or "").strip()
    key = cmd_raw.lower()
    if key in ("rendez vous","rendez  vous"): key = "rendez vous"
    if key in ("janji_temu",): key = "janji temu"
    args = (m.group("args_cmd") or "").lstrip(":-").strip()
    return True, {"trigger_type":"command","cmd_raw":cmd_raw,"cmd_normalized":_MEETING_CMD_CANON.get(key,"meeting"),"args":args}

def detect_meeting_intent(text: str) -> tuple[bool,str]:
    t = (text or "").strip()
    if not t: return False, "none"
    if MEETING_COMMAND_RX.search(t): return True, "command"
    if MEETING_KEYWORDS_RX.search(t): return True, "keyword"
    return False, "none"