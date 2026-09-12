# Experimental single-use reservoir bound and repair components

The package `optimization/ddd/reservoir_hybrid` is separate from the legacy solvers.
It accepts the existing immutable reservoir domain and canonical certificates.
`benchmarks/run_ddd_reservoir_hybrid.py` provides `replay`, `bound`, `refine`, and
`repair` and experimental `hybrid` phases. Reusable deployments remain gated.
Existing standard solver entry points are unchanged.

## Passenger time encodings

`--journey-encoding legacy` preserves the initial interval-cost formulation.
`ride_bounds` changes each alighting coefficient to at least release plus the
minimum ride duration. This bound includes required STOP at both endpoints and
optimistic intermediate route durations. It does not assume any maximum Waiting
smaller than the original domain permits.

`time_moments` retains shared passenger arc flow f and introduces T and U for its
entry-time and entry-plus-Waiting first moments, measured in passenger-seconds.
These are ordinary continuous LP variables; no multiplication of decision variables
is required. For a real flow of n people entering at tick t and waiting w ticks:

```
f = n
T = n*t / 1e6
U = n*(t+w) / 1e6
```

Each local arc supplies lower/upper bounds on t, u and u-t from its admissible
polygon vertices. Their homogeneous inequalities bound T, U and U-T by multiples
of f. The convex relaxation of the union of zero and positive Waiting includes
every original realization. At boarding, `U + platform_exit*f >= release*f`.
On intermediate nodes, incoming `U + duration*f` sums equal outgoing T sums.
Alighting costs use `T + platform_entry*f`; these arrivals are bounded by the
service horizon and by release plus the whole ride's minimum duration.

For an original certificate, exact timestamps multiplied by its integer quantities
satisfy every time equality and inequality. The original route's physical end
equals the next route's entry. Therefore the summed equality also holds after
cabin labels are removed. Together with the existing shared capacity projection,
this gives a necessary relaxation of every original plan. Its objective equals
the original journey-time objective on the projected plan. Fractional flows and
moment mixing can still prevent the inverse mapping to a physical plan.

Gurobi is floating point. Projected row violations must be within the existing
certificate tolerance. An LP value is used as a global bound only after an optimal
LP status; timeout or a partially feasible simplex iterate does not provide a
new exported bound. Physical and passenger validators remain independent.

## Refinement

`refinement.py` refines only `movement_capacity` with `time_moments`. After a
completed LP, it ranks source cells by positive passenger mass times cell width
and bisects up to three cells. This is a bounded deterministic heuristic, not a
complete DDD search. Releases and old boundaries are retained. Every child arc
must map to a parent arc with the same visit and route. Summing child flows and
their first moments yields a feasible parent relaxation: local time bounds are
subsets, and moment/flow conservation is additive. A monotone ledger retains
previously established bounds. Original seed projection is checked each round.

Resource-window refinement is deliberately separate: splitting a window and
retaining only its pieces can lose the original window inequality. This pilot
does not silently replace the old resource cuts. On the measured reference the
resource and movement time-moment LPs produced the same bound, making the faster
movement profile a reasonable refinement diagnostic.

The diagnostic allows at most five LP rounds including its initial baseline,
300 seconds total, and twice the initial variable count. Three completed rounds
without meaningful increase stop it. None of these limits imply infeasibility or
global optimality of the original integer problem.

On the measured reference the first three completed rounds improved the bound
to 176187.38, 205163.79 and 209409.89. The fourth round reached its remaining
time budget without an optimal LP certificate; the previous best remained valid.

## Local repairs

`ReservoirRepairProblem.prepare` freezes every deployment outside the requested
set, including its original integer passenger assignment. Assigned outside
passengers are subtracted by demand group. Exhausted groups are omitted because
the existing domain requires positive group counts; their IDs are not reassigned.
Residual fleet slots contain the open deployments plus explicitly allowed new
slots, capped by original Kmax minus the number of frozen deployments.

`build_repair` calls the existing reservoir CP builder on this smaller domain.
Frozen resource intervals are calculated from the original usage offsets,
Waiting coefficients, headway and operational-horizon presence rules. They are
added to the original `NoOverlap` resources as constants. Exact state-time
uniqueness includes frozen return events and optional local return events.
No outside movement or passenger decision receives a free solver variable.

