"""Shared physical/time contract for the new short-horizon thesis comparisons.

Start policies and solver time grids are deliberately owned by their adapters.
Historical results do not acquire this identity retrospectively.
"""

from dataclasses import asdict, dataclass
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import math
from pathlib import Path


THESIS_CONTRACT_ID = "t5r_g500_geometric_2cycles_900completion_300tail_v3"
HEADWAY_CONTRACT = "geometric_shared_entry_exit_v1"
RELATIVE_JOURNEY_K = tuple(range(10, 31, 5))
CONSTANT_JOURNEY_K = tuple(range(20, 31, 5))
CONSTANT_REFERENCE_K = 30
JOURNEY_REFERENCE_K = tuple(sorted(set((*RELATIVE_JOURNEY_K, CONSTANT_REFERENCE_K))))


def solver_versions() -> dict[str, str | None]:
    values = {}
    for package in ("ortools", "gurobipy"):
        try:
            values[package] = version(package)
        except PackageNotFoundError:
            values[package] = None
    return values


@dataclass(frozen=True)
class ThesisWindows:
    cycle_seconds: float
    completion_seconds: float = 900.0
    continuation_seconds: float = 300.0

    def __post_init__(self):
        if not math.isfinite(self.cycle_seconds) or self.cycle_seconds <= 0:
            raise ValueError("All-Stop cycle must be finite and positive")
        if any(not math.isfinite(value) or value < 0 for value in (
            self.completion_seconds, self.continuation_seconds,
        )):
            raise ValueError("completion and continuation must be finite and nonnegative")

    @property
    def demand_window_seconds(self) -> float:
        return 2 * self.cycle_seconds

    @property
    def service_horizon_seconds(self) -> float:
        return self.demand_window_seconds + self.completion_seconds

    @property
    def operation_seconds(self) -> float:
        return self.service_horizon_seconds + self.continuation_seconds

    def manifest(self) -> dict:
        return {
            **asdict(self),
            "headway_contract": HEADWAY_CONTRACT,
            "demand_window_seconds": self.demand_window_seconds,
            "service_horizon_seconds": self.service_horizon_seconds,
            "operation_seconds": self.operation_seconds,
        }


def source_digest(root: Path) -> str:
    """Content identity of executable Python and dependency specifications.

    Ignore generated outputs, Git dirty flags, docs and frontend-only edits.
    A source checkout need not have Git installed to compute this identity.
    """
    paths = sorted((root / "src").rglob("*.py"))
    paths += sorted((root / "benchmarks").glob("*.py"))
    paths += [root / name for name in ("pyproject.toml", "uv.lock")]
    digest = hashlib.sha256()
    for path in paths:
        if path.is_file():
            data = path.read_bytes()
            digest.update(json.dumps([path.relative_to(root).as_posix(), len(data)]).encode())
            digest.update(data)
    return digest.hexdigest()
