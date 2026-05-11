# MILP v0 Sparse Optimization

Status: **implemented v1**

## Goal

Add an optional sparse variable strategy that makes the existing MILP v0 formulation significantly smaller without changing its semantics.

The model should still use:

```text
x[c,t,v] = cabin c occupies node v at time t
y[c,t,a] = cabin c uses arc a from t to t+1
```

but variables and constraints should only be created where they can matter when sparse mode is enabled.

The current dense/naive formulation remains available as the baseline implementation.

## Scope

This plan covers four concrete optimization steps:

1. Add variable strategy selection while keeping dense as baseline.
2. Sparse reachability for variables.
3. Flow constraints only on relevant nodes.
4. Conflict constraints only when relevant.

Same-node occupancy unification remains desirable, but should not be required for the first sparse upgrade. Initially, same-node occupancy can stay as a solver-internal constraint mechanism that is generated sparsely.

Out of scope:

- arc-only formulation
- path-based formulation
- rolling horizon
- passenger-aware queuing-time MILP
- Gurobi parameter tuning
- objective changes

## 1. Variable Strategy Selection

Add an explicit variable strategy to `MilpV0Config`:

```python
class MilpV0VariableStrategy(Enum):
    DENSE = "dense"
    SPARSE_REACHABILITY = "sparse_reachability"
```

```python
@dataclass(frozen=True)
class MilpV0Config:
    horizon_steps: int
    fixed_starts: tuple[FixedCabinStart, ...]
    allow_move_arcs: bool = True
    allow_wait_arcs: bool = True
    allow_skip_arcs: bool = True
    variable_strategy: MilpV0VariableStrategy = MilpV0VariableStrategy.DENSE
```

Default:

```text
DENSE
```

so current solver behavior remains unchanged unless sparse mode is explicitly enabled.

Both dense and sparse modes should feed a common solver path through the same variable-index interface.

Recommended shared index:

```python
@dataclass(frozen=True)
class MilpV0VariableIndex:
    x_keys: tuple[tuple[int, int, str], ...]
    y_keys: tuple[tuple[int, int, str], ...]
    node_ids_by_cabin_time: dict[tuple[int, int], tuple[str, ...]]
    arc_ids_by_cabin_time: dict[tuple[int, int], tuple[str, ...]]
    out_arc_ids_by_cabin_time_node: dict[tuple[int, int, str], tuple[str, ...]]
    in_arc_ids_by_cabin_time_node: dict[tuple[int, int, str], tuple[str, ...]]
```

Builders:

```python
build_dense_milp_v0_variable_index(...)
build_sparse_reachability_milp_v0_variable_index(...)
```

The solver should not have separate dense and sparse implementations. It should build the chosen index, then create variables and constraints from that index.

## 2. Sparse Reachability

Current naive model creates:

```text
x[c,t,v] for all c, t, v
y[c,t,a] for all c, t, a
```

Sparse model should create:

```text
x[c,t,v] only if node v is reachable by cabin c at time t
y[c,t,a] only if arc a can be used by cabin c at time t
```

Reachability is computed from:

- fixed start node of each cabin
- directed allowed arcs
- horizon `H`

Suggested model:

```python
@dataclass(frozen=True)
class MilpV0VariableIndex:
    x_keys: tuple[tuple[int, int, str], ...]
    y_keys: tuple[tuple[int, int, str], ...]
    node_ids_by_cabin_time: dict[tuple[int, int], tuple[str, ...]]
    arc_ids_by_cabin_time: dict[tuple[int, int], tuple[str, ...]]
    out_arc_ids_by_cabin_time_node: dict[tuple[int, int, str], tuple[str, ...]]
    in_arc_ids_by_cabin_time_node: dict[tuple[int, int, str], tuple[str, ...]]
```

Where:

```text
x_keys = (cabin_id, time_step, node_id)
y_keys = (cabin_id, time_step, arc_id)
```

Build rule:

