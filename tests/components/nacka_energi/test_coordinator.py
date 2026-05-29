import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.nacka_energi.api import (
    NackaEnergiAuthError,
    NackaEnergiConnectionError,
    NackaEnergiRateLimitError,
)
from custom_components.nacka_energi.coordinator import (
    NackaEnergiCoordinator,
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
