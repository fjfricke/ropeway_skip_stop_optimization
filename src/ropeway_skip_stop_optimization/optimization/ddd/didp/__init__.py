"""Optional DIDPPy backend. Importing this package does not import DIDPPy."""

from .structure import PreparedDidpStructure, prepare_didp_structure

__all__ = ["PreparedDidpStructure", "prepare_didp_structure"]

from .optimizer import DddDidpConfig, DddDidpOptimizer

__all__ += ["DddDidpConfig", "DddDidpOptimizer"]
