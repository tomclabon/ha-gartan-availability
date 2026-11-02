"""Constants for the HA-free core. No Home Assistant imports in this package."""
from __future__ import annotations

from datetime import timedelta

SLOT = timedelta(minutes=15)

# Appliance statuses, from the text at the end of each appliance cell's title,
# e.g. "KT52P1 (0000 - 0015) Available". Only these titles have been seen;
# anything else is reported as unknown (and raises an attention issue).
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

# One character per slot in the schedule sensor.
STATUS_CHAR = {
    STATUS_AVAILABLE: "A",
    STATUS_ALTERNATE: "L",
    STATUS_OFF_RUN: "O",
    STATUS_OFF_STATION: "S",
    STATUS_UNKNOWN: "?",
}
PERSON_ON, PERSON_OFF, PERSON_BOOKABLE = "1", "0", "b"

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
