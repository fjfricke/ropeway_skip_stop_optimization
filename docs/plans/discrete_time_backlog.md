# Discrete-Time Backlog

Status: **low-priority prototype work**

## Position

The discrete-time model is retained for comparison, replay, and methodological
history. New exact optimization work should normally target the continuous EAN
model because long horizons make the time-expanded representation very large
and discretization changes timing accuracy.

## Diagnostics

Add a backend discretization report with:

- segment and route physical/discrete durations;
- service-versus-skip drift between matching entry and exit switches;
- complete-cycle slack and accumulated lap drift;
- source segment and route identifiers.

The frontend may expose `Segments`, `Routes`, `Switch Drift`, and `Cycle` views,
but should render exported diagnostics rather than independently recomputing
them.

## Remaining Construction Improvements

Investigate only when the discrete prototype is needed for a new experiment:

- compact integer node and arc indices internally;
- avoid materializing tens of millions of Python tuple keys;
- chunked or array-based variable-index construction;
- explicit export of same-node occupancy constraints when frontend inspection
  of those counts is useful.

The existing cached sparse reachability and participant precomputation should
remain the baseline.

## Alternative Formulations

Research ideas, ordered from smaller to larger semantic change:

1. Arc and wait-policy tightening plus symmetry breaking.
2. Block aggregation or capacity arcs.
3. Rolling-horizon optimization with explicit boundary-state transfer.
4. Periodic-pattern optimization for steady circulation.
5. Path-based cabin or passenger formulations.
6. Lazy or separated conflict constraints.

These are alternatives to the current full-horizon node/arc prototype, not
incremental default optimizations. Each requires a stated approximation or
exactness boundary and comparison against a small reference instance.
