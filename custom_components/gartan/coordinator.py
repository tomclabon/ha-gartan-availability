"""Data coordinator: hourly full week, 5-minute today, call-out baseline, repairs."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from aiohttp import DummyCookieJar
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_APPLIANCE,
    CONF_BASE_URL,
    CONF_BRIGADE_ID,
    CONF_BRIGADE_NAME,
    CONF_DISPLAY_NAMES,
    CONF_DUAL_ROLE,
    CONF_ME,
    CONF_WHAT_IF,
    DEFAULT_APPLIANCE,
    DEFAULT_BASE_URL,
    DEFAULT_BRIGADE_ID,
    DEFAULT_BRIGADE_NAME,
    DEFAULT_DUAL_ROLE,
    DEFAULT_ME,
    DOMAIN,
    MAX_CAPTURES,
    STALE_AFTER,
    TODAY_INTERVAL,
    WEEK_DAYS,
    WEEK_INTERVAL,
)
from .core.client import AuthError, FetchError, GartanClient
from .core.const import STATUS_OFF_STATION
from .core.parse import DaySchedule, parse_day
from .core.view import CoreConfig, View, build_view

_LOGGER = logging.getLogger(__name__)


def opt(entry: ConfigEntry, key: str, default=None):
    if key in entry.options:
        return entry.options[key]
    return entry.data.get(key, default)


def parse_lines(text: str, sep: str = "") -> list[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def parse_display_names(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for ln in parse_lines(text):
        if "=" in ln:
            k, v = ln.split("=", 1)
            if k.strip() and v.strip():
                out[k.strip().upper()] = v.strip()
    return out


def core_config(entry: ConfigEntry) -> CoreConfig:
    return CoreConfig(
        appliance_label=opt(entry, CONF_APPLIANCE, DEFAULT_APPLIANCE),
        my_name=opt(entry, CONF_ME, DEFAULT_ME),
        dual_names=frozenset(
            n.upper() for n in parse_lines(opt(entry, CONF_DUAL_ROLE, DEFAULT_DUAL_ROLE))
        ),
        extra_skills=frozenset(opt(entry, CONF_WHAT_IF, "").split()),
        display_names=parse_display_names(opt(entry, CONF_DISPLAY_NAMES, "")),
    )


class GartanCoordinator(DataUpdateCoordinator[View]):
    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, config_entry=entry, update_interval=TODAY_INTERVAL
        )
        self.cfg = core_config(entry)
        self._session = async_create_clientsession(
            hass, cookie_jar=DummyCookieJar(), auto_cleanup=False
        )
        self._client = GartanClient(
            self._session,
            opt(entry, CONF_BASE_URL, DEFAULT_BASE_URL),
            entry.data["username"],
            entry.data["password"],
            opt(entry, CONF_BRIGADE_ID, DEFAULT_BRIGADE_ID),
            opt(entry, CONF_BRIGADE_NAME, DEFAULT_BRIGADE_NAME),
        )
        self._store: Store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self._days: dict[date, DaySchedule] = {}
        self._raw: dict[date, str] = {}
        self._week_at: datetime | None = None
        self._baseline: dict[str, str] = {}
        self._captured: set[str] = set()
        self._issue_ids: set[str] = set()
        self.last_success: datetime | None = None
        self.last_error: str | None = None
        self._unsub_tick = async_track_time_change(
            hass, self._tick, minute=[0, 15, 30, 45], second=2
        )

    # -- lifecycle ---------------------------------------------------------
    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self._baseline = data.get("baseline", {})

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

    # -- fetching ----------------------------------------------------------
    def _week_due(self, today: date) -> bool:
        if self._week_at is None or dt_util.utcnow() - self._week_at >= WEEK_INTERVAL:
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
            self._days[day] = await self.hass.async_add_executor_job(
                parse_day, html, day, tz
            )
        if len(wanted) > 1 and not failed:
            self._week_at = now
        for stale in [d for d in self._days if d < today]:
            self._days.pop(stale, None)
            self._raw.pop(stale, None)

        if failed:
            self.last_error = "; ".join(failed)
            _LOGGER.warning("Gartan fetch problems: %s", self.last_error)
        else:
            self.last_error = None
        if today in wanted and not any(f.startswith(str(today)) for f in failed):
            self.last_success = now
        elif today not in self._days:
            raise UpdateFailed(self.last_error or "no schedule for today")

        view = build_view(self._days.values(), self.cfg, self._baseline, now)
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
        if self.last_success and now - self.last_success > STALE_AFTER:
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
        if view.deployed or any(s == STATUS_OFF_STATION for s in view.timeline.p1_raw):
            reasons.add("off_station")
        new = reasons - self._captured
        if not new or today not in self._raw:
            return
        self._captured |= new
        payload = json.dumps({"d": self._raw[today]})
        stamp = dt_util.now().strftime("%Y%m%d-%H%M%S")
        name = f"{stamp}_{'+'.join(sorted(new))}"[:120].replace("/", "_").replace(":", "-")
        folder = self.hass.config.path("gartan_captures")
        await self.hass.async_add_executor_job(_write_capture, folder, name, payload)


def _write_capture(folder: str, name: str, payload: str) -> None:
    import os

    os.makedirs(folder, exist_ok=True)
    files = sorted(os.listdir(folder))
    for old in files[: max(0, len(files) - MAX_CAPTURES + 1)]:
        os.remove(os.path.join(folder, old))
    with open(os.path.join(folder, f"{name}.json"), "w", encoding="utf-8") as fh:
        fh.write(payload)
