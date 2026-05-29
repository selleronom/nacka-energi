# Nacka Energi for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A custom [Home Assistant](https://www.home-assistant.io/) integration for
[Nacka Energi](https://www.nackaenergi.se/) that reads electricity consumption
and invoice data from the customer portal at `portal.nackaenergi.se`.

> Unofficial integration. Not affiliated with or endorsed by Nacka Energi.

## Features

The integration polls the Nacka Energi portal and exposes the following sensors:

| Sensor | Description |
| --- | --- |
| Hourly energy usage | Most recent hourly consumption (kWh) |
| Daily energy usage | Most recent daily consumption (kWh) |
| Monthly energy usage | Previous completed month's consumption (kWh) |
| Current month energy usage | Consumption so far this month (kWh) |
| Yearly energy usage | Year-to-date consumption (kWh) |
| Latest invoice amount | Amount of the most recent invoice |
| Latest invoice balance | Outstanding balance on the most recent invoice |
| Latest invoice due date | Due date of the most recent invoice |
| Latest invoice status | Paid/unpaid status of the most recent invoice |
| User email | Email registered on the account |
| User phone | Phone number registered on the account |

The energy sensors are compatible with the Home Assistant **Energy dashboard**.

## Installation

### HACS (recommended)

1. In Home Assistant, go to **HACS → Integrations**.
2. Open the **⋮** menu (top right) → **Custom repositories**.
3. Add `https://github.com/selleronom/nacka-energi` with category **Integration**.
4. Search for **Nacka Energi**, download it, and **restart Home Assistant**.

### Manual

1. Copy the `custom_components/nacka_energi` directory into your Home Assistant
   `config/custom_components/` directory.
2. Restart Home Assistant.

## Configuration

After installation, add the integration via the UI:

**Settings → Devices & Services → Add Integration → Nacka Energi**

You will be asked for:

1. **Username (email)** and **password** for your Nacka Energi portal account.
2. The **user entity** to associate with the integration (if your account has
   more than one).
3. The **metering point** to monitor.

All configuration is done through the UI — no YAML required.

## How it works

The portal uses a Lime CRM platform that requires a multi-step authentication
and entity-selection flow before any data endpoints become available. The
integration handles this flow automatically, refreshes the session before it
expires (~90 minutes), and re-resolves the (rotating) entity and serviceplace
identifiers by their stable human-readable names on each setup.

Polling follows Home Assistant's cloud-service guidance and is not
user-configurable.

## Development

```bash
# Install dev dependencies (uses uv)
uv sync

# Run the test suite
pytest tests/components/nacka_energi \
  --cov=custom_components.nacka_energi \
  --cov-report term-missing
```

A `docker-compose.yml` is provided that mounts the integration into a Home
Assistant container for local manual testing.

## Disclaimer

This is a community project provided "as is". The Nacka Energi portal is not a
public API and may change at any time, which can break the integration.

## License

[MIT](LICENSE)
