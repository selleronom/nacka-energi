"""Sensor platform for Nacka Energi."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import NackaEnergiConfigEntry
from .api import ConsumptionEntry, Invoice, UserProperties
from .const import CONF_METERING_POINT_NAME, DOMAIN
from .coordinator import NackaEnergiCoordinator, NackaEnergiData

PARALLEL_UPDATES = 0  # All sensors share a coordinator; no direct polling.

_CURRENCY_SEK = "SEK"


@dataclass(frozen=True, kw_only=True)
class NackaEnergiEnergySensorDescription(SensorEntityDescription):
    """Describe an energy consumption sensor (period-based)."""

    consumption_fn: Callable[[NackaEnergiData], ConsumptionEntry | None]


@dataclass(frozen=True, kw_only=True)
class NackaEnergiYearlySensorDescription(SensorEntityDescription):
    """Describe the yearly total sensor (plain float)."""

    value_fn: Callable[[NackaEnergiData], float | None]


@dataclass(frozen=True, kw_only=True)
class NackaEnergiInvoiceSensorDescription(SensorEntityDescription):
    """Describe an invoice sensor."""

    value_fn: Callable[[Invoice], Any]
    attr_fn: Callable[[Invoice], dict[str, Any]] | None = None


@dataclass(frozen=True, kw_only=True)
class NackaEnergiUserPropertySensorDescription(SensorEntityDescription):
    """Describe a user property sensor."""

    value_fn: Callable[[UserProperties], str | None]


ENERGY_SENSORS: tuple[NackaEnergiEnergySensorDescription, ...] = (
    NackaEnergiEnergySensorDescription(
        key="hourly_usage",
        name="Hourly energy usage",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=3,
        consumption_fn=lambda data: data.hourly_usage,
    ),
    NackaEnergiEnergySensorDescription(
        key="daily_usage",
        name="Daily energy usage",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        consumption_fn=lambda data: data.daily_usage,
    ),
    NackaEnergiEnergySensorDescription(
        key="monthly_usage",
        name="Monthly energy usage",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        consumption_fn=lambda data: data.monthly_usage,
    ),
    NackaEnergiEnergySensorDescription(
        key="monthly_usage_current",
        name="Current month energy usage",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        consumption_fn=lambda data: data.monthly_usage_current,
    ),
)

YEARLY_SENSORS: tuple[NackaEnergiYearlySensorDescription, ...] = (
    NackaEnergiYearlySensorDescription(
        key="yearly_usage",
        name="Yearly energy usage",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=0,
        value_fn=lambda data: data.yearly_usage_kwh,
    ),
)

INVOICE_SENSORS: tuple[NackaEnergiInvoiceSensorDescription, ...] = (
    NackaEnergiInvoiceSensorDescription(
        key="latest_invoice_amount",
        name="Latest invoice amount",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_CURRENCY_SEK,
        suggested_display_precision=0,
        value_fn=lambda inv: inv.invoice_amount,
        attr_fn=lambda inv: {
            "invoice_ref": inv.invoice_ref,
            "invoice_date": inv.invoice_date,
            "due_date": inv.due_date,
            "paid_status": inv.paid_status,
            "invoicing_delivery": inv.invoicing_delivery,
        },
    ),
    NackaEnergiInvoiceSensorDescription(
        key="latest_invoice_balance",
        name="Latest invoice balance",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_CURRENCY_SEK,
        suggested_display_precision=0,
        value_fn=lambda inv: inv.balance_amount,
    ),
    NackaEnergiInvoiceSensorDescription(
        key="latest_invoice_due_date",
        name="Latest invoice due date",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda inv: (
            date.fromisoformat(inv.due_date[:10]) if inv.due_date else None
        ),
    ),
    NackaEnergiInvoiceSensorDescription(
        key="latest_invoice_status",
        name="Latest invoice status",
        value_fn=lambda inv: inv.paid_status,
        attr_fn=lambda inv: {"invoice_ref": inv.invoice_ref},
    ),
)

USER_PROPERTY_SENSORS: tuple[NackaEnergiUserPropertySensorDescription, ...] = (
    NackaEnergiUserPropertySensorDescription(
        key="user_email",
        name="User email",
        icon="mdi:email",
        value_fn=lambda props: props.email,
    ),
    NackaEnergiUserPropertySensorDescription(
        key="user_phone",
        name="User phone",
        icon="mdi:phone",
        value_fn=lambda props: props.mobilephone,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NackaEnergiConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Nacka Energi sensors from a config entry."""
    coordinator = entry.runtime_data

    entities: list[SensorEntity] = []
    for description in ENERGY_SENSORS:
        entities.append(NackaEnergiEnergySensor(coordinator, description, entry))
    for description in YEARLY_SENSORS:
        entities.append(NackaEnergiYearlySensor(coordinator, description, entry))
    for description in INVOICE_SENSORS:
        entities.append(NackaEnergiInvoiceSensor(coordinator, description, entry))
    for description in USER_PROPERTY_SENSORS:
        entities.append(NackaEnergiUserPropertySensor(coordinator, description, entry))

    async_add_entities(entities)


