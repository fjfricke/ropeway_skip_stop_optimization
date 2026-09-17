"""Monotone bracketing and bisection for the regular All-Stop baseline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from time import perf_counter
from pathlib import Path
import json

from .thesis_cases import ExperimentCaseSpec, prepare_experiment_case
from .thesis_cases import prepare_fixed_k_experiment
from ..optimization.ddd.cp_sat_capacity import DddCpSatCapacityOptimizer
from ..optimization.ddd.cp_sat_integrated import DddIntegratedCpSatConfig
from ..optimization.ddd.fixed_k import DddFixedKOperatingMode
from ..optimization.ddd.all_stop_phase import (
    AllStopPhaseConfig,
    prepare_all_stop_phase,
    solve_all_stop_phase,
)
from ..optimization.ddd.all_stop_phase_cells import (
    prepare_all_stop_phase_cells,
    solve_all_stop_phase_cells,
)
from ..optimization.ddd.reservoir_cp_sat_certificate import DddReservoirCpPlan


@dataclass(frozen=True, slots=True)
class AllStopCapacitySearchConfig:
    maximum_demand: int
    initial_demand: int = 100
    time_limit_seconds: float = 120.0
    workers: int = 12
    seed: int = 0
    cabins: int | None = None
    log_search_progress: bool = False
    probe_demands: tuple[int, ...] = ()
    compact_time_links: bool = False
    reference_directories: tuple[str, ...] = ()
    encoding: str = "integrated"

    def validate(self) -> None:
        if self.maximum_demand <= 0:
            raise ValueError("maximum_demand must be positive")
        if not 1 <= self.initial_demand <= self.maximum_demand:
            raise ValueError("initial_demand must lie in [1, maximum_demand]")
        if self.time_limit_seconds <= 0 or self.workers <= 0:
            raise ValueError("time limit and workers must be positive")
        if any(type(n) is not int or not 1 <= n <= self.maximum_demand for n in self.probe_demands):
            raise ValueError("probe demands must lie within the demand search range")
        if self.encoding not in ("integrated", "phase_cells"):
            raise ValueError("All-Stop capacity encoding must be integrated or phase_cells")


def search_all_stop_capacity(
    case_spec: ExperimentCaseSpec,
    config: AllStopCapacitySearchConfig,
    *,
    event_callback=None,
    incumbent_callback=None,
) -> tuple[dict, DddReservoirCpPlan | None, object]:
    """Find adjacent proven feasible/infeasible demands within a hard budget.

    The demand generator is nested, so every feasible value proves all smaller
    prefixes feasible and every proven infeasible value proves all larger
    prefixes infeasible. Unknown solver results never tighten either endpoint.
    """
    config.validate()
    started = perf_counter()
    probes: list[dict] = []
    feasible = 0
    infeasible: int | None = None
    best_plan = None
    best_prepared = None
    probe_tail = min(10.0, max(1.0, config.time_limit_seconds * 0.1))
    reused_references = []
    for directory in config.reference_directories:
        from .thesis_reference_reuse import load_capacity_reference
        lower, upper, plan, prepared = load_capacity_reference(Path(directory), case_spec, config)
        if lower > feasible:
            feasible, best_plan, best_prepared = lower, plan, prepared
            if incumbent_callback is not None:
                incumbent_callback(plan, prepared)
        if upper is not None:
            infeasible = upper if infeasible is None else min(upper, infeasible)
        reused_references.append(directory)
    if infeasible is not None and feasible >= infeasible:
        raise ValueError("inconsistent capacity reference interval")

    def emit(event):
        if event_callback is not None:
            event_callback({**event, "stage": "all_stop_capacity"})

    def probe(demand: int) -> str:
        nonlocal feasible, infeasible, best_plan, best_prepared
        remaining = config.time_limit_seconds - (perf_counter() - started)
        if remaining <= probe_tail:
            return "budget_exhausted"
        prepared = prepare_experiment_case(replace(case_spec, demand_total=demand))
        cabins = config.cabins or prepared.all_stop_reference_cabins
        phase = prepare_all_stop_phase(
            prepared.problem,
            AllStopPhaseConfig(
                cabins=cabins,
                objective="unserved",
                require_full_service=True,
                time_limit_seconds=max(0.001, remaining - probe_tail),
                workers=config.workers,
                seed=config.seed,
                log_search_progress=config.log_search_progress,
                compact_time_links=config.compact_time_links,
                phase_hint_tick=None if best_plan is None else best_plan.trips[0].switch_ticks[0],
            ),
        )
        if config.encoding == "phase_cells":
            cells = prepare_all_stop_phase_cells(phase)
            result, plan = solve_all_stop_phase_cells(
                cells,
                time_limit_seconds=max(0.001, remaining - probe_tail),
                workers=config.workers,
                seed=config.seed,
                phase_hint_tick=None if best_plan is None else best_plan.trips[0].switch_ticks[0],
                log_search_progress=config.log_search_progress,
                deadline=started + config.time_limit_seconds - probe_tail,
            )
        else:
            result, plan = solve_all_stop_phase(
                phase, event_callback=emit,
                deadline=started + config.time_limit_seconds - probe_tail,
            )
        status = result["solver_status"]
        outcome = "unknown"
        if plan is not None and result["metrics"]["unserved"] == 0:
            outcome = "feasible"
            if demand > feasible:
                feasible, best_plan, best_prepared = demand, plan, prepared
                if incumbent_callback is not None:
                    incumbent_callback(plan, prepared)
        elif status == "INFEASIBLE":
            outcome = "infeasible"
            infeasible = demand if infeasible is None else min(infeasible, demand)
        entry = {
            "demand": demand,
            "outcome": outcome,
            "solver_status": status,
            "proven_optimal": result["proven_optimal"],
            "elapsed_seconds": perf_counter() - started,
            "solve": result,
        }
        probes.append(entry)
        emit({"kind": "capacity_probe", **entry})
        return outcome

    # Requested probes are re-solved; their values are never trusted as bounds.
    for demand in config.probe_demands:
        if demand <= feasible or (infeasible is not None and demand >= infeasible):
            continue
        if probe(demand) not in ("feasible", "infeasible"):
            break
    candidate = min(config.maximum_demand, max(config.initial_demand, 2 * feasible))
    while candidate <= config.maximum_demand and infeasible is None and feasible < config.maximum_demand:
        outcome = probe(candidate)
        if outcome not in ("feasible", "infeasible"):
            break
        if outcome == "infeasible" or candidate == config.maximum_demand:
            break
        candidate = min(config.maximum_demand, max(candidate + 1, candidate * 2))

    while infeasible is not None and infeasible - feasible > 1:
        middle = (feasible + infeasible) // 2
        outcome = probe(middle)
        if outcome not in ("feasible", "infeasible"):
            break

    exact = infeasible is not None and infeasible == feasible + 1
    result = {
        "schema": "all_stop_capacity_search_v1",
        "config": asdict(config),
        "case_fingerprint_at_limit": case_spec.fingerprint,
        "proven_feasible_demand": feasible,
        "proven_infeasible_demand": infeasible,
        "capacity_proven": exact,
        "capacity": feasible if exact else None,
        "open_upper_limit": infeasible is None,
        "probes": probes,
        "total_wall_seconds": perf_counter() - started,
        "proof_scope": "REGULAR_NO_WAIT_ALL_STOP_COMMON_PHASE_AND_NESTED_DEMAND",
        "reused_references": reused_references,
    }
    return result, best_plan, best_prepared


def search_fixed_k_all_stop_capacity(
    case_spec: ExperimentCaseSpec,
    config: AllStopCapacitySearchConfig,
    *,
    cabins: int,
    event_callback=None,
) -> dict:
    """Bracket the nested full-service threshold for fixed balanced starts."""
    config.validate()
    if cabins <= 0:
        raise ValueError("cabins must be positive")
    started = perf_counter()
    probes = []
    feasible = 0
    infeasible = None
    probe_tail = min(10.0, max(1.0, config.time_limit_seconds * 0.1))

    def probe(demand: int) -> str:
        nonlocal feasible, infeasible
        remaining = config.time_limit_seconds - (perf_counter() - started)
        if remaining <= probe_tail:
            return "budget_exhausted"
        _, prepared, manifest = prepare_fixed_k_experiment(
            replace(case_spec, demand_total=demand),
            cabins=cabins,
            time_limit_seconds=max(0.001, remaining - probe_tail),
            workers=config.workers,
            seed=config.seed,
            operating_mode=DddFixedKOperatingMode.ALL_STOP,
        )
        run = DddCpSatCapacityOptimizer(
            DddIntegratedCpSatConfig(
                total_time_limit_seconds=max(0.001, remaining - probe_tail),
                num_workers=config.workers,
                seed=config.seed,
                log_search_progress=config.log_search_progress,
            )
        ).solve(prepared.problem, require_full_service=True)
        if run["capacity_feasible"]:
            outcome = "feasible"
            feasible = max(feasible, demand)
        elif run["capacity_infeasible_proven"]:
            outcome = "infeasible"
            infeasible = demand if infeasible is None else min(infeasible, demand)
        else:
            outcome = "unknown"
        entry = {
            "demand": demand,
            "outcome": outcome,
            "elapsed_seconds": perf_counter() - started,
            "case": manifest,
            "solve": run,
        }
        probes.append(entry)
        if event_callback is not None:
            event_callback({"kind": "fixed_k_capacity_probe", **entry})
        return outcome

    for demand in config.probe_demands:
        if probe(demand) not in ("feasible", "infeasible"):
            break
    candidate = min(config.maximum_demand, max(config.initial_demand, 2 * feasible))
    while candidate <= config.maximum_demand and infeasible is None and feasible < config.maximum_demand:
        outcome = probe(candidate)
        if outcome not in ("feasible", "infeasible"):
            break
        if outcome == "infeasible" or candidate == config.maximum_demand:
            break
        candidate = min(config.maximum_demand, max(candidate + 1, candidate * 2))
    while infeasible is not None and infeasible - feasible > 1:
        if probe((feasible + infeasible) // 2) not in ("feasible", "infeasible"):
            break
    exact = infeasible is not None and infeasible == feasible + 1
    return {
        "schema": "fixed_k_all_stop_capacity_search_v1",
        "config": asdict(config),
        "cabins": cabins,
        "proven_feasible_demand": feasible,
        "proven_infeasible_demand": infeasible,
        "capacity_proven": exact,
        "capacity": feasible if exact else None,
        "probes": probes,
        "total_wall_seconds": perf_counter() - started,
        "proof_scope": "FIXED_K_BALANCED_START_ALL_STOP_AND_NESTED_DEMAND",
    }
