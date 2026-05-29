"""Tests for the Nacka Energi API client."""

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.nacka_energi.api import (
    NackaEnergiAuthError,
    NackaEnergiClient,
    NackaEnergiConnectionError,
    NackaEnergiRateLimitError,
    UserProperties,
)

LOGIN_PAGE_HTML = """
<html>
<head>
<meta name="csrf-token" content="test_csrf_token_12345">
</head>
<body>Login page</body>
</html>
"""

SELECT_USER_ENTITY_HTML = """
<html>
<head>
<meta name="csrf-token" content="test_csrf_token_12345">
</head>
<body>
<div id="app">
<select-user-entity :entities="[{&quot;id&quot;:&quot;test_entity_id_1&quot;,&quot;limetype&quot;:&quot;portaluser&quot;,&quot;descriptive&quot;:&quot;Test User&quot;,&quot;descriptive_id&quot;:12345,&quot;descriptive_limetype&quot;:&quot;company&quot;},{&quot;id&quot;:&quot;test_entity_id_2&quot;,&quot;limetype&quot;:&quot;portaluser&quot;,&quot;descriptive&quot;:&quot;Test User 2&quot;,&quot;descriptive_id&quot;:67890,&quot;descriptive_limetype&quot;:&quot;company&quot;}]"></select-user-entity>
</div>
</body>
</html>
"""

SELECT_USER_ENTITY_SINGLE_HTML = """
<html>
<head>
<meta name="csrf-token" content="test_csrf_token_12345">
</head>
<body>
<div id="app">
<select-user-entity :entities="[{&quot;id&quot;:&quot;single_entity_id&quot;,&quot;limetype&quot;:&quot;portaluser&quot;,&quot;descriptive&quot;:&quot;Only User&quot;,&quot;descriptive_id&quot;:11111,&quot;descriptive_limetype&quot;:&quot;company&quot;}]"></select-user-entity>
</div>
</body>
</html>
"""

SELECT_USER_ENTITY_NO_ENTITIES_HTML = """
<html>
<head>
<meta name="csrf-token" content="test_csrf_token_12345">
</head>
<body>
<div id="app">
<select-user-entity></select-user-entity>
</div>
</body>
</html>
"""


def _make_response(status=200, json_data=None, text="", headers=None, cookies=None):
    """Create a mock aiohttp response."""
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data)
    resp.text = AsyncMock(return_value=text)
    resp.headers = headers or {}
    resp.history = []

    # Make headers iterable via getall
    real_headers = headers or {}
    resp.headers = MagicMock()
    resp.headers.getall = MagicMock(
        side_effect=lambda key, default=None: real_headers.get(key, default or [])
    )
    return resp


def _make_session(*responses):
    """Create a mock aiohttp session returning sequential responses."""
    session = AsyncMock()
    response_iter = iter(responses)

    class _ContextManager:
        def __init__(self, resp):
            self.resp = resp

        async def __aenter__(self):
            return self.resp

        async def __aexit__(self, *args):
            pass

    def _get(*args, **kwargs):
        return _ContextManager(next(response_iter))

    def _post(*args, **kwargs):
        return _ContextManager(next(response_iter))

    session.get = _get
    session.post = _post
    session.cookie_jar = MagicMock()
    return session


async def test_authenticate_success() -> None:
    """Test successful authentication."""
    login_page_resp = _make_response(
        status=200,
        text=LOGIN_PAGE_HTML,
        headers={
            "set-cookie": [
                "XSRF-TOKEN=test_xsrf; path=/",
                "nacka_energi_session=test_session; path=/",
            ]
        },
    )
    login_post_resp = _make_response(
        status=200,
        json_data={"success": True},
        headers={
            "set-cookie": [
                "XSRF-TOKEN=new_xsrf; path=/",
                "nacka_energi_session=new_session; path=/",
            ]
        },
    )

    session = _make_session(login_page_resp, login_post_resp)
    client = NackaEnergiClient("user@test.com", "password", session)

    await client.authenticate()

    assert client._csrf_token == "test_csrf_token_12345"


