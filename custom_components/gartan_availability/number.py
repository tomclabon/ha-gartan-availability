"""Refresh settings as number entities on the station device (Configuration).
Changes apply immediately (no reload) and are restored after a restart."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.const import EntityCategory, UnitOfTime

from .const import (
    HISTORY_GAP_MAX,
    HISTORY_GAP_MIN,
    HISTORY_REQUEST_GAP,
    TODAY_INTERVAL,
    TODAY_INTERVAL_MAX,
    TODAY_INTERVAL_MIN,
    WEEK_INTERVAL,
    WEEK_INTERVAL_MAX,
    WEEK_INTERVAL_MIN,
)
from .entity import GartanEntity


@dataclass(frozen=True)
class Setting:
    key: str
    name: str
    unit: str
    default: float
    minimum: float
    maximum: float
    step: float
    icon: str
    apply: Callable[[object, float], Awaitable[None] | None]


async def _today(c, v): await c.async_set_today_interval(v)
def _week(c, v): c.set_week_interval(v)
def _gap(c, v): setattr(c.history, "request_gap", v)


SETTINGS = (
    Setting("today_refresh", "Today refresh", UnitOfTime.MINUTES,
            TODAY_INTERVAL.total_seconds() / 60, TODAY_INTERVAL_MIN, TODAY_INTERVAL_MAX, 1,
            "mdi:timer-sync-outline", _today),
    Setting("week_refresh", "Week refresh", UnitOfTime.MINUTES,
            WEEK_INTERVAL.total_seconds() / 60, WEEK_INTERVAL_MIN, WEEK_INTERVAL_MAX, 5,
            "mdi:calendar-sync-outline", _week),
    Setting("history_request_gap", "History request gap", UnitOfTime.SECONDS,
            HISTORY_REQUEST_GAP, HISTORY_GAP_MIN, HISTORY_GAP_MAX, 0.5,
            "mdi:timer-sand", _gap),
)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    c = entry.runtime_data
    async_add_entities([SettingNumber(c, s) for s in SETTINGS])


class SettingNumber(GartanEntity, RestoreNumber):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, setting: Setting) -> None:
        super().__init__(coordinator, setting.key, setting.name)
        self._setting = setting
        self._attr_native_unit_of_measurement = setting.unit
        self._attr_native_min_value = setting.minimum
        self._attr_native_max_value = setting.maximum
        self._attr_native_step = setting.step
        self._attr_icon = setting.icon
        self._attr_native_value = setting.default

    @property
    def available(self) -> bool:
        return True  # settings must stay editable even when Gartan is down

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            value = min(max(float(last.native_value), self._setting.minimum), self._setting.maximum)
            if value != self._setting.default:
                await self._apply(value)

    async def async_set_native_value(self, value: float) -> None:
        await self._apply(value)

    async def _apply(self, value: float) -> None:
        self._attr_native_value = value
        result = self._setting.apply(self.coordinator, value)
        if result is not None:
            await result
        self.async_write_ha_state()
