from __future__ import annotations

from ropeway_skip_stop_optimization.examples.three_station import (
    ThreeStationExample,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanFixedStartHeadwayClassifier,
    EanHeadwayCandidateTimeBounds,
    EanHeadwayPairClassification,
    EanTimeReference,
    HeadwayPair,
)


def test_fixed_start_classifier_detects_both_fixed_directions_and_overlap() -> None:
    classifier = EanFixedStartHeadwayClassifier(
        candidate_bounds_by_id={
            "early": _point_bounds(10.0, 20.0),
            "late": _point_bounds(30.0, 40.0),
            "overlap": _point_bounds(18.0, 35.0),
        }
    )

    assert classifier.classify(_pair("early", "late", headway=5.0)) is (
        EanHeadwayPairClassification.FIXED_FORWARD
    )
    assert classifier.classify(_pair("late", "early", headway=5.0)) is (
        EanHeadwayPairClassification.FIXED_REVERSE
    )
    assert classifier.classify(_pair("early", "overlap", headway=5.0)) is (
        EanHeadwayPairClassification.DISJUNCTIVE
    )


def test_fixed_start_classifier_bounds_include_platform_wait_occupancy() -> None:
    example = ThreeStationExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    artifact = example.build_ean_artifact_builder(scenario, config).build(
        scenario,
        config,
    )

    classifier = EanFixedStartHeadwayClassifier.build(artifact)

    assert classifier is not None
    platform_exit = next(
        candidate
        for candidate in artifact.headway_candidates
        if candidate.time_reference is EanTimeReference.PLATFORM_EXIT_TIME
    )
    bounds = classifier.candidate_bounds_by_id[platform_exit.id]
    assert bounds.leader_clear_upper > bounds.follower_enter_upper
    assert bounds.leader_clear_lower == bounds.follower_enter_lower


def _point_bounds(lower: float, upper: float) -> EanHeadwayCandidateTimeBounds:
    return EanHeadwayCandidateTimeBounds(
        leader_clear_lower=lower,
        leader_clear_upper=upper,
        follower_enter_lower=lower,
        follower_enter_upper=upper,
    )


def _pair(first: str, second: str, *, headway: float) -> HeadwayPair:
    return HeadwayPair(
        id=f"pair::{first}::{second}",
        checkpoint_id="checkpoint",
        first_candidate_id=first,
        second_candidate_id=second,
        headway_seconds=headway,
    )
