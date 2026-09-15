"""Binary sensors for Toyota Israel."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import CarData, ToyotaIsraelConfigEntry
from .entity import ToyotaIsraelEntity


@dataclass(frozen=True, kw_only=True)
class ToyotaBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a Toyota Israel binary sensor."""

    value_fn: Callable[[CarData], bool | None]
    exists_fn: Callable[[CarData], bool] = lambda _: True


BINARY_SENSORS: tuple[ToyotaBinarySensorDescription, ...] = (
    ToyotaBinarySensorDescription(
        key="charging",
        translation_key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=lambda c: (c.battery or {}).get("isCharging"),
        exists_fn=lambda c: c.has_battery,
    ),
    ToyotaBinarySensorDescription(
        key="charging_ac",
        translation_key="charging_ac",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda c: (c.battery or {}).get("isChargingAC"),
        exists_fn=lambda c: c.has_battery,
    ),
    ToyotaBinarySensorDescription(
        key="battery_low",
        translation_key="battery_low",
        device_class=BinarySensorDeviceClass.BATTERY,
        value_fn=lambda c: (
            None
            if (level := (c.battery or {}).get("batteryPercentage")) is None
            else level <= 15  # the threshold the app turns its gauge red at
        ),
        exists_fn=lambda c: c.has_battery,
    ),
    ToyotaBinarySensorDescription(
        key="service_booked",
        translation_key="service_booked",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: bool(c.appointment.get("haveAppointment")),
        exists_fn=lambda c: "haveAppointment" in c.appointment,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ToyotaIsraelConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors for every car."""
    coordinator = entry.runtime_data
    async_add_entities(
        ToyotaIsraelBinarySensor(coordinator, plate, description)
        for plate, car in coordinator.data.items()
        for description in BINARY_SENSORS
        if description.exists_fn(car)
    )


class ToyotaIsraelBinarySensor(ToyotaIsraelEntity, BinarySensorEntity):
    """A yes/no state from the car."""

    entity_description: ToyotaBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        car = self.car
        return self.entity_description.value_fn(car) if car else None

    @property
    def available(self) -> bool:
        return super().available and self.is_on is not None
