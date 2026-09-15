# Toyota Israel for Home Assistant

Home Assistant integration for cars connected to **MyTOYOTA Israel**, the app run by
Union Motors (יוניון מוטורס), the Toyota importer in Israel.

Israel does not use Toyota Motor Europe's connected-services platform, so the
existing [`ha_toyota`](https://github.com/pytoyoda/ha_toyota) / `pytoyoda`
integrations cannot talk to it. This one speaks the Israeli backend directly.
The API it uses is written up in [docs/API.md](docs/API.md).

## Entities

Created per car, and only where that car actually reports the data.

| Entity | Needs telematics |
| --- | --- |
| Battery level, Charging, Battery low | ✅ EV |
| Range remaining, Charging time left, Charging power | ✅ EV |
| Location (`device_tracker`) and location address | ✅ |
| Safety score, Distance this month | ✅ |
| **Odometer** | — |
| First registered, Service interval, Insurance reminder, Service booked | — |
| Battery capacity, Rated range, Max AC/DC charging power | — |
| Recommended tyre pressures | — |

Rows marked "—" come from the account itself and work on any car, including hybrids
and petrol models.

A sensor reads `unknown` when the server answered without a value for it, and
`unavailable` only when the source could not be read at all. Range, for instance,
goes `unknown` while the car is charging — the API stops reporting it until the
charge ends.

## Requirements

- A MyTOYOTA Israel account — phone number and Israeli ID.
- For live vehicle data: **Toyota Connect** active on the car. The app reports this
  as `hasIturan`; battery entities also need `hasIturanEv`.
- Home Assistant 2024.12 or newer.

## Installation

**HACS** → Integrations → ⋮ → Custom repositories → add
`https://github.com/zchesler/ha-toyota-israel` as an *Integration*, then install
**Toyota Israel** and restart Home Assistant.

Or copy `custom_components/toyota_israel/` into your `config/custom_components/`
and restart.

Then: Settings → Devices & Services → Add Integration → **Toyota Israel**.

## Signing in

Setup mirrors the app: enter your phone number and Israeli ID, and Toyota sends a
one-time SMS code. The code is only valid for about a minute.

The token that comes back does not auto-refresh — the app never refreshes it
either — so if it is ever rejected, Home Assistant will prompt you to sign in again.

## The telematics trade-off, before you enable it

Battery, charging and location are not served by Toyota. They come from the
**Ituran** (איתוראן) unit in the car, and reading them means registering Home
Assistant with Ituran using a *second* SMS code, once per car.

**Only one device can hold that registration at a time.** Registering here signs
the MyTOYOTA app out of live vehicle data, and signing back in on the app takes
the registration away from Home Assistant. There is no way around this; it is how
Ituran pairs a client to a car.

So pick one:

- **With telematics** — full battery, charging and location in Home Assistant, and
  the phone app stops showing live vehicle data until you sign in there again.
- **Without telematics** — the app keeps working, and Home Assistant still gets the
  odometer, servicing dates and vehicle specs, which need no registration.

The choice is a step during setup, and **Reconfigure** on the integration switches
between them later. If the app takes the registration back, the telematics entities
go unavailable, a warning appears in the log, and Reconfigure claims it again.

## Polling

The default is every 15 minutes, adjustable down to 5 in the integration's options.
Every request wakes a telematics unit in a car and goes to someone else's
production server, so prefer longer intervals unless you need the detail.

**While a car is charging, a second, shorter interval applies** — 5 minutes by
default, adjustable down to 2. At 15 minutes a charge that starts just after a
poll goes unreported for a quarter of an hour, which is most of the time you
actually wanted to watch. The faster rate stops as soon as charging does, so it
stays bounded.

## Development

`tools/probe.py` runs the real login and records what every endpoint returns, and
`tools/ituran_activate.py` does the Ituran registration and reads vehicle data. Both
write a full copy and a redacted copy; the full one is git-ignored.

```bash
python tools/probe.py
python tools/ituran_activate.py
```

Your details go only to `my-toyota.toyota.co.il`, exactly as the app sends them.

## Disclaimer

Unofficial, and not affiliated with, endorsed by, or supported by Toyota, Union
Motors, or Ituran. It relies on a private API that can change or break without
notice. Use it with your own account only.

## License

MIT
