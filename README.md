# realtime_trains_api
api.rtt.io Home Assistant integration

It provides detailed live train departures and journey stats:

```yaml
- origin_name: London Waterloo
  destination_name: Portsmouth & Southsea
  service_date: '2022-01-16'
  service_uid: L52875
  scheduled: '18:02'
  estimated: '18:02'
  platform: '17'
  operator_name: South Western Railway
  scheduled_arrival: '19:10'
  estimated_arrival: '19:09'
  journey_time_mins: 67
  stops: 2
```

This Home Assistant integration is only made possible by the brilliant Realtime Trains API (https://api.rtt.io also see https://www.realtimetrains.co.uk) which is maintained by Tom Cairns under swlines Ltd (https://twitter.com/swlines).

Alternatively, you can use the built-in `uk_transport` integration (see https://www.home-assistant.io/integrations/uk_transport/).  NOTE: Unlike this `realtime_trains_api` integration, `uk_transport` cannot provide additional journey details such as stops, journey durations and arrival times.

# Guide

## Installation & Usage

1. Signup to https://api.rtt.io
2. Add repository to HACS (see https://hacs.xyz/docs/faq/custom_repositories) - use "https://github.com/megakid/ha_realtime_trains_api" as the repository URL.
3. Install the `realtime_trains_api` integration inside HACS
4. To your HA `configuration.yaml`, add the following:

```yaml
sensor:
  - platform: realtime_trains_api
    username: '[Your RTT API Auth Credentials username]'
    password: '[Your RTT API Auth Credentials password]' # (recommended to use '!secret my_rtt_password' and add to secrets.yaml)
    queries:
        - origin: WAL
          destination: WAT
          # arrival_times_for_next_X_trains is optional, defaults to 0. 
          # Entering 5 here means the first 5 departures from the origin 
          # (WAL in this case) to destination (WAT in this case) will hit 
          # the API to lookup the number of stops, journey time and estimated
          # arrival time to the destination (WAT in this case).
          arrival_times_for_next_X_trains: 5 
        - origin: WAT
          destination: WAL
```
5. Restart HA
6. Your `sensor` will be named something like `sensor.next_train_from_wal_to_wat` for each query you defined in your configuration.