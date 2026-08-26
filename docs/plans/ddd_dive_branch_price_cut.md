# Certified trajectory Dive-and-Cut-and-Price and Branch-Price-and-Cut

Status: **remaining gated work after implementation of typed service/route
branch domains and bounded service-decision dives**

Implemented behavior and the first Five-Station $K=20$ gate are maintained in
[`../reference/ddd_trajectory_branching_and_diving.md`](../reference/ddd_trajectory_branching_and_diving.md).
This plan now governs the remaining cabin/corridor LNS, conflict-cut, and
conditional complete-tree work. The implemented boundary-aware
resource-window gate is documented in
[`../reference/ddd_trajectory_branching_and_diving.md`](../reference/ddd_trajectory_branching_and_diving.md).

## Decision summary

Continue the existing exact fixed-$K$ trajectory Root-CG in two gated stages:

1. extend the implemented bounded physical dive with a pragmatic
   **Dive-and-Cut-and-Price** LNS that keeps the certified root lower bound and
   searches aggressively for validated integer Skip-Stop schedules;
2. only if a material root integrality gap remains, an exact
   **Branch-Price-and-Cut** tree that performs certified pricing and conflict
   separation at every open node.

The first experiment campaign remains fixed-$K$, fixed canonical starts, and
No-Wait. All-Stop and Skip-Stop use the same physical scenario, demand,
objective, horizon, and initial state whenever both modes are feasible. Every
result carries the complete `DddFixedKTrajectoryProblem` fingerprint so that
bounds from different formulations can never be combined accidentally.

The method has two independent certificate channels:

$$
LB_K
=
\max\{LB_K^{\mathrm{DDD}},LB_K^{\mathrm{rootCG}},LB_K^{\mathrm{tree}}\}
\le z_K^*
\le
UB_K,
$$

where every upper bound is a completely reconstructed and independently
validated movement and passenger schedule. Restricted pools, heuristic
pricing, dives, and LNS neighborhoods may improve $UB_K$ but may not claim a
global lower bound.

This plan extends
[`ddd_trajectory_column_generation.md`](ddd_trajectory_column_generation.md)
and uses the campaign/certificate contract from
[`ddd_fixed_k_certified_bounds.md`](ddd_fixed_k_certified_bounds.md). It does
not revive the standard Passenger Benders path rejected by
[`ddd_arc_flow_passenger_benders.md`](ddd_arc_flow_passenger_benders.md).

## Scientific motivation

