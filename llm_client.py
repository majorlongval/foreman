from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from typing import List
from llm_client import estimate_cost

log = logging.getLogger("foreman.costs")

@dataclass
class CostRecord:
    timestamp: str
    agent: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    action: str

class CostMonitor:
    def __init__(self, ceiling_usd: float = 1.0):
        self.ceiling_usd = ceiling_usd
        self.total_cost = 0.0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.calls = 0
        self.records: List[CostRecord] = []

    def record(self, model: str, usage, agent: str = "unknown", action: str = "unknown") -> float:
        """Record an API call's cost. Returns the cost of this call."""
        input_tokens = usage.input_tokens
        output_tokens = usage.output_tokens
        
        cost = estimate_cost(model, input_tokens, output_tokens)
        
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
        """Monitor budget usage."""
        if self.total_cost >= self.ceiling_usd:
            log.error(f"  🚨 BUDGET EXCEEDED: ${self.total_cost:.4f} / ${self.ceiling_usd:.2f}")
            raise RuntimeError(f"Budget exceeded: ${self.total_cost:.4f}")
        
        elif self.total_cost >= (self.ceiling_usd * 0.9):
            log.warning(f"  ⚠️ BUDGET WARNING: {self.total_cost/self.ceiling_usd*100:.0f}% used")

    def summary(self) -> str:
        return (f"Total spent: ${self.total_cost:.4f} across {self.calls} calls "
                f"({self.total_input_tokens} input, {self.total_output_tokens} output tokens).")