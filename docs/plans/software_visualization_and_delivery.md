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

The release-based Vercel workflow, generated-data staging, chunked JSON loader,
and Basic Auth middleware are implemented. Remaining operational work:

1. Ensure Vercel does not publish production directly from `main`.
2. Prepare the intended generated example data.
3. Publish a GitHub release with `frontend-generated-examples.tar.gz`.
4. Verify the release-triggered deployment, authentication, example loading,
   and protection of direct `/generated/...` requests.

Deployment verification is operational work and should not be mixed with
optimization benchmark results.
