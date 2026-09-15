"""Diagnostics for Toyota Israel."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_ACCESS_TOKEN, CONF_CAR_UUIDS, CONF_PERSONAL_ID, CONF_PHONE
from .coordinator import ToyotaIsraelConfigEntry

REDACT_CONFIG = {CONF_ACCESS_TOKEN, CONF_PERSONAL_ID, CONF_PHONE, CONF_CAR_UUIDS}

# Anything that identifies the owner, the car, or the Ituran registration.
REDACT_DATA = {
    "licensePlate",
    "plate",
    "carNo",
    "userName",
    "address",
    "lat",
    "lon",
    "phoneNumber",
    "garageNumber",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ToyotaIsraelConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), REDACT_CONFIG),
        "options": dict(entry.options),
        "cars": [
            {
                "car": async_redact_data(car.car, REDACT_DATA),
                "extra": async_redact_data(car.extra, REDACT_DATA),
                "location": async_redact_data(car.location or {}, REDACT_DATA),
                "battery": car.battery,
                "driving": car.driving,
                "telematics_lost": car.telematics_lost,
                "has_battery": car.has_battery,
                "odometer": car.odometer,
            }
            for car in coordinator.data.values()
        ],
    }
