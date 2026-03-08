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
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dataclasses import dataclass, field

log = logging.getLogger("foreman.costs")

# ─── API Cost Tracking ───────────────────────────────────────

# Pricing per 1M tokens (update as needed)
MODEL_PRICING = {
    "claude-sonnet-4-20250514":  {"input": 3.0,  "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
    "claude-opus-4-20250514":    {"input": 15.0, "output": 75.0},
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
    _notify_fn: object = None

    def set_