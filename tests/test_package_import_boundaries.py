from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.parametrize("package", ["ddd", "ean"])
def test_public_optimization_facade_is_lazy(package: str) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                f"import ropeway_skip_stop_optimization.optimization.{package}; "
                "heavy = {'gurobipy', 'ortools', 'numpy', 'scipy'}; "
                "assert not heavy.intersection(sys.modules), "
                "sorted(heavy.intersection(sys.modules))"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_solver_free_public_models_do_not_load_solver_stacks() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "from ropeway_skip_stop_optimization.optimization.ddd import "
                "DddLayeredTimeNetwork, DddMovementProblem; "
                "from ropeway_skip_stop_optimization.optimization.ean import EanConfig; "
                "assert DddLayeredTimeNetwork and DddMovementProblem and EanConfig; "
                "heavy = {'gurobipy', 'ortools', 'numpy', 'scipy'}; "
                "assert not heavy.intersection(sys.modules), "
                "sorted(heavy.intersection(sys.modules))"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
