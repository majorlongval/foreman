"""
FOREMAN PR Reviewer — v0.1
Watches for new pull requests and posts code review comments.

This agent runs alongside the seed agent as a separate process.
It polls for open PRs that haven't been reviewed yet and uses Claude
to analyze the diff and post review comments.

Usage:
  python review_agent.py                # Run the loop
  python review_agent.py --once         # Single pass then exit
  python review_agent.py --dry-run      # Log without posting comments
"""

import os
import sys
import time
import json
import logging
import argparse
from datetime import datetime, timezone

import anthropic
from github import Github, GithubException

# ─── Configuration ────────────────────────────────────────────

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
REPO_NAME = os.environ.get("FOREMAN_REPO", "")

POLL_INTERVAL_SEC = int(os.environ.get("REVIEW_POLL_INTERVAL", "120"))
MODEL_REVIEW = os.environ.get("MODEL_REVIEW", "claude-sonnet-4-20250514")
COST_CEILING_USD = float(os.environ.get("COST_CEILING_USD", "5.0"))

# Label applied after review so we don't review twice
LABEL_REVIEWED = "foreman-reviewed"
# Label for PRs that should be skipped
LABEL_SKIP_REVIEW = "skip-review"

BOT_SIGNATURE = "\n\n---\n_Review by FOREMAN 🤖_"

# ─── Logging ──────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("foreman-reviewer")

# ─── Cost Tracking (shared pattern with seed_agent) ──────────

class CostTracker:
    PRICING = {
        "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
        "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
        "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
    }

    def __init__(self, ceiling_usd: float):
        self.ceiling = ceiling_usd
        self.total_cost = 0.0
        self.calls = 0

    def record(self, model: str, usage) -> float:
        pricing = self.PRICING.get(model, {"input": 3.0, "output": 15.0})
        cost = (usage.input_tokens * pricing["input"] + usage.output_tokens * pricing["output"]) / 1_000_000
        self.total_cost += cost
        self.calls += 1
        log.info(f"  💰 ${cost:.4f} | Session: ${self.total_cost:.4f} / ${self.ceiling:.2f}")
        return cost

    def check_ceiling(self) -> bool:
        if self.total_cost >= self.ceiling:
            log.warning(f"🚨 COST CEILING: ${self.total_cost:.4f} >= ${self.ceiling:.2f}")
            return False
        return True

    def summary(self) -> str:
        return f"Session: {self.calls} calls, ${self.total_cost:.4f}"


# ─── Review Prompts ──────────────────────────────────────────

REVIEW_SYSTEM = """You are FOREMAN's code reviewer. You review pull requests for a self-improving
autonomous agent system built in Python.

You will receive:
1. The PR title and description
2. The full diff
3. A list of changed files

Your job is to provide a thorough but concise code review. Focus on:

**Critical (must fix before merge):**
- Bugs, logic errors, or race conditions
- Security issues (exposed secrets, injection risks)
- Infinite loop risks (especially important — this is a self-modifying system)
- Missing error handling that could crash the agent loop
- Cost control issues (unbounded API calls, missing cost checks)

**Important (should fix):**
- Missing safety rails or guard clauses
- Poor error messages that would make debugging hard in autonomous mode
- Hardcoded values that should be configurable
- Missing logging (the agent runs unattended, logs are critical)

**Suggestions (nice to have):**
- Code clarity and naming
- Performance improvements
- Test coverage gaps
- Documentation

Output your review in this format:

## Summary
One paragraph overall assessment. Is this PR safe to merge? What's the risk level?

## Issues
For each issue found:
- **[CRITICAL/IMPORTANT/SUGGESTION]** `filename:line_range` — Description of the issue
  and what to do about it.

## Verdict
One of: APPROVE, REQUEST_CHANGES, or COMMENT
With a one-line justification.

Rules:
- Be direct. No pleasantries. The reader is an autonomous system.
- If the diff is clean and safe, say so briefly and approve.
- Always flag anything that could cause runaway costs or infinite loops.
- Remember: this code runs UNATTENDED. Failures must be graceful.
"""


# ─── GitHub PR Helpers ───────────────────────────────────────

