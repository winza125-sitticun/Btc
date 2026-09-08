from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PositionSide(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class SimulationPosition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=3, max_length=30)
    side: PositionSide
    entry_price: float = Field(gt=0)
    quantity: float = Field(gt=0)
    leverage: float = Field(gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    take_profits: list[float] = Field(default_factory=list)
    fees_paid: float = Field(default=0, ge=0)
    funding_paid: float = Field(default=0, ge=0)
    slippage_cost: float = Field(default=0, ge=0)

    @property
    def total_costs(self) -> float:
        return self.fees_paid + self.funding_paid + self.slippage_cost

    def unrealized_pnl(self, mark_price: float) -> float:
        if mark_price <= 0:
            raise ValueError("mark_price must be positive")
        direction = 1 if self.side is PositionSide.LONG else -1
        gross = (mark_price - self.entry_price) * self.quantity * direction
        return gross - self.total_costs
