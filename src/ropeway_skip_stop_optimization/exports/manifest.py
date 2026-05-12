from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ropeway_skip_stop_optimization.examples.base import ScenarioExample
from ropeway_skip_stop_optimization.exports.artifacts import ArtifactSet, ExportArtifact
from ropeway_skip_stop_optimization.exports.json_codec import write_json


MANIFEST_SCHEMA_VERSION = 1


def manifest_path(output_root: Path) -> Path:
    return output_root / "manifest.json"


def build_artifact_set_entry(artifact_set: ArtifactSet, artifacts: tuple[ExportArtifact, ...]) -> dict[str, Any]:
    return {
        "id": artifact_set.id,
        "label": artifact_set.label,
        "artifacts": {artifact.kind.value: artifact.relative_path.as_posix() for artifact in artifacts},
        "artifact_metadata": [
            {
                "id": artifact.id,
                "kind": artifact.kind.value,
                "label": artifact.label,
                "path": artifact.relative_path.as_posix(),
            }
            for artifact in artifacts
        ],
    }


def build_example_entry(
    example: ScenarioExample,
    artifact_set: ArtifactSet,
    artifacts: tuple[ExportArtifact, ...],
    *,
    existing_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = example.metadata
    artifact_set_entry = build_artifact_set_entry(artifact_set, artifacts)
    existing_sets = list(existing_entry.get("artifact_sets", [])) if existing_entry is not None else []
    artifact_sets = [entry for entry in existing_sets if entry.get("id") != artifact_set.id]
    artifact_sets.append(artifact_set_entry)
    artifact_sets.sort(key=lambda entry: str(entry.get("id", "")))

    default_artifact_set = artifact_set.id if artifact_set.is_default else None
    if default_artifact_set is None and existing_entry is not None:
        default_artifact_set = existing_entry.get("default_artifact_set")
    if default_artifact_set is None:
        default_artifact_set = artifact_set.id

    return {
        "id": metadata.id,
        "label": metadata.label,
        "description": metadata.description,
        "tags": list(metadata.tags),
        "default_artifact_set": default_artifact_set,
        "artifact_sets": artifact_sets,
    }


def load_manifest(output_root: Path) -> dict[str, Any]:
    path = manifest_path(output_root)
    if not path.exists():
        return {"schema_version": MANIFEST_SCHEMA_VERSION, "generated_at": None, "examples": []}
    return json.loads(path.read_text(encoding="utf-8"))


def merge_and_write_manifest(
    output_root: Path,
    example: ScenarioExample,
    artifact_set: ArtifactSet,
    artifacts: tuple[ExportArtifact, ...],
) -> Path:
    manifest = load_manifest(output_root)
    existing_examples = list(manifest.get("examples", []))
    existing_entry = next((entry for entry in existing_examples if entry.get("id") == example.metadata.id), None)
    example_entry = build_example_entry(example, artifact_set, artifacts, existing_entry=existing_entry)
    examples = [entry for entry in existing_examples if entry.get("id") != example.metadata.id]
    examples.append(example_entry)
    examples.sort(key=lambda entry: str(entry.get("id", "")))

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "examples": examples,
    }
    path = manifest_path(output_root)
    write_json(path, manifest)
    return path