Local dispatch symmetry orders only local cabin IDs, so insertion before an
outside deployment is permitted. Reconstruction globally sorts deployments by
dispatch, maps all ride IDs through canonical candidates, and invokes the
original independent validator. Positive ride counts missing from the target
domain raise an error. Outside passengers are never discarded. The implementation
keeps their assignment fixed even after a successful repair; optional global
passenger reassignment is not silently performed.

The seed supplies movement, passenger and derived auxiliary hints. Hints do not
fix decisions. A feasible local objective cutoff preserves every potentially
improving repair. Every native candidate is globally validated; only strict
improvements replace the incumbent and invoke the checkpoint callback. Local
solver bounds are diagnostic raw values, never global lower bounds.

`benchmarks/run_reservoir_repair_diagnostic.py` freezes twelve neighborhoods from
one reference: demand-cost, Waiting-heavy dispatch-neighbor and low-service
replacement choices; sizes three/six with one/two extra slots. Each child has a
ten-second wall budget including startup, with eight seconds requested internally.
Waiting-heavy selection is a proxy; an exact conflict-graph/blocker selector is
not implemented. A timeout remains UNKNOWN and never proves a neighborhood has
no improvement.

The full hint can be validated separately with `verify_fixed_hint=True`; this
diagnostic fixes decisions and must never be counted as optimization progress.
In ordinary optimization the hint remains advisory. `presolve=False` is an
experimental warm-repair setting: it reduced seed acceptance to below one second
on the tested three-/six-deployment neighborhoods. It is not a default change
to the existing CP-SAT solver.

## Sequential coordinator and comparison

`ReservoirHybridOptimizer` in `optimizer.py` accepts an original reservoir problem,
an optional checked primal seed and an optional global bound certificate. Without
a seed, the empty operation is a valid fallback, not a promised useful schedule.
Without a supplied bound, at most 25% of the budget goes to the initial fast
time-moment LP. With a supplied bound, that work is reused and the budget goes
to repairs. The local selector rotates demand, Waiting-heavy and weak-service
neighborhoods and sizes three/six; it recomputes its ranking from the current
incumbent. Every accepted change is validated globally and the ledger is monotone.

The coordinator is a bounded heuristic for the primal search. It does not
exhaustively enumerate neighborhoods and does not promise to close the remaining
global gap. Native local bounds are never promoted. `read_global_bound_result`
selects only completed global LP rounds from locally produced, verified artifacts;
it rejects foreign domains and unfinished/local results. Metadata checks do not
authenticate an arbitrary external mathematical claim.

Example with a verified previously computed bound:

```sh
.venv/bin/python benchmarks/run_ddd_reservoir_hybrid.py \
  --phase hybrid \
  --resume-checkpoint benchmarks/output/model_correctness_audit_20260910/checked_incumbent.json \
  --initial-bound-result benchmarks/output/reservoir_hybrid_refine_20260910_v1/run/result.json \
  --no-repair-presolve --time-limit 600 --seed 0 \
  --output-dir benchmarks/output/new_hybrid_run
```

Use `benchmarks/run_reservoir_hybrid_comparison.py` for the supervised four-run
comparison. Both arms receive the same checkpoint and bound. CP-SAT uses the
existing full reservoir model with the `hints` profile (completed hints, no new
physical constraints), default presolve and twelve workers. The hybrid uses
the same physical kernels on reduced neighborhoods, completed hints, no presolve,
thirty-second repairs and twelve workers. Seeds zero and one are run sequentially.
The shared bound is accounted for equally in certificates; it is not added as
an extra objective-cut row in the CP baseline or as an unsound local cutoff.

The parent supervises a configurable RSS cap (`--memory-gib`, default 4) and each ten-minute wall budget, including worker
startup. The worker is given five seconds less to leave room for extraction and
output. A terminated worker's last independently validated checkpoint is retained,
but the run is marked incomplete. Performance confirmation requires completed
comparisons in both seeds; a memory-limited CP baseline cannot be silently treated
as a completed ten-minute run.

`benchmarks/summarize_reservoir_hybrid.py` exports CSV progress, a Markdown table,
and optional PNG/PDF plots using Matplotlib in a separate plotting environment.
The project's solver dependencies are unchanged.

