from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ropeway_skip_stop_optimization.examples.base import ScenarioExample, ScenarioExampleMetadata
from ropeway_skip_stop_optimization.exports.artifacts import ArtifactSet, ArtifactSetBackend, ExportArtifact
from ropeway_skip_stop_optimization.exports.json_codec import write_json


MANIFEST_SCHEMA_VERSION = 2

_LEGACY_EXAMPLE_GROUPS = {
    "three_station_v0": (
        "three_station_ring",
        "Three station ring",
        "half_cabins_skip_wait",
        "Half cabins skip+wait",
    ),
    "three_station_no_skip_no_wait_v0": (
        "three_station_ring",
        "Three station ring",
        "full_cabins_no_skip_no_wait",
        "Full cabins no_skip+no_wait",
    ),
    "three_station_full_no_skip_no_wait_v0": (
        "three_station_ring",
        "Three station ring",
        "full_cabins_no_skip_no_wait",
        "Full cabins no_skip+no_wait",
    ),
    "three_station_half_no_skip_no_wait_v0": (
        "three_station_ring",
        "Three station ring",
        "half_cabins_no_skip_no_wait",
        "Half cabins no_skip+no_wait",
    ),
    "five_station_v0": (
        "five_station_ring",
        "Five station ring",
        "half_cabins_skip_wait",
        "Half cabins skip+wait",
    ),
    "five_station_no_wait_v0": (
        "five_station_ring",
        "Five station ring",
        "full_cabins_skip_no_wait",
        "Full cabins skip+no_wait",
    ),
    "five_station_half_no_skip_no_wait_v0": (
        "five_station_ring",
        "Five station ring",
        "half_cabins_no_skip_no_wait",
        "Half cabins no_skip+no_wait",
    ),
}


def manifest_path(output_root: Path) -> Path:
    return output_root / "manifest.json"


def build_artifact_set_entry(artifact_set: ArtifactSet, artifacts: tuple[ExportArtifact, ...]) -> dict[str, Any]:
    return {
        "id": artifact_set.id,
        "label": artifact_set.label,
        "backend": artifact_set.backend.value,
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


def build_variant_entry(
    example: ScenarioExample,
    artifact_set: ArtifactSet,
    artifacts: tuple[ExportArtifact, ...],
    *,
    existing_entry: dict[str, Any] | None = None,
    clean: bool = False,
) -> dict[str, Any]:
    metadata = example.metadata
    artifact_set_entry = build_artifact_set_entry(artifact_set, artifacts)
    existing_sets = [] if clean or existing_entry is None else list(existing_entry.get("artifact_sets", []))
    artifact_sets = [entry for entry in existing_sets if entry.get("id") != artifact_set.id]
    artifact_sets.append(artifact_set_entry)
    artifact_sets = [_with_backend(entry) for entry in artifact_sets]
    artifact_sets.sort(key=lambda entry: str(entry.get("id", "")))

    default_artifact_set = artifact_set.id if artifact_set.is_default else None
    if default_artifact_set is None and existing_entry is not None and not clean:
        default_artifact_set = existing_entry.get("default_artifact_set")
    if default_artifact_set not in {entry.get("id") for entry in artifact_sets}:
        default_artifact_set = artifact_set.id

    return {
        "id": _variant_id(metadata),
        "label": _variant_label(metadata),
        "example_id": metadata.id,
        "example_label": metadata.label,
        "description": metadata.description,
        "tags": list(metadata.tags),
        "default_artifact_set": default_artifact_set,
        "artifact_sets": artifact_sets,
    }


def load_manifest(output_root: Path) -> dict[str, Any]:
    path = manifest_path(output_root)
    if not path.exists():
        return {"schema_version": MANIFEST_SCHEMA_VERSION, "generated_at": None, "families": []}
    return _normalize_manifest(json.loads(path.read_text(encoding="utf-8")))


def merge_and_write_manifest(
    output_root: Path,
    example: ScenarioExample,
    artifact_set: ArtifactSet,
    artifacts: tuple[ExportArtifact, ...],
    *,
    clean: bool = False,
) -> Path:
    metadata = example.metadata
    manifest = load_manifest(output_root)
    family_id = _family_id(metadata)
    variant_id = _variant_id(metadata)
    families = _remove_stale_variant_locations(
        list(manifest.get("families", [])),
        example_id=metadata.id,
        family_id=family_id,
        variant_id=variant_id,
    )
    existing_family = next((family for family in families if family.get("id") == family_id), None)
    existing_variants = list(existing_family.get("variants", [])) if existing_family is not None else []
    existing_variant = next(
        (variant for variant in existing_variants if variant.get("id") == variant_id),
        None,
    )
    variant_entry = build_variant_entry(
        example,
        artifact_set,
        artifacts,
        existing_entry=existing_variant,
        clean=clean,
    )
    variants = [variant for variant in existing_variants if variant.get("id") != variant_entry["id"]]
    variants.append(variant_entry)
    variants.sort(key=lambda entry: str(entry.get("id", "")))

    family_entry = {
        "id": family_id,
        "label": _family_label(metadata),
        "variants": variants,
    }
    families = [family for family in families if family.get("id") != family_id]
    families.append(family_entry)
    families.sort(key=lambda entry: str(entry.get("id", "")))

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "families": families,
    }
    path = manifest_path(output_root)
    write_json(path, manifest)
    return path


