#!/usr/bin/env python3
"""Replay a saved GetSchedule response through the parser. No Home Assistant needed.

    python tools/replay.py capture.json 2026-11-02 [--me "SURNAME, I"] [--now 2026-11-02T08:00:00Z]
                           [--export]

Accepts the raw JSON ({"d": "<table>..."}) or a bare HTML file. Prints each
appliance's on-the-run periods, your on-call periods, who is on at --now, any
issues, and (with --export) the schedule sensor's attributes.
"""
import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.gartan_availability.core.const import ON_STATUSES  # noqa: E402
from custom_components.gartan_availability.core.model import runs_from_flags  # noqa: E402
from custom_components.gartan_availability.core.parse import parse_day  # noqa: E402
from custom_components.gartan_availability.core.view import (  # noqa: E402
    CoreConfig,
    build_view,
    people_on,
    schedule_export,
)

ap = argparse.ArgumentParser()
ap.add_argument("file")
ap.add_argument("day")
ap.add_argument("--me", default="", help="default: auto-detect")
ap.add_argument("--now", help="default: local midnight of the day")
ap.add_argument("--tz", default="Europe/London")
ap.add_argument("--export", action="store_true", help="print the schedule sensor attributes")
a = ap.parse_args()

tz = ZoneInfo(a.tz)
raw = Path(a.file).read_text(encoding="utf-8")
try:
    raw = json.loads(raw)["d"]
except (ValueError, KeyError, TypeError):
    pass
day = parse_day(raw, date.fromisoformat(a.day), tz)
now = (
    datetime.fromisoformat(a.now.replace("Z", "+00:00"))
    if a.now
    else datetime.combine(day.date, datetime.min.time(), tz).astimezone(timezone.utc)
)
v = build_view([day], CoreConfig(a.me), {}, now)


def fmt(s, e):
    return f"{s.astimezone(tz):%H:%M}-{e.astimezone(tz):%H:%M}"


print(f"slots={len(day.slot_starts)} people={len(day.people)} me={v.me_key} "
      f"imports={[p.name for p in day.people if p.is_import]}")
print("issues:", v.issues or "none")
for label, app in v.appliances.items():
    runs = runs_from_flags(v.timeline, [s in ON_STATUSES for s in app.effective])
    print(f"{label} on the run:", [fmt(*r) for r in runs])
if v.me_key:
    print("me on call:", [fmt(*r) for r in runs_from_flags(v.timeline, v.timeline.series[v.me_key].on)])
print(f"on at {now.astimezone(tz):%H:%M}:", [p["name"] for p in people_on(v, now)])
if a.export:
    print(json.dumps(schedule_export(v), indent=1))
