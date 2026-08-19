# Artificial Demand and Capacity Experiment Pipeline

Status: **proposed implementation and experiment plan**

## Purpose

Turn the artificial line and double-ring cases into a reproducible experiment
pipeline that can answer two separate questions:

1. At the same fleet size and absolute demand, when does Skip-Stop improve
   passenger service relative to All-Stop?
2. By how much can Skip-Stop increase the largest completely serviceable
   demand, with a certified lower and upper bound?

The topology definitions, spatial demand families, temporal profiles, integer
demand semantics, and reference-capacity notation are specified in
[`../reference/demand_case_families.md`](../reference/demand_case_families.md).
The physical A/B/C assumptions and headway derivations are specified in
[`../reference/topology_parameter_derivation/main.tex`](../reference/topology_parameter_derivation/main.tex).
This document defines the implementation order, experiment runner, proof
contracts, and acceptance evidence. It does not redefine those inputs.

## Fixed comparison contract

Every All-Stop/Skip-Stop comparison fixes:

- physical topology and A/B/C technology;
- fleet cardinality $K$ and initial-state policy;
- passenger demand realization, including integer OD-bucket counts;
- cabin capacity, horizon, and tail semantics;
- waiting policy;
- passenger objective and solver budget.

Changing any of these fields creates another experiment instance. Bounds from
different instances must not be combined.

The first tranche uses:

- the six-station bidirectional line and six-station double ring;
- a 60-minute horizon, with demand released during the first 45 minutes;
- P0 stationary demand;
- no station waiting;
- exact fixed fleet cardinality per probe and deterministic initial phases for
  every tested $K$;
- architecture B for the first Skip-Stop pilots;
- complete passenger service as the capacity-feasibility requirement;
- passenger journey time only in selected cells after the capacity frontier
  has been bounded.

Architectures A and C, bounded waiting, P1/P2/P4, optimized initial placement,
and longer horizons are later experiment factors, not part of the first
pipeline validation.

## Step 0: Freeze the physical artificial cases

Before generating results, create one versioned artificial-case specification
containing every elementary topology and operating input. No experiment may
silently obtain a different geometry or derived headway.

One parameter remains to be frozen explicitly: the intermediate bypass length.
The recommended baseline is 26 m, equal to the geometric length of the service
path. This isolates the benefit of avoiding the slow platform movement from an
additional benefit caused merely by a shorter geometric route. Retaining the
existing 20 m abstraction is possible, but then it must be documented as a
separate topology assumption and used consistently in all variants.

Acceptance evidence:

- one source of truth for the line and double-ring physical inputs;
- deterministic scenario fingerprints;
- identical topology and movement durations across A/B/C except for derived
  resource/headway policy;
- successful physical-policy and topology validation;
- exported table of elementary inputs and derived quantities.

## Step 1: Implement nested artificial demand generation

Implement F0--F6 and P0, P1, P2, and P4 exactly as defined in the reference
document. Let $c=(i,j,b)$ be an active OD-bucket cell with target share $q_c$.
Generate one deterministic infinite passenger sequence using

$$
c_m
=
\arg\max_c\{m q_c-n_c(m-1)\},
$$

with stable cell IDs as tie breakers. The size-$N$ instance is the prefix of
length $N$. Therefore

$$
D(N)\subset D(N+1)
$$

and an infeasibility result at $N$ applies to every larger prefix. Do not use
independent largest-remainder apportionment during a capacity search, because
it can move demand between cells when $N$ changes and destroys this monotonic
inference.

Required output:

```text
ArtificialDemandInstance
  topology_id
  spatial_family_id
  temporal_profile_id
  total_passengers
  ordered_integer_groups
  target_share_summary
  generator_version
  fingerprint
```

Tests:

- exact total $N$ for every generated instance;
- componentwise nesting from $N$ to $N+1$ over a long prefix;
- deterministic reproduction independent of dictionary iteration order;
- correct active OD cells and directional P2 handling on both topologies;
- empirical shares converge to the specified $q_c$;
- diameter OD pairs on the ring remain direction-neutral in the input.

