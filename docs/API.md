# MyTOYOTA Israel — API reference

Written for: developers working on this integration.

Union Motors (יוניון מוטורס), the Toyota importer in Israel, runs its own backend —
it is **not** Toyota Motor Europe's `ctpa-oneapi` platform. `pytoyoda` / `ha_toyota`
do not work against it, which is why this integration exists.

Everything below was recovered from the public Android app
(`com.toyota.mobile`, version 2.2.41, build 514) by reading its DEX string pool,
field tables, and bytecode. No traffic interception was involved.

Telematics (location, odometer, EV battery, driving events) are supplied by
**Ituran** (איתוראן) and surfaced through Toyota's own backend, which is why the
EV endpoints live under an `ituran/` prefix.

---

## Transport

Base URL: `https://my-toyota.toyota.co.il/api/`

Other environments referenced by the app (not used here): `test-my-toyota`,
`test-hf-my-toyota`, and `share-app.toyota.co.il/api/v3/` (Toyota Share rentals).

### Headers

The app attaches these to every request, from a single OkHttp interceptor:

| Header | Value |
| --- | --- |
| `Authorization` | `Bearer <accessToken>` — omitted while logged out |
| `AppVersion` | app `versionName`, e.g. `2.2.41` |
| `DeviceId` | `Settings.Secure.ANDROID_ID` |
| `DeviceOS` | `Android` |
| `DeviceOSVersion` | `Build.VERSION.RELEASE` |
| `DeviceModel` | `Build.MODEL` |
| `Platform` | `Application` (literal) |
| `X-App-Signature` | see below |
| `FbAccessToken` | Facebook token, only when signed in via Facebook |

`X-App-Signature` is the lowercase hex SHA-256 of the app's X.509 signing
certificate (`MessageDigest("SHA-256").digest(cert.getEncoded())`, joined with
`%02x`). It is a constant, identical for every install:

```
efa3a9bbf63b1a7f47895e5924482b004f66c4baf6a2b2665a792631c61f8d5f
```

Recomputable from any official APK — see `tools/` for the extractor used.

### Response envelope

Every endpoint returns the same wrapper; the payload is under `body`:

```json
{ "custom": null, "errorCode": 0, "errorMessage": null, "body": { } }
```

`errorCode` is `0` on success. Confirmed live against `GET settings/all`, which
needs no authentication and is a useful place to check connectivity.

`settings/all` also carries server-side config worth reading, including the
battery thresholds the app colours its gauge with — `BatteryMaxRangeOrange` (49)
and `BatteryMaxRangeRed` (15) — and `Application.UpdateForceMinVersionAndroid`,
which is the minimum app build the server will serve (514 at time of writing,
matching `AppVersion: 2.2.41`).

---

## Authentication

Login is phone number + Israeli ID + one-time SMS code. There is no password.

**1. Request the code** — `POST account/generateVerificationCodeV2`

```json
{ "phoneNumber": "05XXXXXXXX",
  "personalId": "XXXXXXXXX",
  "consents": [ { "consentType": "TermsAndPrivacy",
                  "largeText": "", "mediumText": "", "smallText": "" } ] }
```

Returns `{ consentsToken, totalTimeoutInSeconds, needsPersonalInfoReview }`.

Note the JSON keys do **not** match the app's Kotlin field names — the DTO calls
it `mobilePhone` and misspells `smallTex`, but the wire format is `phoneNumber`
and `smallText`. These were confirmed against the live server, which names the
missing property in its validation errors. Field names here are authoritative;
the Kotlin ones are not.

`consents` must contain the terms entry or the server refuses with `20004`. The
app also offers a `MarketingMessages` consent; this integration does not send it,
since signing in should not opt anyone into marketing.

**2. Exchange the code for a token** — `POST account/verifyUserV2`

```json
{ "mobilePhone": "...", "personalId": "...", "verificationCode": "1234",
  "consentsToken": "..." }
```

Note the inconsistency, confirmed against the live server: step 1 wants
`phoneNumber`, step 2 wants `mobilePhone`. Sending `phoneNumber` here returns a
500. `consentsToken` is the ~370-character token from step 1. The code is valid
for `totalTimeoutInSeconds`, 60 seconds in practice.

Returns `{ userInfo, verificationToken, verifiedMobilePhone, needsPersonalInfoReview }`.

`userInfo.carsInfo[]` arrives with the response, so a single login already yields
the car list.

`userInfo.accessToken` is the long-lived bearer token. The app stores it in
SharedPreferences under `userAccessToken` and never refreshes it — a new SMS
login is the only renewal path, so the integration needs a re-auth flow.

`account/logout` invalidates it.

---

## Entities

### `UserInfo` — from `account/getUserInfo` and `verifyUserV2`

`accessToken`, `id`, `identifier`, `personalId`, `customerNumber`, `firstName`,
`lastName`, `mobilePhone`, `email`, `birthday`, `age`, `gender`, `city`,
`street`, `houseNumber`, `imageUrl`, `dateCreated`, `subscriberKey`,
`hasCreditCard`, `hasShareAccount`, `hasHiddenCars`,
`isAccountDeletionRequested`, `lastDateRentedShare`, `carsInfo: Car[]`

