from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Iterable, Mapping

from ropeway_skip_stop_optimization.benchmarking.optimization_events import (
    OptimizationEventKind,
    OptimizationProgressEvent,
)


@dataclass(frozen=True, slots=True)
class OptimizationLivePaths:
    canonical_campaign_dir: Path
    frontend_root: Path | None = None

    @property
    def events_path(self) -> Path:
        return self.canonical_campaign_dir / "events.jsonl"

    @property
    def campaign_path(self) -> Path:
        return self.canonical_campaign_dir / "campaign.json"


class OptimizationLiveStore:
    """Append-only event log plus atomic campaign/frontend snapshots."""

    def __init__(self, paths: OptimizationLivePaths) -> None:
        self.paths = paths
        self.paths.canonical_campaign_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._sequence = self._last_sequence()

    @property
    def next_sequence(self) -> int:
        return self._sequence + 1

    def append(self, event: OptimizationProgressEvent) -> None:
        with self._lock:
            if event.sequence != self.next_sequence:
                raise ValueError(
                    f"expected event sequence {self.next_sequence}, got {event.sequence}"
                )
            with self.paths.events_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._sequence = event.sequence

    def append_new(
        self,
        kind: OptimizationEventKind,
        campaign_id: str,
        **values: Any,
    ) -> OptimizationProgressEvent:
        with self._lock:
            event = OptimizationProgressEvent(
                sequence=self.next_sequence,
                kind=kind,
                campaign_id=campaign_id,
                **values,
            )
            self.append(event)
            return event

    def publish(self, campaign: Mapping[str, Any]) -> None:
        with self._lock:
            snapshot = dict(campaign)
            snapshot["sequence"] = self._sequence
            _atomic_write_json(self.paths.campaign_path, snapshot)
            if self.paths.frontend_root is None:
                return
            campaign_id = str(snapshot["campaign_id"])
            campaign_dir = self.paths.frontend_root / campaign_id
            _atomic_write_json(campaign_dir / "snapshot.json", snapshot)
            self._publish_frontend_index(snapshot)

    def read_events(self) -> tuple[OptimizationProgressEvent, ...]:
        with self._lock:
            if not self.paths.events_path.exists():
                return ()
            return tuple(
                OptimizationProgressEvent.from_dict(json.loads(line))
                for line in self.paths.events_path.read_text(
                    encoding="utf-8"
                ).splitlines()
                if line.strip()
            )

    def _last_sequence(self) -> int:
        events = self.read_events()
        return 0 if not events else events[-1].sequence

    def _publish_frontend_index(self, snapshot: Mapping[str, Any]) -> None:
        assert self.paths.frontend_root is not None
        index_path = self.paths.frontend_root / "index.json"
        existing: dict[str, Any] = {"schema_version": 1, "campaigns": []}
        if index_path.exists():
            existing = json.loads(index_path.read_text(encoding="utf-8"))
        summary = {
            key: snapshot.get(key)
            for key in (
                "campaign_id",
                "label",
                "status",
                "objective",
                "method",
                "formulation",
                "campaign_kind",
                "operating_mode",
                "updated_at_utc",
                "sequence",
                "completed_trial_count",
                "trial_count",
                "largest_certified_feasible_k",
                "frontier_k",
                "frontier_status",
                "frontier_termination",
            )
        }
        campaigns = [
            item
            for item in existing.get("campaigns", [])
            if item.get("campaign_id") != snapshot.get("campaign_id")
        ]
        campaigns.append(summary)
        campaigns.sort(key=lambda item: str(item.get("campaign_id")))
        _atomic_write_json(
            index_path,
            {"schema_version": 1, "campaigns": campaigns},
        )


def reduce_optimization_events(
    events: Iterable[OptimizationProgressEvent],
) -> dict[str, Any]:
    ordered = sorted(events, key=lambda item: item.sequence)
    if not ordered:
        raise ValueError("cannot reduce an empty event stream")
    expected = list(range(ordered[0].sequence, ordered[-1].sequence + 1))
    if [item.sequence for item in ordered] != expected:
        raise ValueError("event stream contains a gap or duplicate sequence")
    campaign: dict[str, Any] = {
        "schema_version": 1,
        "campaign_id": ordered[0].campaign_id,
        "status": "queued",
        "trials": {},
        "events": [],
    }
    for event in ordered:
        if event.campaign_id != campaign["campaign_id"]:
            raise ValueError("event stream mixes campaigns")
        campaign["updated_at_utc"] = event.timestamp_utc
        campaign["sequence"] = event.sequence
        campaign["events"].append(event.to_dict())
        if event.kind is OptimizationEventKind.CAMPAIGN_STARTED:
            campaign["status"] = "running"
            campaign.update(event.payload)
        elif event.kind is OptimizationEventKind.CAMPAIGN_COMPLETED:
            campaign["status"] = str(event.payload.get("status", "complete"))
            campaign.update(
                {
                    key: value
                    for key, value in event.payload.items()
                    if key
                    not in {"trials", "events", "trial_count", "completed_trial_count"}
                }
            )
        if event.policy_id is None or event.available_fleet_count is None:
            continue
        trial_id = f"{event.policy_id}__k{event.available_fleet_count}"
        trial = campaign["trials"].setdefault(
            trial_id,
            {
                "trial_id": trial_id,
                "policy_id": event.policy_id,
                "available_fleet_count": event.available_fleet_count,
                "status": "queued",
                "events": [],
            },
        )
        trial["events"].append(event.to_dict())
        trial["updated_at_utc"] = event.timestamp_utc
        trial["sequence"] = event.sequence
        if event.trial_fingerprint is not None:
            trial["trial_fingerprint"] = event.trial_fingerprint
        if event.stage is not None:
            trial["stage"] = event.stage
        if event.elapsed_seconds is not None:
            trial["elapsed_seconds"] = event.elapsed_seconds
        for source, target in (
            (event.global_certified_lower_bound, "certified_lower_bound"),
            (event.global_validated_upper_bound, "validated_upper_bound"),
            (event.global_relative_gap, "relative_gap"),
        ):
            if source is not None:
                trial[target] = source
        if event.kind is OptimizationEventKind.TRIAL_STARTED:
            trial.update(event.payload)
            trial["status"] = "running"
        elif event.kind is OptimizationEventKind.TRIAL_COMPLETED:
            trial.update(event.payload)
            trial["solver_status"] = event.payload.get("status")
            trial["status"] = "complete"
        elif event.kind is OptimizationEventKind.TRIAL_FAILED:
            trial.update(event.payload)
            trial["status"] = "failed"
        elif event.kind is OptimizationEventKind.CG_ROUND_COMPLETED:
            trial["round_index"] = event.round_index
            trial.update(event.payload)
    campaign["trial_count"] = max(
        int(campaign.get("trial_count", 0)), len(campaign["trials"])
    )
    campaign["completed_trial_count"] = sum(
        trial["status"] == "complete" for trial in campaign["trials"].values()
    )
    return campaign


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise
