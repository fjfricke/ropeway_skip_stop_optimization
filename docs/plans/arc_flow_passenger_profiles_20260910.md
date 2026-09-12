# Labelled Arc-Flow: isolated passenger reformulations A–D

Status: implemented; 76 tests and 24 historical fixed-plan replays passed.
The first performance campaign completed all 22 runs in 9783 seconds (2 h 43 min),
within the 180-minute envelope. Results are in
`benchmarks/output/arc_flow_passenger_campaign_20260910_v2/`, including
`comparison.md`, `analysis.json`, `summary.json`, native logs and validated
checkpoints. Legacy remains the default. The earlier preflight was stopped
before performance to keep D's summed linking bounds separate from C's
alighting strengthening; no earlier free-search campaign consumed the budget.

Final finding: D (`destination_flows`) won the K39 screening and produced
slightly better validated costs in both confirmations, but failed all predefined
effect thresholds. Against the corresponding legacy seed, cost reductions were
approximately 0.0344% and 0.0850%; gap reductions were approximately 0.724 and
0.764 percentage points. Its best K39 UB was 1260865.058744 with LB
416665.297226 (66.95% gap). K39 model size fell from 355304 to 214399 variables,
but every K39 run still reported only one search node. This is a structural
improvement and a small empirical benefit, not a demonstrated breakthrough or
a reason to change the default. A and C-alighting reached the K20 batch optimum
faster in screening; no profile improved the distributed K20 seed. No further
solver jobs were started after the campaign.

## Contract

The physical problem, fixed cabin starts, canonical ride IDs, integer passenger
semantics, time resolution and independent validators remain unchanged. The
public `--passenger-profile` options are `legacy`, `reachability`,
`ride_integrality`, `drop_redundant_links`, `alight_links`, `destination_flows`.
Non-legacy profiles require labeled movement. The frozen configuration supports
combinations internally; the first campaign tests only isolated profiles.

The normalized passenger encoding keeps the original domain, transformed
algebra, original-to-transformed variable projection, pruning evidence,
redundant-row witnesses and a model fingerprint. Seeds are mapped from
canonical rides. A positive seed on removed support is an error. Exported
assignments are reconstructed and independently validated in the original
domain, including integer counts, route stops, timing, demand and capacity.

## Formulations and proof obligations

### A: reachability

For each ride, forward reachability starts at eligible boarding arcs, backward
reachability at eligible alighting arcs. Only arcs on a board-to-alight path
survive. Conservation on the layered acyclic graph forces all removed flows
to zero, including in the LP. Empty demand rows stay; empty flow rows disappear.
An arc need not be feasible jointly with other cabins to survive this test.

### B: ride integrality

Add one nonnegative integer `q_r = sum(boarding flows)` per canonical ride;
allow its arc flows to be continuous. Keep all existing linear constraints.
For integral labeled movement, exactly one arc per layer is selected on one
source-to-terminal path. Off-path passenger variables are zero by their links;
conservation propagates `q_r` unchanged from its boarding to its alighting
layer. Hence all original ride flows are integral. This is not an assertion
that the multi-commodity passenger LP is integral: `q_r` remains integer.
Relaxing `q_r` restores the original LP projection. Relocating integrality
does not remove the LP columns themselves and need not accelerate the root LP.

### C: links

An individual `f <= Q*x` is removed only when a retained capacity row contains
that same nonnegative variable once with coefficient one and RHS `Q*x`.
Store the implying row ID. Smaller individual bounds are preserved.

Separately, add `sum(alighting flows on STOP arc a) <= Q*x_a`. At an integer
movement this follows from incoming capacity; on fractional movement it may
strengthen the LP. Alighting is before boarding; do not sum alighting and the
following onboard load into one capacity row.

### D: destination flows

Group rides by cabin and concrete alighting visit, further partitioning them
when their intermediate/alighting supports differ. Pairwise compatibility
requires identical arc supports on every layer after both boarding layers.
Keep each original boarding variable and its release test/demand debit.
Replace non-boarding variables sharing a block and movement arc with their
sum. Aggregate conservation equations by block and state-time node. A shared
variable occurs once, not once per constituent ride, in conservation and
capacity rows. Passenger cost coefficients on shared variables are identical:
zero on intermediate arcs and the same event time on the common alighting arc.
Its linking upper bound is the sum of the original linking bounds. In
particular D alone does not add a `Q*x` bound at alighting; that strengthening
belongs exclusively to C. Onboard capacity rows remain unchanged under projection.

