"""The Nacka Energi integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import (
    NackaEnergiClient,
    NackaEnergiConnectionError,
    NackaEnergiRateLimitError,
)
from .const import (
    CONF_ENTITY_ID,
    CONF_ENTITY_NAME,
    CONF_METERING_POINT,
    CONF_METERING_POINT_NAME,
    LOGGER,
)
from .coordinator import NackaEnergiCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type NackaEnergiConfigEntry = ConfigEntry[NackaEnergiCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: NackaEnergiConfigEntry) -> bool:
    """Set up Nacka Energi from a config entry."""
    session = async_create_clientsession(hass)
    stored_entity_id = entry.data.get(CONF_ENTITY_ID, "")
    stored_entity_name = entry.data.get(CONF_ENTITY_NAME, "")
    client = NackaEnergiClient(
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        session,
        entity_name=stored_entity_name or None,
        entity_id=stored_entity_id or None,
    )

    # authenticate() also performs entity selection (steps 3–4 of the auth
    # flow) so subsequent re-auths after session expiry don't strand us
    # without an active entity, which would cause data endpoints to 500.
    try:
        await client.authenticate()
    except NackaEnergiRateLimitError as err:
        raise ConfigEntryNotReady(
            "Rate limited by Nacka Energi portal, will retry later"
        ) from err
    except NackaEnergiConnectionError as err:
        raise ConfigEntryNotReady(
            f"Cannot connect to Nacka Energi portal: {err}"
        ) from err

    # Persist the resolved entity ID if it changed.
    resolved_entity_id = client.entity_id or ""
    if resolved_entity_id and resolved_entity_id != stored_entity_id:
        LOGGER.info(
            "Entity ID changed for %s: %s -> %s",
            stored_entity_name or "(unknown)",
            stored_entity_id,
            resolved_entity_id,
        )
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_ENTITY_ID: resolved_entity_id},
        )

    # ── Resolve the serviceplace (metering point) ───────────────────────
    # The portal's opaque serviceplace IDs can also rotate between sessions.
    stored_id = entry.data[CONF_METERING_POINT]
    stored_name = entry.data.get(CONF_METERING_POINT_NAME, "")
    serviceplace_id = stored_id

    try:
        metering_points = await client.get_metering_points()
    except NackaEnergiConnectionError as err:
        raise ConfigEntryNotReady(f"Cannot fetch metering points: {err}") from err

    for mp in metering_points:
        if mp.name == stored_name:
            serviceplace_id = mp.value
            break

    if serviceplace_id != stored_id:
        LOGGER.info(
            "Serviceplace ID changed for %s: %s -> %s",
            stored_name,
            stored_id,
            serviceplace_id,
        )
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_METERING_POINT: serviceplace_id},
        )

    # ── Set up the coordinator ──────────────────────────────────────────
    coordinator = NackaEnergiCoordinator(
        hass,
        client,
        serviceplace_id,
        config_entry=entry,
    )

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: NackaEnergiConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
