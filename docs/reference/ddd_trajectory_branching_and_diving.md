# Certified trajectory branching and bounded diving

The fixed-start trajectory Root-CG supports immutable physical branch domains
and a bounded primal dive coordinator. This page records the implemented
contract; remaining clique, LNS, and complete tree work stays in
[`../plans/ddd_dive_branch_price_cut.md`](../plans/ddd_dive_branch_price_cut.md).

## Branch-domain contract

`DddTrajectoryBranchPredicate` currently supports service decisions and stable
route-option decisions. A missing visit evaluates to false. Therefore the
children `predicate=true` and `predicate=false` are disjoint and cover the
complete parent trajectory universe, including shorter trajectories.

`DddTrajectoryBranchDomain` canonicalizes decisions, detects contradictions,
serializes deterministically, and has its own fingerprint. The exact fixed-
start pricing model receives the same decision equalities used to filter
existing columns. Every node pricing certificate records the branch-domain
fingerprint.

The implementation deliberately rejects branch domains for OIP and reservoir
pricing until their complete branch semantics are implemented and tested.

## Bounded dive contract

`DddTrajectoryDiveCoordinator` rebuilds the restricted trajectory LP, selects
the most balanced fractional Stop/Skip predicate, follows one child, and reruns
exact node column generation. It may import generated trajectories and update
the upper bound only from a complete validated integer timetable.

Unexplored siblings are not retained. Consequently node lower bounds are
diagnostic only and the returned global lower bound remains the certified root
bound. This is a primal heuristic with exact node pricing, not yet a complete
Branch-Price tree.

The application CLI exposes:

- `--dive`;
- `--dive-time-limit`;
- `--dive-node-time-limit`;
- `--dive-count`;
- `--dive-max-depth`;
- `--dive-node-iterations`.

All dive time is reserved inside the common application wall-clock budget.
Candidate selection time is charged to the dive budget, and a node is not
continued without at least one compatible column for every cabin.

## Start-boundary limitation

Balanced-reference starts up to the analytic All-Stop maximum use the common
evenly spaced All-Stop snapshot and are supported by Root-CG. Above that
maximum, the balanced Skip-Stop snapshot can contain resource occupancies that
cross the boundary at time zero. Fixed-start proof pricing now receives the
complete immutable boundary-occurrence tuple, constrains every prospective
route-resource usage against it, and attaches the cabin's own occurrences to
the generated trajectory. The boundary tuple participates in the Root-CG
instance fingerprint.

Boundary-aware resource-window rows are now supported exactly. For a priced
cabin, its immutable boundary occurrence contributes the constant coefficient

$$
a^{\partial}_{c,w}
=
\mathbb{1}\{\text{the fixed occurrence of }c\text{ covers window }w\}
$$

to the reduced cost of every prospective column. Boundary occurrences of
other cabins remain fixed obstacles in the pricing model. An occurrence that
starts before time zero is intersected with the modeled horizon, so its
effective entry tick is zero; negative non-boundary entries remain invalid.
For No-Wait time-expanded pricing, variable resource-window membership is
constant on each route arc and its dual coefficient is attached directly to
that arc. The compact and bounded-Wait formulations retain explicit exact
membership variables.

## Five-Station K=20 gate

The first 300-second calibration with balanced-reference starts produced:

| Quantity | Value |
|---|---:|
| certified Root-CG lower bound | 523,756.726 |
| final restricted LP | 526,731.757 |
| All-Stop seed upper bound | 635,519.998 |
| known complete arc-flow Skip-Stop objective | about 525,730.908 |
| root-bound distance to that objective | about 0.376% |
| fractional trajectory options | 55 |
| fractional service decisions | 296 |

The basic service-decision dive followed four balanced branches but did not
improve the All-Stop upper bound. This is positive evidence for the dual/root
channel and negative evidence for pure one-path service diving as the main
primal mechanism. The next Gate-2 experiment must combine the root certificate
with a complete fixed-K arc-flow incumbent or a real cabin/corridor
fix-and-optimize neighborhood before any full Branch-Price tree is built.

## Five-Station K=39 boundary gate

Boundary-aware Root-CG was run on the first exact fleet size above the analytic
All-Stop maximum of 38. The periodic balanced snapshot contained five fixed
resource occurrences crossing the retained boundary. Pair-only Root-CG
converged in 15 rounds and about 340 seconds:

| Quantity | Value |
|---|---:|
| fixed boundary occurrences | 5 |
| generated trajectory columns | 568 |
| final incompatibility pairs | 45,646 |
| certified full root-LP value | 315,690.6 |
| validated periodic-seed objective | 1,441,586.4 |
| certified integer gap | 78.10% |

