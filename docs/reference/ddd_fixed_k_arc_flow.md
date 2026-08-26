# Complete Fixed-K DDD arc-flow solver

The arc-flow solver is the integrated exact alternative to trajectory Root-CG
for fixed starts and no waiting. It gives Gurobi every cabin path, resource
interval, and passenger flow in one MILP. A validated incumbent is a global
upper bound; `ObjBound` is a global lower bound for the same DDD tick domain.

## Two exact formulations

The public runner exposes two independently selectable formulations:

- `labeled` is the established layered cabin-by-cabin DAG. Its binary
  variables retain cabin and visit indices.
- `exact_anonymous` quotients the complete labeled DAG by the exact physical
  state and integer time tick. Cabin identity remains only on the fixed source
  token and is reconstructed after the solve.

For an exact node $v=(s,t)$, let $A^-(v)$ and $A^+(v)$ be its incoming
and outgoing arcs. The anonymous integer Movement model uses

$$
\sum_{a\in A^-(v)}x_a=\sum_{a\in A^+(v)}x_a,
\qquad
\sum_{a\in A^-(v)}x_a\le 1,
$$

plus one unit of source flow per fixed start slot, exactly $K$ terminal
arcs, and the same maximal half-open resource-interval cliques as the labeled
model. Route durations are strictly positive, so the graph is acyclic. Every
integer solution therefore decomposes deterministically into (K) physical
paths. Reattaching each source-slot label produces a complete reference
solution, which must pass the unchanged Movement and resource validator.

Passenger variables form a direct-ride multicommodity flow on those same
exact nodes. For demand group $g$,

$$
\sum_{a\in A^-(v)}f_{ga}+b_{gv}
=
\sum_{a\in A^+(v)}f_{ga}+d_{gv},
\qquad
\sum_g f_{ga}\le Qx_a.
$$

Boarding and alighting exist only on selected Stop arcs and use their exact
platform event ticks. Reachability stops at the origin or destination, so the
model preserves the current no-transfer, less-than-one-circulation ride
semantics. At an integer Movement solution, node capacity one prevents
anonymous re-pairing: exactly one physical cabin enters and leaves a used
state-time node. The formulation is consequently integer-equivalent, not a
relaxation.

Its LP relaxation is nevertheless structurally different. Fractional Movement
can split and re-pair at a node, so equality of LP bounds is not guaranteed in
general. In the first Five-Station $K=20$ gate, however, both formulations
attained the same root objective and integer optimum. The anonymous model was
slower because its root LP took substantially longer to solve, not because its
bound was weaker. It therefore remains an experimental gated alternative;
`labeled` remains the default.

## Capacity-dependent start policy

`balanced_reference` is the comparison policy for experiments. It first
computes the no-wait all-stop capacity of the deterministic circulation. If
the all-stop cycle time is `T_AS` and `h_AS` is the largest service-service
headway on a resource used by that circulation, then

```text
K_max_AS = floor(T_AS / h_AS).
```

For every `K <= K_max_AS`, All-Stop and Skip-Stop receive the identical
continuous, evenly spaced all-stop snapshot. The phase separation is
`T_AS / K`, hence every resource separation is at least `h_AS`. There is no
optimized phase offset: a common rotation of all starts changes neither
feasibility nor their relative spacings.

For `K > K_max_AS`, All-Stop is returned as analytically movement-infeasible;
Gurobi and CP-SAT are not started. Skip-Stop instead receives a compatible
service-rich reference snapshot:

1. every threshold-optimal homogeneous periodic Stop/Skip route contributes
   all of its safe phase slots;
2. two slots are incompatible when their complete resource occurrences
   overlap under the original headway semantics;
3. CP-SAT selects exactly `K` mutually compatible slots;
4. its lexicographic integer objective first maximizes the minimum number of
   stops over stations, then total stops, then a deterministic tie-break;
5. selected trajectories are relabelled canonically and converted to fixed
   starts at `t=0`.

The CP-SAT selection is only a start-layout problem. It does not select the
later passenger-optimal route. From `t=0` onward the complete arc-flow MILP
may choose every permitted Stop/Skip option.

### Boundary resource semantics

A cabin can occupy a platform, exit switch, or another headway resource across
`t=0`. Replacing the reference trajectory by only its next switch event would
lose that occupancy and admit an artificial collision. The fixed-K problem
therefore stores every reference occurrence whose protected half-open interval
reaches the boundary:

```text
[enter, clear + headway) intersects [0, H).
```

The same immutable boundary context is used in all three channels:

- conflicting time-expanded movement arcs are omitted from the MILP;
- fixed optional intervals are added to the CP-SAT seed model;
- reconstructed incumbents carry the occurrences into full reference and EAN
  validation.

This is part of the problem fingerprint. Bounds or checkpoints from another
start snapshot cannot be combined accidentally.

## Single trial

```bash
.venv/bin/python benchmarks/run_ddd_fixed_k_arc_flow.py \
  --example five_station_circle_cw_half_skip_no_wait_headway_b_v0 \
  --cabins 20 \
  --mode skip_stop \
  --start-policy balanced_reference \
  --time-limit 600 \
  --cp-seed-time-limit 60 \
  --cp-seed-workers 8 \
  --progress \
  --frontend-live
```