For integral movement, all boarded amounts follow the same unique cabin path
to the block's fixed destination visit. They therefore decompose back to their
canonical rides. Different destination visits are never merged, and every
boarding belongs to an existing ride: no extra circulation or transfer is
introduced. If A is combined with D, differing remaining supports cause blocks
to split rather than weakening the physical ride contract. D alone keeps all
passenger variables integer; B+D relocates their integrality to canonical rides.
The aggregated LP may be weaker even when integer equivalence holds.

## Correctness gates

- Fully enumerated small routes and integer quantities, including microsecond
  waiting alternatives; compare all profile optima and reconstructed flows.
- LP equality for A, B and redundant-link removal; nondecreasing LB for alight
  links; evaluate D separately.
- Legacy-to-profile seed round trips, positive-pruned-seed rejection, unknown
  profile and incompatible formulation rejection, deterministic fingerprints.
- Exact service horizon and one tick after, last movement beyond the horizon,
  releases during waiting, simultaneous alighting/boarding, true bypass overtake.
- Historical odd-cycle fixed-movement assignment: integer waiting cost 12.5
  versus relaxed cost 12.25; B and D must retain the integer result. This test
  uses the historical artifact with a matching explicit movement core.
- Revalidate and fix historical K20 batch/distributed, K38 and K39 plans in
  each profile; require proven fixed-timetable passenger optimum and matching
  original-domain certificate.

## Initial campaign: hard 180-minute envelope

All solver jobs are sequential, 12 threads, eager resource cliques,
`MIPFocus=0`, automatic root method, no imported Root-CG bounds. Common
historical seeds are independently re-evaluated once per frozen case.

| Case | Profiles | Budget per process |
|---|---:|---:|
| K20 batch, 1280 people, all-stop seed 635519.998080 | six | 60 s |
| K20 diffuse distributed, 1280 people, original follow-up demand | six | 120 s |
| K39 batch, fixed original balanced starts, seed 1262099.935264 | six | 900 s |
| K39 best new profile vs legacy, seeds 1 and 2 | four runs | 900 s |

Nominal total is 168 minutes, leaving 12 minutes for common preparation and
closure. Each process budget includes its model build and validation. Parent
process termination enforces the envelope and cleans up descendants. No run
starts without its full budget plus a closure reserve. Failed/timed-out
processes are not infeasibility or optimality certificates. Native checkpoints
are saved on first native solution and genuine subsequent improvements.

Record original/algebra variable counts, row families and nonzeros, exposed
presolve information, root-LP time from native logs, nodes, peak RSS, separate
timings and validated UB/LB curves. Seed adoption is not improvement.
Run workers from frozen source copies; keep versions, hashes, domains and
seeds beside the results. Historical files are read only.

Select the new K39 profile by UB, LB, then first improvement time. A confirmed
recommendation needs both additional seeds to show 0.1% lower cost, one
percentage point smaller gap without worse UB, or 20% earlier attainment of
legacy's final UB and LB without worse endpoints. A UB gain with a weaker LB
is explicitly a primal-only benefit. Size savings alone are not speedups.
No standard switch, combination campaign, larger waiting network or longer
run follows automatically.

## Literature and limits of attribution

This implementation is a ropeway-specific synthesis, not reproduction of a
single published ropeway formulation. The B proof and C witnesses above are
derived from the actual labeled movement and passenger equations.

- de Lima et al., *Arc Flow Formulations Based on Dynamic Programming:
  Theoretical Foundations and Applications*, EJOR 296 (2022), 3–21:
  https://doi.org/10.1016/j.ejor.2021.04.024 ; open text
  https://arxiv.org/html/2010.00558v2 . DP-network/flow foundations and the
  size-versus-strength tradeoff; no universal guarantee for our coupled model.
- Kazemi et al., *New commodity representations for multicommodity network
  flow problems*, COR: https://doi.org/10.1016/j.cor.2021.105505 ;
  https://arxiv.org/abs/2101.03707 . Motivation for partial commodity aggregation;
  their empirical results do not establish speedups for our D encoding.
- Boland et al. (2017), https://doi.org/10.1287/opre.2017.1624 ;
  Marshall et al., https://doi.org/10.1287/trsc.2020.0994 . Relevant to a later
  adaptive waiting network, not implemented by this package.
- Van Dyk and Koenemann, https://arxiv.org/abs/2303.01419 . Hard storage
  constraints require care when deriving DDD relaxations for occupied resources.

Earlier complete K20 waiting expansion exhausted ~829 seconds building its
network without reaching the solve. Historical K39 no-wait root processing
and failed Benders gates motivate reducing the existing passenger matrix
before adding a new time representation.
