"""Check platform APIs against an installed Home Assistant release."""

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

pytest.importorskip("homeassistant")

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.zonopnaam import (
    ZonopnaamData,
    async_setup_entry,
    async_unload_entry,
    sensor,
)
from custom_components.zonopnaam.api import CannotConnect, InvalidAuth
from custom_components.zonopnaam.config_flow import ZonopnaamConfigFlow
from custom_components.zonopnaam.coordinator import ZonopnaamCoordinator
from custom_components.zonopnaam.gas import parse_gas_prices
from custom_components.zonopnaam.prices import TIME_ZONE, parse_prices

FIXTURES = Path(__file__).parent / "fixtures"


def data():
    now = datetime(2026, 9, 27, 12, tzinfo=TIME_ZONE)
    electricity = parse_prices(
        (FIXTURES / "pricing_today.html").read_text(), now.date()
    )
    gas = parse_gas_prices((FIXTURES / "pricing_gas.html").read_text())
    return now, electricity, gas


@pytest.mark.asyncio
async def test_sensor_platform_units_values_and_chart_attributes(monkeypatch):
    now, electricity, gas = data()
    monkeypatch.setattr(sensor.dt_util, "utcnow", lambda: now)
    entry = SimpleNamespace(
        entry_id="test",
        runtime_data=ZonopnaamData(
            None,
            SimpleNamespace(data=electricity, last_update_success=True),
            SimpleNamespace(data=gas, last_update_success=True),
        ),
    )
    added = []
    await sensor.async_setup_entry(None, entry, added.extend)
    assert len(added) == 11
    by_key = {entity.entity_description.key: entity for entity in added}
    for key, unit in (("current_price", "EUR/kWh"), ("current_gas_price", "EUR/m³")):
        entity = by_key[key]
        assert entity.native_unit_of_measurement == unit
        assert entity.state_class == SensorStateClass.MEASUREMENT
        assert (
            entity.device_class is None
        )  # A rate is not a cumulative monetary sensor.
        assert entity.available
        assert isinstance(entity.native_value, float)
    assert by_key["current_gas_price"].native_value == 1.6523
    assert by_key["next_gas_price"].native_value == 1.6524
    assert len(by_key["avg_price"].extra_state_attributes["prices_today"]) == 24
    assert (
        by_key["highest_price_time_today"].device_class == SensorDeviceClass.TIMESTAMP
    )
    assert by_key["highest_price_time_today"].native_value.tzinfo is not None
    before = by_key["current_price"].native_value
    now += timedelta(hours=1)
    assert by_key["current_price"].native_value != before
    entry.runtime_data.gas.last_update_success = False
    assert not by_key["current_gas_price"].available
    assert by_key["current_price"].available


@pytest.mark.asyncio
async def test_no_gas_link_only_creates_electricity_sensors():
    _, electricity, _ = data()
    entry = SimpleNamespace(
        entry_id="test",
        runtime_data=ZonopnaamData(
            None,
            SimpleNamespace(data=electricity, last_update_success=True),
            None,
        ),
    )
    added = []
    await sensor.async_setup_entry(None, entry, added.extend)
    assert len(added) == 9


@pytest.mark.asyncio
async def test_timer_changes_state_without_fetching(monkeypatch):
    _, electricity, _ = data()
    coordinator = Mock(data=electricity, last_update_success=True)
    entity = sensor.ZonopnaamPriceSensor(
        coordinator, SimpleNamespace(entry_id="test"), sensor.DESCRIPTIONS[0]
    )
    entity.hass = Mock()
    entity.async_write_ha_state = Mock()
    cancel = Mock()
    track = Mock(return_value=cancel)
    monkeypatch.setattr(sensor, "async_track_utc_time_change", track)
    await entity.async_added_to_hass()
    assert track.call_args.kwargs == {"minute": [0, 15, 30, 45], "second": 0}
    track.call_args.args[1](None)
    entity.async_write_ha_state.assert_called_once()
    coordinator.async_request_refresh.assert_not_called()
    entity._call_on_remove_callbacks()
    cancel.assert_called_once()


@pytest.mark.asyncio
async def test_config_form_uses_current_schema_api():
    flow = ZonopnaamConfigFlow()
    flow.hass = Mock()
    result = await flow.async_step_user()
    assert result["step_id"] == "user"
    assert result["data_schema"]({"username": "user", "password": "secret"}) == {
        "username": "user",
        "password": "secret",
    }


@pytest.mark.asyncio
async def test_two_hour_coordinator_and_error_mapping():
    hass = Mock()
    client = Mock(async_get_prices=AsyncMock(), async_get_gas_prices=AsyncMock())
    coordinator = ZonopnaamCoordinator(hass, client, None)
    assert coordinator.update_interval == timedelta(hours=2)
    await coordinator._async_update_data()
    client.async_get_prices.assert_awaited_once()
    client.async_get_prices.side_effect = CannotConnect
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    client.async_get_prices.side_effect = InvalidAuth
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
    gas = ZonopnaamCoordinator(hass, client, None, "gas")
    assert gas.update_interval == timedelta(hours=2)
    await gas._async_update_data()
    client.async_get_gas_prices.assert_awaited_once()


@pytest.mark.asyncio
async def test_entry_setup_and_unload():
    hass = Mock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    entry = SimpleNamespace(data={"username": "user", "password": "secret"})
    session = Mock()
    client = Mock(async_login=AsyncMock(), gas_pricing_path="/mc/123/pricing-gas/")
    electricity = Mock(async_config_entry_first_refresh=AsyncMock())
    gas = Mock(async_refresh=AsyncMock())
    with (
        patch(
            "custom_components.zonopnaam.async_create_clientsession",
            return_value=session,
        ),
        patch("custom_components.zonopnaam.ZonopnaamClient", return_value=client),
        patch(
            "custom_components.zonopnaam.ZonopnaamCoordinator",
            side_effect=[electricity, gas],
        ),
    ):
        assert await async_setup_entry(hass, entry)
    assert entry.runtime_data.client is client
    electricity.async_config_entry_first_refresh.assert_awaited_once()
    gas.async_refresh.assert_awaited_once()
    hass.config_entries.async_forward_entry_setups.assert_awaited_once()
    assert await async_unload_entry(hass, entry)
    client.session.detach.assert_called_once()


@pytest.mark.parametrize(
    "unit, meter_unit, price, expected",
    [
        ("EUR/kWh", "kWh", 0.3, 0.3),
        ("EUR/kWh", "Wh", 0.3, 0.0003),
        ("EUR/m³", "m³", 1.65, 1.65),
    ],
)
def test_energy_dashboard_reads_our_unit_prices(unit, meter_unit, price, expected):
    from homeassistant.components.energy.sensor import (
        VALID_ENERGY_UNITS,
        VALID_ENERGY_UNITS_GAS,
        EnergyCostSensor,
    )
    from homeassistant.core import State

    cost = object.__new__(EnergyCostSensor)
    cost.hass = Mock()
    cost._config = {"entity_energy_price": "sensor.zonopnaam_current_price"}
    cost.hass.states.get.return_value = State(
        "sensor.zonopnaam_current_price",
        str(price),
        {"unit_of_measurement": unit},
    )
    units = VALID_ENERGY_UNITS_GAS if unit == "EUR/m³" else VALID_ENERGY_UNITS
    value, price_unit = cost._get_energy_price(units, None)
    assert price_unit == unit.partition("/")[2]
    assert cost._convert_energy_price(value, price_unit, meter_unit) == pytest.approx(
        expected
    )
