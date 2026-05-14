#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <release-tag>" >&2
  exit 2
fi

release_tag="$1"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
generated_dir="$repo_root/frontend/public/generated"
examples_dir="$generated_dir/examples"
archive_name="frontend-generated-examples.tar.gz"
tmp_dir="$(mktemp -d)"

cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

if [[ ! -d "$examples_dir" ]]; then
  echo "Missing generated examples directory: $examples_dir" >&2
  echo "Run the frontend export command before publishing release data." >&2
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "Missing GitHub CLI: gh" >&2
  exit 1
fi

archive_path="$tmp_dir/$archive_name"

echo "Creating $archive_name from $generated_dir"
tar -czf "$archive_path" -C "$repo_root/frontend/public" generated

echo "Archive:"
ls -lh "$archive_path"

echo "SHA-256:"
if command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "$archive_path"
elif command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$archive_path"
else
  echo "No SHA-256 tool found; skipping checksum." >&2
fi

echo "Checking GitHub release $release_tag"
gh release view "$release_tag" >/dev/null

echo "Uploading $archive_name to release $release_tag"
gh release upload "$release_tag" "$archive_path" --clobber

echo "Uploaded $archive_name"
