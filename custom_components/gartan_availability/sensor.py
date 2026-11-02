"""Sensors: next on/off, who's on, whole-week schedule, last scrape."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.util import dt as dt_util

from .coordinator import selected_appliances
from .core.model import next_on_off
from .core.view import people_on, schedule_export
from .core.history import PERIODS, all_callouts, callout_counts, hours_summary
from .entity import (
    ApplianceEntity,
    GartanEntity,
    HistoryListenerMixin,
    appliance_runs,
    me_runs,
    status_now,
)

PERIOD_NAMES = {
    "this_week": "this week",
    "last_4_weeks": "last 4 weeks",
    "last_52_weeks": "last 52 weeks",
    "since_start": "since start",
}
from .core.const import STATUS_OFF_STATION


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    c = entry.runtime_data
    entities: list = [
        MyNext(c, "next_on_call", "Next on call", True),
        MyNext(c, "next_off_call", "Next off call", False),
        WhoIsOn(c),
        Schedule(c),
        LastScrape(c),
        HistoryStatus(c),
    ]
    entities += [Hours(c, period) for period in PERIODS]
    for label in selected_appliances(entry):
        entities += [
            ApplianceNext(c, label, "next_on_the_run", "Next on the run", True),
            ApplianceNext(c, label, "next_off_the_run", "Next off the run", False),
        ]
        entities += [CallOuts(c, label, period, mine) for period in PERIODS for mine in (False, True)]
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


class Hours(HistoryListenerMixin, GartanEntity, SensorEntity):
    """Your on-call hours against contract for a Gartan-week period.
    State: actual hours. "This week" counts only the part already passed, and
    its contract is pro-rata; the longer periods add that to whole past weeks."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, coordinator, period: str) -> None:
        super().__init__(coordinator, f"hours_{period}", f"Hours {PERIOD_NAMES[period]}")
        self._period = period

    def _summary(self):
        tz = dt_util.get_default_time_zone()
        return hours_summary(self.coordinator.history.ledger, self.view, dt_util.utcnow(), tz)[self._period]

    @property
    def native_value(self) -> float:
        return self._summary().actual

    @property
    def extra_state_attributes(self) -> dict:
        s = self._summary()
        attrs = {
            "contract": s.contract,
            "difference": s.difference,
            "under_contract": s.actual < s.contract,
            "past_weeks": s.weeks,
            "complete": s.complete,
        }
        if self._period == "this_week":
            from datetime import timedelta

            today = dt_util.now().date()
            week = self.coordinator.history.ledger.weeks.get(today - timedelta(days=today.weekday()))
            attrs["week_contract"] = week.contract if week else None
            attrs["week_scheduled"] = week.actual if week else None
        return attrs


class CallOuts(HistoryListenerMixin, ApplianceEntity, SensorEntity):
    """Number of call-outs for the appliance (or the ones you were on call for)."""

    _attr_native_unit_of_measurement = "call-outs"
    _attr_icon = "mdi:fire-truck"

    def __init__(self, coordinator, label: str, period: str, mine: bool) -> None:
        name = f"{'My call-outs' if mine else 'Call-outs'} {PERIOD_NAMES[period]}"
        key = f"{'my_' if mine else ''}call_outs_{period}"
        super().__init__(coordinator, label, key, name)
        self._period, self._mine = period, mine

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success  # history counts even if the row moves

    @property
    def native_value(self) -> int:
        now = dt_util.utcnow()
        tz = dt_util.get_default_time_zone()
        led = self.coordinator.history.ledger
        counts = callout_counts(all_callouts(led, self.view, now), led, self.label, now, tz)
        return counts[self._period]["me" if self._mine else "all"]


class HistoryStatus(HistoryListenerMixin, GartanEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:history"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "history", "History")

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> str:
        return self.coordinator.history.status

    @property
    def extra_state_attributes(self) -> dict:
        return self.coordinator.history.progress()
