"""Build-only ablation of headways, fixed types and interval sharing; no solves."""

import argparse
import gc
import json
from pathlib import Path
from time import perf_counter

from ropeway_skip_stop_optimization.benchmarking.oip_pattern_waiting import (
    prepare_oip_pattern_waiting_pilot,
)
from ropeway_skip_stop_optimization.optimization.oip.cp_sat import (
    build_oip_cp_sat_model,
)
from ropeway_skip_stop_optimization.optimization.oip.runner import _cp_model_stats
from ropeway_skip_stop_optimization.benchmarking.frontend_results import atomic_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument(
        "--families", nargs="+", default=["f2", "f3", "f0"], choices=["f2", "f3", "f0"]
    )
    args = p.parse_args()
    rows = []
    for family in args.families:
        demand = {"f2": 2266, "f3": 5430, "f0": 7606}[family]
        types = (
            ("all_stop", "bd", "ce")
            if family == "f2"
            else ("all_stop", "alternating_phase_0", "alternating_phase_1")
        )
        counts = dict(zip(types, (30, 16, 16)))
        for name, legacy, specialize, reduce in [
            ("historical_choice", True, False, False),
            ("geometric_choice", False, False, False),
            ("geometric_fixed_full", False, True, False),
            ("geometric_fixed_reduced", False, True, True),
        ]:
            started = perf_counter()
            domain = prepare_oip_pattern_waiting_pilot(
                maximum_wait_seconds=0,
                cabin_count=62,
                demand_total=demand,
                demand_family=family,
                legacy_headways=legacy,
            ).domain
            built = build_oip_cp_sat_model(
                domain,
                type_catalog="all_stop_bd_ce"
                if family == "f2"
                else "all_stop_alternating",
                formulation="nowait_templates",
                objective="served",
                fixed_type_counts=counts,
                specialize_fixed_types=specialize,
                reduce_headways=reduce,
            )
            assert not built.model.validate(), built.model.validate()
            row = {
                "family": family,
                "variant": name,
                "fixed_type_counts": counts,
                "domain_fingerprint": domain.fingerprint,
                "build_seconds": built.build_seconds,
                "preparation_and_build_seconds": perf_counter() - started,
                **_cp_model_stats(built.model_stats),
                **built.reduction_stats,
                "presolve": None,
                "search": None,
            }
            rows.append(row)
            atomic_json(
                args.output,
                {
                    "scope": "K62, 30/16/16, build only; no presolve or search",
                    "rows": rows,
                },
            )
            print(json.dumps(row), flush=True)
            del built, domain
            gc.collect()


if __name__ == "__main__":
    main()
