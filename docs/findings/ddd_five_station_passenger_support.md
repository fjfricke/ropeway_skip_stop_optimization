# DDD Five-Station Passenger-Support Diagnosis

## Scope

Recorded on 2026-08-10 from the uncommitted `ddd` branch working tree. The
measurements come from:

- `benchmarks/output/ddd_passenger_master/five_station_k19_skip_no_wait_50/`
  for the equality-core loop;
- `benchmarks/output/ddd_passenger_master/five_station_k19_free_primal/` for
  the independent CP-SAT primal run.

This finding concerns the fixed-start, fixed-$K$ DDD passenger loop on
`five_station_circle_cw_half_skip_no_wait_v0` with $K=19$. It separates three
questions that must not be conflated:

1. how quickly the anonymous passenger master solves;
2. how informative its passenger lower bound is;
3. how efficiently CP-SAT returns physical information to the master.

## Equality-core run

The 50-round aggregate passenger-master run ended without a physical
incumbent after approximately 116 seconds. Its main measurements were:

- master lower bound: approximately $2{,}676$ passenger-seconds;
- master model build time: approximately $6.65$ seconds in total;
- master optimization time: approximately $3.51$ seconds in total;
- CP-SAT time: approximately $101$ seconds in total;
- 50 CP-SAT calls, all proving their fixed aggregate supports infeasible;
- 50 exact support-core cuts and no time-cell splits;
- all 1,280 passengers optimistically served in the master;
- no validated passenger upper bound.

The master objective remained almost unchanged while CP-SAT rejected one
aggregate count vector after another. The selected passenger service was
priced as if very late visit layers could occur close to time zero because
many source cells still had lower bound zero. Exact equality no-goods then
removed only the currently selected point in a very large count-vector space.

This case is therefore not primarily limited by Gurobi master optimization.
It is limited by an overly optimistic passenger-time relaxation and local
support feedback.

## Independent primal run

A free full-route CP-SAT call followed by exact fixed-movement passenger
assignment produced a validated timetable in approximately 3.17 seconds:

- CP-SAT movement search: approximately $2.69$ seconds;
- exact passenger assignment: approximately $0.09$ seconds;
- journey-time upper bound: approximately $697{,}373$ passenger-seconds;
- served passengers: 1,248 of 1,280;
- 19 Skip visits and 409 Stop visits.

The CP search did not prove optimality. This is a valid upper bound and useful
primal seed, but it does not strengthen the anonymous lower bound by itself.

## Interpretation and limitations

The experiment shows that adaptive Gurobi master time limits are not the first
response to this particular failure: CP support processing and relaxation
quality dominate. It does not establish that the same profile holds with
waiting, optimized initial placement, other fleet sizes, or other objectives.
The independent CP result establishes feasibility and an upper bound, not
optimality. Planned responses and their proof obligations are kept in
`docs/plans/ddd_stronger_cp_support_cuts.md`.

## Structural earliest-time run

The same 50-round configuration was repeated with layer-state earliest-time
clipping enabled. The only intended formulation change was that every layered
state cell was intersected with its resource-free earliest reachable interval.

| Metric | Original | Earliest-time clipping |
|---|---:|---:|
| Lower bound | 2,676.36 | 409,360.38 |
| Validated upper bound | none | none |
| Total solve time | 116.26 s | 120.25 s |
| Initial nodes | 365 | 348 |
| Initial arcs | 1,288 | 1,232 |
| Final variables | 12,524 | 11,637 |
| Final constraints | 9,988 | 9,050 |
| Final threshold binaries | 494 | 278 |
| Fixed-support CP calls/cuts | 50 | 50 |
| Total CP-SAT time | 101.11 s | 101.78 s |

The lower bound increased by 406,684.02 passenger-seconds, or a factor of
approximately 153. Relative to the previously obtained free-CP upper bound of
697,372.78, the resulting open relative gap is approximately 41.3 percent.
Network size fell by approximately 4.7 percent in nodes and 4.3 percent in
arcs; the final master fell by approximately 7.1 percent in variables and 9.4
percent in constraints.

This confirms that the near-zero passenger bound was caused primarily by
physically impossible early layer times. It also confirms a separate issue:
all 50 selected aggregate supports remained physically infeasible, so
reachability clipping alone does not replace stronger support feedback or an
independent primal channel.

## Bootstrap and nearest-support smoke result

The first integrated two-round run with the independent bootstrap and
nearest-feasible-support oracle used the same Five-Station $K=19$ Skip/no-wait
Passenger Journey case. The free bootstrap found and exactly passenger-scored
a valid timetable in 2.63 seconds, establishing an immediate upper bound of
1,422,004 passenger-seconds before the first master solve.

Both master supports were physically infeasible. The nearest-support solves
nevertheless returned validated timetables and certified nontrivial exclusion
radii:

| Round | nearest primal distance | certified distance lower bound |
|---:|---:|---:|
| 1 | 174 | 54 |
| 2 | 78 | 27 |

