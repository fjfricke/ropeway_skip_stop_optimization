# Integrated passenger CP-SAT: first implementation gate

Date: 9 September 2026. Scope: the canonical Fixed-K, fixed-start, No-Wait Five-Station Architecture B instance, Journey Time, integer direct-ride passengers. Implementation details: [reference](../reference/ddd_integrated_cp_sat_passengers.md). Requirements: [plan](../plans/ddd_integrated_cp_sat_passengers.md).

## Decision

The product formulation is a useful new **primal alternative with its own global bound**, but these runs do not demonstrate a better optimality-proof method than complete Arc-Flow. Keep the product implementation and its validated K=39 timetable; do not continue the unary formulation in this first campaign.

The K=39 run improved its imported incumbent from **1,376,000.782880 to 1,272,673.026168**, a **7.51%** reduction in the existing Journey-Time-plus-unserved objective. The new value is also **4.09%** below the previously documented CP/Root-CG value of approximately 1,326,950.671. The final native CP lower bound is **402,843.295830**, leaving **68.35% gap**. There is no global optimality claim.

At K=20, the valid historical optimal timetable was supplied as a seed to both encodings. Both preserve its objective, but neither proves it in five minutes. The product model reaches about 20.13% gap; unary reaches no positive native lower bound. The known K=20 optimum alone is therefore not evidence of successful CP proof performance.

A matched new Arc-Flow performance run, a second CP random seed and additional demand profiles have **not** been run in this gate. Historical Arc-Flow/Root-CG numbers are context, not a controlled same-budget timing comparison. No 30-/60-minute continuation was launched automatically.

## Domain and reproducibility

- Example: `five_station_circle_cw_half_skip_no_wait_headway_b_v0`.
- Start policy: `balanced_reference`; the actual K=39 snapshot is periodic-derived, but future routing is unrestricted by periodicity.
- Operating mode: `skip_stop`; No-Wait; capacity 8.
- Demand: 1,280 people in 20 OD groups, all released at time zero.
- Service and operational horizons: 1,200 s.
- CP workers: 8; random seed: 0; relative and absolute solver gap limits: zero.
- Performance runs were sequential on the same machine; no concurrent solver benchmark or test suite was run during them.
- Cooperative solver shutdown and final serialization/validation can extend the nominal total budget slightly; actual measured wall times are reported below.

| K | Historical problem fingerprint | Full domain fingerprint |
|---|---|---|
| 20 | `2c53481066e498cc29ec206e717911f55d1ac30296cdc5cb8ac05139b35fbd01` | `9a12aad41c4cba5c2e875a2240deb8618122db9de87ff996655465b9635294ee` |
| 39 | `2f82126c06273d2299ab258ca5c5d92acc9d83d829360422f8473c26521cc0f0` | `f8b765b7b1821a2ac4746aed1cbdc3511fc813d47ed5cb8e347dac913ba6186b` |

Full manifests and constructed-model hashes are stored in each result. Input guards and output interoperability were completed around these runs; the movement/passenger constraint formulations used for the reported experiments are unchanged. The original run JSONs are retained. `progress.csv` and the K=39 post-validation/seed exports are separate derived artifacts.

## Results

Costs are passenger-seconds, including the existing penalty for unserved demand. These are native CP bounds; no historical Arc-Flow bound was merged into them.

| K | Encoding | Nominal budget | Actual total wall | Validated UB | Native LB | Gap | Served / total | Peak RSS MB |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 20 | Product | 300 s | 300.35 s | 525,730.908160 | 419,877.358122 | 20.13% | 1,280 / 1,280 | 1,351 |
| 20 | Unary | 300 s | 300.22 s | 525,730.908160 | 0 | 100% | 1,280 / 1,280 | 1,764 |
| 39 | Product | 600 s | 603.22 s | 1,272,673.026168 | 402,843.295830 | 68.35% | 400 / 1,280 | 2,051 |

All three solves ended `FEASIBLE` at the time limit. The initial K=39 solution came from the complete anonymous Arc-Flow one-hour result and was independently reassigned/validated before CP search. The unavailable full export of the better historical CP/Root-CG value was not used as a fabricated seed.

The product K=39 native lower bound remains below the historical anonymous Arc-Flow one-hour bound of about 441,919.534. These durations and starts-of-search differ; this observation does not establish a same-budget ranking. An optimality gap for the new timetable combined with that historical bound is deliberately not reported without the full cross-run domain audit.

Serving 400 people and leaving 880 unserved is still a substantial service limitation. The result improves the stated objective, which is not lexicographic full service. These incumbent values do not prove that K=39 must perform worse than K=20 at optimality; the K=39 global gap is still large.

## Build size