```text
reachable[c,0] = {start_node(c)}
reachable[c,t+1] = {to(a) for v in reachable[c,t], a in A_out(v)}
```

Wait arcs are included if allowed by the arc policy.

Dense mode can also use the same index type:

```text
node_ids_by_cabin_time[(c,t)] = all nodes
out_arc_ids_by_cabin_time_node[(c,t,v)] = allowed outgoing arcs from v
in_arc_ids_by_cabin_time_node[(c,t,v)] = allowed incoming arcs to v
```

## 3. Flow Constraints Only On Relevant Nodes

Current model creates outgoing and incoming flow constraints for all:

```text
c, t, v
```

Sparse model should keep the position-assignment constraint, but only over reachable nodes:

```text
sum_{v in reachable[c,t]} x[c,t,v] = 1
for c in C, t in T_node
```

Then it should only create flow constraints where relevant:

Outgoing:

```text
sum y[c,t,a] over reachable outgoing arcs from v = x[c,t,v]
for (c,t,v) in x_keys where t < H
```

Incoming:

```text
sum y[c,t,a] over reachable incoming arcs to v = x[c,t+1,v]
for (c,t+1,v) in x_keys where t+1 > 0
```

This avoids constraints for nodes that a cabin cannot occupy at that time.

The incoming-arc lookup should use a clear time convention. Recommended:

```text
reachable_in_arc_ids_by_cabin_time_node[(c, t, v)]
```

means arcs selected at `t-1` that can bring cabin `c` into node `v` at time `t`.

Then:

```text
sum y[c,t-1,a] over reachable incoming arcs to v = x[c,t,v]
for (c,t,v) in x_keys where t > 0
```

## 4. Conflict Constraints Only When Relevant

Current model creates conflict constraints for every conflict and every time step.

Sparse model should create a conflict constraint only if at least two reachable `x` variables participate.

For each time step and conflict:

```text
participants = [
    x[c,t,v]
    for c in C
    for v in conflict.node_ids
    if (c,t,v) exists
]
```

Create:

```text
sum(participants) <= 1
```

only when:

```text
len(participants) >= 2
```

The same rule applies to same-node occupancy constraints once those are represented as unified conflicts.

For normal multi-node conflicts, participants may come from different nodes. For same-node occupancy, participants are multiple cabins on the same single node:

```text
participants = [x[c,t,node_id] for c in C if (c,t,node_id) exists]
```

So the implementation must count variable participants, not just distinct occupied node ids.

Constraint metadata/names must preserve:

- conflict id
- kind
- scope
- time step

so we can still inspect and later relax groups of constraints.

## Same-Node Occupancy

Current solver has separate node occupancy constraints:

```text
sum_c x[c,t,v] <= 1
```

plus existing `DiscreteConstraint`s for headway/cross-segment conflicts.

This duplicates the conflict mechanism, but changing the `DiscreteScenario` contract is not required for the first sparse upgrade.

First sparse implementation:

- keep same-node occupancy as a solver-internal constraint family
- generate it sparsely with the same participant filtering
- only create `sum participants <= 1` when at least two cabins can occupy the node at that time

Later cleanup:

- move same-node occupancy into the unified `DiscreteConstraint` set
- expose it in exported `DiscreteScenario`
- remove the separate solver branch

Add constraints during or after discretization, preferably during discretization so exported `DiscreteScenario` JSON and frontend counts show the same constraint set used by the optimizer:

```text
DiscreteConstraint(
    id=f"constraint::node_occupancy::{node_id}",
    kind=DiscreteConstraintKind.NODE_OCCUPANCY,
    scope=DiscreteConstraintScope.SAME_NODE,
    strength=DiscreteConstraintStrength.HARD,
    node_ids=(node_id,),
)
```

Because a same-node conflict has only one node, its MILP interpretation differs slightly:

```text
sum_c x[c,t,node_id] <= 1
```

General capacity interpretation:

