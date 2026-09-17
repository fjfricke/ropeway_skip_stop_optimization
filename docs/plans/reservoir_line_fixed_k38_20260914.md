# Fixed-K38 evolution comparison

Authorized follow-up after completion of the two 30-minute interval runs.

- R2, 3,074 passengers; existing reservoir physics and 300-second dispatch window.
- Exactly 38 active cabins in every candidate, not merely an upper bound.
- GA mixed_global, population 32, offspring 8, seed 0. Fleet-changing local operators are disabled; global proposals retain K38.
- No imported solution and no deliberately inserted homogeneous All-Stop samples. All-Stop remains an allowed pattern, including in random mixtures and later mutations.
- Initial catalog mixtures: alternating, grouped and random; remainder randomly sampled.
- Interval decoder and waiting fallback unchanged: fixed dispatches during repair, maximum 1,200 seconds per STOP, waiting allowed from time zero, 5 seconds per fresh repair including its existing overhead rules, no aggregate repair quota.
- 1,800 seconds supervised wall time, 12 repair workers, one passenger-IP thread, 32 GiB process-tree RSS and existing system-pressure guard.
- 2,496 served is an external reference only; no hint or objective cutoff.
- Existing genotype deduplication and phenotype evaluation cache remain unchanged. Population-level phenotype deduplication is a separate potential change, not included in this fixed-K comparison.
- Independent certificate validation remains mandatory. Failed construction and unknown repair do not prove fleet infeasibility.

## Verification

45 tests passed across evolution, interval decoder and waiting repair. Additional tests verify all operator profiles retain exact K, fixed-K initialization, invalid fleet rejection, unchanged variable-K default, and the native GA execution path. Synthetic catalog tests check variation algebra; the existing decoder/repair tests check physical semantics.

## Evaluation

Record valid mixed plans and their evolution, construction failures, repair outcomes, native improvements, and pattern composition. Compare time with the variable-K runs without treating the comparison as an isolated K-only ablation: deliberate All-Stop initialization is also removed. No automatic extension.

## Waiting-aware construction follow-up

Implemented `--waiting-construction prefix_first` as an explicit alternative to the backward-compatible `no_wait_first` default. It requires positive Waiting repair budget and the interval decoder. Every insertion checks only necessary occupancy before the first legal waiting opportunity, retaining desired dispatches when permitted instead of seeking a later globally No-Wait-compatible departure first. Fleet, patterns and order are unchanged. Full resource feasibility is still checked by the existing native Waiting model with exact fixed dispatches. No construction-success claim implies a feasible timetable.

The first-return template/lap selection remains the existing No-Wait-derived lifecycle restriction. Prefix construction is not a complete search over dispatches or all possible Waiting lifecycles. The separate ranking issue (missing cabins versus complete-plan conflicts) is not modified by this option and remains open.

Validation: 49 focused tests passed. A small case explicitly has a later feasible No-Wait dispatch, while prefix_first retains the earlier departure and the native solver successfully repairs it with independently validated service. Immutable early conflicts, waiting release, valid No-Wait replay and legacy defaults remain tested.

Frozen K38 replay from the population at approximately 527 seconds: old policy places 37 cabins, last dispatch 294.802975 s, then fails; prefix_first places all 38, last dispatch 185.394387 s, with 1,375 unrepaired physical conflicts. No native K38 timing solve was started for this replay; it is a construction result only. Data: `benchmarks/output/reservoir_line_evolution_20260914/prefix_first_regression_v1/replay.json`.

The ongoing fixed_k38_waiting_live_v1 process uses its already loaded no_wait_first implementation and continues unchanged. No second large solver run is started automatically by this code change.

## Grouped selection restart

Added explicit `--selection-profile grouped` for GA; legacy remains default. Separate valid, complete-unrepaired and incomplete candidates in both survivor and parent selection. At population 32, quotas are 0/24/8 before a valid solution exists and 16/12/4 thereafter. Other population sizes scale those ratios; vacant slots are filled round-robin from available groups without comparing incompatible scores. Parent groups use the same relative weights, renormalized across nonempty groups; tournaments compare only within-group scores.