async def test_authenticate_success_redirect_300() -> None:
    """Test successful authentication with 300 redirect status."""
    login_page_resp = _make_response(
        status=200,
        text=LOGIN_PAGE_HTML,
        headers={
            "set-cookie": [
                "XSRF-TOKEN=test_xsrf; path=/",
                "nacka_energi_session=test_session; path=/",
            ]
        },
    )
    login_post_resp = _make_response(
        status=300,
        headers={
            "Location": "https://portal.nackaenergi.se/select-user-entity",
            "set-cookie": [
                "XSRF-TOKEN=new_xsrf; path=/",
                "nacka_energi_session=new_session; path=/",
            ],
        },
    )

    session = _make_session(login_page_resp, login_post_resp)
    client = NackaEnergiClient("user@test.com", "password", session)

    await client.authenticate()

    assert client._csrf_token == "test_csrf_token_12345"


async def test_authenticate_invalid_credentials() -> None:
    """Test authentication with invalid credentials."""
    login_page_resp = _make_response(
        status=200,
        text=LOGIN_PAGE_HTML,
        headers={
            "set-cookie": [
                "XSRF-TOKEN=test_xsrf; path=/",
            ]
        },
    )
    login_post_resp = _make_response(status=422)

    session = _make_session(login_page_resp, login_post_resp)
    client = NackaEnergiClient("user@test.com", "wrong", session)

    with pytest.raises(NackaEnergiAuthError):
        await client.authenticate()


async def test_authenticate_no_csrf_token() -> None:
    """Test authentication when CSRF token is missing from page."""
    login_page_resp = _make_response(
        status=200,
        text="<html><body>No token</body></html>",
        headers={"set-cookie": []},
    )

    session = _make_session(login_page_resp)
    client = NackaEnergiClient("user@test.com", "password", session)

    with pytest.raises(NackaEnergiConnectionError, match="CSRF token"):
        await client.authenticate()


async def test_get_user_entities() -> None:
    """Test fetching user entities from the select-user-entity page."""
    entity_page_resp = _make_response(
        status=200,
        text=SELECT_USER_ENTITY_HTML,
        headers={"set-cookie": []},
    )

    session = _make_session(entity_page_resp)
    client = NackaEnergiClient("user@test.com", "password", session)
    client._csrf_token = "test_token"
    client._cookies = {"XSRF-TOKEN": "test_xsrf", "nacka_energi_session": "test"}
    client._authenticated_at = datetime.now()

    entities = await client.get_user_entities()

    assert len(entities) == 2
    assert entities[0].id == "test_entity_id_1"
    assert entities[0].limetype == "portaluser"
    assert entities[0].descriptive == "Test User"
    assert entities[0].descriptive_id == 12345
    assert entities[0].descriptive_limetype == "company"
    assert entities[1].id == "test_entity_id_2"
    assert entities[1].descriptive == "Test User 2"


async def test_get_user_entities_single() -> None:
    """Test fetching user entities when only one entity exists."""
    entity_page_resp = _make_response(
        status=200,
        text=SELECT_USER_ENTITY_SINGLE_HTML,
        headers={"set-cookie": []},
    )

    session = _make_session(entity_page_resp)
    client = NackaEnergiClient("user@test.com", "password", session)
    client._csrf_token = "test_token"
    client._cookies = {"XSRF-TOKEN": "test_xsrf", "nacka_energi_session": "test"}
    client._authenticated_at = datetime.now()

    entities = await client.get_user_entities()

    assert len(entities) == 1
    assert entities[0].id == "single_entity_id"
    assert entities[0].descriptive == "Only User"


async def test_get_user_entities_no_entities() -> None:
    """Test fetching user entities when no entities are found in the page."""
    entity_page_resp = _make_response(
        status=200,
        text=SELECT_USER_ENTITY_NO_ENTITIES_HTML,
        headers={"set-cookie": []},
    )

    session = _make_session(entity_page_resp)
    client = NackaEnergiClient("user@test.com", "password", session)
    client._csrf_token = "test_token"
    client._cookies = {"XSRF-TOKEN": "test_xsrf", "nacka_energi_session": "test"}
    client._authenticated_at = datetime.now()

    with pytest.raises(
        NackaEnergiConnectionError, match="Could not find user entities"
    ):
        await client.get_user_entities()


