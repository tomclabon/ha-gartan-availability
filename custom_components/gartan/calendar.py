"""Calendar entities: the appliance on-the-run schedule and my on-call schedule."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .entity import (
    GartanEntity,
    me_runs,
    my_label,
    shout_span,
    truck_label,
    truck_runs,
)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities) -> None:
    c = entry.runtime_data
    async_add_entities(
        [
            RunsCalendar(c, "cal_truck", truck_label(c), f"{truck_label(c)} on the run", True),
            RunsCalendar(c, "cal_me", my_label(c), "On call", False),
        ]
    )


class RunsCalendar(GartanEntity, CalendarEntity):
    def __init__(self, coordinator, key, name, summary, is_truck) -> None:
        super().__init__(coordinator, key, name)
        self._summary = summary
        self._is_truck = is_truck

    def _events(self) -> list[CalendarEvent]:
        view = self.view
        runs = truck_runs(view) if self._is_truck else me_runs(view)
        events = [
            CalendarEvent(start=s, end=e, summary=self._summary, uid=f"{self.unique_id}_{s.isoformat()}")
            for s, e in runs
        ]
        if self._is_truck:
            span = shout_span(view)
            if span:
                events.append(
                    CalendarEvent(
                        start=span[0],
                        end=span[1],
                        summary=f"{self._summary.split(' on the run')[0]} out on shout",
                        uid=f"{self.unique_id}_shout_{span[0].isoformat()}",
                    )
                )
        return sorted(events, key=lambda ev: ev.start)

    @property
    def event(self) -> CalendarEvent | None:
        if self.coordinator.data is None:
            return None
        now = dt_util.utcnow()
        events = self._events()
        current = next((e for e in events if e.start <= now < e.end), None)
        if current:
            return current
        return next((e for e in events if e.start > now), None)

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        if self.coordinator.data is None:
            return []
        return [e for e in self._events() if e.end > start_date and e.start < end_date]