## Limits and provenance

Size caps are optional (`--max-variables 0 --max-rows 0`). The supervising campaign
enforces 4 GiB RSS and time limits. `--lp-method` selects the Gurobi LP method;
automatic concurrent LP solving can require more memory than dual simplex.
The worker runner alone offers cooperative solver deadlines; use the supervising
campaign for a hard process deadline and memory guard.

Per-run configuration, original domain, Python-source hashes, versions, certificates,
events and result files are saved in new directories. Historical results are never
overwritten. The plan and evolving measured conclusions are in
`docs/plans/reservoir_hybrid_reassessment_20260910.md` and
`docs/findings/reservoir_hybrid_pilot_20260910.md`. This is an experimental
project-specific combination, not a claim that the cited papers guarantee a
performance improvement on this instance.

## Optional empty-tail normalization

`trim_empty_tails(problem, plan)` independently validates the input and output.
It removes unused deployments and cuts a used deployment at its first existing
port return after the complete last passenger-alighting movement, respecting
`return_start_seconds`. All retained route times, waits and passenger assignments
are unchanged. Canonical cabin/ride IDs are translated together. Exact served
count and journey cost must agree before/after.

This operation removes future resource occupations without inserting a new port
movement. It is valid for the supported optional, single-use reservoir lifecycle;
it is not a Fixed-K always-circulating transformation. The feasible search domain
is unchanged. `--trim-empty-tails` (API `normalize_empty_tails=True`) enables it
for the initial seed and accepted repairs. The default is false. The completed
S5 comparison deliberately uses the original unnormalized common seed.

On reference R, normalization reduces 1055 visits to 615, retains 38 deployments
and all 1280 passengers, and preserves cost 368765.821408 exactly. This is a
cost-neutral cleanup, not an objective improvement or measured speedup.

For the first refinement use `--refinement-rounds 3 --journey-encoding time_moments`
with `--bound-profile movement_capacity`: the measured fourth model consumed most
of the five-minute budget without an additional certified bound. This is an
experimental recommendation from one instance, not an automatic default switch.

The first 4 GiB comparison killed the two full CP baselines. The final comparison
uses 8 GiB; only those baselines were rerun. Completed hybrid runs are explicitly
reused with their original provenance because their observed memory stayed below
both caps. No memory-aborted baseline is counted as a completed control.

## Global passenger repair and conflict selection (11 September)

`reservoir_hybrid/global_repair.py` adds `GlobalPassengerRepair(context)` using
an existing `ReservoirRepairProblem`. Its solver keeps only the chosen movement
slots variable, adds outside movement event times as constants, and calls the
existing integer passenger builder over the combined view. This is a separate
experimental repair path; the existing coordinator and defaults are unchanged.

Outside passengers are not subtracted from demand. Boarding/alighting assignments
on both fixed and variable movements share the original global demand balances.
Seats remain indexed by cabin and segment. Unused/end-of-trip outside visits are
removed only from the internal candidate view, with positive hints checked.
Canonical original ride IDs are recovered together with the final dispatch-order
relabeling. All accepted plans pass the original validator. An empty technical
local slot is explicitly disabled for the all-closed case.

`conflict_neighborhoods.py` proposes a STOP-to-SKIP change with through passengers,
shifts that deployment's later event times optimistically, and identifies actual
conflicting reservations of other deployments. It includes both protected resource
intervals and the existing state-time uniqueness rule. All direct blockers must
fit the configured neighborhood cap; oversized proposals are counted and omitted
from this heuristic, never declared globally infeasible. The score is optimistic
passenger time saved per opened deployment. Proposed route/timing changes are
not fixed or treated as feasible certificates.

The bounded ablation runner is `benchmarks/run_reservoir_global_repair_campaign.py`.
It first compares old/global passenger handling on identical neighborhoods, then
screens conflict-selected neighborhoods, then compares the best new neighborhood
with its identical legacy control and full CP-SAT using two fresh seeds.
All trials start from the same original checkpoint. The external global bound
is accounted for separately and local bounds never become global certificates.

Implementation/protocol: `docs/plans/reservoir_global_passengers_conflict_test_20260911.md`.
