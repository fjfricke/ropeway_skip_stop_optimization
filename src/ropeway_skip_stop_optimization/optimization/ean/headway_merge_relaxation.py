from __future__ import annotations

from dataclasses import dataclass

from ropeway_skip_stop_optimization.optimization.ean.artifact import (
    EanBuildArtifact,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanFleetMode,
    EanHeadwayPairScope,
    HeadwayCheckpointKind,
)
from ropeway_skip_stop_optimization.optimization.ean.network import (
    EanPassengerBehavior,
)


@dataclass(frozen=True)
class EanDirectMergeHeadwayRelaxationIndex:
    """Direct merge-exit pairs omitted by the diagnostic relaxation.

    Exit candidates currently use one ACTIVE candidate for both the service
    and skip route. Consequently, the smallest representable static relaxation
    is checkpoint-wide: every pair at a service/skip reconvergence exit is
    omitted. This is intentionally a superset of realized cross-stream
    conflicts and must never be treated as a certified model.
    """

    checkpoint_ids: frozenset[str]
    pair_ids: frozenset[str]

    @classmethod
    def build(
        cls,
        artifact: EanBuildArtifact,
    ) -> EanDirectMergeHeadwayRelaxationIndex:
        _require_supported_artifact(artifact)
        network = artifact.movement_network
        assert network is not None
        pattern = network.pattern(artifact.circulation_pattern_ids[0])
        option_by_id = {option.id: option for option in network.route_options}
        merge_state_ids: set[str] = set()
        for state_id, option_ids in zip(
            pattern.state_ids,
            pattern.route_option_ids_by_position,
            strict=True,
        ):
            behaviors = {
                option_by_id[option_id].passenger_behavior
                for option_id in option_ids
            }
            if {
                EanPassengerBehavior.SERVICE,
                EanPassengerBehavior.SKIP,
            } <= behaviors:
                merge_state_ids.add(state_id)

        checkpoint_ids = frozenset(
            checkpoint.id
            for checkpoint in artifact.headway_checkpoints
            if checkpoint.kind is HeadwayCheckpointKind.EXIT_SWITCH
            and checkpoint.switch_id in merge_state_ids
        )
        return cls(
            checkpoint_ids=checkpoint_ids,
            pair_ids=frozenset(
                pair.id
                for pair in artifact.headway_pairs
                if pair.checkpoint_id in checkpoint_ids
            ),
        )


def _require_supported_artifact(artifact: EanBuildArtifact) -> None:
    if artifact.fleet_mode is not EanFleetMode.FIXED_STARTS:
        raise NotImplementedError(
            "diagnostic_relax_merge_headways currently supports fixed starts only"
        )
    if artifact.headway_pair_scope is not EanHeadwayPairScope.COMPLETE:
        raise NotImplementedError(
            "diagnostic_relax_merge_headways requires complete eager headway pairs"
        )
    if artifact.movement_network is None or len(artifact.circulation_pattern_ids) != 1:
        raise NotImplementedError(
            "diagnostic_relax_merge_headways requires one canonical movement pattern"
        )
