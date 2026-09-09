"""One reproducible, bounded reservation-insertion diagnostic on a saved CP run."""

from __future__ import annotations

import json
import math
import resource
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from time import perf_counter

from ..optimization.ddd.cp_sat_certificate import atomic_json, stable_fingerprint
from ..optimization.ddd.fixed_k import DddFixedKOperatingMode, DddFixedKStartPolicy
from ..optimization.ddd.fixed_k_certificate import build_ddd_fixed_k_domain_manifest
from ..optimization.ddd.reservation_checkpoint import DddReservationCheckpointAdapter
from ..optimization.ddd.reservation_models import DddReservationInsertionConfig
from ..optimization.ddd.reservation_optimizer import DddReservationInsertionOptimizer
from ..optimization.ddd.reservation_passenger import DddServiceInsertionCandidateBuilder
from ..optimization.ddd.primal_evaluation import DddEanPassengerPrimalEvaluator
from ..optimization.ddd.reservation_refinement import DddReservationAssignmentRefiner
from .ddd_scaling import build_initial_ddd_network_problem
from .ddd_cp_sat_waiting import with_exit_waiting
from .ddd_cp_sat_warmup import with_empty_warmup
from .ddd_fixed_k_arc_flow import (
    DddFixedKArcFlowRunConfig,
    prepare_ddd_fixed_k_arc_flow_run,
)
from .optimization_events import OptimizationEventKind
from .optimization_live_store import OptimizationLivePaths, OptimizationLiveStore


@dataclass(frozen=True, slots=True)
class DddReservationInsertionRunConfig:
    source_run: Path
    output_dir: Path
    solver: DddReservationInsertionConfig = DddReservationInsertionConfig()
    request_count: int = 100
    group_count: int = 3
    passenger_refinement_seconds: float = 0.0

    def validate(self):
        self.solver.validate()
        if (
            not math.isfinite(self.passenger_refinement_seconds)
            or self.passenger_refinement_seconds < 0
        ):
            raise ValueError(
                "passenger refinement budget must be finite and nonnegative"
            )
        if self.request_count <= 0 or self.group_count <= 0:
            raise ValueError("request/group counts must be positive")
        if self.output_dir.exists():
            raise ValueError("choose a fresh output directory")