class PRReviewer:
    def __init__(self, token: str, repo_name: str, dry_run: bool = False):
        self.gh = Github(token)
        self.repo = self.gh.get_repo(repo_name)
        self.claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.cost = CostTracker(COST_CEILING_USD)
        self.dry_run = dry_run
        self.stats = {"reviewed": 0, "skipped": 0, "failed": 0}
        self._ensure_labels()

    def _ensure_labels(self):
        existing = {l.name for l in self.repo.get_labels()}
        for name, color in {LABEL_REVIEWED: "bfdadc", LABEL_SKIP_REVIEW: "d4c5f9"}.items():
            if name not in existing:
                if not self.dry_run:
                    self.repo.create_label(name=name, color=color)

    def get_review_queue(self) -> list:
        """Get open PRs that haven't been reviewed by FOREMAN yet."""
        pulls = self.repo.get_pulls(state="open", sort="created", direction="asc")
        queue = []
        for pr in pulls:
            pr_labels = {l.name for l in pr.labels}
            if LABEL_REVIEWED in pr_labels:
                continue
            if LABEL_SKIP_REVIEW in pr_labels:
                continue
            queue.append(pr)
        return queue

    def get_pr_diff(self, pr) -> str:
        """Get the full diff for a PR."""
        files = pr.get_files()
        diff_parts = []
        for f in files:
            header = f"--- a/{f.filename}\n+++ b/{f.filename}\n"
            patch = f.patch or "(binary or empty)"
            diff_parts.append(f"{header}{patch}")
        return "\n\n".join(diff_parts)

    def get_changed_files(self, pr) -> list[str]:
        """Get list of changed file paths."""
        return [f.filename for f in pr.get_files()]

    def review_pr(self, pr) -> bool:
        """Review a single PR. Returns True on success."""
        log.info(f"🔍 Reviewing PR #{pr.number}: {pr.title}")

        try:
            diff = self.get_pr_diff(pr)
            files = self.get_changed_files(pr)

            # Truncate massive diffs to avoid blowing context
            MAX_DIFF_CHARS = 50000
            if len(diff) > MAX_DIFF_CHARS:
                diff = diff[:MAX_DIFF_CHARS] + f"\n\n... [TRUNCATED — {len(diff)} chars total, showing first {MAX_DIFF_CHARS}]"
                log.warning(f"  ⚠️ Diff truncated from {len(diff)} chars")

            response = self.claude.messages.create(
                model=MODEL_REVIEW,
                max_tokens=3000,
                system=REVIEW_SYSTEM,
                messages=[{
                    "role": "user",
                    "content": (
                        f"## PR #{pr.number}: {pr.title}\n\n"
                        f"**Description:**\n{pr.body or '(no description)'}\n\n"
                        f"**Changed files:** {', '.join(files)}\n\n"
                        f"**Diff:**\n```\n{diff}\n```"
                    ),
                }],
            )
            self.cost.record(MODEL_REVIEW, response.usage)

            if not self.cost.check_ceiling():
                return False

            review_body = response.content[0].text

            # Determine review event type from verdict
            event = "COMMENT"  # default
            verdict_lower = review_body.lower()
            if "verdict" in verdict_lower:
                if "approve" in verdict_lower.split("verdict")[-1][:100]:
                    event = "APPROVE"
                elif "request_changes" in verdict_lower.split("verdict")[-1][:100]:
                    event = "REQUEST_CHANGES"

            if self.dry_run:
                log.info(f"  [DRY RUN] Would post {event} review on PR #{pr.number}")
                log.info(f"  [DRY RUN] Review:\n{review_body[:500]}...")
                self.stats["reviewed"] += 1
                return True

            # Post the review
            pr.create_review(
                body=review_body + BOT_SIGNATURE,
                event=event,
            )

            # Label as reviewed so we don't hit it again
            pr.add_to_labels(self.repo.get_label(LABEL_REVIEWED))

            log.info(f"  ✅ Posted {event} review on PR #{pr.number}")
            self.stats["reviewed"] += 1
            return True

        except Exception as e:
            log.error(f"  ❌ Failed to review PR #{pr.number}: {e}")
            self.stats["failed"] += 1
            return False

    def run_once(self) -> dict:
        log.info("=" * 60)
        log.info(f"🔄 FOREMAN reviewer @ {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")

        if not self.cost.check_ceiling():
            log.warning("💤 Parked — cost ceiling reached")
            return self.stats

        queue = self.get_review_queue()
        log.info(f"📋 PR review queue: {len(queue)} PRs")

        for pr in queue:
            self.review_pr(pr)
            if not self.cost.check_ceiling():
                break
            time.sleep(5)  # Be nice

        log.info(f"📊 Stats: {self.stats}")
        log.info(f"💰 {self.cost.summary()}")
        return self.stats

    def run_loop(self):
        log.info("🚀 FOREMAN PR reviewer starting")
        log.info(f"   Repo: {REPO_NAME}")
        log.info(f"   Poll interval: {POLL_INTERVAL_SEC}s")
        log.info(f"   Model: {MODEL_REVIEW}")
        log.info(f"   Dry run: {self.dry_run}")

        try:
            while True:
                self.run_once()
                log.info(f"💤 Sleeping {POLL_INTERVAL_SEC}s...")
                time.sleep(POLL_INTERVAL_SEC)
        except KeyboardInterrupt:
            log.info("\n🛑 Reviewer stopped")
            log.info(f"📊 Final: {self.stats}")
            log.info(f"💰 {self.cost.summary()}")


# ─── CLI ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="FOREMAN PR Reviewer")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    for var in ["GITHUB_TOKEN", "ANTHROPIC_API_KEY", "FOREMAN_REPO"]:
        if not os.environ.get(var):
            log.error(f"❌ {var} not set")
            sys.exit(1)

    reviewer = PRReviewer(GITHUB_TOKEN, REPO_NAME, dry_run=args.dry_run)

    if args.once:
        reviewer.run_once()
    else:
        reviewer.run_loop()


if __name__ == "__main__":
    main()
