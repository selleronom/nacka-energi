"""API client for Nacka Energi portal."""

from __future__ import annotations

import asyncio
import html as html_module
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from http.cookies import SimpleCookie

import aiohttp

from .const import (
    CONSUMPTION_URL,
    INVOICE_URL,
    LOGGER,
    LOGIN_PAGE_URL,
    LOGIN_POST_URL,
    SELECT_USER_ENTITY_URL,
    SERVICEPLACE_URL,
    SET_USER_ENTITY_URL,
    USER_PROPERTIES_URL,
)

MIN_AUTH_INTERVAL = timedelta(seconds=60)

# Regex to extract entity data from the select-user-entity page HTML.
# The page embeds a Vue component like:
#   <select-user-entity :entities="[{&quot;id&quot;:…}]"></select-user-entity>
# The :entities attribute value is HTML-escaped JSON.
_ENTITY_RE = re.compile(r":entities=\"([^\"]*)\"", re.IGNORECASE)


class NackaEnergiAuthError(Exception):
    """Raised when authentication fails."""


class NackaEnergiConnectionError(Exception):
    """Raised when connection fails."""


class NackaEnergiRateLimitError(NackaEnergiConnectionError):
    """Raised when the API returns 429 Too Many Requests."""


@dataclass
class MeteringPoint:
    """A metering point (service place)."""

    name: str
    value: str


@dataclass
class UserEntity:
    """A user entity from the select-user-entity page.

    The portal embeds entity choices in the HTML of the select-user-entity
    page.  Each entity represents a portal user context that must be
    explicitly selected before data endpoints become available.
    """

    id: str
    limetype: str
    descriptive: str
    descriptive_id: int
    descriptive_limetype: str


@dataclass
class ConsumptionEntry:
    """A single consumption data point."""

    period_start: str
    period_end: str
    quantity: float
    unit: str
    quality_name: str
    created: str | None
    is_smear: bool


@dataclass
class Invoice:
    """An invoice from Nacka Energi."""

    invoice_ref: str
    invoice_amount: float
    paid_amount: float | None
    balance_amount: float
    invoice_date: str
    due_date: str
    paid_status: str
    invoicing_delivery: str


@dataclass
class UserProperties:
    """User profile properties from Nacka Energi."""

    mobilephone: str | None
    email: str | None
    pua: bool


class NackaEnergiClient:
    """Client for the Nacka Energi portal API."""

    def __init__(
        self,
        username: str,
        password: str,
        session: aiohttp.ClientSession,
        entity_name: str | None = None,
        entity_id: str | None = None,
    ) -> None:
        """Initialize the client.

        ``entity_name`` and ``entity_id`` describe the portal user entity that
        must be re-selected on every login.  When set, ``authenticate()`` will
        also POST to ``/auth/set-user-entity`` so data endpoints work after a
        session refresh.  Entity IDs may rotate between sessions, so matching
        is preferred by ``entity_name`` with ``entity_id`` as a fallback.
        """
        self._username = username
        self._password = password
        self._session = session
        self._entity_name = entity_name
        self._entity_id = entity_id
        self._csrf_token: str | None = None
        self._cookies: dict[str, str] = {}
        self._authenticated_at: datetime | None = None
        self._session_lifetime = timedelta(
            minutes=90
        )  # Cookies expire after 2h; refresh at 90min
        self._auth_lock = asyncio.Lock()

    @property
    def entity_id(self) -> str | None:
        """Return the currently selected entity ID (may rotate on re-auth)."""
        return self._entity_id

    def _common_headers(self) -> dict[str, str]:
        """Return headers required for authenticated requests."""
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "X-Accept-Language": "sv",
            "X-User-Agent": "Lime Portal v2.19.0",
            "Accept": "application/json, text/plain, */*",
        }
        if self._csrf_token:
            headers["X-CSRF-TOKEN"] = self._csrf_token
        if xsrf := self._cookies.get("XSRF-TOKEN"):
            headers["X-XSRF-TOKEN"] = xsrf
        return headers

    def _cookie_header(self) -> str:
        """Build cookie header string."""
        return "; ".join(f"{k}={v}" for k, v in self._cookies.items())

    def _update_cookies(self, response: aiohttp.ClientResponse) -> None:
        """Extract and update cookies from response headers."""
        for header_value in response.headers.getall("set-cookie", []):
            cookie: SimpleCookie = SimpleCookie()
            cookie.load(header_value)
            for key, morsel in cookie.items():
                self._cookies[key] = morsel.value

    def _session_expired(self) -> bool:
        """Return True if the session is missing or older than the refresh threshold."""
        if self._authenticated_at is None:
            return True
        return datetime.now() - self._authenticated_at >= self._session_lifetime

    async def authenticate(self) -> None:
        """Perform full login flow.

        Uses a lock to prevent concurrent authentication attempts and enforces
        a minimum interval of 60 seconds between login requests to respect
        the portal's rate limit of 5 attempts per window.
        """
        async with self._auth_lock:
            # Throttle: skip if we authenticated recently (prevents cascading re-auths)
            if (
                self._authenticated_at is not None
                and datetime.now() - self._authenticated_at < MIN_AUTH_INTERVAL
            ):
                LOGGER.debug(
                    "Skipping re-authentication, last auth was %s ago",
                    datetime.now() - self._authenticated_at,
                )
                return

            # Clear stale session state so the login page is served fresh
            # instead of the server 302-redirecting an "already logged-in" user.
            self._cookies.clear()
            self._csrf_token = None
            self._session.cookie_jar.clear()

            try:
                await self._fetch_login_page()
                await self._post_login()
                # Mark the session authenticated *before* selecting the entity
                # so the nested set-user-entity POST does not see an "expired"
                # session and recursively call authenticate() (which would
                # deadlock on the non-reentrant auth lock).
                self._authenticated_at = datetime.now()
                if self._entity_name or self._entity_id:
                    await self._select_entity()
            except aiohttp.ClientError as err:
                self._authenticated_at = None
                LOGGER.debug("HTTP client error during authenticate: %s", err)
                raise NackaEnergiConnectionError(f"Connection error: {err}") from err
            except NackaEnergiConnectionError:
                self._authenticated_at = None
                LOGGER.debug("Connection error during authenticate")
                raise
            except NackaEnergiAuthError:
                self._authenticated_at = None
                LOGGER.debug("Authentication failed due to invalid credentials")
                raise
            except Exception as err:  # Defensive catch for unexpected errors
                self._authenticated_at = None
                LOGGER.exception("Unexpected error during authenticate: %s", err)
                raise NackaEnergiConnectionError(
                    f"Unexpected authentication error: {err}"
                ) from err

    async def _select_entity(self) -> None:
        """Re-fetch entities and select the one matching the stored name.

        Entity IDs are opaque and may rotate between sessions, so we match by
        descriptive name first and fall back to the stored ID, then to the
        first available entity.  The resolved ID is stored on the client so
        callers can persist it if it changed.
        """
        entities = await self.get_user_entities()
        if not entities:
            raise NackaEnergiConnectionError("No user entities available after login")

        selected = entities[0]
        if self._entity_name:
            for e in entities:
                if e.descriptive == self._entity_name:
                    selected = e
                    break
        elif self._entity_id:
            for e in entities:
                if e.id == self._entity_id:
                    selected = e
                    break

        await self.set_user_entity(selected.id)
        if selected.id != self._entity_id:
            LOGGER.info(
                "Entity ID rotated for %s: %s -> %s",
                self._entity_name or "(unknown)",
                self._entity_id,
                selected.id,
            )
        self._entity_id = selected.id

    async def _fetch_login_page(self) -> None:
        """Fetch login page to get CSRF token and initial cookies."""
        async with self._session.get(
            LOGIN_PAGE_URL,
            allow_redirects=True,
            headers={"Accept": "text/html"},
        ) as resp:
            self._update_cookies(resp)
            # Also check redirects in history
            for hist_resp in resp.history:
                self._update_cookies(hist_resp)

            text = await resp.text()
            # Be flexible when parsing the CSRF meta tag - attribute order
            # may change and the site can use single or double quotes.
            match = re.search(
                r'<meta[^>]*name=["\']csrf-token["\'][^>]*content=["\']([^"\']+)["\']',
                text,
                re.IGNORECASE,
            )
            if not match:
                LOGGER.debug(
                    "Login page did not contain CSRF token; status=%s, snippet=%s",
                    resp.status,
                    (text[:500] + "...") if len(text) > 500 else text,
                )
                raise NackaEnergiConnectionError(
                    "Could not find CSRF token on login page"
                )
            self._csrf_token = match.group(1)
            LOGGER.debug("Fetched login page; csrf_token=%s", self._csrf_token)

    async def _post_login(self) -> None:
        """Post login credentials."""
        headers = self._common_headers()
        headers["Content-Type"] = "application/json"
        headers["Referer"] = LOGIN_PAGE_URL
        headers["Cookie"] = self._cookie_header()

        async with self._session.post(
            LOGIN_POST_URL,
            json={"username": self._username, "password": self._password},
            headers=headers,
            allow_redirects=False,
        ) as resp:
            self._update_cookies(resp)

            if resp.status == 422:
                raise NackaEnergiAuthError("Invalid username or password")

            if resp.status == 429:
                raise NackaEnergiRateLimitError(
                    "Rate limited by portal (429). Try again later."
                )

            # Accept 200 (JSON response), 300 (redirect to entity selection),
            # or 302 (redirect) as success.
            if resp.status not in (200, 300, 302):
                text = await resp.text()
                LOGGER.debug(
                    "Login POST returned unexpected status %s; body=%s",
                    resp.status,
                    (text[:500] + "...") if len(text) > 500 else text,
                )
                raise NackaEnergiConnectionError(f"Login returned status {resp.status}")

            # If JSON is returned, respect an explicit failure flag.
            if resp.status == 200:
                try:
                    data = await resp.json()
                except Exception:
                    # Non-JSON 200 responses are unexpected but treat as success
                    LOGGER.debug(
                        "Login POST returned non-JSON 200 response; treating as success"
                    )
                    return

                if isinstance(data, dict) and not data.get("success", True):
                    raise NackaEnergiAuthError("Login was not successful")

            LOGGER.debug("Login POST successful; status=%s", resp.status)

    async def _authenticated_get(
        self, url: str, _retry: bool = True, **kwargs: str
    ) -> dict | list:
        """Make an authenticated GET request.

        Proactively refreshes the session when it approaches the 2-hour expiry,
        and retries once on responses that indicate an expired session.
        The authenticate() lock and throttle prevent cascading re-auth calls
        when multiple API requests detect an expired session simultaneously.
        """
        if self._session_expired():
            LOGGER.debug("Session near expiry, proactively re-authenticating")
            await self.authenticate()

        headers = self._common_headers()
        headers["Cookie"] = self._cookie_header()

        async with self._session.get(
            url,
            headers=headers,
            params=kwargs,
            allow_redirects=False,
        ) as resp:
            self._update_cookies(resp)

            if resp.status == 429:
                raise NackaEnergiRateLimitError(
                    f"Rate limited by portal (429) on {url}"
                )

            if resp.status in (302, 401, 419) and _retry:
                LOGGER.debug(
                    "Possible session expiry (status %s), re-authenticating",
                    resp.status,
                )
                await self.authenticate()
                return await self._authenticated_get(url, _retry=False, **kwargs)

            if resp.status != 200:
                raise NackaEnergiConnectionError(
                    f"Request to {url} returned status {resp.status}"
                )

            return await resp.json()

    async def _authenticated_post(
        self, url: str, json: dict | None = None, _retry: bool = True
    ) -> dict | list | None:
        """Make an authenticated POST request with one retry on auth/redirect.

        Mirrors _authenticated_get behavior for POSTs that may return JSON
        or no content (204). Raises the same connection/auth/rate limit
        exceptions as the GET helper.
        """
        if self._session_expired():
            LOGGER.debug("Session near expiry, proactively re-authenticating")
            await self.authenticate()

        headers = self._common_headers()
        headers["Cookie"] = self._cookie_header()

        async with self._session.post(
            url, headers=headers, json=json, allow_redirects=False
        ) as resp:
            self._update_cookies(resp)

            if resp.status == 429:
                raise NackaEnergiRateLimitError(
                    f"Rate limited by portal (429) on {url}"
                )

            if resp.status in (302, 401, 419) and _retry:
                LOGGER.debug(
                    "Possible session expiry on POST (status %s), re-authenticating",
                    resp.status,
                )
                await self.authenticate()
                return await self._authenticated_post(url, json=json, _retry=False)

            # Allow 200/204 as success; try to decode JSON when present
            if resp.status not in (200, 204):
                raise NackaEnergiConnectionError(
                    f"POST to {url} returned status {resp.status}"
                )

            # 204 No Content
            if resp.status == 204:
                return None

            # Attempt to parse JSON; callers can handle dict/list return types
            return await resp.json()

    async def get_user_entities(self) -> list[UserEntity]:
        """Fetch available user entities from the select-user-entity page.

        After login the portal presents a page at /select-user-entity that
        embeds the available entity choices as a Vue component prop.  This
        method parses that HTML and returns the entity list so the caller can
        present a selection or auto-pick the only option.
        """
        headers = self._common_headers()
        headers["Cookie"] = self._cookie_header()
        headers["Accept"] = (
            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        )
        headers["Referer"] = LOGIN_PAGE_URL

        async with self._session.get(
            SELECT_USER_ENTITY_URL,
            headers=headers,
            allow_redirects=True,
        ) as resp:
            self._update_cookies(resp)
            for hist_resp in resp.history:
                self._update_cookies(hist_resp)

            if resp.status != 200:
                raise NackaEnergiConnectionError(
                    f"Failed to load entity selection page (status {resp.status})"
                )

            text = await resp.text()

        match = _ENTITY_RE.search(text)
        if not match:
            LOGGER.debug(
                "select-user-entity page did not contain entity data; "
                "page length=%d, snippet=%s",
                len(text),
                (text[:500] + "...") if len(text) > 500 else text,
            )
            raise NackaEnergiConnectionError(
                "Could not find user entities on selection page"
            )

        entities_raw = html_module.unescape(match.group(1))

        # The attribute value may contain trailing characters after the JSON
        # array (e.g. from the closing "></select-user-entity>").  Find the
        # bounding brackets and parse only the JSON array.
        start = entities_raw.find("[")
        end = entities_raw.rfind("]")
        if start == -1 or end == -1 or end <= start:
            raise NackaEnergiConnectionError(
                "Could not parse entity data from selection page"
            )

        json_str = entities_raw[start : end + 1]

        try:
            entities_data = json.loads(json_str)
        except json.JSONDecodeError as err:
            LOGGER.debug(
                "Failed to parse entity JSON: %s; snippet=%s", err, json_str[:300]
            )
            raise NackaEnergiConnectionError(
                f"Could not parse entity data: {err}"
            ) from err

        if not isinstance(entities_data, list):
            raise NackaEnergiConnectionError(
                "Unexpected entity data format on selection page"
            )

        return [
            UserEntity(
                id=e["id"],
                limetype=e.get("limetype", ""),
                descriptive=e.get("descriptive", ""),
                descriptive_id=e.get("descriptive_id", 0),
                descriptive_limetype=e.get("descriptive_limetype", ""),
            )
            for e in entities_data
        ]

    async def set_user_entity(self, entity_id: str) -> None:
        """Select the active user entity (serviceplace) for the session.

        The portal requires an explicit selection of the "user entity" after
        login; POSTing the chosen `entityId` ensures subsequent API calls
        return data for that service place.
        """
        await self._authenticated_post(
            SET_USER_ENTITY_URL, json={"entityId": entity_id}
        )

    async def get_metering_points(self) -> list[MeteringPoint]:
        """Fetch available metering points.

        Must be called after set_user_entity() or the endpoint returns 500.
        """
        data = await self._authenticated_get(SERVICEPLACE_URL)
        if not isinstance(data, list):
            raise NackaEnergiConnectionError("Unexpected metering points response")
        return [MeteringPoint(name=item["text"], value=item["value"]) for item in data]

    async def get_consumption(
        self,
        serviceplace_id: str,
        period_type: str,
        period_start: date,
        period_end: date,
    ) -> list[ConsumptionEntry]:
        """Fetch consumption data for a metering point."""
        url = CONSUMPTION_URL.format(serviceplace_id=serviceplace_id)
        data = await self._authenticated_get(
            url,
            periodtype=period_type,
            periodstart=period_start.isoformat(),
            periodend=period_end.isoformat(),
        )
        if not isinstance(data, dict) or "items" not in data:
            return []
        return [
            ConsumptionEntry(
                period_start=item["PeriodStart"],
                period_end=item["PeriodEnd"],
                quantity=item["Quantity"],
                unit=item["Unit"],
                quality_name=item.get("QualityName", "Unknown"),
                created=item.get("Created"),
                is_smear=item.get("IsSmear", False),
            )
            for item in data["items"]
        ]

    async def get_invoices(self) -> list[Invoice]:
        """Fetch invoices, sorted newest first."""
        data = await self._authenticated_get(INVOICE_URL)
        if not isinstance(data, dict) or "data" not in data:
            return []
        return [
            Invoice(
                invoice_ref=item["invoiceref"],
                invoice_amount=item["invoice_amount"],
                paid_amount=item.get("paid_amount"),
                balance_amount=item["balance_amount"],
                invoice_date=item["invoice_date"],
                due_date=item["duedate"],
                paid_status=item["paid_status"],
                invoicing_delivery=item.get("invoicing_delivery", ""),
            )
            for item in data["data"]
        ]

    async def get_user_properties(self) -> UserProperties:
        """Fetch user profile properties (phone, email, PUA status)."""
        data = await self._authenticated_get(USER_PROPERTIES_URL)
        if not isinstance(data, dict):
            raise NackaEnergiConnectionError(
                "Unexpected user properties response format"
            )
        return UserProperties(
            mobilephone=data.get("mobilephone"),
            email=data.get("email"),
            pua=bool(data.get("pua", False)),
        )
