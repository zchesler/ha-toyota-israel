#!/usr/bin/env python3
"""Interactive probe for the MyTOYOTA Israel (Union Motors) API.

Runs the real SMS-OTP login against my-toyota.toyota.co.il, then calls every
endpoint the Home Assistant integration needs and records what comes back.

Nothing is uploaded anywhere: your details go only to Toyota's own server,
exactly as the phone app sends them. Two files are written next to this script:

  probe-raw.json       full responses, including your personal details (git-ignored)
  probe-redacted.json  same shape with identifying values masked - safe to share

Usage:  python tools/probe.py
"""

from __future__ import annotations

import getpass
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
import uuid as uuidlib
from pathlib import Path
from typing import Any

BASE = "https://my-toyota.toyota.co.il/api/"
APP_VERSION = "2.2.41"

# SHA-256 of the app's X.509 signing certificate, lowercase hex. The app computes
# this at runtime and sends it as X-App-Signature; it is the same for every install.
APP_SIGNATURE = "efa3a9bbf63b1a7f47895e5924482b004f66c4baf6a2b2665a792631c61f8d5f"

HERE = Path(__file__).resolve().parent
RAW_PATH = HERE / "probe-raw.json"
RED_PATH = HERE / "probe-redacted.json"

# Values captured during the run that must never reach the redacted file.
SECRETS: list[str] = []


class ApiError(RuntimeError):
    pass


def device_id() -> str:
    """Stable pseudo ANDROID_ID for this machine (16 hex chars)."""
    return f"{uuidlib.getnode():016x}"[:16]


