"""Shared entity base and schedule helpers.

Devices per config entry:
- the station device ("Gartan Availability"): your own availability and station-wide entities
- one device per selected appliance ("Gartan Availability <row label>", e.g. "Gartan Availability KT52P1")
Entity ids derive from these names, so nothing is person- or station-specific.
"""
from __future__ import annotations

from datetime import datetime

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_BRIGADE_NAME, DOMAIN
from .coordinator import GartanCoordinator
from .core.const import ON_STATUSES, SLOT, STATUS_OFF_STATION
from .core.model import runs_from_flags
from .core.view import ApplianceView, View


def appliance_runs(app: ApplianceView, view: View) -> list[tuple[datetime, datetime]]:
    return runs_from_flags(view.timeline, [s in ON_STATUSES for s in app.effective])


def me_runs(view: View) -> list[tuple[datetime, datetime]]:
    if view.me_key is None:
        return []
    return runs_from_flags(view.timeline, view.timeline.series[view.me_key].on)


def live_index(view: View) -> int | None:
    return view.timeline.index_at(dt_util.utcnow())


def status_now(app: ApplianceView, view: View) -> str | None:
    i = live_index(view)
    return None if i is None else app.effective[i]


def shout_span(app: ApplianceView, view: View) -> tuple[datetime, datetime] | None:
    """(start of the current out-on-a-call run, end of the current slot)."""
    i = live_index(view)
    if i is None or app.effective[i] != STATUS_OFF_STATION:
        return None
    j = i
    while j > 0 and app.effective[j - 1] == STATUS_OFF_STATION:
        j -= 1
    return view.timeline.starts[j], view.timeline.starts[i] + SLOT


def me_on_now(view: View) -> bool | None:
    i = live_index(view)
    if i is None or view.me_key is None:
        return None
    return view.timeline.series[view.me_key].on[i]


class GartanEntity(CoordinatorEntity[GartanCoordinator]):
    """Station-level entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GartanCoordinator, key: str, name: str | None) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_station_{key}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Gartan Availability",
            manufacturer="Gartan Availability",
            model=str(entry.data.get(CONF_BRIGADE_NAME, "")) or None,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def view(self) -> View:
        return self.coordinator.data


class ApplianceEntity(GartanEntity):
    """Entity on a per-appliance device."""

    def __init__(self, coordinator, label: str, key: str, name: str | None) -> None:
        super().__init__(coordinator, key, name)
        entry = coordinator.config_entry
        self.label = label
        self._attr_unique_id = f"{entry.entry_id}_appliance_{label}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_appliance_{label}")},
            name=f"Gartan Availability {label}",
            manufacturer="Gartan Availability",
            model="Appliance",
            entry_type=DeviceEntryType.SERVICE,
            via_device=(DOMAIN, entry.entry_id),
        )

    @property
    def app(self) -> ApplianceView | None:
        data = self.coordinator.data
        return None if data is None else data.appliances.get(self.label)

    @property
    def available(self) -> bool:
        return super().available and self.app is not None
