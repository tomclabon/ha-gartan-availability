"""Config, reauth and options flows.

Setup asks only for the site URL and login. The station comes from the schedule
page's station list, your own row is detected (the only one with editable cells),
and appliances are chosen from the rows Gartan returns.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from aiohttp import DummyCookieJar
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONF_APPLIANCES,
    CONF_BASE_URL,
    CONF_BRIGADE_ID,
    CONF_BRIGADE_NAME,
    CONF_EBID,
    CONF_HISTORY_YEARS,
    CONF_ME,
    DEFAULT_HISTORY_YEARS,
    DOMAIN,
)
from .core.client import AuthError, FetchError, GartanClient
from .core.model import build_timeline
from .core.parse import Brigade, DaySchedule, parse_day
from .core.view import appliance_labels, find_me

PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
URL = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))


def _select(options, multiple: bool = False, custom: bool = False) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=options,
            multiple=multiple,
            custom_value=custom,
            mode=SelectSelectorMode.LIST if multiple else SelectSelectorMode.DROPDOWN,
        )
    )


class _Session:
    """A cookie-less session for the duration of one flow step."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.session = async_create_clientsession(
            hass, cookie_jar=DummyCookieJar(), auto_cleanup=False
        )

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc):
        await self.session.close()


def _client(session, data: dict[str, Any]) -> GartanClient:
    return GartanClient(
        session,
        data[CONF_BASE_URL],
        data["username"],
        data["password"],
        data.get(CONF_BRIGADE_ID),
        data.get(CONF_BRIGADE_NAME),
    )


async def _brigades(hass, data) -> tuple[str | None, list[Brigade]]:
    async with _Session(hass) as session:
        try:
            return None, await _client(session, data).fetch_brigades()
        except AuthError:
            return "invalid_auth", []
        except FetchError:
            return "cannot_connect", []


async def _today(hass, data) -> tuple[str | None, DaySchedule | None]:
    async with _Session(hass) as session:
        try:
            html = await _client(session, data).fetch_day(dt_util.now().date())
        except AuthError:
            return "invalid_auth", None
        except FetchError:
            return "cannot_connect", None
    day = await hass.async_add_executor_job(
        parse_day, html, dt_util.now().date(), dt_util.get_default_time_zone()
    )
    if not day.people:
        return "no_schedule", None
    if not day.appliances:
        return "no_appliances", None
    return None, day


class GartanConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._brigade_list: list[Brigade] = []
        self._day: DaySchedule | None = None

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**user_input, CONF_BASE_URL: user_input[CONF_BASE_URL].rstrip("/")}
            err, brigades = await _brigades(self.hass, data)
            if err is None:
                self._data, self._brigade_list = data, brigades
                if len(brigades) == 1:
                    return await self._use_brigade(brigades[0])
                return await self.async_step_brigade()
            errors["base"] = err
        d = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(CONF_BASE_URL, default=d.get(CONF_BASE_URL, "https://")): URL,
                vol.Required("username", default=d.get("username", "")): str,
                vol.Required("password"): PASSWORD,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_brigade(self, user_input=None):
        """Only shown when the login can see more than one station."""
        if user_input is not None:
            chosen = next(
                b for b in self._brigade_list if str(b.id) == user_input[CONF_BRIGADE_ID]
            )
            return await self._use_brigade(chosen)
        options = [SelectOptionDict(value=str(b.id), label=b.name) for b in self._brigade_list]
        default = next((str(b.id) for b in self._brigade_list if b.selected), vol.UNDEFINED)
        return self.async_show_form(
            step_id="brigade",
            data_schema=vol.Schema(
                {vol.Required(CONF_BRIGADE_ID, default=default): _select(options)}
            ),
        )

    async def _use_brigade(self, brigade: Brigade):
        self._data[CONF_BRIGADE_ID] = brigade.id
        self._data[CONF_BRIGADE_NAME] = brigade.name
        await self.async_set_unique_id(
            f"{self._data[CONF_BASE_URL]}|{self._data['username']}|{brigade.id}".lower()
        )
        self._abort_if_unique_id_configured()
        err, day = await _today(self.hass, self._data)
        if err is not None:
            return self.async_abort(reason=err)
        self._day = day
        if find_me(build_timeline([day])) is None:
            return await self.async_step_me()
        return await self.async_step_appliances()

    async def async_step_me(self, user_input=None):
        """Only shown if your own row could not be detected automatically."""
        if user_input is not None:
            self._data[CONF_ME] = user_input[CONF_ME]
            return await self.async_step_appliances()
        names = sorted({p.name for p in self._day.people if not p.is_import})
        return self.async_show_form(
            step_id="me", data_schema=vol.Schema({vol.Required(CONF_ME): _select(names)})
        )

    async def async_step_appliances(self, user_input=None):
        labels = appliance_labels([self._day])
        if user_input is not None:
            data = {**self._data, CONF_APPLIANCES: user_input[CONF_APPLIANCES]}
            return self.async_create_entry(title=f"Gartan Availability {data[CONF_BRIGADE_NAME]}", data=data)
        return self.async_show_form(
            step_id="appliances",
            data_schema=vol.Schema(
                {vol.Required(CONF_APPLIANCES, default=labels): _select(labels, multiple=True)}
            ),
        )

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            data = {**entry.data, "password": user_input["password"]}
            err, _ = await _today(self.hass, data)
            if err is None:
                return self.async_update_reload_and_abort(entry, data=data)
            errors["base"] = err
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required("password"): PASSWORD}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return GartanOptionsFlow()


class GartanOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        entry = self.config_entry

        def cur(key, default=None):
            return entry.options.get(key, entry.data.get(key, default))

        if user_input is not None:
            return self.async_create_entry(data=user_input)
        coordinator = getattr(entry, "runtime_data", None)
        labels = list(getattr(coordinator, "known_appliances", []) or [])
        for label in cur(CONF_APPLIANCES, []) or []:
            if label not in labels:
                labels.append(label)
        schema = vol.Schema(
            {
                vol.Required(CONF_APPLIANCES, default=cur(CONF_APPLIANCES, [])): _select(
                    labels, multiple=True
                ),
                vol.Optional(CONF_ME, description={"suggested_value": cur(CONF_ME, "")}): str,
                vol.Required(
                    CONF_HISTORY_YEARS, default=cur(CONF_HISTORY_YEARS, DEFAULT_HISTORY_YEARS)
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=10)),
                vol.Optional(CONF_EBID, description={"suggested_value": cur(CONF_EBID, None)}): vol.Coerce(int),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
