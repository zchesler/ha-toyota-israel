"""Config flow for Toyota Israel.

There are two separate SMS flows here, which is unusual enough to be worth
spelling out:

1. Signing in to the Toyota account - phone number, Israeli ID, and a code.
2. Registering with Ituran for telematics, once per car, with a second code.

Step 2 is optional and mutually exclusive with the phone app: the Ituran
registration is exclusive per car, so claiming it here signs the app out of live
vehicle data, and signing back in on the app takes it away from Home Assistant.
Odometer and specs do not need it.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .api import (
    ToyotaApiError,
    ToyotaInvalidCredentials,
    ToyotaIsraelApi,
    ToyotaIturanNotRegistered,
    new_client_uuid,
)
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_CAR_UUIDS,
    CONF_PERSONAL_ID,
    CONF_PHONE,
    CONF_SCAN_INTERVAL_MINUTES,
    CONF_TELEMATICS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)
from .coordinator import ToyotaIsraelConfigEntry

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PHONE): str,
        vol.Required(CONF_PERSONAL_ID): str,
    }
)
STEP_CODE_SCHEMA = vol.Schema({vol.Required("code"): str})


class ToyotaIsraelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Toyota Israel config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._api: ToyotaIsraelApi | None = None
        self._phone: str = ""
        self._personal_id: str = ""
        self._consents_token: str = ""
        self._user_info: dict[str, Any] = {}
        self._cars: list[dict[str, Any]] = []
        self._pending: list[dict[str, Any]] = []
        self._car_uuids: dict[str, str] = {}
        self._active_uuid: str = ""

    # ------------------------------------------------------------- account login

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect the phone number and ID, and ask for an SMS code."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._phone = user_input[CONF_PHONE].strip()
            self._personal_id = user_input[CONF_PERSONAL_ID].strip()
            self._api = ToyotaIsraelApi(
                async_get_clientsession(self.hass), device_id=self.flow_id[:16]
            )
            try:
                self._consents_token = await self._api.async_request_login_code(
                    self._phone, self._personal_id
                )
            except ToyotaInvalidCredentials:
                errors["base"] = "no_account_match"
            except ToyotaApiError as err:
                _LOGGER.debug("requesting the login code failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                return await self.async_step_code()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_code(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Redeem the SMS code."""
        errors: dict[str, str] = {}
        if user_input is not None:
            assert self._api is not None
            try:
                self._user_info = await self._api.async_verify_login_code(
                    self._phone,
                    self._personal_id,
                    user_input["code"].strip(),
                    self._consents_token,
                )
            except ToyotaInvalidCredentials:
                errors["base"] = "invalid_code"
            except ToyotaApiError as err:
                _LOGGER.debug("verifying the login code failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                if self.source == "reauth":
                    return self.async_update_reload_and_abort(
                        self._get_reauth_entry(),
                        data_updates={
                            CONF_ACCESS_TOKEN: self._api.access_token,
                            CONF_PHONE: self._phone,
                            CONF_PERSONAL_ID: self._personal_id,
                        },
                    )
                await self.async_set_unique_id(str(self._user_info.get("id")))
                if self.source == "reconfigure":
                    # Same account, new token - do not treat it as a duplicate.
                    self._abort_if_unique_id_mismatch()
                else:
                    self._abort_if_unique_id_configured()
                self._cars = [
                    c
                    for c in self._user_info.get("carsInfo") or []
                    if isinstance(c, dict) and c.get("licensePlate")
                ]
                return await self.async_step_telematics()

        return self.async_show_form(
            step_id="code",
            data_schema=STEP_CODE_SCHEMA,
            errors=errors,
            description_placeholders={"phone": self._phone},
        )

    # ---------------------------------------------------------------- telematics

    async def async_step_telematics(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer live vehicle data, explaining what it costs."""
        connected = [c for c in self._cars if c.get("hasIturan")]
        if not connected:
            return self._create_entry(telematics=False)

        if user_input is not None:
            if not user_input["enable"]:
                return self._create_entry(telematics=False)
            self._pending = connected
            return await self.async_step_activate()

        return self.async_show_form(
            step_id="telematics",
            data_schema=vol.Schema({vol.Required("enable", default=True): bool}),
            description_placeholders={
                "cars": ", ".join(
                    c.get("modelInHebrew") or c["licensePlate"] for c in connected
                )
            },
        )

    async def async_step_activate(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Register this client with Ituran for the next car in the queue."""
        if not self._pending:
            return self._create_entry(telematics=True)

        assert self._api is not None
        car = self._pending[0]
        errors: dict[str, str] = {}
        self._active_uuid = new_client_uuid()
        try:
            await self._api.async_ituran_activate(
                self._phone, car["licensePlate"], self._active_uuid
            )
        except (ToyotaApiError, ToyotaIturanNotRegistered) as err:
            _LOGGER.debug("Ituran activation failed: %s", err)
            errors["base"] = "ituran_failed"
            # Submitting this form calls back in here and starts a fresh attempt.
            return self.async_show_form(
                step_id="activate",
                data_schema=vol.Schema({}),
                errors=errors,
                description_placeholders={
                    "car": car.get("modelInHebrew") or car["licensePlate"]
                },
            )
        return await self.async_step_activate_code()

    async def async_step_activate_code(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the Ituran SMS code for the car being registered."""
        assert self._api is not None
        car = self._pending[0]
        plate = car["licensePlate"]
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await self._api.async_ituran_verify(
                    self._phone, plate, user_input["code"].strip()
                )
                # Prove the registration took before moving on - verify reports
                # success even when the pairing did not stick.
                await self._api.async_get_location(plate, self._active_uuid)
            except ToyotaIturanNotRegistered:
                errors["base"] = "invalid_code"
            except ToyotaApiError as err:
                _LOGGER.debug("Ituran verification failed: %s", err)
                errors["base"] = "ituran_failed"
            else:
                self._car_uuids[plate] = self._active_uuid
                self._pending.pop(0)
                return await self.async_step_activate()

        return self.async_show_form(
            step_id="activate_code",
            data_schema=STEP_CODE_SCHEMA,
            errors=errors,
            description_placeholders={"car": car.get("modelInHebrew") or plate},
        )

    # --------------------------------------------------------------------- misc

    def _create_entry(self, *, telematics: bool) -> ConfigFlowResult:
        assert self._api is not None
        name = self._user_info.get("firstName") or self._phone
        data = {
            CONF_PHONE: self._phone,
            CONF_PERSONAL_ID: self._personal_id,
            CONF_ACCESS_TOKEN: self._api.access_token,
            CONF_TELEMATICS: telematics,
            CONF_CAR_UUIDS: self._car_uuids,
        }
        if self.source == "reconfigure":
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(), data_updates=data
            )
        return self.async_create_entry(title=f"Toyota ({name})", data=data)

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """The stored token stopped working."""
        self._phone = entry_data.get(CONF_PHONE, "")
        self._personal_id = entry_data.get(CONF_PERSONAL_ID, "")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                description_placeholders={"phone": self._phone},
            )
        return await self.async_step_user(
            {CONF_PHONE: self._phone, CONF_PERSONAL_ID: self._personal_id}
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-run the flow, typically to claim the Ituran registration back."""
        entry = self._get_reconfigure_entry()
        self._phone = entry.data.get(CONF_PHONE, "")
        self._personal_id = entry.data.get(CONF_PERSONAL_ID, "")
        return await self.async_step_user()

    @staticmethod
    @callback
    def async_get_options_flow(entry: ToyotaIsraelConfigEntry) -> OptionsFlow:
        return ToyotaIsraelOptionsFlow()


class ToyotaIsraelOptionsFlow(OptionsFlow):
    """How often to poll."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL_MINUTES,
            int(DEFAULT_SCAN_INTERVAL.total_seconds() // 60),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL_MINUTES, default=current
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=int(MIN_SCAN_INTERVAL.total_seconds() // 60),
                            max=720,
                            step=5,
                            unit_of_measurement="min",
                            mode=NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
        )
