"""Data update coordinator for Nacka Energi."""

from __future__ import annotations

import zoneinfo
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    ConsumptionEntry,
    Invoice,
    NackaEnergiAuthError,
    NackaEnergiClient,
    NackaEnergiConnectionError,
    NackaEnergiRateLimitError,
    UserProperties,
)
from .const import (
    DOMAIN,
    LOGGER,
    PERIOD_TYPE_DAILY,
    PERIOD_TYPE_HOURLY,
    PERIOD_TYPE_MONTHLY,
)

_PORTAL_TZ = zoneinfo.ZoneInfo("Europe/Stockholm")


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
        all_hourly: list[ConsumptionEntry] = []

        try:
            hourly, all_hourly = await self._fetch_hourly_usage()
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

        if all_hourly:
            try:
                await self._inject_hourly_statistics(all_hourly)
            except Exception as err:  # noqa: BLE001
                LOGGER.warning("Failed to inject hourly statistics: %s", err)

        return NackaEnergiData(
            hourly_usage=hourly,
            daily_usage=daily,
            monthly_usage=monthly,
            monthly_usage_current=monthly_current,
            yearly_usage_kwh=yearly,
            latest_invoice=latest_invoice,
            user_properties=user_properties,
        )

    async def _inject_hourly_statistics(
        self, ok_entries: list[ConsumptionEntry]
    ) -> None:
        """Inject all available OK hourly entries into HA's statistics recorder.

        Uses ``async_add_external_statistics`` so each hour's energy lands at
        its actual timestamp in the energy dashboard, regardless of when the
        coordinator polled. The running sum is continued from whatever the
        recorder already holds, so re-runs are idempotent.
        """
        statistic_id = f"{DOMAIN}:{self.config_entry.unique_id}_hourly_energy"

        recorder = get_instance(self.hass)
        last_stats = await recorder.async_add_executor_job(
            get_last_statistics,
            self.hass,
            1,
            statistic_id,
            False,
            {"sum"},
        )

        last_sum = 0.0
        last_start_ts = 0.0
        if statistic_id in last_stats and last_stats[statistic_id]:
            row = last_stats[statistic_id][0]
            last_sum = row.get("sum") or 0.0
            last_start_ts = row.get("start") or 0.0

        # Only append hours strictly newer than the latest one already recorded,
        # continuing the cumulative sum. This keeps re-runs idempotent. Note the
        # trade-off: an OK hour that arrives *after* a later hour was recorded
        # (e.g. a mid-series gap that fills late, or an estimate revised to OK)
        # is not back-filled, because doing so would require recomputing the sum
        # of every subsequent hour. In practice the portal delivers hours in
        # order in 2-hour batches and only the most recent hours are ever
        # pending, so gaps occur at the tail and are picked up on the next poll.
        new_stats: list[StatisticData] = []
        running_sum = last_sum
        prev_utc: datetime | None = None
        for entry in ok_entries:
            start_utc = self._period_start_to_utc(entry.period_start, prev_utc)
            prev_utc = start_utc
            if start_utc.timestamp() <= last_start_ts:
                continue
            running_sum += entry.quantity
            new_stats.append(
                StatisticData(
                    start=start_utc,
                    state=entry.quantity,
                    sum=running_sum,
                )
            )

        if not new_stats:
            return

        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"{self.config_entry.title} hourly energy",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_class="energy",
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        )
        async_add_external_statistics(self.hass, metadata, new_stats)
        LOGGER.debug(
            "Injected %d hourly statistics entries (running sum: %.3f kWh)",
            len(new_stats),
            running_sum,
        )

    @staticmethod
    def _period_start_to_utc(period_start: str, prev_utc: datetime | None) -> datetime:
        """Convert a naive local (Europe/Stockholm) period start to UTC.

        During the autumn DST fall-back the 02:00-03:00 wall-clock hour repeats
        and both occurrences share the same ``period_start`` string. They are
        disambiguated by order: when converting yields a timestamp that is not
        strictly after the previous entry, it must be the second (``fold=1``)
        occurrence. Callers must pass entries in ascending period order.
        """
        naive = datetime.fromisoformat(period_start)
        start_utc = naive.replace(tzinfo=_PORTAL_TZ).astimezone(dt_util.UTC)
        if prev_utc is not None and start_utc <= prev_utc:
            start_utc = naive.replace(tzinfo=_PORTAL_TZ, fold=1).astimezone(dt_util.UTC)
        return start_utc

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

    async def _fetch_hourly_usage(
        self,
    ) -> tuple[ConsumptionEntry | None, list[ConsumptionEntry]]:
        """Fetch hourly consumption entries for today and yesterday.

        Returns ``(latest_ok_entry, all_ok_entries)``. The latest entry drives
        the sensor state; all entries are passed to ``_inject_hourly_statistics``
        so every completed hour lands in the recorder at its actual timestamp.
        Fetches from yesterday to cover the midnight boundary — the 23:00-00:00
        hour starts on the previous day.
        """
        today = date.today()
        yesterday = today - timedelta(days=1)
        tomorrow = today + timedelta(days=1)

        entries = await self.client.get_consumption(
            self.serviceplace_id, PERIOD_TYPE_HOURLY, yesterday, tomorrow
        )

        # Sort ascending by period start so the running sum and dedup in
        # _inject_hourly_statistics are correct, and so [-1] is genuinely the
        # latest hour, regardless of the order the API returns entries in.
        ok_entries = sorted(
            (e for e in entries if e.quality_name.upper() == "OK"),
            key=lambda e: e.period_start,
        )
        return (ok_entries[-1] if ok_entries else None), ok_entries

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
