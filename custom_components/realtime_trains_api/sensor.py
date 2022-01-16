"""Support for UK train data provided by api.rtt.io."""
from __future__ import annotations

from datetime import datetime, timedelta
from http import HTTPStatus
import logging
import re

import requests
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.const import TIME_MINUTES
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import Throttle
import homeassistant.util.dt as dt_util

_LOGGER = logging.getLogger(__name__)

ATTR_ATCOCODE = "atcocode"
ATTR_LOCALITY = "locality"
ATTR_REQUEST_TIME = "request_time"
ATTR_STATION_CODE = "station_code"
ATTR_CALLING_AT = "calling_at"
ATTR_NEXT_TRAINS = "next_trains"

CONF_API_USERNAME = "username"
CONF_API_PASSWORD = "password"
CONF_QUERIES = "queries"
CONF_ORIGIN = "origin"
CONF_DESTINATION = "destination"
CONF_ARRIVALTIMES = "arrival_times_for_next_X_trains"

_QUERY_SCHEME = vol.Schema(
    {
        vol.Required(CONF_ORIGIN): cv.string,
        vol.Required(CONF_DESTINATION): cv.string,
        vol.Optional(CONF_ARRIVALTIMES, default=0): cv.positive_int,
    }
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_API_USERNAME): cv.string,
        vol.Required(CONF_API_PASSWORD): cv.string,
        vol.Required(CONF_QUERIES): [_QUERY_SCHEME],
    }
)


def setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Get the realtime_train sensor."""
    sensors: list[RealtimeTrainSensor] = []
    interval = timedelta(seconds=120)

    username = config[CONF_API_USERNAME]
    password = config[CONF_API_PASSWORD]
    queries = config[CONF_QUERIES]

    for query in queries:
        station_code = query.get(CONF_ORIGIN)
        calling_at = query.get(CONF_DESTINATION)
        arrival_times_for_next_X_trains = query.get(CONF_ARRIVALTIMES)
        sensors.append(
            RealtimeTrainLiveTrainTimeSensor(
                username,
                password,
                station_code,
                calling_at,
                arrival_times_for_next_X_trains,
                interval,
            )
        )

    add_entities(sensors, True)


class RealtimeTrainSensor(SensorEntity):
    """
    Sensor that reads the rtt API.

    api.rtt.io provides free comprehensive train data for UK trains
    across the UK via simple JSON API. Subclasses of this
    base class can be used to access specific types of information.
    """

    TRANSPORT_API_URL_BASE = "https://api.rtt.io/api/v1/json/"
    _attr_icon = "mdi:train"
    _attr_native_unit_of_measurement = TIME_MINUTES

    def __init__(self, name, username, password, url):
        """Initialize the sensor."""
        self._data = {}
        self._username = username
        self._password = password
        self._url = self.TRANSPORT_API_URL_BASE + url
        self._name = name
        self._state = None

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self._state

    def _do_api_request(self):
        """Perform an API request."""
        response = requests.get(self._url, auth=(self._username, self._password))
        if response.status_code == HTTPStatus.OK:
            self._data = response.json()
        elif response.status_code == HTTPStatus.FORBIDDEN:
            self._state = "Credentials invalid"
        else:
            _LOGGER.warning("Invalid response from API")

class RealtimeTrainLiveTrainTimeSensor(RealtimeTrainSensor):
    """Live train time sensor from api.rtt.io."""

    _attr_icon = "mdi:train"

    def __init__(self, username, password, station_code, calling_at,
                arrival_times_for_next_X_trains, interval):
        """Construct a live train time sensor."""
        self._station_code = station_code
        self._calling_at = calling_at
        self._arrival_times_for_next_X_trains = arrival_times_for_next_X_trains
        self._next_trains = []

        sensor_name = f"Next train from {station_code} to {calling_at}"
        query_url = f"search/{station_code}/to/{calling_at}"

        RealtimeTrainSensor.__init__(
            self, sensor_name, username, password, query_url
        )
        self.update = Throttle(interval)(self._update)

    def _update(self):
        """Get the latest live departure data for the specified stop."""
        self._do_api_request()
        self._next_trains = []

        trainCount = 0
        if self._data != {}:
            if self._data["services"] == None:
                self._state = "No departures"
            else:
                for departure in self._data["services"]:
                    if departure["isPassenger"]:
                        trainCount += 1
                        train = {
                                "origin_name": departure["locationDetail"]["origin"][0]["description"],
                                "destination_name": departure["locationDetail"]["destination"][0]["description"],
                                "service_date": departure["runDate"],
                                "service_uid": departure["serviceUid"],
                                "scheduled": _to_colonseparatedtime(departure["locationDetail"]["gbttBookedDeparture"]),
                                "estimated": _to_colonseparatedtime(departure["locationDetail"]["realtimeDeparture"]),
                                "platform": departure["locationDetail"]["platform"],
                                "operator_name": departure["atocName"],
                            }
                        if trainCount <= self._arrival_times_for_next_X_trains:
                            self._add_arrival_time(train)
                        self._next_trains.append(train)

                if self._next_trains:
                    self._state = min(
                        _delta_mins_vs_now(train["scheduled"]) for train in self._next_trains
                    )
                else:
                    self._state = None

    def _add_arrival_time(self, train):
        """Perform an API request."""
        trainUrl = self.TRANSPORT_API_URL_BASE + f"service/{train['service_uid']}/{train['service_date'].replace('-', '/')}"
        response = requests.get(trainUrl, auth=(self._username, self._password))
        if response.status_code == HTTPStatus.OK:
            data = response.json()
            stopCount = -1 # origin counts as a stop in the returned json
            found = False
            for stop in data['locations']:
                if stop['crs'] == self._calling_at:
                    scheduled_arrival = stop['gbttBookedArrival']
                    estimated_arrival = stop['realtimeArrival']
                    train["scheduled_arrival"] = _to_colonseparatedtime(scheduled_arrival)
                    train["estimated_arrival"] = _to_colonseparatedtime(estimated_arrival)
                    train["journey_time_mins"] = _delta_mins(train["estimated_arrival"] , train["estimated"])
                    train["stops"] = stopCount
                    found = True
                    break
                stopCount += 1
            if not found:
                _LOGGER.warning(f"Could not find {self._calling_at} in stops for service {train['service_uid']}.")    
        else:
            _LOGGER.warning(f"Could not populate arrival times: Invalid response from API (HTTP code {response.status_code})")

    @property
    def extra_state_attributes(self):
        """Return other details about the sensor state."""
        attrs = {}
        if self._data is not None:
            attrs[ATTR_STATION_CODE] = self._station_code
            attrs[ATTR_CALLING_AT] = self._calling_at
            if self._next_trains:
                attrs[ATTR_NEXT_TRAINS] = self._next_trains
            return attrs

def _to_colonseparatedtime(hhmm_time_str):
    return hhmm_time_str[:2] + ":" + hhmm_time_str[2:]

def _delta_mins(hhmm_time_str_a, hhmm_time_str_b):
    """Calculate time delta in minutes to a time in hh:mm format."""
    now = dt_util.now()
    hhmm_time_a = datetime.strptime(hhmm_time_str_a, "%H:%M")
    hhmm_datetime_a = now.replace(hour=hhmm_time_a.hour, minute=hhmm_time_a.minute)
    hhmm_time_b = datetime.strptime(hhmm_time_str_b, "%H:%M")
    hhmm_datetime_b = now.replace(hour=hhmm_time_b.hour, minute=hhmm_time_b.minute)
    
    if hhmm_datetime_a < hhmm_datetime_b:
        hhmm_datetime_a += timedelta(days=1)

    delta_mins = (hhmm_datetime_a - hhmm_datetime_b).total_seconds() // 60
    return delta_mins

def _delta_mins_vs_now(hhmm_time_str):
    """Calculate time delta in minutes to a time in hh:mm format."""
    now = dt_util.now()
    hhmm_time = datetime.strptime(hhmm_time_str, "%H:%M")
    
    hhmm_datetime = now.replace(hour=hhmm_time.hour, minute=hhmm_time.minute)

    if hhmm_datetime < now:
        hhmm_datetime += timedelta(days=1)

    delta_mins = (hhmm_datetime - now).total_seconds() // 60
    return delta_mins