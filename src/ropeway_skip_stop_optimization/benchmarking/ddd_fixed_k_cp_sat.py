from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import json
from pathlib import Path
import resource
import sys
from threading import Lock
from time import perf_counter

from .ddd_fixed_k_arc_flow import (
    DddFixedKArcFlowRunConfig,
    DddPreparedFixedKArcFlowRun,
    prepare_ddd_fixed_k_arc_flow_run,
    _validate_prepared_run_compatibility,
    _load_ddd_fixed_k_arc_flow_result_seed,
)
from .ddd_scaling import build_initial_ddd_network_problem
from ..optimization.ddd.fixed_k import DddFixedKOperatingMode, DddFixedKStartPolicy
from ..optimization.ddd.fixed_k_primal_seed import (
    DddFixedKPrimalSeedFactory,
    load_ddd_fixed_k_root_cg_seed_trajectories,
)
from ..optimization.ddd.cp_sat_certificate import (
    FORMULATION_VERSION,
    atomic_json,
    stable_fingerprint,
    validate_ddd_cp_sat_domain,
    validate_ddd_cp_sat_incumbent,
    read_ddd_cp_sat_checkpoint,
    write_ddd_cp_sat_checkpoint,
    solution_from_cp_sat_payload,
)
from ..optimization.ddd.time_ticks import ddd_seconds_to_tick
from ..optimization.ddd.cp_sat_integrated import (
    DddIntegratedCpSatConfig,
    DddIntegratedCpSatOptimizer,
    build_ddd_integrated_cp_sat,
)


@dataclass(frozen=True)
class DddFixedKCpSatRunConfig:
    example_id: str
    cabin_count: int
    output_dir: Path
    solver: DddIntegratedCpSatConfig = field(default_factory=DddIntegratedCpSatConfig)
    start_policy: DddFixedKStartPolicy = DddFixedKStartPolicy.BALANCED_REFERENCE
    operating_mode: DddFixedKOperatingMode = DddFixedKOperatingMode.SKIP_STOP
    start_layout_time_limit_seconds: float = 120.0
    seed_passenger_time_limit_seconds: float = 30.0
    primal_seed_result: Path | None = None
    primal_seed_checkpoint: Path | None = None
    resume_checkpoint: Path | None = None
    fixed_movement_result: Path | None = None
    build_only: bool = False
    maximum_wait_seconds: float = 0.0
    waiting_step_seconds: float = 0.000001
    warmup_seconds: float = 0.0

    def validate(self) -> None:
        self.solver.validate()
        if not 0 <= self.warmup_seconds < float("inf"):
            raise ValueError("CP-SAT warmup must be finite and nonnegative")
        if not 0 <= self.maximum_wait_seconds < float(
            "inf"
        ) or not 0 < self.waiting_step_seconds < float("inf"):
            raise ValueError(
                "CP-SAT waiting limit/grid must be finite and nonnegative/positive"
            )
        if (
            not self.example_id
            or type(self.cabin_count) is not int
            or self.cabin_count <= 0
        ):
            raise ValueError("CP-SAT benchmark needs an example and positive K")
        if self.start_policy not in (
            DddFixedKStartPolicy.BALANCED_REFERENCE,
            DddFixedKStartPolicy.CANONICAL_ROPE,
        ):
            raise ValueError(
                "CP-SAT benchmark supports canonical_rope or balanced_reference"
            )
        if not isinstance(self.operating_mode, DddFixedKOperatingMode):
            raise ValueError("CP-SAT benchmark operating mode is invalid")
        for value in (
            self.start_layout_time_limit_seconds,
            self.seed_passenger_time_limit_seconds,
        ):
            if not 0 < value < float("inf"):
                raise ValueError(
                    "CP-SAT preparation budgets must be positive and finite"
                )
        if (
            sum(
                p is not None
                for p in (
                    self.primal_seed_result,
                    self.primal_seed_checkpoint,
                    self.resume_checkpoint,
                )
            )
            > 1
        ):
            raise ValueError("choose one CP-SAT seed source")
        if self.fixed_movement_result is not None and any(
            p is not None
            for p in (
                self.primal_seed_result,
                self.primal_seed_checkpoint,
                self.resume_checkpoint,
            )
        ):
            raise ValueError("fixed movement result is itself the seed source")


