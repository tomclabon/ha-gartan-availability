"""Gartan availability integration. HA imports are inside functions so the
HA-free core (and its tests) can be imported without Home Assistant installed."""
from __future__ import annotations

PLATFORMS = ["binary_sensor", "calendar", "sensor"]


async def async_setup_entry(hass, entry) -> bool:
    from .coordinator import GartanCoordinator

    coordinator = GartanCoordinator(hass, entry)
    await coordinator.async_load()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _reload(hass, entry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        entry.runtime_data.async_cleanup()
    return ok
