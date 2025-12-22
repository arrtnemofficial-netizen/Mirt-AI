#!/usr/bin/env python3
"""
Dependency Checker Script

Перевіряє залежності на конфлікти та актуальність версій.
Використовує PyPI API та pip check для виявлення проблем.

Usage:
    python scripts/check_dependencies.py
"""

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS_FILE = PROJECT_ROOT / "requirements.txt"
PYPROJECT_FILE = PROJECT_ROOT / "pyproject.toml"


def parse_requirements(file_path: Path) -> dict[str, str]:
    """Parse requirements.txt and return package:version dict."""
    requirements = {}
    if not file_path.exists():
        return requirements

    with open(file_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Parse package==version or package>=version
            match = re.match(r"^([a-zA-Z0-9_-]+(?:\[.*\])?)([=<>!]+)(.+)$", line)
            if match:
                package = match.group(1).split("[")[0]  # Remove extras
                constraint = match.group(2) + match.group(3)
                if "==" in constraint:
                    version = constraint.split("==")[1]
                    requirements[package] = version
            else:
                # Just package name
                package = line.split("[")[0].split(">=")[0].split("==")[0]
                requirements[package] = "latest"

    return requirements


def parse_pyproject(file_path: Path) -> dict[str, str]:
    """Parse pyproject.toml and return package:version dict."""
    requirements = {}
    if not file_path.exists():
        return requirements

    with open(file_path, encoding="utf-8") as f:
        content = f.read()

    # Extract dependencies section
    deps_match = re.search(r'dependencies\s*=\s*\[(.*?)\]', content, re.DOTALL)
    if deps_match:
        deps_section = deps_match.group(1)
        # Find all package==version
        for match in re.finditer(r'"([^"]+)"', deps_section):
            pkg_spec = match.group(1)
            if "==" in pkg_spec:
                parts = pkg_spec.split("==")
                package = parts[0].split("[")[0]
                version = parts[1]
                requirements[package] = version

    return requirements


def get_latest_version(package: str) -> str | None:
    """Get latest version from PyPI."""
    try:
        url = f"https://pypi.org/pypi/{package}/json"
        with urlopen(url, timeout=5) as response:
            data = json.loads(response.read())
            return data["info"]["version"]
    except Exception:
        return None


def check_pip_conflicts() -> list[str]:
    """Run pip check and return list of conflicts."""
    try:
        result = subprocess.run(
            ["pip", "check"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return [line for line in result.stdout.split("\n") if line.strip()]
        return []
    except Exception as e:
        return [f"Error running pip check: {e}"]


def check_version_sync() -> dict[str, Any]:
    """Check if requirements.txt and pyproject.toml are in sync."""
    req_deps = parse_requirements(REQUIREMENTS_FILE)
    pyproject_deps = parse_pyproject(PYPROJECT_FILE)

    mismatches = []
    for package, req_version in req_deps.items():
        if package in pyproject_deps:
            pyproject_version = pyproject_deps[package]
            if req_version != pyproject_version and req_version != "latest":
                mismatches.append({
                    "package": package,
                    "requirements.txt": req_version,
                    "pyproject.toml": pyproject_version,
                })

    return {"mismatches": mismatches, "synced": len(mismatches) == 0}


def check_known_conflicts(requirements: dict[str, str]) -> list[dict[str, Any]]:
    """Check for known dependency conflicts."""
    conflicts = []

    # Known conflict: httpx vs supabase
    if "httpx" in requirements and "supabase" in requirements:
        httpx_version = requirements["httpx"]
        # supabase 2.9.1 requires httpx<0.28 and >=0.26
        if httpx_version.startswith("0.28"):
            conflicts.append({
                "type": "version_conflict",
                "packages": ["httpx", "supabase"],
                "issue": "supabase 2.9.1 requires httpx<0.28, but httpx==0.28.x is specified",
                "fixed": httpx_version == "0.27.2",
            })

    # Known conflict: pydantic vs aiogram
    if "pydantic" in requirements and "aiogram" in requirements:
        pydantic_version = requirements["pydantic"]
        # aiogram 3.15.0 requires pydantic<2.10 and >=2.4.1
        if pydantic_version.startswith("2.1") or pydantic_version.startswith("2.12"):
            conflicts.append({
                "type": "version_conflict",
                "packages": ["pydantic", "aiogram"],
                "issue": "aiogram 3.15.0 requires pydantic<2.10, but pydantic>=2.10 is specified",
                "fixed": pydantic_version == "2.9.2",
            })

    # Check openai httpx compatibility
    if "openai" in requirements and "httpx" in requirements:
        httpx_version = requirements["httpx"]
        # openai 1.60.1 requires httpx<1 and >=0.23.0
        try:
            major, minor = map(int, httpx_version.split(".")[:2])
            if major >= 1 or (major == 0 and minor < 23):
                conflicts.append({
                    "type": "version_conflict",
                    "packages": ["openai", "httpx"],
                    "issue": f"openai 1.60.1 requires httpx<1 and >=0.23.0, but httpx=={httpx_version}",
                    "fixed": False,
                })
        except ValueError:
            pass

    return conflicts


def check_transitive_dependencies() -> dict[str, Any]:
    """Check transitive dependencies for conflicts."""
    try:
        # Try to get dependency tree using pip show
        result = subprocess.run(
            ["pip", "list", "--format=json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            installed = json.loads(result.stdout)
            return {
                "installed_count": len(installed),
                "packages": [pkg["name"] for pkg in installed[:20]],  # First 20
            }
    except Exception:
        pass

    return {"installed_count": 0, "packages": []}


def check_version_currency(requirements: dict[str, str]) -> dict[str, Any]:
    """Check if versions are up to date."""
    outdated = []
    checked = []

    for package, current_version in requirements.items():
        if current_version == "latest":
            continue

        latest = get_latest_version(package)
        if latest and latest != current_version:
            outdated.append({
                "package": package,
                "current": current_version,
                "latest": latest,
            })
        checked.append({
            "package": package,
            "current": current_version,
            "latest": latest or "unknown",
        })

    return {"outdated": outdated, "checked": checked}


def generate_report() -> dict[str, Any]:
    """Generate comprehensive dependency report."""
    requirements = parse_requirements(REQUIREMENTS_FILE)
    pyproject_deps = parse_pyproject(PYPROJECT_FILE)

    report = {
        "timestamp": datetime.now().isoformat(),
        "requirements_file": str(REQUIREMENTS_FILE),
        "pyproject_file": str(PYPROJECT_FILE),
        "total_packages": len(requirements),
        "version_sync": check_version_sync(),
        "known_conflicts": check_known_conflicts(requirements),
        "version_currency": check_version_currency(requirements),
        "transitive_deps": check_transitive_dependencies(),
        "pip_check": check_pip_conflicts(),
    }

    return report


def print_report(report: dict[str, Any]) -> None:
    """Print formatted report."""
    print("=" * 80)
    print("DEPENDENCY CHECK REPORT")
    print("=" * 80)
    print(f"Generated: {report['timestamp']}")
    print(f"Total packages: {report['total_packages']}")
    print()

    # Version sync
    print("📋 VERSION SYNCHRONIZATION")
    print("-" * 80)
    if report["version_sync"]["synced"]:
        print("✅ requirements.txt and pyproject.toml are in sync")
    else:
        print("❌ VERSION MISMATCHES FOUND:")
        for mismatch in report["version_sync"]["mismatches"]:
            print(f"   {mismatch['package']}:")
            print(f"      requirements.txt: {mismatch['requirements.txt']}")
            print(f"      pyproject.toml:   {mismatch['pyproject.toml']}")
    print()

    # Known conflicts
    print("⚠️  KNOWN CONFLICTS")
    print("-" * 80)
    if not report["known_conflicts"]:
        print("✅ No known conflicts detected")
    else:
        for conflict in report["known_conflicts"]:
            status = "✅ FIXED" if conflict.get("fixed") else "❌ NOT FIXED"
            print(f"{status}: {conflict['issue']}")
            print(f"   Packages: {', '.join(conflict['packages'])}")
    print()

    # Version currency
    print("🔄 VERSION CURRENCY")
    print("-" * 80)
    outdated = report["version_currency"]["outdated"]
    if not outdated:
        print("✅ All packages are up to date")
    else:
        print(f"⚠️  {len(outdated)} packages have newer versions available:")
        for pkg in outdated[:10]:  # Show first 10
            print(f"   {pkg['package']}: {pkg['current']} → {pkg['latest']}")
        if len(outdated) > 10:
            print(f"   ... and {len(outdated) - 10} more")
    print()

    # Transitive dependencies
    print("🌳 TRANSITIVE DEPENDENCIES")
    print("-" * 80)
    transitive = report.get("transitive_deps", {})
    if transitive.get("installed_count", 0) > 0:
        print(f"✅ {transitive['installed_count']} packages installed")
        if transitive.get("packages"):
            print(f"   Sample: {', '.join(transitive['packages'][:10])}")
    else:
        print("⚠️  Could not check transitive dependencies (pip list failed)")
    print()

    # Pip check
    print("🔍 PIP CHECK RESULTS")
    print("-" * 80)
    if not report["pip_check"]:
        print("✅ No conflicts detected by pip check")
    else:
        print("❌ Conflicts detected:")
        for conflict in report["pip_check"]:
            print(f"   {conflict}")
    print()

    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    issues = []
    if not report["version_sync"]["synced"]:
        issues.append(f"{len(report['version_sync']['mismatches'])} version mismatch(es)")
    unfixed_conflicts = [c for c in report["known_conflicts"] if not c.get("fixed")]
    if unfixed_conflicts:
        issues.append(f"{len(unfixed_conflicts)} unfixed conflict(s)")
    if report["pip_check"]:
        issues.append(f"{len(report['pip_check'])} pip check issue(s)")

    if not issues:
        print("✅ All checks passed!")
    else:
        print(f"⚠️  Found {len(issues)} issue(s):")
        for issue in issues:
            print(f"   - {issue}")


def main():
    """Main entry point."""
    print("Checking dependencies...")
    print()

    report = generate_report()
    print_report(report)

    # Save report to file
    report_file = PROJECT_ROOT / "dependency_report.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\n📄 Full report saved to: {report_file}")

    # Exit with error code if issues found
    issues_found = (
        not report["version_sync"]["synced"]
        or any(not c.get("fixed") for c in report["known_conflicts"])
        or report["pip_check"]
    )

    if issues_found:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()

