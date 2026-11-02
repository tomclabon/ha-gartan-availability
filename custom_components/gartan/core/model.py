"""Timeline, crew rule and booking-window logic. Stdlib only."""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Sequence

from .const import (
    BA_SKILL,
    DRIVER_SKILL,
    IC_SKILL,
    MIN_BA,
    MIN_COMPETENT_FF,
    MIN_CREW,
    ON_STATUSES,
    SLOT,
    STATUS_UNKNOWN,
)
from .parse import DaySchedule, find_appliance, is_dual_cover

EMPTY: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Member:
    key: str
    name: str
    skills: frozenset[str]
    visitor: bool = False


@dataclass
class Series:
    key: str
    name: str
    visitor: bool
    on: list[bool]
    bookable: list[bool]
    skills: list[frozenset[str]]


@dataclass
class Timeline:
    starts: list[datetime]
    p1_raw: list[str]
    series: dict[str, Series]
    dual_import_on: list[bool]

    def index_at(self, t: datetime) -> int | None:
        if not self.starts:
            return None
        i = bisect.bisect_right(self.starts, t) - 1
        if i < 0 or t >= self.starts[i] + SLOT:
            return None
        return i

    @property
    def end(self) -> datetime | None:
        return self.starts[-1] + SLOT if self.starts else None

    def members_on(self, i: int, exclude: str | None = None) -> list[Member]:
        return [
            Member(s.key, s.name, s.skills[i], s.visitor)
            for s in self.series.values()
            if s.on[i] and s.key != exclude
        ]


def _fit(lst: Sequence, n: int, default) -> list:
    out = list(lst)[:n]
    return out + [default] * (n - len(out))


def build_timeline(days: Iterable[DaySchedule], appliance_label: str) -> Timeline:
    starts: list[datetime] = []
    p1: list[str] = []
    dual: list[bool] = []
    series: dict[str, Series] = {}
    for day in sorted(days, key=lambda d: d.date):
        n = len(day.slot_starts)
        off = len(starts)
        starts.extend(day.slot_starts)
        p1.extend(_fit(find_appliance(day.appliances, appliance_label) or [], n, STATUS_UNKNOWN))
        dual_on = [False] * n
        seen: set[str] = set()
        for idx, p in enumerate(day.people):
            if p.is_import:
                if is_dual_cover(p):
                    dual_on = [a or b for a, b in zip(dual_on, _fit(p.on, n, False))]
                    continue
                key, visitor = f"visitor|{day.date.isoformat()}|{idx}|{p.name}", True
            else:
                key, visitor = p.name, False
                if key in seen:
                    key = f"{key}|{idx}"
            seen.add(key)
            s = series.get(key)
            if s is None:
                s = series[key] = Series(
                    key, p.name, visitor, [False] * off, [False] * off, [EMPTY] * off
                )
            s.on.extend(_fit(p.on, n, False))
            s.bookable.extend(_fit(p.bookable, n, False))
            s.skills.extend([p.skills] * n)
        for s in series.values():
            if s.key not in seen:
                s.on.extend([False] * n)
                s.bookable.extend([False] * n)
                s.skills.extend([EMPTY] * n)
        dual.extend(dual_on)
    return Timeline(starts, p1, series, dual)


@dataclass
class CrewCheck:
    size: int
    ba: int
    valid_strict: bool  # distinct IC1 and driver holders
    valid_dual: bool  # ... or a permitted dual-role person holds both
    missing: list[str]  # shortfalls under the lenient (dual-allowed) reading


def check_crew(members: Sequence[Member], dual_names: frozenset[str]) -> CrewCheck:
    ic = [m for m in members if IC_SKILL in m.skills]
    drv = [m for m in members if DRIVER_SKILL in m.skills]
    ba = sum(1 for m in members if BA_SKILL in m.skills)
    distinct = any(i.key != d.key for i in ic for d in drv)
    dual_ok = any(
        i.key == d.key and i.name.upper() in dual_names for i in ic for d in drv
    )
    size_ok = len(members) >= max(MIN_CREW, MIN_COMPETENT_FF)
    base = size_ok and ba >= MIN_BA
    missing: list[str] = []
    if not size_ok:
        missing.append("crew")
    if ba < MIN_BA:
        missing.append("BA")
    if not ic:
        missing.append(IC_SKILL)
    if not drv:
        missing.append(DRIVER_SKILL)
    if ic and drv and not (distinct or dual_ok):
        missing.append("separate IC1/ERD-Ang holder")
    return CrewCheck(
        len(members), ba, base and distinct, base and (distinct or dual_ok), missing
    )


def runs_from_flags(tl: Timeline, flags: Sequence[bool]) -> list[tuple[datetime, datetime]]:
    out: list[tuple[datetime, datetime]] = []
    start = end = None
    for i, on in enumerate(flags):
        s = tl.starts[i]
        if on:
            if start is not None and end == s:
                end = s + SLOT
            else:
                if start is not None:
                    out.append((start, end))
                start, end = s, s + SLOT
        elif start is not None:
            out.append((start, end))
            start = end = None
    if start is not None:
        out.append((start, end))
    return out


def next_on_off(
    runs: Sequence[tuple[datetime, datetime]], now: datetime, horizon_end: datetime | None
) -> tuple[datetime | None, datetime | None, bool]:
    """Return (next_on, next_off, currently_on). next_off is None when the run
    reaches the end of the known schedule (true end unknown)."""
    current = next((r for r in runs if r[0] <= now < r[1]), None)
    upcoming = next((r for r in runs if r[0] > now), None)
    if current:
        off = None if current[1] == horizon_end else current[1]
        return (upcoming[0] if upcoming else None), off, True
    if upcoming:
        off = None if upcoming[1] == horizon_end else upcoming[1]
        return upcoming[0], off, False
    return None, None, False
