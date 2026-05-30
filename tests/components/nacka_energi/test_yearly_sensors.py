import pytest

from custom_components.nacka_energi.sensor import (
    NackaEnergiYearlySensor,
)


@pytest.mark.asyncio
async def test_yearly_sensor(mock_coordinator, mock_data):
    coordinator, entry = mock_coordinator
    coordinator.data = mock_data

    from custom_components.nacka_energi.sensor import YEARLY_SENSORS

    yearly_sensor_desc = next(d for d in YEARLY_SENSORS if d.key == "yearly_usage")
    sensor = NackaEnergiYearlySensor(coordinator, yearly_sensor_desc, entry)
    assert sensor.native_value == 150.0
