"""Constants for the Toyota Israel integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "toyota_israel"

BASE_URL: Final = "https://my-toyota.toyota.co.il/api/"

# Mirrors the phone app. The server enforces a minimum build
# (Application.UpdateForceMinVersionAndroid in settings/all), so this needs to keep
# up with the published app rather than being pinned forever.
APP_VERSION: Final = "2.2.41"

# Lowercase hex SHA-256 of the app's X.509 signing certificate, which the app sends
# as X-App-Signature. It is a constant, identical for every install.
APP_SIGNATURE: Final = (
    "efa3a9bbf63b1a7f47895e5924482b004f66c4baf6a2b2665a792631c61f8d5f"
)

# The server will not issue a login code without the terms consent. Marketing
# consent is deliberately never sent - signing in must not opt anyone into it.
TERMS_CONSENT: Final = {
    "consentType": "TermsAndPrivacy",
    "largeText": "",
    "mediumText": "",
    "smallText": "",
}

# This is someone else's production server, and behind it is a telematics unit in a
# car. Poll gently.
DEFAULT_SCAN_INTERVAL: Final = timedelta(minutes=15)
MIN_SCAN_INTERVAL: Final = timedelta(minutes=5)

CONF_PHONE: Final = "phone"
CONF_PERSONAL_ID: Final = "personal_id"
CONF_ACCESS_TOKEN: Final = "access_token"
CONF_TELEMATICS: Final = "telematics"
CONF_CAR_UUIDS: Final = "car_uuids"
CONF_SCAN_INTERVAL_MINUTES: Final = "scan_interval_minutes"

# API error codes. Errors arrive as HTTP 200 with a non-zero errorCode.
ERR_OK: Final = 0
ERR_VALIDATION: Final = 10001
ERR_NO_TERMS_CONSENT: Final = 20004
ERR_ITURAN_GENERIC: Final = 11111
ERR_NO_PHONE_ID_MATCH: Final = 91133
ERR_ITURAN_NOT_REGISTERED: Final = 92001
ERR_ITURAN_NO_PLATE_LINK: Final = 95555

# Values the app colours its battery gauge with, from settings/all.
BATTERY_LOW: Final = 15
BATTERY_MEDIUM: Final = 49

IGNITION_ELECTRIC: Final = "Electric"
IGNITION_PLUGIN: Final = "PlugIn"
IGNITION_HYBRID: Final = "Hybrid"
IGNITION_GASOLINE: Final = "Gasoline"

# Ignition types that have a traction battery worth reporting.
IGNITION_WITH_BATTERY: Final = frozenset({IGNITION_ELECTRIC, IGNITION_PLUGIN})
