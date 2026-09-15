# Toyota Israel for Home Assistant

Home Assistant integration for cars connected to **MyTOYOTA Israel**, the app run by
Union Motors (יוניון מוטורס), the Toyota importer in Israel.

Israel does not use Toyota Motor Europe's connected-services platform, so the
existing [`ha_toyota`](https://github.com/pytoyoda/ha_toyota) / `pytoyoda`
integrations cannot talk to it. This one speaks the Israeli backend directly.

> **Status: in development.** The API has been mapped (see [docs/API.md](docs/API.md))
> and verified reachable, but the integration is being validated against a real
> account before first release. Not yet ready to install.

## What it will expose

For each car on your account, gated by what that car actually reports:

| Entity | Source | Requires |
| --- | --- | --- |
| Battery level (%) | `batteryPercentage` | EV telematics |
| Charging | `isCharging` | EV telematics |
| Range remaining | `rangeLeftOnBatteryPower` | EV telematics |
| Time to full charge | `chargingMinutesLeftTillFullBattery` | EV telematics |
| Odometer | `lastSpeedometer` / `milage` | telematics |
| Car location | `ituran/getLocation` | telematics |
| Driving safety score and events | `ituran/drivingReport` | safety telematics |
| Next service appointment | `order/nextAppointment` | — |

Cars without Toyota Connect still get the data the account itself carries, such as
the odometer reading and the next service appointment.

## Requirements

- A MyTOYOTA Israel account (phone number + Israeli ID).
- For vehicle data: **Toyota Connect** active on the car — the app shows this as
  `hasIturan`. Battery entities additionally need `hasIturanEv`.

## Setup

Login mirrors the app: enter your phone number and ID, receive an SMS code, enter it.
Home Assistant then stores the resulting access token. The token does not
auto-refresh, so the integration will prompt you to sign in again if it stops working.

## Development

`tools/probe.py` runs the real login flow and records what every endpoint returns,
writing a full copy and a redacted copy. It is how this integration's data model is
validated against an actual account:

```bash
python tools/probe.py
```

Your phone number and ID are sent only to `my-toyota.toyota.co.il`, exactly as the
app sends them. `probe-raw.json` holds your real data and is git-ignored;
`probe-redacted.json` masks identifying values and is the one safe to share.

## Disclaimer

Unofficial and not affiliated with, endorsed by, or supported by Toyota,
Union Motors, or Ituran. It relies on a private API that can change or break at any
time. Use it with your own account only.

## License

MIT
