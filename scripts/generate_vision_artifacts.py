#!/usr/bin/env python3
"""
Thin wrapper to run vision artifact generator from project root.

Usage:
    python scripts/generate_vision_artifacts.py

This simply delegates to data/vision/generate.py
"""

import subprocess
import sys
from pathlib import Path


def main():
    """Run the canonical generator script."""
    project_root = Path(__file__).parent.parent
    generator = project_root / "data" / "vision" / "generate.py"

    if not generator.exists():
        print(f"❌ Generator not found: {generator}")
        sys.exit(1)

    print(f"🔧 Running: {generator.relative_to(project_root)}")
    result = subprocess.run([sys.executable, str(generator)], check=False, cwd=project_root)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
