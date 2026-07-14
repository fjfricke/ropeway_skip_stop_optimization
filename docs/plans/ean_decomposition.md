# EAN Decomposition Roadmap

Status: **research plan**

## Goal

Evaluate decomposition and delayed constraint generation without weakening the
exactness claims of the current integrated EAN passenger MILP. The integrated
model remains the reference implementation and certification path.

## Phase 1: Fixed-Movement Passenger Evaluator

Build a destination-layered event-expanded passenger model for a fixed movement
and timing plan.

The network should contain demand sources, station waiting events, boarding,
cabin-interval ride arcs, alighting, destination sinks, and an unserved option.
Destination layers preserve OD identity and share cabin capacities:

```text
sum(flow on cabin interval over all destinations) <= cabin capacity
```

The shared capacities make this a multi-commodity model. Its continuous LP is
not automatically integral.

Record:

- model size and runtime;
- whether every flow is integral;
- fractional arcs and paths;
- flow-to-path decomposition size;
- objective agreement with the integrated model for the same fixed movement.

## Phase 2: Exact Passenger Certification

If the LP is fractional, solve an exact restricted integer repair over active
arcs or decomposed paths. Treat a repaired solution as exact only when it is
feasible for the complete fixed-movement passenger assignment problem.

If restricted repair is insufficient, evaluate path-based column generation
and then branch-and-price only if exact integer assignment remains a bottleneck.
The LP may still serve as a lower bound, diagnostic, or MIP-start generator.

## Phase 3: Delayed Exit-Switch Headways

Prototype delayed generation for selected exit-switch or rope-merge headway
pairs using an external solve loop:

```text
solve current model
inspect incumbent movement
detect every delayed headway violation
add the exact missing disjunctions
reload compatible start values
repeat until no violation remains
```

Keep station and platform constraints eager initially. Report intermediate gaps
as bounds for the current generated model, not for the complete problem.
Compare the final verified result against the eager model on exact small cases.

## Phase 4: Progressive Wait

For guaranteed feasible-set nesting, build the full-wait artifact once and
solve restricted stages by fixing or capping its existing wait variables:

```text
wait = 0
optional intermediate cap
full configured wait bound
```

A solution from a smaller cap is then a feasible incumbent for a larger cap.
Its lower bound is not transferable.

A separately built `NO_WAITING` artifact has different checkpoint and variable
sets, including missing platform-exit wait checkpoints. It may provide a
partial name-based heuristic start, but it is not a guaranteed feasible
incumbent for the full-wait artifact.

Use a small fixed cap schedule for initial experiments. Do not claim that
headway pair count varies monotonically with the numeric cap: current pair
generation does not use such a cap. Complexity-adaptive schedules require a
separate conservative time-window classifier first.

## Phase 5: Decomposed Exact Search

Attempt classical LP Benders only if the passenger LP's required integrality
property is established. Otherwise use integer/logic-based Benders,
branch-and-Benders, or keep an exact integrated certification stage.

The final reported result is exact only when:

- all full-wait variables and constraints are active;
- no delayed physical violation remains;
- passenger assignment is integral and fully feasible;
- the reported bound and gap belong to that certified model.

## Evaluation Order

1. Fixed-movement passenger LP and integrality diagnostics.
2. Exact restricted passenger repair.
3. Delayed exit-switch headways.
4. Same-artifact progressive wait.
5. Combined decomposition only after the separate components agree with the
   integrated reference model.