The best repaired timetable reduced the upper bound to 696,749 while the
structural passenger master retained the lower bound 409,360. Thus the first
two rounds already produced a valid open interval of approximately
$[409{,}360,696{,}749]$. The second master contained 6,802 shared aggregate
threshold binaries; this is the principal model-size cost of exact L1-ball
cuts and must be measured in longer runs.

## Controlled 20-round A/B result

The bootstrap/equality and bootstrap/equality/nearest variants were then run
for 20 rounds with identical five-second fixed-support CP budgets. The nearest
variant received an additional five-second CP budget per rejected support.

| Metric | Bootstrap + equality | Bootstrap + equality + nearest |
|---|---:|---:|
| Solve time | 49.73 s | 158.18 s |
| Lower bound | 409,360.38 | 409,360.38 |
| Upper bound | 1,422,004.21 | 636,168.52 |
| Relative open gap (to UB) | 71.21% | 35.65% |
| Equality-core cuts | 20 | 20 |
| Distance cuts | 0 | 20 |
| Fixed-support CP time | 39.86 s | 39.83 s |
| Nearest-support CP time | 0 s | 100.60 s |
| Master build/solve time | 2.52/2.40 s | 4.49/5.18 s |
| Final variables/constraints | 11,478/8,702 | 18,161/22,087 |
| Shared threshold binaries | 119 | 6,802 |

All 20 master supports were physically infeasible in both variants. The
equality-only upper bound therefore remained at the bootstrap value. Every
nearest-support call returned a validated physical timetable. Its certified
distance lower bounds ranged from 11 to 54, while its found primal distances
ranged from 52 to 173. The best upper bound was already reached in round 7.

The first distance cut materialized essentially the full shared threshold
vocabulary; later distance cuts reused the 6,802 binaries and added only their
new rows. Master optimization nevertheless remained below approximately 0.35
seconds per round. The additional runtime came almost entirely from the fixed
five-second nearest-support budget.

This establishes two distinct conclusions. First, nearest-support search is a
strong primal repair/diversification channel: it improved the upper bound by
approximately 55.3 percent over the same bootstrap. Second, unweighted L1
balls in the complete high-dimensional route-count space did not raise the
passenger lower bound in 20 rounds. The passenger master can move to another
far-away but equally optimistic support. Further lower-bound work should
therefore target passenger-relevant service projections or resource/time
structure rather than merely extending this unweighted run.

## Timed-flow cover implementation smoke

The first opt-in timed-flow-cover smoke used the same Five-Station $K=19$
Skip/no-wait journey-time passenger master, disabled bootstrap and nearest
support to isolate cut generation, and allowed five seconds for each CP call.
Two rounds completed in 5.42 seconds:

| Round | CP status/time | Timed core | Covers in master | Threshold binaries | Core resource provenance |
|---:|---:|---:|---:|---:|---|
| 1 | infeasible / 2.17 s | 1 | 0 | 0 | D entry exit-switch and platform-entry |
| 2 | infeasible / 2.23 s | 1 | 1 | 1 | C entry exit-switch |

Each lower-threshold core added one new cover. The first cover was present in
round two with exactly one shared threshold binary and three associated rows
(two equivalence rows and the cover itself). The master lower bound remained
$409{,}360.38$ after two rounds; this smoke establishes correct sparse
materialization and physical localization, not convergence. In particular it
must not be compared as an upper-bound experiment because both independent
primal channels were deliberately disabled.

## Controlled 20-round equality versus timed-flow cover result

A controlled follow-up kept the free bootstrap enabled, disabled nearest
support in both variants, and used identical five-second fixed-support CP
budgets. This isolates the lower-bound feedback of aggregate equality cores
and timed-flow lower-threshold covers.

| Metric | Aggregate equality cores | Timed-flow covers |
|---|---:|---:|
| Solve time | 49.38 s | 61.18 s |
| Lower bound | 409,360.38 | 409,360.38 |
| Bootstrap upper bound | 1,422,004.21 | 1,422,004.21 |
| Absolute gap | 1,012,643.83 | 1,012,643.83 |
| Cuts after 20 rounds | 20 | 20 |
| Mean / median core size | 5.85 / 5 | 3.70 / 2 |
| One-literal cores | 0 | 7 |
| CP solve time total | 39.75 s | 45.31 s |
| Master build time total | 2.43 s | 7.00 s |
| Master optimize time total | 2.39 s | 2.29 s |
| Final variables / constraints | 11,478 / 8,702 | 11,414 / 8,574 |
| Final threshold binaries | 119 | 55 |

The timed formulation therefore produced smaller and more local cores and
reduced threshold binaries by 53.8 percent. Seven rounds proved a single
timed-region overload sufficient; the reported provenance repeatedly points
to physical exit-switch and platform-entry resources at all five station
entries. The final master used 64 fewer variables and 128 fewer rows.