Branch-and-Price is the established exact extension of Dantzig--Wolfe column
generation: the LP relaxation at every branch-and-bound node is solved over an
implicit column universe by pricing. The classical reference explains why
path/configuration reformulations can provide stronger relaxations and remove
symmetry in large routing and scheduling models:
[Barnhart et al. (1998)](https://doi.org/10.1287/opre.46.3.316).

The architecture is established in closely related public-transport fields:

- real railway rolling-stock circulation:
  [Peeters and Kroon (2008)](https://doi.org/10.1016/j.cor.2006.03.019);
- real train-unit scheduling with custom branch rules and column inheritance:
  [Lin and Kwan (2016)](https://doi.org/10.1016/j.trb.2016.09.007);
- train timetabling on a time-space network:
  [He et al. (2014)](https://doi.org/10.1155/2014/641562).

The closest methodological template for the present integrated operational and
Passenger problem is the periodic train-timetabling matheuristic of
[Martin-Iradi and Ropke](https://arxiv.org/abs/1912.06941). It combines line-path
column generation, delayed conflict separation, Passenger Benders cuts,
diving, and large-neighborhood search. The transferable lesson is to combine a
strong root relaxation with a dedicated primal mechanism instead of expecting
root column generation alone to construct good integer schedules.

This literature validates the method family, not its runtime on the present
ropeway problem. Continuous event times, dense merge conflicts, per-rotation
Stop/Skip choices, and the current direct-ride Passenger model make the exact
pricing and branching problems project-specific. Each implementation stage is
therefore guarded by quantitative acceptance gates.

## Mathematical master

For every cabin $c\in C$, let $P_c$ denote the complete finite set of
whole-horizon trajectories admitted by the declared start, route, waiting, and
horizon domains. A trajectory fixes all movement decisions of that cabin but
does not impose a repeated rotation template. Let

$$
\lambda_{cp}\in\{0,1\}
$$

select trajectory $p\in P_c$. The configuration master contains

$$
\sum_{p\in P_c}\lambda_{cp}=1
\qquad \forall c\in C,
$$

the current Passenger-flow/load model, extensible resource rows, and separated
trajectory incompatibilities. Its LP relaxation uses
$0\le\lambda_{cp}\le1$.

For current dual vector $\pi$, exact pricing for cabin $c$ computes

$$
\rho_c^*
=
\min_{p\in P_c}
\left(c_{cp}-\pi^\top a_{cp}\right).
$$

If all omitted-column pricing problems are exact or have certified lower
bounds $\underline\rho_c$, then

$$
LB
=
z_{\mathrm{RMP}}
+
\sum_{c\in C}\min\{0,\underline\rho_c\}
$$

is globally valid for that node. Root convergence may be declared only when
every required pricing universe is certified nonnegative. The existing
pair-row exclusion semantics remain mandatory: pair-specific rows name only
already generated trajectory IDs, while extensible resource rows must expose a
physical membership predicate to pricing.

## Why branching is required

An optimal root solution can mix complete trajectories, for example

$$
\lambda_{c,p^{\mathrm{stop}}}
=
\lambda_{c,p^{\mathrm{skip}}}
=\tfrac12.
$$

The root lower bound remains valid, but the mixture is not a physical cabin
schedule. Branching partitions the complete trajectory universe until an
integer selection is obtained. At every child node, column generation must be
rerun because columns with negative reduced cost can exist there even if they
did not exist at the parent.

Branching directly on a generated $\lambda_{cp}$ is not the default: an
equivalent omitted trajectory can evade the decision and cabin-label symmetry
can create an unnecessarily large tree. Version 1 supports decisions in the
original movement domain that can be imposed inside exact pricing:

1. `SERVICE_DECISION(c, visit)`: Stop versus Skip;
2. `MOVEMENT_ARC(c, arc_id)`: use versus avoid a stable physical/DDD arc;
3. `EVENT_THRESHOLD(c, event, tick)`: event time at most versus greater than a
   canonical integer tick;
4. later, `RESOURCE_PRECEDENCE(c1, c2, resource_window)`: one cabin before the
   other when the pricing interface can propagate the decision exactly.

Branch candidates are scored by fractionality, expected balance, pricing
compatibility, and physical provenance. Stop/Skip branching is the first
production rule; event thresholds are used only when movement decisions are
already integral but time remains fractional. Every branch restriction has a
typed representation, deterministic fingerprint, JSON serialization, and an
explicit method that applies it both to existing columns and to pricing.

## Conflict cuts

Generated trajectories induce a conflict graph $G=(V,E)$: a vertex is a
trajectory choice and an edge links choices that cannot coexist. Pair rows

$$
\lambda_i+\lambda_j\le1
$$

are exact but can be weak. The first strengthening family is a deterministic
maximal-clique separator:

$$
\sum_{i\in Q}\lambda_i\le1
\qquad \text{for every valid clique }Q.
$$

Cliques must be justified by one common physical resource-time occupancy or by
pairwise conflicts with a complete validation certificate. Greedy clique
discovery may choose which valid cuts to add, but cut validity may not depend
on the heuristic. The separator prioritizes violation, clique size, and stable
IDs and limits each batch.

The second optional family is odd-cycle strengthening for induced conflict
subgraphs:

$$
\sum_{i\in W}\lambda_i
\le
\frac{|W|-1}{2}
$$

for an odd cycle $W$. It is enabled only after clique cuts show measurable
root benefit. General resource-time cover cuts are a later research tranche;
they require exact capacity semantics and a pricing-compatible coefficient
oracle.

Cuts are separated at the root and at branch nodes. A cut may contribute to a
certificate only if it is globally valid within the node's branch domain and
all future columns have a defined coefficient predicate. Cuts naming only a
finite generated set are local pool cuts and cannot be used to close a node
against omitted columns.

### Gate result and prerequisite for tree search

Resource-window clique rows and their fixed-boundary pricing coefficients are
implemented and exact. The high-density K=39 gate showed that strong clique
rows can leave the RMP at its single compatible seed while independent pricing
returns mutually incompatible negative-reduced-cost columns. In that state the
global pricing correction remains at the objective floor even though the RMP
itself is integral. A Branch-Price-and-Cut tree would replicate this expensive
root pathology at its nodes.

Before Stage C, one of the following must pass a fixed-budget root gate:

1. native solution-pool/k-best pricing that returns several distinct negative
   columns per cabin in one pricing solve;
2. dual stabilization plus multi-column pricing;
3. a bounded coordinated multi-cabin pricing/repair subproblem that returns a
   jointly compatible negative batch without altering proof pricing.

The accepted variant must move both the K=39 restricted LP and its certified
lower bound while preserving exhaustive reduced-cost equality on tiny cases.
Until then, resource cliques remain an optional exact root strengthening, not
the default conflict mode and not a basis for a complete tree.

The first two variants did not pass that gate: three sequential diverse
columns per cabin still left the K=39 clique RMP at its seed. A coordinated
CP-SAT package generator did move the RMP and improved the validated upper
bound by roughly 4.7 percent within five minutes, but the clique-corrected
lower bound remained zero. Consequently the production candidate is now a
hybrid: pair-only exact Root-CG remains the proof engine, while periodically
generated complete CP packages are a primal-only accelerator. A full tree is
still conditional on a nonzero, competitive root certificate under this
hybrid.

## Remaining Stage A: certified root diagnostics

Before adding tree search, consolidate one immutable root result containing:

- problem and column-universe fingerprint;
- complete initial column provenance;
- every RMP objective and corrected lower bound;
- exact/certified pricing status per cabin and tier;
- separated conflict rows and their coefficient scope;
- final fractional trajectory, Stop/Skip, arc, event-time, Passenger, and
  resource-load statistics;
- best validated integer solution and its provenance.

Cross-check tiny instances against exhaustive trajectory enumeration and the
complete arc-flow LP/MIP. For the Five-Station $K=20$ calibration instance,
the first gate is reproduction of a root bound close to the previously
observed $522{,}335$ under exactly the same fingerprint as the known optimum
near $525{,}731$. No historical number may be combined until this equivalence
check passes.

## Remaining Stage B: Dive-and-Cut-and-Price LNS

A basic service-decision dive is implemented and did not improve the K=20
All-Stop seed. The remaining Stage-B work is therefore the neighborhood layer;
the dive still does not claim that unexplored sibling domains were proved or
searched.

The primal layer performs trajectory LNS/fix-and-optimize:

- fix all but a selected cabin cohort;
- or release trajectories intersecting one station/resource-time corridor;
- or release one visit/rotation band across all cabins;
- solve the resulting restricted exact master;
- request heuristic pricing only inside the released neighborhood;
- import every new trajectory into the persistent global pool;
- accept only independently validated improving schedules.

Neighborhoods begin with 3--6 cabins and grow after repeated stagnation. Root
proof pricing and heuristic neighborhood pricing remain separate services and
metrics. A heuristic negative column may enter the pool, but a failed
heuristic search never proves nonnegativity.

The Stage-B output is a valid anytime interval

$$
LB^{\mathrm{rootCG}}\le z^*\le UB^{\mathrm{dive/LNS}}.
$$

It does not claim integer optimality unless both values meet within tolerance.

## Stage C: limited tree pilot

Implement an explicit deterministic node manager rather than solver callbacks
first. Each `DddTrajectoryBranchNode` stores only:

- parent ID and branch decision;
- node-local bound/status;
- references to inherited global columns and cuts;
- node-local columns/cuts;
- warm-start basis and incumbent hints when compatible;
- unresolved pricing certificates.

The global pool owns immutable trajectories and globally valid cuts. Child
nodes inherit them by reference and filter columns against their branch
domain. New columns are globally deduplicated and become visible to other
compatible nodes. Node selection initially uses best bound with deterministic
depth tie-breaking; periodic diving supplies incumbents.

The pilot explores at most a configured number of nodes and supports only
Stop/Skip and stable movement-arc branching. It must demonstrate:

- monotone global tree lower bound;
- correct sibling-domain partition;
- exact pricing under every branch restriction;
- pruning only from certified infeasibility or `node_LB >= global_UB`;
- checkpoint/resume with identical node order and bounds.

## Stage D: full Branch-Price-and-Cut

Proceed only if the limited tree pilot materially closes a real integrality
gap. The complete method adds:

- event-threshold and, if justified, resource-precedence branching;
- strong/reliability branching based on cheap restricted solves;
- global and node-local clique/odd-cycle separation;
- reduced-cost fixing under a valid incumbent;
- column inheritance and pool aging without deleting certificate provenance;
- parallel pricing across cabins, but deterministic result integration;
- exact final pricing before closing any node;
- interruption-safe global gap and frontier export.

The global lower bound is the minimum certified bound over all open nodes. If
there are no open nodes and a validated incumbent exists, the result is
integer optimal. A time-limited result exports

$$
\min_{n\in\mathcal O}LB_n
\le z^*\le UB
$$

with the complete open-node frontier and certificate fingerprints.

## Passenger integration boundary

Passenger Assignment remains explicit in the trajectory master for generated
ride options. Because direct-ride capacity coupling is not generally totally
unimodular in this repository, Passenger LP values cannot silently become
integer upper bounds. The rules are:

- Passenger LP belongs to node lower bounds;
- a complete Passenger IP or independently exact Passenger evaluator belongs
  to upper bounds;
- adding a trajectory may introduce ride/load columns and therefore requires
  the existing exact row-and-column accounting;
- no Passenger Benders cut is required for Stage B;
- Pareto/core-point Passenger Benders cuts remain an isolated experiment and
  may be imported only after exhaustive validity tests and measurable root
  improvement.

If explicit Passenger rows dominate node solution time, test partial embedding
or aggregated Passenger cuts against the complete root LP as a separate
formulation experiment. Do not weaken the production certificate merely to
make node solves faster.

## OO design

Add a thin tree/primal layer around the current trajectory components instead
of duplicating pricing or master construction:

- `DddTrajectoryBranchDecision`: immutable tagged union with column filtering
  and pricing-domain application;
- `DddTrajectoryBranchDomain`: canonical conjunction of decisions with
  contradiction detection and fingerprinting;
- `DddTrajectoryBranchCandidateEvaluator`: extracts and scores fractional
  physical decisions;
- `DddTrajectoryConflictCut` and `DddTrajectoryConflictCutPool`: immutable
  algebra, scope, provenance, deduplication, and serialization;
- `DddTrajectoryCliqueSeparator`: exact-validity conflict-graph separator;
- `DddTrajectoryDiveCoordinator`: diversified bounded dives and schedule
  validation;
- `DddTrajectoryNeighborhoodGenerator`: cabin, corridor, and rotation-band
  neighborhoods;
- `DddTrajectoryBranchNode` and `DddTrajectoryNodeQueue`: explicit tree state
  and deterministic selection;
- `DddTrajectoryBranchPriceCutSolver`: orchestration only; delegates RMP,
  exact pricing, Passenger evaluation, conflict separation, and validation;
- `DddTrajectoryAnytimeCertificate`: root/tree LB, validated UB, policy
  comparison interval, and full provenance.

`DddTrajectoryExactRootColumnGenerationSolver` remains the owner of root CG.
Extract a reusable node-CG service only when Stage C starts, preserving the
existing root behavior and regression corpus. The current exact pricing
oracles remain the single source of reduced-cost certificates and gain typed
branch-domain input; no second pricing implementation is introduced.

## Policy and fleet-size certificates

For minimization, policy intervals are

$$
LB_{P,K}\le z_{P,K}^*\le UB_{P,K},
\qquad P\in\{AS,SS\}.
$$

The certified Skip-Stop improvement interval is

$$
LB(\Delta_K)=LB_{AS,K}-UB_{SS,K},
$$

$$
UB(\Delta_K)=UB_{AS,K}-LB_{SS,K}.
$$

Thus `LB(Delta_K) > 0` proves a minimum Skip-Stop benefit, while
`UB(Delta_K) <= epsilon` proves that no material benefit remains under the
declared instance semantics.

For a fleet availability limit, derive rather than re-solve

$$
z_P^{\le K}=\min_{1\le k\le K}z_{P,k}^{=k},
$$

with

$$
LB_P^{\le K}=\min_{k\le K}LB_{P,k},
\qquad
UB_P^{\le K}=\min_{k\le K}UB_{P,k}.
$$

Above the analytic All-Stop capacity $K_{\max}^{AS}$, report two distinct
claims:

1. a capacity-extension certificate: All-Stop movement infeasible and a
   validated Skip-Stop movement schedule feasible;
2. a demand-benefit interval comparing
   $z_{AS}^{\le K_{\max}^{AS}}$ with $z_{SS}^{\le K}$.

Exact-$K$ results with different start policies are never mixed without an
explicit policy label and fingerprint.

## Progress and outputs

Terminal and frontend progress expose without jitter:

- global/root/tree lower bound, validated upper bound, absolute/relative gap;
- certified Skip-Stop improvement interval when the matching policy result is
  available;
- current phase: root CG, cut separation, dive, neighborhood, node CG, or
  validation;
- root/node ID, depth, open nodes, processed nodes, and best-bound frontier;
- columns generated/reused/rejected, conflict pairs, cliques, and active rows;
- exact versus heuristic pricing counts and remaining pricing domains;
- fractionality by trajectory, Stop/Skip, arc, time, and Passenger variables;
- incumbent provenance and last improvement age;
- wall-clock budget and checkpoint sequence.

Every output distinguishes `ROOT_LP_CERTIFIED`, `VALIDATED_INCUMBENT`,
`TREE_GAP_CERTIFIED`, `INTEGER_OPTIMAL`, and heuristic-only progress.

## Automated tests

### Branch-domain correctness

- every generated column satisfies all active branch decisions;
- parent columns are filtered identically to newly priced columns;
- Stop/Skip, arc, and event-threshold siblings are disjoint and cover the
  parent domain;
- contradictory decisions close a node without pricing;
- domain fingerprints and JSON round-trips are deterministic.

### Pricing and bounds

- randomized tiny branch domains compare exact pricing with exhaustive
  trajectory enumeration;
- pricing-corrected node bounds never exceed exhaustive node optima;
- heuristic pricing cannot close a node;
- interrupted pricing uses only certified objective bounds;
- global tree LB is monotone and equals the minimum certified open-node bound.

### Conflict cuts

- clique and odd-cycle cuts are valid on exhaustive conflict graphs;
- generated and future columns receive identical coefficients from the
  physical membership predicate;
- duplicate and dominated cuts are rejected deterministically;
- pool-local rows are excluded from global node certificates.

### Primal validity

- every dive/LNS incumbent passes complete movement, headway, horizon,
  fixed-$K$, and Passenger validation;
- a restricted-pool objective never becomes a global lower bound;
- Passenger LP fractionality cannot produce an upper bound;
- incumbent inheritance respects child branch domains.

### End-to-end references

- tiny One-/Three-Station cases match exhaustive configuration enumeration;
- Five-Station $K=20$ matches the complete arc-flow MIP and LP under one
  fingerprint;
- restarting from a checkpoint reproduces node order, columns, cuts, bounds,
  and status;
- deliberate certificate corruption terminates as
  `INTERNAL_CERTIFICATE_ERROR`.

## Experimental gates

### Gate 1: root equivalence

On fixed canonical No-Wait $K=20$, reproduce the known integer objective and a
Root-CG gap below one percent under the same fingerprint. Compare the complete
arc-flow LP, exhaustive/reference trajectory LP where available, and Root-CG
bound.

**Reject tree work** if exact pricing cannot reproduce the reference root
relaxation or if pair/resource rows lack future-column coefficient semantics.

### Gate 2: primal value

Compare on $K=20$ and $K=38$:

- All-Stop seed only;
- restricted MIP from the root pool;
- diversified diving;
- diving plus cabin/corridor LNS.

Measure time to first genuine Skip-Stop improvement, best validated UB, root
LB, and certificate gap.

**Accept Stage B** if it lowers the Skip-Stop UB materially relative to the
All-Stop seed on at least one demand scenario while preserving all
certificates.

The first K=20 service-dive-only run failed this primal gate: it retained
$UB=635{,}519.998$ while the certified Root-CG lower bound reached
$523{,}756.726$. The next matched run must import or reconstruct the known
complete arc-flow incumbent near $525{,}730.908$ and then test cabin/corridor
LNS. Full tree work remains rejected until that primal path is established.

The stronger K=39 gate reinforces this decision. Boundary-aware Root-CG
certified the full root LP in about 340 seconds, but both its restricted MIP
and a separate 600-second complete arc-flow run retained only the periodic
seed. The complete model remained at its root node with 312,833 Passenger
variables. The next implementation tranche must therefore keep Passenger
evaluation exact but outside the movement-neighborhood search core; simply
extending the complete Branch-and-Bound or Branch-Price tree is not accepted.

### Gate 3: cut value

Run matched Root-CG experiments with pair rows only and with clique
separation. Record root objective, rounds, pricing time, master size,
fractionality, and peak RSS.

**Retain clique cuts** only if they improve the root bound or reduce
fractionality/node projections enough to offset their solve and pricing cost.

### Gate 4: limited branching

On cases with a measured nonzero root integrality gap, compare root-only,
diving, and at most 10/50/200 certified nodes. Record global LB movement, UB
movement, node throughput, pricing tailing-off, and column reuse.

**Proceed to full Branch-Price-and-Cut** only if certified branching closes a
material portion of the remaining gap that diving alone cannot close. If the
root gap is already below the thesis tolerance, keep the root certificate and
spend computation on primal LNS and the cross-$K$/demand campaign instead.

## Initial campaign

1. Five-Station Architecture B, canonical fixed starts, No-Wait, $K=20$:
   formulation/fingerprint calibration and exact reference.
2. Same topology and semantics, $K=38$: one-hour root and primal comparison.
3. Around the All-Stop frontier:
   $K_{\max}^{AS}-1$, $K_{\max}^{AS}$, and
   $K_{\max}^{AS}+1$ where the declared Skip-Stop start builder has capacity.
4. Demand profiles: low/medium/high scale, balanced versus directional, and
   uniform versus peaked arrivals, always derived from versioned base demand.
5. Only after stable certificates, extend to the planned Six-/Fifteen-Station
   network cases and bounded Waiting.

The campaign exports exact-$K$ policy intervals, derived available-fleet
envelopes, capacity-extension certificates, and the Skip-Stop improvement
interval rather than ranking policies by incumbents alone.

## Alternatives and stopping rules

- **Standard Passenger Branch-and-Benders:** parked. Reconsider only if a
  Pareto/core-point or problem-specific cut family raises the calibrated
  $K=20$ root bound materially before branching.
- **Lamorgese--Mannino noncompact/alternative graph:** retain as a separate
  movement/headway strengthening experiment, especially if Big-$M$ timing or
  precedence fractionality dominates after trajectory selection. See
  [Lamorgese and Mannino (2019)](https://doi.org/10.1287/opre.2018.1837).
- **Logic-based Benders with CP-SAT:** use for complete movement seeds and
  explainable infeasibility cores; do not use as the Passenger lower-bound
  channel without strong globally valid master cuts.
- **Lagrangian relaxation:** optional fast/parallel lower-bound benchmark;
  production use requires evidence that it competes with Root-CG.
- **CBS/MAPF conflict search:** optional feasibility and repair heuristic for
  sparse merge conflicts; it does not replace the Passenger certificate.
- **Pure ALNS/genetic search:** may improve incumbents but remains a primal-only
  supplement.

Stop exact tree development if pricing at branch nodes becomes the dominant
cost without moving the global lower bound, or if Root-CG plus validated LNS
already produces the required policy-improvement intervals. The thesis needs
defensible gaps and policy conclusions, not integer optimality at every cost.

## Assumptions

- The first implementation is exact-$K$, canonical fixed start, finite horizon,
  one deterministic circulation pattern, and No-Wait.
- The trajectory universe permits different Stop/Skip choices in every
  rotation; no periodic trajectory template is imposed.
- Passenger transfers, dynamic routing/turnbacks, continuous Waiting, and OIP
  branching are later extensions.
- All globally claimed bounds use exact or certified pricing and globally
  valid cuts over the complete declared column universe.
- Solver callbacks are not required for the first explicit tree pilot.
- Reproducible experiments use one shared wall-clock budget including master,
  pricing, cuts, validation, Passenger evaluation, and checkpointing.
