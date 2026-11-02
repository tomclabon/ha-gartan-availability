"""Week timeline built from per-day schedules. Stdlib only, no station rules."""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Sequence

from .const import SLOT, STATUS_UNKNOWN
from .parse import DaySchedule


@dataclass
class Series:
    key: str
    name: str
    imported: bool
    on: list[bool]
    bookable: list[bool]
    skills: frozenset[str] = frozenset()  # from the first day the row appears
    expiring: frozenset[str] = frozenset()
    is_me: bool = False
    ebid: int | None = None


@dataclass
class Timeline:
    starts: list[datetime]
    appliances: dict[str, list[str]]  # label -> raw status per slot
    series: dict[str, Series]

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

    def on_at(self, i: int) -> list[Series]:
        return [s for s in self.series.values() if s.on[i]]


def _fit(lst: Sequence, n: int, default) -> list:
    out = list(lst)[:n]
    return out + [default] * (n - len(out))


def build_timeline(days: Iterable[DaySchedule]) -> Timeline:
    """Concatenate days. Crew rows are keyed by name; imported rows are keyed by
    "import|<name>" and same-named imports on one day are merged (on = any)."""
    starts: list[datetime] = []
    appliances: dict[str, list[str]] = {}
    series: dict[str, Series] = {}
    for day in sorted(days, key=lambda d: d.date):
        n = len(day.slot_starts)
        off = len(starts)
        starts.extend(day.slot_starts)
        for label, statuses in day.appliances.items():
            appliances.setdefault(label, [STATUS_UNKNOWN] * off).extend(
                _fit(statuses, n, STATUS_UNKNOWN)
            )
        today: dict[str, tuple[list[bool], list[bool]]] = {}
        for p in day.people:
            key = f"import|{p.name}" if p.is_import else p.name
            s = series.get(key)
            if s is None:
                s = series[key] = Series(
                    key, p.name, p.is_import, [False] * off, [False] * off,
                    p.skills, p.expiring, p.is_me, p.ebid,
                )
            s.is_me = s.is_me or p.is_me
            s.ebid = s.ebid or p.ebid
            if key in today:
                on, book = today[key]
                today[key] = (
                    [a or b for a, b in zip(on, _fit(p.on, n, False))],
                    [a or b for a, b in zip(book, _fit(p.bookable, n, False))],
                )
            else:
                today[key] = (_fit(p.on, n, False), _fit(p.bookable, n, False))
        for key, s in series.items():
            on, book = today.get(key, ([False] * n, [False] * n))
            s.on.extend(on)
            s.bookable.extend(book)
        for label, statuses in appliances.items():
            if len(statuses) < off + n:
                statuses.extend([STATUS_UNKNOWN] * (off + n - len(statuses)))
    return Timeline(starts, appliances, series)


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
