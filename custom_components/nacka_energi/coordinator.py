"""Data update coordinator for Nacka Energi."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    ConsumptionEntry,
    Invoice,
    NackaEnergiAuthError,
    NackaEnergiClient,
    NackaEnergiConnectionError,
    NackaEnergiRateLimitError,
    UserProperties,
)
from .const import LOGGER, PERIOD_TYPE_DAILY, PERIOD_TYPE_HOURLY, PERIOD_TYPE_MONTHLY


@dataclass
class NackaEnergiData:
    """Data returned by the coordinator."""

    hourly_usage: ConsumptionEntry | None
    daily_usage: ConsumptionEntry | None
    monthly_usage: ConsumptionEntry | None
    monthly_usage_current: ConsumptionEntry | None
    yearly_usage_kwh: float | None
    latest_invoice: Invoice | None
    user_properties: UserProperties | None


class NackaEnergiCoordinator(DataUpdateCoordinator[NackaEnergiData]):
    """Coordinator to fetch Nacka Energi consumption data."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        client: NackaEnergiClient,
        serviceplace_id: str,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            logger=LOGGER,
            name="Nacka Energi",
            update_interval=timedelta(hours=1),
            config_entry=config_entry,
        )
        self.client = client
        self.serviceplace_id = serviceplace_id

    async def _async_update_data(self) -> NackaEnergiData:
        """Fetch consumption data from the API.

        Each endpoint is fetched independently so a transient failure on one
        (e.g. a 500 from the consumption endpoint) does not block the others.
        On partial failure the previous successful value is preserved; if we
        have never fetched successfully the field stays None.
        """
        previous = self.data
        hourly: ConsumptionEntry | None = previous.hourly_usage if previous else None
        daily: ConsumptionEntry | None = previous.daily_usage if previous else None
        monthly: ConsumptionEntry | None = previous.monthly_usage if previous else None
        monthly_current: ConsumptionEntry | None = (
            previous.monthly_usage_current if previous else None
        )
        yearly: float | None = previous.yearly_usage_kwh if previous else None
        latest_invoice: Invoice | None = previous.latest_invoice if previous else None
        user_properties: UserProperties | None = (
            previous.user_properties if previous else None
        )
        errors: list[str] = []

        try:
            hourly = await self._fetch_hourly_usage()
        except NackaEnergiAuthError as err:
            raise ConfigEntryAuthFailed(
                "Authentication failed, please reconfigure"
            ) from err
        except NackaEnergiRateLimitError as err:
            raise UpdateFailed(
                "Rate limited by Nacka Energi portal, will retry next cycle"
            ) from err
        except NackaEnergiConnectionError as err:
            LOGGER.debug("Failed to fetch hourly usage: %s", err)
            errors.append(f"hourly: {err}")

        try:
            daily = await self._fetch_daily_usage()
        except NackaEnergiAuthError as err:
            raise ConfigEntryAuthFailed(
                "Authentication failed, please reconfigure"
            ) from err
        except NackaEnergiRateLimitError as err:
            raise UpdateFailed(
                "Rate limited by Nacka Energi portal, will retry next cycle"
            ) from err
        except NackaEnergiConnectionError as err:
            LOGGER.debug("Failed to fetch daily usage: %s", err)
            errors.append(f"daily: {err}")

        try:
            monthly, monthly_current, yearly = await self._fetch_monthly_usage()
        except NackaEnergiAuthError as err:
            raise ConfigEntryAuthFailed(
                "Authentication failed, please reconfigure"
            ) from err
        except NackaEnergiRateLimitError as err:
            raise UpdateFailed(
                "Rate limited by Nacka Energi portal, will retry next cycle"
            ) from err
        except NackaEnergiConnectionError as err:
            LOGGER.debug("Failed to fetch monthly usage: %s", err)
            errors.append(f"monthly: {err}")

        try:
            latest_invoice = await self._fetch_latest_invoice()
        except NackaEnergiAuthError as err:
            raise ConfigEntryAuthFailed(
                "Authentication failed, please reconfigure"
            ) from err
        except NackaEnergiRateLimitError as err:
            raise UpdateFailed(
                "Rate limited by Nacka Energi portal, will retry next cycle"
            ) from err
        except NackaEnergiConnectionError as err:
            LOGGER.debug("Failed to fetch invoices: %s", err)
            errors.append(f"invoices: {err}")

        try:
            user_properties = await self._fetch_user_properties()
        except NackaEnergiAuthError as err:
            raise ConfigEntryAuthFailed(
                "Authentication failed, please reconfigure"
            ) from err
        except NackaEnergiRateLimitError as err:
            raise UpdateFailed(
                "Rate limited by Nacka Energi portal, will retry next cycle"
            ) from err
        except NackaEnergiConnectionError as err:
            LOGGER.debug("Failed to fetch user properties: %s", err)
            errors.append(f"user_properties: {err}")

        # If ALL endpoints failed and we have no previous data, raise so
        # the coordinator signals a problem instead of returning empty data.
        total_endpoints = 5
        if len(errors) == total_endpoints and previous is None:
            raise UpdateFailed(f"All API endpoints failed: {'; '.join(errors)}")

        if errors:
            LOGGER.warning(
                "Partial update — %d/%d endpoints failed: %s",
                len(errors),
                total_endpoints,
                "; ".join(errors),
            )

        return NackaEnergiData(
            hourly_usage=hourly,
            daily_usage=daily,
            monthly_usage=monthly,
            monthly_usage_current=monthly_current,
            yearly_usage_kwh=yearly,
            latest_invoice=latest_invoice,
            user_properties=user_properties,
        )

    async def _fetch_daily_usage(self) -> ConsumptionEntry | None:
        """Fetch the previous day's total usage."""
        today = date.today()
        start = today.replace(day=1)
        end = (start + timedelta(days=32)).replace(day=1)

        entries = await self.client.get_consumption(
            self.serviceplace_id, PERIOD_TYPE_DAILY, start, end
        )

        # Find yesterday's entry first
        yesterday = (today - timedelta(days=1)).isoformat()
        for entry in reversed(entries):
            if (
                entry.period_start.startswith(yesterday)
                and entry.quality_name.upper() == "OK"
            ):
                return entry

        # Fall back to the most recent valid entry
        for entry in reversed(entries):
            if entry.quality_name.upper() == "OK":
                return entry

        return None

    async def _fetch_hourly_usage(self) -> ConsumptionEntry | None:
        """Fetch the latest available hourly usage.

        Fetches from yesterday to cover the midnight boundary — the last
        completed hour (23:00-00:00) starts on the previous day, so data
        won't appear in a today-only query until hour 00-01 completes.
        """
        today = date.today()
        yesterday = today - timedelta(days=1)
        tomorrow = today + timedelta(days=1)

        entries = await self.client.get_consumption(
            self.serviceplace_id, PERIOD_TYPE_HOURLY, yesterday, tomorrow
        )

        for entry in reversed(entries):
            if entry.quality_name.upper() == "OK":
                return entry

        return None

    async def _fetch_monthly_usage(
        self,
    ) -> tuple[ConsumptionEntry | None, ConsumptionEntry | None, float | None]:
        """Fetch monthly data and derive last month, current month, and yearly total.

        Returns:
            (last_complete_month, current_month_to_date, yearly_kwh_sum)
        """
        today = date.today()
        year_start = date(today.year, 1, 1)
        year_end = date(today.year + 1, 1, 1)

        entries = await self.client.get_consumption(
            self.serviceplace_id, PERIOD_TYPE_MONTHLY, year_start, year_end
        )

        last_complete: ConsumptionEntry | None = None
        current_partial: ConsumptionEntry | None = None
        yearly_sum = 0.0
        has_any_yearly = False

        current_month_start = today.replace(day=1).isoformat()

        for entry in entries:
            if entry.period_start.startswith(current_month_start):
                # Current (partial) month — include regardless of quality
                current_partial = entry
                if entry.quantity > 0:
                    yearly_sum += entry.quantity
                    has_any_yearly = True
            elif entry.quality_name.upper() == "OK" and entry.quantity > 0:
                last_complete = entry
                yearly_sum += entry.quantity
                has_any_yearly = True

        return last_complete, current_partial, yearly_sum if has_any_yearly else None

    async def _fetch_latest_invoice(self) -> Invoice | None:
        """Fetch the most recent invoice."""
        invoices = await self.client.get_invoices()
        return invoices[0] if invoices else None

    async def _fetch_user_properties(self) -> UserProperties | None:
        """Fetch user profile properties (phone, email, PUA status)."""
        return await self.client.get_user_properties()
