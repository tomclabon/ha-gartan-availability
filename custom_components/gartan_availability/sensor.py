"""Sensors: next on/off, who's on, whole-week schedule, last scrape."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.util import dt as dt_util

from .coordinator import selected_appliances
from .core.model import next_on_off
from .core.view import people_on, schedule_export
from .entity import ApplianceEntity, GartanEntity, appliance_runs, me_runs, status_now
from .core.const import STATUS_OFF_STATION


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    c = entry.runtime_data
    entities: list = [
        MyNext(c, "next_on_call", "Next on call", True),
        MyNext(c, "next_off_call", "Next off call", False),
        WhoIsOn(c),
        Schedule(c),
        LastScrape(c),
    ]
    for label in selected_appliances(entry):
        entities += [
            ApplianceNext(c, label, "next_on_the_run", "Next on the run", True),
            ApplianceNext(c, label, "next_off_the_run", "Next off the run", False),
        ]
    async_add_entities(entities)


class MyNext(GartanEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, key, name, want_on) -> None:
        super().__init__(coordinator, key, name)
        self._want_on = want_on

    @property
    def native_value(self) -> datetime | None:
        view = self.view
        if view is None:
            return None
        nxt_on, nxt_off, _ = next_on_off(me_runs(view), dt_util.utcnow(), view.timeline.end)
        return nxt_on if self._want_on else nxt_off


class ApplianceNext(ApplianceEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, label, key, name, want_on) -> None:
        super().__init__(coordinator, label, key, name)
        self._want_on = want_on

    @property
    def native_value(self) -> datetime | None:
        app, view = self.app, self.view
        if app is None or status_now(app, view) == STATUS_OFF_STATION:
            return None  # out on a call: its schedule is unreliable until it returns
        nxt_on, nxt_off, _ = next_on_off(
            appliance_runs(app, view), dt_util.utcnow(), view.timeline.end
        )
        return nxt_on if self._want_on else nxt_off


class WhoIsOn(GartanEntity, SensorEntity):
    _attr_icon = "mdi:account-group"
    _attr_native_unit_of_measurement = "people"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "who_is_on", "Who is on")

    @property
    def native_value(self) -> int | None:
        return len(people_on(self.view, dt_util.utcnow()))

    @property
    def extra_state_attributes(self) -> dict:
        return {"people": people_on(self.view, dt_util.utcnow())}


class Schedule(GartanEntity, SensorEntity):
    """The whole known week, compact, for downstream templates.
    State: when the schedule was generated. Attributes are not recorded."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-clock"
    _unrecorded_attributes = frozenset(
        {"start", "slot_minutes", "slots", "appliances", "people", "legend"}
    )

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "schedule", "Schedule")

    @property
    def native_value(self) -> datetime | None:
        return self.view.generated if self.view else None

    @property
    def extra_state_attributes(self) -> dict:
        return schedule_export(self.view)


class LastScrape(GartanEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "last_scrape", "Last scrape")

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.last_success
