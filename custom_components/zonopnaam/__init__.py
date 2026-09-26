"""Zon op Naam integration."""
from aiohttp import CookieJar
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from .api import CannotConnect, InvalidAuth, UnexpectedResponse, ZonopnaamClient


async def async_setup_entry(hass, entry):
    session = async_create_clientsession(hass, cookie_jar=CookieJar())
    client = ZonopnaamClient(session, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    try:
        await client.async_login()
    except InvalidAuth as err:
        session.detach()
        raise ConfigEntryAuthFailed("Zon op Naam login failed") from err
    except (CannotConnect, UnexpectedResponse) as err:
        session.detach()
        raise ConfigEntryNotReady("Zon op Naam unavailable or changed") from err
    except BaseException:
        session.detach()
        raise
    entry.runtime_data = client
    return True


async def async_unload_entry(hass, entry):
    entry.runtime_data.session.detach()
    return True
