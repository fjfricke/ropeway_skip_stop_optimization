# Optimization Package Restructure

Status: **implemented**

## Goal

Separate optimization code by formulation instead of mixing discrete-time MILP,
continuous-time EAN, shared helper indexes, and solver versions in one flat
`optimization/` package.

The package should make it obvious which model family a file belongs to:

```text
optimization/
  discrete_time/
  ean/
```

## Motivation

The current flat package mixes:

- old time-expanded movement MILP
- passenger waiting MILP built on the same time-expanded variables
- sparse/dense variable indexing
- movement plan validation
- continuous-time EAN dataclasses and builders

This makes new EAN solver work harder to reason about and increases the chance
that old time-expanded assumptions leak into the continuous-time model.

## Target Structure

```text
src/ropeway_skip_stop_optimization/optimization/
  __init__.py

  discrete_time/
    __init__.py
    graph_index.py
    models.py
    movement_model.py
    movement_model_builder.py
    passenger_index.py
    passenger_waiting_model.py
    validation.py
    variable_index.py

  ean/
    __init__.py
    models.py
    builders/
      __init__.py
      switch_visit_builder.py
      ring_switch_visit_builder.py
      headway_checkpoint_builder.py
      headway_candidate_builder.py
      headway_pair_builder.py
    solvers/
      movement_feasibility.py      # later
      passenger_waiting.py         # later
    validation.py                  # later
```

## File Moves

```text
optimization/models.py
  -> optimization/discrete_time/models.py

optimization/graph_index.py
  -> optimization/discrete_time/graph_index.py

optimization/variable_index.py
  -> optimization/discrete_time/variable_index.py

optimization/movement_milp_builder.py
  -> optimization/discrete_time/movement_model_builder.py

optimization/milp_v0.py
  -> optimization/discrete_time/movement_model.py

optimization/milp_v1_passenger_waiting.py
  -> optimization/discrete_time/passenger_waiting_model.py

optimization/passenger_index.py
  -> optimization/discrete_time/passenger_index.py

optimization/movement_plan_validation.py
  -> optimization/discrete_time/validation.py
```

## Naming

Use descriptive formulation names instead of version-only filenames:

```text
milp_v0.py                       -> movement_model.py
milp_v1_passenger_waiting.py     -> passenger_waiting_model.py
movement_milp_builder.py         -> movement_model_builder.py
movement_plan_validation.py      -> validation.py
```

The public config/result dataclasses may keep their existing names for now to
avoid unnecessary churn. Later we can rename `MilpV0Config` etc. once the EAN
solver API is stable.

## Public API

Do not keep root compatibility re-exports in:

```text
optimization/__init__.py
```

Import formulation-specific APIs explicitly:

```python
from ropeway_skip_stop_optimization.optimization.discrete_time import solve_milp_v0
from ropeway_skip_stop_optimization.optimization.ean import RingSwitchVisitBuilder
```

Internal imports should use the formulation-specific packages after the move.

## Test Move

Test file renaming can happen later. For this refactor, update imports only and
keep the existing test filenames. That keeps the change focused on source
layout.

## Acceptance Criteria

- no behavior changes
- no solver formulation changes
- no root optimization compatibility re-exports
- internal imports point to `optimization.discrete_time.*`
- `uv run pytest` passes
