"""Cost tracking functions for memory/shared/costs/ persistence.

Reads and writes JSONL files named by date (e.g., 2026-03-15.jsonl).
Each line is a JSON object with: timestamp, agent, model, action,
input_tokens, output_tokens, cost_usd.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("foreman.brain.costs")


def load_today_spend(costs_dir: Path) -> float:
    """Sum today's cost entries. Returns 0.0 if no file exists."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cost_file = costs_dir / f"{today}.jsonl"
    if not cost_file.exists():
        return 0.0
    total = 0.0
    for line in cost_file.read_text().strip().split("\n"):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            total += entry.get("cost_usd", 0.0)
        except json.JSONDecodeError:
            log.warning(f"Skipping malformed cost entry: {line}")
    return total


def load_today_cycles(costs_dir: Path) -> int:
    """Count completed cycles today by counting 'council' action entries."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cost_file = costs_dir / f"{today}.jsonl"
    if not cost_file.exists():
        return 0
    count = 0
    for line in cost_file.read_text().strip().split("\n"):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            if entry.get("action") == "council":
                count += 1
        except json.JSONDecodeError:
            log.warning(f"Skipping malformed cost entry: {line}")
    return count


def append_cost_entry(
    costs_dir: Path,
    agent: str,
    model: str,
    action: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
) -> None:
    """Append a cost entry to today's JSONL file."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cost_file = costs_dir / f"{today}.jsonl"
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": agent,
        "model": model,
        "action": action,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
    }
    with cost_file.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    log.info(f"Cost logged: {agent}/{action} ${cost_usd:.4f} ({model})")
