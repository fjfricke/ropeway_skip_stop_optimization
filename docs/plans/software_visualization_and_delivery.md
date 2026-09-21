# Software, Visualization, and Delivery Backlog

Status: **future work**

## Replay and Projection

Implement physical position traces for `STATION_FIFO_BUFFER`. The trace must
represent queue position through time, preserve cabin order, and project waits
without inventing overtaking. Until then, EAN projection should continue to
raise an explicit error for positive FIFO-buffer waits.

Possible later replay extensions:

- additional passenger boarding policies beyond greedy FIFO;
- policy selection in replay tooling when more than one policy exists;
- richer validation of station-buffer occupancy and queue transitions.

## Architecture Maintenance

Consider splitting replay namespaces into discrete-time and physical/EAN
packages only when new functionality makes the current modules ambiguous.
Keep `Scenario` as the physical source of truth and both derived models
explicit. Avoid compatibility packages whose only purpose is preserving old
internal import paths.

## Benchmark Tooling

Potential improvements:

- automate repeated benchmark matrices and aggregate statistics;
- generate benchmark matrices from typed formulation categories plus
  independently enabled exact reductions;
- expose a stable experiment preset API around existing local scripts;
- record solver seed and repeated-run variance;
- add optional CSV/table generation from benchmark JSON;
- support remote compute only after formulation comparisons are reproducible.

Normal exports already receive per-objective progress recorders and write
solver progress metadata. Core metrics must continue to come from callbacks and
model attributes, not parsed Gurobi logs.

## Frontend Delivery

The hand-in uses a local viewer and a separately packaged raw-data ZIP.
The former hosted-release deployment and its authentication configuration have
been removed. No hosting setup is required to inspect the submitted results.
See the [repository README](../../README.md) for export and startup commands.
