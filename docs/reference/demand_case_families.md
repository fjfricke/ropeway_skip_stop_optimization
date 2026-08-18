# Demand Case Families and Demand Profiles

This document defines a compact case taxonomy for evaluating when skip-stop
operation improves an urban ropeway system. A **demand family** describes the
spatial OD and resource-conflict structure. A **demand profile** describes how
that demand changes over time. Families and profiles are combined factorially
unless an explicitly documented route-direction ambiguity prevents it.

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

### Setup 1: Small Artificial Line and Double Ring

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

#### A2: Bidirectional six-station double ring

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

The double ring is one topology, not two independent experimental cases. It
additionally measures whether complementary stop patterns and the two
simultaneous directions can increase useful throughput without a mandatory
terminal bottleneck. An OD demand is generated once. Passenger assignment may
choose the clockwise or counter-clockwise circulation; demand is not split
between the two directions in advance.

#### Artificial OD profiles

Both topologies use the common station index set

$$
V=\{0,1,2,3,4,5\}.
$$

On the line, stations 0 and 5 are terminals. On the double ring all six
stations are ordinary service stations. Let $w_{ij}\ge 0$ be the unnormalised
weight of the ordered OD pair $i\to j$. The generator normalises the selected
profile according to

$$
\bar w_{ij}=\frac{w_{ij}}{\sum_{o\ne d}w_{od}}.
$$

The following definitions are the executable artificial instances of the
families in Section 1.

##### F0: diffuse demand

Every ordered OD pair has equal weight:

$$
w_{ij}=1\qquad i\ne j.
$$

There are 30 active OD pairs on either topology. This is the neutral reference
case.

##### F4: local demand

Only adjacent stations exchange passengers. On the line,

$$
w_{ij}=1\iff |i-j|=1,
$$

which gives ten ordered OD pairs. On the double ring,

$$
w_{ij}=1\iff d_{\mathrm{ring}}(i,j)=1,
$$

which gives twelve ordered OD pairs. This is the negative control case for
skip-stop operation.

##### F3: long-distance/express demand

The line activates exactly the OD pairs with

$$
|i-j|\ge 4,
$$

namely $0\leftrightarrow4$, $0\leftrightarrow5$, and
$1\leftrightarrow5$. The double ring activates the three pairs of opposite
stations,

$$
0\leftrightarrow3,\qquad
1\leftrightarrow4,\qquad
2\leftrightarrow5.
$$

The double-ring pairs have two equally short physical routes. Their direction
is therefore chosen by passenger assignment rather than fixed by the demand
generator.

##### F1: common hub

Station 2 is the common hub on both topologies:

$$
w_{ij}=1\iff (i=2\lor j=2)\land i\ne j.
$$

This gives ten ordered OD pairs. It deliberately retains one common station
bottleneck while allowing other stations to be skipped.

##### F2: complementary OD clusters

The two equally strong bidirectional markets are

$$
1\leftrightarrow3,
\qquad
2\leftrightarrow4.
$$

Their origin/destination station sets are disjoint, although their shortest
paths share rope infrastructure. This directly tests whether cabin groups can
specialise on different station resources while continuing to use the same
line or directional rope.

##### F5: mixed local and express demand

Let $\bar w^{F4}$ and $\bar w^{F3}$ be the already normalised local and express
matrices for the selected topology. The mixed profile is

$$
\bar w^{F5}
=0.5\,\bar w^{F4}+0.5\,\bar w^{F3}.
$$

Thus exactly half of total demand is assigned to local markets and half to
long-distance markets, independently of how many OD pairs each component
contains.

##### F6: downstream starvation

The line uses two mirrored directional clusters:

| Ordered OD pair | Raw weight |
|---|---:|
| $1\to4$ | 7 |
| $2\to5$ | 3 |
| $4\to1$ | 7 |
| $3\to0$ | 3 |

In the increasing-index direction, strong demand at station 1 can occupy cabin
capacity before station 2 is reached. The decreasing-index direction contains
the reflected case.

The double ring uses an analogous case on both directional ropes:

