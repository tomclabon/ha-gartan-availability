"""Binary sensors."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.util import dt as dt_util

from .coordinator import selected_appliances
from .core.const import ON_STATUSES, STATUS_OFF_STATION
from .entity import ApplianceEntity, GartanEntity, me_on_now, status_now


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    c = entry.runtime_data
    entities: list = [OnCall(c), Attention(c)]
    for label in selected_appliances(entry):
        entities += [
            ApplianceFlag(c, label, "on_the_run", "On the run", ON_STATUSES, BinarySensorDeviceClass.RUNNING),
            ApplianceFlag(c, label, "deployed", "Deployed", frozenset({STATUS_OFF_STATION}), None),
        ]
    async_add_entities(entities)


class OnCall(GartanEntity, BinarySensorEntity):
    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "on_call", "On call")

    @property
    def is_on(self) -> bool | None:
        return None if self.coordinator.data is None else me_on_now(self.view)


class ApplianceFlag(ApplianceEntity, BinarySensorEntity):
    def __init__(self, coordinator, label, key, name, statuses, device_class) -> None:
        super().__init__(coordinator, label, key, name)
        self._statuses = statuses
        self._attr_device_class = device_class

    @property
    def is_on(self) -> bool | None:
        app = self.app
        if app is None:
            return None
        st = status_now(app, self.view)
        return None if st is None else st in self._statuses

    @property
    def extra_state_attributes(self) -> dict:
        app = self.app
        return {"status": status_now(app, self.view) if app else None}


class Attention(GartanEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "needs_attention", "Needs attention")

    def _issues(self) -> dict[str, str]:
        return self.coordinator.attention(self.coordinator.data, dt_util.utcnow())

    @property
    def available(self) -> bool:
        return True  # must stay visible precisely when things are failing

    @property
    def is_on(self) -> bool:
        return bool(self._issues())

    @property
    def extra_state_attributes(self) -> dict:
        return {"issues": self._issues()}
