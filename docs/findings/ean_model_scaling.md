# EAN Headway Model Scaling

Date: 2026-07-11

Software commit: `0df791f`

## Measurement

The current example builders were executed directly and the generated
`EanBuildArtifact` collections were counted before Gurobi model construction.
Passenger candidates use the default optimization configuration.

| Example | Cabins | Visits | Headway candidates | Headway pairs | Same-cabin pairs | Ride candidates |
|---|---:|---:|---:|---:|---:|---:|
| `three_station_v0` | 15 | 431 | 1,079 | 57,676 | 3,353 | 958 |
| `five_station_v0` | 31 | 989 | 2,719 | 166,692 | 4,077 | 5,136 |
| `five_station_no_wait_v0` | 61 | 1,947 | 3,894 | 471,950 | 5,838 | 10,108 |

For `five_station_v0`, pair counts by checkpoint kind are:

```text
platform entry: 60,648
platform exit:  45,396
exit switch:    60,648
```

For `five_station_no_wait_v0`, no platform-exit wait checkpoints are generated:

```text
platform entry: 235,975
exit switch:    235,975
```

## Findings

Headway pairs grow quadratically within each checkpoint because the current
builder emits every unordered pair. Same-cabin pairs are a small but
unambiguous first fixed-order class: `five_station_v0` could remove 4,077
ordering binaries without deciding the order of any different-cabin pair.

The two five-station variants are not an isolated comparison of waiting modes.
`five_station_v0` deliberately keeps every second start cabin and has 31
cabins, while `five_station_no_wait_v0` keeps all 61. Its larger pair count
therefore cannot be interpreted as evidence that disabling waiting increases
headway complexity. Cabin count and checkpoint set change simultaneously.

These counts are an implementation snapshot, not a stable property of the
physical scenarios. Builder, horizon, cabin-start, or checkpoint changes may
change them.
