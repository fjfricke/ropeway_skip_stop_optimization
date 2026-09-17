from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class GurobiSolverPolicyPreset(StrEnum):
    DEFAULT = "default"
    DEBUG_SHORT = "debug_short"
    QUICK_GOOD_SOLUTION = "quick_good_solution"
    PAPER_BENCHMARK = "paper_benchmark"
    EXACT_OPTIMALITY = "exact_optimality"


@dataclass(frozen=True)
class GurobiSolverPolicy:
    mip_gap: float | None = None
    time_limit_seconds: float | None = None
    method: int | None = None
    threads: int | None = None
    mip_focus: int | None = None
    numeric_focus: int | None = None
    feasibility_tolerance: float | None = None
    soft_memory_limit_gib: float | None = None
    seed: int | None = None

    def validate(self) -> None:
        if self.mip_gap is not None and not (0 <= self.mip_gap <= 1):
            raise ValueError("mip_gap must be between 0 and 1 when set")
        if self.time_limit_seconds is not None and self.time_limit_seconds <= 0:
            raise ValueError("time_limit_seconds must be positive when set")
        if self.threads is not None and self.threads <= 0:
            raise ValueError("threads must be positive when set")
        if self.mip_focus is not None and self.mip_focus not in {0, 1, 2, 3}:
            raise ValueError("mip_focus must be 0, 1, 2, or 3 when set")
        if self.numeric_focus is not None and self.numeric_focus not in {0, 1, 2, 3}:
            raise ValueError("numeric_focus must be 0, 1, 2, or 3 when set")
        if self.feasibility_tolerance is not None and not (
            1e-9 <= self.feasibility_tolerance <= 1e-2
        ):
            raise ValueError(
                "feasibility_tolerance must lie between 1e-9 and 1e-2"
            )
        if self.soft_memory_limit_gib is not None and self.soft_memory_limit_gib <= 0:
            raise ValueError("soft_memory_limit_gib must be positive when set")
        if self.seed is not None and self.seed < 0:
            raise ValueError("seed must be nonnegative when set")


def gurobi_solver_policy_for_preset(preset: GurobiSolverPolicyPreset | str) -> GurobiSolverPolicy:
    preset = GurobiSolverPolicyPreset(preset)
    if preset is GurobiSolverPolicyPreset.DEFAULT:
        return GurobiSolverPolicy()
    if preset is GurobiSolverPolicyPreset.DEBUG_SHORT:
        return GurobiSolverPolicy(
            mip_gap=0.20,
            time_limit_seconds=60.0,
            method=3,
        )
    if preset is GurobiSolverPolicyPreset.QUICK_GOOD_SOLUTION:
        return GurobiSolverPolicy(
            mip_gap=0.10,
            method=3,
            mip_focus=1,
        )
    if preset is GurobiSolverPolicyPreset.PAPER_BENCHMARK:
        return GurobiSolverPolicy(
            mip_gap=0.01,
            method=3,
            mip_focus=2,
        )
    if preset is GurobiSolverPolicyPreset.EXACT_OPTIMALITY:
        return GurobiSolverPolicy(
            mip_gap=0.0,
            method=3,
            mip_focus=2,
        )
    raise ValueError(f"unsupported Gurobi solver policy preset: {preset.value}")


def apply_gurobi_solver_policy(model: Any, policy: GurobiSolverPolicy) -> None:
    policy.validate()
    if policy.mip_gap is not None:
        model.Params.MIPGap = policy.mip_gap
    if policy.time_limit_seconds is not None:
        model.Params.TimeLimit = policy.time_limit_seconds
    if policy.method is not None:
        model.Params.Method = policy.method
    if policy.threads is not None:
        model.Params.Threads = policy.threads
    if policy.mip_focus is not None:
        model.Params.MIPFocus = policy.mip_focus
    if policy.numeric_focus is not None:
        model.Params.NumericFocus = policy.numeric_focus
    if policy.feasibility_tolerance is not None:
        model.Params.FeasibilityTol = policy.feasibility_tolerance
    if policy.soft_memory_limit_gib is not None:
        model.Params.SoftMemLimit = policy.soft_memory_limit_gib
    if policy.seed is not None:
        model.Params.Seed = policy.seed
