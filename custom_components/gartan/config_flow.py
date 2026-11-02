"""Config, reauth and options flows."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from aiohttp import DummyCookieJar
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType
from homeassistant.util import dt as dt_util

from .const import (
    CONF_APPLIANCE,
    CONF_BASE_URL,
    CONF_BRIGADE_ID,
    CONF_BRIGADE_NAME,
    CONF_DISPLAY_NAMES,
    CONF_DUAL_ROLE,
    CONF_ME,
    CONF_MY_LABEL,
    CONF_SLUG,
    CONF_WHAT_IF,
    DEFAULT_APPLIANCE,
    DEFAULT_BASE_URL,
    DEFAULT_BRIGADE_ID,
    DEFAULT_BRIGADE_NAME,
    DEFAULT_DUAL_ROLE,
    DEFAULT_ME,
    DEFAULT_MY_LABEL,
    DEFAULT_SLUG,
    DOMAIN,
)
from .core.client import AuthError, FetchError, GartanClient
from .core.model import build_timeline
from .core.parse import find_appliance, parse_day
from .core.view import find_me

MULTILINE = TextSelector(TextSelectorConfig(multiline=True))
PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


async def _validate(hass: HomeAssistant, data: dict[str, Any]) -> str | None:
    """Return an error key, or None if the settings work."""
    session = async_create_clientsession(hass, cookie_jar=DummyCookieJar(), auto_cleanup=False)
    try:
        return await _validate_with(hass, session, data)
    finally:
        await session.close()


async def _validate_with(hass: HomeAssistant, session, data: dict[str, Any]) -> str | None:
    client = GartanClient(
        session,
        data[CONF_BASE_URL],
        data["username"],
        data["password"],
        data[CONF_BRIGADE_ID],
        data[CONF_BRIGADE_NAME],
    )
    tz = dt_util.get_default_time_zone()
    today = dt_util.now().date()
    try:
        html = await client.fetch_day(today)
    except AuthError:
        return "invalid_auth"
    except FetchError:
        return "cannot_connect"
    day = parse_day(html, today, tz)
    if not day.people:
        return "no_schedule"
    if find_appliance(day.appliances, data[CONF_APPLIANCE]) is None:
        return "appliance_not_found"
    if find_me(build_timeline([day], data[CONF_APPLIANCE]), data[CONF_ME]) is None:
        return "me_not_found"
    return None


class GartanConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}
        if user_input is not None:
            err = await _validate(self.hass, user_input)
            if err is None:
                await self.async_set_unique_id(
                    f"{user_input[CONF_BASE_URL]}|{user_input['username']}".lower()
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Gartan", data=user_input)
            errors["base"] = err
        d = user_input or {}
        schema = vol.Schema(
            {
                vol.Required("username", default=d.get("username", "")): str,
                vol.Required("password"): PASSWORD,
                vol.Required(CONF_BASE_URL, default=d.get(CONF_BASE_URL, DEFAULT_BASE_URL)): str,
                vol.Required(CONF_BRIGADE_ID, default=d.get(CONF_BRIGADE_ID, DEFAULT_BRIGADE_ID)): int,
                vol.Required(CONF_BRIGADE_NAME, default=d.get(CONF_BRIGADE_NAME, DEFAULT_BRIGADE_NAME)): str,
                vol.Required(CONF_ME, default=d.get(CONF_ME, DEFAULT_ME)): str,
                vol.Required(CONF_MY_LABEL, default=d.get(CONF_MY_LABEL, DEFAULT_MY_LABEL)): str,
                vol.Required(CONF_APPLIANCE, default=d.get(CONF_APPLIANCE, DEFAULT_APPLIANCE)): str,
                vol.Required(CONF_SLUG, default=d.get(CONF_SLUG, DEFAULT_SLUG)): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            data = {**entry.data, "password": user_input["password"]}
            err = await _validate(self.hass, data)
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

        def cur(key, default=""):
            return entry.options.get(key, entry.data.get(key, default))

        if user_input is not None:
            return self.async_create_entry(data=user_input)
        schema = vol.Schema(
            {
                vol.Required(CONF_ME, default=cur(CONF_ME, DEFAULT_ME)): str,
                vol.Required(CONF_APPLIANCE, default=cur(CONF_APPLIANCE, DEFAULT_APPLIANCE)): str,
                vol.Optional(CONF_DUAL_ROLE, default=cur(CONF_DUAL_ROLE, DEFAULT_DUAL_ROLE)): MULTILINE,
                vol.Optional(CONF_DISPLAY_NAMES, default=cur(CONF_DISPLAY_NAMES)): MULTILINE,
                vol.Optional(CONF_WHAT_IF, default=cur(CONF_WHAT_IF)): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
