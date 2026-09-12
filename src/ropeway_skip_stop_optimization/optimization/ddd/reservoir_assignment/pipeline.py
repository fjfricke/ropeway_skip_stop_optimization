"""One-pass load-aware assignment and exact timing pipeline."""

from dataclasses import asdict, dataclass
import math
from time import perf_counter

from ..reservoir_cp_sat_certificate import validate_reservoir_cp_plan
from .master import ReservoirAssignmentMasterConfig, solve_assignment_master
from .timing import ReservoirAssignmentTimingConfig, solve_assignment_timing


@dataclass(frozen=True)
class ReservoirAssignmentPipelineConfig:
    additional_served: int = 10
    assignment_profile: str = "balanced"
    fleet_cap: int | None = None
    master_seconds: float = 60.0
    timing_seconds: float = 120.0
    threads: int = 12
    seed: int = 0
    soft_memory_gb: float = 24.0
    use_witness_hints: bool = True
    fix_routes: bool = True
    log_solvers: bool = False

    def validate(self):
        if type(self.additional_served) is not int or self.additional_served <= 0:
            raise ValueError("additional served must be a positive integer")
        if any(
            not math.isfinite(v) or v <= 0
            for v in (self.master_seconds, self.timing_seconds, self.soft_memory_gb)
        ):
            raise ValueError("invalid pipeline time or memory limit")
        if type(self.threads) is not int or self.threads <= 0:
            raise ValueError("invalid pipeline worker count")
        if type(self.seed) is not int or self.seed < 0:
            raise ValueError("invalid pipeline seed")


def solve_assignment_pipeline(
    problem, reference_plan, config=ReservoirAssignmentPipelineConfig()
):
    """Run each native engine once; never repair or silently fall back."""
    config.validate()
    started = perf_counter()
    reference = validate_reservoir_cp_plan(problem, reference_plan)
    demand = sum(g.count for g in problem.demand_groups)
    target = min(demand, reference.served + config.additional_served)
    if target <= reference.served:
        raise ValueError("reference already serves all demand")
    master, assignment = solve_assignment_master(
        problem,
        ReservoirAssignmentMasterConfig(
            target_served=target,
            profile=config.assignment_profile,
            fleet_cap=config.fleet_cap,
            time_limit_seconds=config.master_seconds,
            threads=config.threads,
            seed=config.seed,
            soft_memory_gb=config.soft_memory_gb,
            log_to_console=config.log_solvers,
        ),
        reference_plan=reference_plan,
    )
    timing = None
    plan = None
    if assignment is not None:
        timing, plan = solve_assignment_timing(
            problem,
            assignment,
            ReservoirAssignmentTimingConfig(
                time_limit_seconds=config.timing_seconds,
                workers=config.threads,
                seed=config.seed,
                log_search_progress=config.log_solvers,
                use_witness_hints=config.use_witness_hints,
                fix_routes=config.fix_routes,
            ),
        )
    result = {
        "schema": "reservoir_assignment_pipeline_result_v1",
        "problem_fingerprint": problem.fingerprint,
        "config": asdict(config),
        "reference": asdict(reference),
        "demand": demand,
        "target_served": target,
        "master": master,
        "timing": timing,
        "has_assignment": assignment is not None,
        "has_valid_plan": plan is not None,
        "improvement_over_reference": None
        if plan is None
        else validate_reservoir_cp_plan(problem, plan).served - reference.served,
        "total_seconds": perf_counter() - started,
    }
    return result, assignment, plan
