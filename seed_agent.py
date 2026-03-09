"""
FOREMAN Seed Agent — v0.1
The smallest unit that can work on itself.

Modes:
  REFINE     — Rewrites issues labeled 'needs-refinement' into structured specs
  BRAINSTORM — Generates new draft issues from VISION.md when pipeline is dry

Usage:
  python seed_agent.py                    # Run the loop
  python seed_agent.py --once             # Single pass then exit
  python seed_agent.py --brainstorm-only  # Force brainstorm mode
  python seed_agent.py --dry-run          # Log actions without touching GitHub
"""

import os
import sys
import time
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime, timezone

from github import Github, GithubException
from github.Issue import Issue

# ─── Configuration ────────────────────────────────────────────

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_NAME = os.environ.get("FOREMAN_REPO", "")  # e.g. "jordanuser/foreman"

# Agent behavior
POLL_INTERVAL_SEC = int(os.environ.get("POLL_INTERVAL", "60"))
BRAINSTORM_THRESHOLD = int(os.environ.get("BRAINSTORM_THRESHOLD", "2"))
BRAINSTORM_MAX_DRAFTS = int(os.environ.get("BRAINSTORM_MAX_DRAFTS", "5"))
COST_CEILING_USD = float(os.environ.get("COST_CEILING_USD", "5.0"))

# Routing profile: "cheap", "balanced", or "quality"
ROUTING_PROFILE = os.environ.get("ROUTING_PROFILE", "balanced")

# Optional Telegram Notifications
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Labels
LABEL_NEEDS_REFINEMENT = "needs-refinement"
LABEL_AUTO_REFINED = "auto-refined"
LABEL_REFINED_OUT = "refined-out"  # closed originals that spawned a refined version
LABEL_DRAFT = "draft"
LABEL_READY = "ready"  # refined and ready for implementation

# Safety: labels we NEVER process through the refine pipeline
LABEL_IMPLEMENTING = "foreman-implementing"
FORBIDDEN_LABELS = {LABEL_AUTO_REFINED, LABEL_REFINED_OUT, LABEL_DRAFT, LABEL_READY, LABEL_IMPLEMENTING}

# ─── Logging ──────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("foreman")

# ─── Cost Tracking & LLM ─────────────────────────────────────

from cost_monitor import CostTracker, CloudCostMonitor, create_cost_system
from llm_client import LLMClient, ModelRouter
from telegram_notifier import TelegramNotifier


# ─── Vision Loader ───────────────────────────────────────────

def load_vision() -> str:
    """Load VISION.md from repo root or local fallback."""
    paths = [
        Path(__file__).parent / "VISION.md",
        Path.cwd() / "VISION.md",
    ]
    for p in paths:
        if p.exists():
            log.info(f"📖 Loaded VISION.md from {p}")
            return p.read_text()
    log.warning("⚠️  VISION.md not found, brainstorm mode will be limited")
    return ""


# ─── GitHub Helpers ──────────────────────────────────────────

class GitHubClient:
    def __init__(self, token: str, repo_name: str, dry_run: bool = False):
        if not token or not repo_name:
            log.error("❌ GITHUB_TOKEN and FOREMAN_REPO must be set.")
            sys.exit(1)
        self.g = Github(token)
        self.repo = self.g.get_repo(repo_name)
        self.dry_run = dry_run
        log.info(f"🛠️ GitHub client initialized for repo '{repo_name}'")
        if self.dry_run:
            log.warning("🌵 Dry run mode enabled. No changes will be made to GitHub.")

    def find_issues(self, labels: list[str], state: str = "open", exclude_labels: set[str] | None = None) -> list[Issue]:
        """Find issues with a given set of labels, excluding others."""
        try:
            issues = self.repo.get_issues(state=state, labels=labels)
            filtered_issues = []
            for issue in issues:
                issue_labels = {label.name for label in issue.labels}
                if exclude_labels and not issue_labels.isdisjoint(exclude_labels):
                    continue
                filtered_issues.append(issue)
            return list(filtered_issues)
        except GithubException as e:
            log.error(f"GitHub API error while finding issues: {e}")
            return []

    def create_issue(self, title: str, body: str, labels: list[str]) -> Issue | None:
        """Create a new issue."""
        log.info(f"Creating issue: '{title}' with labels: {labels}")
        if self.dry_run:
            log.info("[DRY RUN] Would create issue.")
            # Return a mock object that has a `number` and `html_url` for logging
            class MockIssue:
                number = 0
                html_url = "https://github.com/mock/issue"
                title = title
                def edit(self, *args, **kwargs): pass
                def create_comment(self, *args, **kwargs): pass
            return MockIssue()
        try:
            return self.repo.create_issue(title