# Fixed-K OIP Fleet Capacity

## Status

The original max-active experiment remains a small-instance reference only.
It materialised the physical packing bound `U_pack` as potential cabins and
then maximised `sum(cabin_active)`.  This is not the production path because
the canonical all-pairs headway artifact grows with that loose physical bound
before the solver can exploit inactive cabins.

The canonical implementation now searches the finite-horizon capacity through
exact fixed-fleet feasibility probes.

## Capacity Statement

For the current OIP model and operational horizon `H`, define

\[
K_{\max}^{\mathrm{OIP}}(H)=
\max\{K\mid \operatorname{FeasibleOIP}(K,H)\}.
\]

Each probe contains exactly `K` active, interchangeable cabins.  It decides
their initial phase and physical state plus all subsequent stop, skip, waiting,
timing and headway decisions, but contains no passenger objective and no fleet
activation decision.  Removing a cabin preserves every remaining constraint,
so feasibility is downward closed.

`U_pack` remains a conservative inclusive upper bound and the canonical
all-stop/no-wait circulation supplies the first lower bound `K_AS`.

## Search

1. Verify `K_AS` in the exact fixed-K model.
2. Probe `K_AS + 1`, `K_AS + 2`, `K_AS + 4`, ... until an infeasible value
   or `U_pack` is reached.
3. After a proven infeasible value, close the bracket by binary search.
4. A timeout without an incumbent is `UNKNOWN` and never changes a certified
   bound.  The reported interval remains `[K_LB, K_UB]`; it is exact only when
   both bounds coincide.

Each probe receives its own configured solver limit.  Setup and solve times
are recorded separately because headway artifact construction is part of the
scaling result.

## Limits and Future Work

The initial cabin-ID phase ordering is symmetry breaking only.  It does not
fix later rope orders: service, skip and waiting may reorder cabins at a
station merge.  All-pairs headways therefore remain exact in this phase.

The passenger OIP remains explicitly configured and does not automatically
consume a capacity-search result.  A later integration may use a closed exact
value as an exact active fleet size.  FIFO remains unsupported until both its
occupancy model and matching physical packing bound exist.
