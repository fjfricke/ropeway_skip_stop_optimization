# Progressive fleet continuation in the full reservoir CP-SAT model

## Purpose

The pilot tests whether a validated solution for fleet cap `K-1` is a useful
hint for the unrestricted full model at cap `K`. Dispatch times, route choices,
Waiting, returns, and passenger assignments remain free at every stage. The
objective is the existing product-encoded journey-time objective, including
the horizon penalty for unserved passengers.

The frozen case is historical R2 with 3,074 passengers, the migrated shared
reservoir port, and a uniform 1,200-second Waiting limit. The movement stored
inside the frozen checkpoint is used only to reconstruct and authenticate the
domain; the campaign starts from the empty K=1 plan.

## Procedure

For `K=1,...,50`, the runner rebuilds the complete reservoir CP-SAT model with
at most `K` active cabins. It independently validates and imports the previous
checkpoint across the fleet-cap change and supplies all movement and passenger
values as hints. It never passes `fixed_plan` or `fixed_route_plan`.

The budgets are 30 seconds for K=1–10, 90 seconds for K=11–25, and 210 seconds
for K=26–50. Their sum is 115 minutes; five minutes remain within the two-hour
campaign deadline for preparation and finalization. Each stage runs in a fresh
supervised process with 12 workers, a 32-GiB process-tree ceiling, and the
existing 30-second system-memory-pressure grace period.

Timeouts and resource stops retain the latest independently validated
checkpoint. An interrupted campaign can resume without repeating completed
fleet caps; a checkpoint from an interrupted attempt is also considered as a
hint if it improves the previous completed stage. Bounds remain attached to
their own fleet cap and are never transferred to a larger domain.

## Interpretation

The dashboard reports the objective, served and unserved counts, actual used
fleet, mean journey time of served passengers, STOP/SKIP counts, and SKIPs
while passengers are on board. A transferred seed does not count as native
progress. A stage improves only when its independently validated journey-time
objective is strictly lower than its input seed. Comparisons against a direct
K=50 solve require a later run with the same domain and total budget.
