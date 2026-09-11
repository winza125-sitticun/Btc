from pathlib import Path

from scripts.check_spec_governance import is_runtime_sensitive, validate_changes


def write_files(root: Path, *paths: str) -> None:
    for raw in paths:
        path = root / raw
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok\n", encoding="utf-8")


def test_runtime_sensitive_paths() -> None:
    assert is_runtime_sensitive("btc_core/service.py")
    assert is_runtime_sensitive("apps/web/src/main.ts")
    assert is_runtime_sensitive("Dockerfile.market-worker")
    assert is_runtime_sensitive("railway.market-worker.toml")
    assert is_runtime_sensitive("pyproject.toml")
    assert not is_runtime_sensitive("docs/SPEC_KIT_WORKFLOW.md")
    assert not is_runtime_sensitive("specs/001-example/spec.md")


def test_docs_only_change_does_not_require_feature_spec(tmp_path: Path) -> None:
    errors = validate_changes(
        {"docs/SPEC_KIT_WORKFLOW.md", "AGENTS.md"},
        branch="codex/docs-only",
        root=tmp_path,
    )
    assert errors == []


def test_feature_runtime_change_requires_complete_spec(tmp_path: Path) -> None:
    write_files(tmp_path, "specs/012-example/spec.md")
    errors = validate_changes(
        {"btc_core/service.py", "specs/012-example/spec.md"},
        branch="codex/example",
        root=tmp_path,
    )
    assert errors
    assert "spec.md, plan.md, and tasks.md" in errors[0]


def test_feature_runtime_change_accepts_complete_spec(tmp_path: Path) -> None:
    write_files(
        tmp_path,
        "specs/012-example/spec.md",
        "specs/012-example/plan.md",
        "specs/012-example/tasks.md",
    )
    errors = validate_changes(
        {
            "btc_core/service.py",
            "specs/012-example/spec.md",
            "specs/012-example/plan.md",
            "specs/012-example/tasks.md",
        },
        branch="codex/example",
        root=tmp_path,
    )
    assert errors == []


def test_bug_runtime_change_requires_all_bug_reports(tmp_path: Path) -> None:
    write_files(tmp_path, ".specify/bugs/login-timeout/assessment.md")
    errors = validate_changes(
        {
            "btc_core/service.py",
            ".specify/bugs/login-timeout/assessment.md",
        },
        branch="fix/login-timeout",
        root=tmp_path,
    )
    assert errors
    assert "assessment.md, fix.md, and test.md" in errors[0]


def test_bug_runtime_change_accepts_complete_bug_reports(tmp_path: Path) -> None:
    write_files(
        tmp_path,
        ".specify/bugs/login-timeout/assessment.md",
        ".specify/bugs/login-timeout/fix.md",
        ".specify/bugs/login-timeout/test.md",
    )
    errors = validate_changes(
        {
            "btc_core/service.py",
            ".specify/bugs/login-timeout/assessment.md",
            ".specify/bugs/login-timeout/fix.md",
            ".specify/bugs/login-timeout/test.md",
        },
        branch="fix/login-timeout",
        root=tmp_path,
    )
    assert errors == []
