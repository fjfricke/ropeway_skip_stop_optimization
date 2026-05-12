# Scenario Mapping and Replay Architecture

Status: **planned**

## Goal

Keep the physical scenario as the source of truth while supporting multiple
derived optimization/replay representations:

```text
Physical Scenario
  -> DiscreteScenario        legacy/discrete-time representation
  -> EAN build artifact      continuous-time optimization representation
```

Both derived representations should remain inspectable and replayable where
appropriate.

## Principles

- `Scenario` is the physical model and should stay canonical.
- `DiscreteScenario` remains supported for existing exports, frontend views, and
  discrete-time replay.
- New EAN optimization should map from `Scenario`, not from `DiscreteScenario`.
- EAN solutions must carry enough mapping information to project back onto the
  physical model.
- Replay should be organized by representation: discrete-time replay and
  physical replay are different products.

## Target Structure

```text
src/ropeway_skip_stop_optimization/
  models/
    scenario.py
    discrete_scenario.py       # legacy/deprecated for new solvers, still supported
    plan.py
    replay.py

  mapping/
    __init__.py
    physical_to_discrete.py    # existing discretizer moved here
    physical_to_ean.py         # later
    ean_to_physical.py         # later

  optimization/
    discrete_time/
      ...
    ean/
      models.py
      builders/
      solvers/

  replay/
    discrete_time/
      demand.py
      passengers.py
      metrics.py
    physical/
      projection.py            # later
      timeline.py              # later
```

## DiscreteScenario

`DiscreteScenario` is not removed.

It should be treated as:

- legacy/deprecated for new optimization work
- still valid for existing discrete-time MILP
- still valid for existing frontend graph/replay views
- still exportable as JSON

Use the mapping API:

```python
from ropeway_skip_stop_optimization.mapping import discretize_scenario
```

## EAN Mapping

EAN should eventually have an explicit build artifact:

```text
EanBuildArtifact:
  scenario_id
  config
  timings
  cabin_starts
  switch_visits
  headway_checkpoints
  headway_candidates
  headway_pairs
  physical_mapping
```

The physical mapping should preserve enough detail to project EAN solutions back
to the physical model:

```text
EanPhysicalMapping:
  switch_id_to_physical_node_id
  station_id_by_switch_id
  checkpoint_to_physical_reference
  service_path_segments_by_switch_id
  skip_path_segments_by_switch_id
```

The solver should not hide physical mapping details in Gurobi variable names.
Mapping data should be explicit and serializable.

## Replay

Existing replay should be moved under a discrete-time namespace later:

```text
replay/discrete_time/
```

It consumes:

```text
DiscreteScenario + MovementPlan
```

Future physical replay should consume:

```text
Scenario + physical projection of an EAN solution
```

The frontend can continue to support the old discrete replay for scenarios that
were exported discretely, while adding a separate physical/EAN replay path later.

## Near-Term Refactor

The existing discretizer implementation should live at:

```text
mapping/physical_to_discrete.py
```

Do not keep a `preprocessing` compatibility layer. Update imports to use
`mapping` directly.

Do not move replay modules yet. The replay split should happen after the EAN
solution/projection shape is defined.
