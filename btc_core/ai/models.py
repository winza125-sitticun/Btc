from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AIProvider(StrEnum):
    GEMINI = "GEMINI"
    CLAUDE = "CLAUDE"
    OPENAI_COMPATIBLE = "OPENAI_COMPATIBLE"
    DEEPSEEK = "DEEPSEEK"
    OPENROUTER = "OPENROUTER"


class Direction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    WAIT = "WAIT"
    EXIT = "EXIT"


class AIDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: AIProvider
    model: str = Field(min_length=1, max_length=120)
    symbol: str = Field(min_length=3, max_length=30)
    timeframe: str = Field(min_length=1, max_length=10)
    direction: Direction
    confidence: float = Field(ge=0, le=100)
    entry_min: float | None = Field(default=None, ge=0)
    entry_max: float | None = Field(default=None, ge=0)
    stop_loss: float | None = Field(default=None, ge=0)
    take_profits: list[float] = Field(default_factory=list, max_length=5)
    risk_reward: float | None = Field(default=None, ge=0)
    reason_summary: str = Field(min_length=1, max_length=1000)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("take_profits")
    @classmethod
    def validate_take_profits(cls, values: list[float]) -> list[float]:
        if any(value < 0 for value in values):
            raise ValueError("take profit values must not be negative")
        return values

    @model_validator(mode="after")
    def validate_trade_geometry_contract(self):
        if self.direction in {Direction.WAIT, Direction.EXIT}:
            self.entry_min = None
            self.entry_max = None
            self.stop_loss = None
            self.take_profits = []
            self.risk_reward = None
            return self

        if (
            self.entry_min is None
            or self.entry_max is None
            or self.stop_loss is None
            or self.risk_reward is None
            or self.entry_min <= 0
            or self.entry_max <= 0
            or self.stop_loss <= 0
            or self.risk_reward <= 0
            or not self.take_profits
            or any(value <= 0 for value in self.take_profits)
        ):
            raise ValueError("LONG/SHORT decisions require complete positive trade geometry")
        if self.entry_min > self.entry_max:
            raise ValueError("entry_min must be less than or equal to entry_max")
        return self
