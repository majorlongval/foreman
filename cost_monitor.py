"""
FOREMAN Cost Monitor — tracks API spend + cloud infrastructure costs.

Supports:
  - Anthropic API cost tracking (from token usage)
  - GCP cost tracking (from billing API)
  - Combined budget enforcement
  - Telegram alerts when thresholds are hit

This module is imported by agents, not run standalone.
"""

import os
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dataclasses import dataclass, field
from llm_client import PRICING as MODEL_PRICING

log = logging.getLogger("foreman.costs")


@dataclass
class CostRecord:
    timestamp: str
    agent: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    action: str  # "refine", "brainstorm", "review", "title_gen", etc.


@dataclass
class CostTracker:
    """Tracks API costs across agents with persistence and budget enforcement."""

    ceiling_usd: float = 5.0
    session_start: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    records: list = field(default_factory=list)
    total_cost: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    calls: int = 0

    # Budget alert thresholds (percentage of ceiling)
    _alert_thresholds: list = field(default_factory=lambda: [0.50, 0.75, 0.90, 1.0])
    _alerts_fired: set = field(default_factory=set)

    # Telegram notification callback (set by agent)
    _notify_fn: object = None

    def set_notify(self, fn):
        """Set callback for budget alerts: fn(message: str)"""
        self._notify_fn = fn

    def record(self, model: str, usage, agent: str = "unknown", action: str = "unknown") -> float:
        """Record an API call's cost. Returns the cost of this call."""
        input_tokens = usage.input_tokens
        output_tokens = usage.output_tokens
        pricing = MODEL_PRICING.get(model, {"input": 3.0, "output": 15.0})
        cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost += cost
        self.calls += 1
        self.records.append(CostRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            agent=agent,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            action=action,
        ))
        log.info(
            f"  💰 {action}: ${cost:.4f} ({model}) | "
            f"Session: ${self.total_cost:.4f} / ${self.ceiling_usd:.2f} "
            f"({self.total_cost/self.ceiling_usd*100:.0f}%)"
        )
        # Check alert thresholds
        self._check_alerts()
        return cost

    def _check_alerts(self):
        """Fire alerts at budget thresholds."""
        try:
            pct = self.total_cost / self.ceiling_usd if self.ceiling_usd > 0 else 0
            for threshold in self._alert_thresholds:
                if pct >= threshold and threshold not in self._alerts_fired:
                    self._alerts_fired.add(threshold)
                    msg = (
                        f"⚠️ BUDGET ALERT: {threshold*100:.0f}% of ${self.ceiling_usd:.2f} "
                        f"(${self.total_cost:.4f} spent, {self.calls} calls)"
                    )
                    log.warning(msg)
                    if self._notify_fn:
                        try:
                            self._notify_fn(msg)
                        except Exception as e:
                            log.error(f"Failed to send alert: {e}")
        except Exception as e:
            log.error(f"Error checking budget alerts: {e}")

    def check_ceiling(self) -> bool:
        """Returns True if under budget. Logs warning if over."""
        if self.total_cost >= self.ceiling_usd:
            log.warning(
                f"🚨 COST CEILING REACHED: ${self.total_cost:.4f} >= ${self.ceiling_usd:.2f} "
                f"— agent should park"
            )
            return False
        return True

    def summary(self) -> str:
        return (
            f"Session: {self.calls} calls, "
            f"{self.total_input_tokens:,} in / {self.total_output_tokens:,} out, "
            f"${self.total_cost:.4f} / ${self.ceiling_usd:.2f}"
        )

    def breakdown_by_agent(self) -> dict:
        """Cost breakdown per agent."""
        agents = {}
        for r in self.records:
            if r.agent not in agents:
                agents[r.agent] = {"cost": 0.0, "calls": 0}
            agents[r.agent]["cost"] += r.cost_usd
            agents[r.agent]["calls"] += 1
        return agents

    def breakdown_by_action(self) -> dict:
        """Cost breakdown per action type."""
        actions = {}
        for r in self.records:
            if r.action not in actions:
                actions[r.action] = {"cost": 0.0, "calls": 0}
            actions[r.action]["cost"] += r.cost_usd
            actions[r.action]["calls"] += 1
        return actions

    def save_session(self, path: str = "cost_log.jsonl"):
        """Append session records to a JSONL file for analysis."""
        try:
            p = Path(path)
            with p.open("a") as f:
                for r in self.records:
                    f.write(json.dumps({
                        "timestamp": r.timestamp,
                        "agent": r.agent,
                        "model": r.model,
                        "input_tokens": r.input_tokens,
                        "output_tokens": r.output_tokens,
                        "cost_usd": r.cost_usd,
                        "action": r.action,
                    }) + "\n")
            log.info(f"📝 Saved {len(self.records)} cost records to {path}")
        except Exception as e:
            log.error(f"Failed to save session costs: {e}")


# ─── Cloud Cost Monitoring ───────────────────────────────────

class CloudCostMonitor:
    """
    Monitors cloud infrastructure costs.

    For GCP: Uses the Cloud Billing API to check current spend.
    For Railway: Uses the Railway API to check usage.

    This is a placeholder that will be implemented when we deploy to cloud.
    For now it provides the interface that agents will call.
    """

    def __init__(self, provider: str = "local"):
        self.provider = provider
        self.daily_budget_usd = float(os.environ.get("CLOUD_DAILY_BUDGET", "2.0"))

    def get_today_spend(self) -> float:
        """Get today's cloud infrastructure spend in USD."""
        try:
            if self.provider == "local":
                return 0.0  # Running locally, no cloud cost

            if self.provider == "gcp":
                return self._get_gcp_spend()

            if self.provider == "railway":
                return self._get_railway_spend()

            return 0.0
        except Exception as e:
            log.error(f"Failed to get cloud spend: {e}")
            return 0.0

    def check_budget(self) -> tuple[bool, float]:
        """Returns (under_budget: bool, spend: float)."""
        spend = self.get_today_spend()
        ok = spend < self.daily_budget_usd
        if not ok:
            log.warning(
                f"🚨 CLOUD BUDGET EXCEEDED: ${spend:.2f} >= ${self.daily_budget_usd:.2f}"
            )
        return ok, spend

    def _get_gcp_spend(self) -> float:
        """Query GCP billing API for today's spend."""
        log.info("  GCP cost check: not yet implemented")
        return 0.0

    def _get_railway_spend(self) -> float:
        """Query Railway API for current usage."""
        log.info("  Railway cost check: not yet implemented")
        return 0.0


# ─── Combined Budget Check ───────────────────────────────────

def create_cost_system(
    api_ceiling_usd: float = 5.0,
    cloud_provider: str = "local",
    cloud_daily_budget_usd: float = 2.0,
) -> tuple[CostTracker, CloudCostMonitor]:
    """Create the full cost monitoring system."""
    api = CostTracker(ceiling_usd=api_ceiling_usd)
    cloud = CloudCostMonitor(provider=cloud_provider)
    cloud.daily_budget_usd = cloud_daily_budget_usd
    return api, cloud