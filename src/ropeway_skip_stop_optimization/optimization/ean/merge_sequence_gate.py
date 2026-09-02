from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from itertools import combinations
import math
from time import perf_counter
from typing import Protocol


class EanMergeStream(StrEnum):
    SERVICE = "service"
    SKIP = "skip"


class EanMergeGateFormulation(StrEnum):
    ENUMERATION = "enumeration"
    PAIRWISE_FIFO = "pairwise_fifo"
    LATTICE = "lattice"
    SLOTS = "slots"
    CP_SAT = "cp_sat"


@dataclass(frozen=True)
class EanMergeGateEvent:
    id: str
    stream: EanMergeStream
    stream_index: int
    release_seconds: float
    weight: float = 1.0

    def validate(self) -> None:
        if not self.id.strip():
            raise ValueError("merge gate event id must be nonempty")
        if not isinstance(self.stream, EanMergeStream):
            raise ValueError("merge gate event needs a valid stream")
        if self.stream_index < 0:
            raise ValueError("merge gate stream index must be nonnegative")
        if not math.isfinite(self.release_seconds) or self.release_seconds < 0:
            raise ValueError("merge gate release must be finite and nonnegative")
        if not math.isfinite(self.weight) or self.weight < 0:
            raise ValueError("merge gate weight must be finite and nonnegative")


