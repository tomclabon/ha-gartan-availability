"""Derived view of the schedule: effective P1 status, booking windows, diagnostics."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from .const import (
    BA_SKILL,
    DRIVER_SKILL,
    IC_SKILL,
    ON_STATUSES,
    SLOT,
    STATUS_OFF_STATION,
    STATUS_UNKNOWN,
)
from .model import Member, Timeline, build_timeline, check_crew
from .parse import DaySchedule, find_appliance


@dataclass(frozen=True)
class CoreConfig:
    appliance_label: str
    my_name: str  # data-name of the user's own row
    dual_names: frozenset[str] = frozenset()  # upper-cased data-names
    extra_skills: frozenset[str] = frozenset()  # "what-if" skills for me
    display_names: dict[str, str] = field(default_factory=dict)  # UPPER name -> label


@dataclass
class Window:
    start: datetime
    end: datetime
    goes_on: bool  # True: truck goes on if you book; False: still short
    needs_dual_role: bool
    fills: list[str]
    missing: list[str]

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass
class View:
    timeline: Timeline
    p1_effective: list[str]
    baseline: dict[str, str]
    deployed: bool
    p1_now: str
    me_key: str | None
    issues: dict[str, str]
    windows: list[Window]
    diagnostics: dict
    generated: datetime


def display_name(name: str, overrides: dict[str, str], visitor: bool = False) -> str:
    label = overrides.get(name.upper())
    if not label:
        if "," in name:
            surname, initials = (s.strip() for s in name.split(",", 1))
            label = f"{initials} {surname.title()}"
        else:
            label = name.title()
    return f"{label} (visiting)" if visitor else label


def find_me(tl: Timeline, my_name: str) -> str | None:
    for s in tl.series.values():
        if not s.visitor and s.name.upper() == my_name.upper():
            return s.key
    return None


def effective_p1(
    tl: Timeline, baseline: dict[str, str], now: datetime
) -> tuple[list[str], dict[str, str], bool]:
    """While the truck is out every future P1 slot is shown pink (off station).
    Keep the pre-call-out schedule for those slots instead of the pink."""
    cur = tl.index_at(now)
    cur_start = tl.starts[cur] if cur is not None else now
    eff: list[str] = []
    new: dict[str, str] = {}
    for s, raw in zip(tl.starts, tl.p1_raw):
        iso = s.isoformat()
        if raw == STATUS_OFF_STATION:
            if s <= now:
                eff.append(STATUS_OFF_STATION)
            else:
                eff.append(baseline.get(iso, STATUS_UNKNOWN))
            if iso in baseline and s >= cur_start:
                new[iso] = baseline[iso]
        else:
            eff.append(raw)
            if s >= cur_start:
                new[iso] = raw
    deployed = cur is not None and eff[cur] == STATUS_OFF_STATION
    return eff, new, deployed


def find_windows(
    tl: Timeline, p1_eff: list[str], me_key: str, cfg: CoreConfig, now: datetime
) -> list[Window]:
    me = tl.series[me_key]
    cur = tl.index_at(now)
    first = cur if cur is not None else 0
    out: list[Window] = []
    cur_w: Window | None = None
    sig = None
    for i in range(first, len(tl.starts)):
        qualifies = (
            p1_eff[i] not in ON_STATUSES
            and p1_eff[i] not in (STATUS_OFF_STATION, STATUS_UNKNOWN)
            and me.bookable[i]
        )
        w = None
        if qualifies:
            others = tl.members_on(i, exclude=me_key)
            c0 = check_crew(others, cfg.dual_names)
            if not c0.valid_dual:
                mine = Member(me.key, me.name, me.skills[i] | cfg.extra_skills)
                c1 = check_crew([*others, mine], cfg.dual_names)
                fills = sorted(set(c0.missing) - set(c1.missing))
                if c1.valid_strict:
                    w = (True, False, fills, [])
                elif c1.valid_dual:
                    w = (True, True, fills, [])
                else:
                    w = (False, False, fills, c1.missing)
        if w is None:
            cur_w, sig = None, None
            continue
        key = (w[0], w[1], tuple(w[2]), tuple(w[3]))
        s, e = tl.starts[i], tl.starts[i] + SLOT
        if cur_w is not None and sig == key and cur_w.end == s:
            cur_w.end = e
        else:
            cur_w = Window(s, e, w[0], w[1], w[2], w[3])
            sig = key
            out.append(cur_w)
    return out


def compare_p1(tl: Timeline, p1_eff: list[str], cfg: CoreConfig) -> dict:
    """Oracle: does our crew rule reproduce Gartan's appliance row?"""
    checked, bad = 0, []
    for i, st in enumerate(p1_eff):
        if st in (STATUS_OFF_STATION, STATUS_UNKNOWN):
            continue
        chk = check_crew(tl.members_on(i), cfg.dual_names)
        expected = chk.valid_strict or (chk.valid_dual and tl.dual_import_on[i])
        checked += 1
        if expected != (st in ON_STATUSES):
            bad.append((tl.starts[i], expected, st))
    return {
        "checked_slots": checked,
        "mismatched_slots": len(bad),
        "mismatch_examples": [
            {"start": s.isoformat(), "rule_says_on": e, "gartan": g} for s, e, g in bad[:6]
        ],
    }


