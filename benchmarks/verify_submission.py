"""Check raw submission files and selection without importing a solver."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ropeway_skip_stop_optimization.submission import verify_manifest

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', nargs='?', type=Path, default=Path('results/submission_manifest.json'))
    args = parser.parse_args()
    try:
        manifest = verify_manifest(args.manifest)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f'Submission check failed: {exc}\n')
    print(f"Verified {len(manifest['files'])} files, 64 Journey and 30 service comparisons.")
