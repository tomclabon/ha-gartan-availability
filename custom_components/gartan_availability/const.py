"""Home Assistant constants for the Gartan integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "gartan_availability"

CONF_BASE_URL = "base_url"
CONF_BRIGADE_ID = "brigade_id"  # discovered from the schedule page at setup
CONF_BRIGADE_NAME = "brigade_name"
CONF_APPLIANCES = "appliances"  # appliance row labels to create entities for
CONF_ME = "me"  # optional override; empty = auto-detect the logged-in user's row
CONF_HISTORY_YEARS = "history_years"  # how far back to load history (0 = off)
CONF_EBID = "employee_brigade_id"  # optional override for the employee view id

DEFAULT_HISTORY_YEARS = 5
HISTORY_REQUEST_GAP = 2.5  # seconds between history requests
HISTORY_RETRY = 300  # seconds to wait after a failed history request
HISTORY_REFRESH_DAYS = 14  # re-fetched nightly to catch late corrections
HISTORY_REFRESH_WEEKS = 4
HISTORY_EMPTY_STOP = 8  # empty fortnights in a row = before you started

# Refresh settings: defaults; changeable at runtime via number entities
TODAY_INTERVAL = timedelta(minutes=5)
WEEK_INTERVAL = timedelta(minutes=60)
TODAY_INTERVAL_MIN, TODAY_INTERVAL_MAX = 2, 60  # minutes
WEEK_INTERVAL_MIN, WEEK_INTERVAL_MAX = 15, 360  # minutes
HISTORY_GAP_MIN, HISTORY_GAP_MAX = 1.0, 60.0  # seconds
WEEK_DAYS = 7
STALE_AFTER = timedelta(hours=2)  # minimum; grows with the week interval (x2)
TODAY_STALE_AFTER = timedelta(minutes=15)  # minimum; grows with the today interval (x3)
MAX_CAPTURES = 20
