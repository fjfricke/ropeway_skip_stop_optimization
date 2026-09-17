from pathlib import Path

import pytest

from ropeway_skip_stop_optimization.benchmarking.thesis_full_cp_sat_overload import (
    ThesisOverloadPilotConfig,
    prepare_pilot,
)


ROOT = Path(__file__).resolve().parents[1]


def test_historical_overload_reference_is_rejected_by_current_contract(tmp_path):
    config = ThesisOverloadPilotConfig(
        reference_dir=ROOT / "results/thesis_phase_cell_capacity_references_20260916/reference_t5r_f2_r15",
        output_dir=tmp_path / "run",
    )
    with pytest.raises(ValueError, match="differ physically"):
        prepare_pilot(config)
