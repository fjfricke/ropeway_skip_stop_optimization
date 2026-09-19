from __future__ import annotations

import json
import math
from dataclasses import fields, is_dataclass
from datetime import time
from enum import Enum
from pathlib import Path
from typing import Any


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, time):
        return value.isoformat(timespec="minutes")
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if is_dataclass(value):
        return {field.name: to_jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, set | frozenset):
        return [to_jsonable(item) for item in sorted(value, key=repr)]
    if isinstance(value, tuple | list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    return value


def write_json(output_path: Path, payload: Any) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(to_jsonable(payload), allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def decode_headway_design(payload: dict):
    """Read v2 headways or explicitly migrate the unversioned legacy layout.

    No scenario reader previously existed: use this entry point when importing
    a saved ``headway_design`` instead of constructing dataclasses from JSON.
    """
    import warnings
    from ..models.headway import (
        ConventionalQuickSwitchDesign, DefaultBypassStopOnFaultDesign,
        FailSafeDiversionDesign, GeometricSharedBoundaryDesign, HeadwayDesign,
        HeadwayEvidenceKind, HeadwayParameterProvenance, HeadwayPhysicalParameters,
        MandatoryServiceStationDesign, StationMechanismAssignment,
    )

    def provenance(items):
        return tuple(HeadwayParameterProvenance(
            **{**item, "evidence_kind": HeadwayEvidenceKind(item["evidence_kind"])}
        ) for item in items)

    version = payload.get("schema_version", 1)
    if version not in (1, 2):
        raise ValueError(f"Unsupported headway schema version: {version}")
    unexpected = set(payload) - {"schema_version", "physical", "station_mechanisms", "provenance"}
    if unexpected:
        raise ValueError(f"Unknown headway fields: {sorted(unexpected)}")
    physical = dict(payload["physical"])
    fault_names = {"merge_clearance_m", "emergency_merge_sway_angle_rad",
                   "control_delay_seconds", "emergency_deceleration_m_per_s2"}
    legacy = {}
    legacy_provenance = ()
    if version == 1:
        legacy = {name: physical.pop(name) for name in fault_names if name in physical}
        legacy_provenance = tuple(p for p in physical.get("provenance", ())
                                  if p["parameter_name"] in fault_names)
        physical["provenance"] = tuple(p for p in physical.get("provenance", ())
                                        if p["parameter_name"] not in fault_names)
    physical["provenance"] = provenance(physical.get("provenance", ()))
    assignments = []
    used_legacy = False
    for assignment in payload["station_mechanisms"]:
        data = dict(assignment["design"])
        if not data:
            mechanism = GeometricSharedBoundaryDesign()
        elif "manufacturer_vehicle_interval_seconds" in data:
            mechanism = ConventionalQuickSwitchDesign(**data)
        elif "safety_path_segment_ids" in data:
            data["safety_path_segment_ids"] = tuple(data["safety_path_segment_ids"])
            mechanism = FailSafeDiversionDesign(**data)
        elif "guaranteed_vehicle_interval_seconds" in data:
            mechanism = MandatoryServiceStationDesign(**data)
        elif "mechanical_service_cycle_seconds" in data:
            if version == 1:
                for name, value in legacy.items():
                    if name in data and data[name] != value:
                        raise ValueError(f"Conflicting legacy headway parameter: {name}")
                    data[name] = value
                data["provenance"] = (*data.get("provenance", ()), *legacy_provenance)
                used_legacy = True
            data["provenance"] = provenance(data.get("provenance", ()))
            mechanism = DefaultBypassStopOnFaultDesign(**data)
        else:
            raise ValueError(f"Unknown headway mechanism: {sorted(data)}")
        assignments.append(StationMechanismAssignment(assignment["exit_switch_id"], mechanism))
    if legacy and not used_legacy:
        warnings.warn(
            "Unused legacy fault inputs removed while migrating headway schema: "
            + json.dumps(legacy, sort_keys=True), UserWarning, stacklevel=2,
        )
    design = HeadwayDesign(HeadwayPhysicalParameters(**physical), tuple(assignments),
                           provenance(payload.get("provenance", ())))
    design.validate()
    return design
