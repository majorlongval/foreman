```python
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
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger("foreman.costs")

# ─── API Cost Tracking ───────────────────────────────────────

# Pricing per 1M tokens (update as needed from https://docs.anthropic.com/en/api/pricing)
MODEL_PRICING = {
    "claude-3-5-sonnet-20240620": {"input": 3.0,  "output": 15.0},
    "claude-3-opus-20240229":     {"input": 15.0, "output": 75.0},
    "claude-3-haiku-20240307":    {"input": 0.25, "output": 1.25},
}


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
    _notify_fn: Callable[[str], None] | None = None

    def set_notifier(self, notify_fn: Callable[[str], None]):
        """Sets the notification callback function."""
        try:
            self._notify_fn = notify_fn
            log.info("CostTracker notifier has been set.")
        except Exception as e:
            log.error(f"Failed to set notifier: {e}", exc_info=True)

    def track_api_cost(self, agent_name: str, model: str, input_tokens: int, output_tokens: int, action: str):
        """Calculates cost for an API call, adds it to the total, and checks budget."""
        try:
            if model not in MODEL_PRICING:
                log.warning(f"Cost tracking: Model '{model}' not found in pricing list. Assuming $0 cost.")
                cost = 0.0
            else:
                price_in = MODEL_PRICING[model]["input"]
                price_out = MODEL_PRICING[model]["output"]
                cost = ((input_tokens / 1_000_000) * price_in) + ((output_tokens / 1_000_000) * price_out)

            record = CostRecord(
                timestamp=datetime.now(timezone.utc).isoformat(),
                agent=agent_name,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
                action=action,
            )

            self.records.append(record)
            self.total_cost += cost
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens
            self.calls += 1

            log.info(
                f"API call cost: ${cost:.6f} | Total session cost: ${self.total_cost:.4f} "
                f"({action}, {model}, in:{input_tokens}, out:{output_tokens})"
            )

            self._check_budget()

        except Exception as e:
            log.error(f"Error tracking API cost: {e}", exc_info=True)

    def is_over_budget(self) -> bool:
        """Checks if the total cost has exceeded the configured ceiling."""
        return self.total_cost >= self.ceiling_usd

    def _check_budget(self):
        """Checks current cost against alert thresholds and sends notifications."""
        try:
            if not self._notify_fn:
                return

            # Check from highest to lowest threshold
            for threshold in sorted(self._alert_thresholds, reverse=True):
                if self.total_cost >= self.ceiling_usd * threshold:
                    # If this threshold alert has not been fired yet
                    if threshold not in self._alerts_fired:
                        self._alerts_fired.add(threshold)
                        percentage = int(threshold * 100)
                        
                        if threshold == 1.0:
                            message = (
                                f"⛔️ *COST CEILING REACHED* ⛔️\n\n"
                                f"The API cost ceiling of *${self.ceiling_usd:.2f}* has been reached.\n"
                                f"The agent will now stop making API calls.\n\n"
                                f"🔹 **Final Cost:** ${self.total_cost:.2f}"
                            )
                        else:
                            message = (
                                f"🚨 *Cost Alert* 🚨\n\n"
                                f"API cost has reached *{percentage}%* of the ceiling.\n\n"
                                f"🔹 **Current Cost:** ${self.total_cost:.2f}\n"
                                f"🔹 **Ceiling:** ${self.ceiling_usd:.2f}"
                            )
                        
                        self._notify_fn(message)
                        log.info(f"Fired cost alert for {percentage}% threshold.")
                    
                    # Once we fire the highest applicable alert, we stop.
                    # This prevents spamming notifications for 50%, 75%, etc. on a single API call.
                    break
        except Exception as e:
            log.error(f"Failed to check budget and send notification: {e}", exc_info=True)

    def persist_session(self, log_dir: Path):
        """Saves the current session's cost data to a JSON file."""
        try:
            if not log_dir.exists():
                log_dir.mkdir(parents=True, exist_ok=True)

            # Sanitize timestamp for filename
            sanitized_ts = self.session_start.replace(':', '-').replace('+', '_').split('.')[0]
            log_file = log_dir / f"cost_session_{sanitized_ts}.json"

            session_data = {
                "session_start": self.session_start,
                "session_end": datetime.now(timezone.utc).isoformat(),
                "ceiling_usd": self.ceiling_usd,
                "total_cost_usd": self.total_cost,
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
                "total_api_calls": self.calls,
                "records": [rec.__dict__ for rec in self.records],
            }

            with open(log_file, "w") as f:
                json.dump(session_data, f, indent=2)

            log.info(f"Cost session data saved to {log_file}")
        except Exception as e:
            log.error(f"Failed to persist cost session data: {e}", exc_info=True)
```