## Step 2: Establish the physical $K$ domain and canonical starts

For each topology, technology, and operating mode, first compute a safe
physical packing/circulation upper bound

$$
\overline K_m^{\mathrm{UB}},
\qquad
m\in\{\mathrm{AS},\mathrm{SS}\}.
$$

The bound may include rope packing, platform, terminal, mechanism, horizon,
and circulation-work restrictions. It is allowed to be loose, but it must not
exclude a physically executable plan. Candidate exact fleet cardinalities are
then

$$
\mathcal K_m
=
\{1,\ldots,\overline K_m^{\mathrm{UB}}\}.
$$

On the double ring, the symmetric first tranche uses $k$ cabins in each
direction and therefore total $K=2k$. Passengers are not assigned to a
direction in advance. Asymmetric direction splits are a later sensitivity.

For every candidate $K$, build a deterministic initial physical state by
evenly phasing the cabins over the circulation patterns. The same state is
used for All-Stop and Skip-Stop at that $K$. This is a fixed-start experiment:
the capacity certificate applies to the stated initial-state policy, not to an
unknown optimal placement. Architecture-B boundary behavior is part of the
state fingerprint.

For All-Stop, the route and event timetable following this state is
deterministic. A complete movement infeasibility proof at exact $K$ implies

$$
\kappa_{\mathrm{AS}}^{=}(K)=0.
$$

For Skip-Stop, the same All-Stop trajectory is a valid primal seed whenever it
is physically feasible. Values above the All-Stop movement limit remain
eligible for a genuine Skip-Stop solve.

Tests and acceptance evidence:

- safe $\overline K_m^{\mathrm{UB}}$ on exhaustive tiny instances;
- exact fleet cardinality and symmetric ring split;
- deterministic phase, boundary-state, and event IDs for every $K$;
- identical starts between All-Stop and Skip-Stop at the same $K$;
- complete validation of every accepted All-Stop seed;
- explicit `INFEASIBLE` versus `UNKNOWN` movement status;
- stable state and timetable fingerprints used by all downstream results.

## Step 3: Define the certified $K$--$N$ capacity surface

For topology $\mathcal T$, spatial family $F$, operating mode $m$, and exact
active fleet cardinality $K$, define

$$
\kappa_m^{=}(K)
=
\max\{N:\text{exactly }K\text{ cabins completely serve }D(F,P0,N)\}.
$$

For every row $K$, maintain the invariant

$$
L_{m,K}
\le
\kappa_m^{=}(K)
\le
U_{m,K}.
$$

- $L_{m,K}$ is the largest $N$ with a completely validated executable plan;
- $U_{m,K}$ is the smallest valid capacity ceiling;
- $L_{m,K}=U_{m,K}$ is an exact row capacity.

Exact-$K$ capacity need not be monotone in $K$, because an additional active
cabin can introduce movement conflicts. The economically relevant
available-fleet frontier is therefore derived separately:

$$
\kappa_m^{\le}(K)
=
\max_{k\le K}\kappa_m^{=}(k).
$$

It is monotone and has the certified interval

$$
\max_{k\le K}L_{m,k}
\le
\kappa_m^{\le}(K)
\le
\max_{k\le K}U_{m,k}.
$$

The absolute mode capacity and the smallest fleet attaining it are

$$
\kappa_m^\star
=
\max_{K\in\mathcal K_m}\kappa_m^{=}(K),
\qquad
K_m^\star
=
\min\arg\max_{K\in\mathcal K_m}\kappa_m^{=}(K).
$$

For a selected demand level, the minimum required available fleet is

$$
K_m^{\min}(N)
=
\min\{K:\kappa_m^{\le}(K)\ge N\}.
$$

The two primary comparative quantities are therefore

$$
G_{\mathrm{capacity}}(K)
=
\frac{\kappa_{\mathrm{SS}}^{\le}(K)}
     {\kappa_{\mathrm{AS}}^{\le}(K)},