| Ordered OD pair | Unique shortest direction | Raw weight |
|---|---|---:|
| $0\to2$ | clockwise | 7 |
| $1\to3$ | clockwise | 3 |
| $3\to1$ | counter-clockwise | 7 |
| $2\to0$ | counter-clockwise | 3 |

Every OD pair has a unique two-segment shortest route. Consequently this case
loads both directions symmetrically without preassigning passengers to a rope
in the input data. A passenger optimiser may still select a longer route if
its complete journey-time objective justifies doing so.

F6 measures both stop-pattern specialisation and passenger-capacity
allocation. A sufficiently strong integrated assignment can reserve downstream
capacity even under all-stop operation, so an improvement in F6 must not be
attributed to skip-stop alone without inspecting the passenger solution.

#### Artificial temporal profiles

The initial horizon is 60 minutes. Demand is released in nine five-minute
buckets at

$$
08{:}00,08{:}05,\ldots,08{:}40,
$$

and the interval from 08:45 to 09:00 is reserved for serving already released
demand. Let $p_b$ be an unnormalised temporal weight and
$\bar p_b=p_b/\sum_kp_k$.

##### P0: stationary

$$
p=[1,1,1,1,1,1,1,1,1].
$$

This profile is used for every spatial family in the first experiment stage.

##### P1: single peak

$$
p=[1,2,3,4,5,4,3,2,1].
$$

The release rate at 08:20 is five times the rate in the first and final
buckets, while total demand remains unchanged after normalisation.

##### P2: tidal

For a directional OD pair, the increasing-index/clockwise temporal weights are

$$
p^+=[5,5,4,3,2,1,1,1,1],
$$

and the reflected direction uses

$$
p^-=[1,1,1,1,2,3,4,5,5].
$$

On the line, the sign follows the OD direction. On the double ring, it follows
the unique shortest ring direction. Diameter OD pairs with two equally short
routes cannot receive a directional tidal label from the current demand data;
they are excluded from P2 until route preference is represented explicitly.

##### P4: batch arrivals

$$
p=[3,0,0,3,0,0,3,0,0].
$$

Three equal feeder/event batches arrive at 08:00, 08:15, and 08:30. P3
(double peak) and P5 (uncertain demand) are deferred until the 60-minute
baseline cases are understood.

#### Integer demand generation

For a requested total of $N$ passengers, the fractional number assigned to OD
pair $i\to j$ and bucket $b$ is

$$
x_{ijb}=N\bar w_{ij}\bar p_b.
$$

Demand groups must contain integer passenger counts. The generator first sets
$n_{ijb}=\lfloor x_{ijb}\rfloor$ and then distributes the remaining passengers
to cells in descending order of fractional remainder. Stable OD and bucket IDs
break ties. Therefore

$$
\sum_{i\ne j}\sum_b n_{ijb}=N
$$

holds exactly and repeated generation is deterministic.

The definition of $N$ is deliberately not fixed here. The next methodological
decision is whether intensity should be referenced to cabin flow, seat-segment
capacity, an all-stop passenger optimum, or a combination of these quantities.
Until that reference-capacity definition is fixed, concrete demand counts are
experiment inputs rather than topology constants.

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
| Cabin height | 2.22 m | Manufacturer reference for a ten-passenger cabin. |
| Attachment point to cabin roof | 2.0 m | Explicit compact urban-system assumption. |
| Attachment point to lowest envelope | 4.22 m | Derived geometric sway-envelope input. |
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

The A/B/C artificial scenarios use the derived headway policy described in the
linked derivation. Rope, merge, service-platform, and mechanism requirements
are represented separately; the legacy common-spacing value is not used for
their collision or capacity constraints.

The initial evaluation uses a 60-minute service horizon. Demand is released in
the first 45 minutes and the final 15 minutes allow previously released demand
to be served. Fleet size and demand intensity are experiment factors rather
than topology parameters. All-stop and skip-stop must always be compared with
the same fleet size, demand realization, horizon, and initial-state policy.

After the no-wait baseline, selected cases are repeated with maximum station
waiting times of 30 and 60 seconds. Longer daily profiles are introduced only
after the spatial families are understood in the 60-minute setup.
