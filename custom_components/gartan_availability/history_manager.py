"""Loads and maintains the history ledger in the background.

- First run: backfills weekly contract figures (two weeks per request) and then
  each past day (one request per day, for call-outs and your on-call minutes),
  newest first, throttled. Progress is saved as it goes, so a restart resumes
  where it stopped instead of starting again.
- Every night: re-fetches the last few weeks/days to pick up late corrections.
- "Rebuild history" clears everything and starts again.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta
from typing import Callable

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_EBID,
    CONF_HISTORY_YEARS,
    DEFAULT_HISTORY_YEARS,
    DOMAIN,
    HISTORY_EMPTY_STOP,
    HISTORY_REFRESH_DAYS,
    HISTORY_REFRESH_WEEKS,
    HISTORY_REQUEST_GAP,
    HISTORY_RETRY,
)
from .coordinator import GartanCoordinator, opt
from .core.client import AuthError, FetchError
from .core.history import Ledger, record_day
from .core.parse import employee_rows_dates, parse_day, parse_employee_weeks

_LOGGER = logging.getLogger(__name__)


class HistoryManager:
    def __init__(self, hass: HomeAssistant, coordinator: GartanCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.entry = coordinator.config_entry
        self._store: Store = Store(hass, 1, f"{DOMAIN}.{self.entry.entry_id}.history")
        self.ledger = Ledger()
        self.status = "starting"
        self.detail = ""
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._refresh_due = True
        self._listeners: list[Callable[[], None]] = []
        self._unsub_nightly: CALLBACK_TYPE | None = None
        self.version = 0  # bumped on every ledger change
        self.request_gap: float = HISTORY_REQUEST_GAP  # seconds; set by a number entity

    # -- lifecycle ---------------------------------------------------------
    @property
    def years(self) -> int:
        return int(opt(self.entry, CONF_HISTORY_YEARS, DEFAULT_HISTORY_YEARS) or 0)

    async def async_load(self) -> None:
        self.ledger = Ledger.from_json(await self._store.async_load())

    def start(self) -> None:
        if self.years <= 0:
            self.status = "disabled"
            return
        self._unsub_nightly = async_track_time_change(
            self.hass, self._nightly, hour=3, minute=30, second=0
        )
        self._task = self.entry.async_create_background_task(
            self.hass, self._run(), f"{DOMAIN} history"
        )

    @callback
    def stop(self) -> None:
        if self._unsub_nightly:
            self._unsub_nightly()
            self._unsub_nightly = None
        if self._task:
            self._task.cancel()
            self._task = None

    async def async_rebuild(self) -> None:
        self.stop()
        self.ledger = Ledger()
        await self._store.async_save(self.ledger.to_json())
        self._changed()
        self._refresh_due = True
        self.start()

    @callback
    def _nightly(self, _now) -> None:
        self._refresh_due = True
        self._wake.set()

    # -- listeners (entities) ---------------------------------------------
    @callback
    def async_add_listener(self, cb: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    @callback
    def _changed(self) -> None:
        self.version += 1
        for cb in list(self._listeners):
            cb()

    def _save_soon(self) -> None:
        self._store.async_delay_save(self.ledger.to_json, 10)

    # -- the loader --------------------------------------------------------
    async def _run(self) -> None:
        while self.coordinator.data is None:
            await asyncio.sleep(10)
        while True:
            try:
                ebid, me_name = self._identity()
                if ebid is None:
                    self._set("waiting", "Employee id not found: set it in the options")
                else:
                    refresh = self._refresh_due
                    self._refresh_due = False
                    await self._load_weeks(ebid, refresh)
                    await self._load_days(me_name, refresh)
                    self._set("complete", "")
                    from .statistics import async_import_history

                    async_import_history(self.hass, self.entry, self.ledger)
            except AuthError:
                self._set("error", "Gartan login failed")
                return
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - keep the loader alive
                _LOGGER.exception("History load failed")
                self._set("error", str(err))
                await asyncio.sleep(HISTORY_RETRY)
                continue
            self._wake.clear()
            await self._wake.wait()

    def _identity(self) -> tuple[int | None, str]:
        view = self.coordinator.data
        me = view.timeline.series.get(view.me_key) if view and view.me_key else None
        override = opt(self.entry, CONF_EBID, None)
        ebid = int(override) if override else (me.ebid if me else None)
        return ebid, (me.name if me else "")

    def _set(self, status: str, detail: str) -> None:
        if (status, detail) != (self.status, self.detail):
            self.status, self.detail = status, detail
            self._changed()

    async def _fetch(self, coro_factory):
        """Run one throttled request, retrying network problems."""
        while True:
            try:
                result = await coro_factory()
            except FetchError as err:
                self._set("retrying", str(err))
                await asyncio.sleep(HISTORY_RETRY)
                continue
            await asyncio.sleep(self.request_gap)
            return result

    def _today(self) -> date:
        return dt_util.now().date()

    def _cutoff(self) -> date:
        return self._today() - timedelta(days=round(365.25 * self.years))

    async def _load_weeks(self, ebid: int, refresh: bool) -> None:
        client = self.coordinator.client
        today = self._today()
        monday = today - timedelta(days=today.weekday())
        cutoff = self._cutoff()
        recent = {monday - timedelta(weeks=k) for k in range(HISTORY_REFRESH_WEEKS + 1)}
        empties = 0
        w = monday
        while w >= cutoff:
            pair = (w, w + timedelta(weeks=1))
            have = all(d in self.ledger.weeks for d in pair) or w in self.ledger.empty_windows
            if have and not (refresh and (pair[0] in recent or pair[1] in recent)):
                empties = empties + 1 if w in self.ledger.empty_windows else 0
            else:
                self._set("loading hours", f"weeks from {w:%d %b %Y}")
                html = await self._fetch(lambda w=w: client.fetch_employee(w, ebid, 14))
                weeks = await self.hass.async_add_executor_job(parse_employee_weeks, html)
                if not employee_rows_dates(html) or not weeks:
                    self.ledger.empty_windows.add(w)
                    empties += 1
                else:
                    self.ledger.empty_windows.discard(w)
                    self.ledger.weeks.update(weeks)
                    empties = 0
                self._save_soon()
                self._changed()
            if empties >= HISTORY_EMPTY_STOP and self.ledger.weeks:
                break  # well before you started
            w -= timedelta(weeks=2)

    async def _load_days(self, me_name: str, refresh: bool) -> None:
        client = self.coordinator.client
        tz = dt_util.get_default_time_zone()
        today = self._today()
        first = max(self._cutoff(), self.ledger.start or self._cutoff())
        recent = {today - timedelta(days=k) for k in range(1, HISTORY_REFRESH_DAYS + 1)}
        d = today - timedelta(days=1)
        done = 0
        while d >= first:
            if d not in self.ledger.days or (refresh and d in recent):
                self._set("loading call-outs", f"{d:%d %b %Y}")
                html = await self._fetch(lambda d=d: client.fetch_day(d))
                parsed = await self.hass.async_add_executor_job(parse_day, html, d, tz)
                self.ledger.days[d] = record_day(parsed, me_name)
                done += 1
                if done % 14 == 0:
                    self._save_soon()
                    self._changed()
            d -= timedelta(days=1)
        self._save_soon()
        self._changed()

    # -- progress for the diagnostic sensor -------------------------------
    def progress(self) -> dict:
        first = max(self._cutoff(), self.ledger.start or self._cutoff())
        total_days = max(0, (self._today() - first).days)
        have = sum(1 for d in self.ledger.days if first <= d < self._today())
        return {
            "detail": self.detail,
            "weeks_loaded": len(self.ledger.weeks),
            "days_loaded": have,
            "days_total": total_days,
            "started": self.ledger.start.isoformat() if self.ledger.start else None,
            "history_years": self.years,
        }
