"""Fetch one price page for all price sensors."""

import logging
from datetime import timedelta

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CannotConnect, InvalidAuth, UnexpectedResponse

_LOGGER = logging.getLogger(__name__)


class ZonopnaamCoordinator(DataUpdateCoordinator):
    """Poll prices every two hours; advance through cached intervals locally."""

    def __init__(self, hass, client, entry, fuel="electricity"):
        super().__init__(
            hass,
            _LOGGER,
            name=f"Zonopnaam {fuel} prices",
            config_entry=entry,
            update_interval=timedelta(hours=2),
        )
        self.client = client
        self.fuel = fuel

    async def _async_update_data(self):
        try:
            if self.fuel == "gas":
                return await self.client.async_get_gas_prices()
            return await self.client.async_get_prices()
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed("Zonopnaam login failed") from err
        except CannotConnect as err:
            raise UpdateFailed("Cannot connect to Zonopnaam") from err
        except UnexpectedResponse as err:
            raise UpdateFailed(f"Unsupported Zonopnaam price page: {err}") from err
        finally:
            cookies = self.client.export_cookies()
            if cookies != self.config_entry.data.get("cookies", {}):
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data={"cookies": cookies}
                )