\qquad
G_{\mathrm{fleet}}(N)
=
1-
\frac{K_{\mathrm{SS}}^{\min}(N)}
     {K_{\mathrm{AS}}^{\min}(N)}.
$$

The normalized load used across temporal sensitivities is

$$
\rho=\frac{N}{\kappa_{\mathrm{AS}}^\star}.
$$

This replaces any arbitrary service-interval reference. It also distinguishes
maximum passenger capacity from maximum physically packable cabin count.

For an All-Stop row with feasible movement, events and Stop decisions are
fixed. Its capacity probe is therefore an exact fixed-timetable passenger
assignment with release times, destination delivery, direction choice on the
ring, and integer cabin-leg capacities. A finite unserved-passenger penalty is
not a feasibility proof: the row is feasible only when every passenger is
delivered. An exact row value requires adjacent certificates,

$$
N=\kappa_{\mathrm{AS}}^{=}(K)\text{ feasible},
\qquad
N=\kappa_{\mathrm{AS}}^{=}(K)+1\text{ infeasible}.
$$

## Step 4: Construct valid capacity ceilings for every $K$

Build a passenger-flow relaxation per mode and exact fleet cardinality that
maximizes the common demand multiplier while retaining every constraint needed
for a valid upper bound:

- OD flow conservation and delivery by the horizon;
- cabin-seat flow over physical path segments;
- rope, platform, terminal, and mechanism throughput capacities;
- fleet-time or circulation-work capacity;
- topology-valid service and bypass paths.

The relaxation may remove cabin identities, integer route synchronization,
exact event times, and detailed merge ordering. These removals enlarge the
feasible set. The implementation must include a proof mapping every executable
timetable to a feasible relaxed flow. Without this mapping, a numerical LP
value is only a heuristic estimate and must not be reported as
$U_{m,K}$.

The result supplies, for every candidate $K$,

$$
\kappa_m^{=}(K)
\le
\left\lfloor
\kappa_{m,\mathrm{flow}}^{\mathrm{UB}}(K)
\right\rfloor
=U_{m,K}^{\mathrm{flow}}.
$$

Validation:

- compare with exhaustive executable schedules on tiny cases;
- verify that every known feasible timetable maps into the relaxation;
- assert that the ceiling never falls below a validated feasible $N$;
- report separately the active rope, station, terminal, fleet-time, and
  passenger-flow bottlenecks;
- retain a coarse proven ceiling if a stronger optional relaxation fails.

## Step 5: Implement the proof-aware adaptive frontier runner

### Probe objective and bound extraction

The capacity phase never mixes passenger quality or fleet cost into its
objective. At fixed $(m,K,N)$ it solves only

$$
u_{m,K}^\star(N)
=
\min\sum_g u_g,
$$

where $u_g$ is the integer number of unserved passengers in demand group $g$.
Journey Time is optimized later, after complete service has been fixed. This
keeps every incumbent and solver bound interpretable in passenger-count units.

Suppose an interrupted minimization returns incumbent value
$\overline u_{m,K}(N)$ and global solver bound
$\underline u_{m,K}(N)$. An incumbent with
$\overline u_{m,K}(N)=0$ proves that $N$ is feasible. A positive integer lower
bound proves more than infeasibility at $N$. With numerical tolerance
$\epsilon_u$ define

$$
r
=
\left\lceil
\underline u_{m,K}(N)-\epsilon_u
\right\rceil.
$$

Nested demand implies

$$
u_{m,K}^\star(N-1)
\ge
u_{m,K}^\star(N)-1.
$$

Therefore $r\ge1$ yields the valid capacity update

$$
U_{m,K}
\leftarrow
\min\{U_{m,K},N-r\}.
$$

An incumbent with positive unserved demand may still improve the lower bound,
but $N-\overline u$ is not automatically a feasible nested prefix. Let $s_c$
be the incumbent's served count in OD-bucket cell $c$. Compute

$$
q
=
\max\{n:n_c(n)\le s_c\ \forall c\}.
$$

