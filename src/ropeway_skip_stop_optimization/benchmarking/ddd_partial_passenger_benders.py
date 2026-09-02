from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from time import perf_counter
from typing import Callable

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    DddFixedKArcFlowRunConfig,
    prepare_ddd_fixed_k_arc_flow_run,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddArcFlowPassengerDomain,
    DddArcFlowPassengerDomainBuilder,
    DddArcFlowProblemPreparer,
    DddPartialPassengerRootConfig,
    DddPartialPassengerCutStrategy,
    DddPartialPassengerRootCutSolver,
    DddPartialPassengerRootProgress,
    DddPartialPassengerRootResult,
    DddPassengerCoreConfig,
    DddPassengerCorePolicy,
)


@dataclass(frozen=True, slots=True)
class DddPartialPassengerGateVariant:
    id: str
    policy: DddPassengerCorePolicy
    core_variable_fraction: float
    core_nonzero_fraction: float

    def validate(self) -> None:
        if not self.id or not isinstance(self.policy, DddPassengerCorePolicy):
            raise ValueError("partial Passenger gate variant is invalid")
        for value in (self.core_variable_fraction, self.core_nonzero_fraction):
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("partial Passenger core fractions must lie in [0, 1]")
        if self.policy in {
            DddPassengerCorePolicy.NONE,
            DddPassengerCorePolicy.ALL,
        }:
            expected = 0.0 if self.policy is DddPassengerCorePolicy.NONE else 1.0
            if (
                self.core_variable_fraction != expected
                or self.core_nonzero_fraction != expected
            ):
                raise ValueError("NONE/ALL Passenger policies need exact boundaries")


@dataclass(frozen=True, slots=True)
class DddPartialPassengerGateConfig:
    run: DddFixedKArcFlowRunConfig
    variants: tuple[DddPartialPassengerGateVariant, ...]
    per_variant_time_limit_seconds: float = 120.0
    max_iterations: int = 30
    reference_lp_objective: float | None = None
    reference_problem_fingerprint: str | None = None
    required_bound_fraction: float = 0.9
    maximum_core_nonzero_fraction: float = 0.4
    cut_strategy: DddPartialPassengerCutStrategy = (
        DddPartialPassengerCutStrategy.STANDARD
    )
    pareto_time_limit_seconds: float = 10.0

    def validate(self) -> None:
        self.run.validate()
        if self.run.waiting_headway_multiplier != 0:
            raise ValueError("partial Passenger gate version 1 is No-Wait only")
        if not self.variants:
            raise ValueError("partial Passenger gate needs at least one variant")
        for variant in self.variants:
            variant.validate()
        ids = tuple(item.id for item in self.variants)
        if len(ids) != len(set(ids)):
            raise ValueError("partial Passenger gate variant IDs must be unique")
        if (
            not math.isfinite(self.per_variant_time_limit_seconds)
            or self.per_variant_time_limit_seconds <= 0
            or self.max_iterations <= 0
        ):
            raise ValueError("partial Passenger gate budgets are invalid")
        if self.reference_lp_objective is not None and (
            not math.isfinite(self.reference_lp_objective)
            or self.reference_lp_objective <= 0
        ):
            raise ValueError("partial Passenger reference LP objective is invalid")
        if self.reference_problem_fingerprint is not None and not (
            len(self.reference_problem_fingerprint) == 64
            and all(
                character in "0123456789abcdef"
                for character in self.reference_problem_fingerprint
            )
        ):
            raise ValueError("partial Passenger reference fingerprint is invalid")
        if not 0 < self.required_bound_fraction <= 1:
            raise ValueError("partial Passenger required bound fraction is invalid")
        if not 0 <= self.maximum_core_nonzero_fraction <= 1:
            raise ValueError("partial Passenger core nonzero gate is invalid")
        if not isinstance(self.cut_strategy, DddPartialPassengerCutStrategy):
            raise ValueError("partial Passenger gate cut strategy is invalid")
        if (
            not math.isfinite(self.pareto_time_limit_seconds)
            or self.pareto_time_limit_seconds <= 0
        ):
            raise ValueError("partial Passenger gate Pareto budget is invalid")


