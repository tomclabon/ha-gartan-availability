"""Rebuild-history button."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory

from .entity import GartanEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([RebuildHistory(entry.runtime_data)])


class RebuildHistory(GartanEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:database-refresh"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "rebuild_history", "Rebuild history")

    @property
    def available(self) -> bool:
        return True

    async def async_press(self) -> None:
        await self.coordinator.history.async_rebuild()
