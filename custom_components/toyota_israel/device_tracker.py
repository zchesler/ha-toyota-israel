"""Device tracker for Toyota Israel."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ToyotaIsraelConfigEntry
from .entity import ToyotaIsraelEntity

DESCRIPTION = EntityDescription(key="location", translation_key="location")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ToyotaIsraelConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a tracker for every car with telematics."""
    coordinator = entry.runtime_data
    async_add_entities(
        ToyotaIsraelTracker(coordinator, plate, DESCRIPTION)
        for plate, car in coordinator.data.items()
        if car.car.get("hasIturan")
    )


class ToyotaIsraelTracker(ToyotaIsraelEntity, TrackerEntity):
    """Where the car is."""

    _attr_source_type = SourceType.GPS

    @property
    def _location(self) -> dict[str, Any]:
        car = self.car
        return (car.location or {}) if car else {}

    @property
    def latitude(self) -> float | None:
        value = self._location.get("lat")
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def longitude(self) -> float | None:
        value = self._location.get("lon")
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def available(self) -> bool:
        return super().available and self.latitude is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        location = self._location
        attributes: dict[str, Any] = {}
        if address := location.get("address"):
            attributes["address"] = address
        if city := location.get("city"):
            attributes["city"] = city
        if isinstance(heading := location.get("head"), (int, float)):
            attributes["heading"] = heading
        return attributes or None
