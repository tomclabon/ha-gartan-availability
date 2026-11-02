"""Derived view: effective appliance status (call-out handling), your row, and the
raw schedule export. No station-specific crewing rules live here."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .const import (
    ON_STATUSES,
    PERSON_BOOKABLE,
    PERSON_OFF,
    PERSON_ON,
    SLOT,
    STATUS_CHAR,
    STATUS_OFF_STATION,
    STATUS_UNKNOWN,
)
from .model import Timeline, build_timeline
from .parse import DaySchedule


@dataclass(frozen=True)
class CoreConfig:
    my_name: str = ""  # override; empty = auto-detect the logged-in user's row


@dataclass
class ApplianceView:
    label: str
    raw: list[str]
    effective: list[str]
    deployed: bool


@dataclass
class View:
    timeline: Timeline
    appliances: dict[str, ApplianceView]
    baseline: dict[str, dict[str, str]]  # label -> {slot iso: status}
    me_key: str | None
    issues: dict[str, str]
    generated: datetime


def find_me(tl: Timeline, my_name: str = "") -> str | None:
    """The logged-in user's row (the only one with editable cells), unless a
    name override is given."""
    crew = [s for s in tl.series.values() if not s.imported]
    if my_name:
        return next((s.key for s in crew if s.name.upper() == my_name.upper()), None)
    mine = [s.key for s in crew if s.is_me]
    return mine[0] if len(mine) == 1 else None


def appliance_labels(days: Iterable[DaySchedule]) -> list[str]:
    seen: dict[str, None] = {}
    for d in days:
        for label in d.appliances:
            seen.setdefault(label, None)
    return list(seen)


def effective_status(
    tl: Timeline, raw: list[str], baseline: dict[str, str], now: datetime
) -> tuple[list[str], dict[str, str], bool]:
    """While an appliance is out, Gartan shows every future slot as Off Station.
    For those future slots, use the last schedule seen before the call-out."""
    cur = tl.index_at(now)
    cur_start = tl.starts[cur] if cur is not None else now
    eff: list[str] = []
    new: dict[str, str] = {}
    for s, status in zip(tl.starts, raw):
        iso = s.isoformat()
        if status == STATUS_OFF_STATION:
            eff.append(STATUS_OFF_STATION if s <= now else baseline.get(iso, STATUS_UNKNOWN))
            if iso in baseline and s >= cur_start:
                new[iso] = baseline[iso]
        else:
            eff.append(status)
            if s >= cur_start:
                new[iso] = status
    deployed = cur is not None and eff[cur] == STATUS_OFF_STATION
    return eff, new, deployed


def build_view(
    days: Iterable[DaySchedule],
    cfg: CoreConfig,
    baseline: dict[str, dict[str, str]],
    now: datetime,
) -> View:
    days = list(days)
    tl = build_timeline(days)
    issues: dict[str, str] = {}
    for d in days:
        issues.update(d.issues)
    me_key = find_me(tl, cfg.my_name)
    if days and me_key is None:
        issues["me_missing"] = (
            f"Your row {cfg.my_name!r} not found in the schedule"
            if cfg.my_name
            else "Could not identify your own row in the schedule (set it in options)"
        )
    apps: dict[str, ApplianceView] = {}
    new_base: dict[str, dict[str, str]] = {}
    for label, raw in tl.appliances.items():
        eff, nb, deployed = effective_status(tl, raw, baseline.get(label, {}), now)
        apps[label] = ApplianceView(label, raw, eff, deployed)
        new_base[label] = nb
    return View(tl, apps, new_base, me_key, issues, now)


def contiguous_slots(tl: Timeline) -> int:
    """Number of leading slots with no gaps (a missing day would break the
    slot-index -> time mapping of the schedule export)."""
    for i in range(1, len(tl.starts)):
        if tl.starts[i] - tl.starts[i - 1] != SLOT:
            return i
    return len(tl.starts)


def schedule_export(view: View) -> dict:
    """Compact whole-week schedule for downstream templates.

    Slot i covers start + i*15min. Appliances: one status char per slot.
    People: one char per slot ("1" on, "0" off, "b" bookable)."""
    tl = view.timeline
    n = contiguous_slots(tl)
    if n == 0:
        return {"start": None, "slot_minutes": 15, "slots": 0, "appliances": {}, "people": []}

    def person_chars(s) -> str:
        return "".join(
            PERSON_ON if s.on[i] else PERSON_BOOKABLE if s.bookable[i] else PERSON_OFF
            for i in range(n)
        )

    people = []
    for s in sorted(tl.series.values(), key=lambda s: (s.imported, s.name)):
        people.append(
            {
                "name": s.name,
                "me": s.key == view.me_key,
                "imported": s.imported,
                "skills": sorted(s.skills),
                "expiring": sorted(s.expiring),
                "slots": person_chars(s),
            }
        )
    return {
        "start": tl.starts[0].isoformat(),
        "slot_minutes": int(SLOT.total_seconds() // 60),
        "slots": n,
        "appliances": {
            label: "".join(STATUS_CHAR[st] for st in a.effective[:n])
            for label, a in view.appliances.items()
        },
        "people": people,
        "legend": {
            "appliance": {v: k for k, v in STATUS_CHAR.items()},
            "person": {PERSON_ON: "on", PERSON_OFF: "off", PERSON_BOOKABLE: "bookable"},
        },
    }


def people_on(view: View, now: datetime) -> list[dict]:
    i = view.timeline.index_at(now)
    if i is None:
        return []
    return [
        {"name": s.name, "imported": s.imported, "skills": sorted(s.skills)}
        for s in sorted(view.timeline.on_at(i), key=lambda s: (s.imported, s.name))
    ]


def is_on_the_run(status: str) -> bool:
    return status in ON_STATUSES
