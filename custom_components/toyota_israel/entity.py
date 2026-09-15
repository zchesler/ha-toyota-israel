"""Base entity for Toyota Israel."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CarData, ToyotaIsraelCoordinator


class ToyotaIsraelEntity(CoordinatorEntity[ToyotaIsraelCoordinator]):
    """An entity belonging to one car."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ToyotaIsraelCoordinator,
        plate: str,
        description: EntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self._plate = plate
        self.entity_description = description
        self._attr_unique_id = f"{plate}_{description.key}"

    @property
    def car(self) -> CarData | None:
        return self.coordinator.data.get(self._plate)

    @property
    def device_info(self) -> DeviceInfo:
        car = self.car
        raw = car.car if car else {}
        extra = car.extra if car else {}
        model = raw.get("modelInHebrew") or self._plate
        # modelCode is only present on homepage/get, and finishType only on
        # carExtraInfo, so a trim-qualified model name is best-effort.
        if trim := extra.get("finishType"):
            model = f"{model} {trim}"
        return DeviceInfo(
            identifiers={(DOMAIN, self._plate)},
            manufacturer="Toyota",
            name=raw.get("modelInHebrew") or self._plate,
            model=model,
            model_id=raw.get("modelCode"),
            serial_number=self._plate,
            configuration_url="https://www.toyota.co.il/",
        )

    @property
    def available(self) -> bool:
        return super().available and self.car is not None
