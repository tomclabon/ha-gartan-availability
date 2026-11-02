"""Shared entity base and schedule helpers."""
from __future__ import annotations

from datetime import datetime

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_MY_LABEL, CONF_SLUG, DEFAULT_MY_LABEL, DEFAULT_SLUG, DOMAIN
from .coordinator import GartanCoordinator, opt
from .core.const import ON_STATUSES, SLOT, STATUS_OFF_STATION
from .core.model import runs_from_flags
from .core.view import View


def truck_label(coordinator: GartanCoordinator) -> str:
    return str(opt(coordinator.config_entry, CONF_SLUG, DEFAULT_SLUG)).upper()


def my_label(coordinator: GartanCoordinator) -> str:
    return str(opt(coordinator.config_entry, CONF_MY_LABEL, DEFAULT_MY_LABEL))


def truck_runs(view: View) -> list[tuple[datetime, datetime]]:
    return runs_from_flags(view.timeline, [s in ON_STATUSES for s in view.p1_effective])


def me_runs(view: View) -> list[tuple[datetime, datetime]]:
    if view.me_key is None:
        return []
    return runs_from_flags(view.timeline, view.timeline.series[view.me_key].on)


def live_index(view: View) -> int | None:
    return view.timeline.index_at(dt_util.utcnow())


def truck_on_now(view: View) -> bool:
    i = live_index(view)
    return i is not None and view.p1_effective[i] in ON_STATUSES


def deployed_now(view: View) -> bool:
    i = live_index(view)
    return i is not None and view.p1_effective[i] == STATUS_OFF_STATION


def shout_span(view: View) -> tuple[datetime, datetime] | None:
    """(start of the current out-on-shout run, end of the current slot)."""
    i = live_index(view)
    if i is None or view.p1_effective[i] != STATUS_OFF_STATION:
        return None
    j = i
    while j > 0 and view.p1_effective[j - 1] == STATUS_OFF_STATION:
        j -= 1
    return view.timeline.starts[j], view.timeline.starts[i] + SLOT


def me_on_now(view: View) -> bool:
    i = live_index(view)
    return i is not None and view.me_key is not None and view.timeline.series[view.me_key].on[i]


class GartanEntity(CoordinatorEntity[GartanCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: GartanCoordinator, key: str, name: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Gartan",
            manufacturer="Gartan Availability",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def view(self) -> View:
        return self.coordinator.data