def run_ddd_reservation_insertion(
    config: DddReservationInsertionRunConfig, *, prepared_run=None
):
    config.validate()
    started = perf_counter()
    deadline = started + config.solver.total_time_limit_seconds
    config.output_dir.mkdir(parents=True)
    source_config = config.source_run / "config.json"
    source_checkpoint = config.source_run / "incumbent.json"
    raw = json.loads(source_config.read_text())
    raw = raw.get("physical_source_config", raw)
    store = OptimizationLiveStore(OptimizationLivePaths(config.output_dir))
    campaign = config.output_dir.name
    store.append_new(OptimizationEventKind.TRIAL_STARTED, campaign, stage="prepare")
    atomic_json(
        config.output_dir / "config.json",
        json.loads(json.dumps(asdict(config), default=str)),
    )
    try:
        prepared = prepared_run
        if prepared is None:
            prepared = prepare_ddd_fixed_k_arc_flow_run(
                DddFixedKArcFlowRunConfig(
                    example_id=raw["example_id"],
                    cabin_count=raw["cabin_count"],
                    operating_mode=DddFixedKOperatingMode(raw["operating_mode"]),
                    start_policy=DddFixedKStartPolicy(raw["start_policy"]),
                    total_time_limit_seconds=max(1e-6, deadline - perf_counter()),
                    start_layout_time_limit_seconds=max(
                        1e-6, deadline - perf_counter()
                    ),
                    cp_seed_time_limit_seconds=0,
                )
            )
            if raw.get("maximum_wait_seconds", 0):
                prepared = with_exit_waiting(
                    prepared,
                    maximum_seconds=raw["maximum_wait_seconds"],
                    step_seconds=raw["waiting_step_seconds"],
                )
            if raw.get("warmup_seconds", 0):
                prepared = with_empty_warmup(prepared, seconds=raw["warmup_seconds"])
        problem = prepared.problem
        adapter = DddReservationCheckpointAdapter()
        initial = adapter.read(source_checkpoint, problem=problem)
        adapter.write(config.output_dir / "initial.json", problem=problem, plan=initial)
        restored = adapter.read(config.output_dir / "initial.json", problem=problem)
        if (
            restored.solution != initial.solution
            or restored.ride_counts != initial.ride_counts
            or restored.objective_tick != initial.objective_tick
        ):
            raise RuntimeError("reservation initial roundtrip differs")
        intents = DddServiceInsertionCandidateBuilder().build(
            problem, initial, limit=config.request_count, group_limit=config.group_count
        )
        atomic_json(
            config.output_dir / "requests.json",
            {"requests": [asdict(i) for i in intents]},
        )
        manifest = build_ddd_fixed_k_domain_manifest(problem)
        payload = json.loads(json.dumps(asdict(config), default=str))
        payload.update(
            physical_source_config=raw.get("physical_source_config", raw),
            domain_manifest=manifest,
            domain_fingerprint=stable_fingerprint(manifest),
            algorithm_fingerprint=stable_fingerprint(asdict(config.solver)),
            implementation_fingerprint=stable_fingerprint(
                {
                    path.name: sha256(path.read_bytes()).hexdigest()
                    for path in sorted(
                        (Path(__file__).parents[1] / "optimization" / "ddd").glob(
                            "reservation_*.py"
                        )
                    )
                }
            ),
            source_checkpoint_sha256=sha256(source_checkpoint.read_bytes()).hexdigest(),
            source_config_sha256=sha256(source_config.read_bytes()).hexdigest(),
            candidate_policy="three_highest_unserved_groups_early_existing_visits_missing_stop_endpoints",
            repair_scope="nearest_prior_stop_suffix_blocker_expansion",
            wait_policy="bounded_beam_interval_endpoints_and_future_resource_boundaries",
        )
        atomic_json(config.output_dir / "config.json", payload)
        prepare_seconds = perf_counter() - started
        reserve = min(
            4 * config.passenger_refinement_seconds,
            max(0, deadline - perf_counter()) * 0.25,
        )
        with (config.output_dir / "attempts.jsonl").open("w") as output:

            def progress(attempt):
                output.write(json.dumps(asdict(attempt), allow_nan=False) + "\n")
                output.flush()
                store.append_new(
                    OptimizationEventKind.SOLVER_SAMPLE,
                    campaign,
                    stage="repair",
                    elapsed_seconds=perf_counter() - started,
                    payload=asdict(attempt),
                )

            result = DddReservationInsertionOptimizer(config.solver).optimize(
                problem=problem,
                initial_plan=initial,
                intents=intents,
                progress_callback=progress,
                deadline=deadline - reserve,
            )
        best = result.best_plan
        refinements = []
        if config.passenger_refinement_seconds > 0 and perf_counter() < deadline:
            trajectory = problem.resolved_trajectory_problem
            refiner = DddReservationAssignmentRefiner(
                DddEanPassengerPrimalEvaluator(
                    scenario=prepared.scenario,
                    artifact=problem.artifact,
                    objective=problem.objective,
                    waiting_policy=trajectory.waiting_policy,
                    passenger_candidate_build=problem.passenger_build,
                    threads=1,
                ),
                build_initial_ddd_network_problem(
                    trajectory.structural_movement_problem, trajectory.waiting_policy
                ),
            )
            # At most three distinct native finalists, then the unchanged control.
            plans = [
                (f"native_finalist_{i}", p) for i, p in enumerate(result.finalist_plans)
            ]
            if not plans:
                plans = [("native_best", best)]
            if all(p.solution != initial.solution for _, p in plans):
                plans.append(("initial_control", initial))
            for label, plan in plans:
                refined = refiner.refine(
                    problem,
                    plan,
                    deadline=deadline,
                    time_limit_seconds=config.passenger_refinement_seconds,
                )
                refinements.append(
                    dict(
                        candidate=label,
                        status=refined.status,
                        elapsed_seconds=refined.elapsed_seconds,
                        improved=refined.improved,
                        objective=refined.plan.objective,
                    )
                )
                if refined.plan.objective_tick < best.objective_tick:
                    best = refined.plan
        adapter.write(config.output_dir / "incumbent.json", problem=problem, plan=best)
        adapter.export_cp_seed(
            config.output_dir / "cp_seed.json", problem=problem, plan=best
        )
        durations = sorted(a.elapsed_seconds for a in result.attempts)

        def percentile(q):
            return (
                durations[min(len(durations) - 1, int((len(durations) - 1) * q))]
                if durations
                else None
            )

        report = {
            "schema": "reservation_insertion_result_v1",
            "proof_scope": "heuristic_finite_horizon",
            "initial_objective": initial.objective,
            "validated_upper_bound": best.objective,
            "served_passenger_count": sum(best.ride_counts.values()),
            "unserved_passenger_count": sum(best.unserved_counts.values()),
            "lower_bound": None,
            "relative_gap": None,
            "proven_optimal": False,
            "request_count": len(intents),
            "attempt_count": len(result.attempts),
            "statuses": dict(Counter(a.status.value for a in result.attempts)),
            "distinct_movements": result.distinct_movements,
            "improving_attempt_count": sum(
                a.objective is not None and a.objective < initial.objective
                for a in result.attempts
            ),
            "attempt_p50_seconds": percentile(0.5),
            "attempt_p95_seconds": percentile(0.95),
            "repair_seconds": sum(a.repair_seconds for a in result.attempts),
            "passenger_seconds": sum(a.passenger_seconds for a in result.attempts),
            "validation_seconds": sum(a.validation_seconds for a in result.attempts),
            "prepare_seconds": prepare_seconds,
            "optimizer_seconds": result.elapsed_seconds,
            "total_wall_seconds": perf_counter() - started,
            "termination_reason": result.termination_reason,
            "deadline_overrun_seconds": max(0, perf_counter() - deadline),
            "peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            / (1024**2 if sys.platform == "darwin" else 1024),
            "peak_rss_scope": "process_lifetime",
            "roundtrip_passed": True,
            "assignment_evaluation": "integer_greedy_no_mip",
            "native_upper_bound": result.best_plan.objective,
            "post_assignment_ip": refinements or "NOT_RUN",
            "refinement_selection": "three_native_finalists_then_initial_control",
        }
        atomic_json(config.output_dir / "result.json", report)
        store.append_new(
            OptimizationEventKind.TRIAL_COMPLETED,
            campaign,
            elapsed_seconds=report["total_wall_seconds"],
            global_validated_upper_bound=best.objective,
            payload=report,
        )
        return report
    except Exception as error:
        atomic_json(
            config.output_dir / "error.json",
            {"error_type": type(error).__name__, "detail": str(error)},
        )
        store.append_new(
            OptimizationEventKind.TRIAL_FAILED, campaign, payload={"error": str(error)}
        )
        raise