Valid candidates rank by unserved, complete unrepaired candidates by physical conflict count then total overlap, incomplete candidates by missing cabins. Conflict counts are before repair for unsuccessful candidates. Proved-infeasible candidates can remain as parents for mutated descendants; neither this rank nor UNKNOWN is a global bound. Exact complete schedules are deduplicated using routes, event times, Waiting and return; retain the best known passenger evaluation. If fewer unique schedules exist than requested population places, keep fewer rather than inserting clones.

54 focused tests passed, including survival quotas with 1 missing versus 1,200 conflicts, within-group parent tournaments, empty-group filling, exact schedule deduplication and native GA integration.

Restart requested by user: stop `fixed_k38_prefix_first_live_v1`, preserve its logs, start `fixed_k38_prefix_first_grouped_live_v1` for 30 minutes. Same K38, seed0, no deliberate All-Stop initialization, prefix_first, five seconds per repair, 12 requested repair workers and 32 GiB memory limit. No dispatch relaxation added.

## No-Wait comparison after user-requested stop

Stopped `fixed_k38_prefix_first_grouped_live_v1` at approximately 1,206 seconds: 1,496 evaluations, zero valid plans, 1,232 fixed-candidate infeasibility outcomes. The latest complete-population minimum was 763 physical conflicts, down from about 1,260 initially. This is continued conflict-score improvement, not validated passenger service. `user_stop.json` and `population_at_stop.json` preserve the snapshot and population. Exact continuation of the engine RNG and evaluation cache is not implemented; these artifacts support analysis and a future explicitly implemented population restart.

Started fresh `fixed_k38_no_wait_grouped_live_v1`, authorized 30-minute comparison. Retain exact K38, R2 demand 3,074, seed0, mixed_global, grouped selection, no imported initialization and no deliberate All-Stop initialization. Waiting repair budget is zero. Construction switches to the full No-Wait interval decoder (`no_wait_first`); `prefix_first` requires a positive repair budget and is not appropriate here. Consequently this compares complete No-Wait construction with Waiting-aware construction plus repair, rather than isolating solver overhead alone. All-Stop remains in the admissible catalog. Memory cap remains 32 GiB, workers requested 12; decoder work is serial and the existing passenger IP uses one thread. No additional run is automatically scheduled.

## Corrected comparison: prefix construction with conflict scoring only

User stopped the preceding No-Wait insertion comparison at approximately 539 seconds, 10,262 evaluations and zero valid plans. Its population and snapshot are saved. The change of construction had confounded the intended repair comparison.

`prefix_first` construction is now independent of the repair budget and requires the interval decoder only. With `--waiting-repair-seconds 0`, use exactly the previous immutable-prefix dispatch construction and complete No-Wait resource checks, retaining full conflicting proposals for grouped selection. No Waiting optimizer or passenger optimizer is called for such infeasible proposals. Only physically valid complete No-Wait plans receive passenger evaluation and can become incumbents. Immutable-prefix failures still produce incomplete proposals; construction is not claimed to succeed for every genome. Defaults and positive-budget repair behavior remain unchanged.

Fresh run `fixed_k38_prefix_conflicts_live_v1`: 1,800 seconds, K38, R2 3,074 persons, seed0, mixed_global, grouped selection, no reference/All-Stop initialization, identical prefix policy and boundary configuration to the previous Waiting run, repair disabled. Neither previous population is imported. Direct `unrepaired_candidate` events report pre-Waiting conflicts without a repair attempt and populate the dashboard's unrepaired-candidate series. The retained domain Waiting parameters define the same prefix construction; exported accepted plans in this run have zero Waiting.

Validation: 57 focused tests passed and frontend production build passed. New tests verify identical complete proposals and conflict witnesses with repair disabled, prohibit timing/passenger optimization on a conflicting proposal, check cached events are not counted twice, and reject prefix construction with a non-interval decoder. A later restart of the Waiting variant remains possible; exact engine-state continuation has not been implemented.
