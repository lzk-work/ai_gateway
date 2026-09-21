"""Read-only replacement plan preview."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from replace_workflow_common import main
if __name__ == '__main__':
    sys.argv.append('--dry-run')
    main('inventory')
