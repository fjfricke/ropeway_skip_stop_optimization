"""Fixed-start integrated CP-SAT minimizing unserved persons, not Journey Time.

Uses unchanged movement physics and integer passenger assignment. Native primal
checkpoints retain independently recomputed Journey Time for compatibility;
capacity bounds live only in this result schema, in persons.
"""

from dataclasses import dataclass, field
from time import perf_counter

from ortools.sat.python import cp_model

from .cp_sat_certificate import (
    stable_fingerprint,
    validate_ddd_cp_sat_domain,
    validate_ddd_cp_sat_incumbent,
    solution_from_cp_sat_payload,
    write_ddd_cp_sat_checkpoint,
)
from .cp_sat_integrated import (
    DddIntegratedCpSatConfig,
    DddIntegratedCpSatModel,
    _movement_values,
    _raw_incumbent,
)
from .cp_sat_movement import build_ddd_cp_sat_movement
from .cp_sat_passenger import build_ddd_cp_sat_passenger_assignment
from .cp_formulation import formulation_identity, prepare_cp_structure, apply_cp_temporal
from .cp_hint_completion import complete_cp_hints
from .fixed_timetable_capacity import conservative_count_bound


@dataclass(frozen=True)
class DddCpSatCapacityOptimizer:
    config: DddIntegratedCpSatConfig = field(default_factory=DddIntegratedCpSatConfig)

    def solve(
        self,
        problem,
        *,
        primal_seed=None,
        fixed_movement=None,
        event_callback=None,
        log_callback=None,
    ):
        self.config.validate()
        started = perf_counter()
        deadline = started + self.config.total_time_limit_seconds
        manifest = validate_ddd_cp_sat_domain(problem)
        incumbent = None
        if primal_seed is not None:
            incumbent = validate_ddd_cp_sat_incumbent(
                problem,
                primal_seed.solution,
                primal_seed.ride_counts,
                provenance="capacity_seed",
            )
        if fixed_movement is not None:
            checked = validate_ddd_cp_sat_incumbent(
                problem, fixed_movement, {}, provenance="fixed_capacity_movement"
            )
            if incumbent is not None and incumbent.solution != checked.solution:
                raise ValueError("seed differs from fixed movement")
            if incumbent is None:
                incumbent = checked
        events = []

        def emit(item):
            item = {"elapsed_seconds": perf_counter() - started, **item}
            events.append(item)
            if event_callback:
                event_callback(item)

        def score(x):
            return sum(x.unserved_counts.values())

        def save(x):
            if self.config.checkpoint_path:
                write_ddd_cp_sat_checkpoint(
                    self.config.checkpoint_path,
                    problem=problem,
                    manifest=manifest,
                    incumbent=x,
                )

        built = None
        status = cp_model.UNKNOWN
        lower = None
        raw_bound = None
        response = None
        solve_seconds = 0
        hint_seconds = 0.0
        validation_seconds = 0.0
        try:
            if perf_counter() >= deadline:
                raise TimeoutError()
            movement = problem.resolved_trajectory_problem.structural_movement_problem
            b = build_ddd_cp_sat_movement(
                movement,
                waiting_policy=problem.resolved_trajectory_problem.waiting_policy,
                boundary_occurrences=problem.boundary_context.resource_occurrences,
                deadline_monotonic=deadline,
                resource_encoding=self.config.formulation.resource_encoding,
            )
            preprocessing_started = perf_counter()
            prepared = None
            if not self.config.formulation.legacy:
                prepared = prepare_cp_structure(movement, problem.passenger_build, b.states_by_cabin)
                if self.config.formulation.enabled("temporal"):
                    apply_cp_temporal(b, prepared)
            preprocessing_seconds = perf_counter() - preprocessing_started
            passengers = build_ddd_cp_sat_passenger_assignment(
                movement,
                problem.passenger_build,
                problem.artifact.config.cabin_capacity,
                b,
                with_journey_cost=False,
                formulation=self.config.formulation, prepared=prepared,
                deadline_monotonic=deadline,
            )
            hint_started = perf_counter()
            if fixed_movement is not None:
                values, _ = _movement_values(problem, b, fixed_movement)
                for i, v in values.items():
                    b.model.add(b.model.get_int_var_from_proto_index(i) == v)
            if incumbent is not None:
                values, times = _movement_values(problem, b, incumbent.solution)
                for i, v in values.items():
                    b.model.add_hint(b.model.get_int_var_from_proto_index(i), v)
                passengers.add_hints(problem, b.model, incumbent.ride_counts, times)
                b.model.add(passengers.objective_expression <= score(incumbent))
            if self.config.formulation.enabled("hints"):
                complete_cp_hints(b.model)
            hint_seconds = perf_counter() - hint_started
            error = b.model.validate()
            if error:
                raise ValueError(error)
            stats = dict(
                variables=len(b.model.proto.variables),
                constraints=len(b.model.proto.constraints),
                cost_auxiliaries=passengers.cost_auxiliary_count,
                ride_candidates=len(passengers.ride_count),
            )
            stats["preprocessing_seconds"] = preprocessing_seconds
            if not self.config.formulation.legacy:
                stats["preprocessing"] = formulation_identity(self.config.formulation, prepared)
            built = DddIntegratedCpSatModel(
                b,
                passengers,
                manifest,
                "FIXED_MOVEMENT" if fixed_movement is not None else "FIXED_K_GLOBAL",
                stable_fingerprint(
                    {"version": "fixed_start_capacity_v1", "model": str(b.model.proto), **formulation_identity(self.config.formulation, prepared)}
                ),
                stats,
            )
        except TimeoutError:
            pass
        build_seconds = perf_counter() - started
        if built is not None:
            emit(
                dict(
                    kind="model_built",
                    model_stats=built.stats,
                    model_fingerprint=built.model_fingerprint,
                    workers=self.config.num_workers,
                )
            )
        if built is not None and perf_counter() < deadline:
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = deadline - perf_counter()
            solver.parameters.num_search_workers = self.config.num_workers
            solver.parameters.random_seed = self.config.seed
            solver.parameters.absolute_gap_limit = (
                solver.parameters.relative_gap_limit
            ) = 0
            solver.parameters.log_search_progress = self.config.log_search_progress
            if log_callback:
                solver.log_callback = log_callback
                solver.parameters.log_to_stdout = False

            def extract(value):
                nonlocal validation_seconds
                before_validation = perf_counter()
                raw = _raw_incumbent(built, value)
                checked = validate_ddd_cp_sat_incumbent(
                    problem,
                    solution_from_cp_sat_payload(problem, raw),
                    raw["ride_counts"],
                    provenance="cp_sat_capacity",
                )
                if score(checked) != raw["objective_tick"]:
                    raise RuntimeError(
                        "capacity objective differs from independently counted unserved"
                    )
                validation_seconds += perf_counter()-before_validation
                return checked

            class Callback(cp_model.CpSolverSolutionCallback):
                error = None
                last_checkpoint = -float("inf")

                def on_solution_callback(cb):
                    nonlocal incumbent
                    try:
                        upper = int(cb.value(passengers.objective_expression))
                        emit(
                            dict(
                                kind="incumbent",
                                unserved=upper,
                                raw_lower_bound=cb.best_objective_bound,
                            )
                        )
                        now = perf_counter()
                        if (
                            upper == 0
                            or now - cb.last_checkpoint
                            >= self.config.checkpoint_interval_seconds
                        ):
                            checked = extract(cb.value)
                            if incumbent is None or score(checked) <= score(incumbent):
                                incumbent = checked
                                save(checked)
                            cb.last_checkpoint = now
                    except Exception as exc:
                        cb.error = exc
                        cb.stop_search()

            callback = Callback()
            solver.best_bound_callback = lambda bound: emit(
                dict(kind="bound", raw_lower_bound=bound)
            )
            before = perf_counter()
            status = solver.solve(b.model, callback)
            solve_seconds = perf_counter() - before
            response = solver.response_stats()
            if callback.error:
                raise RuntimeError("capacity callback failed") from callback.error
            if status == cp_model.MODEL_INVALID:
                raise RuntimeError(response)
            if status == cp_model.INFEASIBLE and incumbent is not None:
                raise RuntimeError("capacity infeasibility contradicts validated seed")
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                found = extract(solver.value)
                if incumbent is None or score(found) <= score(incumbent):
                    incumbent = found
            if status != cp_model.INFEASIBLE:
                raw_bound = float(solver.best_objective_bound)
                lower = conservative_count_bound(raw_bound)
            if status == cp_model.OPTIMAL:
                if incumbent is None or abs(raw_bound - score(incumbent)) > 0.25:
                    raise RuntimeError("capacity optimal bound mismatch")
                lower = score(incumbent)
        if incumbent is not None:
            save(incumbent)
        upper = None if incumbent is None else score(incumbent)
        if upper is not None and lower is not None and lower > upper:
            raise RuntimeError("capacity lower bound exceeds validated upper bound")
        feasible = upper == 0
        # Zero unserved is certified optimal even if a time limit prevented a native OPTIMAL status.
        if feasible:
            lower = 0
        status_name = cp_model.CpSolver().status_name(status)
        emit(
            dict(
                kind="final",
                status=status_name,
                unserved_upper_bound=upper,
                unserved_lower_bound=lower,
            )
        )
        return dict(
            schema="fixed_start_capacity_result_v1",
            objective="unserved",
            bound_units="persons",
            problem_fingerprint=problem.fingerprint,
            domain_manifest=manifest,
            proof_scope="FIXED_MOVEMENT"
            if fixed_movement is not None
            else "FIXED_K_GLOBAL",
            solver_status=status_name,
            proven_optimal=feasible or status == cp_model.OPTIMAL,
            total_demand=sum(g.count for g in problem.passenger_build.demand_groups),
            served=None
            if upper is None
            else sum(g.count for g in problem.passenger_build.demand_groups) - upper,
            unserved_upper_bound=upper,
            unserved_lower_bound=lower,
            raw_lower_bound=raw_bound,
            capacity_feasible=feasible,
            capacity_infeasible_proven=status == cp_model.INFEASIBLE
            or (lower is not None and lower > 0),
            model_stats={} if built is None else built.stats,
            model_fingerprint=None if built is None else built.model_fingerprint,
            incumbent=None if incumbent is None else incumbent.to_payload(),
            build_seconds=build_seconds,
            hint_seconds=hint_seconds, model_build_seconds=build_seconds-hint_seconds,
            validation_seconds=validation_seconds,
            solve_seconds=solve_seconds,
            total_seconds=perf_counter() - started,
            response_stats=response,
            events=events,
        )
