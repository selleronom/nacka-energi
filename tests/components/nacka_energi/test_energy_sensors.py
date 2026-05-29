from datetime import datetime

import pytest

from custom_components.nacka_energi.sensor import (
    NackaEnergiEnergySensor,
)


@pytest.mark.asyncio
async def test_energy_sensors(mock_coordinator, mock_data):
    coordinator, entry = mock_coordinator
    coordinator.data = mock_data

    from custom_components.nacka_energi.sensor import ENERGY_SENSORS

    # Hourly
    hourly_sensor_desc = next(d for d in ENERGY_SENSORS if d.key == "hourly_usage")
    sensor = NackaEnergiEnergySensor(coordinator, hourly_sensor_desc, entry)
    assert sensor.native_value == 0.387
    assert sensor.last_reset == datetime.fromisoformat("2026-02-13T14:00:00")
    assert sensor.extra_state_attributes["period_start"] == "2026-02-13T14:00:00"
    assert sensor.extra_state_attributes["period_end"] == "2026-02-13T15:00:00"
    assert sensor.extra_state_attributes["quality"] == "OK"
    assert sensor.extra_state_attributes["estimated"] is False
    assert (
        sensor.extra_state_attributes["measurement_created"]
        == "2026-02-13T15:00:41.1234567"
    )

    # Daily
    daily_sensor_desc = next(d for d in ENERGY_SENSORS if d.key == "daily_usage")
    sensor = NackaEnergiEnergySensor(coordinator, daily_sensor_desc, entry)
    assert sensor.native_value == 12.5

    # Monthly
    monthly_sensor_desc = next(d for d in ENERGY_SENSORS if d.key == "monthly_usage")
    sensor = NackaEnergiEnergySensor(coordinator, monthly_sensor_desc, entry)
    assert sensor.native_value == 100.0

    # Monthly Current
    monthly_current_sensor_desc = next(
        d for d in ENERGY_SENSORS if d.key == "monthly_usage_current"
    )
    sensor = NackaEnergiEnergySensor(coordinator, monthly_current_sensor_desc, entry)
    assert sensor.native_value == 50.0