```text
capacity = 1
sum participants <= capacity
```

For now, `DiscreteConstraint` has no explicit capacity field. v0 can infer capacity `1` for all hard conflicts. If later station capacity needs `capacity > 1`, add an explicit field.

The movement-plan validator must also switch to the same participant-based interpretation:

```text
participants = cabins occupying any node in constraint.node_ids at time t
violation if len(participants) > 1
```

This is important because a same-node occupancy constraint has only one `node_id`; checking only the number of distinct occupied nodes would miss two cabins occupying the same node.

## Expected Impact

Sparse reachability should reduce the model from:

```text
O(|C| * |T| * |V| + |C| * |T| * |A|)
```

to roughly:

```text
O(number of actually reachable states and transitions)
```

The biggest expected reduction comes from avoiding variables for nodes/arcs that a cabin cannot physically reach at a given time.

## Validation Plan

Use existing dense c23/h60 export as benchmark.

Dense baseline:

```text
1,135,418 binary variables
1,221,904 constraints
```

After sparse optimization:

- dense mode still produces a valid result
- sparse mode produces a valid result
- solver result still `optimal`
- movement plan still validates
- same fixed starts
- same horizon
- same 23 trajectories
- substantially fewer variables and constraints

Observed c23/h60 sparse result:

```text
10,575 binary variables
17,259 constraints
```

Tests:

- Dense variable index matches current dense variable counts.
- Sparse variable index starts only at fixed start nodes.
- Sparse variable index follows directed arcs.
- Sparse variable index is a subset of dense variable keys.
- Sparse MILP solves the tiny Gurobi test.
- Sparse MILP export solves c2/h2.
- c23/h60 export validates.
- existing full test suite passes.

## Implementation Order

Implemented:

- `MilpV0VariableStrategy` added to config, defaulting to `DENSE`.
- Shared `MilpV0VariableIndex` added.
- Dense index builder added and tested against current dense variable counts.
- `solve_milp_v0` refactored to use `MilpV0VariableIndex` while still running dense by default.
- Sparse reachability index builder added.
- Position-assignment constraints sum over indexed nodes only.
- Flow constraints iterate over indexed reachable keys.
- Existing conflict constraints skip irrelevant conflict/time combinations.
- Same-node occupancy constraints are generated sparsely inside the solver.
- Sparse export option and filename marker added.
- c23/h60 sparse export generated and validated.
- Sparse variable and constraint counts compared against the dense baseline.

Still open:

- move same-node occupancy into exported `DiscreteScenario` constraints, if we want frontend and JSON counts to expose this explicitly
- test longer horizons with sparse mode
- decide whether dense c23/h60 export should remain checked in or be replaced by sparse export for frontend experiments

## Sparse Reachability Performance Follow-Up

Observed issue:

```text
build_sparse_variable_index
```

took roughly 9 minutes for:

```text
23 cabins
H = 2400
strategy = sparse_reachability
```

This is too slow for normal iteration. The bottleneck is currently Python-side reachability/index construction, before Gurobi solve time.

### Full-Horizon Benchmark

Observed command:

```bash
uv run python -m ropeway_skip_stop_optimization.export_scenarios \
  --progress \
  --milp-horizon 2400 \
  --milp-cabin-count 23 \
  --milp-variable-strategy sparse_reachability
```

Observed timings:

```text
build_sparse_variable_index   702.396s
create_variables               99.740s
add_position_constraints        22.761s
add_flow_constraints           208.149s
add_initial_constraints          0.001s
add_conflict_constraints        75.927s
optimize                      184.180s
extract_solution               49.659s
validate_solution               0.796s
```

Observed input model:

```text
43,711,706 rows
40,115,025 binary variables
240,183,746 nonzeros
```

Observed presolved model:

```text
3,926,741 rows
566,681 binary variables
153,244,438 nonzeros
```

Interpretation:

