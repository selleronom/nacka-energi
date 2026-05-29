"""Tests for the Nacka Energi config flow."""

from unittest.mock import AsyncMock

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.nacka_energi.api import (
    NackaEnergiAuthError,
    NackaEnergiConnectionError,
    NackaEnergiRateLimitError,
    UserEntity,
)
from custom_components.nacka_energi.const import (
    CONF_ENTITY_ID,
    CONF_ENTITY_NAME,
    CONF_METERING_POINT,
    CONF_METERING_POINT_NAME,
    DOMAIN,
)

from .conftest import (
    TEST_ENTITY_ID,
    TEST_ENTITY_NAME,
    TEST_METERING_POINT_NAME,
    TEST_METERING_POINT_VALUE,
    TEST_PASSWORD,
    TEST_USERNAME,
)


@pytest.mark.usefixtures("mock_config_flow_client")
async def test_user_flow_single_entity(hass: HomeAssistant) -> None:
    """Test successful user config flow with a single entity (auto-selected)."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_USERNAME: TEST_USERNAME,
            CONF_PASSWORD: TEST_PASSWORD,
        },
    )
    # With a single entity, the flow should skip the entity step
    # and go directly to metering_point
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "metering_point"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_METERING_POINT: TEST_METERING_POINT_VALUE},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == TEST_METERING_POINT_NAME
    assert result["data"][CONF_USERNAME] == TEST_USERNAME
    assert result["data"][CONF_PASSWORD] == TEST_PASSWORD
    assert result["data"][CONF_ENTITY_ID] == TEST_ENTITY_ID
    assert result["data"][CONF_ENTITY_NAME] == TEST_ENTITY_NAME
    assert result["data"][CONF_METERING_POINT] == TEST_METERING_POINT_VALUE
    assert result["data"][CONF_METERING_POINT_NAME] == TEST_METERING_POINT_NAME


async def test_user_flow_multiple_entities(
    hass: HomeAssistant, mock_config_flow_client: AsyncMock
) -> None:
    """Test config flow with multiple entities (shows entity selection step)."""
    # Override with two entities
    mock_config_flow_client.get_user_entities.return_value = [
        UserEntity(
            id="entity_id_1",
            limetype="portaluser",
            descriptive="User One",
            descriptive_id=1,
            descriptive_limetype="company",
        ),
        UserEntity(
            id="entity_id_2",
            limetype="portaluser",
            descriptive="User Two",
            descriptive_id=2,
            descriptive_limetype="company",
        ),
    ]

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_USERNAME: TEST_USERNAME,
            CONF_PASSWORD: TEST_PASSWORD,
        },
    )
    # With multiple entities, the flow should show the entity step
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "entity"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_ENTITY_ID: "entity_id_1"},
    )
    # After entity selection, go to metering_point
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "metering_point"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_METERING_POINT: TEST_METERING_POINT_VALUE},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ENTITY_ID] == "entity_id_1"
    assert result["data"][CONF_ENTITY_NAME] == "User One"


async def test_user_flow_invalid_auth(
    hass: HomeAssistant, mock_config_flow_client: AsyncMock
) -> None:
    """Test config flow with invalid credentials."""
    mock_config_flow_client.authenticate.side_effect = NackaEnergiAuthError("Invalid")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_USERNAME: TEST_USERNAME,
            CONF_PASSWORD: "wrong_password",
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_cannot_connect(
    hass: HomeAssistant, mock_config_flow_client: AsyncMock
) -> None:
    """Test config flow when connection fails."""
    mock_config_flow_client.authenticate.side_effect = NackaEnergiConnectionError(
        "Connection failed"
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_USERNAME: TEST_USERNAME,
            CONF_PASSWORD: TEST_PASSWORD,
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_rate_limited(
    hass: HomeAssistant, mock_config_flow_client: AsyncMock
) -> None:
    """Test config flow when rate limited."""
    mock_config_flow_client.authenticate.side_effect = NackaEnergiRateLimitError(
        "Rate limited"
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_USERNAME: TEST_USERNAME,
            CONF_PASSWORD: TEST_PASSWORD,
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_no_entities(
    hass: HomeAssistant, mock_config_flow_client: AsyncMock
) -> None:
    """Test config flow when no user entities are found."""
    mock_config_flow_client.get_user_entities.return_value = []

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_USERNAME: TEST_USERNAME,
            CONF_PASSWORD: TEST_PASSWORD,
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_get_entities_fails(
    hass: HomeAssistant, mock_config_flow_client: AsyncMock
) -> None:
    """Test config flow when get_user_entities raises a connection error."""
    mock_config_flow_client.get_user_entities.side_effect = NackaEnergiConnectionError(
        "Failed"
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_USERNAME: TEST_USERNAME,
            CONF_PASSWORD: TEST_PASSWORD,
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_metering_point_step_connection_error(
    hass: HomeAssistant, mock_config_flow_client: AsyncMock
) -> None:
    """Test metering_point step when set_user_entity fails."""
    # Make the client fail when set_user_entity is called during the auto-selection transition
    mock_config_flow_client.set_user_entity.side_effect = NackaEnergiConnectionError(
        "Failed to set entity"
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_USERNAME: TEST_USERNAME,
            CONF_PASSWORD: TEST_PASSWORD,
        },
    )

    # Since set_user_entity failed, it should return the metering_point form with errors
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "metering_point"
    assert result["errors"] == {"base": "cannot_connect"}
