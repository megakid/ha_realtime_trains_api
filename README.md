# realtime_trains_api
api.rtt.io Home Assistant integration

It provides detailed live train departures and journey stats:

```yaml
station_code: WAL
calling_at: WAT
next_trains:
  - origin_name: Woking
    destination_name: London Waterloo
    service_uid: Q46187
    scheduled: 19-01-2022 23:17
    estimated: 19-01-2022 23:17
    minutes: 4
    platform: null
    operator_name: South Western Railway
    scheduled_arrival: 19-01-2022 23:57
    estimate_arrival: 19-01-2022 23:57
    journey_time_mins: 40
    stops: 11
  - origin_name: Basingstoke
    destination_name: London Waterloo
    service_uid: Q46486
    scheduled: 19-01-2022 23:43
    estimated: 19-01-2022 23:43
    minutes: 30
    platform: null
    operator_name: South Western Railway
    scheduled_arrival: 20-01-2022 00:10
    estimate_arrival: 20-01-2022 00:09
    journey_time_mins: 27
    stops: 5
unit_of_measurement: min
icon: mdi:train
friendly_name: Next Waterloo train data
```

This Home Assistant integration is only made possible by the brilliant Realtime Trains API (https://api.rtt.io also see https://www.realtimetrains.co.uk) which is maintained by Tom Cairns under swlines Ltd (https://twitter.com/swlines).

Alternatively, you can use the built-in `uk_transport` integration (see https://www.home-assistant.io/integrations/uk_transport/).  NOTE: Unlike this `realtime_trains_api` integration, `uk_transport` cannot provide additional journey details such as stops, journey durations and arrival times.

# Guide

## Installation & Usage

1. Signup to https://api.rtt.io
2. Add repository to HACS (see https://hacs.xyz/docs/faq/custom_repositories) - use "https://github.com/megakid/ha_realtime_trains_api" as the repository URL.
3. Install the `realtime_trains_api` integration inside HACS
5. To your HA `configuration.yaml`, add the following:
```yaml
sensor:
  - platform: realtime_trains_api
    username: '[Your RTT API Auth Credentials username]'
    password: '[Your RTT API Auth Credentials password]' # (recommended to use '!secret my_rtt_password' and add to secrets.yaml)
    scan_interval:
      seconds: 90 # this defaults to 60 seconds (in HA) so you can change this.  Dont set it too frequent or you might get blocked for abuse of the RTT API.
    queries:
        - origin: WAL
          destination: WAT
          # arrival_times_for_next_X_trains is optional, defaults to 0. 
          # Entering 5 here means the first 5 departures from the origin 
          # (WAL in this case) to destination (WAT in this case) will hit 
          # the API to lookup the number of stops, journey time and estimated
          # arrival time to the destination (WAT in this case).
          arrival_times_for_next_X_trains: 5 
          auto_adjust_scans: true # If no depatures are retrieved, back off polling interval to 30 mins (until there are some trains)
        - origin: WAT
          destination: WAL
          sensor_name: My Custom Journey # this will appear as 'sensor.my_custom_journey'
          time_offset:
            minutes: 20 # This will display departures from now+20 minutes - useful if the station is 20 minutes travel/walk away.
```
6. Restart HA
7. Your `sensor` will be named something like `sensor.next_train_from_wal_to_wat` (unless you specified a `sensor_name`) for each query you defined in your configuration.