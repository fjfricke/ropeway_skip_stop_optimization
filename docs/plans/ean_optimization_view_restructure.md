# EAN Optimization View Restructure Plan

## Summary

The current EAN Optimization `View` is mostly an artifact/debug view: it exposes switch cycles, timings, headway checkpoints, and raw replay events. The target should be a result-oriented optimization view that first answers:

- What was optimized?
- How good is the result?
- How large/hard was the model?
- What operational plan did the solver produce?

Detailed artifact tables should remain available, but as secondary debug details.

## Current View

The current `EanView` shows:

- header metrics: horizon, switch count, cabin count, replay event count;
- build summary: horizon, tail, model end, capacity, starts, visits, checkpoints, headway pairs;
- full switch cycle;
- skip/stop timing table;
- headway checkpoint table;
- first 240 replay events and selected-event details;
- plan status: trajectories, stop/skip decision counts, plan end, scenario id;
- objective result: objective, value, status, gap, best bound, runtime, nodes, solutions, gap target, time limit, served/unserved, visible skips.

## Problems

- Important solver/result information is visually secondary.
- Raw artifact details dominate the page.
- Replay events are useful for debugging but noisy as a default result view.
- Switch cycle and checkpoint tables are not the first thing a user needs when assessing optimization quality.
- The note about `v0` horizon behavior feels like an internal implementation comment.
- Some available metadata is underused, especially model size and passenger-service statistics.

## Proposed Structure

The EAN optimization area should have four tabs:

- `View`: result summary, model size, operational plan, and debug details;
- `Progress`: solver progress over wall-clock optimization runtime;
- `Metrics`: passenger queues, onboard loads, and accumulated objective over model time;
- `Replay`: physical replay of the optimized plan.

`Progress` should be placed between `View` and `Metrics`, because it describes the optimizer run itself. `Metrics` should keep its current meaning: passenger/service behavior over scenario time.

### 1. Result Summary

Put this at the top of the EAN view.

Show:

- objective kind;
- objective value in passenger-hours;
- solver/result status;
- MIP gap;
- best bound converted to passenger-hours;
- runtime;
- served and unserved passengers;
- visible skipped visits.

Use warning treatment for:

- non-optimal/interrupted status;
- unserved passengers greater than zero;
- events after horizon greater than zero.

### 2. Model Size & Solver Performance

Show compact model/build metrics:

- variables;
- constraints;
- demand groups;
- ride candidates;
- slot variables;
- headway checkpoints;
- headway pairs;
- branch-and-bound nodes;
- solution count;
- gap target;
- time limit.

This is important for comparing optimization improvements and benchmark runs.

### 3. Operational Plan Summary

Show a compact summary of the produced plan:

- number of trajectories/cabins with plans;
- stop vs. skip decision counts;
- plan end and horizon;
- replay event range;
- events after horizon;
- skipped visits and visible skipped visits.

This should help answer what the solver actually decided without opening detailed tables.

### 4. Debug Details

Keep the existing detailed artifacts, but move them below the summaries and make them visually secondary.

Sections:

- Switch Cycle
- Skip/Stop Timings
- Headway Checkpoints
- Replay Events
- Selected Event

Preferred behavior:

- collapsed by default if the UI already has a local pattern for collapsible panels;
- otherwise keep them below the fold in the current panel style.

## Progress Tab

Add a new EAN optimization tab named `Progress`.

The Progress tab should answer:

- how the incumbent objective improved over solver runtime;
- how the best bound improved over solver runtime;
- how the MIP gap closed;
- how much branch-and-bound search happened;
- when new incumbent solutions were found.

### Progress Content

Show a solver-runtime chart using `runtime_seconds` on the x-axis.

Primary series:

- incumbent objective, displayed in passenger-hours;
- best bound, displayed in passenger-hours.

The stored callback values remain raw solver objective seconds. The frontend should convert objective and bound values to passenger-hours consistently with the existing objective summary.

Secondary information:

- MIP gap over runtime;
- node count;
- solution count;
- sample event type: `interval`, `incumbent`, `final`.

Summary cards:

- final objective;
- final best bound;
- final MIP gap;
- runtime;
- node count;
- solution count;
- solver status.

Interaction:

- hover selects the nearest progress sample;
- selected sample details show runtime, incumbent, bound, gap, nodes, solutions, work, and event type;
- incumbent samples should be visually distinguishable from periodic samples.

Empty-state behavior:

- if an older generated EAN result has no `progress_samples`, hide the tab or show a compact unavailable state;
- do not break old generated JSON files.

## What To Remove Or De-emphasize

- Remove or rewrite the `v0 uses the horizon as physical model boundary` note.
- Remove `scenario` from Plan Status; the scenario is already visible in the app header.
- Do not show raw replay events as a primary right-side panel.
- Do not lead with switch cycle or headway checkpoint tables.

## Data Sources

For the `View`, use existing loaded artifacts:

- `EanBuildArtifact`
- `EanMovementPlan`
- `EanPhysicalReplay`
- `EanPassengerServiceResult`

For the new `Progress` tab, add solver progress samples to `EanPassengerServiceResult.metadata`.

The progress data should come from the Gurobi callback recorder, not from parsing solver logs.

The normal export CLI should record this automatically for EAN passenger-service solves. Do not add a new CLI flag for enabling progress recording. Regenerating an EAN passenger-service artifact should be enough to populate `metadata.progress_samples`.

Progress sample fields:

