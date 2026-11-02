"""Binary sensors."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.util import dt as dt_util

from .entity import GartanEntity, deployed_now, me_on_now, my_label, truck_label, truck_on_now


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    c = entry.runtime_data
    t, m = truck_label(c), my_label(c)
    async_add_entities(
        [
            Flag(c, "truck_on", f"{t} on", lambda v: truck_on_now(v), BinarySensorDeviceClass.RUNNING),
            Flag(c, "truck_deployed", f"{t} deployed", lambda v: deployed_now(v), None),
            Flag(c, "me_on_call", f"{m} on call", lambda v: me_on_now(v), None),
            Attention(c),
        ]
    )


class Flag(GartanEntity, BinarySensorEntity):
    def __init__(self, coordinator, key, name, fn, device_class) -> None:
        super().__init__(coordinator, key, name)
        self._fn = fn
        self._attr_device_class = device_class

    @property
    def is_on(self) -> bool | None:
        return None if self.coordinator.data is None else bool(self._fn(self.view))


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
