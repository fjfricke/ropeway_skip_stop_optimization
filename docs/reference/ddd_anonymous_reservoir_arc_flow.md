# Anonymous Reservoir Arc-Flow

Status: **implemented experimental production path**

## Research question

The formulation compares a conventional equally spaced all-stop service with
a skip-stop service under the same physical network, demand, service interval,
and available fleet cap. Cabins are interchangeable. They start outside the
line, enter through an ideal boundary reservoir during warm-up, and return to
the same reservoir after passenger service.

The first campaign fixes

\[
\bar K=\left\lceil1.5K_{\max}^{AS}\right\rceil
=\lceil1.5\cdot38\rceil=57,
\]

with warm-up \(W=300\) s, service \(T=1200\) s, and recovery
\(R=300\) s. The model is exact for its documented finite dispatch and waiting
grids; it is not a certificate for arbitrary continuous dispatch times.

## State-time network

Let \(N\) be physical entry/merge states crossed with exact integer
microsecond timestamps. The arc set is partitioned into dispatch arcs
\(A^D\), physical movement arcs \(A^M\), and recovery arcs \(A^R\).
Dispatch is allowed only in \([0,W)\), passenger service in \([W,W+T]\), and
recovery only in \([W+T,W+T+R]\).

Dispatch timestamps use a one-second grid plus the exact all-stop anchors.
Movement durations and headway intervals retain the existing microsecond
representation. Stop and skip arcs are generated during warm-up and service.
Recovery is no-wait. It allows stop or skip because a hard simultaneous switch
to skip-only is not closure-safe: a follower that skips can catch a leader
whose final stop began shortly before \(W+T\). Allowing the all-stop clearing
continuation is necessary for the inclusion
\(\mathcal F_{AS}\subseteq\mathcal F_{SS}\).

For every arc \(a\),

\[
x_a\in\{0,1\}
\]

indicates that one anonymous cabin uses it. At every physical state-time node
\(n\),

\[
\sum_{a\in\delta^-(n)}x_a
=
\sum_{a\in\delta^+(n)}x_a,
\qquad
\sum_{a\in\delta^-(n)}x_a\le1.
\]

The second inequality is valid because two cabins at the same physical state
and exact time would violate positive headway. Fleet conservation is

\[
\sum_{a\in A^D}x_a
=
\sum_{a\in A^R}x_a
\le \bar K.
\]

There is no dispatch or recovery during service, so the dispatch count equals
both the used fleet and peak active fleet in version 1. Unused cabins remain
in the reservoir and consume no physical resource.

## Physical resources

Each movement arc induces half-open protected intervals

\[
[t^{enter}_{ar},t^{clear}_{ar}+h_{ar})
\]

on every used physical resource \(r\). The interval graph is perfect; capacity
one is represented exactly by one inequality for every maximal interval
clique \(Q\):

\[
\sum_a m_{aQ}x_a\le1.
\]

The builder enumerates these cliques with a deterministic interval sweep. A
candidate active set after a start time is non-maximal precisely when another
interval starts before the earliest active interval ends. This avoids the
quadratic subset test used by the older generic builder.

## Passenger flow

For every demand group \(g\), movement arc \(a\), and valid direct-ride
position, \(y_{ga}\) is the onboard flow. Boarding \(b_{ga}\), alighting
\(l_{ga}\), and unserved demand \(u_g\) are integer. Passenger conservation is

\[
\sum_{a\in\delta^-(n)}y_{ga}+\sum_{a\in B_g(n)}b_{ga}
=
\sum_{a\in\delta^+(n)}y_{ga}+\sum_{a\in L_g(n)}l_{ga}.
\]

Demand and capacity are

\[
u_g+\sum_a b_{ga}=q_g,
\qquad
\sum_a b_{ga}=\sum_a l_{ga},
\qquad
\sum_g y_{ga}\le Cx_a.
\]

Boarding before release and alighting after service are omitted from the
domain. Direct-ride reachability stops at the first destination occurrence and
does not permit transfers.

## Lexicographic certificate

The primary problem minimizes

\[
U=\sum_g u_g.
\]

At any interruption Gurobi provides a certified primary lower bound
\(LB_U\). The best independently validated schedule, including the all-stop
reference, provides \(UB_U\). Hence the number served lies in

\[
[Q-UB_U,\;Q-LB_U].
\]

Only after \(U^*\) is proven is \(U=U^*\) fixed and total passenger journey
time minimized. A secondary result is never started from a merely incumbent
primary service level.

The all-stop reference is inserted as a complete movement and passenger MIP
start. Therefore the reported skip-stop upper bound must satisfy

\[
UB_U^{SS}\le U^{AS}.
\]

Paths and cabin IDs are reconstructed only after an integer solve by sorting
dispatches by time and arc ID. Every dispatched path must terminate in exactly
one recovery arc.

## Reproducibility and checkpoints

Problem and network fingerprints cover topology, resources, demands, phase
lengths, fleet cap, and finite timing policies. Same-model resume requires both
fingerprints. A no-wait incumbent may be imported into the richer waiting
network only after metadata, arc existence, flow, recovery, fleet, and resource
cliques have been revalidated.

The runner writes atomic results and validated incumbent checkpoints. It does
not claim to resume Gurobi's branch-and-bound tree.

## Current scope

- one directed circulation pattern;
- one ideal entry/exit boundary state;
- direct-ride passengers without transfers;
- finite dispatch and bounded-wait grids;
- no dispatch or recovery during passenger service;
- fixed available fleet, endogenous used fleet.

The five-station integration gate revealed that the newly reconstructed
all-stop boundary schedule can serve all 2,560 passengers in the current full
demand fixture. The earlier value 2,464 belonged to the previous fixed-horizon
trajectory experiment and must not be reused as an unserved-demand baseline
without reproducing its boundary semantics. Consequently, a throughput
headline needs either a higher demand scale or a separate operational service
constraint; journey-time comparison remains meaningful at equal served demand.
