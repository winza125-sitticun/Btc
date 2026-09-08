from fastapi import FastAPI

from services.api.app.config import PublicConfig


app = FastAPI(title="BTC AI Futures API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "btc-ai-futures-api"}


@app.get("/api/v1/config/public", response_model=PublicConfig)
def public_config() -> PublicConfig:
    return PublicConfig()