def headers(token: str | None) -> dict[str, str]:
    h = {
        "Content-Type": "application/json; charset=utf-8",
        "AppVersion": APP_VERSION,
        "DeviceId": device_id(),
        "DeviceOS": "Android",
        "DeviceOSVersion": "13",
        "DeviceModel": "Pixel 6",
        "Platform": "Application",
        "X-App-Signature": APP_SIGNATURE,
        "Accept": "application/json",
        "Accept-Language": "he",
        "User-Agent": "okhttp/4.12.0",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def call(path: str, body: Any = None, token: str | None = None,
         method: str | None = None) -> tuple[int, Any]:
    """POST `body` to `path`. Falls back to GET when the server rejects POST."""
    methods = [method] if method else ["POST", "GET"]
    last: tuple[int, Any] = (0, None)
    ctx = ssl.create_default_context()
    for m in methods:
        data = json.dumps(body).encode() if (body is not None and m == "POST") else None
        req = urllib.request.Request(BASE + path, data=data, headers=headers(token), method=m)
        try:
            with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
                raw, status = r.read().decode("utf-8", "replace"), r.status
        except urllib.error.HTTPError as e:
            raw, status = e.read().decode("utf-8", "replace"), e.code
        except urllib.error.URLError as e:
            raise ApiError(f"network error calling {path}: {e.reason}") from e
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = {"_unparsed": raw[:2000]}
        last = (status, parsed)
        if status not in (404, 405):
            break
    return last


def unwrap(path: str, status: int, payload: Any) -> Any:
    """Unwrap the {custom, errorCode, errorMessage, body} envelope."""
    if not isinstance(payload, dict):
        raise ApiError(f"{path}: HTTP {status}, unexpected payload {payload!r}")
    if payload.get("errorCode"):
        raise ApiError(f"{path}: errorCode={payload['errorCode']} "
                       f"errorMessage={payload.get('errorMessage')!r}")
    if status >= 400:
        raise ApiError(f"{path}: HTTP {status} {payload!r}")
    return payload.get("body")


# --------------------------------------------------------------------------- redaction

MASK_KEYS = {
    "accesstoken", "verificationtoken", "consentstoken", "token", "uuid",
    "personalid", "identifier", "mobilephone", "verifiedmobilephone", "phonenumber",
    "email", "firstname", "lastname", "birthday", "street", "housenumber",
    "customernumber", "subscriberkey", "fullname", "address", "username",
    "licenseplate", "plate", "carno", "platenumber", "licensenumber",
}
KEEP_SHAPE = {"lat", "lon", "latitude", "longitude", "userlatitude", "userlongitude"}


def redact(value: Any, key: str = "") -> Any:
    k = key.lower()
    if isinstance(value, dict):
        return {kk: redact(vv, kk) for kk, vv in value.items()}
    if isinstance(value, list):
        return [redact(v, key) for v in value]
    if value is None or isinstance(value, bool):
        return value
    if k in KEEP_SHAPE and isinstance(value, (int, float)):
        # Keep ~1km precision so the field can be confirmed as a real coordinate.
        return round(float(value), 2)
    if k in MASK_KEYS:
        s = str(value)
        return f"<{key}:{len(s)} chars>" if s else ""
    if isinstance(value, str):
        for secret in SECRETS:
            if secret and secret in value:
                return f"<redacted:{len(value)} chars>"
        if re.fullmatch(r"[\d\-+ ]{7,}", value):
            return f"<numeric:{len(value)} chars>"
    return value


# --------------------------------------------------------------------------- flow

def main() -> int:
    print("MyTOYOTA Israel API probe")
    print("=" * 60)
    print("Your phone number and ID go only to my-toyota.toyota.co.il.\n")

    phone = input("Mobile phone (e.g. 0501234567): ").strip()
    personal_id = getpass.getpass("Israeli ID (teudat zehut, hidden): ").strip()
    SECRETS.extend(x for x in (phone, personal_id) if x)

    results: dict[str, Any] = {"_meta": {"base": BASE, "appVersion": APP_VERSION}}

    def record(name: str, path: str, body: Any = None, token: str | None = None) -> Any:
        status, payload = call(path, body, token)
        results[name] = {"path": path, "status": status, "response": payload}
        print(f"  {name:24} {path:34} HTTP {status}")
        return unwrap(path, status, payload)

    try:
        print("\n[1/6] requesting SMS code ...")
        otp = record("generateVerificationCode", "account/generateVerificationCodeV2",
                     {"mobilePhone": phone, "personalId": personal_id,
                      "isRegister": False, "consents": []})
        consents_token = (otp or {}).get("consentsToken") if isinstance(otp, dict) else None
        if isinstance(otp, dict) and otp.get("totalTimeoutInSeconds"):
            print(f"        code valid for {otp['totalTimeoutInSeconds']}s")

        code = input("\nEnter the SMS code you received: ").strip()

        print("\n[2/6] verifying ...")
        verified = record("verifyUser", "account/verifyUserV2",
                          {"mobilePhone": phone, "personalId": personal_id,
                           "verificationCode": code, "isRegister": False,
                           "consentsToken": consents_token})
        if not isinstance(verified, dict):
            raise ApiError(f"verifyUserV2 returned {verified!r}")
        user_info = verified.get("userInfo") or {}
        token = user_info.get("accessToken")
        if not token:
            raise ApiError("no accessToken in verifyUserV2 response - see probe-raw.json")
        SECRETS.append(token)
        print(f"        got accessToken ({len(token)} chars, starts {token[:6]}...)")

        print("\n[3/6] account + homepage ...")
        record("getUserInfo", "account/getUserInfo", {}, token)
        home = record("homepage", "homepage/get", {}, token)

        cars: list[dict[str, Any]] = []
        if isinstance(home, dict):
            for item in home.get("homePageCarItems") or []:
                car = (item or {}).get("car") or {}
                if car.get("licensePlate"):
                    cars.append(car)
        if not cars:
            for car in user_info.get("carsInfo") or []:
                if car.get("licensePlate"):
                    cars.append(car)

        print(f"\n[4/6] found {len(cars)} car(s)")
        for car in cars:
            print(f"        {car.get('modelInHebrew')} | ignition={car.get('ignitionType')} "
                  f"| hasIturan={car.get('hasIturan')} hasIturanEv={car.get('hasIturanEv')} "
                  f"| odometer={car.get('lastSpeedometer')}")

        connected = [c for c in cars if c.get("hasIturan")]
        if not connected:
            print("\n  No car reports hasIturan=true, so there are no telematics calls to make.")

        for idx, car in enumerate(connected):
            plate = car["licensePlate"]
            tag = f"car{idx}"
            print(f"\n[5/6] telematics for {car.get('modelInHebrew')} ...")
            for name, path, body in (
                (f"{tag}_carExtraInfo", "car/carExtraInfo", {"licensePlate": plate}),
                (f"{tag}_location", "ituran/getLocation",
                 {"plate": plate, "uuid": "", "version": APP_VERSION,
                  "userLatitude": None, "userLongitude": None}),
                (f"{tag}_battery", "ituran/getBatteryInfo",
                 {"licensePlate": plate, "uuid": "", "username": "",
                  "platformId": "Android"}),
            ):
                if name.endswith("_battery") and not car.get("hasIturanEv"):
                    continue
                try:
                    record(name, path, body, token)
                except ApiError as e:
                    print(f"        {path} failed: {e}")

        print("\n[6/6] writing results ...")

    except ApiError as e:
        print(f"\n!! {e}")
        results["_error"] = str(e)
    except KeyboardInterrupt:
        print("\naborted")
        return 130
    finally:
        RAW_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        RED_PATH.write_text(json.dumps(redact(results), ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"\n  raw      -> {RAW_PATH}   (keep private)")
        print(f"  redacted -> {RED_PATH}   (safe to share)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
