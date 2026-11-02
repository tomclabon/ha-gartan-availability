"""Pictures for the companion app's Picture widget (and dashboards).

- image.gartan_availability_<appliance>_week: the week for an appliance and you
- image.gartan_availability_crew: who is on now (until when) and off (from when)

Both are rendered fresh on every request, so their "Updated" stamp is the fetch
time. image_last_updated changes on every data update and slot boundary, which
tells dashboards to re-fetch.
"""
from __future__ import annotations

from homeassistant.components.image import ImageEntity
from homeassistant.core import callback
from homeassistant.util import dt as dt_util

from .coordinator import selected_appliances
from .entity import ApplianceEntity, GartanEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    c = entry.runtime_data
    entities: list = [CrewImage(c)]
    entities += [WeekImage(c, label) for label in selected_appliances(entry)]
    async_add_entities(entities)


class _RenderedImage:
    """Mixin: listed first so its update hook runs before CoordinatorEntity's."""

    _attr_content_type = "image/png"
    _appliance = ""

    def _init_image(self, coordinator) -> None:
        ImageEntity.__init__(self, coordinator.hass)
        self._attr_image_last_updated = dt_util.utcnow()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_image_last_updated = dt_util.utcnow()
        super()._handle_coordinator_update()

    @staticmethod
    def _render(inp) -> bytes:
        raise NotImplementedError

    async def async_image(self) -> bytes | None:
        view = self.coordinator.data
        if view is None:
            return None
        from .core.render import RenderInput

        inp = RenderInput(
            view=view,
            appliance=self._appliance,
            tz=dt_util.get_default_time_zone(),
            now=dt_util.utcnow(),
            fetched=dict(self.coordinator.fetched_at),  # keyed by local date
            today_stale_after=self.coordinator.today_stale_after,
            day_stale_after=self.coordinator.day_stale_after,
        )
        return await self.hass.async_add_executor_job(self._render, inp)


class WeekImage(_RenderedImage, ApplianceEntity, ImageEntity):
    _attr_icon = "mdi:calendar-week"

    def __init__(self, coordinator, label: str) -> None:
        ApplianceEntity.__init__(self, coordinator, label, "week", "Week")
        self._appliance = label
        self._init_image(coordinator)

    @staticmethod
    def _render(inp) -> bytes:
        from .core.render import render_week_png

        return render_week_png(inp)


class CrewImage(_RenderedImage, GartanEntity, ImageEntity):
    _attr_icon = "mdi:account-group"

    def __init__(self, coordinator) -> None:
        GartanEntity.__init__(self, coordinator, "crew", "Crew")
        self._init_image(coordinator)

    @staticmethod
    def _render(inp) -> bytes:
        from .core.render import render_crew_png

        return render_crew_png(inp)
