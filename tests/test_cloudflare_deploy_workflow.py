from pathlib import Path


WORKFLOW = Path(".github/workflows/deploy-web.yml")


def test_cloudflare_deploy_waits_for_green_main_ci_and_uses_scoped_secrets():
    assert WORKFLOW.exists(), "Cloudflare deploy workflow must exist"

    text = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_run:" in text
    assert 'workflows: ["CI"]' in text
    assert "branches: [main]" in text
    assert "types: [completed]" in text
    assert "github.event.workflow_run.conclusion == 'success'" in text

    assert "VITE_API_BASE_URL: https://api-production-399c.up.railway.app" in text
    assert "npm install" in text
    assert "npm run build" in text
    assert "cloudflare/wrangler-action@v3" in text
    assert "secrets.CLOUDFLARE_API_TOKEN" in text
    assert "secrets.CLOUDFLARE_ACCOUNT_ID" in text
    assert "deploy --config wrangler.jsonc" in text

    # Deploy must never be triggered directly from pull requests.
    assert "pull_request:" not in text
