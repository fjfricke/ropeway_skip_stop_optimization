# Merge-Time-Corridor Primal Search

## Scope

The merge-time-corridor optimizer is a primal-only fix-and-optimize channel for
the fixed-start trajectory Root-CG. It addresses the failure mode of a cabin
cohort neighborhood: a merge sequence can require coordinated route changes by
many cabins even though those changes are localized at one merge wave.

The method does not change proof pricing, the Root-LP certificate, or the
meaning of the global lower bound.

## Neighborhood

Let `bar y[c,v,o]` be the route selection of the current validated incumbent.
For merge family `m` and half-open time window `[T1,T2)`, the selector finds all
incumbent merge occurrences

$$
O(m,T_1,T_2)=
\{(c,v):m(c,v)=m,\ T_1\le \bar t_{cv}<T_2\}.
$$

For every occurrence, the released set contains the merge visit plus configured
upstream and downstream visit padding:

$$
F=\bigcup_{(c,v)\in O}
\{(c,j):v-b^-\le j\le v+b^+\}.
$$

Every incumbent route decision outside `F` is fixed:

$$
y_{cv\bar o_{cv}}=1
\qquad \forall(c,v)\notin F.
$$

Inside `F`, the original Stop/Skip domain remains available. Event times are
not fixed. CP-SAT re-solves the complete movement horizon, including every
resource interval and headway. A local route change that creates a downstream
conflict is therefore rejected globally.

The current implementation is deliberately No-Wait. Bounded Waiting can later
release wait decisions in `F` and a recovery suffix while retaining global
resource validation.

## Deterministic selection

Candidates are generated from every merge occurrence and configured window
width. Windows inducing the same set of merge occurrences are deduplicated.
The score is

$$
s=|O|+4D+2Q,
$$

where `D` is Root-LP mass using a route different from the incumbent and `Q`
is fractional incumbent-route mass. Ties use family ID, window bounds, and a
stable fingerprint. Consecutive calls rotate through the ranked candidates.

This is a deterministic initial policy, not a claim that the weights are
universally optimal. Gate experiments must compare it against global
coordinated CP and whole-cabin cohorts.

## Bound semantics

CP-SAT uses Passenger-dual ride preferences only as a search objective. Every
candidate is converted to a complete trajectory package and independently
validated. The fixed-movement Passenger MIP then provides its exact objective
value before it may update the upper bound:

$$
UB_{t+1}=\min\{UB_t,z^{\mathrm{package-IP}}\}.
$$

Corridor search does not contribute a reduced-cost certificate:

$$
LB_{t+1}^{\mathrm{RootCG}}=LB_t^{\mathrm{RootCG}}
$$

unless ordinary proof pricing independently improves the Root-CG bound.
Infeasibility of one corridor proves only that this restricted neighborhood has
no alternative, never global infeasibility.

## Research context

The implementation is a problem-specific large-neighborhood/fix-and-optimize
matheuristic. Its methodological basis is consistent with:

- Fischetti and Lodi, *Local Branching*, Mathematical Programming 98 (2003),
  <https://doi.org/10.1007/s10107-003-0395-5>;
- Ropke and Pisinger, *An Adaptive Large Neighborhood Search Heuristic for the
  Pickup and Delivery Problem with Time Windows*, Transportation Science 40
  (2006), <https://doi.org/10.1287/trsc.1050.0135>;
- Martin-Iradi and Ropke, *A column-generation-based matheuristic for periodic
  and symmetric train timetabling with integrated passenger routing*, European
  Journal of Operational Research 297 (2022),
  <https://doi.org/10.1016/j.ejor.2021.04.048>.

The merge/time destroy operator is specific to the ropeway topology. It is not
itself Branch-Price-and-Cut. Exact integer certification would additionally
require pricing-compatible branching at every open tree node.

## Gate

The `merge_time_corridor` root-gate variant compares equal-budget trajectories
and bound histories against Pair-only Root-CG and the existing primal channels.
Primary acceptance criteria are material validated-UB improvement at K=20 and
K=39 without any change to the certified Root-LP lower bound.
