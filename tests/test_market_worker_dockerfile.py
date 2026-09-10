from pathlib import Path


DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile.market-worker"


def test_market_worker_dockerfile_keeps_supabase_service_role_key_out_of_build_env() -> None:
    assert DOCKERFILE.exists(), "Dockerfile.market-worker must exist"

    text = DOCKERFILE.read_text(encoding="utf-8")
    normalized_lines = [line.strip().upper() for line in text.splitlines()]

    assert not any(
        line.startswith("ARG ") and "SUPABASE_SERVICE_ROLE_KEY" in line
        for line in normalized_lines
    )
    assert not any(
        line.startswith("ENV ") and "SUPABASE_SERVICE_ROLE_KEY" in line
        for line in normalized_lines
    )