Restrict the incumbent assignment to $D(q)$ and independently validate the
resulting movement and passenger plans. Only then update

$$
L_{m,K}
\leftarrow
\max\{L_{m,K},q\}.
$$

Thus a solve with an open MIP gap can improve both sides of the capacity
interval. The central operation remains

```text
PROBE(mode, K, N)
```

but records the more informative outcomes:

- `FULLY_SERVED`: a validated incumbent has zero unserved passengers;
- `PROVED_NOT_FULLY_SERVICEABLE`: the global unserved bound is at least one;
- `BOUND_PROGRESS`: at least one capacity bound improved while the probe gap
  remains open;
- `NO_PROGRESS`: neither capacity bound improved;
- `INVALID_INTERNAL`: incumbent validation or bound consistency failed.

The nested demand construction makes each fixed-$K$ row monotone in $N$.
Consequently a feasible result covers every smaller prefix and an infeasible
result covers every larger prefix. `NO_PROGRESS` and a solver timeout never
change either capacity bound.

The probe result records at least:

```text
CapacityProbeResult
  mode
  cabin_count
  requested_passenger_count
  incumbent_unserved_count
  best_bound_unserved_count
  validated_prefix_passenger_count
  implied_capacity_upper_bound
  capacity_lower_bound_before/after
  capacity_upper_bound_before/after
  solver_status
  solver_mip_gap
  checkpoint
  movement_and_passenger_validation
```

### Warm-start policy

Warm starts are applied only across fingerprint-compatible problems:

1. At the same $K$, a plan for $D(N)$ starts a larger nested instance by
   retaining movement and served rides and initially marking new passengers
   unserved.
2. A larger-demand plan starts a smaller instance after trimming its passenger
   assignment to the requested prefix.
3. A validated All-Stop plan starts Skip-Stop at the same $(K,N)$ because
   $\mathcal F_{\mathrm{AS}}\subseteq\mathcal F_{\mathrm{SS}}$.
4. A checkpoint resumes the identical $(m,K,N)$ model whenever available.
5. A full-service capacity incumbent starts the later Journey-Time solve in
   the identical cell.
6. A plan from $K$ to exact $K+1$ is at most a partial MIP start: the old
   trajectories may be retained while the new cabin and affected order
   variables remain unset. It is never treated as a feasible incumbent.

Passenger warm starts are not transferred between demand families, temporal
profiles, waiting domains, or incompatible A/B/C policies. A movement-only
start may cross such a boundary only when independent validation proves that
it satisfies the target physical policy. Fixed-start and optimized-placement
certificates are never mixed.

### Inner search over $N$

Initialize $L_{m,K}=0$ and $U_{m,K}=U_{m,K}^{\mathrm{flow}}$. Reuse validated
plans and passenger assignments as warm starts. For Skip-Stop, import the
All-Stop lower bound and plan at the same $K$ whenever available:

$$
L_{\mathrm{SS},K}\ge L_{\mathrm{AS},K}.
$$

While no finite infeasible bracket is known, increase the demand geometrically:

$$
N_{\mathrm{next}}
=
\min\left\{
U_{m,K},
\max\left(L_{m,K}+1,\left\lceil1.5L_{m,K}\right\rceil\right)
\right\}.
$$

Once feasible and infeasible endpoints are known, use integer bisection:

$$
N_{\mathrm{next}}
=
\left\lfloor
\frac{L_{m,K}+U_{m,K}+1}{2}
\right\rfloor.
$$

Near the boundary, a difficult midpoint need not monopolize the budget. A
lower $N$ is useful for finding a full-service incumbent; a higher $N$ is often
useful for proving a positive unserved bound. The scheduler may therefore work
from both sides before resuming the hard boundary probe. Every probe is
checkpointed.

### Outer scheduling over $K$

Do not solve a rectangular matrix blindly. Seed the search with small,
intermediate, near-All-Stop-limit, and largest-bound candidate values. Then
prioritize rows with the largest remaining ability to improve the required
result.

For the absolute mode capacity, maintain

