#!/usr/bin/env python3
"""Register this client with the Ituran telematics service and read vehicle data.

`ituran/getLocation` and `ituran/getBatteryInfo` are keyed on a per-car client
UUID. The phone app generates that UUID itself (UUID.randomUUID) and registers it
with `ituran/activate` + an SMS code, then stores it under `cars_uuid`. Without a
registered UUID the server answers 92001, "re-identify to the vehicle location
service" - which is exactly what probe.py hit.

This script performs that registration once, using its own generated UUID, and
then retries the data calls with it.

It reuses the access token from probe-raw.json, so it does not need a second
login SMS. Ituran will send its own SMS for the activation step.

Usage:  python tools/ituran_activate.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid as uuidlib
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
RAW_PATH = HERE / "probe-raw.json"
OUT_PATH = HERE / "ituran-raw.json"
RED_PATH = HERE / "ituran-redacted.json"
STATE_PATH = HERE / "ituran-state.json"

spec = importlib.util.spec_from_file_location("probe", HERE / "probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def load_session() -> tuple[str, str, list[dict[str, Any]]]:
    if not RAW_PATH.exists():
        sys.exit(f"{RAW_PATH} not found - run 'python tools/probe.py' first.")
    data = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    user_info: dict[str, Any] = {}
    for key, entry in data.items():
        if key.startswith("verifyUser[") and entry.get("status") == 200:
            user_info = ((entry.get("response") or {}).get("body") or {}).get("userInfo") or {}
            if user_info:
                break
    if not user_info:
        info = (data.get("getUserInfo") or {}).get("response") or {}
        user_info = info.get("body") or {}
    token = user_info.get("accessToken")
    if not token:
        sys.exit("no accessToken in probe-raw.json - re-run probe.py")
    phone = user_info.get("mobilePhone") or ""
    cars = [c for c in (user_info.get("carsInfo") or []) if c.get("hasIturan")]
    return token, phone, cars


def main() -> int:
    token, phone, cars = load_session()
    probe.SECRETS.extend(x for x in (token, phone) if x)

    if not cars:
        sys.exit("no car on this account has hasIturan=true")

    print("Ituran activation")
    print("=" * 62)
    for i, car in enumerate(cars):
        print(f"  [{i}] {car.get('modelInHebrew')}  ({car.get('ignitionType')}, "
              f"EV telematics: {car.get('hasIturanEv')})")
    pick = 0 if len(cars) == 1 else int(input("\nWhich car? ").strip() or 0)
    car = cars[pick]
    plate = car["licensePlate"]

    state = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {}
    client_uuid = state.get(plate) or str(uuidlib.uuid4())
    reused = plate in state
    print(f"\nclient UUID: {client_uuid}{'  (reused)' if reused else '  (new)'}")

    results: dict[str, Any] = {"_meta": {"plate_len": len(plate), "uuid": client_uuid}}

    def record(name: str, path: str, body: Any, method: str = "POST") -> Any:
        if method == "GET":
            status, payload = probe.call(path, None, token, "GET", params=body)
        else:
            status, payload = probe.call(path, body, token, "POST")
        results[name] = {"path": path, "method": method, "status": status,
                         "request_keys": sorted(body), "response": payload}
        code = (payload or {}).get("errorCode")
        msg = (payload or {}).get("errorMessage")
        print(f"  {name:18} {method:4} {path:26} HTTP {status} code={code}")
        if msg:
            print(f"        -> {msg}")
        return (payload or {}).get("body"), code

    try:
        if not reused:
            print("\n[1/3] activating ...")
            body, code = record("activate", "ituran/activate",
                                {"phoneNumber": phone, "plate": plate, "key": client_uuid})
            if isinstance(body, dict):
                print(f"        didRecognizeOwner = {body.get('didRecognizeOwner')}")

            otp = input("\nEnter the Ituran SMS code (blank to skip verify): ").strip()
            if otp:
                print("\n[2/3] verifying ...")
                record("verify", "ituran/verify",
                       {"phoneNumber": phone, "plate": plate, "otpCode": otp})
            else:
                print("\n[2/3] skipped")

        # getLocation has to come first: its response carries the Ituran service
        # userName, and that - not the phone number - is what the other Ituran
        # calls expect as `username`. The app builds its IturanCarUdid the same way.
        print("\n[3/3] reading vehicle data with the registered UUID ...")
        loc, loc_code = record("location", "ituran/getLocation",
                               {"plate": plate, "uuid": client_uuid,
                                "version": probe.APP_VERSION,
                                "userLatitude": None, "userLongitude": None})

        user_name = (loc or {}).get("userName") if isinstance(loc, dict) else None
        if isinstance(loc, dict):
            print(f"        fields returned: {', '.join(sorted(loc))}")
            print(f"        milage={loc.get('milage')}  city={loc.get('city')!r}  "
                  f"head={loc.get('head')}  has_coords={loc.get('lat') is not None}")
        if user_name:
            probe.SECRETS.append(user_name)
            print(f"        Ituran userName recovered ({len(user_name)} chars)")
        else:
            print("        no userName in the response - the calls below will likely fail")

        if car.get("hasIturanEv"):
            bat, _ = record("battery", "ituran/getBatteryInfo",
                            {"licensePlate": plate, "uuid": client_uuid,
                             "username": user_name or phone, "platformId": "Android"})
            if isinstance(bat, dict):
                print(f"        fields returned: {', '.join(sorted(bat))}")
                print(f"        battery={bat.get('batteryPercentage')}%  "
                      f"charging={bat.get('isCharging')}  "
                      f"range={bat.get('rangeLeftOnBatteryPower')}  "
                      f"minsToFull={bat.get('chargingMinutesLeftTillFullBattery')}")

        if car.get("hasIturanSafety"):
            rep, _ = record("drivingReport", "ituran/drivingReport",
                            {"plateNumber": plate, "uuid": client_uuid,
                             "username": user_name or phone, "reportPeriod": "Month"})
            if isinstance(rep, dict):
                print(f"        fields returned: {', '.join(sorted(rep))}")

        record("carExtraInfo", "car/carExtraInfo", {"plateNumber": plate}, method="GET")

        if loc_code == 0:
            state[plate] = client_uuid
            STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
            print(f"\n  UUID registered and saved to {STATE_PATH.name}")

    except KeyboardInterrupt:
        print("\naborted")
        return 130
    finally:
        OUT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        RED_PATH.write_text(json.dumps(probe.redact(results), ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"\n  raw      -> {OUT_PATH}   (keep private)")
        print(f"  redacted -> {RED_PATH}   (safe to share)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