@dataclass(frozen=True)
class EanMergeGateInstance:
    id: str
    events: tuple[EanMergeGateEvent, ...]
    service_leader_headway_seconds: float
    skip_leader_headway_seconds: float

    @property
    def service_events(self) -> tuple[EanMergeGateEvent, ...]:
        return tuple(
            sorted(
                (event for event in self.events if event.stream is EanMergeStream.SERVICE),
                key=lambda event: event.stream_index,
            )
        )

    @property
    def skip_events(self) -> tuple[EanMergeGateEvent, ...]:
        return tuple(
            sorted(
                (event for event in self.events if event.stream is EanMergeStream.SKIP),
                key=lambda event: event.stream_index,
            )
        )

    def headway(self, event: EanMergeGateEvent) -> float:
        return (
            self.service_leader_headway_seconds
            if event.stream is EanMergeStream.SERVICE
            else self.skip_leader_headway_seconds
        )

    def validate(self) -> None:
        if not self.id.strip() or not self.events:
            raise ValueError("merge gate instance needs an id and events")
        if len({event.id for event in self.events}) != len(self.events):
            raise ValueError("merge gate event ids must be unique")
        for event in self.events:
            event.validate()
        for stream_events in (self.service_events, self.skip_events):
            if tuple(event.stream_index for event in stream_events) != tuple(
                range(len(stream_events))
            ):
                raise ValueError("merge gate stream indices must be contiguous")
        for value in (
            self.service_leader_headway_seconds,
            self.skip_leader_headway_seconds,
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("merge gate headways must be finite and positive")


@dataclass(frozen=True)
class EanMergeGateSolveConfig:
    time_limit_seconds: float = 30.0
    threads: int = 1
    seed: int = 1

    def validate(self) -> None:
        if self.time_limit_seconds <= 0 or self.threads <= 0 or self.seed < 0:
            raise ValueError("invalid merge gate solve configuration")


@dataclass(frozen=True)
class EanMergeGateMetrics:
    variable_count: int
    binary_variable_count: int
    constraint_count: int
    nonzero_count: int
    build_seconds: float
    solve_seconds: float
    node_count: float | None = None
    best_bound: float | None = None
    root_relaxation: float | None = None
    work: float | None = None


@dataclass(frozen=True)
class EanMergeGateSolution:
    formulation: EanMergeGateFormulation
    status: str
    objective: float | None
    sequence: tuple[str, ...]
    time_by_event_id: tuple[tuple[str, float], ...]
    metrics: EanMergeGateMetrics

    def validate_against(self, instance: EanMergeGateInstance) -> None:
        if self.objective is None:
            return
        expected = {event.id for event in instance.events}
        if set(self.sequence) != expected or len(self.sequence) != len(expected):
            raise ValueError("merge gate solution is not a permutation")
        event_by_id = {event.id: event for event in instance.events}
        for stream in (EanMergeStream.SERVICE, EanMergeStream.SKIP):
            observed = tuple(
                event_by_id[event_id].stream_index
                for event_id in self.sequence
                if event_by_id[event_id].stream is stream
            )
            if observed != tuple(range(len(observed))):
                raise ValueError("merge gate solution violates stream FIFO")
        time_by_id = dict(self.time_by_event_id)
        for event in instance.events:
            if time_by_id[event.id] + 1e-5 < event.release_seconds:
                raise ValueError("merge gate solution violates a release")
        for leader_id, follower_id in zip(self.sequence, self.sequence[1:]):
            leader = event_by_id[leader_id]
            if (
                time_by_id[follower_id] + 1e-5
                < time_by_id[leader_id] + instance.headway(leader)
            ):
                raise ValueError("merge gate solution violates an adjacent headway")
        expected_objective = sum(
            event.weight * (time_by_id[event.id] - event.release_seconds)
            for event in instance.events
        )
        if abs(expected_objective - self.objective) > 1e-5:
            raise ValueError("merge gate objective does not match event times")


class EanMergeGateSolver(Protocol):
    formulation: EanMergeGateFormulation

    def solve(
        self,
        instance: EanMergeGateInstance,
        config: EanMergeGateSolveConfig,
    ) -> EanMergeGateSolution: ...


@dataclass(frozen=True)
class EanEnumeratedMergeGateSolver:
    formulation: EanMergeGateFormulation = EanMergeGateFormulation.ENUMERATION

    def solve(
        self,
        instance: EanMergeGateInstance,
        config: EanMergeGateSolveConfig = EanMergeGateSolveConfig(),
    ) -> EanMergeGateSolution:
        del config
        instance.validate()
        started = perf_counter()
        event_by_id = {event.id: event for event in instance.events}
        best_objective = math.inf
        best_sequence: tuple[EanMergeGateEvent, ...] = ()
        best_times: dict[str, float] = {}
        for ids in enumerate_stable_merge_sequences(instance):
            sequence = tuple(event_by_id[event_id] for event_id in ids)
            objective, times = _earliest_sequence_objective(instance, sequence)
            if objective < best_objective - 1e-9 or (
                abs(objective - best_objective) <= 1e-9
                and ids < tuple(event.id for event in best_sequence)
            ):
                best_objective = objective
                best_sequence = sequence
                best_times = times
        runtime = perf_counter() - started
        solution = EanMergeGateSolution(
            formulation=self.formulation,
            status="optimal",
            objective=best_objective,
            sequence=tuple(event.id for event in best_sequence),
            time_by_event_id=tuple(sorted(best_times.items())),
            metrics=EanMergeGateMetrics(
                variable_count=0,
                binary_variable_count=0,
                constraint_count=0,
                nonzero_count=0,
                build_seconds=0.0,
                solve_seconds=runtime,
                best_bound=best_objective,
            ),
        )
        solution.validate_against(instance)
        return solution


def enumerate_stable_merge_sequences(
    instance: EanMergeGateInstance,
) -> tuple[tuple[str, ...], ...]:
    """Enumerate the binomial two-stream shuffle universe deterministically."""

    instance.validate()
    service = instance.service_events
    skip = instance.skip_events
    total = len(instance.events)
    sequences: list[tuple[str, ...]] = []
    for service_positions in combinations(range(total), len(service)):
        service_position_set = set(service_positions)
        service_index = 0
        skip_index = 0
        sequence: list[str] = []
        for position in range(total):
            if position in service_position_set:
                sequence.append(service[service_index].id)
                service_index += 1
            else:
                sequence.append(skip[skip_index].id)
                skip_index += 1
        sequences.append(tuple(sequence))
    return tuple(sequences)


@dataclass(frozen=True)
class EanPairwiseMergeGateSolver:
    formulation: EanMergeGateFormulation = EanMergeGateFormulation.PAIRWISE_FIFO

    def solve(
        self,
        instance: EanMergeGateInstance,
        config: EanMergeGateSolveConfig = EanMergeGateSolveConfig(),
    ) -> EanMergeGateSolution:
        import gurobipy as gp
        from gurobipy import GRB

        instance.validate()
        config.validate()
        build_started = perf_counter()
        model = gp.Model(f"merge_gate_pairwise_{instance.id}")
        _configure_gurobi(model, config)
        upper = _time_upper_bound(instance)
        big_m = upper + max(instance.headway(event) for event in instance.events)
        event_time = {
            event.id: model.addVar(
                lb=event.release_seconds,
                ub=upper,
                name=f"time_{event.id}",
            )
            for event in instance.events
        }
        order = {}
        for service_event in instance.service_events:
            for skip_event in instance.skip_events:
                key = service_event.id, skip_event.id
                order[key] = model.addVar(vtype=GRB.BINARY, name=f"order_{key[0]}_{key[1]}")
                model.addConstr(
                    event_time[service_event.id] + instance.headway(service_event)
                    <= event_time[skip_event.id] + big_m * (1 - order[key])
                )
                model.addConstr(
                    event_time[skip_event.id] + instance.headway(skip_event)
                    <= event_time[service_event.id] + big_m * order[key]
                )
        _add_stream_precedences(model, instance, event_time)
        model.setObjective(
            gp.quicksum(
                event.weight * (event_time[event.id] - event.release_seconds)
                for event in instance.events
            ),
            GRB.MINIMIZE,
        )
        model.update()
        build_seconds = perf_counter() - build_started
        solve_started = perf_counter()
        model.optimize()
        solve_seconds = perf_counter() - solve_started
        return _gurobi_solution(
            model=model,
            instance=instance,
            formulation=self.formulation,
            event_time=event_time,
            build_seconds=build_seconds,
            solve_seconds=solve_seconds,
        )


@dataclass(frozen=True)
class EanLatticeMergeGateSolver:
    formulation: EanMergeGateFormulation = EanMergeGateFormulation.LATTICE

    def solve(
        self,
        instance: EanMergeGateInstance,
        config: EanMergeGateSolveConfig = EanMergeGateSolveConfig(),
    ) -> EanMergeGateSolution:
        import gurobipy as gp
        from gurobipy import GRB

        instance.validate()
        config.validate()
        build_started = perf_counter()
        model = gp.Model(f"merge_gate_lattice_{instance.id}")
        _configure_gurobi(model, config)
        service = instance.service_events
        skip = instance.skip_events
        upper = _time_upper_bound(instance)
        big_m = upper + max(instance.headway(event) for event in instance.events)
        event_time = {
            event.id: model.addVar(lb=event.release_seconds, ub=upper, name=f"time_{event.id}")
            for event in instance.events
        }
        east = {
            (i, j): model.addVar(vtype=GRB.BINARY, name=f"east_{i}_{j}")
            for i in range(len(service))
            for j in range(len(skip) + 1)
        }
        north = {
            (i, j): model.addVar(vtype=GRB.BINARY, name=f"north_{i}_{j}")
            for i in range(len(service) + 1)
            for j in range(len(skip))
        }
        for i in range(len(service) + 1):
            for j in range(len(skip) + 1):
                incoming = []
                outgoing = []
                if i > 0:
                    incoming.append(east[(i - 1, j)])
                if j > 0:
                    incoming.append(north[(i, j - 1)])
                if i < len(service):
                    outgoing.append(east[(i, j)])
                if j < len(skip):
                    outgoing.append(north[(i, j)])
                rhs = 1 if (i, j) == (0, 0) else -1 if (i, j) == (len(service), len(skip)) else 0
                model.addConstr(gp.quicksum(outgoing) - gp.quicksum(incoming) == rhs)
        for i, service_event in enumerate(service):
            for j, skip_event in enumerate(skip):
                service_before_skip = gp.quicksum(
                    north[(emitted_service, j)]
                    for emitted_service in range(i + 1, len(service) + 1)
                )
                model.addConstr(
                    event_time[service_event.id] + instance.headway(service_event)
                    <= event_time[skip_event.id]
                    + big_m * (1 - service_before_skip)
                )
                model.addConstr(
                    event_time[skip_event.id] + instance.headway(skip_event)
                    <= event_time[service_event.id] + big_m * service_before_skip
                )
        _add_stream_precedences(model, instance, event_time)
        model.setObjective(
            gp.quicksum(
                event.weight * (event_time[event.id] - event.release_seconds)
                for event in instance.events
            ),
            GRB.MINIMIZE,
        )
        model.update()
        build_seconds = perf_counter() - build_started
        solve_started = perf_counter()
        model.optimize()
        solve_seconds = perf_counter() - solve_started
        return _gurobi_solution(
            model=model,
            instance=instance,
            formulation=self.formulation,
            event_time=event_time,
            build_seconds=build_seconds,
            solve_seconds=solve_seconds,
        )


@dataclass(frozen=True)
class EanSlotMergeGateSolver:
    formulation: EanMergeGateFormulation = EanMergeGateFormulation.SLOTS

    def solve(
        self,
        instance: EanMergeGateInstance,
        config: EanMergeGateSolveConfig = EanMergeGateSolveConfig(),
    ) -> EanMergeGateSolution:
        import gurobipy as gp
        from gurobipy import GRB

        instance.validate()
        config.validate()
        build_started = perf_counter()
        model = gp.Model(f"merge_gate_slots_{instance.id}")
        _configure_gurobi(model, config)
        events = tuple(sorted(instance.events, key=lambda event: event.id))
        count = len(events)
        upper = _time_upper_bound(instance)
        event_time = {
            event.id: model.addVar(lb=event.release_seconds, ub=upper, name=f"time_{event.id}")
            for event in events
        }
        assignment = {
            (event.id, slot): model.addVar(vtype=GRB.BINARY, name=f"assign_{event.id}_{slot}")
            for event in events
            for slot in range(count)
        }
        slot_time = {
            slot: model.addVar(lb=0.0, ub=upper, name=f"slot_time_{slot}")
            for slot in range(count)
        }
        for event in events:
            model.addConstr(gp.quicksum(assignment[(event.id, slot)] for slot in range(count)) == 1)
            for slot in range(count):
                model.addGenConstrIndicator(
                    assignment[(event.id, slot)],
                    True,
                    slot_time[slot] == event_time[event.id],
                )
        for slot in range(count):
            model.addConstr(gp.quicksum(assignment[(event.id, slot)] for event in events) == 1)
        position = {
            event.id: gp.quicksum(slot * assignment[(event.id, slot)] for slot in range(count))
            for event in events
        }
        for stream_events in (instance.service_events, instance.skip_events):
            for first, second in zip(stream_events, stream_events[1:]):
                model.addConstr(position[first.id] + 1 <= position[second.id])
        for slot in range(count - 1):
            selected_headway = gp.quicksum(
                instance.headway(event) * assignment[(event.id, slot)]
                for event in events
            )
            model.addConstr(slot_time[slot + 1] >= slot_time[slot] + selected_headway)
        model.setObjective(
            gp.quicksum(
                event.weight * (event_time[event.id] - event.release_seconds)
                for event in events
            ),
            GRB.MINIMIZE,
        )
        model.update()
        build_seconds = perf_counter() - build_started
        solve_started = perf_counter()
        model.optimize()
        solve_seconds = perf_counter() - solve_started
        return _gurobi_solution(
            model=model,
            instance=instance,
            formulation=self.formulation,
            event_time=event_time,
            build_seconds=build_seconds,
            solve_seconds=solve_seconds,
        )


@dataclass(frozen=True)
class EanCpSatMergeGateSolver:
    time_scale: int = 1_000
    formulation: EanMergeGateFormulation = EanMergeGateFormulation.CP_SAT

    def solve(
        self,
        instance: EanMergeGateInstance,
        config: EanMergeGateSolveConfig = EanMergeGateSolveConfig(),
    ) -> EanMergeGateSolution:
        from ortools.sat.python import cp_model

        instance.validate()
        config.validate()
        build_started = perf_counter()
        model = cp_model.CpModel()
        upper_ticks = math.ceil(_time_upper_bound(instance) * self.time_scale)
        start = {}
        intervals = []
        for event in instance.events:
            release = round(event.release_seconds * self.time_scale)
            duration = round(instance.headway(event) * self.time_scale)
            start[event.id] = model.new_int_var(release, upper_ticks, f"start_{event.id}")
            end = model.new_int_var(release + duration, upper_ticks + duration, f"end_{event.id}")
            intervals.append(model.new_interval_var(start[event.id], duration, end, f"interval_{event.id}"))
        model.add_no_overlap(intervals)
        for stream_events in (instance.service_events, instance.skip_events):
            for first, second in zip(stream_events, stream_events[1:]):
                model.add(start[second.id] >= start[first.id] + round(instance.headway(first) * self.time_scale))
        objective_terms = []
        objective_scale = 1_000
        for event in instance.events:
            integer_weight = round(event.weight * objective_scale)
            release = round(event.release_seconds * self.time_scale)
            objective_terms.append(integer_weight * (start[event.id] - release))
        model.minimize(sum(objective_terms))
        build_seconds = perf_counter() - build_started
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = config.time_limit_seconds
        solver.parameters.num_search_workers = config.threads
        solver.parameters.random_seed = config.seed
        solve_started = perf_counter()
        status = solver.solve(model)
        solve_seconds = perf_counter() - solve_started
        feasible = status in {cp_model.OPTIMAL, cp_model.FEASIBLE}
        times = (
            {
                event.id: solver.value(start[event.id]) / self.time_scale
                for event in instance.events
            }
            if feasible
            else {}
        )
        sequence = tuple(sorted(times, key=lambda event_id: (times[event_id], event_id)))
        objective = (
            sum(
                event.weight * (times[event.id] - event.release_seconds)
                for event in instance.events
            )
            if feasible
            else None
        )
        result = EanMergeGateSolution(
            formulation=self.formulation,
            status=(
                "optimal"
                if status == cp_model.OPTIMAL
                else "feasible"
                if status == cp_model.FEASIBLE
                else "infeasible"
                if status == cp_model.INFEASIBLE
                else "unknown"
            ),
            objective=objective,
            sequence=sequence,
            time_by_event_id=tuple(sorted(times.items())),
            metrics=EanMergeGateMetrics(
                variable_count=len(instance.events) * 2,
                binary_variable_count=0,
                constraint_count=len(intervals),
                nonzero_count=0,
                build_seconds=build_seconds,
                solve_seconds=solve_seconds,
                best_bound=solver.best_objective_bound / (self.time_scale * objective_scale),
            ),
        )
        result.validate_against(instance)
        return result


def _earliest_sequence_objective(
    instance: EanMergeGateInstance,
    sequence: tuple[EanMergeGateEvent, ...],
) -> tuple[float, dict[str, float]]:
    times: dict[str, float] = {}
    previous: EanMergeGateEvent | None = None
    for event in sequence:
        earliest = event.release_seconds
        if previous is not None:
            earliest = max(
                earliest,
                times[previous.id] + instance.headway(previous),
            )
        times[event.id] = earliest
        previous = event
    objective = sum(
        event.weight * (times[event.id] - event.release_seconds)
        for event in instance.events
    )
    return objective, times


def _add_stream_precedences(model, instance, event_time) -> None:
    for stream_events in (instance.service_events, instance.skip_events):
        for first, second in zip(stream_events, stream_events[1:]):
            model.addConstr(
                event_time[first.id] + instance.headway(first)
                <= event_time[second.id]
            )


def _time_upper_bound(instance: EanMergeGateInstance) -> float:
    return (
        max(event.release_seconds for event in instance.events)
        + sum(instance.headway(event) for event in instance.events)
        + 1.0
    )


def _configure_gurobi(model, config: EanMergeGateSolveConfig) -> None:
    model.Params.OutputFlag = 0
    model.Params.MIPGap = 0.0
    model.Params.TimeLimit = config.time_limit_seconds
    model.Params.Threads = config.threads
    model.Params.Seed = config.seed


def _gurobi_solution(
    *,
    model,
    instance: EanMergeGateInstance,
    formulation: EanMergeGateFormulation,
    event_time,
    build_seconds: float,
    solve_seconds: float,
) -> EanMergeGateSolution:
    from gurobipy import GRB

    feasible = model.SolCount > 0
    times = (
        {event_id: float(variable.X) for event_id, variable in event_time.items()}
        if feasible
        else {}
    )
    sequence = tuple(sorted(times, key=lambda event_id: (times[event_id], event_id)))
    result = EanMergeGateSolution(
        formulation=formulation,
        status=(
            "optimal"
            if model.Status == GRB.OPTIMAL
            else "feasible"
            if feasible
            else "infeasible"
            if model.Status == GRB.INFEASIBLE
            else "unknown"
        ),
        objective=float(model.ObjVal) if feasible else None,
        sequence=sequence,
        time_by_event_id=tuple(sorted(times.items())),
        metrics=EanMergeGateMetrics(
            variable_count=int(model.NumVars),
            binary_variable_count=int(model.NumBinVars),
            constraint_count=int(model.NumConstrs + model.NumGenConstrs),
            nonzero_count=int(model.NumNZs),
            build_seconds=build_seconds,
            solve_seconds=solve_seconds,
            node_count=float(model.NodeCount),
            best_bound=float(model.ObjBound),
            work=float(model.Work),
        ),
    )
    result.validate_against(instance)
    return result