This establishes that exact boundary pricing and root-bound generation scale
to K=39. It does not establish a useful integer schedule: the remaining gap is
almost entirely a primal problem.

A subsequent complete fixed-K arc-flow run received the compatible Root-CG
bound and 600 seconds with `MIPFocus=1`. Its integrated model contained 42,471
movement variables, 312,833 Passenger variables, and 512,996 Passenger
coupling rows. Gurobi improved the global integer lower bound to 407,377.4 but
did not find a second incumbent; the periodic seed remained at 1,441,586.4 and
the certified gap was 71.74%. The solver spent essentially the complete budget
at the root node. A larger unrestricted arc-flow tree is therefore not the
next primal experiment; a movement/trajectory neighborhood with exact
Passenger evaluation outside its search core is required.

## Resource-window root gate

The first boundary-aware clique experiment used
`RESOURCE_WINDOWS_WITH_PAIR_FALLBACK`. Exact unit tests compare its reduced
cost against exhaustive enumeration, including a fixed own-cabin boundary
occurrence.

At K=20, a 180-second run generated 692 resource-window rows and 240 columns.
The restricted master left the seed after three rounds and reached a certified
lower bound of 512,709.7. This is valid but weaker at the fixed time budget
than the established pair-only root result.

At K=39, 394 resource-window rows made the initial compatible schedule an
integral restricted-master solution. Independent pricing still found one
negative-reduced-cost column for almost every cabin in each round, but those
columns were not jointly compatible. Consequently the RMP stayed at
1,441,586.4 and the pricing-corrected global lower bound remained zero. Barrier
duals did not alter the outcome. Direct time-expanded arc coefficients reduced
each pricing round to about 30 seconds, compared with roughly 475 seconds when
all resource-window membership auxiliaries were built indiscriminately.

The conclusion is deliberately narrow: resource cliques are valid and strong,
but one-best-column-per-cabin generation is not a suitable high-density engine
for them. A complete Branch-Cut-and-Price tree is deferred until a coordinated
or multi-column pricing gate makes the K=39 restricted master and certified
bound move.

## Coordinated primal packages with pair-only proof pricing

Generating three diverse independent columns per cabin did not move the K=39
clique RMP even after 468 stored columns. The implemented alternative uses the
complete CP-SAT movement model to generate all cabins jointly. Its objective
contains a bounded, deterministically cabin-balanced subset of Passenger-dual
ride preferences. The current calibration uses at most 200 preferences, a
validated incumbent as CP hint, and a CP wall-clock limit that includes model
setup.

The returned schedule batch is fully conflict-free and validated before its
trajectory columns enter the RMP. It has no certificate authority: the global
lower bound continues to use only exact single-cabin proof pricing. Formally,

$$
LB_t
=
z_t^{RMP}+\sum_c\min\{0,\underline\rho_{ct}\}
$$

is unchanged by the CP objective, while any complete CP package may improve
the restricted integer incumbent and hence the validated upper bound.

The decisive K=39 run combined pair-only rows with one 20-second coordinated
CP call every fifth round. It completed exact Root-CG in 17 rounds and about
530 seconds:

| Quantity | Value |
|---|---:|
| certified full root-LP value | 315,690.6 |
| validated coordinated upper bound | 1,326,950.7 |
| certified integer gap | 76.21% |
| generated columns | 660 |
| final incompatibility pairs | 64,681 |

The lower bound exactly reproduces the prior pair-only reference, while the
upper bound improves by about 7.95%. This hybrid is therefore the current
preferred calibration path. Resource-window cliques remain opt-in until they
can retain comparable proof progress.

A subsequent six-case fixed-$K$ screening on each of two demand levels refined
that conclusion. Pair-only Root-CG certified the root at half demand for all
three Skip-Stop fleet sizes $K\in\{20,38,39\}$, and it proved the full-demand
$K=20$ problem integer optimal. The difficult cases are primal rather than
dual: at $K=39$, where no all-stop seed exists, the ten-minute integer gaps were
77.15% at half demand and 64.03% at full demand. Consequently coordinated CP
is retained as a primal-only component, but the next gate increases package
frequency and tests package-level fix-and-optimize before implementing a full
Branch-Price tree.

## Test coverage

Automated tests cover branch complement partitioning, deterministic payloads,
contradictions, branch candidate ranking, both service children against
exhaustive exact pricing, exact node Root-CG, and the integral-root dive case.
