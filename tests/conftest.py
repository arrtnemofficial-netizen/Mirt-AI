import sys
from pathlib import Path


root = Path(__file__).resolve().parents[1]
project_root = str(root)
if project_root not in sys.path:
    sys.path.insert(0, project_root)
