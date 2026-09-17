# G500 calibration: implementation and measured solver scope

**Review correction, 15 September:** The archived Arc-Flow runs used an automatic
All-Stop primal start. Their optimal objective values survived independent replay,
but their runtimes do not measure unseeded search. The old statement that the
frontend integration and 30-s resolution calibration were fully complete was too
broad. See the [implementation review](thesis_implementation_review_20260915.md)
for fixes, the new 15-s sensitivity result and outstanding release gates.

Status: completed on 15 September 2026. The accepted calibration is
`results/thesis_g500_calibration_20260914_v2`. Its solver jobs used 3,174.5 s
including the direct All-Stop Journey supplement, below the authorised two-hour
wall-time limit. The earlier `v1` attempt was stopped after its references because
it mistakenly gave the capacity optimizer demand below the All-Stop boundary.
No optimizer result from that attempt is used; its six valid reference runs were
copied into `v2` with explicit reuse provenance.

## Implemented experiment contract

- G500 adds 500 m of free rope per section while retaining separate station paths.
- T5R and T6R expose the twelve planned G500/P0 groups: eight capacity groups
  and four T5R Journey groups.
- `od_endpoints_v1` is a deterministic line catalogue containing All-Stop and
  the exact endpoint mask of every positive OD pair.
- The thesis runner supports phase-optimized All-Stop references, exact-K
  No-Wait evolution, and labelled Fixed-K Arc-Flow in All-Stop or Skip-Stop mode.
- Fixed-K series preserve the demand level. Evolution may transfer only a parent
  pattern sequence between adjacent K stages; dispatches are searched and the
  resulting plan is validated again. Independent seeds receive no transferred plan.
- The read-only frontend exports relative result, event, scenario and certificate
  paths. It shows the twelve groups, reference proof scope, all recorded runs and
  links to the historical optimization and evolution views.

The physical sizing for G500 is:

| Topology | All-Stop cycle | Regular All-Stop headway | Reference fleet | Physical dispatch bound |
|---|---:|---:|---:|---:|
| T5R | 732.0 s | 11.666667 s | 62 | 695 |
| T6R | 878.4 s | 11.666667 s | 75 | 834 |

The large physical dispatch bounds are safety bounds, not recommended search
limits. The measured experiments use exact fixed K values near the regular
All-Stop saturation fleet.

## Reference and resolution calibration

All capacities below refer to the stated regular No-Wait All-Stop common-phase
contract and nested F2/P0 demand. They are not bounds for arbitrary irregular
All-Stop dispatches.

| Case | 30 s releases | 15 s releases | Resolution conclusion |
|---|---:|---:|---|
| T5R capacity, K=62 | exact 2,901 | 2,900 ≤ κ < 3,000 | unresolved at the 1% criterion |
| T6R capacity, K=75 | exact 2,932 | 2,900 ≤ κ < 3,000 | unresolved at the 1% criterion |
| T5R Kref capacity, K=10 | exact 301 | exact 303 | 0.66% capacity difference; this alone does not validate Journey-cost sensitivity |

The 15 s high-load models reached their 240 s budgets before closing the final
100-person bracket. This is an open sensitivity result rather than evidence that
the 30 s capacity is wrong.

## Capacity witness at 1.1 times All-Stop demand

The optimizer demand uses the matching 30 s reference:

| Case | K | Demand | Exact AS capacity | Validated SS service | Absolute margin | First witness |
|---|---:|---:|---:|---:|---:|---:|
| T5R/F2 | 62 | 3,192 | 2,901 | 3,192 | +291 | 1.20 s |
| T6R/F2 | 75 | 3,226 | 2,932 | 3,226 | +294 | 1.06 s |

Both Skip-Stop plans have `U=0`, so they are optimal for the fixed-demand
unserved objective. They establish a capacity advantage over the regular
All-Stop reference without requiring a global Skip-Stop search bound. The T5R
plan uses 31 `S1-S3` and 31 `S2-S4` lines; T6R uses 38 and 37 respectively.

