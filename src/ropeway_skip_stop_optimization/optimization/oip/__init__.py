"""Optimized-initial-placement (OIP) comparison domain."""

from .domain import (
    OipBackend,
    OipDomain,
    OipOperation,
    OipPassengerEncoding,
    OipTimeGrid,
    prepare_oip_domain,
    shift_scenario_for_oip_warmup,
)
from .cp_sat import (
    BuiltOipCpSatModel,
    OipCpSatConfig,
    OipCpSatResult,
    build_oip_cp_sat_model,
    solve_oip_cp_sat,
)
from .runner import OipRunConfig, run_oip
from .validation import OipCertificateMetrics, validate_oip_certificate

__all__ = [
    "OipBackend",
    "OipDomain",
    "OipOperation",
    "OipPassengerEncoding",
    "OipTimeGrid",
    "prepare_oip_domain",
    "shift_scenario_for_oip_warmup",
    "BuiltOipCpSatModel",
    "OipCpSatConfig",
    "OipCpSatResult",
    "build_oip_cp_sat_model",
    "solve_oip_cp_sat",
    "OipRunConfig",
    "run_oip",
    "OipCertificateMetrics",
    "validate_oip_certificate",
]