def build_view(
    days: Iterable[DaySchedule], cfg: CoreConfig, baseline: dict[str, str], now: datetime
) -> View:
    days = list(days)
    tl = build_timeline(days, cfg.appliance_label)
    issues: dict[str, str] = {}
    for d in days:
        issues.update(d.issues)
    if days and not any(find_appliance(d.appliances, cfg.appliance_label) for d in days):
        issues["appliance_missing"] = f"Appliance row {cfg.appliance_label!r} not found"
    me_key = find_me(tl, cfg.my_name)
    if days and me_key is None:
        issues["me_missing"] = f"Your row {cfg.my_name!r} not found in the schedule"
    eff, new_base, deployed = effective_p1(tl, baseline, now)
    cur = tl.index_at(now)
    p1_now = eff[cur] if cur is not None else STATUS_UNKNOWN
    windows = find_windows(tl, eff, me_key, cfg, now) if me_key else []
    diag = compare_p1(tl, eff, cfg)
    diag["dual_cover_slots"] = sum(tl.dual_import_on)
    return View(tl, eff, new_base, deployed, p1_now, me_key, issues, windows, diag, now)


def crew_groups(view: View, cfg: CoreConfig, now: datetime) -> dict[str, list[str]]:
    """IC / Driver / BA (exclusive of IC+Driver) / Others, plus Off."""
    tl = view.timeline
    i = tl.index_at(now)
    empty = {"ic": [], "driver": [], "ba": [], "others": [], "off": [], "visiting": []}
    if i is None:
        return empty
    ic, drv, ba, oth, off, vis = [], [], [], [], [], []
    on_keys = set()
    for m in tl.members_on(i):
        on_keys.add(m.key)
        label = display_name(m.name, cfg.display_names, m.visitor)
        has_ic, has_drv = IC_SKILL in m.skills, DRIVER_SKILL in m.skills
        if m.visitor:
            vis.append(label)
        if has_ic:
            ic.append(label)
        if has_drv:
            drv.append(label)
        if not has_ic and not has_drv:
            (ba if BA_SKILL in m.skills else oth).append(label)
    for s in tl.series.values():
        if not s.visitor and s.key not in on_keys:
            off.append(display_name(s.name, cfg.display_names))
    return {
        "ic": sorted(ic),
        "driver": sorted(drv),
        "ba": sorted(ba),
        "others": sorted(oth),
        "off": sorted(off),
        "visiting": sorted(vis),
    }
