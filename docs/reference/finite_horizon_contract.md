# Finite horizon validation and continuation claims

Implemented contract: `closed_event_entry_horizon_v1`, 9 September 2026.

## Closed event-entry horizon

For exact event-time activation, T is the passenger service cutoff and H is the operational cutoff. A visit with switch entry at or before H receives its complete route timing. A resource occurrence is included if its follower-entry time is at or before H. Its leader-clear time and required separation are retained in full, even beyond H. A new resource entry after H is excluded, including when it belongs to a visit that began before H.

For a platform-exit waiting occupancy the follower entry is arrival at the waiting position, not departure. The exported plan represents this as `platform_exit_time_seconds - wait_seconds`; the full departure time is the leader clearance. Timing consistency is independently checked against the artifact. Using these validated event fields preserves the DDD export's rounded offsets instead of mixing them with unrounded EAN offsets at the horizon boundary.

DDD/CP uses integer ticks: `entry_tick <= H_tick`. EAN validation uses `is_within_closed_horizon` with a fixed allowance of four floating-point ULPs for arithmetic roundoff. This is far below one microsecond on the project horizons. Continuous EAN event times are not rounded onto a microsecond grid. In particular, H−1 us and H are active; H+1 us is inactive.

The headway/timing feasibility tolerance is **not** added to H. The existing 1e-5 s validation tolerance for DDD-to-EAN fixed-movement passenger evaluation remains unchanged. It controls numerical timing/headway residuals, not horizon membership. This change neither increases the allowed headway error nor creates a post-H clearance certificate.

The native continuous EAN MILP still uses its existing 1e-4 s activation separation (`HORIZON_ACTIVATION_EPSILON_SECONDS`) to encode inactive event inequalities. This numerical modeling separation is not a validator tolerance, and the EAN MILP and tick CP domain are not thereby identical. Validation of an imported CP plan does not assert that the native EAN MILP can generate every such plan. Its encoding was not changed in this gate.

## Coverage

A fixed-start exact prefix must include every visit entering by H. A nonempty trajectory's next switch time after its last visit must therefore be strictly after H. A fixed cabin cannot disappear by exporting an empty trajectory while its start is at or before H. DDD already checks this; EAN now reports `EAN_HORIZON_COVERAGE_MISSING` for the same omission. Reservoir recovery and an inactive EARLIEST start have different contracts and are not subjected to a fictitious always-active fixed-start requirement.

## Three separate statements

1. **Finite model validity:** timings, available boundaries, headways and passengers obey the declared finite domain. The general EAN movement validator does not itself validate a separate initial-placement history or passenger assignment; the existing boundary and passenger validators remain necessary.
2. **Exported-route diagnostic:** `audit_ean_exact_horizon` additionally checks available checkpoint occurrences after H for the visits already exported. It reports violations without adding these constraints to the original model or repairing the plan. Several resource violations may describe one physical interaction. A clean result still says nothing about unexported future visits or omitted initial history.
3. **Safe continuation:** a separately verified extension or invariant must establish that movement remains possible and safe after the evaluated prefix. Neither finite OPTIMAL status nor a clean exported-route diagnostic establishes this.

The audit always reports `continuation_status: NOT_PROVEN`. CP-SAT result payloads now expose this field and `horizon_contract` as well. The proof scopes `FIXED_K_GLOBAL` and `FIXED_MOVEMENT` remain relative to the declared finite domain. Domain fingerprints and historical checkpoints are unchanged because no CP feasible set or objective was changed.

For a future operational certificate, a possible contract is a validated finite transition into a known safe repeating schedule, with exact matching of cabin positions, phases, residual times, resource reservations and passenger obligations. The repeating schedule and wraparound conflicts must themselves be checked. Forcing an arbitrary waiting state, adding a finite tail buffer, or checking only the next merge is insufficient. This certificate is **not implemented or claimed here**, and need not impose periodicity on the preceding optimization horizon.

## Interpretation for the next experiments

The current common contract supports finite algorithm comparisons only. A future stricter route-clearance or continuation requirement changes the feasible domain: give it a new contract/fingerprint, revalidate seeds, and recompute comparable results. Do not silently treat old finite UBs as feasible under the stronger contract. A lower bound from an identified relaxation can transfer only with the appropriate mathematical argument.

Before describing a heuristic's output as an executable continuing operation, require the separate continuation evidence. The present gate does not authorize ignoring the identified tail conflicts. A restricted finite diagnostic may proceed with its scope explicitly stated.

## Implementation and reproducible audit

- [Membership helper](../../src/ropeway_skip_stop_optimization/optimization/ean/horizon_contract.py)
- [EAN validator](../../src/ropeway_skip_stop_optimization/optimization/ean/validation.py), including eager and dominated resource checks
- [Sparse separator and exported-tail diagnostic](../../src/ropeway_skip_stop_optimization/optimization/ean/headway_separator.py)
- [Audit API](../../src/ropeway_skip_stop_optimization/optimization/ean/horizon_audit.py)
- [Regression tests](../../tests/test_optimization_ean_horizon_contract.py)
- [Saved-run audit CLI](../../benchmarks/audit_ddd_cp_sat_horizon.py)

Example, from the software repository:

```sh
.venv/bin/python benchmarks/audit_ddd_cp_sat_horizon.py \
  benchmarks/output/ddd_integrated_cp_sat_warmup/k39/warmup300_600s_seed0 \
  --output benchmarks/output/ddd_horizon_contract_gate/new_warmup300_audit.json \
  --passenger-seconds 30
```

The CLI rebuilds the declared instance and verifies the checkpoint fingerprint. It never optimizes movement or modifies source results. `--passenger-seconds` optionally optimizes only integer passenger assignment for the fixed finite movement; the default is no passenger solve. Existing output paths are rejected. New audits include source config/checkpoint hashes. Results of the first gate are recorded in [the findings](../findings/ddd_horizon_contract_gate.md).
