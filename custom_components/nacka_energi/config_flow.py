"""Config flow for Nacka Energi integration."""

from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from . import NackaEnergiConfigEntry
from .api import (
    MeteringPoint,
    NackaEnergiAuthError,
    NackaEnergiClient,
    NackaEnergiConnectionError,
    UserEntity,
)
from .const import (
    CONF_ENTITY_ID,
    CONF_ENTITY_NAME,
    CONF_METERING_POINT,
    CONF_METERING_POINT_NAME,
    DOMAIN,
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_REAUTH_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): str,
    }
)


class NackaEnergiConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Nacka Energi."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._username: str = ""
        self._password: str = ""
        self._user_entities: list[UserEntity] = []
        self._metering_points: list[MeteringPoint] = []
        self._selected_entity_id: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step - login credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._username = user_input[CONF_USERNAME]
            self._password = user_input[CONF_PASSWORD]

            session = async_create_clientsession(self.hass)
            client = NackaEnergiClient(self._username, self._password, session)

            try:
                await client.authenticate()
                self._user_entities = await client.get_user_entities()
            except NackaEnergiAuthError:
                errors["base"] = "invalid_auth"
            except NackaEnergiConnectionError, aiohttp.ClientError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"

            if not errors:
                if not self._user_entities:
                    errors["base"] = "cannot_connect"
                elif len(self._user_entities) == 1:
                    # Only one entity — auto-select and proceed.
                    self._selected_entity_id = self._user_entities[0].id
                    return await self.async_step_metering_point()
                else:
                    # Multiple entities — let the user choose.
                    return await self.async_step_entity()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_entity(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle user entity selection step.

        Shown when the authenticated user has more than one portal entity
        (e.g. multiple companies/accounts).  Most users will only have one
        and this step is skipped automatically.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            self._selected_entity_id = user_input[CONF_ENTITY_ID]
            return await self.async_step_metering_point()

        entity_options = {
            ent.id: f"{ent.descriptive} ({ent.limetype})" for ent in self._user_entities
        }

        return self.async_show_form(
            step_id="entity",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ENTITY_ID): vol.In(entity_options),
                }
            ),
            errors=errors,
        )

    async def async_step_metering_point(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle metering point selection step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected_value = user_input[CONF_METERING_POINT]

            # Find the selected metering point name
            selected_name = ""
            for mp in self._metering_points:
                if mp.value == selected_value:
                    selected_name = mp.name
                    break

            # Find the entity descriptive name for storage
            entity_name = ""
            for ent in self._user_entities:
                if ent.id == self._selected_entity_id:
                    entity_name = ent.descriptive
                    break

            await self.async_set_unique_id(selected_value)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=selected_name,
                data={
                    CONF_USERNAME: self._username,
                    CONF_PASSWORD: self._password,
                    CONF_ENTITY_ID: self._selected_entity_id,
                    CONF_ENTITY_NAME: entity_name,
                    CONF_METERING_POINT: selected_value,
                    CONF_METERING_POINT_NAME: selected_name,
                },
            )

        # We need to select the entity first, then fetch metering points.
        session = async_create_clientsession(self.hass)
        client = NackaEnergiClient(self._username, self._password, session)

        try:
            await client.authenticate()
            await client.set_user_entity(self._selected_entity_id)
            self._metering_points = await client.get_metering_points()
        except NackaEnergiConnectionError, aiohttp.ClientError:
            errors["base"] = "cannot_connect"
        except Exception:  # noqa: BLE001
            errors["base"] = "unknown"

        if errors:
            return self.async_show_form(
                step_id="metering_point",
                data_schema=vol.Schema({}),
                errors=errors,
            )

        if not self._metering_points:
            errors["base"] = "cannot_connect"
            return self.async_show_form(
                step_id="metering_point",
                data_schema=vol.Schema({}),
                errors=errors,
            )

        metering_point_options = {mp.value: mp.name for mp in self._metering_points}

        return self.async_show_form(
            step_id="metering_point",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_METERING_POINT): vol.In(metering_point_options),
                }
            ),
        )

    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reauthentication when credentials become invalid."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reauthentication confirmation step."""
        errors: dict[str, str] = {}
        reauth_entry: NackaEnergiConfigEntry = self._get_reauth_entry()

        if user_input is not None:
            username = reauth_entry.data[CONF_USERNAME]
            new_password = user_input[CONF_PASSWORD]

            session = async_create_clientsession(self.hass)
            client = NackaEnergiClient(username, new_password, session)

            try:
                await client.authenticate()
            except NackaEnergiAuthError:
                errors["base"] = "invalid_auth"
            except NackaEnergiConnectionError, aiohttp.ClientError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={CONF_PASSWORD: new_password},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            description_placeholders={
                CONF_USERNAME: reauth_entry.data[CONF_USERNAME],
            },
            errors=errors,
        )
