"""Frozen, solver-independent construction of the thesis ring experiments."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from math import ceil

from .thesis_contract import HEADWAY_CONTRACT, THESIS_CONTRACT_ID, ThesisWindows

from .ddd_reservoir_arc_flow import (
    DddReservoirArcFlowRunConfig,
    prepare_ddd_reservoir_arc_flow_run,
)
from .ddd_fixed_k_arc_flow import (
    DddFixedKArcFlowRunConfig,
    DddPreparedFixedKArcFlowRun,
    prepare_ddd_fixed_k_arc_flow_run,
)
from ..optimization.ddd.cp_sat_certificate import stable_fingerprint
from ..optimization.ddd.reservoir_arc_flow_problem import DddReservoirOperatingMode
from ..optimization.ddd.reservoir_boundary import ReservoirBoundaryPolicy
from ..optimization.ddd.reservoir_cp_sat_problem import DddReservoirCpSatProblem
from ..optimization.ddd.fixed_k import DddFixedKOperatingMode, DddFixedKStartPolicy
from ..optimization.ddd.time_ticks import (
    DDD_TIME_TICK_SECONDS,
    ddd_seconds_to_tick,
    ddd_tick_to_seconds,
)
from ..optimization.ean import EanPassengerObjective
from ..optimization.ean.builders.passenger_builder import (
    EanPassengerCandidateBuildResult,
    build_ean_ride_candidates,
)
from ..optimization.ean.models import EanDemandGroup


class ThesisTopology(StrEnum):
    T5R = "t5r"
    T6R = "t6r"


class ThesisGeometry(StrEnum):
    G300 = "g300"
    G500 = "g500"
    G800 = "g800"
    G1200 = "g1200"
    GUNEQ_V2 = "guneq_v2"


class ThesisDemandFamily(StrEnum):
    F0 = "f0"
    F2 = "f2"
    F3 = "f3"
    F4 = "f4"


class ThesisDemandProfile(StrEnum):
    P0 = "p0"
    P1 = "p1"
    P4 = "p4"


class ThesisObjective(StrEnum):
    UNSERVED = "unserved"
    JOURNEY_TIME = "journey_time"


@dataclass(frozen=True, slots=True)
class ThesisExperimentGroup:
    group_id: str
    topology: ThesisTopology
    geometry: ThesisGeometry
    demand_family: ThesisDemandFamily
    demand_profile: ThesisDemandProfile
    objective: ThesisObjective


def core_thesis_experiment_groups() -> tuple[ThesisExperimentGroup, ...]:
    """The nine implemented core curves; T6L is a separate follow-up package."""
    capacity = tuple(
        ThesisExperimentGroup(
            f"capacity_{topology.value}_{family.value}_g800_p0",
            topology,
            ThesisGeometry.G800,
            family,
            ThesisDemandProfile.P0,
            ThesisObjective.UNSERVED,
        )
        for topology in (ThesisTopology.T5R, ThesisTopology.T6R)
        for family in (
            ThesisDemandFamily.F2,
            ThesisDemandFamily.F0,
            ThesisDemandFamily.F4,
        )
    )
    journey = tuple(
        ThesisExperimentGroup(
            f"journey_t5r_{family.value}_g300_p0",
            ThesisTopology.T5R,
            ThesisGeometry.G300,
            family,
            ThesisDemandProfile.P0,
            ThesisObjective.JOURNEY_TIME,
        )
        for family in (
            ThesisDemandFamily.F3,
            ThesisDemandFamily.F0,
            ThesisDemandFamily.F4,
        )
    )
    return (*capacity, *journey)


def thesis_g500_experiment_groups() -> tuple[ThesisExperimentGroup, ...]:
    """The twelve frozen G500/P0 groups selected for the thesis campaign."""
    families = (
        ThesisDemandFamily.F0,
        ThesisDemandFamily.F2,
        ThesisDemandFamily.F3,
        ThesisDemandFamily.F4,
    )
    capacity = tuple(
        ThesisExperimentGroup(
            f"capacity_{topology.value}_{family.value}_g500_p0",
            topology,
            ThesisGeometry.G500,
            family,
            ThesisDemandProfile.P0,
            ThesisObjective.UNSERVED,
        )
        for topology in (ThesisTopology.T5R, ThesisTopology.T6R)
        for family in families
    )
    journey = tuple(
        ThesisExperimentGroup(
            f"journey_t5r_{family.value}_g500_p0",
            ThesisTopology.T5R,
            ThesisGeometry.G500,
            family,
            ThesisDemandProfile.P0,
            ThesisObjective.JOURNEY_TIME,
        )
        for family in families
    )
    return (*capacity, *journey)


def geometric_fleet_caps(
    all_stop_cabins: int,
    port_dispatch_upper_bound_cabins: int,
    *,
    count: int = 5,
) -> tuple[int, ...]:
    """Return unique geometrically spaced caps with both endpoints included."""
    if not 1 <= all_stop_cabins <= port_dispatch_upper_bound_cabins:
        raise ValueError("fleet-cap endpoints are inconsistent")
    if count < 2:
        raise ValueError("at least two fleet-cap points are required")
    ratio = (port_dispatch_upper_bound_cabins / all_stop_cabins) ** (1 / (count - 1))
    values = [all_stop_cabins]
    values.extend(
        ceil(all_stop_cabins * ratio**index) for index in range(1, count - 1)
    )
    values.append(port_dispatch_upper_bound_cabins)
    return tuple(dict.fromkeys(values))


@dataclass(frozen=True, slots=True)
class ExperimentCaseSpec:
    topology: ThesisTopology
    geometry: ThesisGeometry
    demand_family: ThesisDemandFamily
    demand_profile: ThesisDemandProfile
    objective: ThesisObjective
    demand_total: int
    release_resolution_seconds: int = 30
    maximum_wait_seconds: float = 1200.0
    schema: str = "thesis_experiment_case_v1"

    @property
    def example_id(self) -> str:
        return f"thesis_{self.topology.value}_{self.geometry.value}_b_v1"

    @property
    def case_id(self) -> str:
        return "__".join(
            (
                self.topology.value,
                self.geometry.value,
                self.demand_family.value,
                self.demand_profile.value,
                self.objective.value,
                f"n{self.demand_total}",
                f"r{self.release_resolution_seconds}",
            )
        )

    @property
    def fingerprint(self) -> str:
        return stable_fingerprint(asdict(self))

    def validate(self) -> None:
        for enum_type, value in (
            (ThesisTopology, self.topology),
            (ThesisGeometry, self.geometry),
            (ThesisDemandFamily, self.demand_family),
            (ThesisDemandProfile, self.demand_profile),
            (ThesisObjective, self.objective),
        ):
            if not isinstance(value, enum_type):
                raise ValueError(f"invalid {enum_type.__name__}")
        if self.geometry is ThesisGeometry.GUNEQ_V2 and self.topology is not ThesisTopology.T6R:
            raise ValueError("GUNEQ-v2 is defined only for T6R")
        if type(self.demand_total) is not int or self.demand_total <= 0:
            raise ValueError("demand_total must be a positive integer")
        if self.release_resolution_seconds not in (5, 15, 30):
            raise ValueError("release resolution must be 5, 15, or 30 seconds")
        if self.maximum_wait_seconds < 0:
            raise ValueError("maximum_wait_seconds must be nonnegative")


@dataclass(frozen=True, slots=True)
class PreparedExperimentCase:
    spec: ExperimentCaseSpec
    scenario: object
    problem: DddReservoirCpSatProblem
    all_stop_cycle_tick: int
    all_stop_headway_tick: int
    all_stop_unconstrained_saturation_cabins: int
    all_stop_reference_cabins: int
    physical_dispatch_bound: int
    configured_fleet_cap: int
    demand_window_tick: int
    completion_tick: int
    recovery_tick: int
    source_manifest: dict

    @property
    def manifest(self) -> dict:
        return {
            "schema": "prepared_thesis_experiment_v1",
            "case_spec": asdict(self.spec),
            "case_fingerprint": self.spec.fingerprint,
            "problem_fingerprint": self.problem.fingerprint,
            "scenario_id": self.scenario.id,
            "all_stop_cycle_tick": self.all_stop_cycle_tick,
            "all_stop_headway_tick": self.all_stop_headway_tick,
            "all_stop_unconstrained_saturation_cabins": self.all_stop_unconstrained_saturation_cabins,
            "all_stop_reference_cabins": self.all_stop_reference_cabins,
            "physical_dispatch_bound": self.physical_dispatch_bound,
            "configured_fleet_cap": self.configured_fleet_cap,
            "demand_window_tick": self.demand_window_tick,
            "completion_tick": self.completion_tick,
            "recovery_tick": self.recovery_tick,
            "sources": self.source_manifest,
        }


def prepare_experiment_case(
    spec: ExperimentCaseSpec,
    *,
    fleet_cap: int | None = None,
) -> PreparedExperimentCase:
    spec.validate()
    entry_state = "S0_entry_cw"
    # The first pass derives the physical All-Stop cycle and headway. Its
    # provisional horizons do not enter the returned fingerprint.
    initial = prepare_ddd_reservoir_arc_flow_run(
        DddReservoirArcFlowRunConfig(
            example_id=spec.example_id,
            available_fleet_count=1,
            entry_state_id=entry_state,
            warmup_seconds=300,
            service_seconds=3600,
            recovery_seconds=300,
            waiting_max_seconds=spec.maximum_wait_seconds,
            waiting_step_seconds=DDD_TIME_TICK_SECONDS,
            dispatch_step_seconds=DDD_TIME_TICK_SECONDS,
        )
    )
    cycle_tick = ddd_seconds_to_tick(initial.problem.all_stop_cycle_seconds)
    headway_tick = ddd_seconds_to_tick(initial.problem.all_stop_headway_seconds)
    unconstrained_saturation = initial.all_stop_maximum_cabin_count
    warmup_seconds = ddd_tick_to_seconds(cycle_tick)
    demand_window_tick = ddd_seconds_to_tick(45 * 60)

    station_count = 5 if spec.topology is ThesisTopology.T5R else 6
    longest_od_legs = station_count // 2
    longest_all_stop_ride_tick = ceil(longest_od_legs * cycle_tick / station_count)
    completion_tick = max(
        ddd_seconds_to_tick(15 * 60),
        headway_tick + longest_all_stop_ride_tick,
    )
    service_tick = demand_window_tick + completion_tick
    recovery_tick = cycle_tick

    initial_problem = DddReservoirCpSatProblem.from_arc_flow(initial.problem)
    boundary = ReservoirBoundaryPolicy.from_headway_policy(
        initial_problem.movement_core, initial_problem.entry_state_id, initial.headway_policy
    )
    # This is a necessary port-throughput upper bound, not a promise that the
    # station resources admit every fleet size below it.
    physical_bound = cycle_tick // boundary.headway_tick
    reference_cabins = unconstrained_saturation
    configured_fleet = reference_cabins if fleet_cap is None else fleet_cap
    if type(configured_fleet) is not int or not 1 <= configured_fleet <= physical_bound:
        raise ValueError(
            f"fleet_cap must lie in [1, port dispatch upper bound {physical_bound}]"
        )

    final = prepare_ddd_reservoir_arc_flow_run(
        DddReservoirArcFlowRunConfig(
            example_id=spec.example_id,
            available_fleet_count=configured_fleet,
            entry_state_id=entry_state,
            warmup_seconds=warmup_seconds,
            service_seconds=ddd_tick_to_seconds(service_tick),
            recovery_seconds=ddd_tick_to_seconds(recovery_tick),
            waiting_max_seconds=spec.maximum_wait_seconds,
            waiting_step_seconds=DDD_TIME_TICK_SECONDS,
            dispatch_step_seconds=DDD_TIME_TICK_SECONDS,
        )
    )
    problem = DddReservoirCpSatProblem.from_arc_flow(final.problem)
    final_boundary = ReservoirBoundaryPolicy.from_headway_policy(
        problem.movement_core, problem.entry_state_id, final.headway_policy
    )
    if final_boundary != boundary:
        raise ValueError("reservoir boundary changed with fleet cardinality")
    releases = build_demand_groups(
        spec,
        station_ids=tuple(f"S{i}" for i in range(station_count)),
        free_rope_lengths=_free_rope_lengths(final.scenario),
        service_start_tick=cycle_tick,
        demand_window_tick=demand_window_tick,
    )
    problem = replace(
        problem,
        demand_groups=releases,
        available_fleet_count=configured_fleet,
        dispatch_start_seconds=0.0,
        dispatch_end_seconds=warmup_seconds,
        dispatch_step_seconds=DDD_TIME_TICK_SECONDS,
        return_start_seconds=ddd_tick_to_seconds(cycle_tick + service_tick),
        boundary_policy=boundary,
    )
    problem.validate()
    scenario = replace(
        final.scenario,
        experiment_metadata={
            "schema": "thesis_experiment_frontend_v1",
            "topology": spec.topology.value,
            "geometry": spec.geometry.value,
            "architecture": "B",
            "demand_family": spec.demand_family.value,
            "demand_profile": spec.demand_profile.value,
            "objective": spec.objective.value,
            "demand_total": spec.demand_total,
            "release_resolution_seconds": spec.release_resolution_seconds,
            "warmup_seconds": warmup_seconds,
            "demand_window_seconds": ddd_tick_to_seconds(demand_window_tick),
            "completion_seconds": ddd_tick_to_seconds(completion_tick),
            "recovery_seconds": ddd_tick_to_seconds(recovery_tick),
            "all_stop_cycle_seconds": ddd_tick_to_seconds(cycle_tick),
            "all_stop_headway_seconds": ddd_tick_to_seconds(headway_tick),
            "all_stop_reference_cabins": reference_cabins,
            "port_dispatch_upper_bound_cabins": physical_bound,
            "physical_dispatch_bound_scope": "reservoir_port_throughput_only",
            "configured_fleet_cap": configured_fleet,
        },
    )
    return PreparedExperimentCase(
        spec=spec,
        scenario=scenario,
        problem=problem,
        all_stop_cycle_tick=cycle_tick,
        all_stop_headway_tick=headway_tick,
        all_stop_unconstrained_saturation_cabins=unconstrained_saturation,
        all_stop_reference_cabins=reference_cabins,
        physical_dispatch_bound=physical_bound,
        configured_fleet_cap=configured_fleet,
        demand_window_tick=demand_window_tick,
        completion_tick=completion_tick,
        recovery_tick=recovery_tick,
        source_manifest={
            "technology": {
                "citation": "Haimerl et al. (2022), WSC, section 4.1, p. 1418",
                "url": "https://informs-sim.org/wsc22papers/138.pdf",
                "use": "6 m/s rope, 0.3 m/s platform, 10-person cabin",
            },
            "station_geometry": {
                "citation": "GART/STRMTG/Cerema (2023), section 7.3, p. 138",
                "url": "https://www.gart.org/wp-content/uploads/2023/08/Guide-accessibilite-transport-par-cable_Juin-2023.pdf#page=139",
                "use": "scale reference for the documented idealized station derivation",
            },
            "free_rope_geometry": {
                "citation": "Ile-de-France Mobilites, Cable C1 press kit",
                "url": "https://www.iledefrance-mobilites.fr/le-reseau/projets/cablec1/mediatheque/kit-presse-c1",
                "use": (
                    "G500 uses 500 m free-rope sections as a synthetic lower-scale "
                    "case motivated by the published 500-1800 m station spacings; "
                    "station paths are modelled separately"
                ),
            },
            "geometry_decisions": "docs/thesis/experiment_definition_register_20260913.md sections 6-8",
            "demand_functions": "docs/thesis/experiment_definition_register_20260913.md sections 12-13",
        },
    )


def prepare_fixed_k_experiment(
    spec: ExperimentCaseSpec,
    *,
    cabins: int,
    time_limit_seconds: float,
    workers: int,
    seed: int,
    output_flag: bool = False,
    operating_mode: DddFixedKOperatingMode = DddFixedKOperatingMode.SKIP_STOP,
) -> tuple[DddFixedKArcFlowRunConfig, DddPreparedFixedKArcFlowRun, dict]:
    """Prepare the exact no-wait Journey-Time domain at two reference cycles."""
    spec.validate()
    if spec.objective is not ThesisObjective.JOURNEY_TIME:
        raise ValueError("fixed-K thesis preparation is defined for journey_time")
    common = dict(
        example_id=spec.example_id,
        cabin_count=cabins,
        operating_mode=operating_mode,
        objective=EanPassengerObjective.JOURNEY_TIME,
        start_policy=DddFixedKStartPolicy.BALANCED_REFERENCE,
        total_time_limit_seconds=time_limit_seconds,
        cp_seed_time_limit_seconds=min(30.0, time_limit_seconds * 0.1),
        cp_seed_workers=workers,
        solver_threads=workers,
        seed=seed,
        output_flag=output_flag,
        require_full_service=True,
        use_primal_start=False,
    )
    first_config = DddFixedKArcFlowRunConfig(**common)
    first = prepare_ddd_fixed_k_arc_flow_run(first_config)
    if first.start_layout_cycle_seconds is None:
        raise ValueError("balanced Journey-Time case did not expose its All-Stop cycle")
    cycle_tick = ddd_seconds_to_tick(first.start_layout_cycle_seconds)
    headway_tick = ddd_seconds_to_tick(
        first.start_layout_bottleneck_headway_seconds or 0
    )
    station_count = 5 if spec.topology is ThesisTopology.T5R else 6
    windows = ThesisWindows(ddd_tick_to_seconds(cycle_tick))
    completion_tick = ddd_seconds_to_tick(windows.completion_seconds)
    horizon_tick = 2 * cycle_tick + completion_tick
    config = DddFixedKArcFlowRunConfig(
        **common,
        horizon_seconds=ddd_tick_to_seconds(horizon_tick),
        tail_seconds=windows.continuation_seconds,
    )
    prepared = prepare_ddd_fixed_k_arc_flow_run(config)
    groups = build_demand_groups(
        spec,
        station_ids=tuple(f"S{i}" for i in range(station_count)),
        free_rope_lengths=_free_rope_lengths(prepared.scenario),
        service_start_tick=0,
        demand_window_tick=2 * cycle_tick,
    )
    passenger_build = EanPassengerCandidateBuildResult(
        groups,
        build_ean_ride_candidates(groups, prepared.problem.artifact),
    )
    problem = replace(prepared.problem, passenger_build=passenger_build)
    problem.validate()
    scenario = replace(
        prepared.scenario,
        experiment_metadata={
            "schema": "thesis_experiment_frontend_v1",
            "headway_contract": HEADWAY_CONTRACT,
            "thesis_contract_id": THESIS_CONTRACT_ID if spec.topology is ThesisTopology.T5R and spec.geometry is ThesisGeometry.G500 else None,
            "topology": spec.topology.value,
            "geometry": spec.geometry.value,
            "architecture": "B",
            "demand_family": spec.demand_family.value,
            "demand_profile": spec.demand_profile.value,
            "objective": spec.objective.value,
            "demand_total": spec.demand_total,
            "release_resolution_seconds": spec.release_resolution_seconds,
            "demand_window_seconds": ddd_tick_to_seconds(2 * cycle_tick),
            "completion_seconds": ddd_tick_to_seconds(completion_tick),
            "continuation_seconds": windows.continuation_seconds,
            "operation_seconds": windows.operation_seconds,
            "all_stop_cycle_seconds": ddd_tick_to_seconds(cycle_tick),
            "all_stop_headway_seconds": ddd_tick_to_seconds(headway_tick),
            "all_stop_reference_cabins": prepared.all_stop_maximum_cabin_count,
            "configured_fixed_cabins": cabins,
            "operating_mode": operating_mode.value,
        },
    )
    prepared = replace(prepared, scenario=scenario, problem=problem)
    return config, prepared, {
        "headway_contract": HEADWAY_CONTRACT,
        "thesis_contract_id": scenario.experiment_metadata["thesis_contract_id"],
        "problem_fingerprint": problem.fingerprint,
        "cycle_tick": cycle_tick,
        "demand_window_tick": 2 * cycle_tick,
        "completion_tick": completion_tick,
        "horizon_tick": horizon_tick,
        "continuation_tick": ddd_seconds_to_tick(windows.continuation_seconds),
        "operation_tick": ddd_seconds_to_tick(windows.operation_seconds),
        "cabins": cabins,
        "operating_mode": operating_mode.value,
        "demand_groups": len(groups),
        "ride_candidates": len(passenger_build.ride_candidates),
    }


def build_demand_groups(
    spec: ExperimentCaseSpec,
    *,
    station_ids: tuple[str, ...],
    free_rope_lengths: tuple[float, ...],
    service_start_tick: int,
    demand_window_tick: int,
) -> tuple[EanDemandGroup, ...]:
    """Build a stable nested person prefix and aggregate only release times."""
    cells = _directional_od_weights(spec.demand_family, station_ids, free_rope_lengths)
    if not cells:
        raise ValueError("demand family has no OD in the modelled direction")
    total_weight = sum(weight for _, _, weight in cells)
    counts = [0] * len(cells)
    person_od: list[int] = []
    for person_index in range(spec.demand_total):
        completed = person_index + 1
        selected = max(
            range(len(cells)),
            key=lambda i: (completed * cells[i][2] - counts[i] * total_weight, -i),
        )
        counts[selected] += 1
        person_od.append(selected)

    local_indices = [0] * len(cells)
    aggregated: dict[tuple[int, int], int] = defaultdict(int)
    resolution_tick = ddd_seconds_to_tick(spec.release_resolution_seconds)
    for od_index in person_od:
        sequence_index = local_indices[od_index]
        local_indices[od_index] += 1
        quantile = _van_der_corput(sequence_index + 1, 2)
        fraction = _inverse_profile_cdf(spec.demand_profile, quantile)
        raw_tick = min(demand_window_tick - 1, int(fraction * demand_window_tick))
        rounded_tick = min(
            demand_window_tick,
            ((raw_tick + resolution_tick - 1) // resolution_tick) * resolution_tick,
        )
        aggregated[(od_index, rounded_tick)] += 1

    groups = []
    for (od_index, release_tick), count in sorted(aggregated.items()):
        origin, destination, _ = cells[od_index]
        absolute_tick = service_start_tick + release_tick
        groups.append(
            EanDemandGroup(
                id=(
                    f"{spec.demand_family.value}:{spec.demand_profile.value}:"
                    f"{origin}:{destination}:t{absolute_tick}"
                ),
                origin_station_id=origin,
                destination_station_id=destination,
                release_time_seconds=ddd_tick_to_seconds(absolute_tick),
                count=count,
            )
        )
    return tuple(groups)


def _directional_od_weights(family, stations, lengths):
    n = len(stations)
    if len(lengths) != n:
        raise ValueError("ring needs one free-rope length per station")
    total = sum(lengths)
    raw = []
    for i, origin in enumerate(stations):
        for j, destination in enumerate(stations):
            if i == j:
                continue
            hops = (j - i) % n
            clockwise = sum(lengths[(i + h) % n] for h in range(hops))
            opposite = total - clockwise
            direction_weight = 2 if clockwise < opposite else 1 if clockwise == opposite else 0
            include = False
            if family is ThesisDemandFamily.F0:
                include = True
            elif family is ThesisDemandFamily.F2:
                include = (origin, destination) in {
                    ("S1", "S3"), ("S3", "S1"), ("S2", "S4"), ("S4", "S2")
                }
            elif family is ThesisDemandFamily.F3:
                include = hops == n // 2
            elif family is ThesisDemandFamily.F4:
                include = min(hops, n - hops) == 1
            if include and direction_weight:
                raw.append((origin, destination, direction_weight))
    return tuple(sorted(raw))


def _free_rope_lengths(scenario) -> tuple[float, ...]:
    return tuple(
        segment.length_m
        for segment in scenario.track_segments
        if segment.kind.value == "rope"
    )


def _van_der_corput(index: int, base: int) -> float:
    value, denominator = 0.0, 1.0
    while index:
        index, digit = divmod(index, base)
        denominator *= base
        value += digit / denominator
    return value


def _profile_cdf(profile: ThesisDemandProfile, x: float) -> float:
    if profile is ThesisDemandProfile.P0:
        return x
    if profile is ThesisDemandProfile.P1:
        # a=2. Integral of (1 + 2g(x)) / 2 on [0,1].
        return (
            0.5 * x + x * x
            if x <= 0.5
            else 2.5 * x - x * x - 0.5
        )
    if profile is ThesisDemandProfile.P4:
        beta = 0.5
        result = (1 - beta) * x
        width = 2 / 45
        for centre in (7.5 / 45, 22.5 / 45, 37.5 / 45):
            lower, upper = centre - width / 2, centre + width / 2
            result += beta / 3 * max(0.0, min(x, upper) - lower) / width
        return result
    raise ValueError("unsupported demand profile")


def _inverse_profile_cdf(profile: ThesisDemandProfile, q: float) -> float:
    lower, upper = 0.0, 1.0
    for _ in range(60):
        middle = (lower + upper) / 2
        if _profile_cdf(profile, middle) < q:
            lower = middle
        else:
            upper = middle
    return upper
