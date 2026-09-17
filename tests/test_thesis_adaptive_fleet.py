import pytest

from ropeway_skip_stop_optimization.benchmarking.thesis_adaptive_fleet import (
    AdaptiveFleetPolicy,
)


def test_t5_adaptive_fleet_formula_starts_at_16_and_grows_gradually():
    policy = AdaptiveFleetPolicy(84, 933)
    assert policy.step == 4
    assert policy.initial_cap(11) == 16
    assert policy.next_cap(16, 11) == 20
    assert policy.next_cap(20, 20) == 28
    assert policy.next_cap(28, 28) == 36


def test_adaptive_fleet_formula_respects_hard_cap_and_domains():
    policy = AdaptiveFleetPolicy(84, 90)
    assert policy.next_cap(84, 84) == 90
    with pytest.raises(ValueError, match="used fleet"):
        policy.next_cap(16, 17)