This result must be interpreted correctly. The OD-endpoint mixture is generated
by the demand-oriented initial sampler, so the one-second time is not evidence
that evolution discovered a surprising pattern. It shows that the catalogue,
dispatch decoder, passenger assignment and independent validator can turn that
structural candidate into a complete valid plan. Subsequent 285 s K stages and
independent 585 s T6R seeds all reproduced full service.

| Run family | Evaluations | Valid plans | Valid share | Result |
|---|---:|---:|---:|---|
| T5R K=62/63/69, seed 0 | 588–663 | 246–295 | 39.4–44.5% | all demand served |
| T6R K=75/76/83, seed 0 | 437–492 | 175–198 | 38.4–41.2% | all demand served |
| T6R K=76, seeds 1/2 | 634 / 830 | 259 / 306 | 40.9% / 36.9% | all demand served |

Peak process-tree RSS for evolution stayed below 0.5 GiB. Its dominant cost is
serial decoding and fixed-plan passenger evaluation, not memory.

## Exact Journey comparison

The Journey pilot fixes F2/P0 demand at 150, half of the proven 30 s Kref
All-Stop capacity. All rows use the same K-specific fixed starts and the same
labelled Arc-Flow implementation. Every value is independently validated and
globally optimal with zero numerical gap.

| K | All-Stop passenger-s | Skip-Stop passenger-s | Reduction | SS total time | SS discrete vars | SS constraints |
|---:|---:|---:|---:|---:|---:|---:|
| 10 | 41,976.79995 | 36,049.77995 | 14.12% | 23.2 s | 172,964 | 262,751 |
| 15 | 39,927.19995 | 33,246.09995 | 16.73% | 42.5 s | 257,632 | 390,734 |
| 23 | 38,915.130385 | 31,117.353208 | 20.04% | 59.1 s | 388,750 | 588,778 |

Two additional K=23 seeds reproduced 31,117.353208 with Gap 0 in 55.4 and
61.3 s. Peak process-tree RSS was about 4.0 GiB. All-Stop needs only 8,666 to
19,583 discrete variables because route selection disappears, and solves in
1.0–2.1 s.

All these runs had `seed_kind=all_stop`, including the two additional solver
seeds. The distinct solver seeds are repeated runs with the same initialization.
They must not be described as starting without a primal solution.

## Readiness of the twelve groups

| Groups | Status after calibration | Required next work |
|---|---|---|
| T5R/T6R capacity F2 | pilot-ready | run the nested demand ladder beyond 1.1 and independent T5R seeds |
| T5R/T6R capacity F0/F3/F4 | pending | compute matching AS references and perform short catalogue checks |
| T5R Journey F2 | pilot-ready through K=23 | continue the K ladder until two inconclusive/plateau points |
| T5R Journey F0/F3/F4 | pending | compute Kref demand and compare both operating modes |

The complete twelve-group thesis campaign is therefore not ready to launch as
one unattended batch. The two selected solver roles are supported: labelled
Arc-Flow is exact and practical for the measured low-demand K range; the
OD-catalogue evolution rapidly constructs high-load capacity witnesses. No
result here supports Waiting, free patterns, or arbitrary All-Stop dispatches.

## Recommended budgets for the next campaign

1. Compute 30 s All-Stop references for F0/F3/F4. Repeat 15 s only on a
   representative or outcome-sensitive cell; the high-load sensitivity needs a
   focused bracket near the 30 s value rather than another expansion from 100.
2. For capacity, test nested loads 1.0, 1.1, 1.21, … times κAS at KAS first.
   Stop a run immediately after validated `U=0`. Only open points receive the
   KAS+1 and larger K stages. The current five- and ten-minute budgets were much
   longer than needed on the solved F2 points.
3. For Journey, retain K=10, 15 and 23. Test K=35 next with a three-minute cap;
   continue only while model build and bound progress remain useful. Always run
   the same fixed-start All-Stop control, which is inexpensive.
4. Keep the 32 GiB supervisor cap. The measured maximum was about 4 GiB, so CPU
   time and Arc-Flow model growth are the active limits.

Raw campaign metadata is in
`results/thesis_g500_calibration_20260914_v2/campaign.json`; the portable viewer
index is `frontend/public/generated/thesis/index.json`.
