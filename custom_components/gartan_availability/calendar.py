"""Calendars: each appliance's on-the-run periods, and your own on-call periods."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .coordinator import selected_appliances
from .core.history import all_callouts
from .entity import ApplianceEntity, GartanEntity, HistoryListenerMixin, appliance_runs, me_runs


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities) -> None:
    c = entry.runtime_data
    entities: list = [OnCallCalendar(c)]
    entities += [ApplianceCalendar(c, label) for label in selected_appliances(entry)]
    async_add_entities(entities)


class _EventsMixin(CalendarEntity):
    def _events(self) -> list[CalendarEvent]:
        raise NotImplementedError

    @property
    def event(self) -> CalendarEvent | None:
        if self.coordinator.data is None:
            return None
        now = dt_util.utcnow()
        events = self._events()
        current = next((e for e in events if e.start <= now < e.end), None)
        return current or next((e for e in events if e.start > now), None)

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        if self.coordinator.data is None:
            return []
        return [e for e in self._events() if e.end > start_date and e.start < end_date]


def _callouts(entity):
    return all_callouts(entity.coordinator.history.ledger, entity.view, dt_util.utcnow())


class OnCallCalendar(HistoryListenerMixin, GartanEntity, _EventsMixin):
    """Your on-call periods (current week), plus past call-outs you were on call for."""

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "on_call", "On call")

    def _events(self) -> list[CalendarEvent]:
        events = [
            CalendarEvent(start=s, end=e, summary="On call", uid=f"{self.unique_id}_{s.isoformat()}")
            for s, e in me_runs(self.view)
        ]
        wanted = set(selected_appliances(self.coordinator.config_entry))
        for c in _callouts(self):
            if c.me and c.appliance in wanted:
                crew = f" ({c.crew} crew)" if c.crew else ""
                events.append(
                    CalendarEvent(
                        start=c.start, end=c.end, summary=f"Call-out {c.appliance}{crew}",
                        uid=f"{self.unique_id}_co_{c.appliance}_{c.start.isoformat()}",
                    )
                )
        return sorted(events, key=lambda ev: ev.start)


class ApplianceCalendar(HistoryListenerMixin, ApplianceEntity, _EventsMixin):
    def __init__(self, coordinator, label: str) -> None:
        # name None: takes the device name -> calendar.gartan_availability_<label>
        super().__init__(coordinator, label, "calendar", None)

    def _events(self) -> list[CalendarEvent]:
        app = self.app
        if app is None:
            return []
        view = self.view
        events = [
            CalendarEvent(
                start=s, end=e, summary=f"{self.label} on the run",
                uid=f"{self.unique_id}_{s.isoformat()}",
            )
            for s, e in appliance_runs(app, view)
        ]
        for c in _callouts(self):
            if c.appliance == self.label:
                crew = f" ({c.crew} crew)" if c.crew else ""
                events.append(
                    CalendarEvent(
                        start=c.start, end=c.end, summary=f"{self.label} out on a call{crew}",
                        uid=f"{self.unique_id}_out_{c.start.isoformat()}",
                    )
                )
        return sorted(events, key=lambda ev: ev.start)
