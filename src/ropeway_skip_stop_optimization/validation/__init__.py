from __future__ import annotations

from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.validation.result import (
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)
from ropeway_skip_stop_optimization.validation.scenario_rules import validate_scenario_rules


def validate_scenario(scenario: Scenario) -> ValidationReport:
    issues: list[ValidationIssue] = []
    try:
        scenario.validate()
    except ValueError as exc:
        issues.append(
            ValidationIssue(
                code="scenario_integrity_error",
                severity=ValidationSeverity.ERROR,
                message=str(exc),
                entity_type="scenario",
                entity_id=scenario.id,
            )
        )
        return ValidationReport(tuple(issues))

    issues.extend(validate_scenario_rules(scenario))
    return ValidationReport(tuple(issues))


__all__ = [
    "ValidationIssue",
    "ValidationReport",
    "ValidationSeverity",
    "validate_scenario",
]
