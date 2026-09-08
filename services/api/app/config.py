from enum import StrEnum

from pydantic import BaseModel


class TradingMode(StrEnum):
    SIMULATION = "SIMULATION"
    TESTNET = "TESTNET"
    LIVE = "LIVE"


class PublicConfig(BaseModel):
    trading_mode: TradingMode = TradingMode.SIMULATION
    direct_ai_order_enabled: bool = False
    min_confidence: float = 75.0
    min_opportunity_score: float = 75.0
    max_leverage: float = 5.0
