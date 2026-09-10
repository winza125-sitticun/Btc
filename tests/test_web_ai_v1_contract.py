from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "apps" / "web" / "src"


def test_web_api_declares_ai_analysis_and_public_config_readers():
    text = (ROOT / "api.ts").read_text(encoding="utf-8")
    assert "export type AIAnalysis" in text
    assert "export type PublicConfig" in text
    assert "export function fetchLatestAIAnalyses" in text
    assert "/api/v1/ai/latest" in text
    assert "export function fetchPublicConfig" in text
    assert "/api/v1/config/public" in text


def test_web_app_keeps_ai_failure_separate_and_marks_pending_as_not_authorized():
    text = (ROOT / "App.tsx").read_text(encoding="utf-8")
    assert "aiError" in text
    assert "FULL_RISK_CONTEXT_PENDING" in text
    assert "Pending — not trade-authorized" in text
    assert "fetchLatestAIAnalyses" in text
    assert "fetchPublicConfig" in text
    assert "AI analysis unavailable" in text


def test_settings_are_read_only_and_show_only_key_configuration_state():
    text = (ROOT / "App.tsx").read_text(encoding="utf-8")
    assert "ai_api_key_configured" in text
    assert "Configured" in text
    assert "Not configured" in text
    assert "Production AI settings are read-only in V1" in text
    assert "AI order execution and live trading remain disabled" in text


def test_ai_card_styles_exist_without_new_ui_framework():
    text = (ROOT / "styles.css").read_text(encoding="utf-8")
    assert ".ai-analysis" in text
    assert ".ai-grid" in text
    assert ".risk-pending" in text
    package = (ROOT.parent / "package.json").read_text(encoding="utf-8").lower()
    for framework in ("tailwind", "bootstrap", "material-ui", "@mui/"):
        assert framework not in package


def test_web_matches_ai_analysis_to_current_scanner_candidate_identity():
    api = (ROOT / "api.ts").read_text(encoding="utf-8")
    app = (ROOT / "App.tsx").read_text(encoding="utf-8")
    assert "id: number" in api
    assert "run_id: string" in api
    assert "analysis.scanner_candidate_id !== candidate.id" in app
