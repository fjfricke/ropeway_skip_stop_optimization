"""Independent experimental encodings; physical domain identity is unchanged."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ReservoirPhaseFormulationConfig:
    passenger_encoding: str = "legacy"
    passenger_integrality: str = "all"
    passenger_network: str = "legacy"
    resource_encoding: str = "legacy"
    conflict_cuts: str = "none"
    conflict_work_limit: int = 100_000
    conflict_cut_limit: int = 5_000

    def validate(self, method="phase_arc_flow"):
        choices = {
            "passenger_encoding": ("legacy", "od_flow", "od_queue"),
            "passenger_integrality": ("all", "boarding"),
            "passenger_network": ("legacy", "contracted"),
            "resource_encoding": ("legacy", "maximal"),
            "conflict_cuts": ("none", "local_cliques"),
        }
        for field, allowed in choices.items():
            if getattr(self, field) not in allowed:
                raise ValueError(f"unsupported {field}: {getattr(self, field)}")
        if self.conflict_work_limit < 0 or self.conflict_cut_limit < 0:
            raise ValueError("conflict limits must be nonnegative")
        if method != "phase_arc_flow" and self != type(self)():
            raise ValueError("experimental formulation options require phase_arc_flow")

    def as_dict(self):
        return asdict(self)
