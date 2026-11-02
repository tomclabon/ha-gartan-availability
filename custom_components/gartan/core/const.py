"""Constants for the HA-free core. No Home Assistant imports in this package."""
from __future__ import annotations

from datetime import timedelta

SLOT = timedelta(minutes=15)

# Skills (exact tokens as shown in the Gartan skills column)
IC_SKILL = "IC1"
DRIVER_SKILL = "ERD/Ang"
BA_SKILL = "BA"

# Pump crewing rule (see README: derived from sample days, verified by diagnostics)
MIN_CREW = 4
MIN_BA = 2
MIN_COMPETENT_FF = 3  # everyone counts as competent, so MIN_CREW already covers it

# Appliance statuses (from the title text of the appliance cells)
STATUS_AVAILABLE = "available"
STATUS_ALTERNATE = "alternate"
STATUS_OFF_RUN = "off_the_run"
STATUS_OFF_STATION = "off_station"
STATUS_UNKNOWN = "unknown"
ON_STATUSES = frozenset({STATUS_AVAILABLE, STATUS_ALTERNATE})
STATUS_BY_TEXT = {
    "available": STATUS_AVAILABLE,
    "alternate": STATUS_ALTERNATE,
    "off the run": STATUS_OFF_RUN,
    "off station": STATUS_OFF_STATION,
}

# Booking codes (data-codeId). Anything not listed is treated as NOT available
# and raises an attention issue.
CODES_ON = {32: "A", 35: "C"}
CODES_OFF = {
    1: "O",
    20: "U",
    31: "B",
    29: "H",
    2: "S",
    28: "E",
    13: "F",
    3: "T",
    4: "W",
    14: "L",
    19: "Y",
}
