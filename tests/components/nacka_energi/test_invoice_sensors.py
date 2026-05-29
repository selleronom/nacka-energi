from datetime import date

import pytest

from custom_components.nacka_energi.sensor import (
    NackaEnergiInvoiceSensor,
)


@pytest.mark.asyncio
async def test_invoice_sensors(mock_coordinator, mock_data):
    coordinator, entry = mock_coordinator
    coordinator.data = mock_data

    from custom_components.nacka_energi.sensor import INVOICE_SENSORS

    # Amount
    amount_desc = next(d for d in INVOICE_SENSORS if d.key == "latest_invoice_amount")
    sensor = NackaEnergiInvoiceSensor(coordinator, amount_desc, entry)
    assert sensor.native_value == 123.45
    assert sensor.extra_state_attributes["invoice_ref"] == "INV-123"

    # Balance
    balance_desc = next(d for d in INVOICE_SENSORS if d.key == "latest_invoice_balance")
    sensor = NackaEnergiInvoiceSensor(coordinator, balance_desc, entry)
    assert sensor.native_value == 123.45

    # Due Date
    due_date_desc = next(
        d for d in INVOICE_SENSORS if d.key == "latest_invoice_due_date"
    )
    sensor = NackaEnergiInvoiceSensor(coordinator, due_date_desc, entry)
    assert sensor.native_value == date(2026, 2, 15)

    # Status
    status_desc = next(d for d in INVOICE_SENSORS if d.key == "latest_invoice_status")
    sensor = NackaEnergiInvoiceSensor(coordinator, status_desc, entry)
    assert sensor.native_value == "unpaid"
    assert sensor.extra_state_attributes["invoice_ref"] == "INV-123"
