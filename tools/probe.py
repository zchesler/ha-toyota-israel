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
import urllib.parse
import urllib.request
import uuid as uuidlib
from pathlib import Path
from typing import Any

BASE = "https://my-toyota.toyota.co.il/api/"
APP_VERSION = "2.2.41"

# SHA-256 of the app's X.509 signing certificate, lowercase hex. The app computes
# this at runtime and sends it as X-App-Signature; it is the same for every install.
APP_SIGNATURE = "efa3a9bbf63b1a7f47895e5924482b004f66c4baf6a2b2665a792631c61f8d5f"

# The server requires the terms-of-use consent to issue a code. Marketing consent
# ("MarketingMessages") is deliberately not sent - logging in should not opt anyone
# into marketing. The texts are echoed back empty, exactly as the app does.
TERMS_CONSENT = {
    "consentType": "TermsAndPrivacy",
    "largeText": "",
    "mediumText": "",
    "smallText": "",
}

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
         method: str = "POST", params: dict[str, Any] | None = None) -> tuple[int, Any]:
    """Call `path` and return (status, parsed JSON)."""
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if (body is not None and method == "POST") else None
    req = urllib.request.Request(url, data=data, headers=headers(token), method=method)
    try:
        with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()) as r:
            raw, status = r.read().decode("utf-8", "replace"), r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read().decode("utf-8", "replace"), e.code
    except urllib.error.URLError as e:
        raise ApiError(f"network error calling {path}: {e.reason}") from e
    try:
        return status, (json.loads(raw) if raw else None)
    except json.JSONDecodeError:
        return status, {"_unparsed": raw[:2000]}


def unwrap(path: str, status: int, payload: Any) -> Any:
    """Unwrap the {custom, errorCode, errorMessage, body} envelope."""
    if status == 401:
        raise ApiError(f"{path}: HTTP 401 - token rejected")
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
    print("=" * 62)
    print("Your phone number and ID go only to my-toyota.toyota.co.il.\n")

    phone = input("Mobile phone (e.g. 0501234567): ").strip()
    personal_id = getpass.getpass("Israeli ID (teudat zehut, hidden): ").strip()
    SECRETS.extend(x for x in (phone, personal_id) if x)

    results: dict[str, Any] = {"_meta": {"base": BASE, "appVersion": APP_VERSION}}

    def record(name: str, path: str, *, body: Any = None, token: str | None = None,
               method: str = "POST", params: dict[str, Any] | None = None) -> Any:
        status, payload = call(path, body, token, method, params)
        results[name] = {"path": path, "method": method, "status": status,
                         "response": payload}
        print(f"  {name:24} {method:4} {path:26} HTTP {status}")
        return unwrap(path, status, payload)

    try:
        print("\n[1/5] requesting SMS code ...")
        otp = record("generateVerificationCode", "account/generateVerificationCodeV2",
                     body={"phoneNumber": phone, "personalId": personal_id,
                           "consents": [TERMS_CONSENT]})
        consents_token = otp.get("consentsToken") if isinstance(otp, dict) else None
        if isinstance(otp, dict) and otp.get("totalTimeoutInSeconds"):
            print(f"        code valid for {otp['totalTimeoutInSeconds']}s")

        code = input("\nEnter the SMS code you received: ").strip()

        # verifyUserV2 could not be shape-checked with dummy data (it 500s when no OTP
        # session exists), so try the plausible spellings until one is accepted. The
        # code stays valid for the whole window, so retries cost nothing.
        print("\n[2/5] verifying ...")
        candidates = [
            ("phoneNumber+consentsToken",
             {"phoneNumber": phone, "personalId": personal_id,
              "verificationCode": code, "consentsToken": consents_token}),
            ("phoneNumber+consents",
             {"phoneNumber": phone, "personalId": personal_id,
              "verificationCode": code, "consentsToken": consents_token,
              "consents": [TERMS_CONSENT]}),
            ("mobilePhone spelling",
             {"mobilePhone": phone, "personalId": personal_id,
              "verificationCode": code, "consentsToken": consents_token}),
            ("code spelling",
             {"phoneNumber": phone, "personalId": personal_id,
              "code": code, "consentsToken": consents_token}),
        ]
        verified = None
        for label, body in candidates:
            status, payload = call("account/verifyUserV2", body, method="POST")
            err = (payload or {}).get("errorCode") if isinstance(payload, dict) else None
            msg = (payload or {}).get("errorMessage") if isinstance(payload, dict) else None
            results[f"verifyUser[{label}]"] = {"path": "account/verifyUserV2",
                                               "status": status, "response": payload}
            print(f"  verifyUserV2 ({label:24}) HTTP {status} code={err}")
            if status == 200 and not err:
                verified = (payload or {}).get("body")
                print(f"        accepted with: {label}")
                results["_verifyShape"] = sorted(body)
                break
            if msg:
                print(f"        -> {msg}")
        if verified is None:
            raise ApiError("verifyUserV2 rejected every request shape - see probe-raw.json")

        user_info = verified.get("userInfo") or {}
        token = user_info.get("accessToken")
        if not token:
            raise ApiError("no accessToken in verifyUserV2 response - see probe-raw.json")
        SECRETS.append(token)
        print(f"        got accessToken ({len(token)} chars)")

        print("\n[3/5] account + homepage ...")
        record("getUserInfo", "account/getUserInfo", token=token, method="GET")
        home = record("homepage", "homepage/get", token=token, method="GET")

        cars: list[dict[str, Any]] = []
        if isinstance(home, dict):
            for item in home.get("homePageCarItems") or []:
                car = (item or {}).get("car") or {}
                if car.get("licensePlate"):
                    cars.append(car)
                    if item.get("batteryInfo") is not None:
                        print("        homepage/get carries batteryInfo inline")
        for car in user_info.get("carsInfo") or []:
            if car.get("licensePlate") and not any(
                    c["licensePlate"] == car["licensePlate"] for c in cars):
                cars.append(car)

        print(f"\n[4/5] found {len(cars)} car(s)")
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
            print(f"\n[5/5] telematics for {car.get('modelInHebrew')} ...")
            probes: list[tuple[str, str, dict[str, Any]]] = [
                (f"{tag}_carExtraInfo", "car/carExtraInfo", {"licensePlate": plate}),
                (f"{tag}_location", "ituran/getLocation",
                 {"plate": plate, "uuid": "", "version": APP_VERSION,
                  "userLatitude": None, "userLongitude": None}),
            ]
            if car.get("hasIturanEv"):
                probes.append((f"{tag}_battery", "ituran/getBatteryInfo",
                               {"licensePlate": plate, "uuid": "", "username": "",
                                "platformId": "Android"}))
            for name, path, payload in probes:
                try:
                    if path.startswith("car/"):
                        record(name, path, token=token, method="GET", params=payload)
                    else:
                        record(name, path, body=payload, token=token, method="POST")
                except ApiError as e:
                    print(f"        {path} failed: {e}")

        print("\n  done")

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
