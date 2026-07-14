# Current Software Architecture

Status: **implemented reference**

## Pipeline

The physical `Scenario` is the source of truth:

```text
Scenario
  -> validation
  -> DiscreteScenario or EanBuildArtifact
  -> optimizer or deterministic baseline
  -> movement/passenger plan
  -> validation and physical/discrete replay
  -> metrics and JSON export
  -> frontend manifest and visualization
```

`DiscreteScenario` remains supported for the prototype MILPs and replay views.
New exact optimization work uses the continuous EAN path directly from the
physical scenario.

## EAN Construction and Optimization

The EAN builder derives route timing, cabin starts, switch visits and
transitions, headway checkpoints, headway candidates, and headway pairs before
Gurobi model construction. The passenger optimizer then adds movement timing,
stop/skip, waiting, ordering, ride-slot, capacity, demand-balance, and
objective-specific constraints.

Implemented passenger objectives:

- waiting time;
- journey time;
- unserved demand penalty in both models.

Implemented default optimizations:

- candidate horizon pruning;
- exact dominated full-ring ride pruning;
- slot-time relaxation strengthening.

Tight passenger and stop/skip Big-M bounds are implemented behind the opt-in
`tight_big_m_bounds` selection.

## Validation, Replay, and Frontend

EAN output is converted to typed movement and passenger plans, validated
against the build artifact, and projected to physical events. Positive
`STATION_FIFO_BUFFER` waits are intentionally unsupported until position traces
exist. The frontend consumes only paths declared in the generated manifest and
provides scenario, graph, metrics, optimization, and replay views.

## Solver Observability and Checkpoints

Solver policies configure Gurobi without changing the model definition.
Optimizers expose status, objective, bound, gap, runtime, node count, and
solution count. Normal EAN passenger exports automatically receive
per-objective progress recorders; benchmark tooling reuses the same callback
metrics and adds result files and plots.

Checkpoint files store incumbent solutions and are loaded as MIP starts. They
do not persist or resume the previous branch-and-bound tree.

## Benchmark and Delivery

Benchmark scripts write machine-specific JSON, SVG plots, and checkpoints under
the ignored `benchmarks/output/` directory. Frontend artifacts are not produced
by benchmarks unless explicitly requested.

The release deployment workflow packages generated frontend data as a GitHub
release asset, splits oversized JSON into chunks, rebuilds the frontend in
GitHub Actions, deploys through Vercel, and protects requests with Basic Auth.
