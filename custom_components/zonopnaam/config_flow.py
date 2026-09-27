"""Set up account credentials in Home Assistant."""

import probatio as pr
from aiohttp import CookieJar
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import CannotConnect, InvalidAuth, UnexpectedResponse, ZonopnaamClient
from .const import DOMAIN


class ZonopnaamConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _validate(self, data):
        session = async_create_clientsession(
            self.hass, auto_cleanup=False, cookie_jar=CookieJar()
        )
        try:
            await ZonopnaamClient(
                session, data[CONF_USERNAME], data[CONF_PASSWORD]
            ).async_login()
        finally:
            session.detach()

    async def async_step_user(self, user_input=None):
        return await self._credentials_step("user", user_input)

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        return await self._credentials_step("reauth_confirm", user_input)

    async def _credentials_step(self, step, user_input):
        errors = {}
        reauth = step == "reauth_confirm"
        if user_input is not None:
            data = dict(user_input)
            if reauth:
                data[CONF_USERNAME] = self._get_reauth_entry().data[CONF_USERNAME]
            else:
                data[CONF_USERNAME] = data[CONF_USERNAME].strip()
                await self.async_set_unique_id(data[CONF_USERNAME])
                self._abort_if_unique_id_configured()
            try:
                await self._validate(data)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except UnexpectedResponse:
                errors["base"] = "unexpected_response"
            else:
                if reauth:
                    return self.async_update_reload_and_abort(
                        self._get_reauth_entry(), data_updates=data
                    )
                return self.async_create_entry(title=data[CONF_USERNAME], data=data)
        schema = {}
        if not reauth:
            schema[pr.Required(CONF_USERNAME)] = str
        schema[pr.Required(CONF_PASSWORD)] = TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        )
        return self.async_show_form(
            step_id=step, data_schema=pr.Schema(schema), errors=errors
        )
