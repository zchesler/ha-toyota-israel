"""Client for the MyTOYOTA Israel (Union Motors) API.

The wire format is documented in docs/API.md. Two things are worth remembering
when changing anything here:

* Field names come from the live server, not from the app's Kotlin classes - the
  two disagree in several places (``phoneNumber`` vs ``mobilePhone``, ``smallText``
  vs ``smallTex``), and the app declares response fields the server never sends.
* Errors arrive as HTTP 200 with a non-zero ``errorCode``; only auth failures use a
  real HTTP status.
"""

from __future__ import annotations

import logging
import uuid as uuidlib
from typing import Any

from aiohttp import ClientError, ClientSession

from .const import (
    APP_SIGNATURE,
    APP_VERSION,
    BASE_URL,
    ERR_ITURAN_GENERIC,
    ERR_ITURAN_NO_PLATE_LINK,
    ERR_ITURAN_NOT_REGISTERED,
    ERR_NO_PHONE_ID_MATCH,
    TERMS_CONSENT,
)

_LOGGER = logging.getLogger(__name__)


class ToyotaIsraelError(Exception):
    """Base error."""


class ToyotaAuthError(ToyotaIsraelError):
    """The access token is missing, expired or rejected."""


class ToyotaInvalidCredentials(ToyotaIsraelError):
    """No account links this phone number and ID, or the SMS code was wrong."""


class ToyotaIturanNotRegistered(ToyotaIsraelError):
    """This client's Ituran UUID is not registered for the car.

    Raised for 92001, and for the generic 11111 which the server also returns when
    the UUID is unusable. Registration is exclusive per car: signing in on the
    phone app displaces Home Assistant's UUID and vice versa.
    """


