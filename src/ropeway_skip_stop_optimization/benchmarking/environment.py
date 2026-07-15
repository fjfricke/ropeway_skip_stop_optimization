from __future__ import annotations

import subprocess


def current_git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
        ).strip()
    except Exception:
        return None


def git_is_dirty() -> bool:
    try:
        return bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"],
                text=True,
            ).strip()
        )
    except Exception:
        return False


def gurobi_version() -> str | None:
    try:
        import gurobipy as gp

        return ".".join(str(part) for part in gp.gurobi.version())
    except Exception:
        return None
