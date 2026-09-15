"""Sensors for Toyota Israel."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfLength,
    UnitOfPower,
    UnitOfPressure,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import CarData, ToyotaIsraelConfigEntry
from .entity import ToyotaIsraelEntity


def _number(value: Any) -> float | None:
    """Coerce the API's stringly-typed numbers, tolerating junk like '0' or ''."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = dt_util.parse_datetime(str(value))
    return dt_util.as_local(parsed) if parsed else None


@dataclass(frozen=True, kw_only=True)
class ToyotaSensorDescription(SensorEntityDescription):
    """Describes a Toyota Israel sensor."""

    value_fn: Callable[[CarData], Any]
    exists_fn: Callable[[CarData], bool] = lambda _: True
    # Whether the source that feeds this sensor answered at all. A source that
    # answered without a value yields "unknown"; only a source we could not read
    # makes the entity unavailable.
    available_fn: Callable[[CarData], bool] = lambda _: True


SENSORS: tuple[ToyotaSensorDescription, ...] = (
    # --- the ones people actually watch -------------------------------------
    ToyotaSensorDescription(
        key="battery",
        translation_key="battery",
        available_fn=lambda c: c.battery is not None,
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: (c.battery or {}).get("batteryPercentage"),
        exists_fn=lambda c: c.has_battery,
    ),
    ToyotaSensorDescription(
        key="range",
        translation_key="range",
        available_fn=lambda c: c.battery is not None,
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda c: (c.battery or {}).get("rangeLeftOnBatteryPower"),
        exists_fn=lambda c: c.has_battery,
    ),
    ToyotaSensorDescription(
        key="odometer",
        translation_key="odometer",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        value_fn=lambda c: c.odometer,
    ),
    ToyotaSensorDescription(
        key="charging_time_left",
        translation_key="charging_time_left",
        available_fn=lambda c: c.battery is not None,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda c: (c.battery or {}).get("chargingMinutesLeftTillFullBattery"),
        exists_fn=lambda c: c.has_battery,
    ),
    ToyotaSensorDescription(
        key="charging_power",
        translation_key="charging_power",
        available_fn=lambda c: c.battery is not None,
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        # chargingCurrent has been null in every observation, including mid-charge
        # on AC, so this is off by default - enable it if DC charging turns out to
        # populate it. The unit is inferred: its siblings maxChargingCurrentAC/DC
        # match the car's kW ratings exactly (22 / 150), so it is power, not amps.
        entity_registry_enabled_default=False,
        value_fn=lambda c: _number((c.battery or {}).get("chargingCurrent")),
        exists_fn=lambda c: c.has_battery,
    ),
    ToyotaSensorDescription(
        key="location_address",
        translation_key="location_address",
        available_fn=lambda c: c.location is not None,
        value_fn=lambda c: (
            ", ".join(
                p for p in (
                    (c.location or {}).get("address"),
                    (c.location or {}).get("city"),
                ) if p
            ) or None
        ),
        exists_fn=lambda c: bool(c.car.get("hasIturan")),
    ),
    # --- diagnostics ---------------------------------------------------------
    ToyotaSensorDescription(
        key="battery_capacity",
        translation_key="battery_capacity",
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda c: _number(c.extra.get("evBatteryCapacity")),
        exists_fn=lambda c: c.has_battery,
    ),
    ToyotaSensorDescription(
        key="rated_range",
        translation_key="rated_range",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda c: _number(c.extra.get("evRange")),
        exists_fn=lambda c: c.has_battery,
    ),
    ToyotaSensorDescription(
        key="max_charging_power_ac",
        translation_key="max_charging_power_ac",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # The battery call nulls these while charging; carExtraInfo does not.
        value_fn=lambda c: (
            _number(c.extra.get("evMaxPowerForAc"))
            or (c.battery or {}).get("maxChargingCurrentAC")
        ),
        exists_fn=lambda c: c.has_battery,
    ),
    ToyotaSensorDescription(
        key="max_charging_power_dc",
        translation_key="max_charging_power_dc",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda c: (
            _number(c.extra.get("evMaxPowerForDc"))
            or (c.battery or {}).get("maxChargingCurrentDC")
        ),
        exists_fn=lambda c: c.has_battery,
    ),
    ToyotaSensorDescription(
        key="tyre_pressure_front",
        translation_key="tyre_pressure_front",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.PSI,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # The recommended pressure from the handbook, not a live TPMS reading.
        value_fn=lambda c: _number(c.extra.get("frontTirePressure")),
    ),
    ToyotaSensorDescription(
        key="tyre_pressure_rear",
        translation_key="tyre_pressure_rear",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.PSI,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda c: _number(c.extra.get("backTirePressure")),
    ),
    ToyotaSensorDescription(
        key="on_road_date",
        translation_key="on_road_date",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        # "upToRoadDate" is when the car was first registered, not an expiry -
        # a 2019 model reports 2019 and a car delivered this month reports this
        # month.
        value_fn=lambda c: _date(c.extra.get("upToRoadDate")),
    ),
    ToyotaSensorDescription(
        key="service_interval",
        translation_key="service_interval",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.extra.get("treatmentInterval") or None,
    ),
    ToyotaSensorDescription(
        key="insurance_reminder",
        translation_key="insurance_reminder",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda c: _date(c.extra.get("insuranceReminderDate")),
    ),
    # --- driving safety, when the account exposes it -------------------------
    ToyotaSensorDescription(
        key="safety_grade",
        translation_key="safety_grade",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: (c.driving or {}).get("safetyGrade"),
        exists_fn=lambda c: c.driving is not None,
    ),
    ToyotaSensorDescription(
        key="distance_this_month",
        translation_key="distance_this_month",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda c: (c.driving or {}).get("totalKM"),
        exists_fn=lambda c: c.driving is not None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ToyotaIsraelConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors for every car."""
    coordinator = entry.runtime_data
    async_add_entities(
        ToyotaIsraelSensor(coordinator, plate, description)
        for plate, car in coordinator.data.items()
        for description in SENSORS
        if description.exists_fn(car)
    )


class ToyotaIsraelSensor(ToyotaIsraelEntity, SensorEntity):
    """A single reading from the car."""

    entity_description: ToyotaSensorDescription

    @property
    def native_value(self) -> Any:
        car = self.car
        return self.entity_description.value_fn(car) if car else None

    @property
    def available(self) -> bool:
        if not super().available or (car := self.car) is None:
            return False
        return self.entity_description.available_fn(car)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != "safety_grade":
            return None
        events = (self.car.driving or {}).get("safetyEvents") if self.car else None
        return dict(events) if isinstance(events, dict) else None
