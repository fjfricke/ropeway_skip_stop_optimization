# EAN Boundary-Reservoir Capacity and Warm-Up Proof Plan

## Status

Future proof work. The source-reservoir warm-up implementation has been
removed in favor of optimized initial placement with explicit `K`. This file
retains the fleet upper-bound and source-reachability questions. Recovery is
specified separately in `ean_terminal_recovery_feasibility.md`.

## Goal

Future capacity and source-reservoir parameters should carry stronger
guarantees than being valid for one constructed reference circulation:

1. `K_max + 1` cabins cannot produce any feasible network solution.
2. Every admissible initial placement of up to `K_max` cabins can be produced
   from the source reservoir by time `W`.

The exact meaning of "admissible network state" must be fixed before attempting
these proofs.

## Historical Proposal

The removed reservoir proposal used the canonical passenger-free
All-Stop-/No-Wait circulation:

```text
cycle_time = canonical complete ring duration
bottleneck_headway = largest headway traversed by every cabin

K_max = max(1, floor(cycle_time / bottleneck_headway))
W = cycle_time
```

This can construct a periodic reference capacity under its assumptions. It
does not prove that no non-periodic, waiting, storage, or mixed Stop/Skip
solution can contain more cabins. The production initial-placement mode
therefore continues to require an explicit fleet limit.

## 1. Formal Model and Assumptions

Define the theorem domain explicitly:

- one complete directed ring;
- no overtaking;
- exactly one physical source exit and one physical sink entry;
- all physical rope, station, waiting, hold, and storage resources;
- exact headway and occupancy semantics for every resource;
- allowed Stop/Skip decisions;
- allowed waiting and its finite capacities;
- whether the state must be periodic or may be an arbitrary finite-horizon
  state;
- whether cabins may be stored without traversing the complete ring;
- the recovery policy used after `T`.

Each proof must list the assumptions it relies on. In particular, periodic
canonical capacity and global physical network capacity must not be treated as
the same statement without proof.

## 2. Prove or Refute the Current `K_max`

### 2.1 Upper bound at a common checkpoint

For a checkpoint traversed exactly once per cycle by every cabin, let the
cyclic passage gaps be `g_1, ..., g_K`. In a periodic circulation:

```text
sum(g_i) = cycle_time
g_i >= checkpoint_headway
```

Therefore:

```text
K * checkpoint_headway <= cycle_time
K <= floor(cycle_time / checkpoint_headway)
```

Taking the largest applicable checkpoint separation gives the current upper
bound.

The proof must verify:

- every cabin traverses the checkpoint exactly once per relevant cycle;
- all cabins use the same cycle duration;
- checkpoint constraints are cyclic and time-translation invariant;
- platform occupancy constraints can be represented by the separation used in
  the calculation;
- no storage resource allows cabins to avoid the cyclic passage argument.

### 2.2 Constructive feasibility for `K_max`

Construct `K_max` phase-shifted copies of the canonical trajectory:

```text
phase_spacing = cycle_time / K_max
```

For every checkpoint and occupancy resource, prove that the phase spacing
satisfies its effective separation. This proves that `K_max` is attainable for
the canonical policy.

### 2.3 Global physical capacity

The stronger desired statement is:

> No feasible EAN solution exists with more than `K_max` active cabins.

Investigate possible counterexamples involving:

- non-periodic finite-horizon operation;
- station waiting or holding;
- finite storage areas;
- accumulation before a bottleneck;
- different Stop/Skip travel times;
- resource occupancy that is not represented by a point headway;
- cabins that do not complete a full cycle.

If the current formula is not a global upper bound, introduce separate terms:

```text
K_canonical = maximum canonical periodic All-Stop-/No-Wait fleet
K_physical = proven maximum number of cabins that can occupy the network
```

The reservoir availability default should use `K_physical` if the intended
contract is global infeasibility for `K_physical + 1`.

## 3. Prove the Warm-Up Bound `W`

The desired reachability statement is:

> Every admissible target placement of up to `K_max` cabins at time `W` can be
> produced by dispatching those cabins from the source reservoir during
> `[0, W)`.

For each target cabin position, back-project its canonical trajectory to the
last source passage:

```text
dispatch_time[c] = W - travel_time(source -> target_position[c])
```

Prove:

- every dispatch time lies in `[0, W)`;
- the dispatch sequence respects the source headway;
- the forward trajectories reproduce the target placement at `W`;
- the depot can supply all required cabins without another processing or
  capacity restriction;
- a cabin located at the source at `W` can be represented by dispatch at `0`
  followed by one complete cycle.

For a complete directed ring and the canonical movement policy, `W =
cycle_time` should be sufficient.

The proof must determine whether this covers:

- only canonical All-Stop-/No-Wait placements;
- arbitrary feasible Stop/Skip placements;
- placements containing station waits or storage occupancy.

If arbitrary feasible states cannot be reconstructed within one canonical
cycle, either narrow the reservoir contract or derive a stronger warm-up
bound.

## 4. Recovery Feasibility

The earlier proposal `H = T + R` under a no-wait recovery policy is not the
current recovery contract. Waiting may be necessary to resolve resource and
merge conflicts after `T`, so a longest no-wait travel time is not by itself a
valid universal recovery bound.

The replacement proof and decomposition program is specified in
`ean_terminal_recovery_feasibility.md`. It investigates:

- whether every feasible state at `T` has a constructive continuation;
- why at most one topological ring suffix is required when every trajectory
  passes the sink;
- how waiting affects the technical time domain without requiring another
  ring cycle;
- and when an explicit recovery feasibility subproblem is needed.

The implemented default remains the fixed certification horizon
`H = T + delta_tail`, which certifies movement but does not require sink
return.

## 5. Proof Certificates

Consider adding machine-readable derivation results:

```text
KCapacityCertificate
WarmUpReachabilityCertificate
```

They should report:

- topology and policy assumptions;
- canonical cycle duration;
- all relevant checkpoint and occupancy separations;
- the selected bottleneck;
- each derived capacity upper bound;
- the constructive `K_max` phase spacing;
- source-to-position distances;
- the resulting `K_max` and `W`;
- whether the result is canonical-only or a proven global bound.

## 6. Counterexample Search

Before changing the production calculation, construct small exhaustive or MILP
searches that attempt to falsify each statement:

- find a feasible solution with `K_max + 1` cabins;
- find an admissible placement not reachable by `W`;
- repeat with Skip enabled;
- repeat with waiting and storage enabled;
- repeat with asymmetric station and rope timings;
- repeat with heterogeneous checkpoint headways;
- test `W - epsilon` to study whether the bound is sharp.

Counterexample search supports the proof work but does not replace a proof.

## 7. Acceptance Criteria

This future task is complete only when:

- the exact theorem domain is documented;
- the capacity calculation has both an upper-bound proof and a constructive
  feasibility proof;
- global capacity is either proved or explicitly separated from canonical
  capacity;
- warm-up reachability is proved for every state claimed by the API contract;
- proof assumptions are validated by the builders;
- machine-readable certificates expose the derivation;
- adversarial tests cover all identified failure modes;
- existing Fixed-Start behavior remains unchanged.
