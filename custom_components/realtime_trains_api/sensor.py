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

CONF_API_APP_KEY = "username"
CONF_API_APP_ID = "password"
CONF_QUERIES = "queries"
CONF_ORIGIN = "origin"
CONF_DESTINATION = "destination"

_QUERY_SCHEME = vol.Schema(
    {
        vol.Required(CONF_ORIGIN): cv.string,
        vol.Required(CONF_DESTINATION): cv.string,
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
    queries: config[CONF_QUERIES]
    interval = timedelta(seconds=120)

    username = config[CONF_API_USERNAME]
    password = config[CONF_API_PASSWORD]

    for query in queries:
        station_code = query.get(CONF_ORIGIN)
        calling_at = query.get(CONF_DESTINATION)
        sensors.append(
            RealtimeTrainLiveTrainTimeSensor(
                username,
                password,
                station_code,
                calling_at,
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

    def _do_api_request(self, params):
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

    def __init__(self, username, password, station_code, calling_at, interval):
        """Construct a live train time sensor."""
        self._station_code = station_code
        self._calling_at = calling_at
        self._next_trains = []

        sensor_name = f"Next train from {station_code} to {calling_at}"
        query_url = f"search/{station_code}/to/{calling_at}"

        RealtimeTrainSensor.__init__(
            self, sensor_name, username, password, query_url
        )
        self.update = Throttle(interval)(self._update)

    def _update(self):
        """Get the latest live departure data for the specified stop."""
        params = {
        }

        self._do_api_request(params)
        self._next_trains = []

        if self._data != {}:
            if self._data["services"] == None:
                self._state = "No departures"
            else:
                for departure in self._data["services"]:
                    if departure["isPassenger"] == True:
                        self._next_trains.append(
                            {
                                "origin_name": departure["locationDetail"]["origin"][0]["description"],
                                "destination_name": departure["locationDetail"]["destination"][0]["description"],
                                "service_date": departure["runDate"],
                                "service_uid": departure["serviceUid"],
                                "scheduled": departure["locationDetail"]["gbttBookedDeparture"],
                                "estimated": departure["locationDetail"]["realtimeDeparture"],
                                "platform": departure["locationDetail"]["platform"],
                                "operator_name": departure["atocName"],
                            }
                        )

                if self._next_trains:
                    self._state = min(
                        _delta_mins(train["scheduled"]) for train in self._next_trains
                    )
                else:
                    self._state = None

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


def _delta_mins(hhmm_time_str):
    """Calculate time delta in minutes to a time in hh:mm format."""
    now = dt_util.now()
    hhmm_time = datetime.strptime(hhmm_time_str, "%H:%M")

    hhmm_datetime = now.replace(hour=hhmm_time.hour, minute=hhmm_time.minute)

    if hhmm_datetime < now:
        hhmm_datetime += timedelta(days=1)

    delta_mins = (hhmm_datetime - now).total_seconds() // 60
    return delta_mins