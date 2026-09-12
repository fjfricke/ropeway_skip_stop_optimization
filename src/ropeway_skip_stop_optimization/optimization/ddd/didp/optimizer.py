"""CABS execution with independently validated native results and OS supervision."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from time import perf_counter, sleep
import math
import multiprocessing as mp
import resource
import subprocess
import traceback

from .structure import prepare_didp_structure
from .model import build_didp_model
from .certificate import extract_didp_incumbent, replay_didp_checkpoint
from ..cp_sat_certificate import (
    atomic_json,
    read_ddd_cp_sat_checkpoint,
    write_ddd_cp_sat_checkpoint,
    stable_fingerprint,
)


@dataclass(frozen=True)
class DddDidpConfig:
    time_limit_seconds: float = 60
    threads: int = 1
    memory_limit_gib: float = 8
    output_dir: Path | None = None
    reference_checkpoint: Path | None = None
    build_only: bool = False

    def validate(self):
        if not math.isfinite(self.time_limit_seconds) or self.time_limit_seconds <= 0:
            raise ValueError("DIDP time limit must be positive and finite")
        if type(self.threads) is not int or self.threads < 1:
            raise ValueError("DIDP threads must be a positive integer")
        if (
            not math.isfinite(self.memory_limit_gib)
            or not 0 < self.memory_limit_gib <= 8
        ):
            raise ValueError("DIDP memory limit must be in (0, 8] GiB")


def _local_solve(problem, config, emit):
    import didppy as dp

    started = perf_counter()
    deadline = started + config.time_limit_seconds

    def elapsed():
        return perf_counter() - started

    def event(kind, **data):
        emit(dict(kind=kind, elapsed_seconds=elapsed(), **data))

    p = prepare_didp_structure(problem)
    preparation = elapsed()
    reference = None
    if config.reference_checkpoint:
        reference = read_ddd_cp_sat_checkpoint(
            config.reference_checkpoint, problem=problem, manifest=p.manifest
        )
        event(
            "reference",
            unserved=sum(reference.unserved_counts.values()),
            incumbent=reference.to_payload(),
        )
    before = perf_counter()
    b = build_didp_model(p)
    build = perf_counter() - before
    stats = dict(
        state_variables=len(b.variables),
        transitions=len(b.transitions),
        calendar_slots=sum(p.calendar_sizes),
        canonical_candidates=len(p.rides),
        duplicate_rate=None,
    )
    identity = dict(
        domain=p.fingerprint,
        backend="didppy",
        version=dp.__version__,
        encoding="fixed_k_event_v1",
        calendar_sizes=p.calendar_sizes,
        integer_time_storage="float64_exact_ticks",
        objective="unserved",
        source_hashes={
            x.name: sha256(x.read_bytes()).hexdigest()
            for x in sorted(Path(__file__).parent.glob("*.py"))
        },
    )
    fingerprint = stable_fingerprint(identity)
    event(
        "built",
        preparation_seconds=preparation,
        build_seconds=build,
        model_stats=stats,
        model_fingerprint=fingerprint,
    )
    replay_seconds = 0
    if reference is not None:
        before = perf_counter()
        sequence, _ = replay_didp_checkpoint(problem, b, reference)
        replay_seconds = perf_counter() - before
        event(
            "reference_replayed",
            transitions=len(sequence),
            replay_seconds=replay_seconds,
        )
    base = dict(
        schema="fixed_k_didp_v1",
        objective="unserved",
        bound_units="persons",
        domain_manifest=p.manifest,
        problem_fingerprint=p.fingerprint,
        model_fingerprint=fingerprint,
        model_identity=identity,
        model_stats=stats,
        total_demand=p.total_demand,
        preparation_seconds=preparation,
        build_seconds=build,
        replay_seconds=replay_seconds,
        threads=config.threads,
        native_warmstart=False,
    )
    if config.build_only or perf_counter() >= deadline:
        return dict(
            base,
            solver_status="BUILD_ONLY" if config.build_only else "TIME_LIMIT",
            proven_optimal=False,
            native_incumbent=None,
            native_unserved=None,
            unserved_lower_bound=None,
            total_seconds=elapsed(),
        )
    optimizer = dp.CABS(
        b.model,
        time_limit=max(1e-6, deadline - perf_counter()),
        threads=config.threads,
        initial_beam_size=1,
        max_beam_size=None,
        keep_all_layers=True,
        quiet=True,
    )
    incumbent = None
    best_served = None
    lower = None
    validation_seconds = 0
    solve_started = perf_counter()
    solution = None
    event("search_started")
    while perf_counter() < deadline:
        solution, terminated = optimizer.search_next()
        if solution.best_bound is not None:
            lower = max(0, p.total_demand - int(solution.best_bound))
            event(
                "bound",
                unserved_lower_bound=lower,
                generated=solution.generated,
                expanded=solution.expanded,
            )
        if solution.cost is not None and (
            best_served is None or solution.cost > best_served
        ):
            before = perf_counter()
            checked = extract_didp_incumbent(
                problem, b, solution.transitions, solution.cost
            )
            validation_seconds += perf_counter() - before
            first = incumbent is None
            incumbent = checked
            best_served = int(solution.cost)
            if config.output_dir:
                write_ddd_cp_sat_checkpoint(
                    config.output_dir / "incumbent.json",
                    problem=problem,
                    manifest=p.manifest,
                    incumbent=checked,
                )
            event(
                "native_first" if first else "native_incumbent",
                unserved=p.total_demand - best_served,
                incumbent=checked.to_payload(),
                generated=solution.generated,
                expanded=solution.expanded,
                validation_seconds=validation_seconds,
            )
        if terminated:
            break
    optimal = bool(solution and solution.is_optimal)
    status = (
        "OPTIMAL"
        if optimal
        else ("INFEASIBLE" if solution and solution.is_infeasible else "TIME_LIMIT")
    )
    return dict(
        base,
        solver_status=status,
        proven_optimal=optimal,
        native_incumbent=None if incumbent is None else incumbent.to_payload(),
        native_unserved=None if best_served is None else p.total_demand - best_served,
        unserved_lower_bound=lower,
        generated=None if solution is None else solution.generated,
        expanded=None if solution is None else solution.expanded,
        validation_seconds=validation_seconds,
        solve_seconds=perf_counter() - solve_started,
        total_seconds=elapsed(),
    )


def _child(connection, target, args):
    try:
        result = target(*args, lambda event: connection.send(("event", event)))
        # macOS reports bytes, Linux KiB.
        import sys

        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        result["peak_rss_bytes"] = rss if sys.platform == "darwin" else rss * 1024
        connection.send(("result", result))
    except BaseException:
        connection.send(
            (
                "result",
                dict(
                    solver_status="ERROR",
                    proven_optimal=False,
                    error=traceback.format_exc(),
                ),
            )
        )
    finally:
        connection.close()


def supervise(target, args, *, seconds, memory_gib, event_callback=None):
    """A separate process is killable even during native model construction/search."""
    started = perf_counter()
    context = mp.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    child = context.Process(target=_child, args=(sender, target, args))
    child.start()
    sender.close()
    peak = 0
    events = []
    result = None
    reason = None
    eof = False
    while child.is_alive() or (not eof and receiver.poll()):
        while not eof and receiver.poll():
            try:
                kind, item = receiver.recv()
            except EOFError:
                eof = True
                break
            if kind == "event":
                events.append(item)
                if event_callback:
                    event_callback(item)
            else:
                result = item
        if result is not None and not child.is_alive():
            break
        if perf_counter() - started >= seconds:
            reason = "TIME_LIMIT"
            break
        try:
            value = subprocess.run(
                ["ps", "-o", "rss=", "-p", str(child.pid)],
                capture_output=True,
                text=True,
                timeout=1,
            )
            rss = int(value.stdout.strip() or 0) * 1024
            peak = max(peak, rss)
            if rss > memory_gib * 1024**3:
                reason = "MEMORY_LIMIT"
                break
        except (ValueError, subprocess.TimeoutExpired):
            pass
        sleep(0.1)
    if child.is_alive():
        child.terminate()
        child.join(timeout=0.5)
        if child.is_alive():
            child.kill()
    child.join(timeout=1)
    receiver.close()
    if result is None or reason:
        result = dict(
            solver_status=reason or "WORKER_EXIT",
            proven_optimal=False,
            native_incumbent=None,
            native_unserved=None,
            unserved_lower_bound=None,
            exit_code=child.exitcode,
        )
    # Preserve streamed, independently checked incumbents across forced exits.
    for event in events:
        if event["kind"] == "built":
            for key in (
                "model_stats",
                "model_fingerprint",
                "preparation_seconds",
                "build_seconds",
            ):
                result.setdefault(key, event.get(key))
        if event["kind"] in ("native_first", "native_incumbent"):
            if (
                result.get("native_unserved") is None
                or event["unserved"] < result["native_unserved"]
            ):
                result["native_unserved"] = event["unserved"]
                result["native_incumbent"] = event["incumbent"]
        if event["kind"] == "bound" and event.get("unserved_lower_bound") is not None:
            result["unserved_lower_bound"] = max(
                result.get("unserved_lower_bound") or 0, event["unserved_lower_bound"]
            )
    for event in events:
        for key in ("generated", "expanded", "validation_seconds"):
            if key in event:
                result[key] = event[key]
    search_start = next(
        (e["elapsed_seconds"] for e in events if e["kind"] == "search_started"), None
    )
    if search_start is not None:
        result.setdefault(
            "solve_seconds", max(0, perf_counter() - started - search_start)
        )
    result.update(
        events=events,
        peak_rss_bytes=max(peak, result.get("peak_rss_bytes", 0)),
        total_seconds=perf_counter() - started,
    )
    return result


@dataclass(frozen=True)
class DddDidpOptimizer:
    config: DddDidpConfig = DddDidpConfig()

    def solve(self, problem, *, event_callback=None):
        self.config.validate()
        if self.config.output_dir:
            self.config.output_dir.mkdir(parents=True, exist_ok=True)
        result = supervise(
            _local_solve,
            (problem, self.config),
            seconds=self.config.time_limit_seconds,
            memory_gib=self.config.memory_limit_gib,
            event_callback=event_callback,
        )
        reference = next(
            (e for e in result["events"] if e["kind"] == "reference"), None
        )
        result["reference_unserved"] = (
            None if reference is None else reference["unserved"]
        )
        result["best_validated_incumbent"] = result.get("native_incumbent")
        result["best_validated_unserved"] = result.get("native_unserved")
        if reference is not None and (
            result["best_validated_unserved"] is None
            or reference["unserved"] < result["best_validated_unserved"]
        ):
            result["best_validated_incumbent"] = reference["incumbent"]
            result["best_validated_unserved"] = reference["unserved"]
        result.update(
            native_warmstart=False,
            objective="unserved",
            bound_units="persons",
            total_demand=sum(g.count for g in problem.passenger_build.demand_groups),
        )
        if reference is not None and (
            result["solver_status"] == "INFEASIBLE"
            or (
                result.get("unserved_lower_bound") is not None
                and result["unserved_lower_bound"] > reference["unserved"]
            )
        ):
            result.update(
                solver_status="ERROR",
                proven_optimal=False,
                error="Native proof contradicts independently validated reference",
            )
        if self.config.output_dir:
            atomic_json(self.config.output_dir / "result.json", result)
        return result