### `Car`

| Field | Type | Notes |
| --- | --- | --- |
| `licensePlate` | string | primary key for every per-car call |
| `lastSpeedometer` | int? | odometer in km; `null` when unknown |
| `modelInHebrew` | string | e.g. `טויוטה bZ4X` |
| `imageUrl` | string | model render |
| `ignitionType` | enum | `Electric` \| `Gasoline` \| `Hybrid` \| `PlugIn` |
| `hasIturan` | bool | telematics active — gates location/odometer |
| `hasIturanEv` | bool | EV telematics active — gates battery data |
| `hasIturanSafety` | bool | driving-events data available |
| `evRange` | string? | nominal range |
| `finishType`, `roleType`, `videoGuide`, `defaultAgency` | | `roleType` is `MainDriver` etc. |

---

## HTTP verbs and error codes

Verbs are not guessable from the path and were confirmed against the live server
(`405` means the verb is wrong; `401` means the verb is right and auth is missing):

| Endpoint | Verb |
| --- | --- |
| `account/generateVerificationCodeV2`, `account/verifyUserV2` | POST |
| `account/getUserInfo`, `homepage/get`, `car/carExtraInfo` | **GET** |
| `ituran/getBatteryInfo`, `ituran/getLocation` | POST |
| `settings/all` | GET, no auth |

Errors arrive as HTTP 200 with a non-zero `errorCode`; only auth failures use a
real HTTP status.

| Code | Meaning |
| --- | --- |
| `0` | success |
| `10001` | model validation — `errorMessage` names the missing fields, `\|`-separated |
| `20004` | terms consent missing from the request |
| `91133` | no account links that phone number and ID |
| `92001` | Ituran client UUID not registered — run the activation flow |
| `11111` | generic Ituran failure, seen when the UUID is missing or invalid |
| `500` | server-side failure |
| HTTP `401` | token missing, expired, or rejected |

`10001` is worth knowing: the server lists every missing property by name, which
makes it a reliable oracle for request shapes without needing a valid account.

---

## Endpoints used by this integration

### `GET homepage/get`

```
HomePageResponse
  homePageCarItems: HomePageCarItem[]
      car            : Car
      nextAppointment: { haveAppointment, licensePlate, appointmentInfo }
      wwytBanner     : trade-in valuation banner, or null
  orderItems: OrderItem[] | null      (new-car orders — not used here)
```

The app's `HomePageCarItem` class declares a `batteryInfo` field of type
`BatteryInfoResponseBody`, but **the live server does not populate it** — the key
is absent from the response entirely. Battery data has to come from
`ituran/getBatteryInfo`. Treat the APK's data classes as a superset of what the
server actually sends.

`car.lastSpeedometer` is likewise `null` in practice. The only odometer reading
observed on this endpoint arrives in `wwytBanner.vehicleKm` (alongside
`vehicleYear` and `vehicleModel`), and only for cars the trade-in offer applies
to. A reliable odometer comes from `ituran/getLocation`'s `milage`.

`Car` also carries `modelCode` and `modelFamily` (e.g. `X35CAC` / `X3`) on this
endpoint, though both are `null` in `account/getUserInfo`.

### `POST ituran/getBatteryInfo`

Request `{ uuid, licensePlate, username, platformId }`, where `uuid` is the
registered client UUID (see *Ituran activation* below).

| Response field | Type | Maps to |
| --- | --- | --- |
| `batteryPercentage` | int | battery % sensor |
| `isCharging` | bool | charging binary sensor |
| `rangeLeftOnBatteryPower` | int? | remaining range sensor |
| `chargingMinutesLeftTillFullBattery` | int? | time-to-full sensor |
| `maxChargingCurrentAC` / `maxChargingCurrentDC` | int? | diagnostic |

**The response is not the same shape while charging.** Observed on a C-HR+ on a
home AC charger:

| Field | Parked | Charging |
| --- | --- | --- |
| `isCharging` | false | true |
| `batteryPercentage` | 92 | 87 |
| `chargingMinutesLeftTillFullBattery` | null | 90 |
| `rangeLeftOnBatteryPower` | 382 | **null** |
| `maxChargingCurrentAC` / `DC` | 22 / 150 | **null** |
| `isChargingAC` | false | **false** |
| `chargingCurrent` | null | null |

So only four fields are meaningful during a charge, and three that work while
parked stop reporting. `isChargingAC` stayed false throughout an AC charge and
`chargingCurrent` has never been non-null, so treat both as not implemented
rather than as data — the integration does not expose `isChargingAC` at all.

Static equivalents of the charging rates live in `car/carExtraInfo`
(`evMaxPowerForAc`, `evMaxPowerForDc`), which keep their values while charging
and are the better source.

### Ituran activation

The Ituran data calls are keyed on a per-car client UUID. Without a registered
one the server answers `92001`, *"re-identify to the vehicle location service"*.

