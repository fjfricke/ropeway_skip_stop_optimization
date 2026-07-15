# Development Progress

This document records when relevant project work was completed and why the
corresponding decisions were made.

## 2026-07-14

### Documentation consolidation

The software plans and findings were consolidated in commit `8c4b248`. The
previous collection of implementation-history plans was replaced by a small
future-work roadmap, findings documents, and a current-architecture reference.
The thesis plans were consolidated separately in commit `0a07ad4`.

The purpose was to make future work, implemented architecture, and empirical
findings distinguishable without using plan files as an implementation archive.
Git history remains the archive for removed plans.

### EAN horizon and terminal-state review

The current EAN implementation was found to use three different effective
boundaries:

- the passenger horizon `horizon_seconds`;
- the configured model end `horizon_seconds + tail_seconds`;
- a solver time bound derived from the longest no-wait chain plus ten seconds.

The last bound can leave only ten seconds of cumulative waiting for the
longest cabin chain and can therefore couple waiting feasibility to skipping.
The visit builder, optimizer, validator, and replay also do not yet use one
fully consistent rule for events crossing the model end.

The structural reformulation plan now distinguishes:

- passenger cutoff `T`;
- operational certification horizon `H`;
- minimum post-`H` boundary context;
- future full-day terminal modes such as depot return and identity-free cyclic
  operation.

A fixed all-stop/no-wait terminal policy was rejected as a general
extendability certificate. Mixed skip and wait operation can support a larger
active fleet than that fixed policy.

### Configurable EAN horizon and time-bound formulations

The EAN formulation configuration was extended with two mutually exclusive
categories while preserving one comma-separated CLI selection:

- horizon semantics: legacy generated suffix, conservative free suffix, or
  exact activation from optimized event times;
- time bounds: historical no-wait chain plus ten seconds, or propagated
  visit-specific bounds.

This was implemented as selectable cases because the horizon alternatives
define different finite feasible sets and must be benchmarked as semantic
variants rather than presented as same-model speedups. Independent exact
optimizations remain freely combinable with one value from each formulation
category.

The derived bounds use a configured station maximum wait when available and
otherwise one operational horizon as a finite terminal waiting cap. Exact
activation retains route clearance and resource occupancy for events entering
by \(H\), even if the leader clears after \(H\). Later visits receive no new
route decision. Cabins with an earliest start may have an empty active visit
prefix when their first optimized switch entry is after \(H\).

The optimizer, movement-plan extraction, validator, export configuration,
benchmark metadata, README, architecture reference, and thesis methodology
were updated together. Small passenger instances and both conservative and
exact Three-Station skip/stop solves were used to verify valid extracted
prefixes. The exact extraction also normalizes adjacent boundary times from the
same optimized switch variable to avoid false monotonicity failures at roughly
\(10^{-12}\) seconds.

### Horizon and time-bound benchmark matrix

All six combinations of the three horizon cases and two time-bound cases were
run for five minutes on `three_station_v0` with the journey-time objective.
The purpose was to separate semantic viability from solver performance before
changing any default.

The legacy and conservative free-suffix horizons produced nearly identical
five-minute results with the historical time domain. Derived visit bounds
worsened both of those runs, but were essential for making exact time
activation computationally usable. Exact activation with the historical
all-visits domain remained near its initial MIP start with a 59.80% gap;
combining it with propagated visit bounds produced a normal incumbent and a
7.91% gap.

The legacy horizon and legacy time bounds remain the default. The new cases
remain explicit formulation experiments because the horizon choices have
different finite-horizon semantics and the derived bounds have not shown a
general performance benefit.

### Affine stop/skip timing formulation

The historical four Big-M timing implications per visit were retained as one
formulation case and an exact affine alternative was added:

```text
exit = switch + skip_duration
       + (service_duration - skip_duration) * stop
       + wait
```

The affine relation is one ordinary linear equality for an unconditionally
active visit. Under exact time activation, an indicator enables the equality
only for an active visit. Passenger and skip/stop-feasibility optimizers use
the same helper so their timing algebra cannot drift independently.

Exact small instances preserved waiting-time and journey-time objectives.
The full suite passed with 242 tests; Ruff lint, the frontend build, and the
thesis PDF build also succeeded.

A five-minute Three-Station comparison reduced rows by 1,293 and improved the
MIP gap from 6.52% to 4.83%. The affine incumbent was slightly worse and served
four fewer passengers, so Big-M remains the default until repeated runs show
that the proof improvement is stable without an unacceptable primal-side
regression.
