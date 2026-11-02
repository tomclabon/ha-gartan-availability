"""Sensors: next on/off, who's on, booking windows, last scrape, rule check."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.util import dt as dt_util

from .core.model import next_on_off
from .core.view import Window, crew_groups
from .entity import (
    GartanEntity,
    deployed_now,
    me_runs,
    my_label,
    truck_label,
    truck_runs,
)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    c = entry.runtime_data
    t, m = truck_label(c), my_label(c)
    async_add_entities(
        [
            NextChange(c, "truck_next_on", f"{t} next on", truck_runs, True, True),
            NextChange(c, "truck_next_off", f"{t} next off", truck_runs, False, True),
            NextChange(c, "me_next_on", f"{m} next on call", me_runs, True, False),
            NextChange(c, "me_next_off", f"{m} next off call", me_runs, False, False),
            WhoIsOn(c),
            BookableWindows(c, t),
            LastScrape(c),
            RuleCheck(c),
        ]
    )


class NextChange(GartanEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, key, name, runs_fn, want_on, is_truck) -> None:
        super().__init__(coordinator, key, name)
        self._runs_fn, self._want_on, self._is_truck = runs_fn, want_on, is_truck

    @property
    def native_value(self) -> datetime | None:
        view = self.view
        if view is None or (self._is_truck and deployed_now(view)):
            return None  # truck is out: its schedule is unreliable until it returns
        nxt_on, nxt_off, _ = next_on_off(
            self._runs_fn(view), dt_util.utcnow(), view.timeline.end
        )
        return nxt_on if self._want_on else nxt_off


class WhoIsOn(GartanEntity, SensorEntity):
    _attr_icon = "mdi:account-group"
    _attr_native_unit_of_measurement = "people"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "who_is_on", "Who is on")

    @property
    def native_value(self) -> int | None:
        view = self.view
        i = view.timeline.index_at(dt_util.utcnow())
        return None if i is None else len(view.timeline.members_on(i))

    @property
    def extra_state_attributes(self) -> dict:
        g = crew_groups(self.view, self.coordinator.cfg, dt_util.utcnow())
        return {
            "ic": g["ic"],
            "driver": g["driver"],
            "ba": g["ba"],
            "others": g["others"],
            "visiting": g["visiting"],
            "off": g["off"],
        }


def window_text(w: Window, label: str) -> str:
    s, e = dt_util.as_local(w.start), dt_util.as_local(w.end)
    day = s.strftime("%a %d %b")
    span = f"{s:%H:%M}-{e:%H:%M} ({w.minutes} min)"
    if w.goes_on:
        why = f"{label} goes on if you book"
        if w.needs_dual_role:
            why += " (assuming the dual-role import is created)"
    else:
        why = "still short even if you book: " + ", ".join(w.missing)
    return f"{day} {span}: {why}"


class BookableWindows(GartanEntity, SensorEntity):
    _attr_icon = "mdi:calendar-plus"
    _attr_native_unit_of_measurement = "windows"

    def __init__(self, coordinator, truck: str) -> None:
        super().__init__(coordinator, "bookable_windows", "Bookable windows")
        self._truck = truck

    @property
    def native_value(self) -> int:
        return len(self.view.windows)

    @property
    def extra_state_attributes(self) -> dict:
        ws = self.view.windows
        return {
            "windows": [
                {
                    "start": dt_util.as_local(w.start).isoformat(),
                    "end": dt_util.as_local(w.end).isoformat(),
                    "minutes": w.minutes,
                    "truck_goes_on": w.goes_on,
                    "needs_dual_role_import": w.needs_dual_role,
                    "fills": w.fills,
                    "still_missing": w.missing,
                }
                for w in ws
            ],
            "text": "\n".join(window_text(w, self._truck) for w in ws),
        }


class LastScrape(GartanEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "last_scrape", "Last scrape")

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.last_success


class RuleCheck(GartanEntity, SensorEntity):
    """How often our crew rule disagrees with Gartan's own appliance row.
    Informational: Gartan's row is the source of truth for the calendars."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:scale-balance"
    _attr_native_unit_of_measurement = "slots"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "rule_check", "Crew rule mismatches")

    @property
    def native_value(self) -> int:
        return self.view.diagnostics["mismatched_slots"]

    @property
    def extra_state_attributes(self) -> dict:
        return self.view.diagnostics
