from pathlib import Path


ROOT = Path(__file__).parents[1]
WEB_SRC = ROOT / "apps/web/src"


def read(name: str) -> str:
    return (WEB_SRC / name).read_text(encoding="utf-8")


def test_multi_agent_contract_files_exist():
    for name in ("multiAgentTypes.ts", "multiAgentApi.ts", "MultiAgentPanel.tsx"):
        assert (WEB_SRC / name).exists(), f"missing T010 frontend contract file: {name}"


def test_types_mirror_openapi_surface_without_secret_fields():
    source = read("multiAgentTypes.ts")
    for name in (
        "AgentRole",
        "Direction",
        "AttemptStatus",
        "RunStatus",
        "RiskStatus",
        "RolloutMode",
        "RoleAssignmentSummary",
        "MultiAgentConfigSummary",
        "RoleContribution",
        "HesitationBreakdown",
        "VortexInputs",
        "AgentAttempt",
        "ConsensusDecision",
        "RiskResult",
        "MultiAgentRunSummary",
        "MultiAgentRunDetail",
        "DashboardEvent",
        "PerformanceSummary",
    ):
        assert f"export type {name}" in source

    for secret_name in ("api_key", "authorization", "prompt_text", "credential"):
        assert secret_name not in source.lower()


def test_polling_contract_uses_exact_spec_values_and_persisted_state_rules():
    source = read("multiAgentApi.ts")
    for literal in (
        "ACTIVE_POLL_MS = 3000",
        "TERMINAL_POLL_MS = 15000",
        "HIDDEN_POLL_MS = 60000",
        "STALE_AFTER_MS = 30000",
        "RETRY_BACKOFF_MS = [2000, 5000, 10000, 30000]",
    ):
        assert literal in source

    assert "document.hidden" in source
    assert "RUNNING" in source and "PARTIAL" in source
    assert "lastSuccessfulRefresh" in source
    assert "retryIndex" in source
    assert "retryIndex = 0" in source or "setRetryIndex(0)" in source


def test_multi_agent_api_is_read_only_and_uses_all_t009_read_endpoints():
    source = read("multiAgentApi.ts")
    for endpoint in (
        "/api/v1/multi-agent/config",
        "/api/v1/multi-agent/latest",
        "/api/v1/multi-agent/runs/",
        "/api/v1/multi-agent/events",
        "/api/v1/multi-agent/performance",
    ):
        assert endpoint in source

    lowered = source.lower()
    for method in ("method: 'post'", 'method: "post"', "method: 'put'", 'method: "put"', "method: 'patch'", 'method: "patch"', "method: 'delete'", 'method: "delete"'):
        assert method not in lowered
    for mutation_name in ("updateRole", "saveRole", "setRoleAssignment", "updateMultiAgentConfig"):
        assert mutation_name not in source


def test_panel_explains_roles_consensus_hesitation_risk_and_events_without_3d():
    source = read("MultiAgentPanel.tsx")
    for marker in (
        "Multi-Agent Explainability",
        "Consensus",
        "Deterministic Risk",
        "Hesitation",
        "Agreement",
        "Coverage",
        "Event Timeline",
        "TECHNICAL",
        "MOMENTUM",
        "ORDER_FLOW",
        "NEWS",
        "CONTRARIAN",
        "RISK_REVIEW",
    ):
        assert marker in source

    for factor in (
        "disagreement",
        "confidence_dispersion",
        "timeframe_conflict",
        "market_uncertainty",
    ):
        assert factor in source

    assert "missing-role" in source
    assert "wait-evidence" in source
    assert "APPROVED" in source
    assert "WAIT" in source
    assert "@react-three" not in source
    assert "three" not in source.lower()


def test_app_mounts_multi_agent_panel_and_preserves_existing_safety_copy():
    source = read("App.tsx")
    assert "MultiAgentPanel" in source
    assert "Live execution remains disabled. LIVE_READY means readiness checks passed; it does not submit orders." in source


def test_t010_styles_include_mobile_cards_and_state_classes():
    source = read("styles.css")
    for css_class in (
        ".multi-agent-panel",
        ".role-grid",
        ".role-card",
        ".consensus-card",
        ".risk-card",
        ".hesitation-grid",
        ".event-timeline",
        ".stale-badge",
        ".missing-role",
        ".wait-evidence",
    ):
        assert css_class in source
    assert "@media" in source