The UUID is **generated by the client**, not issued by the server —
`MyCarIntroActivity` calls `UUID.randomUUID().toString()` and registers it:

1. `POST ituran/activate` — `{ phoneNumber, plate, key }`, where `key` is the
   freshly generated UUID. Returns `{ plate, didRecognizeOwner }` and triggers an
   SMS from Ituran (separate from the login SMS).
2. `POST ituran/verify` — `{ phoneNumber, plate, otpCode }`. Returns
   `{ returnError, serviceNum }`.

From then on that `key` is passed as `uuid` on every Ituran call. The app persists
the set in SharedPreferences under `cars_uuid`, as a JSON list of
`IturanCarUdid { carNo, userName, uuid }`; `userName` comes back from
`getLocation`'s response rather than being known up front.

Whether the server keeps more than one registered UUID per (phone, plate) is
not yet established — if it does not, activating from Home Assistant may
displace the phone app's registration and vice versa. `tools/ituran_activate.py`
performs this flow and stores the UUID it registered.

### `POST ituran/getLocation`

Request `{ uuid, plate, version, userLatitude, userLongitude }`. `version` is the
app version string; `userLatitude`/`userLongitude` are the phone's own position and
only feed the `distanceInMeters` field, so they may be sent as null.

| Response field | Type | Maps to |
| --- | --- | --- |
| `lat`, `lon` | double | `device_tracker` |
| `address`, `city` | string | tracker attributes |
| `milage` | int? | odometer (spelled `milage` upstream) |
| `head` | int? | heading |
| `distanceInMeters` | double? | distance from the phone's position |

### `GET car/carExtraInfo` → `CarExtraInfo`

Takes `plateNumber` as a query parameter — not `licensePlate`, despite the field
being spelled that way everywhere else.

Static-ish specs, good for device info and diagnostics: `mileage`,
`evBatteryCapacity`, `evConnectorTypeAc`, `evConnectorTypeDc`, `evMaxPowerForAc`,
`evMaxPowerForDc`, `evRange`, `engineType`, `fuelType`, `vehiclePower`,
`acceleration`, `frontTirePressure`, `backTirePressure`, `treatmentInterval`,
`upToRoadDate`, `insuranceReminderDate`, plus manual/booklet links.

### Driving and safety

- `ituran/drivingReport` → `{ safetyGrade, totalKM, gradeTimeDescription, safetyEvents }`
  where `safetyEvents` is `{ accelerations, braking, bypasses, speedViolations,
  speedingInSquares, wideTurns }`. Request takes `reportPeriod` of
  `Day` | `Week` | `Month` | `Year`.
- `ituran/dailySafetyRides` → `{ trips: Trip[] }`, each with start/end time and
  address, a coordinate polyline, and its safety events.
- `ituran/monthlySafetyEvents` → `{ days: Day[] }`, each `{ date, hasTrip, color }`
  with `color` in `Green` | `Yellow` | `Red`.

### Appointments

`order/nextAppointment`, `order/appointments`, `order/history`, `order/monthSlots`,
`order/cancelAppointment`.

---

## Full endpoint inventory

Recovered from the app; listed for completeness. This integration is read-only
and touches only the ones documented above.

```
account/   generateVerificationCodeV2  verifyUserV2  getUserInfo  updateUserInfo
           registerCustomer  logout  addCarToUser  deleteUserCar  driversList
           addSecondaryUserV2  deleteSecondaryUser  deleteUserInfo
           defaultAgency  updateLastSeen
ituran/    verify  activate  getLocation  getBatteryInfo  drivingReport
           dailySafetyRides  monthlySafetyEvents
car/       carExtraInfo  addInsuranceReminder
homepage/  get
onStart/   getSettings
settings/  all                     (public, no auth)
order/     appointments  nextAppointment  cancelAppointment  monthSlots
           history  historyEmailExport
chargingStations/v2/  getFilteredStations  getFiltersMetaData
indicatorsLights/     getAll  getById
locations/            allCities  searchCity
servicecenters/all    recall/recall    content/getVideos
userDocuments/ ...    payment/ ...     rental/ ...     carOrder/ ...
alternativeRegister/ ...               au10tix/ ...
```

`payment/`, `rental/`, `carOrder/`, `au10tix/` and `userDocuments/` cover
purchases, car sharing and ID verification. They are deliberately out of scope.

---

## Notes and open questions

- **Token lifetime is unknown.** The app never refreshes, so treat a `401` or a
  non-zero `errorCode` on a known-good call as "re-authenticate".
- **`IturanCarUdid` provenance is not yet pinned down.** `homepage/get` carrying
  `batteryInfo` inline may make it unnecessary; `tools/probe.py` tests whether the
  Ituran calls work with empty `uuid`/`username`.
- **Poll politely.** This is someone else's production server and the data behind
  it is a mobile telematics unit. The integration defaults to a conservative
  interval and should not be lowered much.
- The API can change without notice. Nothing here is endorsed by Toyota,
  Union Motors, or Ituran.
