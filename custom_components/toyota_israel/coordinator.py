"""Polling coordinator for Toyota Israel."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    ToyotaApiError,
    ToyotaAuthError,
    ToyotaIsraelApi,
    ToyotaIturanNotRegistered,
)
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_CAR_UUIDS,
    CONF_CHARGING_SCAN_INTERVAL_MINUTES,
    CONF_PHONE,
    CONF_SCAN_INTERVAL_MINUTES,
    CONF_TELEMATICS,
    DEFAULT_CHARGING_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    IGNITION_WITH_BATTERY,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class CarData:
    """Everything known about one car after a refresh."""

    car: dict[str, Any]
    appointment: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    location: dict[str, Any] | None = None
    battery: dict[str, Any] | None = None
    driving: dict[str, Any] | None = None
    ituran_username: str | None = None
    ituran_plate: str | None = None
    telematics_lost: bool = False

    @property
    def plate(self) -> str:
        return self.car.get("licensePlate", "")

    @property
    def name(self) -> str:
        return self.car.get("modelInHebrew") or self.plate

    @property
    def is_charging(self) -> bool:
        return bool((self.battery or {}).get("isCharging"))

    @property
    def has_battery(self) -> bool:
        """Whether this car reports a traction battery."""
        return bool(self.car.get("hasIturanEv")) and (
            self.car.get("ignitionType") in IGNITION_WITH_BATTERY
        )

    @property
    def odometer(self) -> int | None:
        """Odometer in km.

        carExtraInfo is the better source: it needs only the account token, so it
        keeps working when the Ituran registration has been taken over by the
        phone app. getLocation reports the same figure when both are available.
        """
        for value in (self.extra.get("mileage"), (self.location or {}).get("milage")):
            if isinstance(value, (int, float)):
                return int(value)
        return None


type ToyotaIsraelConfigEntry = ConfigEntry[ToyotaIsraelCoordinator]


class ToyotaIsraelCoordinator(DataUpdateCoordinator[dict[str, CarData]]):
    """Fetches every car on the account on one schedule."""

    config_entry: ToyotaIsraelConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ToyotaIsraelConfigEntry) -> None:
        minutes = entry.options.get(CONF_SCAN_INTERVAL_MINUTES)
        self._idle_interval = (
            timedelta(minutes=minutes) if minutes else DEFAULT_SCAN_INTERVAL
        )
        charging_minutes = entry.options.get(CONF_CHARGING_SCAN_INTERVAL_MINUTES)
        self._charging_interval = (
            timedelta(minutes=charging_minutes)
            if charging_minutes
            else DEFAULT_CHARGING_SCAN_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=self._idle_interval,
            config_entry=entry,
        )
        self.api = ToyotaIsraelApi(
            async_get_clientsession(hass),
            device_id=entry.entry_id[:16],
            access_token=entry.data[CONF_ACCESS_TOKEN],
        )
        self._phone: str = entry.data[CONF_PHONE]
        self._telematics: bool = entry.data.get(CONF_TELEMATICS, False)
        self._car_uuids: dict[str, str] = dict(entry.data.get(CONF_CAR_UUIDS) or {})
        # Remembered between refreshes so a failed getLocation does not take the
        # battery call down with it.
        self._ituran_names: dict[str, str] = {}
        self._ituran_plates: dict[str, str] = {}
        # Plates already warned about, so a lost registration is logged once.
        self._lost_warned: set[str] = set()

    async def _async_update_data(self) -> dict[str, CarData]:
        try:
            items = await self.api.async_get_home_items()
        except ToyotaAuthError as err:
            raise ConfigEntryAuthFailed("sign in again") from err
        except ToyotaApiError as err:
            raise UpdateFailed(f"could not list cars: {err}") from err

        result: dict[str, CarData] = {}
        for item in items:
            car = item["car"]
            plate = car.get("licensePlate")
            if not plate:
                continue
            appointment = item.get("nextAppointment")
            data = CarData(
                car=car,
                appointment=appointment if isinstance(appointment, dict) else {},
            )
            try:
                data.extra = await self.api.async_get_car_extra_info(plate)
            except ToyotaApiError as err:
                _LOGGER.debug("carExtraInfo failed for %s: %s", data.name, err)

            if self._telematics and car.get("hasIturan"):
                await self._async_add_telematics(data)
            result[plate] = data

        if not result:
            raise UpdateFailed("the account reported no cars")

        self._apply_interval(result)
        return result

    def _apply_interval(self, cars: dict[str, CarData]) -> None:
        """Poll faster while a car is charging, and back off once it stops."""
        wanted = (
            self._charging_interval
            if any(car.is_charging for car in cars.values())
            else self._idle_interval
        )
        if wanted != self.update_interval:
            _LOGGER.debug("switching poll interval to %s", wanted)
            self.update_interval = wanted

    async def _async_add_telematics(self, data: CarData) -> None:
        """Fill in location, battery and driving data for one car.

        A lost registration is not fatal: the account-level data stays valid, so the
        telematics entities simply go unavailable until the user re-registers.
        """
        plate = data.plate
        client_uuid = self._car_uuids.get(plate)
        if not client_uuid:
            return

        try:
            data.location = await self.api.async_get_location(plate, client_uuid)
        except ToyotaIturanNotRegistered as err:
            if plate not in self._lost_warned:
                self._lost_warned.add(plate)
                _LOGGER.warning(
                    "Telematics for %s are no longer registered to Home Assistant "
                    "(%s). Signing in to the MyTOYOTA app takes the registration "
                    "over; reconfigure the integration to claim it back",
                    data.name,
                    err,
                )
            data.telematics_lost = True
            return
        except ToyotaApiError as err:
            _LOGGER.debug("getLocation failed for %s: %s", data.name, err)
            return

        self._lost_warned.discard(plate)

        # getLocation is what reveals the Ituran username and its own plate
        # spelling; both are needed by the calls below.
        if name := data.location.get("userName"):
            self._ituran_names[plate] = name
        if ituran_plate := data.location.get("licensePlate"):
            self._ituran_plates[plate] = ituran_plate
        data.ituran_username = self._ituran_names.get(plate)
        data.ituran_plate = self._ituran_plates.get(plate)

        if not data.ituran_username:
            return

        if data.has_battery:
            try:
                data.battery = await self.api.async_get_battery(
                    plate, client_uuid, data.ituran_username
                )
            except (ToyotaApiError, ToyotaIturanNotRegistered) as err:
                _LOGGER.debug("getBatteryInfo failed for %s: %s", data.name, err)

        if data.car.get("hasIturanSafety") and data.ituran_plate:
            try:
                data.driving = await self.api.async_get_driving_report(
                    data.ituran_plate, client_uuid, data.ituran_username
                )
            except (ToyotaApiError, ToyotaIturanNotRegistered) as err:
                _LOGGER.debug("drivingReport failed for %s: %s", data.name, err)