- Gurobi can presolve away most variables/constraints.
- The main bottleneck is Python-side model/index construction.
- Sparse reachability is excellent for short horizons, but saturates for long horizons because wait arcs and route alternatives make most nodes reachable over time.
- Full-horizon sparse is still useful as a benchmark, but not yet suitable for normal iteration.

### Likely Causes

The current builder performs cabin-by-cabin forward propagation:

```text
for cabin in cabins:
    for t in horizon:
        expand reachable nodes
```

Inside the innermost loop it repeatedly:

- filters outgoing arcs against `allowed_arc_id_set`
- looks up arcs in `graph_index.arcs_by_id`
- creates small tuples, lists, and dictionaries
- deduplicates step arc ids with `dict.fromkeys`
- stores per-cabin/time/node dictionaries

For long horizons this adds up even if the resulting sparse MILP is much smaller than dense.

### Safe Micro-Optimizations

These should not change model semantics.

Precompute allowed outgoing arcs once:

```python
allowed_out_arc_ids_by_node_id = {
    node_id: tuple(
        arc_id
        for arc_id in graph_index.out_arc_ids_by_node_id[node_id]
        if arc_id in allowed_arc_id_set
    )
    for node_id in graph_index.nodes_by_id
}
```

Precompute arc targets once:

```python
to_node_id_by_arc_id = {
    arc_id: graph_index.arcs_by_id[arc_id].to_node_id
    for arc_id in allowed_arc_ids
}
```

Avoid repeated global/dict attribute lookups in inner loops by binding locals:

```python
allowed_out = allowed_out_arc_ids_by_node_id
to_node = to_node_id_by_arc_id
```

Avoid repeated tuple creation until storage boundaries. Keep lists internally and convert to tuples only when assigning into `MilpV0VariableIndex`.

Add final count logging:

```text
sparse reachability x_keys=...
sparse reachability y_keys=...
max reachable nodes per cabin/time=...
```

### Bigger Structural Optimizations

If micro-optimizations are insufficient, use graph/periodicity structure.

#### Reuse Reachability Tails

Reachability states are deterministic functions of:

```text
(reachable_node_set, remaining_horizon)
```

If two cabins reach the same set of nodes at different times, their future expansion is identical up to a time shift.

Possible cache key:

```python
frozenset(reachable_node_ids)
```

This is useful if many cabins share the same local state after entering the same cycle structure.

#### Time-Shifted Cycle Special Case

For the current all-stop baseline, cabin starts are offsets on the same cycle. Many reachable patterns are time-shifted versions of each other.

Potential approach:

- compute reachability once for each unique start offset class
- reuse shifted results for other cabins

Risk:

- this is more scenario-specific
- switches/wait arcs can make reachable sets branch and merge

Do not implement this before the safe micro-optimizations.

#### Build Participants During Reachability

The next known expensive phase is conflict-constraint generation. Reachability can directly build:

```python
reachable_cabin_ids_by_time_node[(t, node_id)] -> tuple[cabin_id, ...]
```

Then same-node occupancy and conflict participants can be created without scanning every cabin for every node/constraint/time.

This would help both:

- sparse variable-index construction diagnostics
- `add_conflict_constraints`

### Recommended Next Implementation Order

1. Precompute `allowed_out_arc_ids_by_node_id`.
2. Precompute `to_node_id_by_arc_id`.
3. Optimize inner loops with local bindings and fewer temporary tuples.
4. Add count/timing logs for the sparse variable index.
5. Re-run full H=2400 sparse export with `--progress`.
6. If reachability is still slow, add caching by reachable node set.
7. If conflict generation becomes the bottleneck, build `reachable_cabin_ids_by_time_node` during reachability and use it in conflict construction.

## Additional Current-Model Speedups

These optimizations keep the current full-horizon node/arc MILP semantics. They do not introduce rolling horizon, periodic patterns, or block aggregation.

### Faster Solution Extraction

Current extraction scans candidate nodes/arcs for every cabin and time step.