This structural improvement did not yet improve the passenger lower bound.
The master continued to choose a different support with the same optimistic
passenger value after every cut. Runtime increased by 23.9 percent. About 4.57
seconds of the increase came from repeated master construction, because the
current implementation reconstructs and matches stable timed regions on every
round; CP solving itself added about 5.56 seconds. Master optimization did not
become harder.

The result supports retaining timed-flow covers as a sparse experimental cut
family, but not replacing equality cores by default yet. The immediate
engineering improvement is a cached region-to-child-arc index. The next
mathematical experiment should aggregate the localized literals into reusable
resource-window covers or add passenger-relevant service projections; simply
running more pointwise supports is not expected to lift the current lower-
bound plateau quickly.

## Fixed-schedule passenger-relaxation diagnosis

To localize the remaining gap, every movement arc was fixed to a complete
validated timetable and only the anonymous passenger master was reoptimized.
The diagnostic first isolated every recovered event time in a one-tick DDD
cell. Thus it measures passenger-flow relaxation on the selected timetable,
not optimism from coarse movement times. Its relaxed value is a lower bound
for that fixed timetable only; it is not another global lower bound.

Two independent feasible schedules were tested:

| Schedule source | Fixed-schedule relaxed value | Exact passenger value | Absolute underestimate | Relative underestimate |
|---|---:|---:|---:|---:|
| Free CP-SAT bootstrap | 1,422,004.210176 | 1,422,004.210176 | 0.000000 | 0.000000% |
| Nearest feasible support, 10-round run | 622,435.558176 | 622,435.558176 | 0.000000 | 0.000000% |

Both tested cases are exact up to floating-point tolerance. The raw difference
on the much better nearest-support timetable was approximately
$-1.2\cdot10^{-10}$ seconds and is reported as zero. The remaining global
interval after ten rounds is $[409{,}360.38,622{,}435.56]$, an absolute gap of
approximately $213{,}075$. Passenger relaxation on the fixed timetable
therefore explains none of that observed global gap in this experiment.

This changes the next-step priority. Trajectory-based passenger coupling is
not currently justified as the main formulation change for the no-wait
Five-Station case. The evidence instead points to the anonymous movement and
resource projection: the master repeatedly obtains excellent passenger
service from route/time flows that cannot jointly be assigned to physical
cabins. The next experiment should therefore strengthen reusable resource-
window/cumulative movement cuts and measure whether they lift the lower bound.
Nearest-support CP remains useful as the primal channel. The conclusion is
specific to fixed-start $K=19$, no waiting, journey time; waiting-enabled and
larger-network cases still require their own fixed-schedule diagnostics.

## Resource-local timed-core diagnosis

The optional local explainability diagnostic was run for 20 timed-flow rounds
on the same fixed-start $K=19$ no-wait journey-time instance. Bootstrap stayed
enabled, nearest-support stayed disabled, the main fixed-support CP budget was
five seconds, and each local resource probe received two seconds. The complete
run is stored in
`benchmarks/output/ddd_passenger_master/local_explainability_20_2s/`.

| Metric | Result |
|---|---:|
| Rejected timed supports | 20 |
| Proved by one resource | 18 |
| Proved only by a resource group | 2 |
| Global / unresolved | 0 / 0 |
| Cores entirely touching the explaining resource set | 9 |
| Local-probe time | 34.64 s |
| Main fixed-support CP time | 49.01 s |
| Total solve time | 107.39 s |
| Lower / upper bound | 409,360.38 / 1,422,004.21 |

All five station entries occurred in the proof provenance. The resources were
the exit-switch and platform-entry headways. The two group cases appeared in
rounds 13 and 18 and coupled resources at four and three stations,
respectively. Thus every sampled rejection had a resource explanation once
the local budget was sufficient.

This result must be interpreted more narrowly than “merge conflicts explain
everything.” A one-resource probe keeps exact route, time, horizon, and
cabins-through-visits consistency. In only seven single-resource rounds (plus
the two group rounds) did every literal of the returned local core itself use
the explaining resource set. The other eleven contradictions needed timed
literals elsewhere in the trajectory even after all other resource
no-overlaps had been removed. A direct anonymous interval-capacity row is
therefore promising for nine observations; it is not yet a valid replacement
for the remaining mixed trajectory/resource covers.

The existing timed covers showed moderate cross-support reuse. Eleven cuts
excluded only their own observed support. Nine would also exclude later or
earlier observed supports: two excluded one other support, four excluded two,
and one each excluded three, four, and five. Nevertheless the global lower
bound did not move in 20 rounds. The next experiment should generate a proved
resource-window/Hall row only from the resource-touching local cores and keep
the current timed cover for every mixed core. If that A/B test does not lift
the bound per unit time, the lower-bound bottleneck is trajectory consistency
rather than missing local capacity rows, and work should move to
sequence-/trajectory-linking cuts while nearest-support search remains the
primal timetable channel.
