# Final capacity study results (17 September 2026)

## Contract

All reported runs use deterministic P0 demand, the G500 geometry, direct
integer passenger assignment, and the shared reservoir port. The evolutionary
runs use independent cabin-pattern genes, No-Wait movement, and the
lexicographic objective (unserved passengers, then passenger journey time).
Reaching full service does not terminate the search. Every active cabin remains
in service until its first complete return at or after the service deadline.

All certificates listed below passed the independent movement and passenger
validator under this lifecycle contract.

## Evolutionary main runs

| Run | Case | K | Demand | Served | Unserved | Journey time (person-s) | Evaluations |
|---|---|---:|---:|---:|---:|---:|---:|
| A1 | T5/F2 | 62 | 2,918 | 2,918 | 0 | 617,562.312 | 2,143 |
| A2 | T5/F2 | 62 | 3,210 | 3,210 | 0 | 1,028,002.739 | 2,432 |
| A3 | T5/F3 | 62 | 7,153 | 3,720 | 3,433 | 9,637,600.751 | 1,527 |
| A4 | T5/F3 | 62 | 7,869 | 3,720 | 4,149 | 11,198,259.279 | 1,476 |
| B1 | T5/F2 | 62 | 3,210 | 3,210 | 0 | 1,031,960.889 | 2,495 |
| B2 | T5/F2 | 62 | 3,210 | 3,210 | 0 | 1,037,868.761 | 2,362 |
| C1 | T6/F2 | 75 | 3,237 | 3,237 | 0 | 911,659.564 | 2,510 |

All three independent T5/F2 overload runs served all 3,210 passengers. A2 was
the best of these runs and therefore became the common CP-SAT seed. Its final
pattern mix contains 31 `stop_S1_S3` and 31 `stop_S2_S4` cabins. The T6
transfer run also reached full service with a 38/37 split of the corresponding
two patterns.

The F3 screenings did not approach the regular All-Stop capacity. Both ended at
3,720 served passengers. Under the tested ten-minute budget, independent
evolution over the five minimal OD masks did not construct a competitive F3
schedule. These time-limited results are not infeasibility proofs.

## Full CP-SAT post-optimization

Both runs started from the same validated A2 certificate. Dispatch, STOP/SKIP,
active fleet, passenger assignment, and (in D2) Waiting remained free.

| Run | Waiting | Served | Active K | Journey time (person-s) | Change from seed |
|---|---:|---:|---:|---:|---:|
| A2 seed | 0 s | 3,210 | 62 | 1,028,002.739 | — |
| D1 | 0 s | 3,210 | 62 | 1,011,764.784 | −1.580% |
| D2 | ≤120 s | 3,210 | 62 | 1,011,822.189 | −1.574% |

CP-SAT improved the evolutionary seed in both variants. D1 ended 57.405
person-seconds better than D2, so the additional Waiting freedom produced no
observed benefit within 30 minutes. Both native lower bounds remained zero;
their reported 100% gaps therefore provide no useful optimality statement.

## Fixed-K sensitivity

| Run | K | Served | Unserved | Journey time (person-s) | Pattern mix |
|---|---:|---:|---:|---:|---|
| E1 | 56 | 3,210 | 0 | 1,482,625.378 | 28 / 28 |
| A2 | 62 | 3,210 | 0 | 1,028,002.739 | 31 / 31 |
| E2 | 69 | 3,210 | 0 | 672,578.646 | 35 / 34 |

All three fixed fleets achieved full service. Relative to K=62, the observed
journey-time value was 44.2% higher at K=56 and 34.6% lower at K=69. These are
heuristic fixed-K outcomes rather than proofs that the displayed values are
optimal.

## Interpretation

The final study supports the restricted-pattern evolutionary method for the F2
capacity regime: it repeatedly found full-service schedules above the regular
All-Stop profile boundary, transferred to T6, and supplied a useful primal seed
to the full CP-SAT model. CP-SAT then delivered a modest additional journey-time
improvement but no informative bound.

The same method did not transfer successfully to F3 under the short screening
budget. The result suggests that the minimal OD-mask representation and search
dynamics are well aligned with the two-flow F2 structure but are insufficient
for the more coupled F3 demand. It does not justify a general claim that
Skip-Stop is ineffective for F3.

Machine-readable summary:
`results/thesis_capacity_final_campaign_20260917_summary.json`.
