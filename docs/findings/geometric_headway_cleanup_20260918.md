# Geometric headway cleanup — 2026-09-18

The comparison is against the working tree's **already geometric** thesis path,
not against the older fault-headway domain. This change removes unused inputs and
auxiliaries; it does not further relax physical constraints.

## Small before/after build

T5R/G500, K2, F2 with 12 passengers, No-Wait, 1 ms, 2364 s service plus 300 s tail,
free All-Stop/BD/CE types, served objective. Native CP-SAT proto sizes before presolve:

| Formulation | Variables before → after | Constraints before → after | Resource intervals |
|---|---:|---:|---:|
| EAN | 1386 → 1384 | 3394 → 3362 | 282 → 282 |
| No-Wait templates | 1304 → 1284 | 2946 → 2908 | 354 → 354 |

The physical fingerprint is unchanged:
`fcc1c32a173aefb0dde2e129ada62f2f7c11a5d8fce9f69f9403812ec06055a9`.
Geometric resources were already active before this cleanup; their intervals remain.

## Representative build-only checks

| Model | Variables | Constraints | Additional size |
|---|---:|---:|---|
| OIP templates, K62, F2 2266, free All-Stop/BD/CE, served | 39684 | 89372 | 10974 resource intervals |
| Journey labelled arc-flow, K10, balanced fixed starts, full service | 53935 | 91060 | 7260 arcs; 8935 resource rows |

Both use T5R/G500 and 2364 + 300 s. The journey build uses the physical example's
small default demand, not a newly calibrated experiment. Its passenger encoding is
`legacy`; counts are diagnostic and not forecasts for calibrated thesis cases.
No solve, presolve, calibration or campaign was run for these measurements.

The arc-flow regression reconstructs the old geometric factory path and verifies
identical problem fingerprints, arcs, boundary intervals and resource cliques.
Gurobi's geometric EAN already omitted fault-history variables; a build-only test
now checks that explicitly while retaining geometric ordering variables.

## Validation

Result: **147 Python tests passed**, 9 deliberately deselected; **18 frontend
safety tests passed**. TypeScript checking and `git diff --check` passed.

Python coverage includes geometric/legacy headways, OIP domain and type catalogs,
template boundary replay, independent passenger checking, resource reduction,
arc-flow preparation/solves on small cases, schema migration and stale-cache rejection.
Local K62 certificate integration tests are excluded from the small regression suite.

```sh
.venv/bin/pytest -q tests/test_headway_geometric_contract.py tests/test_oip_type_catalog.py tests/test_oip_template_replay.py tests/test_oip_pattern_waiting.py tests/test_oip_geometric_reduction.py tests/test_optimization_headway_policy.py tests/test_examples_artificial_headway_cases.py tests/test_oip_domain.py tests/test_optimization_ean_derived_headway.py tests/test_optimization_headway_resource_reduction.py tests/test_optimization_ddd_arc_flow.py -k 'not saved_k62 and not above_capacity and not snapshot and not dual_cuts and not application and not seeded'
```

Frontend checks (from `frontend/`): `npm test -- --run src/safety` and
`npx tsc --noEmit`. Geometric inputs no longer trigger missing emergency-parameter
errors; historical mechanism values remain readable. Historical artifacts and
thesis prose have not been modified.
