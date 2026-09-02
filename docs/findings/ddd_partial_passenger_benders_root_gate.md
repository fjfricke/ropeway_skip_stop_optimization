# Partial Passenger Benders root gate

Date: 2026-09-02

## Decision

The strengthened partial Passenger Benders experiment fails its `K=20` root
gate. Do not implement a Branch-and-Benders callback for the current DDD
Passenger formulation.

This result applies to the current canonical Fixed-$K$, balanced-reference,
No-Wait Five-Station Architecture B instance with problem fingerprint
`2c53481066e498cc29ec206e717911f55d1ac30296cdc5cb8ac05139b35fbd01`.
It does not invalidate Benders decomposition in general or a future Passenger
formulation with a different separable structure.

## Reference

The matched complete monolithic LP and MIP value is

\[
z^{LP}=z^{IP}=525\,730.9081600005.
\]

The implementation plan required a certified root bound of at least 90% of
this value, or `473,157.817`, within 30 separation rounds and 120 seconds while
retaining no more than 40% of the monolithic Passenger nonzeros.

## Implemented gate

The gate reuses the complete DDD Movement arc-flow and the normalized Passenger
domain. A deterministic subset of demand groups remains as an exact Passenger
core in the master. Residual Passenger capacity is

\[
A_Ry_R\le C(x)-A_Cy_C,
\]

so core and residual passengers share rather than duplicate cabin capacity.
The residual LP produces globally valid affine cuts in both Movement variables
$x$ and Passenger-core variables $y_C$.

Two cut strategies were tested:

- the ordinary optimal dual returned by Gurobi;
- a Magnanti-Wong-style auxiliary dual that stays tight at the current point
  and maximizes the cut value at a convex core point.

Before considering multi-cuts, a coupling graph was built between residual
demand groups and shared cabin-capacity rows. Components of this graph are the
finest valid independent recourse blocks.

## Results

| core and cuts | core Passenger variables | core nonzeros | cuts | certified LB | reference fraction | root time |
|---|---:|---:|---:|---:|---:|---:|
| Hybrid 20%, standard dual | 31,644 | 19.90% | 30 | 48,643.542 | 9.25% | 118.4 s |
| Hybrid 20%, core-point dual | 31,644 | 19.90% | 9 | 48,643.542 | 9.25% | 121.0 s |
| Hybrid 40%, standard dual | 59,935 | 39.16% | 11 | 85,163.475 | 16.20% | 120.0 s |

For the 20% standard run, master solution time was 83.6 seconds and residual
LP time was 7.6 seconds. The first partial master already supplied the entire
final lower bound. All 30 residual cuts left `theta = 0` at the subsequent
master optima, despite source violations between roughly 0.75 and 0.86 million.
The cuts were locally tight but globally ineffective.

For the 20% core-point run, the auxiliary dual consumed 44.6 seconds. Seven
core-point-strengthened and two ordinary cuts were accepted, but the certified
lower bound still did not move. Thus dual degeneracy was not repaired
sufficiently by this core-point construction.

The 40% core is the largest admissible core under the planned memory gate. Its
initial bound rose to `85,163.475`, but its residual cuts again failed to raise
the bound. It missed the required bound by more than 387,000 objective units.

## Why component multi-cuts do not apply

For the 20% core, the residual domain contains:

- 17 demand groups;
- 127,315 Passenger variables;
- 16,100 shared capacity rows;
- exactly one coupling component containing all groups and variables.

Consequently, the residual recourse is not separable by OD group. Creating one
theta and one independent cut per OD group would duplicate shared cabin
capacity and would be invalid. The only exact component multi-cut is the single
global cut already being generated.

## Interpretation

The experiment confirms the earlier standard-Benders diagnosis rather than
overturning it. The strong monolithic LP bound is not reproduced by a small set
of global Passenger value-function cuts. It depends on a broad simultaneous
interaction of Passenger flow, ride activation, and shared cabin-capacity rows.
Keeping 20% or 40% of that structure preserves only a small fraction of the
bound; the projected remainder remains highly coupled.

A callback would keep Gurobi's tree alive, but it would still separate the same
ineffective value function. It would add implementation and subproblem cost
without evidence that either the root lower bound or integer incumbent path
would improve. The callback phases are therefore canceled by the plan's own
acceptance rule.

## Recommended solver portfolio

Continue with independently valid channels:

- complete DDD arc-flow MIP for small and medium instances and strong primal
  search;
- complete DDD arc-flow LP/barrier and trajectory Root-CG, taking the maximum
  compatible certified lower bound;
- CP-SAT or Movement arc-flow schedule generation followed by exact Passenger
  IP evaluation, taking the minimum compatible validated upper bound;
- matched long runs only where the recorded bound/incumbent curve is still
  improving.

The partial-core, residual-capacity, core-point, and coupling-index code remains
useful as a tested research artifact and as evidence for the thesis. It should
not be exposed as a production campaign method.
