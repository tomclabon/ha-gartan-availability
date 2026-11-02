"""Data coordinator: hourly full week, 5-minute today, call-out baseline, repairs."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta

from aiohttp import DummyCookieJar
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_APPLIANCES,
    CONF_BASE_URL,
    CONF_BRIGADE_ID,
    CONF_BRIGADE_NAME,
    CONF_ME,
    DOMAIN,
    MAX_CAPTURES,
    STALE_AFTER,
    TODAY_INTERVAL,
    TODAY_STALE_AFTER,
    WEEK_DAYS,
    WEEK_INTERVAL,
)
from .core.client import AuthError, FetchError, GartanClient
from .core.const import STATUS_OFF_STATION
from .core.parse import DaySchedule, parse_day
from .core.view import CoreConfig, View, appliance_labels, build_view

_LOGGER = logging.getLogger(__name__)


def opt(entry: ConfigEntry, key: str, default=None):
    if key in entry.options:
        return entry.options[key]
    return entry.data.get(key, default)


def selected_appliances(entry: ConfigEntry) -> list[str]:
    return list(opt(entry, CONF_APPLIANCES, []) or [])


class GartanCoordinator(DataUpdateCoordinator[View]):
    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, config_entry=entry, update_interval=TODAY_INTERVAL
        )
        self.cfg = CoreConfig(my_name=(opt(entry, CONF_ME, "") or "").strip())
        self._session = async_create_clientsession(
            hass, cookie_jar=DummyCookieJar(), auto_cleanup=False
        )
        self._client = GartanClient(
            self._session,
            entry.data[CONF_BASE_URL],
            entry.data["username"],
            entry.data["password"],
            entry.data[CONF_BRIGADE_ID],
            entry.data[CONF_BRIGADE_NAME],
        )
        self.client = self._client  # shared with the history loader (requests are serialised)
        self._store: Store = Store(hass, 2, f"{DOMAIN}.{entry.entry_id}")
        self._days: dict[date, DaySchedule] = {}
        self._raw: dict[date, str] = {}
        self._week_at: datetime | None = None
        self._baseline: dict[str, dict[str, str]] = {}
        self._captured: set[str] = set()
        self._issue_ids: set[str] = set()
        self.week_interval: timedelta = WEEK_INTERVAL
        self.last_success: datetime | None = None
        self.fetched_at: dict[date, datetime] = {}  # last successful fetch per day
        self.last_error: str | None = None
        self.known_appliances: list[str] = []
        self._unsub_tick = async_track_time_change(
            hass, self._tick, minute=[0, 15, 30, 45], second=2
        )

    # -- lifecycle ---------------------------------------------------------
    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        base = data.get("baseline", {})
        if isinstance(base, dict) and all(isinstance(v, dict) for v in base.values()):
            self._baseline = base

    @callback
    def async_cleanup(self) -> None:
        self._unsub_tick()
        self.hass.async_create_task(self._session.close())
        for issue_id in self._issue_ids:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        self._issue_ids.clear()

    @callback
    def _tick(self, _now) -> None:
        """Slot boundary: re-evaluate entity states from the stored timeline."""
        if self.data is not None:
            self.async_update_listeners()

    # -- runtime settings (number entities) -------------------------------
    @property
    def today_stale_after(self) -> timedelta:
        return max(TODAY_STALE_AFTER, 3 * (self.update_interval or TODAY_INTERVAL))

    @property
    def day_stale_after(self) -> timedelta:
        return max(STALE_AFTER, 2 * self.week_interval)

    async def async_set_today_interval(self, minutes: float) -> None:
        self.update_interval = timedelta(minutes=minutes)
        await self.async_request_refresh()  # reschedules with the new interval

    def set_week_interval(self, minutes: float) -> None:
        self.week_interval = timedelta(minutes=minutes)

    # -- fetching ----------------------------------------------------------
    def _week_due(self, today: date) -> bool:
        if self._week_at is None or dt_util.utcnow() - self._week_at >= self.week_interval - timedelta(seconds=30):
            return True
        return any(today + timedelta(days=i) not in self._days for i in range(WEEK_DAYS))

    async def _async_update_data(self) -> View:
        tz = dt_util.get_default_time_zone()
        now = dt_util.utcnow()
        today = dt_util.now().date()
        wanted = (
            [today + timedelta(days=i) for i in range(WEEK_DAYS)]
            if self._week_due(today)
            else [today]
        )
        failed: list[str] = []
        for day in wanted:
            try:
                html = await self._client.fetch_day(day)
            except AuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except FetchError as err:
                failed.append(f"{day}: {err}")
                continue
            self._raw[day] = html
            self.fetched_at[day] = now
            self._days[day] = await self.hass.async_add_executor_job(
                parse_day, html, day, tz
            )
        if len(wanted) > 1 and not failed:
            self._week_at = now
        for stale in [d for d in self._days if d < today]:
            self._days.pop(stale, None)
            self._raw.pop(stale, None)
            self.fetched_at.pop(stale, None)

        if failed:
            self.last_error = "; ".join(failed)
            _LOGGER.warning("Gartan fetch problems: %s", self.last_error)
        else:
            self.last_error = None
        if not any(f.startswith(str(today)) for f in failed):
            self.last_success = now
        elif today not in self._days:
            raise UpdateFailed(self.last_error or "no schedule for today")

        view = build_view(self._days.values(), self.cfg, self._baseline, now)
        for label in selected_appliances(self.config_entry):
            if label not in view.appliances:
                view.issues[f"appliance_missing_{label}"] = (
                    f"Appliance {label!r} is no longer in the schedule"
                )
        self.known_appliances = appliance_labels(self._days.values())
        if view.baseline != self._baseline:
            self._baseline = view.baseline
            self._store.async_delay_save(lambda: {"baseline": self._baseline}, 30)
        await self._maybe_capture(view, today)
        self._sync_issues(view, now)
        return view

    # -- attention / repairs ---------------------------------------------
    def attention(self, view: View | None, now: datetime) -> dict[str, str]:
        out = dict(view.issues) if view else {}
        if self.last_error:
            out["fetch_error"] = self.last_error
        if self.last_success and now - self.last_success > self.day_stale_after:
            out["stale"] = f"No successful fetch since {self.last_success.isoformat()}"
        return out

    def _sync_issues(self, view: View, now: datetime) -> None:
        current = self.attention(view, now)
        wanted = {f"attention_{k}" for k in current}
        for key, detail in current.items():
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"attention_{key}",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="attention",
                translation_placeholders={"detail": detail},
            )
        for gone in self._issue_ids - wanted:
            ir.async_delete_issue(self.hass, DOMAIN, gone)
        self._issue_ids = wanted

    # -- raw capture of interesting responses ------------------------------
    async def _maybe_capture(self, view: View, today: date) -> None:
        reasons = set(view.issues)
        if any(
            STATUS_OFF_STATION in a.raw or a.deployed for a in view.appliances.values()
        ):
            reasons.add("off_station")
        new = reasons - self._captured
        if not new or today not in self._raw:
            return
        self._captured |= new
        payload = json.dumps({"d": self._raw[today]})
        stamp = dt_util.now().strftime("%Y%m%d-%H%M%S")
        name = f"{stamp}_{'+'.join(sorted(new))}"[:120].replace("/", "_").replace(":", "-")
        folder = self.hass.config.path("gartan_availability_captures")
        await self.hass.async_add_executor_job(_write_capture, folder, name, payload)


def _write_capture(folder: str, name: str, payload: str) -> None:
    import os

    os.makedirs(folder, exist_ok=True)
    files = sorted(os.listdir(folder))
    for old in files[: max(0, len(files) - MAX_CAPTURES + 1)]:
        os.remove(os.path.join(folder, old))
    with open(os.path.join(folder, f"{name}.json"), "w", encoding="utf-8") as fh:
        fh.write(payload)