def _load_result_trajectories(path, problem, raw):
    """Recover older no-wait exports; validate rather than invent wait history."""
    supports = raw.get("trajectory_supports")
    if not isinstance(supports, list) or not supports:
        raise ValueError("CP-SAT seed result contains no trajectory supports")
    if all("wait_seconds" in t for t in supports):
        return _load_ddd_fixed_k_arc_flow_result_seed(path, problem=problem)[0]
    for key, expected in {
        "example_id": problem.artifact.scenario_id,
        "exact_active_cabin_count": problem.fleet_cardinality,
        "operating_mode": problem.operating_mode.value,
        "start_policy": problem.start_policy.value,
        "objective": problem.objective.value,
    }.items():
        if raw.get(key) != expected:
            raise ValueError(f"legacy CP-SAT seed result has incompatible {key}")
    if any(any(w != 0 for w in t.get("wait_seconds", ())) for t in supports):
        raise ValueError("legacy CP-SAT seed contains waiting")
    payload = {
        "trajectory_supports": [
            {
                **t,
                "switch_times_tick": [
                    ddd_seconds_to_tick(s) for s in t["switch_times_seconds"]
                ],
            }
            for t in supports
        ]
    }
    solution = solution_from_cp_sat_payload(problem, payload)
    # Consecutive times must match the actual no-wait route duration exactly.
    # No historical objective or lower bound is accepted through this path.
    return validate_ddd_cp_sat_incumbent(
        problem, solution, {}, provenance=str(path)
    ).solution.trajectories


