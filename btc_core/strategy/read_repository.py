"""Anonymous-key, allow-listed read access for strategy operational data."""
from __future__ import annotations

from typing import Any
import httpx


class StrategyReadRepository:
    _selects = {
        "summary": "id,provider,model,timeframe,direction,symbol,rolling_window,window_started_at,window_ended_at,analysis_count,eligible_signal_count,simulated_trade_count,no_fill_count,win_count,loss_count,win_rate,average_net_return,median_net_return,expectancy,profit_factor,max_drawdown_percent,average_mfe_percent,average_mae_percent,tp1_hit_rate,tp2_hit_rate,tp3_hit_rate,sl_hit_rate,provider_success_rate,median_latency_ms,p95_latency_ms,full_data_count,partial_data_count,created_at",
        "outcomes": "id,ai_analysis_id,scanner_candidate_id,symbol,timeframe,direction,horizon,signal_created_at,evaluation_due_at,entry_reference,entry_touched,stop_touched,highest_tp_hit,mfe_percent,mae_percent,final_return_percent,outcome,data_quality,evaluated_at,created_at",
        "account": "id,name,currency,starting_balance,balance,equity,realized_pnl,max_equity,max_drawdown_percent,daily_realized_loss,trading_date,created_at,updated_at",
        "trades": "id,account_id,ai_analysis_id,scanner_candidate_id,symbol,side,status,planned_entry_min,planned_entry_max,simulated_entry_price,quantity,leverage,risk_amount,stop_loss,highest_tp_reached,fees_paid,slippage_cost,funding_paid,funding_quality,realized_pnl,realized_return_percent,opened_at,closed_at,expires_at,expired_at,exit_reason,full_risk_approved,created_at,updated_at",
        "alerts": "id,alert_type,severity,symbol,ai_analysis_id,scanner_run_id,title,short_summary,dedupe_key,first_observed_at,last_observed_at,status,created_at,updated_at",
        "readiness": "id,overall_status,blocking_reasons,created_at",
        "order_intents": "id,simulation_trade_id,ai_analysis_id,mode,symbol,side,quantity,leverage,entry_type,entry_price,stop_loss,validation_status,rejection_reasons,exchange_submission_allowed,created_at,updated_at",
        "experiments": "id,name,description,baseline_identifier,status,started_at,ended_at,sample_count,decision_reason,created_at,updated_at",
    }
    _tables = {"summary":"market_strategy_metrics", "outcomes":"market_ai_signal_outcomes", "account":"market_simulation_accounts", "trades":"market_simulation_trades", "alerts":"market_alert_events", "readiness":"market_readiness_checks", "order_intents":"market_order_intents", "experiments":"market_strategy_experiments"}

    def __init__(self, *, supabase_url: str, anon_key: str, transport: httpx.AsyncBaseTransport | None = None):
        if not supabase_url.strip() or not anon_key.strip():
            raise ValueError("Supabase URL and anon key are required")
        self._client = httpx.AsyncClient(base_url=f"{supabase_url.rstrip('/')}/rest/v1", headers={"apikey": anon_key, "Authorization": f"Bearer {anon_key}"}, transport=transport, timeout=10)

    async def aclose(self):
        await self._client.aclose()

    async def read(self, resource: str, *, limit: int, cursor: str | None = None, mode: str | None = None) -> dict[str, Any]:
        if resource not in self._tables or not 1 <= limit <= 100:
            raise ValueError("invalid read query")
        params: dict[str, str] = {"select": self._selects[resource], "order": "created_at.desc", "limit": str(limit)}
        if cursor:
            if len(cursor) > 256 or any(c in cursor for c in "\r\n"):
                raise ValueError("invalid cursor")
            params["created_at"] = f"lt.{cursor}"
        if resource == "order_intents":
            if mode not in (None, "DRY_RUN"):
                raise ValueError("only DRY_RUN mode is supported")
            params["mode"] = "eq.DRY_RUN"
        response = await self._client.get(f"/{self._tables[resource]}", params=params)
        response.raise_for_status()
        rows = response.json() if isinstance(response.json(), list) else []
        next_cursor = rows[-1].get("created_at") if len(rows) == limit and rows else None
        return {"items": rows, "next_cursor": next_cursor}
