"""Support for UK train data provided by the Realtime Trains API v2."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
import asyncio
import logging
from typing import Any, cast

import pytz
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.const import CONF_SCAN_INTERVAL, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import Throttle
import homeassistant.util.dt as dt_util

_LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOFFSET = timedelta(minutes=0)
DEFAULT_TIME_WINDOW = 360
TIMEZONE = pytz.timezone("Europe/London")
STRFFORMAT = "%d-%m-%Y %H:%M"

ATTR_JOURNEY_START = "journey_start"
ATTR_JOURNEY_END = "journey_end"
ATTR_NEXT_TRAINS = "next_trains"
ATTR_AGGREGATE = "aggregate_data"

CONF_REFRESH_TOKEN = "refresh_token"
CONF_QUERIES = "queries"
CONF_AUTOADJUSTSCANS = "auto_adjust_scans"
CONF_START = "origin"
CONF_END = "destination"
CONF_JOURNEYDATA = "journey_data_for_next_X_trains"
CONF_SENSORNAME = "sensor_name"
CONF_TIMEOFFSET = "time_offset"
CONF_STOPS_OF_INTEREST = "stops_of_interest"

_QUERY_SCHEME = vol.Schema(
    {
        vol.Optional(CONF_SENSORNAME): cv.string,
        vol.Required(CONF_START): cv.string,
        vol.Required(CONF_END): cv.string,
        vol.Optional(CONF_JOURNEYDATA, default=0): cv.positive_int,
        vol.Optional(CONF_TIMEOFFSET, default=DEFAULT_TIMEOFFSET): vol.All(
            cv.time_period, cv.positive_timedelta
        ),
        vol.Optional(CONF_STOPS_OF_INTEREST): [cv.string],
    }
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_AUTOADJUSTSCANS, default=False): cv.boolean,
        vol.Required(CONF_REFRESH_TOKEN): cv.string,
        vol.Required(CONF_QUERIES): [_QUERY_SCHEME],
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up Realtime Trains sensors from YAML."""
    sensors = {}
    interval = config[CONF_SCAN_INTERVAL]
    client = async_get_clientsession(hass)

    for query in config[CONF_QUERIES]:
        sensor = RealtimeTrainLiveTrainTimeSensor(
            query.get(CONF_SENSORNAME),
            config[CONF_REFRESH_TOKEN],
            query[CONF_START].upper(),
            query[CONF_END].upper(),
            query[CONF_JOURNEYDATA],
            query[CONF_TIMEOFFSET],
            config[CONF_AUTOADJUSTSCANS],
            [stop.upper() for stop in query.get(CONF_STOPS_OF_INTEREST, [])],
            interval,
            client,
        )
        sensors[sensor.name] = sensor

    async_add_entities(sensors.values(), True)