@dataclass(frozen=True, slots=True)
class DddPartialPassengerGateVariantResult:
    variant: DddPartialPassengerGateVariant
    root: DddPartialPassengerRootResult
    core_variable_fraction: float
    core_nonzero_fraction: float
    achieved_reference_fraction: float | None
    passed: bool


@dataclass(frozen=True, slots=True)
class DddPartialPassengerGateResult:
    config: DddPartialPassengerGateConfig
    problem_fingerprint: str
    passenger_domain_fingerprint: str
    passenger_variable_count: int
    passenger_nonzero_count: int
    reference_verified: bool
    preparation_seconds: float
    passenger_domain_build_seconds: float
    variants: tuple[DddPartialPassengerGateVariantResult, ...]
    passed_variant_ids: tuple[str, ...]
    total_seconds: float

    def to_payload(self) -> dict[str, object]:
        return {
            "method": "ddd_partial_passenger_root_gate",
            "problem_fingerprint": self.problem_fingerprint,
            "passenger_domain_fingerprint": self.passenger_domain_fingerprint,
            "example_id": self.config.run.example_id,
            "exact_active_cabin_count": self.config.run.cabin_count,
            "operating_mode": self.config.run.operating_mode.value,
            "objective": self.config.run.objective.value,
            "start_policy": self.config.run.start_policy.value,
            "passenger_variable_count": self.passenger_variable_count,
            "passenger_nonzero_count": self.passenger_nonzero_count,
            "reference_lp_objective": self.config.reference_lp_objective,
            "reference_problem_fingerprint": (
                self.config.reference_problem_fingerprint
            ),
            "reference_verified": self.reference_verified,
            "required_bound_fraction": self.config.required_bound_fraction,
            "maximum_core_nonzero_fraction": (
                self.config.maximum_core_nonzero_fraction
            ),
            "cut_strategy": self.config.cut_strategy.value,
            "pareto_time_limit_seconds": self.config.pareto_time_limit_seconds,
            "preparation_seconds": self.preparation_seconds,
            "passenger_domain_build_seconds": self.passenger_domain_build_seconds,
            "passed_variant_ids": list(self.passed_variant_ids),
            "variants": [_variant_payload(item) for item in self.variants],
            "total_seconds": self.total_seconds,
        }


DddPartialPassengerGateProgressHook = Callable[
    [str, DddPartialPassengerRootProgress], None
]


@dataclass(frozen=True, slots=True)
class DddPartialPassengerGateRunner:
    def run(
        self,
        config: DddPartialPassengerGateConfig,
        *,
        progress_hook: DddPartialPassengerGateProgressHook | None = None,
    ) -> DddPartialPassengerGateResult:
        config.validate()
        started = perf_counter()
        preparation_started = perf_counter()
        run = prepare_ddd_fixed_k_arc_flow_run(config.run)
        prepared = DddArcFlowProblemPreparer().build(run.problem)
        preparation_seconds = perf_counter() - preparation_started
        domain_started = perf_counter()
        domain = DddArcFlowPassengerDomainBuilder().build(prepared)
        domain_seconds = perf_counter() - domain_started
        passenger_nonzeros = _passenger_nonzero_count(domain)
        reference_verified = (
            config.reference_problem_fingerprint == prepared.problem.fingerprint
        )
        results = []
        for variant in config.variants:
            core_config = _core_config(
                variant,
                variable_count=len(domain.variables),
                nonzero_count=passenger_nonzeros,
            )
            root = DddPartialPassengerRootCutSolver(
                DddPartialPassengerRootConfig(
                    core=core_config,
                    time_limit_seconds=config.per_variant_time_limit_seconds,
                    max_iterations=config.max_iterations,
                    threads=config.run.solver_threads,
                    output_flag=config.run.output_flag,
                    cut_strategy=config.cut_strategy,
                    pareto_time_limit_seconds=config.pareto_time_limit_seconds,
                )
            ).solve(
                prepared,
                passenger_domain=domain,
                progress_hook=(
                    None
                    if progress_hook is None
                    else lambda sample, variant_id=variant.id: progress_hook(
                        variant_id,
                        sample,
                    )
                ),
            )
            variable_fraction = root.core_passenger_variable_count / max(
                1, len(domain.variables)
            )
            nonzero_fraction = root.partition.core_nonzero_count / max(
                1, passenger_nonzeros
            )
            achieved = (
                None
                if config.reference_lp_objective is None
                else root.certified_lower_bound / config.reference_lp_objective
            )
            passed = (
                reference_verified
                and achieved is not None
                and achieved + 1e-9 >= config.required_bound_fraction
                and nonzero_fraction
                <= config.maximum_core_nonzero_fraction + 1e-9
            )
            results.append(
                DddPartialPassengerGateVariantResult(
                    variant=variant,
                    root=root,
                    core_variable_fraction=variable_fraction,
                    core_nonzero_fraction=nonzero_fraction,
                    achieved_reference_fraction=achieved,
                    passed=passed,
                )
            )
        return DddPartialPassengerGateResult(
            config=config,
            problem_fingerprint=prepared.problem.fingerprint,
            passenger_domain_fingerprint=domain.fingerprint,
            passenger_variable_count=len(domain.variables),
            passenger_nonzero_count=passenger_nonzeros,
            reference_verified=reference_verified,
            preparation_seconds=preparation_seconds,
            passenger_domain_build_seconds=domain_seconds,
            variants=tuple(results),
            passed_variant_ids=tuple(item.variant.id for item in results if item.passed),
            total_seconds=perf_counter() - started,
        )


def write_ddd_partial_passenger_gate_result(
    result: DddPartialPassengerGateResult,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result.to_payload(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _core_config(
    variant: DddPartialPassengerGateVariant,
    *,
    variable_count: int,
    nonzero_count: int,
) -> DddPassengerCoreConfig:
    if variant.policy is DddPassengerCorePolicy.NONE:
        return DddPassengerCoreConfig(policy=variant.policy)
    if variant.policy is DddPassengerCorePolicy.ALL:
        return DddPassengerCoreConfig(policy=variant.policy)
    return DddPassengerCoreConfig(
        policy=variant.policy,
        maximum_variable_count=max(
            1, math.floor(variable_count * variant.core_variable_fraction)
        ),
        maximum_nonzero_count=max(
            1, math.floor(nonzero_count * variant.core_nonzero_fraction)
        ),
    )


def _passenger_nonzero_count(domain: DddArcFlowPassengerDomain) -> int:
    return (
        len(domain.variables)
        + sum(len(row.coefficients) for row in domain.equality_rows)
        + sum(len(row.variable_ids) for row in domain.demand_rows)
        + sum(len(row.variable_ids) for row in domain.capacity_rows)
    )


def _variant_payload(
    result: DddPartialPassengerGateVariantResult,
) -> dict[str, object]:
    root = asdict(result.root)
    root["status"] = result.root.status.value
    root["partition"]["policy"] = result.root.partition.policy.value
    return {
        "id": result.variant.id,
        "policy": result.variant.policy.value,
        "requested_core_variable_fraction": (
            result.variant.core_variable_fraction
        ),
        "requested_core_nonzero_fraction": result.variant.core_nonzero_fraction,
        "actual_core_variable_fraction": result.core_variable_fraction,
        "actual_core_nonzero_fraction": result.core_nonzero_fraction,
        "achieved_reference_fraction": result.achieved_reference_fraction,
        "passed": result.passed,
        "root": root,
    }
