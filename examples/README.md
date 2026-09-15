# Example automations

Working automations built on this integration, with personal identifiers removed.
Copy one into Settings → Automations → ⋮ → Edit in YAML, then replace the
placeholders:

| Placeholder | Replace with |
| --- | --- |
| `sensor.my_car_*`, `binary_sensor.my_car_*`, `device_tracker.my_car_*` | your car's entities |
| `notify.mobile_app_my_phone` | your phone's notify service |
| `/lovelace/car` | wherever tapping the notification should go |

`charging-notification.yaml` also expects an `input_number.car_charge_target`
helper (Settings → Devices & Services → Helpers → Number) holding the percentage
you normally charge to. Replace it with a plain number like `below: 80` if you
would rather not create one.

They assume live vehicle data is on. Without it, the battery and charging entities
do not exist and only the odometer-based parts apply.

## What is here

| File | What it does |
| --- | --- |
| [charging-notification.yaml](charging-notification.yaml) | One quiet notification with a progress bar while charging, replaced by a summary when it ends |
| [low-battery-alert.yaml](low-battery-alert.yaml) | Alerts on the car's own low-battery flag, or when range drops below a threshold |
| [plug-in-reminder.yaml](plug-in-reminder.yaml) | Reminds you to plug in when the car is home, unplugged and low |

## Two things worth knowing

**Do not push `homeassistant.update_entity` in a loop.** It forces a full refresh —
about five requests to Toyota's servers each time. The integration already switches
to a faster interval on its own while charging (Configure → update interval while
charging), so let it, and read the cached state. A one-minute loop pushing refreshes
is roughly 300 requests an hour against someone else's production API.

**Hebrew and numbers need care on Android.** Two numbers separated only by
punctuation get merged into one left-to-right run and come out reversed —
`82% · 310` can render as `310 · 82%`. Putting a Hebrew word immediately before
each number keeps them apart. The examples are in English, where this does not
arise, but it bites as soon as the text is translated.
