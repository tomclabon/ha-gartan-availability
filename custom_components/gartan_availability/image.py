"""Pictures for the companion app's Picture widget (and dashboards).

- image.gartan_availability_<appliance>_week: 7 days for an appliance and you (4x1)
- image.gartan_availability_crew: who is on now (until) and off (from) (3x1)
- image.gartan_availability_<appliance>_call_outs: recent call-outs and counts (1x1)

All are rendered fresh on every request. image_last_updated changes on every
data update, slot boundary and history change, which tells dashboards to re-fetch.
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
    for label in selected_appliances(entry):
        entities += [WeekImage(c, label), CallOutsImage(c, label)]
    async_add_entities(entities)


class _RenderedImage:
    """Mixin: listed first so its hooks run before CoordinatorEntity's."""

    _attr_content_type = "image/png"
    _appliance = ""

    def _init_image(self, coordinator) -> None:
        ImageEntity.__init__(self, coordinator.hass)
        self._attr_image_last_updated = dt_util.utcnow()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.history.async_add_listener(self._bump))

    @callback
    def _bump(self) -> None:
        self._attr_image_last_updated = dt_util.utcnow()
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_image_last_updated = dt_util.utcnow()
        super()._handle_coordinator_update()

    def _extra(self, now) -> dict:
        return {}

    @staticmethod
    def _render(inp) -> bytes:
        raise NotImplementedError

    async def async_image(self) -> bytes | None:
        view = self.coordinator.data
        if view is None:
            return None
        from .core.render import RenderInput

        now = dt_util.utcnow()
        inp = RenderInput(
            view=view,
            appliance=self._appliance,
            tz=dt_util.get_default_time_zone(),
            now=now,
            fetched=dict(self.coordinator.fetched_at),  # keyed by local date
            today_stale_after=self.coordinator.today_stale_after,
            day_stale_after=self.coordinator.day_stale_after,
            **self._extra(now),
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


class CallOutsImage(_RenderedImage, ApplianceEntity, ImageEntity):
    _attr_icon = "mdi:fire-truck"

    def __init__(self, coordinator, label: str) -> None:
        ApplianceEntity.__init__(self, coordinator, label, "call_outs_picture", "Call-outs")
        self._appliance = label
        self._init_image(coordinator)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    def _extra(self, now) -> dict:
        from .core.history import all_callouts, callout_counts

        led = self.coordinator.history.ledger
        callouts = all_callouts(led, self.coordinator.data, now)
        tz = dt_util.get_default_time_zone()
        return {
            "callouts": callouts,
            "counts": callout_counts(callouts, led, self._appliance, now, tz),
        }

    @staticmethod
    def _render(inp) -> bytes:
        from .core.render import render_callouts_png

        return render_callouts_png(inp)


class CrewImage(_RenderedImage, GartanEntity, ImageEntity):
    _attr_icon = "mdi:account-group"

    def __init__(self, coordinator) -> None:
        GartanEntity.__init__(self, coordinator, "crew", "Crew")
        self._init_image(coordinator)

    @staticmethod
    def _render(inp) -> bytes:
        from .core.render import render_crew_png

        return render_crew_png(inp)