$$
L_m^\star=\max_K L_{m,K}.
$$

A row satisfying

$$
U_{m,K}\le L_m^\star
$$

cannot improve the absolute capacity and may be pruned from the global-maximum
search. Such a row must remain eligible when it could establish a smaller
$K_m^\star$ with the same capacity. To certify the available-fleet frontier at
a particular $K$, refine
only rows that still contribute to

$$
\max_{k\le K}U_{m,k}
-
\max_{k\le K}L_{m,k}.
$$

To certify the minimum fleet for a target demand $N$, find the first $K$ with
$L_{m,K}\ge N$ and prove $U_{m,k}<N$ for every smaller $k$. No monotonicity of
the exact-$K$ rows is assumed.

With open intervals, minimum fleet size is itself reported as

$$
\min\{K:U_{m,K}\ge N\}
\le
K_m^{\min}(N)
\le
\min\{K:L_{m,K}\ge N\}.
$$

### Capacity and solver stopping rules

The normal relative Gurobi MIP gap is not the experiment's stopping metric:
the optimal unserved objective can be zero. Capacity probes therefore request
exact optimization (`MIPGap = 0`) but are interrupted by a fixed wall-clock
budget or a callback once their capacity purpose has been achieved. In
particular, a zero-unserved incumbent may stop immediately. Otherwise a probe
may stop once its derived row/global capacity interval meets the configured
target.

After $\kappa_{\mathrm{AS}}^\star$ has been certified, define

$$
g_{m,K}^{\mathrm{rel}}
=
\frac{U_{m,K}-L_{m,K}}
     {\kappa_{\mathrm{AS}}^\star},
\qquad
g_m^{\star,\mathrm{rel}}
=
\frac{\max_K U_{m,K}-\max_K L_{m,K}}
     {\kappa_{\mathrm{AS}}^\star}.
$$

The experiment protocol fixes these quality levels before results are known:

- screening: global capacity gap at most 5%;
- regularly reported capacity frontiers: at most 2%;
- headline F1/F2/F4 and A/B/C comparisons: at most 1%.

Selected fleet-saving claims require the minimum-fleet interval to collapse to
one integer $K$, irrespective of the percentage capacity target. If a
predeclared wall-clock budget expires first, report the open interval; never
relax the target retrospectively to obtain a preferred conclusion.

The runner should consume the existing Fixed-$K$ certificate interface where
possible rather than defining another meaning for feasibility or optimality.
The relevant contract is described in
[`ddd_fixed_k_certified_bounds.md`](ddd_fixed_k_certified_bounds.md).

Required output:

```text
CapacityFrontierResult
  case_fingerprint
  exact_k_intervals[K] = [L_K, U_K]
  available_fleet_intervals[K]
  global_capacity_interval
  minimum_fleet_certificates_by_target_N
  best_validated_plans
  probe_history
  pruning_provenance
  configured_capacity_gap_level
  achieved_row_and_global_capacity_gaps
  timing_and_model_metrics
```

## Step 6: Run the first discriminating pilots

Use architecture B, P0, and no waiting. The initial census contains F0, F1,
F2, and F4 on both topologies, yielding eight capacity-frontier cases. Within
that census, inspect these four discriminating cases first:

| Topology | Family | Main hypothesis |
|---|---|---|
| Line | F1 common hub | Hub and mandatory terminals constrain capacity gain. |
| Line | F2 complementary clusters | Stop-pattern specialization helps, but terminals remain shared. |
| Double ring | F2 complementary clusters | Largest expected gain because neither terminals nor OD stations are universally shared. |
| Double ring | F4 local | Negative control; skipping should provide little capacity or journey-time benefit. |

For every case, retain the same demand sequence and initial-state policy across
All-Stop and Skip-Stop. First bound $\kappa_m^{=}(K)$ and
$\kappa_m^{\le}(K)$; do not optimize journey time in every probe.

After the capacity frontier is stable, evaluate passenger quality at

$$
N\in
\{0.5,0.8,1.0\}\,\kappa_{\mathrm{AS}}^\star.
$$

