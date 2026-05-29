"""Constants for the Nacka Energi integration."""

import logging

DOMAIN = "nacka_energi"
LOGGER = logging.getLogger(__package__)

CONF_ENTITY_ID = "entity_id"
CONF_ENTITY_NAME = "entity_name"
CONF_METERING_POINT = "metering_point"
CONF_METERING_POINT_NAME = "metering_point_name"

BASE_URL = "https://portal.nackaenergi.se"
LOGIN_PAGE_URL = f"{BASE_URL}/auth/login"
LOGIN_POST_URL = f"{BASE_URL}/auth/login/custom-limetype"
SERVICEPLACE_URL = f"{BASE_URL}/domain-endpoint/statistics/serviceplace"
CONSUMPTION_URL = (
    f"{BASE_URL}/domain-endpoint/statistics/{{serviceplace_id}}/consumptiondata"
)
INVOICE_URL = f"{BASE_URL}/domain-endpoint/invoice"
SELECT_USER_ENTITY_URL = f"{BASE_URL}/select-user-entity"
SET_USER_ENTITY_URL = f"{BASE_URL}/auth/set-user-entity"
USER_PROPERTIES_URL = f"{BASE_URL}/domain-endpoint/my_profile/fetch_properties"

PERIOD_TYPE_HOURLY = "4"
PERIOD_TYPE_DAILY = "5"
PERIOD_TYPE_MONTHLY = "6"
