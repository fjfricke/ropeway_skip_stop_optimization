from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import random
from typing import Iterable

from ropeway_skip_stop_optimization.optimization.ean.merge_sequence_gate import (
    EanCpSatMergeGateSolver,
    EanEnumeratedMergeGateSolver,
    EanLatticeMergeGateSolver,
    EanMergeGateEvent,
    EanMergeGateFormulation,
    EanMergeGateInstance,
    EanMergeGateSolution,
    EanMergeGateSolveConfig,
    EanMergeStream,
    EanPairwiseMergeGateSolver,
    EanSlotMergeGateSolver,
)


@dataclass(frozen=True)
class EanMergeSequenceGateCase:
    stream_size: int
    release_pattern: str
    service_headway_seconds: float
    skip_headway_seconds: float
    seed: int

    def build(self) -> EanMergeGateInstance:
        if self.stream_size <= 0:
            raise ValueError("stream_size must be positive")
        rng = random.Random(self.seed)

        def release(stream: EanMergeStream, index: int) -> float:
            if self.release_pattern == "uniform":
                return float(4 * index + (2 if stream is EanMergeStream.SKIP else 0))
            if self.release_pattern == "clustered":
                return float(2 * (index // 3) + (1 if stream is EanMergeStream.SKIP else 0))
            if self.release_pattern == "adversarial":
                base = self.service_headway_seconds * index
                offset = 0.49 * min(
                    self.service_headway_seconds,
                    self.skip_headway_seconds,
                )
                return float(base + (offset if stream is EanMergeStream.SKIP else 0.0))
            if self.release_pattern == "random":
                return float(index * 2 + rng.randint(0, 5))
            raise ValueError(f"unknown release pattern: {self.release_pattern}")

        events = tuple(
            EanMergeGateEvent(
                id=f"service_{index:03d}",
                stream=EanMergeStream.SERVICE,
                stream_index=index,
                release_seconds=release(EanMergeStream.SERVICE, index),
                weight=float(1 + index % 5),
            )
            for index in range(self.stream_size)
        ) + tuple(
            EanMergeGateEvent(
                id=f"skip_{index:03d}",
                stream=EanMergeStream.SKIP,
                stream_index=index,
                release_seconds=release(EanMergeStream.SKIP, index),
                weight=float(1 + (self.stream_size - index) % 5),
            )
            for index in range(self.stream_size)
        )
        return EanMergeGateInstance(
            id=f"merge_{self.stream_size}_{self.release_pattern}_{self.seed}",
            events=events,
            service_leader_headway_seconds=self.service_headway_seconds,
            skip_leader_headway_seconds=self.skip_headway_seconds,
        )


def solve_ean_merge_sequence_gate(
    case: EanMergeSequenceGateCase,
    *,
    formulations: Iterable[EanMergeGateFormulation],
    config: EanMergeGateSolveConfig,
) -> tuple[EanMergeGateSolution, ...]:
    instance = case.build()
    solver_by_formulation = {
        EanMergeGateFormulation.ENUMERATION: EanEnumeratedMergeGateSolver(),
        EanMergeGateFormulation.PAIRWISE_FIFO: EanPairwiseMergeGateSolver(),
        EanMergeGateFormulation.LATTICE: EanLatticeMergeGateSolver(),
        EanMergeGateFormulation.SLOTS: EanSlotMergeGateSolver(),
        EanMergeGateFormulation.CP_SAT: EanCpSatMergeGateSolver(),
    }
    results = tuple(
        solver_by_formulation[formulation].solve(instance, config)
        for formulation in formulations
    )
    objectives = {
        round(result.objective, 5)
        for result in results
        if result.status == "optimal" and result.objective is not None
    }
    if len(objectives) > 1:
        raise RuntimeError(f"merge gate formulations disagree: {sorted(objectives)}")
    return results


def write_ean_merge_sequence_gate_results(
    path: Path,
    *,
    case: EanMergeSequenceGateCase,
    config: EanMergeGateSolveConfig,
    results: tuple[EanMergeGateSolution, ...],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "case": asdict(case),
        "solve_config": asdict(config),
        "results": [asdict(result) for result in results],
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
