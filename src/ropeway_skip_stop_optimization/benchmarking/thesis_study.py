"""Pure fixed-K study policy; no solver or filesystem side effects."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
import hashlib
import json


def manifest_identity(manifest: dict) -> str:
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def k_ladder(first: int, maximum: int, factor: str = "1.5") -> list[int]:
    if not 0 < first <= maximum or Decimal(factor) <= 1:
        raise ValueError("invalid fleet ladder")
    result = [first]
    while result[-1] < maximum:
        result.append(min(maximum, int((Decimal(result[-1]) * Decimal(factor)).to_integral_value(rounding=ROUND_CEILING))))
    return result


def confirmed_service(result: dict) -> tuple[int, int] | None:
    native = result.get("run", {})
    best = native.get("best") or {}
    if best.get("movement", {}).get("feasible") is True:
        passenger = best.get("passengers") or {}
        if passenger.get("plan") is not None and passenger.get("served") is not None and passenger.get("unserved") is not None:
            return int(passenger["served"]), int(passenger["unserved"])
    return None


def journey_confirmed(result: dict) -> bool:
    native = result.get("run", {})
    return native.get("independent_validation_status") == "feasible" and native.get("validated_upper_bound") is not None


@dataclass
class DemandLadder:
    """Failed heuristic searches delimit tested loads, never physical capacity."""
    current: int
    max_levels: int = 5
    factor: str = "1.1"
    max_intermediate: int = 3
    last_full: int | None = None
    unresolved: int | None = None
    levels: int = 0
    intermediate: int = 0

    def advance(self, full_service: bool) -> int | None:
        self.levels += 1
        if full_service:
            self.last_full = self.current
        else:
            self.unresolved = self.current
        if self.unresolved is not None:
            if self.last_full is None or self.intermediate >= self.max_intermediate or self.unresolved - self.last_full <= 1:
                return None
            self.intermediate += 1
            self.current = (self.last_full + self.unresolved) // 2
        elif self.levels >= self.max_levels:
            return None
        else:
            self.current = int((Decimal(self.current) * Decimal(self.factor)).to_integral_value(rounding=ROUND_CEILING))
        return self.current


def validate_study(manifest: dict, *, require_ready: bool = True) -> None:
    if manifest.get("schema") != "thesis_study_v1":
        raise ValueError("unsupported study manifest")
    if not manifest.get("groups"):
        raise ValueError("study has no groups")
    if not 1 <= manifest.get("workers", 12) <= 12 or not 0 < manifest.get("memory_gib", 32) <= 32:
        raise ValueError("study exceeds the agreed local worker/memory limit")
    ids = set()
    for group in manifest["groups"]:
        if group["id"] in ids:
            raise ValueError("duplicate group")
        ids.add(group["id"])
        if require_ready and group.get("blockers"):
            raise ValueError(f"{group['id']} is blocked: {', '.join(group['blockers'])}")
        if group["objective"] not in ("unserved", "journey_time"):
            raise ValueError("unsupported objective")
        if group.get("catalog", "od_endpoints_v1") not in ("small", "relevant", "od_endpoints_v1"):
            raise ValueError("unsupported pattern catalog")
        if group.get("pattern_search", "independent") not in ("independent", "line_groups"):
            raise ValueError("unsupported pattern search")
        if group.get("pattern_search") == "line_groups" and group["objective"] != "unserved":
            raise ValueError("line_groups requires the capacity evolution method")
        values = group["k_values"]
        if not values or values != sorted(set(values)) or values[0] <= 0:
            raise ValueError("K ladder must be positive, unique and increasing")
        if not group.get("seeds") or len(set(group["seeds"])) != len(group["seeds"]):
            raise ValueError("seeds must be nonempty and unique")
        if group["demand"] <= 0 or group["stage_seconds"] <= 0:
            raise ValueError("positive demand and stage budget required")
        if group.get("max_demand_levels", 5) < 1:
            raise ValueError("at least one demand level is required")
        if group.get("topology") not in ("t5r", "t6r") or group.get("family") not in ("f0", "f2", "f3", "f4"):
            raise ValueError("unsupported thesis topology or demand family")
        if group["resolution_seconds"] not in (5, 15, 30):
            raise ValueError("unsupported release resolution")
