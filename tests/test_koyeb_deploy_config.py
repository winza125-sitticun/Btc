from importlib import import_module
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_koyeb_python_buildpack_contract_is_declared():
    assert (ROOT / "requirements.txt").read_text(encoding="utf-8") == ".\n"
    assert (ROOT / ".python-version").read_text(encoding="utf-8") == "3.12.14\n"


def test_koyeb_ignores_documentation_only_changes():
    ignored = (ROOT / ".koyebignore").read_text(encoding="utf-8").splitlines()

    assert "docs/" in ignored
    assert "README.md" in ignored


def test_news_worker_entrypoint_is_importable():
    module = import_module("services.news_worker.app.main")

    assert callable(module.main)


def test_repository_deployment_contracts_do_not_contain_credentials():
    deployment_files = (
        ROOT / "railway.toml",
        ROOT / "railway.market-worker.toml",
        ROOT / "wrangler.jsonc",
    )
    forbidden_assignment = re.compile(
        r"(?im)^\s*(?:"
        r"(?:BINANCE|GEMINI|ANTHROPIC|OPENAI(?:_COMPATIBLE)?|DEEPSEEK|OPENROUTER)"
        r"_(?:API_)?(?:KEY|SECRET)|"
        r"SUPABASE_SERVICE_ROLE_KEY|"
        r"(?:BINANCE_)?WITHDRAWAL[_A-Z]*(?:KEY|SECRET|PASSWORD|TOKEN|ADDRESS)|"
        r"(?:API_KEY|API_SECRET|PASSWORD|CREDENTIALS?)"
        r")\s*[:=]\s*(?!$|[\"']?\s*(?:\$\{\{|\{\{))"
    )

    violations = {
        path.name: match.group(0).strip()
        for path in deployment_files
        for match in forbidden_assignment.finditer(path.read_text(encoding="utf-8"))
    }

    assert violations == {}
