from pydantic import BaseModel, ConfigDict, Field


class OpportunityInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    technical: float = Field(ge=0, le=100)
    momentum: float = Field(ge=0, le=100)
    volume: float = Field(ge=0, le=100)
    order_flow: float = Field(ge=0, le=100)
    open_interest: float = Field(ge=0, le=100)
    funding: float = Field(ge=0, le=100)
    liquidity: float = Field(ge=0, le=100)
    news: float = Field(ge=0, le=100)
    macro: float = Field(ge=0, le=100)
    risk_reward: float = Field(ge=0, le=100)


WEIGHTS: dict[str, float] = {
    "technical": 0.20,
    "momentum": 0.10,
    "volume": 0.08,
    "order_flow": 0.15,
    "open_interest": 0.10,
    "funding": 0.05,
    "liquidity": 0.10,
    "news": 0.10,
    "macro": 0.05,
    "risk_reward": 0.07,
}


def calculate_opportunity_score(inputs: OpportunityInputs) -> float:
    values = inputs.model_dump()
    return round(sum(values[name] * weight for name, weight in WEIGHTS.items()), 2)