async def test_get_user_entities_non_200_status() -> None:
    """Test fetching user entities when the page returns a non-200 status."""
    entity_page_resp = _make_response(
        status=500,
        text="Server Error",
        headers={"set-cookie": []},
    )

    session = _make_session(entity_page_resp)
    client = NackaEnergiClient("user@test.com", "password", session)
    client._csrf_token = "test_token"
    client._cookies = {"XSRF-TOKEN": "test_xsrf", "nacka_nergi_session": "test"}
    client._authenticated_at = datetime.now()

    with pytest.raises(
        NackaEnergiConnectionError, match="Failed to load entity selection page"
    ):
        await client.get_user_entities()


async def test_set_user_entity() -> None:
    """Test selecting a user entity."""
    set_entity_resp = _make_response(
        status=200,
        json_data={"success": True},
        headers={"set-cookie": []},
    )

    session = _make_session(set_entity_resp)
    client = NackaEnergiClient("user@test.com", "password", session)
    client._csrf_token = "test_token"
    client._cookies = {"XSRF-TOKEN": "test_xsrf", "nacka_energi_session": "test"}
    client._authenticated_at = datetime.now()

    # Should not raise
    await client.set_user_entity("test_entity_id")


async def test_get_metering_points() -> None:
    """Test fetching metering points."""
    api_resp = _make_response(
        status=200,
        json_data=[
            {"text": "Address 1 - 123456", "value": "encoded_id_1"},
            {"text": "Address 2 - 789012", "value": "encoded_id_2"},
        ],
        headers={"set-cookie": []},
    )

    session = _make_session(api_resp)
    client = NackaEnergiClient("user@test.com", "password", session)
    client._csrf_token = "test_token"
    client._cookies = {"XSRF-TOKEN": "test_xsrf", "nacka_energi_session": "test"}
    client._authenticated_at = datetime.now()

    points = await client.get_metering_points()

    assert len(points) == 2
    assert points[0].name == "Address 1 - 123456"
    assert points[0].value == "encoded_id_1"


async def test_get_consumption() -> None:
    """Test fetching consumption data."""
    api_resp = _make_response(
        status=200,
        json_data={
            "quantities": [0.387, 0.773],
            "items": [
                {
                    "PeriodStart": "2026-02-13T00:00:00",
                    "PeriodEnd": "2026-02-13T01:00:00",
                    "Quantity": 0.387,
                    "Unit": "kWh",
                    "QualityName": "OK",
                    "Created": "2026-02-13T07:00:41.2908206",
                    "IsSmear": False,
                },
                {
                    "PeriodStart": "2026-02-13T01:00:00",
                    "PeriodEnd": "2026-02-13T02:00:00",
                    "Quantity": 0.773,
                    "Unit": "kWh",
                    "QualityName": "OK",
                    "Created": "2026-02-13T07:00:41.2908206",
                    "IsSmear": False,
                },
            ],
        },
        headers={"set-cookie": []},
    )

    session = _make_session(api_resp)
    client = NackaEnergiClient("user@test.com", "password", session)
    client._csrf_token = "test_token"
    client._cookies = {"XSRF-TOKEN": "test_xsrf", "nacka_energi_session": "test"}
    client._authenticated_at = datetime.now()

    entries = await client.get_consumption(
        "encoded_id", "4", date(2026, 2, 13), date(2026, 2, 14)
    )

    assert len(entries) == 2
    assert entries[0].quantity == 0.387
    assert entries[0].unit == "kWh"
    assert entries[1].quantity == 0.773


