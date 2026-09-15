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
needs no authentication.

---

## Authentication

Login is phone number + Israeli ID + one-time SMS code. There is no password.

**1. Request the code** — `account/generateVerificationCodeV2`

```json
{ "mobilePhone": "05XXXXXXXX", "personalId": "XXXXXXXXX",
  "isRegister": false, "consents": [] }
```

Returns `{ consentsToken, totalTimeoutInSeconds, needsPersonalInfoReview }`.

**2. Exchange the code for a token** — `account/verifyUserV2`

```json
{ "mobilePhone": "...", "personalId": "...", "verificationCode": "1234",
  "isRegister": false, "consentsToken": "...", "licensePlate": null,
  "facebookAccessToken": null, "appleIdentityToken": null }
```

Returns `{ userInfo, verificationToken, verifiedMobilePhone, needsPersonalInfoReview }`.

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

## Endpoints used by this integration

### `homepage/get`

The most valuable call: one request returns every car **with battery data already
attached**, so the common case needs no separate Ituran round-trip.

```
HomePageResponse
  homePageCarItems: HomePageCarItem[]
      car            : Car
      batteryInfo    : BatteryInfoResponseBody   <-- inline
      nextAppointment: { haveAppointment, licensePlate, appointmentInfo }
      messages       : []
  orderItems: OrderItem[]      (new-car orders — not used here)
```

### `ituran/getBatteryInfo`

Request `{ uuid, licensePlate, username, platformId }` — `uuid` and `username`
come from an `IturanCarUdid { carNo, userName, uuid }` the app holds per car.

| Response field | Type | Maps to |
| --- | --- | --- |
| `batteryPercentage` | int | battery % sensor |
| `isCharging` | bool | charging binary sensor |
| `rangeLeftOnBatteryPower` | int? | remaining range sensor |
| `chargingMinutesLeftTillFullBattery` | int? | time-to-full sensor |
| `maxChargingCurrentAC` / `maxChargingCurrentDC` | int? | diagnostic |

### `ituran/getLocation`

Request `{ uuid, plate, version, userLatitude, userLongitude }`.

| Response field | Type | Maps to |
| --- | --- | --- |
| `lat`, `lon` | double | `device_tracker` |
| `address`, `city` | string | tracker attributes |
| `milage` | int? | odometer (spelled `milage` upstream) |
| `head` | int? | heading |
| `distanceInMeters` | double? | distance from the phone's position |

### `car/carExtraInfo` → `CarExtraInfo`

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