def _normalize_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schema_version") == MANIFEST_SCHEMA_VERSION and "families" in manifest:
        return {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "generated_at": manifest.get("generated_at"),
            "families": [_normalize_family(family) for family in manifest.get("families", [])],
        }
    families: list[dict[str, Any]] = []
    for example_entry in manifest.get("examples", []):
        family_id, family_label, variant_id, variant_label = _legacy_group_for_example(example_entry)
        variant_entry = {
            "id": variant_id,
            "label": variant_label,
            "example_id": example_entry.get("id"),
            "example_label": example_entry.get("label"),
            "description": example_entry.get("description", ""),
            "tags": list(example_entry.get("tags", [])),
            "default_artifact_set": example_entry.get("default_artifact_set"),
            "artifact_sets": [_with_backend(entry) for entry in example_entry.get("artifact_sets", [])],
        }
        _append_legacy_variant(families, family_id, family_label, variant_entry)
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at": manifest.get("generated_at"),
        "families": sorted(families, key=lambda entry: str(entry.get("id", ""))),
    }


def _normalize_family(family: dict[str, Any]) -> dict[str, Any]:
    variants = []
    for variant in family.get("variants", []):
        next_variant = dict(variant)
        next_variant["artifact_sets"] = [_with_backend(entry) for entry in variant.get("artifact_sets", [])]
        variants.append(next_variant)
    variants.sort(key=lambda entry: str(entry.get("id", "")))
    return {
        "id": family.get("id"),
        "label": family.get("label"),
        "variants": variants,
    }


def _append_legacy_variant(
    families: list[dict[str, Any]],
    family_id: str,
    family_label: str,
    variant_entry: dict[str, Any],
) -> None:
    family = next((entry for entry in families if entry.get("id") == family_id), None)
    if family is None:
        families.append({"id": family_id, "label": family_label, "variants": [variant_entry]})
        return
    variants = [variant for variant in family.get("variants", []) if variant.get("id") != variant_entry["id"]]
    variants.append(variant_entry)
    variants.sort(key=lambda entry: str(entry.get("id", "")))
    family["variants"] = variants


def _remove_stale_variant_locations(
    families: list[dict[str, Any]],
    *,
    example_id: str,
    family_id: str,
    variant_id: str,
) -> list[dict[str, Any]]:
    next_families = []
    for family in families:
        variants = [
            variant
            for variant in family.get("variants", [])
            if variant.get("example_id") != example_id
            or (family.get("id") == family_id and variant.get("id") == variant_id)
        ]
        if variants:
            next_family = dict(family)
            next_family["variants"] = variants
            next_families.append(next_family)
    return next_families


def _with_backend(artifact_set_entry: dict[str, Any]) -> dict[str, Any]:
    entry = dict(artifact_set_entry)
    entry["backend"] = entry.get("backend") or _infer_backend(entry)
    return entry


def _infer_backend(artifact_set_entry: dict[str, Any]) -> str:
    artifacts = set(artifact_set_entry.get("artifacts", {}))
    if artifacts & {"ean_input", "ean_result", "ean_replay"}:
        return ArtifactSetBackend.EAN.value
    if artifacts & {"discrete_scenario", "movement_plan", "passenger_replay", "replay_metrics", "milp_result"}:
        return ArtifactSetBackend.DISCRETE.value
    return ArtifactSetBackend.PHYSICAL.value


def _legacy_group_for_example(example_entry: dict[str, Any]) -> tuple[str, str, str, str]:
    example_id = str(example_entry.get("id", ""))
    if example_id in _LEGACY_EXAMPLE_GROUPS:
        return _LEGACY_EXAMPLE_GROUPS[example_id]
    label = str(example_entry.get("label") or example_id)
    return example_id, label, example_id, label


def _family_id(metadata: ScenarioExampleMetadata) -> str:
    return metadata.family_id or metadata.id


def _family_label(metadata: ScenarioExampleMetadata) -> str:
    return metadata.family_label or metadata.label


def _variant_id(metadata: ScenarioExampleMetadata) -> str:
    return metadata.variant_id or metadata.id


def _variant_label(metadata: ScenarioExampleMetadata) -> str:
    return metadata.variant_label or metadata.label
