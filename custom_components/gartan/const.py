"""Home Assistant constants for the Gartan integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "gartan"

CONF_BASE_URL = "base_url"
CONF_BRIGADE_ID = "brigade_id"
CONF_BRIGADE_NAME = "brigade_name"
CONF_ME = "me"
CONF_APPLIANCE = "appliance"
CONF_SLUG = "appliance_slug"
CONF_MY_LABEL = "my_label"
CONF_DUAL_ROLE = "dual_role_people"
CONF_DISPLAY_NAMES = "display_names"
CONF_WHAT_IF = "what_if_skills"

DEFAULT_BASE_URL = "https://gartanlive.dwfire.org.uk"
DEFAULT_BRIGADE_ID = 2
DEFAULT_BRIGADE_NAME = "KT52 Cricklade"
DEFAULT_ME = "CLABON, T"
DEFAULT_APPLIANCE = "KT52P1"
DEFAULT_SLUG = "52p1"
DEFAULT_MY_LABEL = "Tom"
DEFAULT_DUAL_ROLE = "WARD, S"

TODAY_INTERVAL = timedelta(minutes=5)
WEEK_INTERVAL = timedelta(minutes=55)
WEEK_DAYS = 7
STALE_AFTER = timedelta(hours=2)
MAX_CAPTURES = 20
