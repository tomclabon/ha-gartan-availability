"""Home Assistant constants for the Gartan integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "gartan"

CONF_BASE_URL = "base_url"
CONF_BRIGADE_ID = "brigade_id"  # discovered from the schedule page at setup
CONF_BRIGADE_NAME = "brigade_name"
CONF_APPLIANCES = "appliances"  # appliance row labels to create entities for
CONF_ME = "me"  # optional override; empty = auto-detect the logged-in user's row

TODAY_INTERVAL = timedelta(minutes=5)
WEEK_INTERVAL = timedelta(minutes=55)
WEEK_DAYS = 7
STALE_AFTER = timedelta(hours=2)
MAX_CAPTURES = 20
