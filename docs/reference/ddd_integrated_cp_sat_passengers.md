# Integrated Fixed-K CP-SAT with integer passengers

Implementation: `integrated_cp_sat_v2`, September 2026. This is a separate optimizer; the existing CP primal oracle remains available and shares the extracted movement builder. Performance findings are recorded separately in `docs/findings/ddd_integrated_cp_sat_gate.md`.

**Horizon validation updated:** EAN and DDD now agree on the closed event-entry horizon; numerical headway tolerances no longer extend H. The saved 300-s warmup plan now passes the independent finite validation. All three audited Waiting plans nevertheless have headway violations among their exported post-H events. Safe continuation remains unproven. See the [contract](finite_horizon_contract.md) and [G0 findings](../findings/ddd_horizon_contract_gate.md). CP feasible sets and historical domain fingerprints are unchanged.

## Supported problem

The solver accepts the canonical `DddFixedKTrajectoryProblem` for one directed ring, fixed starts and exact fleet size, No-Wait or bounded end-of-platform waiting, one STOP route per state, deterministic route durations, integer homogeneous OD/release demand and integer cabin capacity. Its objective is Journey Time with the existing finite-service unserved cost. All-Stop is supported through `resolved_trajectory_problem`.

The implementation rejects other waiting modes, other objectives, inconsistent EAN/DDD movement data, non-ring transitions, ambiguous STOP routes, insufficient visit bounds and boundary-only reduced resources. It does not optimize initial placement, dispatch from a reservoir or impose periodic operation. Multiple future loops of cabin movement are allowed up to the canonical operational horizon. Passenger rides come from the exact supplied structural candidate list; the solver does not add or remove multi-loop passenger rides.

`T` is the passenger service cutoff; `H` is the operational horizon. These happen to coincide at 1,200 seconds in the current Five-Station B reference. All physical times use the existing one-million-ticks-per-second DDD representation. Releases and horizons must already lie on this grid; sub-tick values are rejected rather than shifting the original Arc-Flow cost constant. This does not create a variable or arc per microsecond.

## Formulation and equivalence argument

### Empty warmup experiment

The benchmark option `--warmup-seconds B` retains the exact initial cabin snapshot and boundary occupancies at t=0, shifts every demand release by B, and increases T and H by B. The service-window length and each group's unserved penalty `T - release` remain unchanged. The normal physical constraints apply throughout the empty prefix; no additional route or waiting decisions are fixed. This optimizes a reachable state at demand release, not arbitrary initial placement. The artifact, visit bounds and passenger candidates are rebuilt for the longer horizon. The default B=0 preserves the previous experiment.

Finite seed trajectories are dropped by this transformation because their continuation beyond the old horizon is not certified. Supply a separately validated complete seed if desired. In particular, individually periodic cabin routes do not imply that their mixed fleet remains conflict-free beyond the checked horizon. Native checkpoints retain strict domain matching, including releases and horizons.

Implementation: `benchmarking/ddd_cp_sat_warmup.py`. Experiment definition and seed protocol: [warmup plan](../plans/ddd_cp_sat_warmup.md).

### Movement and passengers

For each cabin and visit there are event time, active-visit and route-selection variables. A visit is active exactly when its event time is at most H. Exactly one route is selected at an active visit. Its duration plus the chosen exit wait determines the next time; inactive continuation leaves time unchanged. Waiting is zero on SKIP and inactive visits. The final event must be inactive. A minimum-duration traversal verifies that the supplied visit bound covers even the fastest route sequence.

Each selected resource usage creates the existing protected interval `[event + follower_offset + follower_wait_coefficient*w, event + leader_offset + leader_wait_coefficient*w + separation_after)`. A usage is present exactly when its entry is at most H. Its protected end is not clipped at H. Fixed boundary occupancies use the same interval convention with the start clipped at zero. `NoOverlap` applies to each configured resource. This represents the current constant and predecessor-behavior headway rules, not a generic pair-dependent matrix or exclusive occupancy of the whole station.

For a canonical candidate q, `y[q]` is an integer between zero and `min(group_count, capacity)`. Its `used` literal is equivalent to `y[q] >= 1`. Positive assignments require STOP at boarding and alighting, boarding after release and zero, ordered boarding/alighting, and both events by T. Boarding uses actual platform exit including the current wait, alighting platform entry before the current wait. This preserves the existing EAN boarding convention: demand released during the hold can board by departure. Closed-door holding would require a separate boarding cutoff. Unused candidates impose no temporal restrictions on movement. Demand is partitioned into assigned and unserved quantities.

For each cabin interval v, all `y[q]` with `board(q) <= v < alight(q)` share its capacity. This permits seats to be reused after alighting and passengers to remain aboard through intermediate STOP or SKIP visits.

Let `A[e]` be the total number alighting at event e with time `tau[e]`, and

`F0 = sum_g count[g] * max(0, T - release[g])`.