def _make_device_info(entry: NackaEnergiConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.unique_id)},
        name=entry.data.get(CONF_METERING_POINT_NAME, "Nacka Energi"),
        manufacturer="Nacka Energi",
    )


class NackaEnergiEnergySensor(CoordinatorEntity[NackaEnergiCoordinator], SensorEntity):
    """Energy sensor reporting a single consumption period."""

    _attr_has_entity_name = True
    entity_description: NackaEnergiEnergySensorDescription

    def __init__(
        self,
        coordinator: NackaEnergiCoordinator,
        description: NackaEnergiEnergySensorDescription,
        entry: NackaEnergiConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"
        self._attr_device_info = _make_device_info(entry)

    def _consumption(self) -> ConsumptionEntry | None:
        if self.coordinator.data is None:
            return None
        return self.entity_description.consumption_fn(self.coordinator.data)

    @property
    def native_value(self) -> float | None:
        entry = self._consumption()
        return entry.quantity if entry else None

    @property
    def last_reset(self) -> datetime | None:
        entry = self._consumption()
        return datetime.fromisoformat(entry.period_start) if entry else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        entry = self._consumption()
        if entry is None:
            return None
        return {
            "period_start": entry.period_start,
            "period_end": entry.period_end,
            "quality": entry.quality_name,
            "estimated": entry.is_smear,
            "measurement_created": entry.created,
        }


class NackaEnergiYearlySensor(CoordinatorEntity[NackaEnergiCoordinator], SensorEntity):
    """Yearly energy total sensor (running sum of completed months)."""

    _attr_has_entity_name = True
    entity_description: NackaEnergiYearlySensorDescription

    def __init__(
        self,
        coordinator: NackaEnergiCoordinator,
        description: NackaEnergiYearlySensorDescription,
        entry: NackaEnergiConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"
        self._attr_device_info = _make_device_info(entry)

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)


class NackaEnergiInvoiceSensor(CoordinatorEntity[NackaEnergiCoordinator], SensorEntity):
    """Invoice sensor."""

    _attr_has_entity_name = True
    entity_description: NackaEnergiInvoiceSensorDescription

    def __init__(
        self,
        coordinator: NackaEnergiCoordinator,
        description: NackaEnergiInvoiceSensorDescription,
        entry: NackaEnergiConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"
        self._attr_device_info = _make_device_info(entry)

    def _invoice(self) -> Invoice | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.latest_invoice

    @property
    def native_value(self) -> Any:
        inv = self._invoice()
        return self.entity_description.value_fn(inv) if inv else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        inv = self._invoice()
        if inv is None or self.entity_description.attr_fn is None:
            return None
        return self.entity_description.attr_fn(inv)


class NackaEnergiUserPropertySensor(
    CoordinatorEntity[NackaEnergiCoordinator], SensorEntity
):
    """User property sensor (email, phone)."""

    _attr_has_entity_name = True
    entity_description: NackaEnergiUserPropertySensorDescription

    def __init__(
        self,
        coordinator: NackaEnergiCoordinator,
        description: NackaEnergiUserPropertySensorDescription,
        entry: NackaEnergiConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"
        self._attr_device_info = _make_device_info(entry)

    def _user_properties(self) -> UserProperties | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.user_properties

    @property
    def native_value(self) -> str | None:
        props = self._user_properties()
        return self.entity_description.value_fn(props) if props else None
