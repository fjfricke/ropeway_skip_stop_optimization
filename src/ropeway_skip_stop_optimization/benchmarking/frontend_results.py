"""Transactional publication helpers for the local read-only frontend."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

DEFAULT_SUMMARY_FIELDS = (
    "campaign_id", "campaign_kind", "label", "status", "objective", "method",
    "operating_mode", "formulation", "sequence", "trial_count",
    "completed_trial_count", "updated_at_utc", "contract_id", "study_membership",
)

_PROCESS_INDEX_LOCK = threading.Lock()


@contextmanager
def _index_lock(path: Path):
    """Serialize publishers in-process and, where available, across processes."""
    with _PROCESS_INDEX_LOCK, path.open("a+") as stream:
        try:
            import fcntl  # POSIX only
        except ImportError:  # pragma: no cover - exercised on Windows
            yield
        else:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)


def atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    temporary.replace(path)


def update_campaign_index(
    root: Path,
    snapshot: dict[str, Any],
    *,
    summary_fields: Iterable[str] = DEFAULT_SUMMARY_FIELDS,
) -> None:
    """Replace one campaign summary while serializing concurrent publishers."""
    root.mkdir(parents=True, exist_ok=True)
    index_path = root / "index.json"
    lock_path = root / ".index.lock"
    with _index_lock(lock_path):
        payload = json.loads(index_path.read_text()) if index_path.exists() else {
            "schema_version": 1, "campaigns": [],
        }
        summary = {field: snapshot.get(field) for field in summary_fields}
        campaigns = [
            item for item in payload.get("campaigns", [])
            if item.get("campaign_id") != snapshot["campaign_id"]
        ]
        campaigns.append(summary)
        campaigns.sort(key=lambda item: str(item.get("campaign_id")))
        payload["campaigns"] = campaigns
        atomic_json(index_path, payload)
