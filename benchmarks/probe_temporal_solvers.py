"""Run with each planner's own Python; never imports or changes engine code."""

import argparse
import contextlib
import hashlib
import importlib.metadata
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

COMMITS = {
    "tempest": "a888dc25d2fb705be42a4790cf4f3ceea83fcb6c",
    "patty": "651a813d9c61b9b2926dcc9abdeeb05b4b2acb97",
    "patty_instradi": "6246e9a8a878f4299adbb111773267504ab8b05a",
}


def tempest_probe(source):
    from pysmt.environment import get_env
    from pysmt.shortcuts import Equals, Real, Solver
    from tempest.encoders.symbol_encoder import SymbolEncoder
    from unified_planning.shortcuts import DurativeAction, IntType

    encoder = SymbolEncoder({}, get_env())
    action = DurativeAction("waiting_probe", steps=IntType(0, 2))
    amount = encoder.parameter(action, action.parameter("steps"), 0)
    with Solver(name="z3") as solver:
        for constraint in encoder.type_constraints[0]:
            solver.add_assertion(constraint)
        solver.add_assertion(Equals(amount, Real((1, 2))))
        fractional = solver.solve()
        witness = str(solver.get_value(amount)) if fractional else None
    # This exercises the published symbolic encoding, not a hand-written real
    # relaxation. It does NOT claim all integer-update action models are wrong.
    return {
        "gate": "NOT_CERTIFIED",
        "test": "bounded_integer_wait_parameter",
        "declared_domain": "IntType(0,2)",
        "encoded_sort": str(amount.symbol_type()),
        "fractional_value_satisfies_published_type_constraints": fractional,
        "witness": witness,
        "timestamp_sort": str(encoder.t(0).symbol_type()),
        "scope": "Direct numeric parameter/event encoding fails exact tick contract. Alternative compilations are not certified.",
        "source_files": [
            "src/tempest/encoders/symbol_encoder.py",
            "src/tempest/engine.py",
        ],
        "matrix": {
            "integer_wait_parameters": "failed direct encoding",
            "integer_event_grid": "not imposed",
            "integer_passengers": "constant integer updates possible; variable integer parameters not certified",
            "simultaneous_handover": "not certified; epsilon/mutex semantics require translation proof",
            "internal_resource_offsets": "engine supports intermediate conditions/effects; ropeway translation untested",
            "fixed_k_tail": "untested",
            "reservoir_return": "untested",
            "objective": "no ropeway capacity bound certified",
        },
    }


def patty_probe(source):
    sys.path.insert(0, str(source))
    from src.pddl.Domain import Domain

    domain = """(define (domain ropeway_duration_probe)
      (:requirements :strips :durative-actions)
      (:predicates (ready) (finished))
      (:durative-action stop :parameters () :duration (= ?duration 2)
       :condition (at start (ready)) :effect (at end (finished))))"""
    errors = io.StringIO()
    parsed, exception = None, None
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "domain.pddl"
        path.write_text(domain)
        try:
            with contextlib.redirect_stderr(errors), contextlib.redirect_stdout(errors):
                parsed = Domain.fromFile(str(path))
        except Exception as exc:  # noqa: BLE001 - preserve diagnostics across optional native engine failures
            exception = f"{type(exc).__name__}: {exc}"
    actions = [] if parsed is None else [str(a) for a in parsed.actions]
    return {
        "gate": "NOT_CERTIFIED",
        "test": "native_durative_STOP",
        "pddl": domain,
        "parser_diagnostics": errors.getvalue(),
        "exception": exception,
        "parsed_actions": actions,
        "scope": "This frozen public repository is the numeric pattern planner; it is not a certified temporal ICE ropeway adapter.",
        "source_files": [
            "src/pddl/Domain.py",
            "grammar/pddl.g4",
            "main.py",
            "README.md",
        ],
        "matrix": {
            "durative_STOP": "rejected or not represented by published parser",
            "integer_event_grid": "not certified",
            "integer_passengers": "not certified",
            "simultaneous_handover": "untested",
            "internal_resource_offsets": "untested",
            "fixed_k_tail": "untested",
            "reservoir_return": "untested",
            "objective": "pattern bound is not an objective bound",
        },
    }


def patty_instradi_probe(source):
    """Exercise the temporal branch's complete native ICE encoding, unchanged.

    A fixed two-tick action is sufficient to test whether dispatch is on the
    integer grid. A separate release/require pair tests exact resource handover.
    This is a representability probe, not a ropeway performance adapter.
    """
    from fractions import Fraction

    sys.path.insert(0, str(source))
    from pysmt.shortcuts import Equals, Real, Solver
    from src.ices.ActionIntermediateCondition import ActionIntermediateCondition
    from src.ices.ActionIntermediateEffect import ActionIntermediateEffect
    from src.ices.Happening import (
        HappeningActionEnd,
        HappeningActionStart,
        HappeningConditionEnd,
        HappeningConditionStart,
        HappeningEffect,
    )
    from src.ices.ICEAction import END, START, ICEAction
    from src.ices.ICEEncoding import ICEEncoding
    from src.ices.ICEPattern import ICEPattern
    from src.ices.ICETask import ICETask
    from src.pddl.Atom import Atom
    from src.pddl.Literal import Literal
    from src.utils.Constants import EPSILON

    diagnostics = io.StringIO()

    def encode(actions, happenings, atom=None):
        task = ICETask()
        task.addActions(set(actions))
        happenings = list(happenings)
        # This frozen encoding calls .equal on empty Python sums. Supply ordinary
        # private preconditions/effects so the probe does not hit that unrelated
        # empty-action implementation defect. No engine source is changed.
        for action in actions:
            if not action.icond:
                ready = Atom.simple(action.name + "_ready")
                task.addPropVariable(ready)
                task.init.assignments.append(Literal.pos(ready))
                cond = ActionIntermediateCondition.fromProperties(START + 0, START + 0)
                cond.addCondition(Literal.pos(ready))
                action.icond.append(cond)
                at = (
                    next(
                        i
                        for i, h in enumerate(happenings)
                        if isinstance(h, HappeningActionStart) and h.action == action
                    )
                    + 1
                )
                happenings[at:at] = [
                    HappeningConditionStart(cond, action, 99),
                    HappeningConditionEnd(cond, action, 99),
                ]
            if not action.ieff:
                done = Atom.simple(action.name + "_done")
                task.addPropVariable(done)
                task.init.assignments.append(Literal.neg(done))
                effect = ActionIntermediateEffect.fromProperties(END + 0)
                effect.addEffect(Literal.pos(done))
                action.ieff.append(effect)
                at = next(
                    i
                    for i, h in enumerate(happenings)
                    if isinstance(h, HappeningActionEnd) and h.action == action
                )
                happenings.insert(at, HappeningEffect(effect, action, "done"))
        if atom is not None:
            task.addPropVariable(atom)
            task.init.assignments.append(Literal.neg(atom))
        pattern = ICEPattern.fromOrder([ICEPattern().getFake(), *happenings])
        with contextlib.redirect_stdout(diagnostics):
            encoding = ICEEncoding(task, pattern)
        solver = Solver(name="z3", solver_options={"timeout": 5000})
        for rule in encoding.rules:
            solver.add_assertion(rule.getExpression())
        for h in happenings:
            solver.add_assertion(
                Equals(
                    encoding.transVars.happeningVariables[h].getExpression(), Real(1)
                )
            )
        return encoding, solver

    action = ICEAction.fromProperties("STOP", 2)
    start, end = HappeningActionStart(action), HappeningActionEnd(action)
    encoding, solver = encode([action], [start, end])
    t_start = encoding.transVars.timeVariables[start].getExpression()
    t_end = encoding.transVars.timeVariables[end].getExpression()
    solver.add_assertion(Equals(t_start, Real((1, 2))))
    grid_result = solver.solve()
    grid_witness = (
        {
            "start": str(solver.get_value(t_start)),
            "end": str(solver.get_value(t_end)),
        }
        if grid_result
        else None
    )

    free = Atom.simple("resource_free")
    first, second = (ICEAction.fromProperties(name, 2) for name in ("first", "second"))
    release = ActionIntermediateEffect.fromProperties(END + 0)
    release.addEffect(Literal.pos(free))
    first.ieff.append(release)
    require = ActionIntermediateCondition.fromProperties(START + 0, START + 0)
    require.addCondition(Literal.pos(free))
    second.icond.append(require)
    a_start, a_end = HappeningActionStart(first), HappeningActionEnd(first)
    b_start, b_end = HappeningActionStart(second), HappeningActionEnd(second)
    h_release = HappeningEffect(release, first, "release")
    h_require = HappeningConditionStart(require, second, 0)
    h_require_end = HappeningConditionEnd(require, second, 0)
    events = [a_start, h_release, a_end, b_start, h_require, h_require_end, b_end]
    encoding, solver = encode([first, second], events, atom=free)
    times = encoding.transVars.timeVariables
    solver.add_assertion(Equals(times[a_start].getExpression(), Real(0)))
    solver.push()
    solver.add_assertion(Equals(times[b_start].getExpression(), Real(2)))
    handover_exact = "sat" if solver.solve() else "unsat"
    solver.pop()
    solver.add_assertion(
        Equals(times[b_start].getExpression(), Real(Fraction(2) + Fraction(EPSILON)))
    )
    handover_delayed = "sat" if solver.solve() else "unsat"
    return {
        "gate": "NOT_CERTIFIED",
        "test": "native_temporal_ICE_integer_grid_and_exact_handover",
        "branch": "instradi",
        "grid_result": "sat" if grid_result else "unsat",
        "grid_witness_ticks": grid_witness,
        "timestamp_sort": str(t_start.get_type()),
        "integer_happening_sort": str(
            [
                str(v.symbol_type())
                for v in encoding.transVars.happeningVariables[a_start]
                .getExpression()
                .get_free_variables()
            ]
        ),
        "handover_exact": handover_exact,
        "handover_plus_epsilon": handover_delayed,
        "epsilon_in_model_time_units": EPSILON,
        "diagnostics": diagnostics.getvalue(),
        "scope": "Complete native ICE rules accept fractional dispatch and the direct Boolean release/require encoding excludes exact handover. This does not prove that every alternative compilation is impossible.",
        "source_files": [
            "src/ices/ICEEncoding.py",
            "src/ices/ICETransitionVariables.py",
            "src/ices/ICEPatternPrecedenceGraph.py",
            "src/utils/Constants.py",
        ],
        "matrix": {
            "durative_STOP": "native ICE action represented",
            "integer_event_grid": "tested by forcing half a tick in complete encoding",
            "integer_passengers": "integer occurrence counts and constant integer updates possible; full passenger adapter untested",
            "simultaneous_handover": "exact and epsilon-delayed release/require tested",
            "variable_STOP_duration": "this branch equates duration to action constant; waiting compilation untested",
            "internal_resource_offsets": "native intermediate effects/conditions available",
            "fixed_k_tail": "untested",
            "reservoir_return": "untested",
            "objective": "no ropeway capacity bound certified",
        },
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--engine", choices=list(COMMITS), required=True)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    commit = subprocess.check_output(
        ["git", "-C", str(args.source), "rev-parse", "HEAD"], text=True
    ).strip()
    if commit != COMMITS[args.engine]:
        raise ValueError("planner source commit differs from audited version")
    subprocess.run(
        ["git", "-C", str(args.source), "diff", "--exit-code", "HEAD", "--"],
        check=True,
        capture_output=True,
    )
    tracked = subprocess.check_output(
        ["git", "-C", str(args.source), "ls-files", "-z"], text=True
    ).split("\0")
    probes = {
        "tempest": tempest_probe,
        "patty": patty_probe,
        "patty_instradi": patty_instradi_probe,
    }
    result = probes[args.engine](args.source)
    result.update(
        engine=args.engine,
        commit=commit,
        python=sys.version,
        packages={
            d.metadata["Name"]: d.version for d in importlib.metadata.distributions()
        },
        source_hashes={
            str(f.relative_to(args.source)): hashlib.sha256(f.read_bytes()).hexdigest()
            for name in tracked
            if name
            for f in [args.source / name]
            if f.is_file()
            and ".git" not in f.parts
            and f.suffix in (".py", ".g4", ".md")
        },
        dependency_binary_hashes={
            str(f.relative_to(args.source)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in args.source.rglob("*.so")
            if f.is_symlink()
        },
        probe_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {k: v for k, v in result.items() if k not in ("source_hashes", "packages")},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
