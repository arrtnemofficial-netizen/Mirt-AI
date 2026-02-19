"""Fail CI when newly added source lines introduce banned AI-style comment markers."""

from __future__ import annotations

import re
import subprocess
import sys


BANNED_MARKERS = (
    "SENIOR-LEVEL",
    "ЗАЛІЗОБЕТОННО",
    "AI wrote this",
)

SOURCE_FILE_RE = re.compile(r"^\+\+\+ b/(src/.+\.py)$")


def _git_added_lines() -> list[tuple[str, int, str]]:
    """Return (file, line_no, line_text) for added lines in HEAD commit."""
    result = subprocess.run(
        ["git", "show", "--unified=0", "--pretty=format:", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []

    findings: list[tuple[str, int, str]] = []
    current_file: str | None = None
    current_new_line = 0
    for raw in result.stdout.splitlines():
        file_match = SOURCE_FILE_RE.match(raw)
        if file_match:
            current_file = file_match.group(1)
            current_new_line = 0
            continue

        if raw.startswith("@@"):
            # Parse hunk header, e.g. @@ -10,0 +11,3 @@
            plus_part = raw.split("+", 1)[1].split(" ", 1)[0]
            current_new_line = int(plus_part.split(",")[0])
            continue

        if current_file is None:
            continue
        if raw.startswith("+++ ") or raw.startswith("--- "):
            continue
        if raw.startswith("+"):
            findings.append((current_file, current_new_line, raw[1:]))
            current_new_line += 1
        elif raw.startswith("-"):
            continue
        else:
            current_new_line += 1
    return findings

def main() -> int:
    added_lines = _git_added_lines()
    if not added_lines:
        return 0

    failed = False
    for path, line_no, text in added_lines:
        if "#" not in text:
            continue
        for marker in BANNED_MARKERS:
            if marker in text:
                failed = True
                snippet = text.strip()
                print(f"{path}:{line_no}: banned marker '{marker}' in comment -> {snippet}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
