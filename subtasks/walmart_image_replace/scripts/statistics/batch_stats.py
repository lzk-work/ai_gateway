"""Read-only replacement progress."""
import argparse
import sys
from pathlib import Path
from collections import Counter
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from replace_workflow_common import batch_paths, load_jsonl
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch-name')
    args = parser.parse_args()
    paths = batch_paths(args.batch_name)
    print(paths['root'])
    for key in ('plan','model_results','main_checkpoint','sub_checkpoint','main_oss_checkpoint','sub_oss_checkpoint','payload'):
        rows = load_jsonl(paths[key])
        print(key, len(rows), dict(Counter(r.get('status', 'planned') for r in rows)))
