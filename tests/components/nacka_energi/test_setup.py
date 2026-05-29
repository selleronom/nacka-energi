from unittest.mock import MagicMock

import pytest

from custom_components.nacka_energi.const import DOMAIN
from custom_components.nacka_energi.sensor import (
    ENERGY_SENSORS,
    INVOICE_SENSORS,
    USER_PROPERTY_SENSORS,
    NackaEnergiEnergySensor,
    NackaEnergiInvoiceSensor,
    NackaEnergiUserPropertySensor,
    async_setup_entry,
)


@pytest.mark.asyncio
async def test_sensors_no_data(mock_coordinator):
    """Test sensors when coordinator has no data."""
    coordinator, entry = mock_coordinator
    coordinator.data = None

    hourly_sensor_desc = next(d for d in ENERGY_SENSORS if d.key == "hourly_usage")
    sensor = NackaEnergiEnergySensor(coordinator, hourly_sensor_desc, entry)
    assert sensor.native_value is None
    assert sensor.last_reset is None
    assert sensor.extra_state_attributes is None

    amount_desc = next(d for d in INVOICE_SENSORS if d.key == "latest_invoice_amount")
    sensor = NackaEnergiInvoiceSensor(coordinator, amount_desc, entry)
    assert sensor.native_value is None
    assert sensor.extra_state_attributes is None

    email_desc = next(d for d in USER_PROPERTY_SENSORS if d.key == "user_email")
    sensor = NackaEnergiUserPropertySensor(coordinator, email_desc, entry)
    assert sensor.native_value is None


@pytest.mark.asyncio
async def test_sensor_device_info(mock_coordinator, mock_data):
    """Test that sensors have correct device info."""
    coordinator, entry = mock_coordinator
    coordinator.data = mock_data

    hourly_sensor_desc = next(d for d in ENERGY_SENSORS if d.key == "hourly_usage")
    from custom_components.nacka_energi.sensor import NackaEnergiEnergySensor

    sensor = NackaEnergiEnergySensor(coordinator, hourly_sensor_desc, entry)

    assert sensor._attr_device_info["name"] == "Test Metering Point"
    assert sensor._attr_device_info["manufacturer"] == "Nacka Energi"
    assert sensor._attr_device_info["identifiers"] == {(DOMAIN, "test_unique_id")}


@pytest.mark.asyncio
async def test_async_setup_entry(hass, mock_coordinator):
    """Test async_setup_entry."""
    coordinator, entry = mock_coordinator
    entry.runtime_data = coordinator

    mock_add_entities = MagicMock()
    await async_setup_entry(hass, entry, mock_add_entities)

    # Verify that entities were added
    mock_add_entities.assert_called_once()
    added_entities = mock_add_entities.call_args[0][0]
    assert len(added_entities) > 0
