from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_primal import (
    DddCpSatFixedRouteDecision,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddNetworkTimeProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceResourceOccurrence,
    DddReferenceTrajectory,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_refinement import (
    DddRecoveredSchedule,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    DddTimeTick,
    ddd_seconds_to_tick,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_coordinated_primal import (
    DddTrajectoryCoordinatedPrimalGenerator,
    DddTrajectoryCoordinatedPrimalResult,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_passenger_lp import (
    DddTrajectoryPassengerLpResult,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import (
    DddTrajectoryWaitingPolicy,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_merge_domain import (
    DddTrajectoryMergeDomain,
    DddTrajectoryMergeOccurrence,
)
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import (
    EanPassengerCandidateBuildResult,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_objective import (
    EanPassengerObjective,
)


@dataclass(frozen=True, order=True)
class DddTrajectoryNeighborhoodCabinScore:
    cabin_id: int
    deviation_mass: float
    fractional_mass: float
    positive_option_count: int

    @property
    def total(self) -> float:
        # Deviation from the current integer solution is the strongest signal:
        # it identifies cabins for which the root LP already sees alternatives.
        return self.deviation_mass + 0.25 * self.fractional_mass


@dataclass(frozen=True)
class DddTrajectoryNeighborhood:
    id: str
    released_cabin_ids: tuple[int, ...]
    fixed_cabin_ids: tuple[int, ...]
    scores: tuple[DddTrajectoryNeighborhoodCabinScore, ...]

    def validate(self, expected_cabin_ids: tuple[int, ...]) -> None:
        if not self.released_cabin_ids:
            raise ValueError("trajectory neighborhood must release at least one cabin")
        if set(self.released_cabin_ids) & set(self.fixed_cabin_ids):
            raise ValueError("trajectory neighborhood fixed and released sets overlap")
        if set((*self.released_cabin_ids, *self.fixed_cabin_ids)) != set(
            expected_cabin_ids
        ):
            raise ValueError("trajectory neighborhood does not partition all cabins")
        if tuple(sorted(self.released_cabin_ids)) != self.released_cabin_ids:
            raise ValueError("released cabin ids must be sorted")
        if tuple(sorted(self.fixed_cabin_ids)) != self.fixed_cabin_ids:
            raise ValueError("fixed cabin ids must be sorted")


@dataclass(frozen=True)
class DddTrajectoryNeighborhoodSelector:
    """Choose deterministic fractional cabin cohorts for fix-and-optimize."""

    cabin_counts: tuple[int, ...] = (4, 8, 12)
    tolerance: float = 1e-7

    def select(
        self,
        *,
        cabin_ids: tuple[int, ...],
        lp_result: DddTrajectoryPassengerLpResult,
        trajectory_by_option_id: dict[str, DddReferenceTrajectory],
        incumbent_option_ids: tuple[str, ...],
        neighborhood_index: int,
    ) -> DddTrajectoryNeighborhood:
        if not cabin_ids:
            raise ValueError("trajectory neighborhood needs cabins")
        if neighborhood_index <= 0:
            raise ValueError("trajectory neighborhood index must be positive")
        if not self.cabin_counts or any(value <= 0 for value in self.cabin_counts):
            raise ValueError("trajectory neighborhood cabin counts must be positive")
        if self.tolerance < 0:
            raise ValueError("trajectory neighborhood tolerance must be nonnegative")

        incumbent_by_cabin = {
            trajectory_by_option_id[option_id].cabin_id: option_id
            for option_id in incumbent_option_ids
            if option_id in trajectory_by_option_id
        }
        values_by_cabin: dict[int, list[tuple[str, float]]] = {
            cabin_id: [] for cabin_id in cabin_ids
        }
        for option_id, value in lp_result.option_values_by_id.items():
            trajectory = trajectory_by_option_id.get(option_id)
            if trajectory is None or trajectory.cabin_id not in values_by_cabin:
                continue
            if value > self.tolerance:
                values_by_cabin[trajectory.cabin_id].append((option_id, value))

        scores = []
        for cabin_id in cabin_ids:
            values = values_by_cabin[cabin_id]
            incumbent_id = incumbent_by_cabin.get(cabin_id)
            deviation_mass = sum(
                value for option_id, value in values if option_id != incumbent_id
            )
            fractional_mass = sum(
                min(value, max(0.0, 1.0 - value)) for _, value in values
            )
            scores.append(
                DddTrajectoryNeighborhoodCabinScore(
                    cabin_id=cabin_id,
                    deviation_mass=deviation_mass,
                    fractional_mass=fractional_mass,
                    positive_option_count=len(values),
                )
            )

        count = min(
            self.cabin_counts[(neighborhood_index - 1) % len(self.cabin_counts)],
            len(cabin_ids),
        )
        offset = (neighborhood_index - 1) % len(cabin_ids)
        cyclic_rank = {
            cabin_id: (index - offset) % len(cabin_ids)
            for index, cabin_id in enumerate(cabin_ids)
        }
        ranked = sorted(
            scores,
            key=lambda item: (
                -item.total,
                -item.positive_option_count,
                cyclic_rank[item.cabin_id],
                item.cabin_id,
            ),
        )
        released = tuple(sorted(item.cabin_id for item in ranked[:count]))
        fixed = tuple(cabin_id for cabin_id in cabin_ids if cabin_id not in released)
        payload = (
            f"n={neighborhood_index}|release={','.join(map(str, released))}|"
            f"fixed={','.join(map(str, fixed))}"
        )
        result = DddTrajectoryNeighborhood(
            id=f"fractional_cabin_cohort::{sha256(payload.encode()).hexdigest()}",
            released_cabin_ids=released,
            fixed_cabin_ids=fixed,
            scores=tuple(sorted(scores)),
        )
        result.validate(cabin_ids)
        return result


@dataclass(frozen=True)
class DddTrajectoryNeighborhoodPrimalResult:
    neighborhood: DddTrajectoryNeighborhood
    coordinated: DddTrajectoryCoordinatedPrimalResult


@dataclass(frozen=True)
class DddTrajectoryNeighborhoodPrimalOptimizer:
    """Passenger-guided CP fix-and-optimize over a released cabin cohort.

    The optimizer is a primal-only column source. All cabins outside the
    neighborhood keep the incumbent's complete route sequence, CP-SAT jointly
    reschedules the released cabins, and the returned full package is validated
    by the coordinated generator before it can enter the restricted master.
    """

    time_limit_seconds: float
    num_workers: int = 8
    max_candidate_count: int = 1
    maximum_preference_count: int = 2_000

    def optimize(
        self,
        *,
        problem: DddNetworkTimeProblem,
        artifact: EanBuildArtifact,
        passenger_build: EanPassengerCandidateBuildResult,
        objective: EanPassengerObjective,
        lp_result: DddTrajectoryPassengerLpResult,
        waiting_policy: DddTrajectoryWaitingPolicy,
        incumbent_trajectories: tuple[DddReferenceTrajectory, ...],
        neighborhood: DddTrajectoryNeighborhood,
        boundary_occurrences: tuple[DddReferenceResourceOccurrence, ...] = (),
        excluded_schedules: tuple[tuple[DddRecoveredSchedule, ...], ...] = (),
    ) -> DddTrajectoryNeighborhoodPrimalResult:
        cabin_ids = tuple(
            sorted(start.cabin_id for start in problem.movement_problem.starts)
        )
        neighborhood.validate(cabin_ids)
        incumbent_by_cabin = {
            trajectory.cabin_id: trajectory for trajectory in incumbent_trajectories
        }
        if set(incumbent_by_cabin) != set(cabin_ids):
            raise ValueError(
                "trajectory neighborhood requires one incumbent trajectory per cabin"
            )
        fixed_trajectories = tuple(
            incumbent_by_cabin[cabin_id]
            for cabin_id in neighborhood.fixed_cabin_ids
        )
        coordinated = DddTrajectoryCoordinatedPrimalGenerator(
            time_limit_seconds=self.time_limit_seconds,
            num_workers=self.num_workers,
            max_candidate_count=self.max_candidate_count,
            maximum_preference_count=self.maximum_preference_count,
        ).generate(
            problem=problem,
            artifact=artifact,
            passenger_build=passenger_build,
            objective=objective,
            lp_result=lp_result,
            waiting_policy=waiting_policy,
            boundary_occurrences=boundary_occurrences,
            excluded_schedules=excluded_schedules,
            hint_trajectories=incumbent_trajectories,
            fixed_trajectories=fixed_trajectories,
            exclude_hint_schedule=True,
        )
        return DddTrajectoryNeighborhoodPrimalResult(
            neighborhood=neighborhood,
            coordinated=coordinated,
        )


@dataclass(frozen=True, order=True)
class DddTrajectoryVisitPosition:
    cabin_id: int
    visit_index: int


@dataclass(frozen=True)
class DddTrajectoryMergeCorridor:
    """A physical merge/time neighborhood over sparse route decisions."""

    id: str
    family_id: str
    window_start_tick: DddTimeTick
    window_end_tick: DddTimeTick
    released_positions: tuple[DddTrajectoryVisitPosition, ...]
    fixed_route_decisions: tuple[DddCpSatFixedRouteDecision, ...]
    merge_occurrence_count: int
    deviation_mass: float
    fractional_mass: float

    @property
    def released_cabin_ids(self) -> tuple[int, ...]:
        return tuple(sorted({item.cabin_id for item in self.released_positions}))

    @property
    def score(self) -> float:
        return (
            float(self.merge_occurrence_count)
            + 4.0 * self.deviation_mass
            + 2.0 * self.fractional_mass
        )

    def validate(
        self,
        incumbent_trajectories: tuple[DddReferenceTrajectory, ...],
    ) -> None:
        if not self.id or not self.family_id:
            raise ValueError("merge corridor identifiers are required")
        if self.window_start_tick < 0 or self.window_end_tick <= self.window_start_tick:
            raise ValueError("merge corridor time window is invalid")
        if not self.released_positions:
            raise ValueError("merge corridor must release route decisions")
        if tuple(sorted(set(self.released_positions))) != self.released_positions:
            raise ValueError("merge corridor released positions must be sorted and unique")
        if tuple(sorted(self.fixed_route_decisions)) != self.fixed_route_decisions:
            raise ValueError("merge corridor fixed decisions must be sorted")
        released = {
            (item.cabin_id, item.visit_index) for item in self.released_positions
        }
        fixed = {
            (item.cabin_id, item.visit_index) for item in self.fixed_route_decisions
        }
        expected = {
            (trajectory.cabin_id, visit.visit_index)
            for trajectory in incumbent_trajectories
            for visit in trajectory.visits
        }
        if released & fixed:
            raise ValueError("merge corridor released and fixed decisions overlap")
        if released | fixed != expected:
            raise ValueError("merge corridor does not partition incumbent decisions")
        if self.merge_occurrence_count <= 0:
            raise ValueError("merge corridor occurrence count must be positive")
        if self.deviation_mass < 0 or self.fractional_mass < 0:
            raise ValueError("merge corridor LP scores must be nonnegative")


@dataclass(frozen=True)
class DddTrajectoryMergeCorridorSelector:
    """Select deterministic high-value merge/time fix-and-optimize windows."""

    window_widths_seconds: tuple[float, ...] = (120.0, 240.0, 480.0)
    upstream_visit_count: int = 1
    downstream_visit_count: int = 1
    minimum_occurrence_count: int = 2
    tolerance: float = 1e-7

    def select(
        self,
        *,
        merge_domain: DddTrajectoryMergeDomain,
        lp_result: DddTrajectoryPassengerLpResult,
        trajectory_by_option_id: dict[str, DddReferenceTrajectory],
        incumbent_trajectories: tuple[DddReferenceTrajectory, ...],
        neighborhood_index: int,
    ) -> DddTrajectoryMergeCorridor:
        self._validate_config()
        merge_domain.validate()
        if neighborhood_index <= 0:
            raise ValueError("merge corridor neighborhood index must be positive")
        if not incumbent_trajectories:
            raise ValueError("merge corridor needs incumbent trajectories")

        incumbent_by_cabin = {
            trajectory.cabin_id: trajectory
            for trajectory in incumbent_trajectories
        }
        if len(incumbent_by_cabin) != len(incumbent_trajectories):
            raise ValueError("merge corridor incumbent cabin IDs must be unique")
        route_mass = self._route_mass(
            lp_result=lp_result,
            trajectory_by_option_id=trajectory_by_option_id,
        )
        occurrences_by_family = {
            family.id: tuple(
                sorted(
                    occurrence
                    for trajectory in incumbent_trajectories
                    for occurrence in merge_domain.occurrences(trajectory)
                    if occurrence.family_id == family.id
                )
            )
            for family in merge_domain.families
        }
        candidate_by_signature: dict[
            tuple[str, tuple[tuple[int, int], ...]],
            DddTrajectoryMergeCorridor,
        ] = {}
        for family_id, occurrences in occurrences_by_family.items():
            for width_seconds in self.window_widths_seconds:
                width_tick = ddd_seconds_to_tick(width_seconds)
                for anchor in occurrences:
                    start_tick = max(0, anchor.merge_entry_tick - width_tick // 2)
                    end_tick = start_tick + width_tick
                    members = tuple(
                        item
                        for item in occurrences
                        if start_tick <= item.merge_entry_tick < end_tick
                    )
                    if len(members) < self.minimum_occurrence_count:
                        continue
                    member_signature = tuple(
                        (item.cabin_id, item.visit_index) for item in members
                    )
                    signature = (family_id, member_signature)
                    corridor = self._build_corridor(
                        family_id=family_id,
                        start_tick=start_tick,
                        end_tick=end_tick,
                        members=members,
                        incumbent_by_cabin=incumbent_by_cabin,
                        route_mass=route_mass,
                    )
                    known = candidate_by_signature.get(signature)
                    if known is None or (
                        corridor.window_end_tick - corridor.window_start_tick,
                        corridor.window_start_tick,
                        corridor.id,
                    ) < (
                        known.window_end_tick - known.window_start_tick,
                        known.window_start_tick,
                        known.id,
                    ):
                        candidate_by_signature[signature] = corridor
        if not candidate_by_signature:
            raise ValueError("no eligible merge/time corridor exists")
        ranked = sorted(
            candidate_by_signature.values(),
            key=lambda item: (
                -item.score,
                -item.merge_occurrence_count,
                item.family_id,
                item.window_start_tick,
                item.window_end_tick,
                item.id,
            ),
        )
        selected = ranked[(neighborhood_index - 1) % len(ranked)]
        selected.validate(incumbent_trajectories)
        return selected

    def _validate_config(self) -> None:
        if (
            not self.window_widths_seconds
            or any(value <= 0 for value in self.window_widths_seconds)
            or tuple(sorted(set(self.window_widths_seconds)))
            != self.window_widths_seconds
        ):
            raise ValueError("merge corridor widths must be increasing and positive")
        if self.upstream_visit_count < 0 or self.downstream_visit_count < 0:
            raise ValueError("merge corridor visit padding must be nonnegative")
        if self.minimum_occurrence_count <= 0:
            raise ValueError("merge corridor occurrence count must be positive")
        if self.tolerance < 0:
            raise ValueError("merge corridor tolerance must be nonnegative")

    def _route_mass(
        self,
        *,
        lp_result: DddTrajectoryPassengerLpResult,
        trajectory_by_option_id: dict[str, DddReferenceTrajectory],
    ) -> dict[tuple[int, int, str], float]:
        result: dict[tuple[int, int, str], float] = {}
        for option_id, value in lp_result.option_values_by_id.items():
            if value <= self.tolerance:
                continue
            trajectory = trajectory_by_option_id.get(option_id)
            if trajectory is None:
                continue
            for visit in trajectory.visits:
                key = (
                    trajectory.cabin_id,
                    visit.visit_index,
                    visit.route_option_id,
                )
                result[key] = result.get(key, 0.0) + value
        return result

    def _build_corridor(
        self,
        *,
        family_id: str,
        start_tick: DddTimeTick,
        end_tick: DddTimeTick,
        members: tuple[DddTrajectoryMergeOccurrence, ...],
        incumbent_by_cabin: dict[int, DddReferenceTrajectory],
        route_mass: dict[tuple[int, int, str], float],
    ) -> DddTrajectoryMergeCorridor:
        released: set[DddTrajectoryVisitPosition] = set()
        deviation_mass = 0.0
        fractional_mass = 0.0
        for member in members:
            trajectory = incumbent_by_cabin[member.cabin_id]
            visits_by_index = {visit.visit_index: visit for visit in trajectory.visits}
            first = max(0, member.visit_index - self.upstream_visit_count)
            last = member.visit_index + self.downstream_visit_count
            for visit_index in range(first, last + 1):
                if visit_index in visits_by_index:
                    released.add(
                        DddTrajectoryVisitPosition(member.cabin_id, visit_index)
                    )
            incumbent_visit = visits_by_index[member.visit_index]
            incumbent_mass = route_mass.get(
                (
                    member.cabin_id,
                    member.visit_index,
                    incumbent_visit.route_option_id,
                ),
                0.0,
            )
            incumbent_mass = min(1.0, max(0.0, incumbent_mass))
            deviation_mass += 1.0 - incumbent_mass
            fractional_mass += min(incumbent_mass, 1.0 - incumbent_mass)
        fixed = tuple(
            sorted(
                DddCpSatFixedRouteDecision(
                    cabin_id=trajectory.cabin_id,
                    visit_index=visit.visit_index,
                    route_option_id=visit.route_option_id,
                )
                for trajectory in incumbent_by_cabin.values()
                for visit in trajectory.visits
                if DddTrajectoryVisitPosition(
                    trajectory.cabin_id, visit.visit_index
                )
                not in released
            )
        )
        released_tuple = tuple(sorted(released))
        payload = (
            f"family={family_id}|window={start_tick}:{end_tick}|"
            f"release={','.join(f'{item.cabin_id}:{item.visit_index}' for item in released_tuple)}"
        )
        return DddTrajectoryMergeCorridor(
            id=f"merge_time_corridor::{sha256(payload.encode()).hexdigest()}",
            family_id=family_id,
            window_start_tick=start_tick,
            window_end_tick=end_tick,
            released_positions=released_tuple,
            fixed_route_decisions=fixed,
            merge_occurrence_count=len(members),
            deviation_mass=deviation_mass,
            fractional_mass=fractional_mass,
        )


@dataclass(frozen=True)
class DddTrajectoryMergeCorridorPrimalResult:
    corridor: DddTrajectoryMergeCorridor
    coordinated: DddTrajectoryCoordinatedPrimalResult


@dataclass(frozen=True)
class DddTrajectoryMergeCorridorPrimalOptimizer:
    """Passenger-guided CP fix-and-optimize in one merge/time corridor."""

    time_limit_seconds: float
    num_workers: int = 8
    max_candidate_count: int = 1
    maximum_preference_count: int = 2_000

    def optimize(
        self,
        *,
        problem: DddNetworkTimeProblem,
        artifact: EanBuildArtifact,
        passenger_build: EanPassengerCandidateBuildResult,
        objective: EanPassengerObjective,
        lp_result: DddTrajectoryPassengerLpResult,
        waiting_policy: DddTrajectoryWaitingPolicy,
        incumbent_trajectories: tuple[DddReferenceTrajectory, ...],
        corridor: DddTrajectoryMergeCorridor,
        boundary_occurrences: tuple[DddReferenceResourceOccurrence, ...] = (),
        excluded_schedules: tuple[tuple[DddRecoveredSchedule, ...], ...] = (),
    ) -> DddTrajectoryMergeCorridorPrimalResult:
        corridor.validate(incumbent_trajectories)
        coordinated = DddTrajectoryCoordinatedPrimalGenerator(
            time_limit_seconds=self.time_limit_seconds,
            num_workers=self.num_workers,
            max_candidate_count=self.max_candidate_count,
            maximum_preference_count=self.maximum_preference_count,
        ).generate(
            problem=problem,
            artifact=artifact,
            passenger_build=passenger_build,
            objective=objective,
            lp_result=lp_result,
            waiting_policy=waiting_policy,
            boundary_occurrences=boundary_occurrences,
            excluded_schedules=excluded_schedules,
            hint_trajectories=incumbent_trajectories,
            fixed_route_decisions=corridor.fixed_route_decisions,
            exclude_hint_schedule=True,
        )
        return DddTrajectoryMergeCorridorPrimalResult(
            corridor=corridor,
            coordinated=coordinated,
        )
