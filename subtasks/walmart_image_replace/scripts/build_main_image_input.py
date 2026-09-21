"""Build replacement image inputs without submitting generation jobs."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from replace_workflow_common import prepare, batch_paths, build_image_input

def run(batch_name=None, dry_run=False):
    records = prepare(batch_name, dry_run)
    if not dry_run:
        return build_image_input(records, batch_paths(batch_name), 'main')
    return []

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch-name')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    run(args.batch_name, args.dry_run)