The integer-tick objective is `F0 + sum_e A[e] * (tau[e] - T)`. This equals the direct served/unserved cost sum because every served candidate obeys release <= boarding <= alighting <= T. Two encodings implement this same expression:

- `product`: one multiplication equality per alighting event.
- `unary`: at most C ordered Boolean levels per event, each with a conditionally activated event-time cost.

The movement recurrence establishes a mapping between route sequences, grid-aligned exit waits and their unique event times. The headway intervals encode the same two-way separation disjunctions as the reference model. The structural y variables then represent exactly the integer ride assignment and capacity constraints for that movement. Conversely, every feasible movement/assignment in the declared domain can populate these CP variables; the derived alighting aggregates and either cost encoding add no restriction. This argument depends on the stated domain checks and the supplied candidate list. It is not a claim about continuous-time variants, other initial placements or passenger paths omitted from that list.

## Validation and identity

`cp_sat_certificate.py` is independent of CP variables. It verifies canonical reference trajectories, restores boundary occupancies from the problem, checks protected intervals in integer ticks, checks every positive ride count, endpoint, release, demand balance and shared capacity, and recomputes the original served/unserved objective. Invalid exported assignments cannot become validated upper bounds or checkpoints.

Historical `problem_fingerprint` values remain unchanged. They do not include all timing, capacity and candidate data. The additional solver-independent `domain_manifest` and `domain_fingerprint` contain the actual movement core, tick timing data, starts, boundaries, demand, capacity and candidates. `model_fingerprint` also identifies the constructed CP model. Native checkpoint imports require the domain fingerprints to match. Legacy timetable imports are independently revalidated and reassigned; they contribute no historical lower bound.

Global search results use `FIXED_K_GLOBAL`. A solve with a fixed movement plan uses `FIXED_MOVEMENT`; its bound is only for that restricted assignment problem. Hints alone do not change the global scope. There are no route exclusions, Hamming constraints, top-N passenger preferences or first-solution stopping rules in the integrated global solver.

New solver payloads additionally identify `horizon_contract=closed_event_entry_horizon_v1` and `continuation_status=NOT_PROVEN`, including for finite `OPTIMAL` results. These labels distinguish finite optimality from operational continuation; they do not change checkpoint compatibility.

Both solver gap limits are zero. A time-limited native floating bound is conservatively converted with downward rounding and the analytic zero floor. Objective expression magnitudes are limited to below 2^53 for exact integer reporting, and OR-Tools model validation also checks integer-expression validity. An `OPTIMAL` result additionally requires independent objective validation and agreement with the native bound to within 1/4 tick, allowing floating error from the solver's internal objective normalization. The integer optimal objective is then the closing bound; this rule never promotes a time-limited result to optimality.

## Exit waiting (v2)

Set `--maximum-wait-seconds 1200` for the first bounded-wait experiment. The default remains zero (No-Wait). `--waiting-step-seconds` defaults to the canonical tick, 0.000001 seconds; no time-expanded graph or enumeration of all wait values is built. Native validation checks grid membership arithmetically. The benchmark retains the existing start-builder restrictions (including its All-Stop fleet precheck); it is not a general Waiting initial-placement solver. The fixed start snapshot is prepared in No-Wait and then lifted by `benchmarking/ddd_cp_sat_waiting.py`; travel times, starts and passenger demand remain fixed. Initial pre-zero movement stays fixed. Added platform-exit boundary occupancies are reconstructed from the known immediately preceding route, with a guard that older prefixes cannot retain an omitted protected occupancy.

The platform-exit resource is occupied from arrival at the waiting position until departure plus its headway. Exit-switch/service-mechanism resources shift with the wait. This is the existing one-position end-of-platform model; it does not introduce an arbitrary-capacity FIFO buffer. Resource constraints can force a shorter wait than the configured cap.

Waiting is allowed to carry the last active route past H. A resource entered by H keeps its complete protected interval beyond H, while resources first entered after H are outside the existing operational scope. The model does not certify an indefinitely sustainable continuation after H. In particular, W=1200 is an explicit bounded experiment, not a proof that arbitrary unbounded waiting is represented without loss. A late wait can hold a cabin beyond passenger service; it cannot create service after T.

The waiting domain manifest includes its policy, cap and grid as well as the new movement/resource core. Bounds of the No-Wait problem are never transferred to the Waiting problem. Old v1 checkpoints are readable only when their exact domain manifest still matches; a legacy timetable export may be used as a cross-domain primal seed after fresh physical and passenger validation. V2 payloads contain both wait ticks and seconds and reject disagreement between them. Fixed-movement diagnostics fix the waits as well as the routes and times.

## Files

| File under `src/ropeway_skip_stop_optimization/` | Responsibility |
|---|---|
| `optimization/ddd/cp_sat_movement.py` | Shared movement construction, including bounded-wait variables and resource occupancies |
| `optimization/ddd/cp_sat_passenger.py` | Complete structural integer assignments, capacity and both cost encodings |
| `optimization/ddd/cp_sat_certificate.py` | Domain checks, independent incumbent validation and atomic checkpoints |
| `optimization/ddd/cp_sat_integrated.py` | Search, hints, fixed-movement diagnostics, bounds and result extraction |
| `benchmarking/ddd_fixed_k_cp_sat.py` | Canonical instance preparation, imports, shared budget and artifact writing |

