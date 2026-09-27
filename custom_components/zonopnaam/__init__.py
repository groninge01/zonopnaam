"""Zonopnaam integration."""

from dataclasses import dataclass

from aiohttp import CookieJar
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import CannotConnect, InvalidAuth, UnexpectedResponse, ZonopnaamClient
from .coordinator import ZonopnaamCoordinator

PLATFORMS = [Platform.SENSOR]


@dataclass
class ZonopnaamData:
    client: ZonopnaamClient
    electricity: ZonopnaamCoordinator
    gas: ZonopnaamCoordinator | None


async def async_setup_entry(hass, entry):
    session = async_create_clientsession(hass, cookie_jar=CookieJar())
    client = ZonopnaamClient(
        session, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
    )
    try:
        await client.async_login()
        coordinator = ZonopnaamCoordinator(hass, client, entry)
        await coordinator.async_config_entry_first_refresh()
        gas = None
        if client.gas_pricing_path:
            gas = ZonopnaamCoordinator(hass, client, entry, "gas")
            # A gas failure must not hide working electricity sensors.
            await gas.async_refresh()
    except InvalidAuth as err:
        session.detach()
        raise ConfigEntryAuthFailed("Zonopnaam login failed") from err
    except (CannotConnect, UnexpectedResponse) as err:
        session.detach()
        raise ConfigEntryNotReady("Zonopnaam unavailable or changed") from err
    except BaseException:
        session.detach()
        raise
    entry.runtime_data = ZonopnaamData(client, coordinator, gas)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass, entry):
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        entry.runtime_data.client.session.detach()
    return unloaded