class RealtimeTrainLiveTrainTimeSensor(SensorEntity):
    """Sensor reading the Realtime Trains API v2."""

    API_URL_BASE = "https://data.rtt.io"
    _attr_icon = "mdi:train"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(
        self,
        sensor_name,
        refresh_token,
        journey_start,
        journey_end,
        journey_data_for_next_X_trains,
        timeoffset,
        autoadjustscans,
        stops_of_interest,
        interval,
        client,
    ):
        default_sensor_name = (
            f"Next train from {journey_start} to {journey_end} ({timeoffset})"
            if timeoffset.total_seconds() > 0
            else f"Next train from {journey_start} to {journey_end}"
        )
        self._journey_start = journey_start
        self._journey_end = journey_end
        self._journey_data_for_next_X_trains = journey_data_for_next_X_trains
        self._next_trains = []
        self._aggregate_data = {}
        self._data = {}
        self._refresh_token = refresh_token
        self._access_token: str | None = None
        self._access_token_valid_until: datetime | None = None
        self._token_lock = asyncio.Lock()
        self._service_cache: dict[str, tuple[datetime, dict[str, Any]]] = {}
        self._service_cache_ttl = timedelta(minutes=5)
        self._timeoffset = timeoffset
        self._autoadjustscans = autoadjustscans
        self._stops_of_interest = stops_of_interest
        self._interval = interval
        self._client = client
        self._name = default_sensor_name if sensor_name is None else sensor_name
        self._state = None
        self.async_update = self._async_update

    @property
    def name(self):
        return self._name

    @property
    def native_value(self):
        return self._state

    @property
    def available(self) -> bool:
        return self._data is not None

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    async def _get_access_token(self, force_refresh: bool = False) -> str | None:
        """Return a cached access token, refreshing it shortly before expiry."""
        now = cast(datetime, dt_util.utcnow())
        if (
            not force_refresh
            and self._access_token
            and self._access_token_valid_until
            and now < self._access_token_valid_until - timedelta(seconds=60)
        ):
            return self._access_token

        async with self._token_lock:
            now = cast(datetime, dt_util.utcnow())
            if (
                not force_refresh
                and self._access_token
                and self._access_token_valid_until
                and now < self._access_token_valid_until - timedelta(seconds=60)
            ):
                return self._access_token

            try:
                async with self._client.get(
                    f"{self.API_URL_BASE}/api/get_access_token",
                    headers=self._headers(self._refresh_token),
                ) as response:
                    if response.status != 200:
                        await self._log_api_error(response, "access-token refresh")
                        self._access_token = None
                        self._access_token_valid_until = None
                        return None
                    data = await response.json()
            except Exception:
                _LOGGER.exception("Realtime Trains access-token request failed")
                return None

            token = data.get("token")
            valid_until = data.get("validUntil")
            if not token or not valid_until:
                _LOGGER.error(
                    "Realtime Trains token response lacked token or validUntil: %s",
                    data,
                )
                return None

            try:
                expiry = datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
                if expiry.tzinfo is None:
                    expiry = pytz.UTC.localize(expiry)
                self._access_token_valid_until = expiry.astimezone(pytz.UTC)
            except (TypeError, ValueError):
                _LOGGER.error("Invalid Realtime Trains validUntil value: %s", valid_until)
                return None

            self._access_token = token
            _LOGGER.debug(
                "Realtime Trains access token refreshed; valid until %s",
                self._access_token_valid_until.isoformat(),
            )
            return self._access_token

    async def _api_get(self, path: str, params=None):
        """GET an API resource, refreshing and retrying once on authentication failure."""
        token = await self._get_access_token()
        if token is None:
            return None

        response = await self._client.get(
            f"{self.API_URL_BASE}{path}",
            headers=self._headers(token),
            params=params,
        )
        if response.status not in (401, 403):
            return response

        response.release()
        token = await self._get_access_token(force_refresh=True)
        if token is None:
            return None
        return await self._client.get(
            f"{self.API_URL_BASE}{path}",
            headers=self._headers(token),
            params=params,
        )

    async def _async_update(self):
        """Get departures and selected journey details."""
        await self._getdepartures_api_request()
        self._next_trains = []

        if self._data is None:
            self._state = None
            return

        now = cast(datetime, dt_util.now()).astimezone(TIMEZONE)
        next_departure_estimated: datetime | None = None
        departures = self._data.get("services") or []
        departure_count = 0

        for departure in departures:
            schedule_metadata = departure.get("scheduleMetadata") or {}
            if schedule_metadata.get("inPassengerService") is False:
                continue
            if schedule_metadata.get("modeType") not in (None, "TRAIN"):
                continue

            temporal_data = departure.get("temporalData") or {}
            departure_times = temporal_data.get("departure") or {}
            scheduled = _api_datetime(
                departure_times.get("scheduleAdvertised")
                or departure_times.get("scheduleInternal")
            )
            estimated = _api_datetime(
                departure_times.get("realtimeActual")
                or departure_times.get("realtimeForecast")
                or departure_times.get("scheduleAdvertised")
                or departure_times.get("scheduleInternal")
            )
            if scheduled is None or estimated is None:
                _LOGGER.debug("Skipping service with no usable departure time: %s", departure)
                continue
            if _delta_secs(scheduled, now) < self._timeoffset.total_seconds():
                continue

            next_departure_estimated = (
                estimated
                if next_departure_estimated is None
                else min(next_departure_estimated, estimated)
            )
            departure_count += 1

            origin = _first(departure.get("origin"))
            destination = _first(departure.get("destination"))
            location_metadata = departure.get("locationMetadata") or {}
            platform = location_metadata.get("platform") or {}
            operator = schedule_metadata.get("operator") or {}
            identity = schedule_metadata.get("uniqueIdentity")
            cancelled = bool(departure_times.get("isCancelled"))

            train = {
                "origin_name": _endpoint_name(origin),
                "destination_name": _endpoint_name(destination),
                "service_uid": identity,
                "scheduled": scheduled.strftime(STRFFORMAT),
                "estimated": estimated.strftime(STRFFORMAT),
                "delay": int(_delta_secs(estimated, scheduled) // 60),
                "minutes": int(_delta_secs(estimated, now) // 60),
                "platform": platform.get("forecast") or platform.get("actual") or platform.get("planned"),
                "operator_name": operator.get("name"),
                "status": "Cancelled" if cancelled else "Delayed" if estimated > scheduled else "OK",
            }

            # Preserve the original setting's meaning: enrich only the first X
            # trains, but still expose all departures returned by the query.
            if identity and departure_count <= self._journey_data_for_next_X_trains:
                await self._add_journey_data(train, scheduled, estimated)
            self._next_trains.append(train)

        self._aggregate_data = self._calculate_aggregates()
        self._state = (
            None
            if next_departure_estimated is None
            else int(_delta_secs(next_departure_estimated, now) // 60)
        )

        if self._autoadjustscans:
            self.async_update = (
                Throttle(timedelta(minutes=30))(self._async_update)
                if next_departure_estimated is None
                else self._async_update
            )

    async def _getdepartures_api_request(self):
        params = {
            "code": f"gb-nr:{self._journey_start}",
            "filterTo": f"gb-nr:{self._journey_end}",
            "timeFrom": cast(datetime, dt_util.now()).astimezone(TIMEZONE).isoformat(),
            "timeWindow": DEFAULT_TIME_WINDOW,
        }
        try:
            response = await self._api_get("/rtt/location", params)
            if response is None:
                self._data = None
                return
            async with response:
                if response.status == 200:
                    self._data = await response.json()
                elif response.status == 204:
                    self._data = {"services": []}
                else:
                    self._data = None
                    await self._log_api_error(response, "departure search")
        except Exception:
            self._data = None
            _LOGGER.exception("Realtime Trains departure request failed")

    async def _add_journey_data(self, train, scheduled_departure, estimated_departure):
        """Add destination and selected intermediate-stop data to a train."""
        service_uid = train["service_uid"]
        now_utc = cast(datetime, dt_util.utcnow())
        cached = self._service_cache.get(service_uid)

        if cached and now_utc - cached[0] < self._service_cache_ttl:
            data = cached[1]
        else:
            params = {"uniqueIdentity": service_uid}
            try:
                response = await self._api_get("/rtt/service", params)
                if response is None:
                    return
                async with response:
                    if response.status != 200:
                        await self._log_api_error(response, "service lookup")
                        return
                    data = await response.json()
            except Exception:
                _LOGGER.exception("Realtime Trains service request failed")
                return
            self._service_cache[service_uid] = (now_utc, data)
            self._prune_service_cache(now_utc)

        service = data.get("service", data)
        locations = service.get("locations") or []
        stops_of_interest = []
        stop_count = -1
        found = False

        for stop in locations:
            location = stop.get("location") or {}
            short_codes = location.get("shortCodes") or []
            code = short_codes[0].upper() if short_codes else None
            temporal = stop.get("temporalData") or {}
            display_as = str(temporal.get("displayAs") or "")
            call_type = str(
                temporal.get("realtimeCallType")
                or temporal.get("scheduledCallType")
                or ""
            )
            is_public_call = "ADVERTISED" in call_type or display_as == "CALL"

            if code == self._journey_end and display_as.upper() != "ORIGIN":
                arrival = temporal.get("arrival") or {}
                scheduled_arrival = _api_datetime(
                    arrival.get("scheduleAdvertised")
                    or arrival.get("scheduleInternal")
                )
                estimated_arrival = _api_datetime(
                    arrival.get("realtimeActual")
                    or arrival.get("realtimeForecast")
                    or arrival.get("scheduleAdvertised")
                    or arrival.get("scheduleInternal")
                )
                if scheduled_arrival is None or estimated_arrival is None:
                    _LOGGER.warning(
                        "No usable arrival time for %s on service %s",
                        self._journey_end,
                        service_uid,
                    )
                    return

                cancelled = bool(arrival.get("isCancelled"))
                status = (
                    "Cancelled"
                    if cancelled
                    else "Delayed"
                    if estimated_arrival > scheduled_arrival
                    else "OK"
                )
                train.update(
                    {
                        "stops_of_interest": stops_of_interest,
                        "scheduled_arrival": scheduled_arrival.strftime(STRFFORMAT),
                        "estimate_arrival": estimated_arrival.strftime(STRFFORMAT),
                        "arrival_delay": int(
                            _delta_secs(estimated_arrival, scheduled_arrival) // 60
                        ),
                        "journey_time_mins": int(
                            _delta_secs(estimated_arrival, estimated_departure) // 60
                        ),
                        "stops": stop_count,
                        "status": status,
                    }
                )
                found = True
                break

            if code in self._stops_of_interest and is_public_call:
                arrival = temporal.get("arrival") or {}
                scheduled_stop = _api_datetime(
                    arrival.get("scheduleAdvertised")
                    or arrival.get("scheduleInternal")
                )
                estimated_stop = _api_datetime(
                    arrival.get("realtimeActual")
                    or arrival.get("realtimeForecast")
                    or arrival.get("scheduleAdvertised")
                    or arrival.get("scheduleInternal")
                )
                if scheduled_stop and estimated_stop:
                    stops_of_interest.append(
                        {
                            "stop": code,
                            "name": location.get("description"),
                            "scheduled_stop": scheduled_stop.strftime(STRFFORMAT),
                            "estimate_stop": estimated_stop.strftime(STRFFORMAT),
                            "stop_delay": int(
                                _delta_secs(estimated_stop, scheduled_stop) // 60
                            ),
                            "journey_time_mins": int(
                                _delta_secs(estimated_stop, estimated_departure) // 60
                            ),
                            "stops": stop_count,
                        }
                    )
            stop_count += 1

        if not found:
            _LOGGER.warning(
                "Could not find %s in stops for service %s",
                self._journey_end,
                service_uid,
            )

    def _prune_service_cache(self, now_utc: datetime) -> None:
        """Remove expired service responses from the in-memory cache."""
        self._service_cache = {
            key: value
            for key, value in self._service_cache.items()
            if now_utc - value[0] < self._service_cache_ttl
        }

    async def _log_api_error(self, response, operation: str) -> None:
        body = (await response.text())[:500]
        if response.status in (401, 403):
            _LOGGER.error("Realtime Trains %s rejected the API token (%s): %s", operation, response.status, body)
        elif response.status == 429:
            _LOGGER.warning("Realtime Trains rate limit reached; retry after %s seconds", response.headers.get("Retry-After", "unknown"))
        else:
            _LOGGER.warning("Realtime Trains %s failed (HTTP %s): %s", operation, response.status, body)

    def _calculate_aggregates(self):
        departure_delays = []
        arrival_delays = []
        stop_delays = []
        durations = []
        aggregate_delays = {}

        for train in self._next_trains:
            if "journey_time_mins" in train:
                durations.append(train["journey_time_mins"])
            if train.get("delay", 0) > 0:
                departure_delays.append(train["delay"])
            if train.get("arrival_delay", 0) > 0:
                arrival_delays.append(train["arrival_delay"])
            for stop in train.get("stops_of_interest", []):
                if stop.get("stop_delay", 0) > 0:
                    stop_delays.append(stop["stop_delay"])

        for name, values in (
            ("arrival", arrival_delays),
            ("departure", departure_delays),
            ("stop", stop_delays),
        ):
            if values:
                aggregate_delays[name] = {
                    "count": len(values),
                    "min": min(values),
                    "max": max(values),
                    "average": round(sum(values) / len(values)),
                }

        durations_data = (
            {
                "count": len(durations),
                "min": min(durations),
                "max": max(durations),
                "average": round(sum(durations) / len(durations)),
            }
            if durations
            else None
        )
        return {"delays": aggregate_delays, "durations": durations_data}

    @property
    def extra_state_attributes(self):
        attrs = {
            ATTR_JOURNEY_START: self._journey_start,
            ATTR_JOURNEY_END: self._journey_end,
        }
        if self._next_trains:
            attrs[ATTR_NEXT_TRAINS] = self._next_trains
            attrs[ATTR_AGGREGATE] = self._aggregate_data
        return attrs


def _api_datetime(value: Any) -> datetime | None:
    """Parse an API ISO datetime and apply Europe/London when no offset is supplied."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(TIMEZONE) if parsed.tzinfo else TIMEZONE.localize(parsed)
    except (TypeError, ValueError):
        return None


def _endpoint_name(endpoint: Any) -> str | None:
    endpoint = _first(endpoint)
    location = endpoint.get("location") if isinstance(endpoint, dict) else None
    return _location_name(location or endpoint)


def _first(value: Any) -> Any:
    return value[0] if isinstance(value, list) and value else value or {}


def _location_name(value: Any) -> str | None:
    value = _first(value)
    if isinstance(value, str):
        return value
    return value.get("description") or value.get("name") or value.get("displayName")


def _location_code(value: dict[str, Any]) -> str | None:
    code = value.get("crs") or value.get("code") or value.get("locationCode")
    if isinstance(code, str) and ":" in code:
        code = code.rsplit(":", 1)[-1]
    return code.upper() if isinstance(code, str) else None


def _service_date(service: dict[str, Any], detail: dict[str, Any], default: date) -> date:
    value = detail.get("runDate") or service.get("runDate") or service.get("departureDate")
    if not value:
        return default
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return default


def _event_datetime(
    obj: dict[str, Any],
    legacy_key: str,
    new_key: str,
    service_date: date,
    fallback: datetime | None = None,
) -> datetime | None:
    value = obj.get(new_key)
    if value is None:
        value = obj.get(legacy_key)
    if value is None:
        return fallback
    if isinstance(value, dict):
        value = value.get("actual") or value.get("estimated") or value.get("scheduled") or value.get("time")
    if value is None:
        return fallback
    text = str(value)
    try:
        if "T" in text:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed.astimezone(TIMEZONE) if parsed.tzinfo else TIMEZONE.localize(parsed)
        digits = text.replace(":", "")
        if len(digits) < 4:
            return fallback
        parsed_time = time(int(digits[:2]), int(digits[2:4]))
        return TIMEZONE.localize(datetime.combine(service_date, parsed_time))
    except (TypeError, ValueError):
        return fallback


def _delta_secs(a: datetime, b: datetime) -> float:
    return (a - b).total_seconds()