async def test_get_invoices() -> None:
    """Test fetching invoices."""
    api_resp = _make_response(
        status=200,
        json_data={
            "data": [
                {
                    "invoiceref": "11064875815",
                    "invoice_amount": 477,
                    "paid_amount": None,
                    "balance_amount": 477,
                    "invoice_date": "2026-02-09T01:00:00+01:00",
                    "duedate": "2026-03-02T01:00:00+01:00",
                    "paid_status": "unpaid",
                    "claimlockuntil": None,
                    "invoicing_delivery": "12",
                    "_id": "test_id_1",
                    "_createdtime": "2026-02-09T12:18:14.250000+01:00",
                },
                {
                    "invoiceref": "11062021818",
                    "invoice_amount": 534,
                    "paid_amount": 534,
                    "balance_amount": 0,
                    "invoice_date": "2026-01-09T01:00:00+01:00",
                    "duedate": "2026-02-02T01:00:00+01:00",
                    "paid_status": "paid",
                    "claimlockuntil": None,
                    "invoicing_delivery": "12",
                    "_id": "test_id_2",
                    "_createdtime": "2026-01-09T11:38:11.840000+01:00",
                },
            ]
        },
        headers={"set-cookie": []},
    )

    session = _make_session(api_resp)
    client = NackaEnergiClient("user@test.com", "password", session)
    client._csrf_token = "test_token"
    client._cookies = {"XSRF-TOKEN": "test_xsrf", "nacka_energi_session": "test"}
    client._authenticated_at = datetime.now()

    invoices = await client.get_invoices()

    assert len(invoices) == 2
    assert invoices[0].invoice_ref == "11064875815"
    assert invoices[0].invoice_amount == 477
    assert invoices[0].paid_amount is None
    assert invoices[0].balance_amount == 477
    assert invoices[0].paid_status == "unpaid"
    assert invoices[1].invoice_ref == "11062021818"
    assert invoices[1].paid_amount == 534


async def test_get_user_properties() -> None:
    """Test fetching user properties."""
    api_resp = _make_response(
        status=200,
        json_data={
            "mobilephone": "+46700000000",
            "email": "test@example.com",
            "pua": False,
        },
        headers={"set-cookie": []},
    )

    session = _make_session(api_resp)
    client = NackaEnergiClient("user@test.com", "password", session)
    client._csrf_token = "test_token"
    client._cookies = {"XSRF-TOKEN": "test_xsrf", "nacka_energi_session": "test"}
    client._authenticated_at = datetime.now()

    props = await client.get_user_properties()

    assert isinstance(props, UserProperties)
    assert props.mobilephone == "+46700000000"
    assert props.email == "test@example.com"
    assert props.pua is False


async def test_get_user_properties_null_fields() -> None:
    """Test fetching user properties with null/missing fields."""
    api_resp = _make_response(
        status=200,
        json_data={
            "mobilephone": None,
            "email": None,
            "pua": False,
        },
        headers={"set-cookie": []},
    )

    session = _make_session(api_resp)
    client = NackaEnergiClient("user@test.com", "password", session)
    client._csrf_token = "test_token"
    client._cookies = {"XSRF-TOKEN": "test_xsrf", "nacka_energi_session": "test"}
    client._authenticated_at = datetime.now()

    props = await client.get_user_properties()

    assert props.mobilephone is None
    assert props.email is None
    assert props.pua is False


async def test_authenticate_rate_limited() -> None:
    """Test authentication raises RateLimitError on 429."""
    login_page_resp = _make_response(
        status=200,
        text=LOGIN_PAGE_HTML,
        headers={
            "set-cookie": [
                "XSRF-TOKEN=test_xsrf; path=/",
                "nacka_energi_session=test_session; path=/",
            ]
        },
    )
    login_post_resp = _make_response(status=429)

    session = _make_session(login_page_resp, login_post_resp)
    client = NackaEnergiClient("user@test.com", "password", session)

    with pytest.raises(NackaEnergiRateLimitError, match="429"):
        await client.authenticate()