def run_ddd_fixed_k_cp_sat(
    config: DddFixedKCpSatRunConfig,
    *,
    prepared_run: DddPreparedFixedKArcFlowRun | None = None,
) -> dict:
    """One bounded experiment; never launches a follow-up campaign."""
    config.validate()
    started = perf_counter()
    deadline = started + config.solver.total_time_limit_seconds
    config.output_dir.mkdir(parents=True, exist_ok=True)
    config_payload = json.loads(json.dumps(asdict(config), default=str))
    atomic_json(config.output_dir / "config.json", config_payload)
    setup_config = DddFixedKArcFlowRunConfig(
        example_id=config.example_id,
        cabin_count=config.cabin_count,
        operating_mode=config.operating_mode,
        start_policy=config.start_policy,
        total_time_limit_seconds=config.solver.total_time_limit_seconds,
        start_layout_time_limit_seconds=min(
            config.start_layout_time_limit_seconds,
            config.solver.total_time_limit_seconds,
        ),
        cp_seed_time_limit_seconds=0,
    )
    try:
        prepared = prepared_run or prepare_ddd_fixed_k_arc_flow_run(setup_config)
        _validate_prepared_run_compatibility(setup_config, prepared)
        if config.maximum_wait_seconds > 0:
            from .ddd_cp_sat_waiting import with_exit_waiting

            prepared = with_exit_waiting(
                prepared,
                maximum_seconds=config.maximum_wait_seconds,
                step_seconds=config.waiting_step_seconds,
            )
        if config.warmup_seconds > 0:
            from .ddd_cp_sat_warmup import with_empty_warmup

            prepared = with_empty_warmup(prepared, seconds=config.warmup_seconds)
        problem = prepared.problem
        manifest = validate_ddd_cp_sat_domain(problem)
        prepare_seconds = perf_counter() - started
        checkpoint = (
            config.solver.checkpoint_path or config.output_dir / "incumbent.json"
        )
        seed = None
        fixed_movement = None
        seed_started = perf_counter()
        if not config.build_only or config.fixed_movement_result is not None:
            trajectories = ()
            provenance = None
            if config.resume_checkpoint is not None:
                seed = read_ddd_cp_sat_checkpoint(
                    config.resume_checkpoint, problem=problem, manifest=manifest
                )
            elif config.primal_seed_checkpoint is not None:
                trajectories, _ = load_ddd_fixed_k_root_cg_seed_trajectories(
                    config.primal_seed_checkpoint, problem=problem
                )
                provenance = f"root_cg_checkpoint:{config.primal_seed_checkpoint}"
            elif (
                config.primal_seed_result is not None
                or config.fixed_movement_result is not None
            ):
                source = config.primal_seed_result or config.fixed_movement_result
                raw = json.loads(source.read_text())
                if raw.get("schema") in ("integrated_cp_sat_v1", FORMULATION_VERSION):
                    seed = read_ddd_cp_sat_checkpoint(
                        source, problem=problem, manifest=manifest
                    )
                elif raw.get("formulation_version") in (
                    "integrated_cp_sat_v1",
                    FORMULATION_VERSION,
                ):
                    if raw.get("domain_fingerprint") != stable_fingerprint(
                        manifest
                    ) or stable_fingerprint(
                        raw.get("domain_manifest")
                    ) != stable_fingerprint(manifest):
                        raise ValueError(
                            "native CP-SAT seed result domain fingerprint mismatch"
                        )
                    saved = raw["incumbent"]
                    if saved is None:
                        raise ValueError("native CP-SAT seed result has no incumbent")
                    seed = validate_ddd_cp_sat_incumbent(
                        problem,
                        solution_from_cp_sat_payload(problem, saved),
                        saved["ride_counts"],
                        provenance=f"cp_sat_result:{source}",
                        expected_objective_tick=saved["objective_tick"],
                    )
                else:
                    trajectories = _load_result_trajectories(source, problem, raw)
                    provenance = f"arc_flow_result:{source}"
            elif prepared.seed_trajectories:
                trajectories = prepared.seed_trajectories
                provenance = "balanced_reference"
            if trajectories:
                remaining = deadline - perf_counter()
                if remaining <= 0:
                    raise TimeoutError("CP-SAT seed import exhausted total budget")
                legacy = DddFixedKPrimalSeedFactory(
                    scenario=prepared.scenario,
                    problem=problem,
                    network_problem=build_initial_ddd_network_problem(
                        problem.resolved_trajectory_problem.structural_movement_problem
                    ),
                    passenger_time_limit_seconds=min(
                        config.seed_passenger_time_limit_seconds, remaining
                    ),
                    threads=1,
                ).build(trajectories, provenance=provenance)
                seed = validate_ddd_cp_sat_incumbent(
                    problem,
                    legacy.solution,
                    {
                        q: int(round(v))
                        for q, v in legacy.ride_counts_by_candidate_id.items()
                    },
                    provenance=provenance,
                )
                if abs(seed.objective - legacy.objective_value) > 1e-5:
                    raise ValueError(
                        "legacy seed objective differs from tick validation"
                    )
            if config.fixed_movement_result is not None:
                if seed is None:
                    raise ValueError("fixed movement source contains no validated plan")
                fixed_movement = seed.solution
        seed_seconds = perf_counter() - seed_started
        if config.build_only:
            before = perf_counter()
            built = build_ddd_integrated_cp_sat(
                problem,
                cost_encoding=config.solver.cost_encoding,
                formulation=config.solver.formulation,
                fixed_movement=fixed_movement,
                deadline_monotonic=deadline,
            )
            payload = {
                "solver_status": "NOT_RUN",
                "termination_reason": "BUILD_ONLY",
                "proven_optimal": False,
                "problem_fingerprint": problem.fingerprint,
                "domain_manifest": manifest,
                "domain_fingerprint": stable_fingerprint(manifest),
                "model_fingerprint": built.model_fingerprint,
                "proof_scope": built.proof_scope,
                "model_stats": built.stats,
                "build_seconds": perf_counter() - before,
                "cost_encoding": config.solver.cost_encoding.value,
                "cp_lower_bound": None,
                "validated_upper_bound": None,
                "relative_gap": None,
                "events": [],
            }
        else:
            if seed is not None:
                write_ddd_cp_sat_checkpoint(
                    checkpoint, problem=problem, manifest=manifest, incumbent=seed
                )
            remaining = deadline - perf_counter()
            # Even when preparation consumes the budget, retain a validated
            # seed and return UNKNOWN without starting a fresh full solve.
            solve_config = replace(
                config.solver,
                total_time_limit_seconds=max(1e-9, remaining),
                checkpoint_path=checkpoint,
            )
            event_lock = Lock()
            with (
                (config.output_dir / "solver.log").open("w") as log,
                (config.output_dir / "events.jsonl").open("w") as event_stream,
            ):

                def write_log(line):
                    log.write(line + "\n")
                    log.flush()

                def write_event(event):
                    with event_lock:
                        event_stream.write(
                            json.dumps(
                                {
                                    **event,
                                    "runner_elapsed_seconds": perf_counter() - started,
                                    "peak_rss_mb": resource.getrusage(
                                        resource.RUSAGE_SELF
                                    ).ru_maxrss
                                    / (1024**2 if sys.platform == "darwin" else 1024),
                                },
                                allow_nan=False,
                            )
                            + "\n"
                        )
                        event_stream.flush()

                result = DddIntegratedCpSatOptimizer(solve_config).solve(
                    problem,
                    primal_seed=seed,
                    fixed_movement=fixed_movement,
                    log_callback=write_log,
                    event_callback=write_event,
                )
            payload = result.to_payload()
        payload.update(
            {
                "example_id": config.example_id,
                "exact_active_cabin_count": config.cabin_count,
                "operating_mode": config.operating_mode.value,
                "start_policy": config.start_policy.value,
                "start_layout_kind": prepared.start_layout_kind,
                "prepare_seconds": prepare_seconds,
                "warmup_seconds": config.warmup_seconds,
                "seed_seconds": seed_seconds,
                "total_wall_seconds": perf_counter() - started,
                "checkpoint_path": str(checkpoint) if checkpoint.exists() else None,
                "num_workers": config.solver.num_workers,
                "random_seed": config.solver.seed,
                "peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                / (1024**2 if sys.platform == "darwin" else 1024),
                "peak_rss_scope": "process_lifetime",
            }
        )
        if config.build_only:
            (config.output_dir / "events.jsonl").touch()
        atomic_json(config.output_dir / "result.json", payload)
        return payload
    except Exception as error:
        atomic_json(
            config.output_dir / "error.json",
            {
                "error_type": type(error).__name__,
                "detail": str(error),
                "total_wall_seconds": perf_counter() - started,
            },
        )
        raise
