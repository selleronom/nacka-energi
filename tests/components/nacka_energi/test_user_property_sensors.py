import pytest

from custom_components.nacka_energi.sensor import (
    NackaEnergiUserPropertySensor,
)


@pytest.mark.asyncio
async def test_user_property_sensors(mock_coordinator, mock_data):
    coordinator, entry = mock_coordinator
    coordinator.data = mock_data

    from custom_components.nacka_energi.sensor import USER_PROPERTY_SENSORS

    email_desc = next(d for d in USER_PROPERTY_SENSORS if d.key == "user_email")
    sensor = NackaEnergiUserPropertySensor(coordinator, email_desc, entry)
    assert sensor.native_value == "test@example.com"

    phone_desc = next(d for d in USER_PROPERTY_SENSORS if d.key == "user_phone")
    sensor = NackaEnergiUserPropertySensor(coordinator, phone_desc, entry)
    assert sensor.native_value == "+46700000000"
