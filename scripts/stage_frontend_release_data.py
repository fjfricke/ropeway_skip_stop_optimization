#!/usr/bin/env python3
"""Stage generated frontend data for Vercel deployment.

Vercel static deployments reject individual files above 100 MB. This script
copies frontend/public/generated into a staging directory and replaces large
JSON files with small descriptors plus raw byte chunks next to the descriptor.
The frontend loader reassembles those chunks transparently at runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


DEFAULT_THRESHOLD_BYTES = 50 * 1024 * 1024
DEFAULT_CHUNK_BYTES = 50 * 1024 * 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Source generated directory")
    parser.add_argument("--output", required=True, type=Path, help="Output staging directory")
    parser.add_argument(
        "--threshold-bytes",
        default=DEFAULT_THRESHOLD_BYTES,
        type=int,
        help="Chunk JSON files larger than this many bytes",
    )
    parser.add_argument(
        "--chunk-bytes",
        default=DEFAULT_CHUNK_BYTES,
        type=int,
        help="Maximum raw chunk size in bytes",
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stage_generated(source: Path, output: Path, threshold_bytes: int, chunk_bytes: int) -> list[Path]:
    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(source, output)

    chunked_files: list[Path] = []
    for json_path in sorted(output.rglob("*.json")):
        if json_path.stat().st_size > threshold_bytes:
            chunk_file(json_path, chunk_bytes)
            chunked_files.append(json_path.relative_to(output))
    return chunked_files


def chunk_file(json_path: Path, chunk_bytes: int) -> None:
    original_size = json_path.stat().st_size
    original_sha256 = sha256_file(json_path)
    chunk_dir = json_path.with_name(f"{json_path.name}.chunks")

    if chunk_dir.exists():
        shutil.rmtree(chunk_dir)
    chunk_dir.mkdir()

    chunks: list[dict[str, object]] = []
    with json_path.open("rb") as source:
        index = 0
        while True:
            data = source.read(chunk_bytes)
            if not data:
                break
            chunk_path = chunk_dir / f"{index:04d}.part"
            chunk_path.write_bytes(data)
            chunks.append(
                {
                    "path": chunk_path.relative_to(json_path.parent).as_posix(),
                    "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
            index += 1

    descriptor = {
        "__chunked_json__": True,
        "version": 1,
        "encoding": "utf-8",
        "size_bytes": original_size,
        "sha256": original_sha256,
        "chunk_size_bytes": chunk_bytes,
        "chunks": chunks,
    }
    json_path.write_text(json.dumps(descriptor, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    source = args.source.resolve()
    output = args.output.resolve()

    if not source.is_dir():
        raise SystemExit(f"Source generated directory does not exist: {source}")
    if args.chunk_bytes <= 0:
        raise SystemExit("--chunk-bytes must be positive")
    if args.threshold_bytes <= 0:
        raise SystemExit("--threshold-bytes must be positive")
    if args.chunk_bytes >= 100 * 1024 * 1024:
        raise SystemExit("--chunk-bytes must be below Vercel's 100 MB file limit")

    chunked_files = stage_generated(source, output, args.threshold_bytes, args.chunk_bytes)

    print(f"Staged generated data: {source} -> {output}")
    if chunked_files:
        print("Chunked large JSON files:")
        for path in chunked_files:
            print(f"  {path}")
    else:
        print("No JSON files exceeded the chunking threshold.")


if __name__ == "__main__":
    main()
