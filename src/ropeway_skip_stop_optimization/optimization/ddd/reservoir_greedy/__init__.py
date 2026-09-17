"""Experimental greedy reservoir insertion; legacy defaults are unchanged."""

from .model import build_insertion, pilot_problem, prepare_insertion, validate_lifecycle
from .optimizer import GreedyConfig, construct_greedy, solve_insertion

__all__ = [
    "GreedyConfig",
    "build_insertion",
    "construct_greedy",
    "pilot_problem",
    "prepare_insertion",
    "solve_insertion",
    "validate_lifecycle",
]
