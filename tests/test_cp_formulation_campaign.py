import runpy
from pathlib import Path

campaign = runpy.run_path(
    str(
        Path(__file__).resolve().parents[1]
        / "benchmarks/run_cp_formulation_campaign.py"
    )
)


def rows(ub, lb=0, case="R"):
    return [
        dict(spec=dict(seed=seed), ub=ub, comparable_lb=lb, problem_fingerprint=case)
        for seed in (1, 2)
    ]


def test_screening_matches_authorized_matrix():
    specs = campaign["specs"]()
    assert len(specs) == 16
    assert sum(s["case"] == "C" for s in specs) == 5
    assert sum(s["backend"] == "ibm" for s in specs) == 3


def test_confirmation_requires_both_seeds_and_meaningful_gain():
    verdict = campaign["confirmation_verdict"]
    assert verdict(rows(999), rows(1000), "R")["status"] == "confirmed"
    assert verdict(rows(999.5), rows(1000), "R")["status"] == "inconclusive"
    assert (
        verdict(rows(990, case="C"), rows(1000, case="C"), "C")["status"] == "confirmed"
    )
    assert (
        verdict(rows(991, case="C"), rows(1000, case="C"), "C")["status"]
        == "inconclusive"
    )
    assert verdict(rows(999)[:1], rows(1000), "R")["status"] == "pending"
    mixed = rows(999)
    mixed[1]["ub"] = 1001
    assert verdict(mixed, rows(1000), "R")["status"] == "inconclusive"
    assert verdict(rows(0), rows(0), "R")["status"] == "inconclusive"


def test_stronger_comparable_bound_requires_ub_not_worse():
    verdict = campaign["confirmation_verdict"]
    assert verdict(rows(1000, 120), rows(1000, 100), "R")["status"] == "confirmed"
    assert verdict(rows(1001, 200), rows(1000, 100), "R")["status"] == "inconclusive"
