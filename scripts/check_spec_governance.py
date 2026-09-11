#!/usr/bin/env python3
"""Structural Spec Kit governance check for pull requests.

Runtime-sensitive feature changes must travel with a complete changed feature
artifact directory. Runtime bug changes on fix/* or bugfix/* branches must
travel with complete Spec Kit bug reports.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Iterable


FEATURE_REQUIRED = ("spec.md", "plan.md", "tasks.md")
BUG_REQUIRED = ("assessment.md", "fix.md", "test.md")


def is_runtime_sensitive(path: str) -> bool:
    """Return True when a changed path can affect runtime/deployment behavior."""
    p = PurePosixPath(path)
    parts = p.parts
    if not parts:
        return False

    if parts[0] in {"apps", "btc_core"}:
        return True

    if len(parts) == 1:
        name = parts[0]
        if name == "pyproject.toml":
            return True
        if name.startswith("Dockerfile"):
            return True
        if name.startswith("railway") and name.endswith(".toml"):
            return True

    return False


def _changed_feature_dirs(changed_files: Iterable[str]) -> set[PurePosixPath]:
    dirs: set[PurePosixPath] = set()
    for raw in changed_files:
        p = PurePosixPath(raw)
        if len(p.parts) >= 3 and p.parts[0] == "specs":
            dirs.add(PurePosixPath(*p.parts[:2]))
    return dirs


def _changed_bug_dirs(changed_files: Iterable[str]) -> set[PurePosixPath]:
    dirs: set[PurePosixPath] = set()
    for raw in changed_files:
        p = PurePosixPath(raw)
        if len(p.parts) >= 4 and p.parts[0:2] == (".specify", "bugs"):
            dirs.add(PurePosixPath(*p.parts[:3]))
    return dirs


def _complete_dir(root: Path, directory: PurePosixPath, required: tuple[str, ...]) -> bool:
    base = root.joinpath(*directory.parts)
    return all((base / filename).is_file() for filename in required)


def validate_changes(changed_files: set[str], branch: str, root: Path) -> list[str]:
    """Validate structural Spec Kit requirements and return human-readable errors."""
    runtime_files = sorted(path for path in changed_files if is_runtime_sensitive(path))
    if not runtime_files:
        return []

    errors: list[str] = []
    is_bug_branch = branch.startswith("fix/") or branch.startswith("bugfix/")

    if is_bug_branch:
        bug_dirs = _changed_bug_dirs(changed_files)
        complete = [d for d in bug_dirs if _complete_dir(root, d, BUG_REQUIRED)]
        if not complete:
            errors.append(
                "Runtime bug changes require a changed .specify/bugs/<slug>/ directory "
                "containing assessment.md, fix.md, and test.md."
            )
    else:
        feature_dirs = _changed_feature_dirs(changed_files)
        complete = [d for d in feature_dirs if _complete_dir(root, d, FEATURE_REQUIRED)]
        if not complete:
            errors.append(
                "Runtime feature changes require a changed specs/<feature>/ directory "
                "containing spec.md, plan.md, and tasks.md."
            )

    if errors:
        errors.append("Runtime-sensitive files changed: " + ", ".join(runtime_files))
    return errors


def changed_files_between(base: str, head: str) -> set[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def current_branch() -> str:
    github_head = os.getenv("GITHUB_HEAD_REF", "").strip()
    if github_head:
        return github_head
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: check_spec_governance.py <base-ref-or-sha> <head-ref-or-sha>")
        return 2

    base, head = argv[1], argv[2]
    root = Path.cwd()
    files = changed_files_between(base, head)
    branch = current_branch()
    errors = validate_changes(files, branch, root)

    if errors:
        print("Spec Kit governance check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Spec Kit governance check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
