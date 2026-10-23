# Realtime Trains API for Home Assistant

A Home Assistant custom integration providing live UK train departure and journey information using the [Realtime Trains API v2](https://realtimetrains.github.io/api-specification/).

The integration can provide:

- Live departure information
- Scheduled and estimated departure times
- Delay information
- Platform information
- Train operator
- Destination arrival forecasts
- Journey duration
- Number of stops
- Arrival forecasts for selected intermediate stations
- Multiple journey queries
- Automatic API access-token renewal
- Temporary caching of service data to reduce API usage

## Example sensor data

A configured sensor exposes the number of minutes until the next departure as its state, with detailed journey information available as attributes.

Example:

```yaml
journey_start: KGX
journey_end: YRK
next_trains:
  - origin_name: London Kings Cross
    destination_name: York
    service_uid: "gb-nr:XXXXXXXX:2026-10-22"
    scheduled: "22-10-2026 15:30"
    estimated: "22-10-2026 15:32"
    delay: 2
    minutes: 12
    platform: "5"
    operator_name: "Example operator"
    status: "Delayed"
    stops_of_interest:
      - stop: PBO
        name: Peterborough
        scheduled_stop: "22-10-2026 16:15"
        estimate_stop: "22-10-2026 16:17"
        stop_delay: 2
        journey_time_mins: 45
    scheduled_arrival: "22-10-2026 17:20"
    estimate_arrival: "22-10-2026 17:22"
    arrival_delay: 2
    journey_time_mins: 110
aggregate_data:
  delays:
    departure:
      count: 1
      min: 2
      max: 2
      average: 2
```

The exact attributes available depend on the service information returned by Realtime Trains and your configuration.

---

# Realtime Trains API

This integration uses the next-generation Realtime Trains API:

**API documentation:**  
https://realtimetrains.github.io/api-specification/

**API Portal:**  
https://api-portal.rtt.io/

**Realtime Trains website:**  
https://www.realtimetrains.co.uk/

You need a Realtime Trains API account and token to use this integration.

The API uses Bearer token authentication. If you are issued a long-lived **refresh token**, this integration automatically exchanges it for a short-lived access token using `/api/get_access_token` and renews it when required.

---

# Installation

## HACS

This is a custom integration and can be installed using HACS.

1. In Home Assistant, open **HACS**.
2. Add this repository as a custom repository.
3. Use:

   ```
   https://github.com/YOUR-GITHUB-USERNAME/ha_realtime_trains_api
   ```

4. Select **Integration** as the repository type.
5. Install **realtime_trains_api**.
6. Restart Home Assistant.

Replace `YOUR-GITHUB-USERNAME` with the owner of the repository you are installing.

If this update is merged into the original project, the upstream repository is:

```
https://github.com/megakid/ha_realtime_trains_api
```

---

# Realtime Trains API credentials

Go to:

https://api-portal.rtt.io/

Sign in with an RTT unified login account and request access to the API.

If you are issued a **refresh token**, store it in your Home Assistant `secrets.yaml` file:

```yaml
rtt_refresh_token: "YOUR_REFRESH_TOKEN"
```

Do not use a temporary access token here. The integration will obtain and renew access tokens automatically from your refresh token.

---

# Configuration

The integration is currently configured through `configuration.yaml`.

For example:

```yaml
sensor:
  - platform: realtime_trains_api
    refresh_token: !secret rtt_refresh_token

    scan_interval:
      minutes: 3

    auto_adjust_scans: true

    queries:
      - origin: KGX
        destination: YRK

        journey_data_for_next_X_trains: 2

        stops_of_interest:
          - PBO

        sensor_name: kings_cross_to_york
```

In this example:

- `KGX` is London King's Cross.
- `YRK` is York.
- `PBO` is Peterborough.
- Detailed journey information is requested for the next two services.
- Peterborough is included as an intermediate stop of interest.
- The resulting Home Assistant entity will use the custom sensor name.

The sensor entity will normally appear as:

```text
sensor.kings_cross_to_york
```

---

# Configuration options

## `refresh_token`

Required.

Your long-lived Realtime Trains refresh token.

It is strongly recommended that you put this in `secrets.yaml`:

```yaml
refresh_token: !secret rtt_refresh_token
```

rather than placing the token directly in `configuration.yaml`.

---

## `queries`

Required.

A list of journeys for which sensors should be created.

You can configure multiple queries:

```yaml
queries:
  - origin: KGX
    destination: YRK
    sensor_name: london_to_york

  - origin: YRK
    destination: KGX
    sensor_name: york_to_london
```

Each query creates a separate Home Assistant sensor.

---

## `origin`

Required.

The three-letter CRS code for the origin station.

For example:

```yaml
origin: KGX
```

---

## `destination`

Required.

The three-letter CRS code for the destination station.

For example:

```yaml
destination: YRK
```

The integration asks Realtime Trains for services from the origin which call at the configured destination.

---

## `sensor_name`

Optional.

Provides a custom Home Assistant entity name.

For example:

```yaml
sensor_name: kings_cross_to_york
```

Without this option the integration generates a name based on the origin and destination.

---

## `journey_data_for_next_X_trains`

Optional. Defaults to `0`.

Controls how many upcoming trains have additional service information retrieved.

For example:

```yaml
journey_data_for_next_X_trains: 2
```

will retrieve detailed journey information for the next two trains.

This enables information such as:

- Destination arrival time
- Estimated destination arrival
- Arrival delay
- Journey duration
- Number of stops
- Stops of interest

Setting:

```yaml
journey_data_for_next_X_trains: 0
```

disables the additional service lookups and therefore reduces API usage.

Service responses are temporarily cached to avoid repeatedly requesting the same service information on every sensor update.

---

## `stops_of_interest`

Optional.

Allows selected intermediate stations to be included in the information for each train.

For example:

```yaml
stops_of_interest:
  - PBO
```

For each matching service, the attributes can include information such as:

```yaml
stops_of_interest:
  - stop: PBO
    name: Peterborough
    scheduled_stop: "22-10-2026 16:15"
    estimate_stop: "22-10-2026 16:17"
    stop_delay: 2
    journey_time_mins: 45
```

Multiple stops can be configured:

```yaml
stops_of_interest:
  - PBO
  - DON
```

Stops-of-interest data is only populated for services for which journey data is retrieved.

---

## `time_offset`

Optional.

Allows departures earlier than a specified time from now to be ignored.

This can be useful if it takes you some time to reach the station.

For example:

```yaml
time_offset:
  minutes: 20
```

will ignore services scheduled to depart within the next 20 minutes.

---

## `scan_interval`

Controls how frequently Home Assistant updates the sensor.

For example:

```yaml
scan_interval:
  minutes: 3
```

Be mindful that a single sensor update can result in more than one API request if `journey_data_for_next_X_trains` is enabled.

The Realtime Trains API applies rate limits over minute, hour, day and week periods. If a rate limit is exceeded, the API returns HTTP `429 Too Many Requests`.

The integration caches service responses to reduce unnecessary API calls, but users with multiple queries should still choose a sensible polling interval.

See the current API documentation for rate-limit details:

https://realtimetrains.github.io/api-specification/

---

## `auto_adjust_scans`

Optional. Defaults to `false`.

For example:

```yaml
auto_adjust_scans: true
```

When enabled, the integration backs off polling when no upcoming services are available, reducing unnecessary API requests.

---

# Complete example

```yaml
sensor:
  - platform: realtime_trains_api
    refresh_token: !secret rtt_refresh_token

    scan_interval:
      minutes: 3

    auto_adjust_scans: true

    queries:
      - origin: KGX
        destination: YRK
        journey_data_for_next_X_trains: 2
        stops_of_interest:
          - PBO
        sensor_name: kings_cross_to_york

      - origin: YRK
        destination: KGX
        journey_data_for_next_X_trains: 2
        stops_of_interest:
          - PBO
        sensor_name: york_to_kings_cross
        time_offset:
          minutes: 15
```

And in `secrets.yaml`:

```yaml
rtt_refresh_token: "YOUR_REFRESH_TOKEN"
```

After making configuration changes, check your Home Assistant configuration and restart Home Assistant.

---

# API usage and rate limiting

The Realtime Trains API places limits on API usage.

A basic location lookup requires one request. Enabling:

```yaml
journey_data_for_next_X_trains
```

can result in additional `/rtt/service` requests.

To reduce API usage, this integration temporarily caches service responses using the service's unique identity. This prevents the same train from being looked up again on every polling cycle while the cache remains valid.

Users with several journey queries should consider:

- Using a sensible `scan_interval`
- Limiting `journey_data_for_next_X_trains` to the number of trains actually required
- Enabling `auto_adjust_scans`
- Only configuring `stops_of_interest` where useful

The API returns rate-limit information in its response headers and responds with HTTP `429` if a limit is exceeded.

---

# Troubleshooting

## Sensor exists but has no train data

Check:

**Developer Tools → States**

and locate the sensor.

You should at least see:

```yaml
journey_start: KGX
journey_end: YRK
```

If no `next_trains` attribute is present, check the Home Assistant logs.

---

## Authentication errors

Check that:

```yaml
refresh_token: !secret rtt_refresh_token
```

refers to the **long-lived refresh token**, not a temporary access token.

The integration automatically requests and renews temporary access tokens.

---

## HTTP 429 / rate-limit errors

Increase your polling interval and/or reduce:

```yaml
journey_data_for_next_X_trains
```

Remember that each 
