"""Electricity prices with ENTSO-e-compatible chart attributes."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_utc_time_change
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN

PARALLEL_UPDATES = 0

PRICE_NAMES = {
    "current_price": "Current electricity price",
    "next_hour_price": "Next period electricity price",
    "min_price": "Lowest energy price",
    "max_price": "Highest energy price",
    "avg_price": "Average electricity price",
}
DESCRIPTIONS = (
    *(
        SensorEntityDescription(
            key=key,
            name=name,
            native_unit_of_measurement="EUR/kWh",
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:currency-eur",
            suggested_display_precision=5,
        )
        for key, name in PRICE_NAMES.items()
    ),
    *(
        SensorEntityDescription(
            key=key,
            name=name,
            native_unit_of_measurement="%",
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:percent",
            suggested_display_precision=1,
        )
        for key, name in {
            "percentage_of_max": "Current percentage of highest electricity price",
            "percentage_of_range": "Current percentage in electricity price range",
        }.items()
    ),
    *(
        SensorEntityDescription(
            key=key,
            name=name,
            device_class=SensorDeviceClass.TIMESTAMP,
        )
        for key, name in {
            "highest_price_time_today": "Time of highest price",
            "lowest_price_time_today": "Time of lowest price",
        }.items()
    ),
)


GAS_DESCRIPTIONS = tuple(
    SensorEntityDescription(
        key=key,
        name=name,
        native_unit_of_measurement="EUR/m³",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fire",
        suggested_display_precision=5,
    )
    for key, name in {
        "current_gas_price": "Current gas price",
        "next_gas_price": "Next gas day price",
    }.items()
)


async def async_setup_entry(hass, entry, async_add_entities):
    entities = [
        ZonopnaamPriceSensor(entry.runtime_data.electricity, entry, description)
        for description in DESCRIPTIONS
    ]
    if entry.runtime_data.gas is not None:
        entities.extend(
            ZonopnaamPriceSensor(entry.runtime_data.gas, entry, description)
            for description in GAS_DESCRIPTIONS
        )
    async_add_entities(entities)


class ZonopnaamPriceSensor(CoordinatorEntity, SensorEntity):
    """Calculate values from cached intervals at their actual boundaries."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, description):
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Zonopnaam",
            manufacturer="Zonopnaam",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_utc_time_change(
                self.hass,
                self._time_changed,
                minute=[0, 15, 30, 45],
                second=0,
            )
        )

    @callback
    def _time_changed(self, now):
        self.async_write_ha_state()

    @property
    def native_value(self):
        data = self.coordinator.data
        return (
            data.value(self.entity_description.key, dt_util.utcnow()) if data else None
        )

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
        if not data:
            return None
        if self.entity_description.key in {"avg_price", "current_gas_price"}:
            return data.attributes(dt_util.utcnow())
        return {"price_type": data.price_type, "price_display": data.price_label}
