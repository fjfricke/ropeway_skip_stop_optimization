# Demand Case Families and Demand Profiles

This document defines a compact case taxonomy for evaluating when skip-stop
operation improves an urban ropeway system. A **demand family** describes the
spatial OD and resource-conflict structure. A **demand profile** describes how
that demand changes over time. Every family can be combined with every profile.

## 1. Demand Families

| ID | Family | Spatial structure | Expected skip-stop effect |
|---|---|---|---|
| F0 | Diffuse demand | Demand is distributed approximately uniformly across many OD pairs. | Neutral reference case; usually little opportunity for specialized stop patterns. |
| F1 | Common hub | Several strong OD groups share the same central station. | Travel-time savings are possible, but the shared hub remains a station bottleneck. |
| F2 | Complementary OD clusters | Strong OD groups require largely different sets of intermediate stations. | High potential: stop patterns can use different station resources while sharing the rope. |
| F3 | Long-distance / express | Most passengers travel across a large part of the line. | High in-vehicle time savings and potentially fewer cabins for a target frequency. |
| F4 | Local demand | Most passengers travel only one or two stations. | Negative control case; additional waiting can exceed the saved travel time. |
| F5 | Mixed local and express | Strong short-distance and long-distance markets coexist. | Specialized local and express cabins may improve both capacity allocation and journey times. |
| F6 | Downstream starvation | Strong upstream demand fills cabins before they reach later boarding stations. | Skip-stop can reserve capacity for downstream passengers and improve service equity. |

The central explanatory quantity is the overlap of **avoidable station
resources** between OD groups. Skip-stop is expected to be most valuable when
this overlap is low while shared rope and mandatory terminal resources still
have residual capacity.

## 2. Demand Profiles

| ID | Profile | Temporal structure | Purpose |
|---|---|---|---|
| P0 | Stationary | Constant demand throughout the horizon. | Isolates the spatial mechanism of a demand family. |
| P1 | Single peak | Demand increases, reaches one peak, and decreases again. | Represents a simple morning or event peak. |
| P2 | Tidal peak | Demand direction reverses between morning and evening. | Tests asymmetric commuting demand. |
| P3 | Double peak | Separate morning and evening peaks with a weaker midday period. | Provides a compact daily demand pattern. |
| P4 | Batch arrivals | Short, concentrated pulses arrive from feeders or events. | Tests queues and capacity conflicts caused by non-smooth arrivals. |
| P5 | Uncertain demand | A base profile is perturbed by scenario-specific or stochastic variation. | Tests robustness of stop patterns and schedules. |

Each family-profile combination should additionally be varied by:

- demand intensity relative to all-stop capacity;
- directional asymmetry;
- cluster strength, from diffuse to strongly concentrated;
- synchronization or time offsets between different OD clusters.

The first experiments should combine F0--F6 with P0. Selected cases should
then be repeated with P1, P2, and P4 before introducing full-day or uncertain
profiles.

## 3. Experimental Setups

### Setup 1: Small Artificial Line and Ring

Setup 1 uses two six-station topologies. They share all physical and operating
parameters so that differences can be attributed to the terminal structure
rather than to different calibration choices.

#### A1: Six-station line

```text
T0 <-> S1 <-> S2 <-> S3 <-> S4 <-> T5
```

- `T0` and `T5` are mandatory terminal stations with turnaround routes;
- `S1`--`S4` provide service and bypass routes in both directions;
- cabins circulate from one terminal to the other and back;
- the terminals cannot be skipped.

The line primarily measures journey-time savings, fleet efficiency, passenger
capacity allocation, and the limiting effect of mandatory shared terminals.

#### A2: Bidirectional six-station ring

```text
        S1 ---- S2
      /            \
    S0              S3
      \            /
        S5 ---- S4
```

- one clockwise and one counter-clockwise circulation pattern use separate
  directional rope resources;
- all six stations provide service and bypass routes in both directions;
- cabins remain assigned to one direction in Setup 1;
- passengers may use either direction, subject to the passenger-routing model;
- no cabin direction change or rope switch is included.

The ring additionally measures whether complementary stop patterns and the two
directions can increase useful throughput without a mandatory terminal
bottleneck.

#### Common baseline parameters

| Parameter | Baseline | Rationale |
|---|---:|---|
| Rope length between adjacent stations | 300 m | Compact urban spacing while retaining meaningful line-haul time. |
| Rope speed | 6.0 m/s | Representative upper operating speed for a detachable urban gondola. |
| Platform speed | 0.3 m/s | Slow continuous movement for boarding and alighting. |
| Platform length | 10 m | Compatible with one small gondola and the existing station abstraction. |
| Bypass length | 20 m | Existing compact bypass abstraction. |
| Fast approach/departure connector | 5 m each | Existing station-layout abstraction. |
| Braking/acceleration connector | 3 m each | Existing timing abstraction; not an engineering acceleration design. |
| Cabin capacity | 10 passengers | Representative small urban gondola. |
| Cabin length | 3.0 m | Existing cabin geometry. |
| Minimum compressed station clearance | 0.5 m | Gives 3.5 m cabin pitch inside a station. |
| Rope line headway | Separate technology scenario | Must not be inferred from the service-platform pitch. |
| Merge headway | Separate technology scenario | Captures independently moving carriers and attachment into a free line slot. |
| Waiting | Disabled | Isolates stop-pattern effects in the first experiment. |

These values imply the following nominal movement times:

| Movement | Time |
|---|---:|
| One rope segment | 50.0 s |
| Intermediate service route | about 36.9 s |
| Intermediate bypass route | about 3.3 s |
| Time saved by one skipped station | about 33.6 s |
| Terminal turnaround route | about 35.2 s |
| All-stop line round trip | about 14.4 min |
| All-stop ring rotation | about 8.7 min |

The headways belong to three physically different mechanisms. The line headway
is an independent technology input:

$$
d_{\mathrm{rope}} = v_{\mathrm{rope}}h_{\mathrm{rope}},
$$

the merge headway follows from detection, braking, attachment, and free-slot
requirements, and the service-channel headway is derived from the compressed
station pitch:

$$
h_{\mathrm{station}} =
\frac{3.0\,\mathrm{m}+0.5\,\mathrm{m}}{0.3\,\mathrm{m/s}}
\approx 11.7\,\mathrm{s}.
$$

The safety derivation, source provenance, and proposed sensitivity cases are
documented in
[`topology_parameter_derivation/main.tex`](topology_parameter_derivation/main.tex).

The current `OperatingParameters.required_cabin_spacing_m` uses one spacing for
both calculations. Setup 1 therefore requires separate line, merge, and station
headways before it is used for final experiments; silently reusing one pitch for
all resources would distort the capacity comparison.

The initial evaluation uses a 60-minute service horizon. Demand is released in
the first 45 minutes and the final 15 minutes allow previously released demand
to be served. Fleet size and demand intensity are experiment factors rather
than topology parameters. All-stop and skip-stop must always be compared with
the same fleet size, demand realization, horizon, and initial-state policy.

After the no-wait baseline, selected cases are repeated with maximum station
waiting times of 30 and 60 seconds. Longer daily profiles are introduced only
after the spatial families are understood in the 60-minute setup.