Add the following switch for the exact anonymous quotient:

```bash
  --formulation exact_anonymous
```

The output records the formulation, exact node count, original labeled arc
count, anonymous Movement arc count, and compression ratio. Single-run and
campaign live events carry the formulation from `trial_started`, so terminal
and frontend distinguish the two models while they are still running.

An existing Root-CG bound can be combined only after a strict problem
fingerprint check:

```bash
  --root-cg-result benchmarks/output/.../result.json
```

CP-SAT is used only for a complete movement MIP start. A CP-SAT timeout does
not stop Gurobi. The exported incumbent is independently checked with the EAN
fixed-timetable passenger optimizer.

The application reserves ten percent of the remaining post-seed budget, at
least one second and at most `seed_passenger_time_limit_seconds`, for that
independent check. If a new solver timetable cannot be validated in the
reserve, it is not exported as the validated upper bound; the last independently
validated seed remains the safe fallback. Setup, solve, and validation still
share the declared total wall-clock budget.

## Campaign

The campaign runner accepts the existing exact-K campaign JSON schema:

```bash
.venv/bin/python benchmarks/run_ddd_fixed_k_arc_flow_campaign.py \
  --config benchmarks/configs/five_station_b_balanced_fixed_k_boundary_screening.json \
  --progress \
  --frontend-live
```

The screening, regular, and headline profiles provide the total per-trial,
start-layout, and CP-seed budgets. Start-layout setup is charged to the common
wall-clock budget. All-Stop and Skip-Stop use the same physical scenario,
demand, fleet size, and—up through `K_max_AS`—the same physical snapshot.

The payload and live dashboard distinguish:

- `evenly_spaced_all_stop` for the common low-capacity snapshot;
- `periodic_balanced_reference` for the selected high-capacity Skip-Stop
  snapshot;
- `analytic_all_stop_capacity` for a high-capacity All-Stop certificate.

The output additionally records candidate and incompatibility counts, minimum
station stop count, observed maximum station service gap, construction time,
and whether CP-SAT proved its start-layout objective optimal. The service gap
is currently a diagnostic; it is not the optimized objective.

During the complete arc-flow solve, a five-second heartbeat keeps terminal and
dashboard state live even when Gurobi remains inside one long callback phase.
The reported stage distinguishes network construction, resource indexing,
model assembly, presolve, root simplex/barrier, root-node processing, and
branch-and-bound. Simplex or barrier iterates are diagnostic only: the global
lower bound changes only when Gurobi exposes a valid MIP best bound (or when a
compatible external certificate exists). Thus a live root-LP phase may
legitimately continue to display the objective floor as its certified bound.

## Scope

- exact active cabin count `K`;
- canonical rope starts (legacy option) or capacity-dependent balanced starts;
- All-Stop or Stop/Skip route domains;
- no waiting;
- integer direct passenger assignment;
- waiting-time or journey-time objective;
- eager maximal interval-clique headway rows.
- optional exact anonymous state-time quotient (`labeled` remains default).

The balanced policy optimizes only the initial reference snapshot. Reservoir
dispatch, a jointly optimized initial placement inside the passenger MILP,
transfers, and bounded waiting remain outside this solver version.

## CP-SAT movement-feasibility sweep

The separate feasibility runner constructs canonical rope starts independently
for every exact cabin count and solves only the complete movement model. It
does not build the passenger arc-flow MILP:

```bash
.venv/bin/python benchmarks/run_ddd_fixed_k_feasibility.py \
  --example five_station_circle_cw_half_skip_no_wait_headway_b_v0 \
  --k-from 23 \
  --k-to 115 \
  --mode skip_stop \
  --time-limit 600 \
  --workers 8 \
  --output benchmarks/output/ddd_fixed_k_feasibility/five_station_b_k23_115.json \
  --frontend-live
```

The default stopping rule ends the sweep at the first CP-SAT `UNKNOWN` or
proved movement infeasibility. Every completed probe is atomically
checkpointed. An interrupted run can be continued with the identical command
plus `--resume`.

Every attempt runs in a fresh spawned process by default. A CP-SAT `UNKNOWN`
that returns before 90 percent of its configured budget is classified as
`PREMATURE_UNKNOWN` and retried once in another fresh process. Checkpoints keep
all attempts, native solver status, conflicts, branches, peak worker RSS, and
the CP-SAT response summary. On resume, a frontier premature `UNKNOWN` is
retried at the same K rather than skipped.

`FEASIBLE` certifies the tested exact-K canonical-start instance. `UNKNOWN`
does not establish infeasibility. Because canonical starts are selected anew
for each K, a proved infeasible probe is not by itself a global optimized-
initial-placement capacity certificate.

`--frontend-live` publishes every CP-SAT attempt to the optimization dashboard
with its native status, runtime, conflicts, branches, memory use, and
termination reason. An older checkpoint can be imported without solving any K
again by adding `--publish-only`; the overview then reports the largest
certified feasible K and labels an unresolved frontier explicitly as unknown.
