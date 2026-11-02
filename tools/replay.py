#!/usr/bin/env python3
"""Replay a saved GetSchedule response through the parser. No Home Assistant needed.

    python tools/replay.py capture.json 2026-11-02 [--me "CLABON, T"] [--appliance KT52P1]
                           [--now 2026-11-02T08:00:00Z] [--what-if "ERD/Ang"]

Accepts the raw JSON ({"d": "<table>..."}) or a bare HTML file. Prints the P1
on-the-run periods, your on-call periods, bookable windows, issues, and how often
the crew rule disagrees with Gartan's own appliance row.
"""
import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.gartan.core.model import runs_from_flags  # noqa: E402
from custom_components.gartan.core.const import ON_STATUSES  # noqa: E402
from custom_components.gartan.core.parse import parse_day  # noqa: E402
from custom_components.gartan.core.view import CoreConfig, build_view  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("file")
ap.add_argument("day")
ap.add_argument("--me", default="CLABON, T")
ap.add_argument("--appliance", default="KT52P1")
ap.add_argument("--dual", default="WARD, S")
ap.add_argument("--what-if", default="")
ap.add_argument("--now")
ap.add_argument("--tz", default="Europe/London")
a = ap.parse_args()

tz = ZoneInfo(a.tz)
raw = Path(a.file).read_text(encoding="utf-8")
try:
    raw = json.loads(raw)["d"]
except (ValueError, KeyError, TypeError):
    pass
day = parse_day(raw, date.fromisoformat(a.day), tz)
cfg = CoreConfig(a.appliance, a.me, frozenset({a.dual.upper()}), frozenset(a.what_if.split()))
now = (
    datetime.fromisoformat(a.now.replace("Z", "+00:00"))
    if a.now
    else datetime.combine(day.date, datetime.min.time(), tz).astimezone(timezone.utc)
)
v = build_view([day], cfg, {}, now)


def fmt(s, e):
    return f"{s.astimezone(tz):%H:%M}-{e.astimezone(tz):%H:%M}"


print(f"slots={len(day.slot_starts)} people={len(day.people)} "
      f"imports={[p.name for p in day.people if p.is_import]}")
print("issues:", v.issues or "none")
print("P1 on:", [fmt(*r) for r in runs_from_flags(v.timeline, [s in ON_STATUSES for s in v.p1_effective])])
if v.me_key:
    print("me on :", [fmt(*r) for r in runs_from_flags(v.timeline, v.timeline.series[v.me_key].on)])
print("bookable windows:")
for w in v.windows:
    tag = "goes on" if w.goes_on else "still short: " + ", ".join(w.missing)
    print(f"  {fmt(w.start, w.end)} ({w.minutes}m) {tag}" + (" [dual-role import assumed]" if w.needs_dual_role else ""))
print("crew-rule check:", json.dumps(v.diagnostics, indent=2))
