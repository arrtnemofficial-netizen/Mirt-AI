from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_ai_smell_comments.py"
SPEC = importlib.util.spec_from_file_location("check_ai_smell_comments", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_parse_added_lines_from_multi_commit_diff() -> None:
    diff_text = """diff --git a/src/a.py b/src/a.py
index 111..222 100644
--- a/src/a.py
+++ b/src/a.py
@@ -1,0 +2,2 @@
+value = 1
+# chatgpt marker
@@ -10,1 +12,0 @@
-old = True
diff --git a/tests/test_a.py b/tests/test_a.py
index 333..444 100644
--- a/tests/test_a.py
+++ b/tests/test_a.py
@@ -0,0 +1,2 @@
+def test_ok():
+    assert True
"""

    assert MODULE._parse_added_lines_from_unified_diff(diff_text) == [
        ("src/a.py", 2, "value = 1"),
        ("src/a.py", 3, "# chatgpt marker"),
        ("tests/test_a.py", 1, "def test_ok():"),
        ("tests/test_a.py", 2, "    assert True"),
    ]


def test_parse_added_lines_ignores_non_scoped_files() -> None:
    diff_text = """diff --git a/docs/readme.md b/docs/readme.md
index 123..456 100644
--- a/docs/readme.md
+++ b/docs/readme.md
@@ -1,0 +1,1 @@
+chatgpt
"""

    assert MODULE._parse_added_lines_from_unified_diff(diff_text) == []