| Case | Movement visits | Route literals | Protected intervals | Ride quantities | Alighting events | Total variables | Total constraints |
|---|---:|---:|---:|---:|---:|---:|---:|
| K=20 product | 725 | 1,450 | 2,175 | 2,560 | 670 | 19,570 | 42,175 |
| K=20 unary | 725 | 1,450 | 2,175 | 2,560 | 670 | 29,620 | 57,585 |
| K=39 product | 1,418 | 2,836 | 5,677 | 5,030 | 1,316 | 43,986 | 92,596 |

Build-only K=20 took about 0.38 s overall. K=39 took 4.53 s including start preparation; the integrated model build itself took about 0.67 s. No time-expanded Arc-Flow graph was built for CP. Peak RSS is the process-lifetime high-water mark, not the size of model data alone.

## Independent validation

**172 tests passed** across the new integrated/assignment/benchmark tests and the existing CP primal/round, Fixed-K, EAN passenger and Reservoir tests. Small cases compare both encodings against full route enumeration with a fixed-movement integer Passenger-IP and complete Arc-Flow. Other tests cover release/cutoff ticks, the historical odd-cycle passenger fixture, seat reuse, bypass overtaking, overlapping platform passages, initial occupancies, horizon completion, hint freedom, shortened visit bounds, unsupported domains, checkpoint corruption and export compatibility.

The final K=39 movement was additionally converted back to the EAN plan and evaluated with the existing independent integer Passenger-IP, with one Gurobi thread and a 30 s maximum solve budget. It returned **OPTIMAL for that fixed movement**, with exactly the same cost **1,272,673.026168**. Native IP solve time was about 0.00035 s; full re-preparation, validation and model construction took 4.43 s. This was a separate postprocess, outside the reported CP budget.

The fixed-IP bound is not a global movement bound. Its agreement shows that the remaining improvement opportunity in this final incumbent is in the timetable, rather than a suboptimal passenger assignment on that timetable.

The checkpointed Reservoir status-reporting failure was separately fixed (`e252ff2`); the legacy CP movement construction was extracted without changing its search semantics (`608b709`). The frontend and thesis source were not changed for this implementation.

## Files and commands

All output paths below are relative to the software repository and are locally gitignored. Git commits contain the implementation, tests and findings, not the large run artifacts.

| Artifact | Path |
|---|---|
| K=20 product run | `benchmarks/output/ddd_integrated_cp_sat/k20/product_300s_seed0_v2/result.json` |
| K=20 unary run | `benchmarks/output/ddd_integrated_cp_sat/k20/unary_300s_seed0/result.json` |
| K=39 product run | `benchmarks/output/ddd_integrated_cp_sat/k39/product_600s_seed0/result.json` |
| Native final CP checkpoint | `benchmarks/output/ddd_integrated_cp_sat/k39/product_600s_seed0/incumbent.json` |
| Independently postchecked checkpoint | `benchmarks/output/ddd_integrated_cp_sat/k39/product_600s_seed0/best_incumbent.json` |
| Arc-Flow-compatible timetable seed | `benchmarks/output/ddd_integrated_cp_sat/k39/product_600s_seed0/arc_flow_seed.json` |
| Fixed-IP validation report | `benchmarks/output/ddd_integrated_cp_sat/k39/product_600s_seed0/post_ip_validation.json` |

Each run directory also contains its config, native solver log, event JSONL and derived `progress.csv`. Event timestamps are relative to the integrated optimizer start, after runner preparation and seed import. Raw CP events are solver-reported samples; final and checkpointed solutions receive independent validation. The initial `k20/product_300s_seed0` attempt stopped at legacy seed import before solving and is not included in the table; its missing-wait-array importer issue was corrected before the `_v2` run.

Reproduce the K=39 run:

```sh
.venv/bin/python benchmarks/run_ddd_fixed_k_cp_sat.py \
  --example five_station_circle_cw_half_skip_no_wait_headway_b_v0 \
  --cabins 39 --start-policy balanced_reference \
  --time-limit 600 --num-workers 8 --seed 0 --cost-encoding product \
  --primal-seed-result benchmarks/output/ddd_exact_anonymous_gate_1h_k39/five_station_circle_cw_half_skip_no_wait_headway_b_v0_arc_flow_exact_anonymous_skip_stop_k39/result.json \
  --log-search-progress \
  --output-dir benchmarks/output/ddd_integrated_cp_sat/k39/repeat_product
```

K=20 used the labeled result under `benchmarks/output/ddd_exact_anonymous_gate/five_station_circle_cw_half_skip_no_wait_headway_b_v0_arc_flow_labeled_skip_stop_k20/result.json`, 300 seconds and the same worker count/seed for each cost encoding.

The next useful experiment is to feed the exported K=39 timetable into complete Arc-Flow and compare against CP with the **same** starting timetable and a declared common budget. A repeat seed and a predeclared additional demand profile are still needed before a broader performance claim. Improving passenger service and proving optimality remain separate evaluation criteria.
