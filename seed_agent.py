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
        self.gh = Github(token)
        self.repo = self.gh.get_repo(repo_name)
        self.dry_run = dry_run
        self._ensure_labels()

    def _ensure_labels(self):
        """Ensure all required labels exist in the repo."""
        required_labels = [
            (LABEL_NEEDS_REFINEMENT, "b1e100", "Issue needs to be broken down into a detailed spec"),
            (LABEL_AUTO_REFINED, "0E8A16", "Issue was automatically refined by the agent"),
            (LABEL_REFINED_OUT, "D93F0B", "Original issue that was refined into a new one"),
            (LABEL_DRAFT, "fbca04", "A draft idea, not ready for implementation"),
            (LABEL_READY, "1d76db", "Ready for implementation"),
            (LABEL_IMPLEMENTING, "8474A4", "Currently being implemented by an agent"),
        ]
        if self.dry_run:
            return
        
        try:
            existing_labels = {label.name for label in self.repo.get_labels()}
            for name, color, description in required_labels:
                if name not in existing_labels:
                    log.info(f"Creating label '{name}'")
                    self.repo.create_label(name, color, description)
        except GithubException as e:
            log.error(f"Error ensuring labels: {e}. Check repo permissions.")
            raise

    def find_issue_to_refine(self):
        """Find the oldest open issue with 'needs-refinement' label."""
        try:
            issues = self.repo.get_issues(state="open", labels=[LABEL_NEEDS_REFINEMENT], sort="created", direction="asc")
            for issue in issues:
                labels = {label.name for label in issue.labels}
                if not FORBIDDEN_LABELS.intersection(labels):
                    return issue
            return None
        except GithubException as e:
            log.error(f"Error finding issue to refine: {e}")
            return None

    def get_ready_issue_count(self):
        """Get the count of open issues ready for implementation."""
        try:
            return self.repo.get_issues(state="open", labels=[LABEL_READY]).totalCount
        except GithubException as e:
            log.error(f"Error getting ready issue count: {e}")
            return 0

    def create_issue(self, title: str, body: str, labels: list[str]):
        """Create a new issue on GitHub."""
        log.info(f"Creating issue '{title}' with labels {labels}")
        if self.dry_run:
            log.warning("DRY RUN: Issue creation skipped.")
            # Return a mock object with an html_url for notification testing
            class MockIssue:
                number = 0
                html_url = "https://github.com/mock/issue"
                title = title
            return MockIssue()
        try:
            return self.repo.create_issue(title=title, body=body, labels=labels)
        except GithubException as e:
            log.error(f"Error creating issue: {e}")
            return None

    def close_issue(self, issue, comment: str):
        """Add a comment and close an issue."""
        log.info(f"Closing issue #{issue.number} with comment.")
        if self.dry_run:
            log.warning("DRY RUN: Issue closing skipped.")
            return
        try:
            if comment:
                issue.create_comment(comment)
            issue.edit(state="closed")
        except GithubException as e:
            log.error(f"Error closing issue #{issue.number}: {e}")

    def add_labels(self, issue, labels: list[str]):
        """Add labels to an existing issue."""
        log.info(f"Adding labels {labels} to issue #{issue.number}")
        if self.dry_run or issue.number == 0: # also check for mock issue
            log.warning("DRY RUN: Adding labels skipped.")
            return
        try:
            issue.add_to_labels(*labels)
        except GithubException as e:
            log.error(f"Error adding labels to issue #{issue.number}: {e}")

def run_refine_pass(client: GitHubClient, llm: LLMClient, notifier: TelegramNotifier):
    log.info("🕵️  Starting refine pass...")
    try:
        issue = client.find_issue_to_refine()
        if not issue:
            log.info("✅ No issues found to refine.")
            return

        log.info(f"Found issue to refine: #{issue.number} {issue.title}")
        refined_spec_json = llm.refine_issue(issue.title, issue.body)
        if not refined_spec_json:
            log.error("LLM did not return a valid spec. Skipping.")
            return

        refined_spec = json.loads(refined_spec_json)
        log.info(f"📝 LLM refined issue into: '{refined_spec['title']}'")
        
        new_issue = client.create_issue(
            title=refined_spec['title'],
            body=refined_spec['body'],
            labels=[LABEL_AUTO_REFINED, LABEL_READY]
        )
        
        if new_issue:
            log.info(f"✅ Successfully created new refined issue #{new_issue.number}")
            client.add_labels(issue, [LABEL_REFINED_OUT])
            client.close_issue(issue, f"Refined into #{new_issue.number}")
            
            message = (
                f"✅ *Issue Refined*\n\n"
                f"*[#{new_issue.number} {new_issue.title}]({new_issue.html_url})*\n\n"
                f"Original: `#{issue.number} {issue.title}`"
            )
            notifier.send_message(message, parse_mode="MarkdownV2")
        
    except json.JSONDecodeError as e:
        log.error(f"Error decoding LLM response for refinement: