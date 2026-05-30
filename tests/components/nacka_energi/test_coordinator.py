from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.nacka_energi.api import (
    ConsumptionEntry,
    NackaEnergiAuthError,
    NackaEnergiConnectionError,
    NackaEnergiRateLimitError,
)
from custom_components.nacka_energi.coordinator import (
    NackaEnergiCoordinator,
)


@pytest.fixture(autouse=True)
def mock_recorder():
    """Stub the recorder so external-statistics injection is a no-op by default.

    The real injection talks to HA's recorder; here we patch it out so the
    coordinator tests stay pure. Tests that exercise the injection itself
    request this fixture to inspect/override the stubbed calls.
    """
    with (
        patch(
            "custom_components.nacka_energi.coordinator.get_instance"
        ) as get_instance,
        patch(
            "custom_components.nacka_energi.coordinator.async_add_external_statistics"
        ) as add_stats,
    ):
        # async_add_executor_job(get_last_statistics, ...) -> no prior stats
        executor = AsyncMock(return_value={})
        get_instance.return_value.async_add_executor_job = executor
        yield SimpleNamespace(add_stats=add_stats, executor=executor)


def _hourly(period_start: str, quantity: float) -> ConsumptionEntry:
    """Build an OK hourly consumption entry for tests."""
    return ConsumptionEntry(
        period_start=period_start,
        period_end=period_start,
        quantity=quantity,
        unit="kWh",
        quality_name="OK",
        created=period_start,
        is_smear=False,
    )


@pytest.fixture
def mock_coordinator_real(mock_client, mock_config_entry_data):
    """Fixture to provide a real coordinator with a mocked client."""
    from unittest.mock import MagicMock

    from homeassistant.core import HomeAssistant

    hass = MagicMock(spec=HomeAssistant)
    # We need a real ConfigEntry for the coordinator
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry_id"
    config_entry.data = mock_config_entry_data

    coordinator = NackaEnergiCoordinator(
        hass=hass,
        client=mock_client,
        serviceplace_id="test_serviceplace",
        config_entry=config_entry,
    )
    return coordinator, mock_client, config_entry


@pytest.mark.asyncio
async def test_async_update_data_success(mock_coordinator_real, mock_data):
    """Test successful data update."""
    coordinator, client, _ = mock_coordinator_real

    # Setup client to return mock_data components
    # We need to mock the individual fetch methods via the client
    client.get_consumption.side_effect = [
        [mock_data.hourly_usage],  # hourly
        [mock_data.daily_usage],  # daily
        [mock_data.monthly_usage, mock_data.monthly_usage_current],  # monthly
    ]
    client.get_invoices.return_value = [mock_data.latest_invoice]
    client.get_user_properties.return_value = mock_data.user_properties

    data = await coordinator._async_update_data()

    assert data.hourly_usage == mock_data.hourly_usage
    assert data.daily_usage == mock_data.daily_usage
    assert data.monthly_usage == mock_data.monthly_usage
    assert data.monthly_usage_current == mock_data.monthly_usage_current
    assert data.yearly_usage_kwh == mock_data.yearly_usage_kwh
    assert data.latest_invoice == mock_data.latest_invoice
    assert data.user_properties == mock_data.user_properties


@pytest.mark.asyncio
async def test_async_update_data_partial_failure(mock_coordinator_real, mock_data):
    """Test partial failure where some endpoints fail with connection errors."""
    coordinator, client, _ = mock_coordinator_real

    # Set previous data so it's not the first fetch
    coordinator.data = mock_data

    # Mock successful responses for some, and connection errors for others
    # hourly: success
    # daily: connection error
    # monthly: success
    # invoice: connection error
    # user_properties: success
    client.get_consumption.side_effect = [
        [mock_data.hourly_usage],  # hourly
        NackaEnergiConnectionError("Daily failed"),  # daily
        [mock_data.monthly_usage, mock_data.monthly_usage_current],  # monthly
    ]
    client.get_invoices.side_effect = NackaEnergiConnectionError("Invoice failed")
    client.get_user_properties.return_value = mock_data.user_properties

    data = await coordinator._async_update_data()

    # Verify that successful data is preserved and failed data remains from previous
    assert data.hourly_usage == mock_data.hourly_usage
    assert data.daily_usage == mock_data.daily_usage  # preserved from previous
    assert data.monthly_usage == mock_data.monthly_usage
    assert data.latest_invoice == mock_data.latest_invoice  # preserved from previous
    assert data.user_properties == mock_data.user_properties


@pytest.mark.asyncio
async def test_async_update_data_auth_failure(mock_coordinator_real):
    """Test authentication failure raises ConfigEntryAuthFailed."""
    coordinator, client, _ = mock_coordinator_real

    client.get_consumption.side_effect = NackaEnergiAuthError("Auth failed")

    with pytest.raises(ConfigEntryAuthFailed) as excinfo:
        await coordinator._async_update_data()
    assert "Authentication failed" in str(excinfo.value)


@pytest.mark.asyncio
async def test_async_update_data_rate_limit(mock_coordinator_real):
    """Test rate limiting raises UpdateFailed."""
    coordinator, client, _ = mock_coordinator_real

    client.get_consumption.side_effect = NackaEnergiRateLimitError("Too many requests")

    with pytest.raises(UpdateFailed) as excinfo:
        await coordinator._async_update_data()
    assert "Rate limited" in str(excinfo.value)


@pytest.mark.asyncio
async def test_async_update_data_all_fail_no_previous(mock_coordinator_real):
    """Test that if all endpoints fail on first run, UpdateFailed is raised."""
    coordinator, client, _ = mock_coordinator_real

    # Ensure no previous data
    coordinator.data = None

    # Make all calls fail with connection errors
    client.get_consumption.side_effect = NackaEnergiConnectionError("Connection failed")
    client.get_invoices.side_effect = NackaEnergiConnectionError("Connection failed")
    client.get_user_properties.side_effect = NackaEnergiConnectionError(
        "Connection failed"
    )

    with pytest.raises(UpdateFailed) as excinfo:
        await coordinator._async_update_data()
    assert "All API endpoints failed" in str(excinfo.value)


def test_period_start_to_utc_summer():
    """A naive Stockholm summer time converts to UTC (CEST = UTC+2)."""
    utc = NackaEnergiCoordinator._period_start_to_utc("2026-05-30T00:00:00", None)
    assert utc.isoformat() == "2026-05-29T22:00:00+00:00"


def test_period_start_to_utc_dst_fallback():
    """The repeated 02:00 hour on the autumn fall-back maps to two UTC hours.

    Both occurrences share the same period_start string; passing the previous
    UTC value disambiguates the second (fold=1) occurrence.
    """
    first = NackaEnergiCoordinator._period_start_to_utc("2026-10-25T02:00:00", None)
    second = NackaEnergiCoordinator._period_start_to_utc("2026-10-25T02:00:00", first)
    assert first.isoformat() == "2026-10-25T00:00:00+00:00"
    assert second.isoformat() == "2026-10-25T01:00:00+00:00"


@pytest.mark.asyncio
async def test_inject_hourly_statistics(mock_coordinator_real, mock_recorder):
    """Each OK hour is injected at its UTC timestamp with a continued sum."""
    coordinator, _, config_entry = mock_coordinator_real
    config_entry.unique_id = "uid123"
    config_entry.title = "Test Place"

    entries = [
        _hourly("2026-05-30T00:00:00", 0.168),
        _hourly("2026-05-30T01:00:00", 0.182),
        _hourly("2026-05-30T02:00:00", 0.241),
    ]
    await coordinator._inject_hourly_statistics(entries)

    mock_recorder.add_stats.assert_called_once()
    _, metadata, stats = mock_recorder.add_stats.call_args[0]
    assert metadata["statistic_id"] == "nacka_energi:uid123_hourly_energy"
    assert metadata["source"] == "nacka_energi"
    assert metadata["has_sum"] is True
    assert [s["start"].isoformat() for s in stats] == [
        "2026-05-29T22:00:00+00:00",
        "2026-05-29T23:00:00+00:00",
        "2026-05-30T00:00:00+00:00",
    ]
    assert [s["state"] for s in stats] == [0.168, 0.182, 0.241]
    assert [round(s["sum"], 3) for s in stats] == [0.168, 0.35, 0.591]


@pytest.mark.asyncio
async def test_inject_hourly_statistics_skips_already_recorded(
    mock_coordinator_real, mock_recorder
):
    """Hours already in the recorder are skipped and the sum continues."""
    coordinator, _, config_entry = mock_coordinator_real
    config_entry.unique_id = "uid"
    config_entry.title = "T"
    statistic_id = "nacka_energi:uid_hourly_energy"

    # Pretend the first hour (22:00Z, sum 0.168) is already recorded.
    first_utc = NackaEnergiCoordinator._period_start_to_utc("2026-05-30T00:00:00", None)
    mock_recorder.executor.return_value = {
        statistic_id: [{"sum": 0.168, "start": first_utc.timestamp()}]
    }

    entries = [
        _hourly("2026-05-30T00:00:00", 0.168),  # already recorded -> skipped
        _hourly("2026-05-30T01:00:00", 0.182),  # new
    ]
    await coordinator._inject_hourly_statistics(entries)

    _, _, stats = mock_recorder.add_stats.call_args[0]
    assert len(stats) == 1
    assert stats[0]["start"].isoformat() == "2026-05-29T23:00:00+00:00"
    assert round(stats[0]["sum"], 3) == 0.35


@pytest.mark.asyncio
async def test_inject_hourly_statistics_noop_when_nothing_new(
    mock_coordinator_real, mock_recorder
):
    """Nothing is written when all available hours are already recorded."""
    coordinator, _, config_entry = mock_coordinator_real
    config_entry.unique_id = "uid"
    config_entry.title = "T"
    statistic_id = "nacka_energi:uid_hourly_energy"

    only_utc = NackaEnergiCoordinator._period_start_to_utc("2026-05-30T00:00:00", None)
    mock_recorder.executor.return_value = {
        statistic_id: [{"sum": 0.168, "start": only_utc.timestamp()}]
    }

    await coordinator._inject_hourly_statistics([_hourly("2026-05-30T00:00:00", 0.168)])

    mock_recorder.add_stats.assert_not_called()


@pytest.mark.asyncio
async def test_update_survives_statistics_injection_failure(
    mock_coordinator_real, mock_data
):
    """A failure injecting statistics must not break the data update."""
    coordinator, client, _ = mock_coordinator_real
    client.get_consumption.side_effect = [
        [mock_data.hourly_usage],
        [mock_data.daily_usage],
        [mock_data.monthly_usage, mock_data.monthly_usage_current],
    ]
    client.get_invoices.return_value = [mock_data.latest_invoice]
    client.get_user_properties.return_value = mock_data.user_properties

    with patch.object(
        coordinator, "_inject_hourly_statistics", side_effect=RuntimeError("boom")
    ):
        data = await coordinator._async_update_data()

    # The update still returns the fetched data despite the injection failure.
    assert data.hourly_usage == mock_data.hourly_usage
    assert data.daily_usage == mock_data.daily_usage