At each load, compare Journey Time with a common fleet
$K=K_{\mathrm{AS}}^{\min}(N)$ and separately report the minimum fleet required
by each mode. Feasible points above the All-Stop capacity are capacity results,
not same-demand Journey-Time comparisons.

For a Journey-Time solve, fix complete service explicitly,

$$
u_g=0\qquad\forall g,
$$

and minimize total release-to-arrival time. The validated capacity plan is the
initial incumbent. Journey-Time gaps are reported in both passenger-hours and
relative terms, with the same predeclared 5% screening, 2% regular, and 1%
headline levels. These objective gaps never alter a capacity certificate.

Record:

- served and unserved passengers;
- total and mean journey, waiting, and in-vehicle time;
- selected Stop/Skip pattern and fleet utilization;
- validated incumbent and certified objective bound;
- capacity lower/upper bounds and relative interval;
- model size, setup time, solve time, and validation time;
- which physical resource limits the relaxed and executable solutions.

The first pilots answer whether the experiment design distinguishes the
intended mechanisms. They do not yet support a general empirical claim.

## Step 7: Expand the experiment matrix conditionally

Proceed only after the four pilots produce valid, interpretable certificates.
Expand in this order:

1. remaining F0--F6 profiles under P0;
2. A/B/C technology comparison with identical absolute demand;
3. P1, P2, and P4 using the absolute $N$ derived from the P0 reference;
4. bounded waiting at 30 and 60 seconds;
5. asymmetric ring fleet splits and optimized initial placement;
6. longer horizons and real-world demand cases.

Do not renormalize each temporal profile to its own capacity. Keeping the
P0-derived $N$ exposes the effect of temporal concentration. Also report an
optional cross-family absolute-demand panel based on F0, because
family-specific $\kappa_{\mathrm{AS}}$ is appropriate for relative loading but
can hide differences in absolute passenger volume.

## Reproducibility and output layout

Every generated result must include:

- code commit and dirty-worktree indicator;
- scenario, policy, timetable, demand, solver, and objective fingerprints;
- elementary inputs and derived A/B/C quantities;
- random seeds and deterministic tie-breaking version;
- exact solver statuses and time limits;
- independent movement, headway, and passenger validation;
- lower- and upper-bound provenance.

Suggested output hierarchy:

```text
benchmarks/output/artificial_capacity/
  references/<topology>/<family>/K_<K>/all_stop_capacity.json
  relaxations/<topology>/<family>/<technology>/K_<K>/flow_upper_bound.json
  probes/<topology>/<family>/<technology>/<waiting>/K_<K>/N_<N>/result.json
  frontiers/<topology>/<family>/<technology>/<waiting>/frontier.json
  summaries/capacity_intervals.csv
  summaries/load_curves.csv
```

The runner must resume from completed fingerprint-compatible probes and reject
stale outputs after topology, demand-generation, policy, or solver-contract
changes.

## Completion criteria

The first implementation tranche is complete when:

- the frozen artificial topologies and nested demand generator are tested;
- safe physical $K$ domains and deterministic fixed starts are available;
- All-Stop seeds validate wherever they are reported feasible;
- exact or explicitly open $\kappa_{\mathrm{AS}}^{=}(K)$ and
  $\kappa_{\mathrm{SS}}^{=}(K)$ intervals exist for the eight initial
  topology/family combinations;
- mathematically justified per-$K$ flow ceilings pass tiny exhaustive tests;
- the architecture-B pilots produce interruption-safe exact-$K$ and
  available-fleet frontiers plus selected load-curve records;
- every lower bound comes from a validated executable timetable;
- every upper bound has explicit infeasibility or relaxation provenance;
- open solver gaps contribute only through certified unserved and validated
  nested-prefix bounds;
- warm starts cross only explicitly compatible fingerprints;
- screening, regular, and headline gap targets are configured before a run;
- no result interprets a timeout as infeasibility or $\rho=1.1$ as a physical
  maximum.
