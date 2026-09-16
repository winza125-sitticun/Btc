from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RezAnalysisResult:
    analysis_version: str
    state: str
    structure_1h: str
    trigger_15m: str
    supporting_triggers: tuple[str, ...]
    reason: str
    protected_swing_timestamp: Optional[int]
    protected_swing_price: Optional[float]
    trigger_level_kind: Optional[str]
    trigger_level_price: Optional[float]
    closed_1h_at_ms: Optional[int]
    closed_15m_at_ms: Optional[int]


def _reject_unknown(analysis_version: str, reason: str) -> RezAnalysisResult:
    return RezAnalysisResult(
        analysis_version=analysis_version,
        state="REJECT",
        structure_1h="UNKNOWN",
        trigger_15m="NO_TRIGGER",
        supporting_triggers=(),
        reason=reason,
        protected_swing_timestamp=None,
        protected_swing_price=None,
        trigger_level_kind=None,
        trigger_level_price=None,
        closed_1h_at_ms=None,
        closed_15m_at_ms=None,
    )


def analyze_rez_candidate(
    *,
    side: str,
    candles_1h: list[dict],
    candles_15m: list[dict],
    atr_period: int,
    atr_buffer_mult: float,
    swing_window: int,
    analysis_version: str = "REZ_V1",
) -> RezAnalysisResult:
    side = str(side).upper()
    if side not in {"LONG", "SHORT"} or atr_period <= 0 or atr_buffer_mult < 0 or swing_window < 1:
        return _reject_unknown(analysis_version, "INVALID_INPUT")
    if not candles_1h or not candles_15m:
        return _reject_unknown(analysis_version, "INSUFFICIENT_HISTORY")
    return _reject_unknown(analysis_version, "ANALYSIS_NOT_READY")
