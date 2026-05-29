"""Fixtures for Nacka Energi tests."""

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from custom_components.nacka_energi.api import (
    ConsumptionEntry,
    MeteringPoint,
    UserEntity,
    UserProperties,
)
from custom_components.nacka_energi.const import (
    CONF_ENTITY_ID,
    CONF_ENTITY_NAME,
    CONF_METERING_POINT,
    CONF_METERING_POINT_NAME,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of the custom_components integration in all tests."""
    yield


@pytest.fixture(autouse=True)
def mock_date():
    """Mock date to ensure deterministic tests."""
    from datetime import date
    from unittest.mock import patch

    with patch(
        "custom_components.nacka_energi.coordinator.date", wraps=date
    ) as mock_date_cls:
        mock_date_cls.today.return_value = date(2026, 2, 15)
        yield mock_date_cls


TEST_USERNAME = "test@example.com"
TEST_PASSWORD = "test_password"
TEST_ENTITY_ID = "eyJpdiI6IkQwTFJtTVpLSXM2b1duaU42ZmZ0L2c9PSIsInZhbHVlIjoiRUhweCtybGViakhzQ1dHdmVZdmxhQT09IiwibWFjIjoiN2ExMjYyMTQxZmM2ZWViN2JkZTdhMGE1NTdiZjI0YTFjMzI2MmEyZDI2YzIzMGMzNzAwNDQ0YzAwYWFiZDk3ZCIsInRhZyI6IiJ9"
TEST_ENTITY_NAME = "Test User"
TEST_METERING_POINT_VALUE = "eyJ2IjoiV0huRkRTRExXNjNxRFQ0am83cnlqZz09In0-"
TEST_METERING_POINT_NAME = "Testvägen 1 - 735999000000000000"

MOCK_USER_ENTITIES = [
    UserEntity(
        id=TEST_ENTITY_ID,
        limetype="portaluser",
        descriptive=TEST_ENTITY_NAME,
        descriptive_id=28109,
        descriptive_limetype="company",
    ),
]

MOCK_METERING_POINTS = [
    MeteringPoint(name=TEST_METERING_POINT_NAME, value=TEST_METERING_POINT_VALUE),
    MeteringPoint(name="Testvägen 2 - 735999106701057187", value="other_value"),
]

MOCK_DAILY_ENTRIES = [
    ConsumptionEntry(
        period_start="2026-02-13T00:00:00",
        period_end="2026-02-14T00:00:00",
        quantity=12.5,
        unit="kWh",
        quality_name="OK",
        created="2026-02-14T07:00:41.2908206",
        is_smear=False,
    ),
]

MOCK_HOURLY_ENTRIES = [
    ConsumptionEntry(
        period_start="2026-02-13T14:00:00",
        period_end="2026-02-13T15:00:00",
        quantity=0.387,
        unit="kWh",
        quality_name="OK",
        created="2026-02-13T15:00:41.1234567",
        is_smear=False,
    ),
]

MOCK_USER_PROPERTIES = UserProperties(
    mobilephone="+46700000000",
    email="test@example.com",
    pua=False,
)


@pytest.fixture
def mock_config_entry_data() -> dict:
    """Return mock config entry data."""
    return {
        CONF_USERNAME: TEST_USERNAME,
        CONF_PASSWORD: TEST_PASSWORD,
        CONF_ENTITY_ID: TEST_ENTITY_ID,
        CONF_ENTITY_NAME: TEST_ENTITY_NAME,
        CONF_METERING_POINT: TEST_METERING_POINT_VALUE,
        CONF_METERING_POINT_NAME: TEST_METERING_POINT_NAME,
    }


@pytest.fixture
def mock_client() -> Generator[AsyncMock]:
    """Return a mocked NackaEnergiClient."""
    with patch(
        "custom_components.nacka_energi.NackaEnergiClient",
        autospec=True,
    ) as mock_cls:
        client = mock_cls.return_value
        client.authenticate = AsyncMock()
        client.get_user_entities = AsyncMock(return_value=MOCK_USER_ENTITIES)
        client.set_user_entity = AsyncMock()
        client.get_metering_points = AsyncMock(return_value=MOCK_METERING_POINTS)
        client.get_consumption = AsyncMock(side_effect=_mock_get_consumption)
        client.get_invoices = AsyncMock(return_value=[])
        client.get_user_properties = AsyncMock(return_value=MOCK_USER_PROPERTIES)
        yield client


def _mock_get_consumption(serviceplace_id, period_type, start, end):
    """Return mock consumption data based on period type."""
    from custom_components.nacka_energi.const import (
        PERIOD_TYPE_DAILY,
        PERIOD_TYPE_HOURLY,
    )

    if period_type == PERIOD_TYPE_DAILY:
        return MOCK_DAILY_ENTRIES
    if period_type == PERIOD_TYPE_HOURLY:
        return MOCK_HOURLY_ENTRIES
    return []


@pytest.fixture
def mock_config_flow_client() -> Generator[AsyncMock]:
    """Return a mocked NackaEnergiClient for config flow."""
    with patch(
        "custom_components.nacka_energi.config_flow.NackaEnergiClient",
        autospec=True,
    ) as mock_cls:
        client = mock_cls.return_value
        client.authenticate = AsyncMock()
        client.get_user_entities = AsyncMock(return_value=MOCK_USER_ENTITIES)
        client.set_user_entity = AsyncMock()
        client.get_metering_points = AsyncMock(return_value=MOCK_METERING_POINTS)
        yield client


@pytest.fixture
def mock_coordinator():
    """Mock NackaEnergiCoordinator."""
    from unittest.mock import MagicMock

    from custom_components.nacka_energi.const import CONF_METERING_POINT_NAME
    from custom_components.nacka_energi.coordinator import NackaEnergiCoordinator

    hass = MagicMock()
    client = MagicMock()
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry"
    config_entry.data = {CONF_METERING_POINT_NAME: "Test Metering Point"}
    config_entry.unique_id = "test_unique_id"

    coordinator = NackaEnergiCoordinator(
        hass=hass,
        client=client,
        serviceplace_id="test_serviceplace",
        config_entry=config_entry,
    )
    return coordinator, config_entry


@pytest.fixture
def mock_data():
    """Mock NackaEnergiData."""
    from custom_components.nacka_energi.api import (
        ConsumptionEntry,
        Invoice,
        UserProperties,
    )
    from custom_components.nacka_energi.coordinator import NackaEnergiData

    return NackaEnergiData(
        hourly_usage=ConsumptionEntry(
            period_start="2026-02-13T14:00:00",
            period_end="2026-02-13T15:00:00",
            quantity=0.387,
            unit="kWh",
            quality_name="OK",
            created="2026-02-13T15:00:41.1234567",
            is_smear=False,
        ),
        daily_usage=ConsumptionEntry(
            period_start="2026-02-13T00:00:00",
            period_end="2026-02-14T00:00:00",
            quantity=12.5,
            unit="kWh",
            quality_name="OK",
            created="2026-02-14T07:00:41.2908206",
            is_smear=False,
        ),
        monthly_usage=ConsumptionEntry(
            period_start="2026-01-01T00:00:00",
            period_end="2026-02-01T00:00:00",
            quantity=100.0,
            unit="kWh",
            quality_name="OK",
            created="2026-02-01T00:00:00",
            is_smear=False,
        ),
        monthly_usage_current=ConsumptionEntry(
            period_start="2026-02-01T00:00:00",
            period_end="2026-03-01T00:00:00",
            quantity=50.0,
            unit="kWh",
            quality_name="OK",
            created="2026-02-15T00:00:00",
            is_smear=False,
        ),
        yearly_usage_kwh=500.0,
        latest_invoice=Invoice(
            invoice_ref="INV-123",
            invoice_amount=123.45,
            paid_amount=0.0,
            balance_amount=123.45,
            invoice_date="2026-02-01",
            due_date="2026-02-15",
            paid_status="unpaid",
            invoicing_delivery="email",
        ),
        user_properties=UserProperties(
            mobilephone="+46700000000",
            email="test@example.com",
            pua=False,
        ),
    )