- `runtime_seconds`
- `node_count`
- `incumbent_objective`
- `best_bound`
- `mip_gap`
- `solution_count`
- `work`
- `event`

Record samples:

- periodically, e.g. every `5s`;
- immediately when a new incumbent solution is found;
- once after `optimize()` as a final sample.

This does require an export schema extension, but it must be backward-compatible: frontend fields should be optional and older generated data should continue to load.

## Implementation Notes

- Keep `EanView` as the entry component.
- Extract small presentational helpers only if the file becomes hard to read.
- Preserve existing formatting helpers where possible.
- Prefer compact metric cards over large tables for summary sections.
- Existing detailed rows (`TimingRow`, `CheckpointRow`, `EventList`, `EventDetails`) can be reused.

### Backend Files

Add:

- `src/ropeway_skip_stop_optimization/optimization/solver_progress.py`

Move the existing progress recorder classes out of benchmarking and into this shared optimization module:

- `GurobiMipProgressSample`
- `GurobiMipProgressRecorder`

Reasoning:

- the recorder is solver/optimization infrastructure, not benchmark-specific logic;
- benchmark runs and normal frontend exports should both consume the same recorder;
- this avoids the wrong dependency direction where production export code imports from `benchmarking`.

Change:

- `src/ropeway_skip_stop_optimization/benchmarking/ean_passenger.py`
  - import `GurobiMipProgressSample` and `GurobiMipProgressRecorder` from `optimization.solver_progress`;
  - remove the local class definitions.
- `src/ropeway_skip_stop_optimization/optimization/ean/optimizers/passenger_service.py`
  - extend `EanPassengerServiceMetadata` with `progress_samples`;
  - after optimization, copy `tuple(config.progress_recorder.samples)` into metadata when a recorder is present;
  - keep the field empty when no recorder is provided.
- `src/ropeway_skip_stop_optimization/exports/artifacts.py`
  - create a progress recorder automatically for each EAN passenger-service objective solve if no explicit recorder was injected;
  - store automatic recorders per objective in `ExportContext` so waiting-time and journey-time solves never share recorder state;
  - keep explicitly injected recorders supported for benchmarks and tests;
  - treat an explicitly injected recorder as a single-solve testing/benchmark hook. If a future benchmark runs multiple passenger-service objectives in one export, switch the internal API to a recorder factory instead of sharing one recorder object.
- `src/ropeway_skip_stop_optimization/optimization/__init__.py`
  - optionally re-export the progress types if that improves import ergonomics.

Object-oriented structure:

- keep `GurobiMipProgressRecorder` as a stateful object, because it owns sampling interval state, last incumbent tracking, callback handling, and final sampling;
- keep `GurobiMipProgressSample` as an immutable dataclass/value object;
- do not introduce a larger abstraction unless another solver backend needs the same interface.

### Frontend Files

Change:

- `frontend/src/types.ts`
  - add `EanSolverProgressSample`;
  - add optional `progress_samples?: EanSolverProgressSample[]` to `EanPassengerServiceMetadata`.
- `frontend/src/components/viewerTypes.ts`
  - add `ean_progress` to `ViewerMode`;
  - add `ean_progress` to `AvailableViewerModes`.
- `frontend/src/components/ViewerModeTabs.tsx`
  - add a `Progress` button between `View` and `Metrics`.
- `frontend/src/components/ScenarioViewer.tsx`
  - make `ean_progress` available only when progress samples exist;
  - render the new progress view;
  - keep `View` as the first EAN optimization tab.

Add:

- `frontend/src/components/EanProgressView.tsx`

`EanProgressView` should follow the style and SVG chart pattern of `EanMetricsView`, but it should be a separate component because it describes solver runtime rather than passenger model time.

Suggested internal helpers:

- `buildProgressChartModel(samples)`
- `nearestProgressSample(samples, runtimeSeconds)`
- `formatGap(value)`
- `formatObjective(value)`
- `formatRuntime(seconds)`

Frontend object model:

- prefer pure chart-model builder functions over classes;
- keep React state limited to hover/selected sample;
- do not add a generic chart abstraction unless duplication with `EanMetricsView` becomes a real maintenance problem.

## Test Plan

- Run `npm run build` in `frontend`.
- Run existing progress recorder tests and update imports.
- Verify EAN artifact set with complete passenger-service result:
  - summary values match current Objective Result values;
  - model size metrics are populated;
  - debug tables still render.
- Verify EAN artifact set with progress samples:
  - `Progress` tab appears between `View` and `Metrics`;
  - incumbent and best-bound series render;
  - final sample matches metadata objective/bound/gap/runtime;
  - incumbent events are visually distinguishable.
- Verify the normal export CLI:
  - no new CLI flag is required;
  - regenerated EAN passenger-service result JSON contains `metadata.progress_samples`.
- Verify old generated EAN result without progress samples:
  - frontend still loads;
  - `Progress` tab is hidden or shows a clear unavailable state.
- Verify EAN artifact set with interrupted result:
  - status/gap/runtime are shown clearly;
  - missing optional fields render as `n/a`.
- Verify EAN artifact set without replay/result:
  - empty states still render instead of crashing.
- Check both three-station and five-station examples.

## Assumptions

- The `View` restructure itself is UI-only.
- The `Progress` tab requires a backward-compatible generated artifact schema extension.
- Existing debug information should remain accessible.
- The main audience is comparing optimization quality and performance, not inspecting every raw EAN event by default.
- Solver progress must come from callback metrics, not solver-log parsing.
