from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ropeway_skip_stop_optimization.optimization.ean.optimizers.movement_model import (
    EanMovementModel,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.passenger_model import (
    EanPassengerModel,
)


class EanVariableFamily(StrEnum):
    SWITCH_TIME = "switch_time"
    EXIT_SWITCH_TIME = "exit_switch_time"
    WAIT_TIME = "wait_time"
    STOP = "stop"
    VISIT_ACTIVE = "visit_active"
    CHECKPOINT_ACTIVE = "checkpoint_active"
    HEADWAY_ORDER = "headway_order"
    PASSENGER_SLOT = "passenger_slot"
    SLOT_BOARD_TIME = "slot_board_time"
    SLOT_ALIGHT_TIME = "slot_alight_time"
    UNSERVED = "unserved"


@dataclass(frozen=True)
class EanVariableFamilyMetrics:
    family: EanVariableFamily
    variable_count: int
    integer_variable_count: int
    fractional_variable_count: int
    fractional_share: float | None
    fractional_distance_sum: float
    maximum_fractional_distance: float
    objective_contribution: float


@dataclass(frozen=True)
class EanRootRelaxationSample:
    runtime_seconds: float
    work: float | None
    node_count: float
    incumbent_objective: float | None
    best_bound: float | None
    linear_objective_value: float
    fractional_variable_count: int
    fractional_distance_sum: float
    families: tuple[EanVariableFamilyMetrics, ...]


@dataclass(frozen=True)
class EanRootRelaxationDiagnostic:
    sample_interval_seconds: float
    samples: tuple[EanRootRelaxationSample, ...]


@dataclass
class EanRootRelaxationRecorder:
    """Sample canonical EAN variable families at the MIP root node."""

    sample_interval_seconds: float = 5.0
    samples: list[EanRootRelaxationSample] = field(default_factory=list)
    _last_sample_runtime: float | None = None
    _groups: tuple[
        tuple[EanVariableFamily, tuple[Any, ...]],
        ...,
    ] = ()
    _variables: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        if self.sample_interval_seconds <= 0:
            raise ValueError("sample_interval_seconds must be positive")

    def bind_models(
        self,
        movement_model: EanMovementModel,
        passenger_model: EanPassengerModel | None,
    ) -> None:
        movement = movement_model.variables
        groups: list[tuple[EanVariableFamily, tuple[Any, ...]]] = [
            (
                EanVariableFamily.SWITCH_TIME,
                _model_variables(movement.switch_time),
            ),
            (
                EanVariableFamily.EXIT_SWITCH_TIME,
                _model_variables(movement.exit_switch_time),
            ),
            (
                EanVariableFamily.WAIT_TIME,
                _model_variables(movement.wait_time),
            ),
            (EanVariableFamily.STOP, _model_variables(movement.stop)),
            (
                EanVariableFamily.VISIT_ACTIVE,
                _model_variables(movement.visit_active),
            ),
            (
                EanVariableFamily.CHECKPOINT_ACTIVE,
                _model_variables(movement.checkpoint_within_horizon),
            ),
            (
                EanVariableFamily.HEADWAY_ORDER,
                _model_variables(movement.headway_order),
            ),
        ]
        if passenger_model is not None:
            passenger = passenger_model.variables
            groups.extend(
                (
                    (
                        EanVariableFamily.PASSENGER_SLOT,
                        _model_variables(passenger.slot),
                    ),
                    (
                        EanVariableFamily.SLOT_BOARD_TIME,
                        _model_variables(passenger.slot_board_time),
                    ),
                    (
                        EanVariableFamily.SLOT_ALIGHT_TIME,
                        _model_variables(passenger.slot_alight_time),
                    ),
                    (
                        EanVariableFamily.UNSERVED,
                        _model_variables(passenger.unserved),
                    ),
                )
            )
        self._groups = tuple(
            (family, variables)
            for family, variables in groups
            if variables
        )
        self._variables = tuple(
            variable
            for _family, variables in self._groups
            for variable in variables
        )

    def begin_run(self) -> None:
        self._last_sample_runtime = None

    def record_callback(
        self,
        model: Any,
        grb: Any,
        where: int,
        *,
        sample_interval_seconds: float,
    ) -> None:
        del sample_interval_seconds
        callback = grb.Callback
        if where != callback.MIPNODE or not self._variables:
            return
        status = _cb_get(
            model,
            getattr(callback, "MIPNODE_STATUS", None),
        )
        if status is None or int(status) != int(grb.OPTIMAL):
            return
        node_count = _cb_get(
            model,
            getattr(callback, "MIPNODE_NODCNT", None),
        )
        if node_count is None or node_count > 0.5:
            return
        runtime = _cb_get(model, getattr(callback, "RUNTIME", None))
        if runtime is None:
            return
        if (
            self._last_sample_runtime is not None
            and runtime - self._last_sample_runtime
            < self.sample_interval_seconds
        ):
            return
        values = _node_relaxation_values(model, self._variables)
        if values is None:
            return

        family_metrics: list[EanVariableFamilyMetrics] = []
        offset = 0
        for family, variables in self._groups:
            family_values = values[offset : offset + len(variables)]
            family_metrics.append(
                _family_metrics(family, variables, family_values)
            )
            offset += len(variables)

        incumbent = _finite_or_none(
            _cb_get(
                model,
                getattr(callback, "MIPNODE_OBJBST", None),
            ),
            grb,
        )
        best_bound = _finite_or_none(
            _cb_get(
                model,
                getattr(callback, "MIPNODE_OBJBND", None),
            ),
            grb,
        )
        self.samples.append(
            EanRootRelaxationSample(
                runtime_seconds=runtime,
                work=_finite_or_none(
                    _cb_get(model, getattr(callback, "WORK", None)),
                    grb,
                ),
                node_count=node_count,
                incumbent_objective=incumbent,
                best_bound=best_bound,
                linear_objective_value=sum(
                    metric.objective_contribution
                    for metric in family_metrics
                ),
                fractional_variable_count=sum(
                    metric.fractional_variable_count
                    for metric in family_metrics
                ),
                fractional_distance_sum=sum(
                    metric.fractional_distance_sum
                    for metric in family_metrics
                ),
                families=tuple(family_metrics),
            )
        )
        self._last_sample_runtime = runtime

    @property
    def diagnostic(self) -> EanRootRelaxationDiagnostic:
        return EanRootRelaxationDiagnostic(
            sample_interval_seconds=self.sample_interval_seconds,
            samples=tuple(self.samples),
        )


def _model_variables(
    variables: dict[Any, Any] | None,
) -> tuple[Any, ...]:
    if variables is None:
        return ()
    return tuple(
        variable
        for variable in variables.values()
        if not isinstance(variable, int | float)
    )


def _node_relaxation_values(
    model: Any,
    variables: tuple[Any, ...],
) -> tuple[float, ...] | None:
    try:
        values = model.cbGetNodeRel(list(variables))
        return tuple(float(value) for value in values)
    except Exception:
        return None


def _family_metrics(
    family: EanVariableFamily,
    variables: tuple[Any, ...],
    values: tuple[float, ...],
) -> EanVariableFamilyMetrics:
    integer_distances = [
        _integer_distance(value)
        for variable, value in zip(variables, values, strict=True)
        if _is_integer_variable(variable)
    ]
    fractional_distances = [
        distance
        for distance in integer_distances
        if distance > 1e-6
    ]
    integer_count = len(integer_distances)
    return EanVariableFamilyMetrics(
        family=family,
        variable_count=len(variables),
        integer_variable_count=integer_count,
        fractional_variable_count=len(fractional_distances),
        fractional_share=(
            len(fractional_distances) / integer_count
            if integer_count
            else None
        ),
        fractional_distance_sum=sum(fractional_distances),
        maximum_fractional_distance=max(
            fractional_distances,
            default=0.0,
        ),
        objective_contribution=sum(
            _objective_coefficient(variable) * value
            for variable, value in zip(variables, values, strict=True)
        ),
    )


def _is_integer_variable(variable: Any) -> bool:
    try:
        return str(variable.VType) in {"B", "I", "N"}
    except Exception:
        return False


def _objective_coefficient(variable: Any) -> float:
    try:
        return float(variable.Obj)
    except Exception:
        return 0.0


def _integer_distance(value: float) -> float:
    return abs(value - round(value))


def _cb_get(model: Any, code: Any) -> float | None:
    if code is None:
        return None
    try:
        return float(model.cbGet(code))
    except Exception:
        return None


def _finite_or_none(
    value: float | None,
    grb: Any,
) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    infinity = getattr(grb, "INFINITY", None)
    if infinity is not None and abs(value) >= float(infinity) * 0.5:
        return None
    return value