async def test_auth_throttle_skips_rapid_reauth() -> None:
    """Test that authenticate() skips if called within 60s of last auth."""
    login_page_resp = _make_response(
        status=200,
        text=LOGIN_PAGE_HTML,
        headers={
            "set-cookie": [
                "XSRF-TOKEN=test_xsrf; path=/",
            ]
        },
    )
    login_post_resp = _make_response(
        status=200,
        json_data={"success": True},
        headers={"set-cookie": []},
    )

    session = _make_session(login_page_resp, login_post_resp)
    client = NackaEnergiClient("user@test.com", "password", session)

    # First call should authenticate
    await client.authenticate()
    assert client._authenticated_at is not None

    # Second call within 60s should be a no-op (no extra requests made)
    await client.authenticate()
    # If a third request had been made it would raise StopIteration
    # from the exhausted response iterator — passing here proves throttle works.


async def test_authenticated_get_raises_on_429() -> None:
    """Test that _authenticated_get raises RateLimitError on 429."""
    api_resp = _make_response(
        status=429,
        headers={"set-cookie": []},
    )

    session = _make_session(api_resp)
    client = NackaEnergiClient("user@test.com", "password", session)
    client._csrf_token = "test_token"
    client._cookies = {"XSRF-TOKEN": "test_xsrf"}
    client._authenticated_at = datetime.now()

    with pytest.raises(NackaEnergiRateLimitError, match="429"):
        await client.get_metering_points()


async def test_x_user_agent_header() -> None:
    """Test that the X-User-Agent header is set to the current portal version."""
    client = NackaEnergiClient("user@test.com", "password", AsyncMock())
    headers = client._common_headers()
    assert headers["X-User-Agent"] == "Lime Portal v2.19.0"


async def test_common_headers_include_csrf_and_xsrf() -> None:
    """Test that common headers include CSRF and XSRF tokens when set."""
    client = NackaEnergiClient("user@test.com", "password", AsyncMock())
    client._csrf_token = "test_csrf"
    client._cookies = {"XSRF-TOKEN": "test_xsrf"}

    headers = client._common_headers()
    assert headers["X-CSRF-TOKEN"] == "test_csrf"
    assert headers["X-XSRF-TOKEN"] == "test_xsrf"
    assert headers["X-Requested-With"] == "XMLHttpRequest"
    assert headers["X-Accept-Language"] == "sv"


async def test_get_consumption_empty_response() -> None:
    """Test fetching consumption data with empty/missing items."""
    api_resp = _make_response(
        status=200,
        json_data={"quantities": []},
        headers={"set-cookie": []},
    )

    session = _make_session(api_resp)
    client = NackaEnergiClient("user@test.com", "password", session)
    client._csrf_token = "test_token"
    client._cookies = {"XSRF-TOKEN": "test_xsrf", "nacka_energi_session": "test"}
    client._authenticated_at = datetime.now()

    entries = await client.get_consumption(
        "encoded_id", "4", date(2026, 2, 13), date(2026, 2, 14)
    )

    assert entries == []


async def test_get_invoices_empty_response() -> None:
    """Test fetching invoices with empty data."""
    api_resp = _make_response(
        status=200,
        json_data={"data": []},
        headers={"set-cookie": []},
    )

    session = _make_session(api_resp)
    client = NackaEnergiClient("user@test.com", "password", session)
    client._csrf_token = "test_token"
    client._cookies = {"XSRF-TOKEN": "test_xsrf", "nacka_energi_session": "test"}
    client._authenticated_at = datetime.now()

    invoices = await client.get_invoices()
    assert invoices == []


async def test_get_user_properties_unexpected_format() -> None:
    """Test fetching user properties when response is not a dict."""
    api_resp = _make_response(
        status=200,
        json_data=["not", "a", "dict"],
        headers={"set-cookie": []},
    )

    session = _make_session(api_resp)
    client = NackaEnergiClient("user@test.com", "password", session)
    client._csrf_token = "test_token"
    client._cookies = {"XSRF-TOKEN": "test_xsrf", "nacka_energi_session": "test"}
    client._authenticated_at = datetime.now()

    with pytest.raises(
        NackaEnergiConnectionError, match="Unexpected user properties response"
    ):
        await client.get_user_properties()