## CLI

Run from the software repository with its Python environment:

```sh
.venv/bin/python benchmarks/run_ddd_fixed_k_cp_sat.py \
  --example five_station_circle_cw_half_skip_no_wait_headway_b_v0 \
  --cabins 20 --start-policy balanced_reference \
  --time-limit 300 --num-workers 8 --cost-encoding product \
  --output-dir benchmarks/output/ddd_integrated_cp_sat/k20/example_run
```

Use `--build-only` for model statistics without a solve. `--cost-encoding unary` selects the alternative exact encoding. Optional seed sources are mutually exclusive:

- `--primal-seed-result PATH`: complete Arc-Flow result or native CP result/checkpoint.
- `--primal-seed-checkpoint PATH`: existing Root-CG checkpoint.
- `--resume-checkpoint PATH`: native CP checkpoint, validated against the full domain manifest.
- `--fixed-movement-result PATH`: Arc-Flow result or native CP result/checkpoint, with restricted proof scope.

Native `result.json` also exposes the existing Arc-Flow timetable schema at the top level, so the Arc-Flow runner can consume it through `--primal-seed-result`. A native checkpoint is a warm start, not persistence of the search tree. Older no-wait Arc-Flow exports without a `wait_seconds` array are accepted only if their complete times reconstruct a valid no-wait trajectory. This path does not infer unobserved waiting or reuse a source lower bound.

Outputs: `config.json`, `result.json`, `events.jsonl`, `incumbent.json` and, for optimization, `solver.log`. Enable `--log-search-progress` for the detailed native log. Failures produce `error.json`. Checkpoint writes are atomic. Solver callbacks capture assignments and periodically validate/checkpoint them without starting Gurobi; a worse CP candidate cannot replace a better saved external seed. The final result retains the best validated external or native incumbent even if CP reports UNKNOWN. A validated seed contradicting CP infeasibility is treated as an error.

The runner charges preparation, imports and passenger seed evaluation to the total time budget, then gives the remaining time to build/solve. CP-SAT checks its limit cooperatively; solver shutdown, final validation and atomic writes may create a small measured overrun. This is not a hard process-kill deadline. Callback validation is included in solve wall time, not added a second time. `peak_rss_mb` is the process-lifetime high-water mark, not isolated allocation by a single run. Raw solver incumbent/bound events are distinguished from the final independently validated result.

## Tests and remaining experimental work

The new tests compare both encodings with exhaustive route enumeration plus the independent Passenger-IP and complete Arc-Flow on small cases. They exercise release boundaries, service cutoff ticks, shared capacity, seat reuse, overlapping platform passages, bypass overtaking, headway interval contact, resource activity at and after H, unserved demand, hints, fixed scope, checkpoint tampering and fingerprint omissions. Existing CP primal/round, Fixed-K, EAN passenger and Reservoir tests are also run.

A faster K=39 solve or stronger native CP lower bound is an empirical question. Passing these tests and obtaining a compact model does not establish a performance advantage. See the gate findings before launching a larger campaign.

## Experimentelle binäre Reisezeitkosten (11.09.2026)

`DddCpSatCostEncoding.BINARY` beziehungsweise `--cost-encoding binary` ergänzt
`product` und `unary`. Standard bleibt `product`. Fixed-K und Single-Use-Reservoir
verwenden denselben Passagierbaustein; Kapazitätsziele erzeugen weiterhin keine
Reisezeit-Kostenhilfen.

Bei `0 <= n <= Q` erhält jedes Ausstiegsereignis `Q.bit_length()` Boolesche Bits
mit `n = Summe(2^j * b_j)`. Reifizierte Gleichungen setzen `z_j = t` für aktive
Bits und andernfalls `z_j = 0`. Der Kostenterm ist exakt
`Summe(2^j * z_j) - H*n`; Nichtbedienungskonstante, Integer-Mengen und Tickzeiten
bleiben unverändert. Die ursprüngliche Grenze `n <= Q` verhindert übergroße
Bitkombinationen auch bei Q ungleich `2^m-1`. Binäre Hilfswerte besitzen eine
eindeutige Darstellung für jedes zulässige `(n,t)`.

Der vollständige Hintpfad setzt Bits und zugehörige Zeitwerte. `cost_auxiliary_count`
erfasst je Bit beide Variablen; der Modell-Fingerprint ändert sich, der physikalische
Fingerprint und historische Ride-IDs nicht.

Der [begrenzte Vergleichsplan](../plans/reservoir_binary_cost_comparison_20260911.md)
beschreibt Korrektheit und Freigabekriterien. Eine mathematisch äquivalente
Darstellung ist keine Zusage besserer Suchleistung.
