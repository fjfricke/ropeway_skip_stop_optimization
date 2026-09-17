# Thesis T5R/F2 seed comparison

Stand: 14.09.2026. This focused pilot compares two starting structures on the
same T5R/G800, F2/P0 instance with 3,000 passengers, 15-second release buckets,
Kmax=84, and the `shared_rides` relevant 14-pattern line model.

## Seed construction

| Seed | Restricted construction | Served | Unserved | Fleet | Native result |
|---|---|---:|---:|---:|---|
| All-Stop | phase-optimized regular No-Wait All-Stop | 2,888 | 112 | 84 | optimal, 35.27 s |
| F2 complementary | 42 × stops S1/S3, 42 × stops S2/S4, free exact dispatch timing | 3,000 | 0 | 84 | optimal, 24.87 s total |

Both certificates pass the original independent physical and integer-passenger
validator. The All-Stop statement has the declared scope
`REGULAR_NO_WAIT_ALL_STOP_COMMON_PHASE`. The F2 witness uses Waiting=0, which is
admissible in the full Skip-Stop-with-Waiting domain.

The F2 construction improved natively through 2,800, 2,879, 2,925, 2,992,
2,995, 2,999, and 3,000 served passengers. It did not import a movement hint.
Thus this instance already contains a valid full-service Skip-Stop witness while
the established thesis All-Stop comparator leaves 112 passengers unserved.

## Free 14-pattern comparison

Each seed was then imported into the same unrestricted relevant-catalog model.
Both runs used seed 0, twelve workers, 32 GiB maximum process memory, and 180 s
end-to-end budget. The construction stage received about 115.3 s and the fixed-
route Waiting stage about 32.6 s.

| Hint | Seed accepted | Final served | Final unserved | Fleet | New construction improvements |
|---|---:|---:|---:|---:|---:|
| All-Stop | 36.43 s | 2,888 | 112 | 84 | 0 |
| F2 complementary | 36.39 s | 3,000 | 0 | 84 | 0 |

The models were identical: 218,988 variables, 2,815,554 constraints, 109,872
native resource intervals, and 2,377,620 temporal link constraints. Waiting did
not improve either fixed route plan. The free model retained the imported
pattern family in both runs: 84 All-Stop lines versus a 42/42 complementary F2
split.

## Interpretation

The ablation isolates the start structure. Under identical model and budget,
the free solver does not escape the All-Stop basin, whereas the demand-derived
seed immediately supplies the primary optimum. The practical capacity workflow
should therefore use at least separate All-Stop and demand-derived starts and
select the best independently validated witness before the broad catalog run.
The large catalog remains useful as an improvement stage; it is not a reliable
constructor of the global line structure at this scale.

This is a focused point above the All-Stop full-service threshold, not the full
factor-1.1 demand ladder. The subsequent capacity campaign should generate both
starts at every nested demand level and report the All-Stop proof scope
explicitly.

## Artifacts

All raw artifacts are under
`results/thesis_seed_comparison_20260914/`, specifically:

- `d3000_all_stop_seed/`
- `d3000_f2_seed_fixed84/`
- `d3000_free_relevant_all_stop_hint/`
- `d3000_free_relevant_f2_hint/`