Better:

```python
x_values = model.getAttr("X", x)
y_values = model.getAttr("X", y)
selected_x_keys = {key for key, value in x_values.items() if value > 0.5}
selected_y_keys = {key for key, value in y_values.items() if value > 0.5}
```

Then reconstruct trajectories from selected keys.

Expected impact:

- reduce `extract_solution`
- current benchmark: `49.659s`

### Precompute Flow Constraint Term Lists

Current flow construction loops through nested dictionaries during model building.

Add to or alongside `MilpV0VariableIndex`:

```python
outgoing_flow_terms: tuple[tuple[tuple[int, int, str], tuple[str, ...]], ...]
incoming_flow_terms: tuple[tuple[tuple[int, int, str], tuple[str, ...]], ...]
```

Where each row is:

```text
(x_key, arc_ids)
```

Then solver construction becomes a flat loop:

```python
for x_key, arc_ids in outgoing_flow_terms:
    c, t, v = x_key
    addConstr(sum(y[c,t,a] for a in arc_ids) == x[x_key])
```

Expected impact:

- reduce `add_flow_constraints`
- current benchmark: `208.149s`

### Precompute Conflict Participants

Current conflict construction scans cabins and node ids while checking whether `(c,t,node_id)` exists.

Better:

```python
reachable_cabin_ids_by_time_node[(t, node_id)] -> tuple[cabin_id, ...]
```

Then same-node occupancy:

```python
participants = [
    x[c,t,node_id]
    for c in reachable_cabin_ids_by_time_node[t,node_id]
]
```

And conflict participants:

```python
participants = [
    x[c,t,node_id]
    for node_id in constraint.node_ids
    for c in reachable_cabin_ids_by_time_node.get((t,node_id), ())
]
```

Expected impact:

- reduce `add_conflict_constraints`
- current benchmark: `75.927s`

### Integer Internal Node/Arc IDs

Current sparse index stores many Python tuple keys with string node/arc ids:

```python
(cabin_id, time_step, "seg::M_lr_platform::12")
```

This is expensive for memory and hashing.

Potential internal representation:

```python
node_index: int
arc_index: int
node_id_by_index: tuple[str, ...]
arc_id_by_index: tuple[str, ...]
```

Then internal keys become:

```python
(cabin_id, time_step, node_index)
(cabin_id, time_step, arc_index)
```

Only convert back to string ids when building `MovementPlan` and metadata.

Expected impact:

- reduce reachability build time
- reduce memory pressure
- reduce dictionary hashing cost

Risk:

- larger refactor
- harder to inspect raw variable names
- should come after simpler precomputations

### Avoid Materializing Huge Key Lists Where Possible

For full horizon, sparse index generated:

```text
x ~= 20M keys
y ~= 20M keys
```

These are Python tuple objects before Gurobi even sees them.

Potential improvement:

- materialize only what Gurobi needs
- use compact arrays/lists internally
- build variable dictionaries in chunks

This is more invasive and should be considered only after precomputing outgoing arcs, target nodes, flow terms, and conflict participants.

## Follow-Up Implementation Update

Status: implemented in current code.

Implemented speedups:

- precomputed allowed outgoing arcs per node
- precomputed arc target nodes
- cached sparse reachability transitions by reachable node tuple
- logged sparse index counts when progress logging is enabled
- built same-node and cross-node conflict participants from `reachable_cabin_ids_by_time_node`
- generated flow constraints from flat precomputed index dictionaries
- extracted selected solution values in per-cabin batches via `model.getAttr("X", ...)`

Validation:

- `uv run pytest` passes with 62 tests.
- isolated `horizon=2400`, `cabins=23` sparse index build now completes in about 16.6 seconds on the local M3 Pro benchmark, compared with the previous observed 702.4 seconds.
- short full solve/export benchmark with `horizon=240`, `cabins=23`, `sparse_reachability` completed successfully.
