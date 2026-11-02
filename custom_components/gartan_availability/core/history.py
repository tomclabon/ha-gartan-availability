"""History ledger: weekly contract figures, per-day on-call minutes and call-outs.
Stdlib only. Holds Gartan's past, so it can be rebuilt from Gartan at any time.

Call-outs: a run of contiguous "Off Station" slots on an appliance row is one
call-out. You count as on it if you were on call when it started.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Iterable

from .const import SLOT, STATUS_OFF_STATION
from .model import build_timeline
from .parse import DaySchedule, WeekHours
from .view import View, find_me


@dataclass
class CallOut:
    appliance: str
    start: datetime  # UTC
    end: datetime  # UTC
    crew: int | None = None  # Gartan's "(N)" crew-off-station figure, if shown
    me: bool = False

    def to_json(self) -> list:
        return [self.appliance, self.start.isoformat(), self.end.isoformat(), self.crew, self.me]

    @classmethod
    def from_json(cls, v: list) -> "CallOut":
        return cls(v[0], datetime.fromisoformat(v[1]), datetime.fromisoformat(v[2]), v[3], bool(v[4]))


@dataclass
class DayRecord:
    day: date
    on_minutes: int  # your on-call minutes that day
    callouts: list[CallOut] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"m": self.on_minutes, "c": [c.to_json() for c in self.callouts]}

    @classmethod
    def from_json(cls, day: date, v: dict) -> "DayRecord":
        return cls(day, int(v.get("m", 0)), [CallOut.from_json(c) for c in v.get("c", [])])


@dataclass
class Ledger:
    weeks: dict[date, WeekHours] = field(default_factory=dict)
    empty_windows: set[date] = field(default_factory=set)  # fortnights with no rows
    days: dict[date, DayRecord] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "weeks": {d.isoformat(): [w.contract, w.actual] for d, w in self.weeks.items()},
            "empty": sorted(d.isoformat() for d in self.empty_windows),
            "days": {d.isoformat(): r.to_json() for d, r in self.days.items()},
        }

    @classmethod
    def from_json(cls, v: dict | None) -> "Ledger":
        led = cls()
        if not v:
            return led
        for k, (c, a) in v.get("weeks", {}).items():
            d = date.fromisoformat(k)
            led.weeks[d] = WeekHours(d, float(c), float(a))
        led.empty_windows = {date.fromisoformat(k) for k in v.get("empty", [])}
        for k, r in v.get("days", {}).items():
            d = date.fromisoformat(k)
            led.days[d] = DayRecord.from_json(d, r)
        return led

    @property
    def start(self) -> date | None:
        """Monday of the first week with a contract (when you started)."""
        weeks = [d for d, w in self.weeks.items() if w.contract > 0 or w.actual > 0]
        return min(weeks) if weeks else None


# ---------------------------------------------------------------------------
# extraction


def _runs(flags: list[bool]) -> list[tuple[int, int]]:
    out, start = [], None
    for i, f in enumerate(flags + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            out.append((start, i))
            start = None
    return out


def callouts_from(view_or_day, me_name: str = "", upto: datetime | None = None) -> list[CallOut]:
    """Call-out runs in a parsed day (or the live view's timeline), optionally
    only slots starting at or before `upto` (so future pink slots are ignored)."""
    if isinstance(view_or_day, DaySchedule):
        tl = build_timeline([view_or_day])
        crew = view_or_day.appliance_crew
        me_key = find_me(tl, me_name)
    else:
        tl = view_or_day.timeline
        crew = {}
        me_key = view_or_day.me_key
    me = tl.series.get(me_key) if me_key else None
    out: list[CallOut] = []
    for label, raw in tl.appliances.items():
        flags = [
            st == STATUS_OFF_STATION and (upto is None or tl.starts[i] <= upto)
            for i, st in enumerate(raw)
        ]
        for a, b in _runs(flags):
            counts = [c for c in (crew.get(label) or [])[a:b] if c is not None]
            out.append(
                CallOut(
                    label, tl.starts[a], tl.starts[b - 1] + SLOT,
                    max(counts) if counts else None,
                    bool(me is not None and me.on[a]),
                )
            )
    return out


def record_day(day: DaySchedule, me_name: str = "") -> DayRecord:
    tl = build_timeline([day])
    me_key = find_me(tl, me_name)
    minutes = 0
    if me_key:
        minutes = int(sum(tl.series[me_key].on) * SLOT.total_seconds() // 60)
    return DayRecord(day.date, minutes, callouts_from(day, me_name))


def merge_callouts(items: Iterable[CallOut]) -> list[CallOut]:
    """Join runs that continue across midnight (end of one == start of next)."""
    out: list[CallOut] = []
    for c in sorted(items, key=lambda c: (c.appliance, c.start)):
        prev = out[-1] if out else None
        if prev and prev.appliance == c.appliance and prev.end >= c.start:
            prev.end = max(prev.end, c.end)
            if c.crew is not None:
                prev.crew = max(prev.crew or 0, c.crew)
        else:
            out.append(CallOut(c.appliance, c.start, c.end, c.crew, c.me))
    return sorted(out, key=lambda c: c.start)


def all_callouts(ledger: Ledger, view: View | None, now: datetime) -> list[CallOut]:
    """Past call-outs from the ledger plus today's (so far) from the live view."""
    items: list[CallOut] = []
    live_from = None
    if view is not None and view.timeline.starts:
        items += callouts_from(view, upto=now)
        live_from = view.timeline.starts[0]  # local midnight today
    for rec in ledger.days.values():
        items += [c for c in rec.callouts if live_from is None or c.start < live_from]
    return merge_callouts(items)


# ---------------------------------------------------------------------------
# period summaries

PERIODS = ("this_week", "last_4_weeks", "last_52_weeks", "since_start")
PERIOD_WEEKS = {"this_week": 0, "last_4_weeks": 4, "last_52_weeks": 52}


def quarter(hours: float) -> float:
    """Round to the schedule's 15-minute granularity."""
    return round(hours * 4) / 4


@dataclass
class HoursSummary:
    actual: float  # hours on call
    contract: float  # hours expected (this week's share pro-rata so far)
    weeks: int  # complete past weeks included
    complete: bool  # every included past week has Gartan figures

    @property
    def difference(self) -> float:
        return quarter(self.actual - self.contract)


def _week_start(now: datetime, tz: tzinfo) -> tuple[date, datetime]:
    loc = now.astimezone(tz)
    monday = loc.date() - timedelta(days=loc.weekday())
    return monday, datetime.combine(monday, datetime.min.time(), tzinfo=tz)


def this_week_so_far(ledger: Ledger, view: View | None, now: datetime, tz: tzinfo) -> float:
    """Hours on call from Monday 00:00 to now: past days from the ledger, today
    from the live view."""
    monday, _ = _week_start(now, tz)
    today = now.astimezone(tz).date()
    minutes = sum(
        ledger.days[d].on_minutes
        for d in (monday + timedelta(days=k) for k in range((today - monday).days))
        if d in ledger.days
    )
    if view is not None and view.me_key:
        tl = view.timeline
        s = tl.series[view.me_key]
        for i, st in enumerate(tl.starts):
            # completed slots only: the schedule has 15-minute granularity
            if st.astimezone(tz).date() == today and st + SLOT <= now and s.on[i]:
                minutes += SLOT.total_seconds() / 60
    return quarter(minutes / 60)


def hours_summary(
    ledger: Ledger, view: View | None, now: datetime, tz: tzinfo
) -> dict[str, HoursSummary]:
    monday, monday_dt = _week_start(now, tz)
    elapsed = min(1.0, max(0.0, (now - monday_dt).total_seconds() / (7 * 86400)))
    this = ledger.weeks.get(monday)
    so_far = this_week_so_far(ledger, view, now, tz)
    contract_so_far = (this.contract * elapsed) if this else 0.0
    out: dict[str, HoursSummary] = {}
    start = ledger.start
    for period in PERIODS:
        if period == "since_start":
            n = ((monday - start).days // 7) if start else 0
        else:
            n = PERIOD_WEEKS[period]
        past = [monday - timedelta(weeks=k) for k in range(1, n + 1)]
        got = [ledger.weeks[m] for m in past if m in ledger.weeks]
        out[period] = HoursSummary(
            actual=quarter(sum(w.actual for w in got) + so_far),
            contract=quarter(sum(w.contract for w in got) + contract_so_far),
            weeks=n,
            complete=len(got) == n and this is not None,
        )
    return out


def period_start(period: str, ledger: Ledger, now: datetime, tz: tzinfo) -> datetime:
    monday, monday_dt = _week_start(now, tz)
    if period == "since_start":
        start = ledger.start or monday
        return datetime.combine(start, datetime.min.time(), tzinfo=tz)
    weeks = PERIOD_WEEKS[period]
    return datetime.combine(monday - timedelta(weeks=weeks), datetime.min.time(), tzinfo=tz)


def callout_counts(
    callouts: list[CallOut], ledger: Ledger, appliance: str, now: datetime, tz: tzinfo
) -> dict[str, dict[str, int]]:
    """{period: {"all": n, "me": n}} for one appliance."""
    out = {}
    mine = [c for c in callouts if c.appliance == appliance and c.start <= now]
    for period in PERIODS:
        since = period_start(period, ledger, now, tz)
        inside = [c for c in mine if c.start >= since]
        out[period] = {"all": len(inside), "me": sum(1 for c in inside if c.me)}
    return out