class ToyotaApiError(ToyotaIsraelError):
    """Any other API-level failure."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


def new_client_uuid() -> str:
    """Return a fresh client UUID, the way the app generates one."""
    return str(uuidlib.uuid4())


class ToyotaIsraelApi:
    """Talks to my-toyota.toyota.co.il."""

    def __init__(
        self,
        session: ClientSession,
        device_id: str,
        access_token: str | None = None,
    ) -> None:
        self._session = session
        self._device_id = device_id
        self.access_token = access_token

    # ------------------------------------------------------------------ transport

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "Accept-Language": "he",
            "AppVersion": APP_VERSION,
            "DeviceId": self._device_id,
            "DeviceOS": "Android",
            "DeviceOSVersion": "13",
            "DeviceModel": "HomeAssistant",
            "Platform": "Application",
            "X-App-Signature": APP_SIGNATURE,
        }
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        try:
            async with self._session.request(
                method,
                BASE_URL + path,
                json=json,
                params=params,
                headers=self._headers(),
            ) as response:
                if response.status == 401:
                    raise ToyotaAuthError(f"{path}: token rejected")
                payload = await response.json(content_type=None)
                if response.status >= 400 and not isinstance(payload, dict):
                    raise ToyotaApiError(f"{path}: HTTP {response.status}")
        except ClientError as err:
            raise ToyotaApiError(f"{path}: {err}") from err

        if not isinstance(payload, dict):
            raise ToyotaApiError(f"{path}: unexpected response {payload!r}")

        code = payload.get("errorCode") or 0
        if code:
            message = payload.get("errorMessage") or f"errorCode {code}"
            if code in (ERR_ITURAN_NOT_REGISTERED, ERR_ITURAN_GENERIC):
                raise ToyotaIturanNotRegistered(message)
            if code == ERR_NO_PHONE_ID_MATCH:
                raise ToyotaInvalidCredentials(message)
            raise ToyotaApiError(f"{path}: {message}", code)
        return payload.get("body")

    # ----------------------------------------------------------------- login flow

    async def async_request_login_code(self, phone: str, personal_id: str) -> str:
        """Ask for an SMS code. Returns the consents token needed to redeem it."""
        body = await self._request(
            "POST",
            "account/generateVerificationCodeV2",
            json={
                "phoneNumber": phone,
                "personalId": personal_id,
                "consents": [TERMS_CONSENT],
            },
        )
        if not isinstance(body, dict) or not body.get("consentsToken"):
            raise ToyotaApiError("no consentsToken in the verification-code response")
        return body["consentsToken"]

    async def async_verify_login_code(
        self, phone: str, personal_id: str, code: str, consents_token: str
    ) -> dict[str, Any]:
        """Redeem the SMS code. Stores the access token and returns userInfo."""
        # Note the inconsistency: step one wants phoneNumber, this one wants
        # mobilePhone. Sending phoneNumber here returns a 500.
        try:
            body = await self._request(
                "POST",
                "account/verifyUserV2",
                json={
                    "mobilePhone": phone,
                    "personalId": personal_id,
                    "verificationCode": code,
                    "consentsToken": consents_token,
                },
            )
        except ToyotaApiError as err:
            # A wrong or expired code surfaces as a server-side failure rather than
            # a tidy validation error.
            if err.code == 500:
                raise ToyotaInvalidCredentials(
                    "the code was wrong or has expired"
                ) from err
            raise
        user_info = (body or {}).get("userInfo") if isinstance(body, dict) else None
        if not isinstance(user_info, dict) or not user_info.get("accessToken"):
            raise ToyotaApiError("no accessToken in the verification response")
        self.access_token = user_info["accessToken"]
        return user_info

    # ---------------------------------------------------------------- account data

    async def async_get_user_info(self) -> dict[str, Any]:
        body = await self._request("GET", "account/getUserInfo")
        return body if isinstance(body, dict) else {}

    async def async_get_homepage(self) -> dict[str, Any]:
        body = await self._request("GET", "homepage/get")
        return body if isinstance(body, dict) else {}

    async def async_get_car_extra_info(self, plate: str) -> dict[str, Any]:
        """Specs and mileage for one car. Note the parameter is plateNumber."""
        body = await self._request(
            "GET", "car/carExtraInfo", params={"plateNumber": plate}
        )
        return body if isinstance(body, dict) else {}

    async def async_get_home_items(self) -> list[dict[str, Any]]:
        """Return one ``{car, nextAppointment, ...}`` item per car.

        homepage/get is preferred: it carries modelCode, modelFamily and the next
        service appointment, none of which getUserInfo provides. The fallback wraps
        getUserInfo's plain car list in the same shape.
        """
        try:
            home = await self.async_get_homepage()
        except ToyotaApiError as err:
            _LOGGER.debug("homepage/get failed, falling back to getUserInfo: %s", err)
        else:
            items = [
                item
                for item in home.get("homePageCarItems") or []
                if isinstance(item, dict) and isinstance(item.get("car"), dict)
            ]
            if items:
                return items
        user_info = await self.async_get_user_info()
        return [
            {"car": c} for c in user_info.get("carsInfo") or [] if isinstance(c, dict)
        ]

    # -------------------------------------------------------------------- telematics

    async def async_ituran_activate(
        self, phone: str, plate: str, key: str
    ) -> dict[str, Any]:
        """Register `key` as this client's UUID. Triggers an SMS from Ituran."""
        body = await self._request(
            "POST",
            "ituran/activate",
            json={"phoneNumber": phone, "plate": plate, "key": key},
        )
        return body if isinstance(body, dict) else {}

    async def async_ituran_verify(
        self, phone: str, plate: str, otp: str
    ) -> dict[str, Any]:
        body = await self._request(
            "POST",
            "ituran/verify",
            json={"phoneNumber": phone, "plate": plate, "otpCode": otp},
        )
        return body if isinstance(body, dict) else {}

    async def async_get_location(self, plate: str, client_uuid: str) -> dict[str, Any]:
        """Position, address and odometer.

        The response also carries ``userName``, the Ituran account name that the
        other telematics calls need, and ``licensePlate`` in Ituran's own spelling.
        userLatitude/userLongitude are the phone's position and only feed
        ``distanceInMeters``, so they are sent as null.
        """
        body = await self._request(
            "POST",
            "ituran/getLocation",
            json={
                "plate": plate,
                "uuid": client_uuid,
                "version": APP_VERSION,
                "userLatitude": None,
                "userLongitude": None,
            },
        )
        return body if isinstance(body, dict) else {}

    async def async_get_battery(
        self, plate: str, client_uuid: str, ituran_username: str
    ) -> dict[str, Any]:
        """EV battery state.

        ``platformId`` really does take the Ituran username again - the app reads
        getUserName() twice and passes it for both fields. Sending "Android" there
        fails with 11111.
        """
        body = await self._request(
            "POST",
            "ituran/getBatteryInfo",
            json={
                "licensePlate": plate,
                "uuid": client_uuid,
                "username": ituran_username,
                "platformId": ituran_username,
            },
        )
        return body if isinstance(body, dict) else {}

    async def async_get_driving_report(
        self,
        ituran_plate: str,
        client_uuid: str,
        ituran_username: str,
        period: str = "Month",
    ) -> dict[str, Any] | None:
        """Safety score and event counts, or None when unavailable.

        Keyed on Ituran's own plate spelling from getLocation. Returns None on
        95555, which some accounts get for this endpoint even with
        hasIturanSafety set.
        """
        try:
            body = await self._request(
                "POST",
                "ituran/drivingReport",
                json={
                    "plateNumber": ituran_plate,
                    "uuid": client_uuid,
                    "username": ituran_username,
                    "reportPeriod": period,
                },
            )
        except ToyotaApiError as err:
            if err.code == ERR_ITURAN_NO_PLATE_LINK:
                return None
            raise
        return body if isinstance(body, dict) else None
