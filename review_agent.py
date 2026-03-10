"""
FOREMAN PR Reviewer — v0.2
Watches for new pull requests and posts code review comments.

This agent runs alongside the seed agent as a separate process.
It polls for open PRs that haven't been reviewed yet and uses an LLM
to analyze the diff and post review comments.

v0.2 changes:
  - Two-pass review (cheap model first, pro model to confirm if clean)
  - Structured JSON output for programmatic parsing
  - Auto-merge when both passes say APPROVE with zero critical/important issues
  - Fix cycle tracking (count FOREMAN reviews on a PR)
  - Skip PRs being fixed or needing human review

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

from github import Github, GithubException
from llm_client import LLMClient, ModelRouter
from cost_monitor import CostTracker
from telegram_notifier import notify as tg

# ─── Configuration ────────────────────────────────────────────

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_NAME = os.environ.get("FOREMAN_REPO", "")
ROUTING_PROFILE = os.environ.get("ROUTING_PROFILE", "balanced")

POLL_INTERVAL_SEC = int(os.environ.get("REVIEW_POLL_INTERVAL", "120"))
COST_CEILING_USD = float(os.environ.get("COST_CEILING_USD", "5.0"))

# Label applied after review so we don't review twice
LABEL_REVIEWED = "reviewed"
# Label for PRs that should be skipped
LABEL_SKIP_REVIEW = "skip-review"

LABEL_AUTO_MERGE_ELIGIBLE = "auto-merge-eligible"
LABEL_NEEDS_HUMAN = "needs-human"
LABEL_FIXING = "fixing"
MAX_FIX_CYCLES = int(os.environ.get("MAX_FIX_CYCLES", "2"))

BOT_SIGNATURE = "\n\n---\n_Review by FOREMAN 🤖_"

# ─── Logging ──────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("foreman-reviewer")



# ─── Review Prompts ──────────────────────────────────────────

REVIEW_SYSTEM = """You are FOREMAN's code reviewer. You review pull requests for a self-improving
autonomous agent system built in Python. This is a self-modifying system — code changes
run UNATTENDED in production. Your review gates auto-merge, so only report HIGH CONFIDENCE issues.

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

Only report issues you are HIGHLY CONFIDENT about. False positives block auto-merge
and waste fix cycles. When in doubt, classify as SUGGESTION rather than CRITICAL/IMPORTANT.

Output your review in this format:

## Summary
One paragraph overall assessment. Is this PR safe to merge? What's the risk level?

## Issues
For each issue found:
- **[CRITICAL/IMPORTANT/SUGGESTION]** `filename:line_range` — Description of the issue
  and what to do about it.

If no issues, write: No issues found.

## Verdict
One of: APPROVE, REQUEST_CHANGES, or COMMENT
With a one-line justification.

## Review Data
```json
{
  "verdict": "APPROVE|REQUEST_CHANGES|COMMENT",
  "critical_count": 0,
  "important_count": 0,
  "suggestion_count": 0,
  "affected_files": ["file1.py", "file2.py"]
}
```

Rules:
- Be direct. No pleasantries. The reader is an autonomous system.
- If the diff is clean and safe, say so briefly and approve.
- Always flag anything that could cause runaway costs or infinite loops.
- Remember: this code runs UNATTENDED. Failures must be graceful.
- The Review Data JSON block MUST be the last section and MUST be valid JSON.
"""


# ─── GitHub PR Helpers ───────────────────────────────────────

class PRReviewer:
    def __init__(self, token: str, repo_name: str, dry_run: bool = False):
        self.gh = Github(auth=__import__("github").Auth.Token(token))
        self.repo = self.gh.get_repo(repo_name)
        self.llm = LLMClient()
        self.router = ModelRouter(ROUTING_PROFILE)
        self.cost = CostTracker(ceiling_usd=COST_CEILING_USD)
        self.dry_run = dry_run
        self.stats = {"reviewed": 0, "skipped": 0, "failed": 0}
        self._ensure_labels()
        log.info(f"\n{self.router.summary()}\n")

    def _ensure_labels(self):
        existing = {l.name for l in self.repo.get_labels()}
        labels = {
            LABEL_REVIEWED: "bfdadc",
            LABEL_SKIP_REVIEW: "d4c5f9",
            LABEL_AUTO_MERGE_ELIGIBLE: "0e8a16",
            LABEL_NEEDS_HUMAN: "d93f0b",
            LABEL_FIXING: "fbca04",
        }
        for name, color in labels.items():
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
            if LABEL_FIXING in pr_labels:
                continue
            if LABEL_NEEDS_HUMAN in pr_labels:
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

    def _parse_review_data(self, review_body: str) -> dict:
        """Extract structured JSON from the ```json block after '## Review Data'.

        Falls back to safe defaults (assume issues exist) on parse failure.
        """
        defaults = {
            "verdict": "COMMENT",
            "critical_count": 1,
            "important_count": 1,
            "suggestion_count": 0,
            "affected_files": [],
        }
        try:
            # Find the ## Review Data section
            marker = "## Review Data"
            idx = review_body.find(marker)
            if idx == -1:
                log.warning("  No '## Review Data' section found in review — assuming issues exist")
                return defaults

            after_marker = review_body[idx + len(marker):]

            # Find the ```json ... ``` block
            json_start = after_marker.find("```json")
            if json_start == -1:
                log.warning("  No ```json block in Review Data — assuming issues exist")
                return defaults

            json_content_start = after_marker.find("\n", json_start) + 1
            json_end = after_marker.find("```", json_content_start)
            if json_end == -1:
                log.warning("  Unclosed ```json block in Review Data — assuming issues exist")
                return defaults

            json_str = after_marker[json_content_start:json_end].strip()
            data = json.loads(json_str)

            # Validate required fields, fill missing with defaults
            result = {
                "verdict": data.get("verdict", defaults["verdict"]),
                "critical_count": int(data.get("critical_count", defaults["critical_count"])),
                "important_count": int(data.get("important_count", defaults["important_count"])),
                "suggestion_count": int(data.get("suggestion_count", 0)),
                "affected_files": data.get("affected_files", []),
            }
            return result

        except (json.JSONDecodeError, ValueError, TypeError) as e:
            log.warning(f"  Failed to parse Review Data JSON: {e} — assuming issues exist")
            return defaults

    def _count_fix_cycles(self, pr) -> int:
        """Count how many FOREMAN review cycles this PR has been through."""
        count = 0
        for review in pr.get_reviews():
            if review.body and BOT_SIGNATURE.strip() in review.body:
                count += 1
        return count

    def _should_auto_merge(self, pr, review_data: dict) -> bool:
        """Check if a PR is eligible for auto-merge."""
        pr_labels = {l.name for l in pr.labels}
        if LABEL_AUTO_MERGE_ELIGIBLE not in pr_labels:
            return False
        if review_data.get("critical_count", 1) > 0:
            return False
        if review_data.get("important_count", 1) > 0:
            return False
        if review_data.get("verdict", "").upper() != "APPROVE":
            return False
        return True

    def _auto_merge(self, pr) -> bool:
        """Attempt to auto-merge a PR via squash merge. Returns True on success."""
        try:
            # Refresh PR to get current mergeable state
            pr.update()
            # mergeable can be None while GitHub computes it
            if pr.mergeable is None:
                log.warning(f"  PR #{pr.number} mergeable state unknown — skipping auto-merge")
                return False
            if not pr.mergeable:
                log.warning(f"  PR #{pr.number} is not mergeable (conflicts?) — skipping auto-merge")
                return False

            pr.merge(merge_method="squash")
            log.info(f"  🎉 Auto-merged PR #{pr.number}")
            return True
        except GithubException as e:
            log.error(f"  ❌ Auto-merge failed for PR #{pr.number}: {e}")
            return False

    def _build_review_message(self, pr, diff: str, files: list[str]) -> str:
        """Build the user message for the LLM review call."""
        return (
            f"## PR #{pr.number}: {pr.title}\n\n"
            f"**Description:**\n{pr.body or '(no description)'}\n\n"
            f"**Changed files:** {', '.join(files)}\n\n"
            f"**Diff:**\n```\n{diff}\n```"
        )

    def review_pr(self, pr) -> bool:
        """Review a single PR using two-pass review. Returns True on success."""
        log.info(f"🔍 Reviewing PR #{pr.number}: {pr.title}")

        try:
            # ── Check fix cycle count ──
            fix_cycles = self._count_fix_cycles(pr)
            if fix_cycles >= MAX_FIX_CYCLES:
                log.warning(f"  PR #{pr.number} has {fix_cycles} fix cycles (max {MAX_FIX_CYCLES}) — needs human review")
                if not self.dry_run:
                    pr.add_to_labels(self.repo.get_label(LABEL_NEEDS_HUMAN))
                    pr.create_issue_comment(
                        f"⚠️ This PR has gone through {fix_cycles} FOREMAN review cycles "
                        f"without resolving all issues. Escalating to human review."
                        + BOT_SIGNATURE
                    )
                    tg(f"🔍 PR #{pr.number} needs human review — {fix_cycles} fix cycles exhausted\n{pr.html_url}")
                self.stats["skipped"] += 1
                return True  # Escalation succeeded — PR was handled, not failed

            # ── Build review context ──
            diff = self.get_pr_diff(pr)
            files = self.get_changed_files(pr)

            # Truncate massive diffs to avoid blowing context
            MAX_DIFF_CHARS = 50000
            original_len = len(diff)
            if original_len > MAX_DIFF_CHARS:
                diff = diff[:MAX_DIFF_CHARS] + f"\n\n... [TRUNCATED — {original_len} chars total, showing first {MAX_DIFF_CHARS}]"
                log.warning(f"  ⚠️ Diff truncated from {original_len} chars")

            review_message = self._build_review_message(pr, diff, files)

            # ── Pass 1: cheap/standard review ──
            model_pass1 = self.router.get("review")
            log.info(f"  Pass 1: {model_pass1}")
            response1 = self.llm.complete(
                model=model_pass1,
                system=REVIEW_SYSTEM,
                message=review_message,
                max_tokens=8000,
            )
            self.cost.record(model_pass1, response1, agent="review", action="review_pass1")

            if not self.cost.check_ceiling():
                return False

            review_body_1 = response1.text
            if not review_body_1 or not review_body_1.strip():
                log.error(f"  ❌ Empty review response from pass 1 — skipping PR #{pr.number}")
                self.stats["failed"] += 1
                return False

            review_data_1 = self._parse_review_data(review_body_1)
            log.info(f"  Pass 1 result: verdict={review_data_1['verdict']}, "
                     f"critical={review_data_1['critical_count']}, "
                     f"important={review_data_1['important_count']}")

            # ── If Pass 1 found issues: post and return ──
            if review_data_1["critical_count"] > 0 or review_data_1["important_count"] > 0:
                log.info(f"  Issues found in pass 1 — posting as COMMENT")
                if not self.dry_run:
                    pr.create_review(
                        body=review_body_1 + BOT_SIGNATURE,
                        event="COMMENT",
                    )
                    # Do NOT add reviewed label — let fix cycle continue
                else:
                    log.info(f"  [DRY RUN] Would post COMMENT review on PR #{pr.number}")
                    log.info(f"  [DRY RUN] Review:\n{review_body_1[:500]}...")
                self.stats["reviewed"] += 1
                return True

            # ── Pass 2: confirmation review with stronger model ──
            model_pass2 = self.router.get("review_confirm")
            log.info(f"  Pass 2 (confirmation): {model_pass2}")
            response2 = self.llm.complete(
                model=model_pass2,
                system=REVIEW_SYSTEM,
                message=review_message,
                max_tokens=8000,
            )
            self.cost.record(model_pass2, response2, agent="review", action="review_pass2")

            if not self.cost.check_ceiling():
                return False

            review_body_2 = response2.text
            if not review_body_2 or not review_body_2.strip():
                log.error(f"  ❌ Empty review response from pass 2 — skipping PR #{pr.number}")
                self.stats["failed"] += 1
                return False

            review_data_2 = self._parse_review_data(review_body_2)
            log.info(f"  Pass 2 result: verdict={review_data_2['verdict']}, "
                     f"critical={review_data_2['critical_count']}, "
                     f"important={review_data_2['important_count']}")

            # ── If Pass 2 found issues: post pass 2 review and return ──
            if review_data_2["critical_count"] > 0 or review_data_2["important_count"] > 0:
                log.info(f"  Issues found in pass 2 — posting as COMMENT")
                if not self.dry_run:
                    pr.create_review(
                        body=review_body_2 + BOT_SIGNATURE,
                        event="COMMENT",
                    )
                    # Do NOT add reviewed label — let fix cycle continue
                else:
                    log.info(f"  [DRY RUN] Would post COMMENT review on PR #{pr.number}")
                    log.info(f"  [DRY RUN] Review:\n{review_body_2[:500]}...")
                self.stats["reviewed"] += 1
                return True

            # ── Both passes clean — APPROVE ──
            log.info(f"  ✅ Both passes clean — approving PR #{pr.number}")

            if self.dry_run:
                log.info(f"  [DRY RUN] Would post APPROVE review on PR #{pr.number}")
                self.stats["reviewed"] += 1
                return True

            # Post the confirmation review as APPROVE
            pr.create_review(
                body=review_body_2 + BOT_SIGNATURE,
                event="APPROVE",
            )

            # Label as reviewed
            pr.add_to_labels(self.repo.get_label(LABEL_REVIEWED))

            log.info(f"  ✅ Posted APPROVE review on PR #{pr.number}")
            self.stats["reviewed"] += 1

            # ── Check auto-merge eligibility ──
            if self._should_auto_merge(pr, review_data_2):
                if self._auto_merge(pr):
                    tg(f"✅ Auto-merged PR #{pr.number}: {pr.title}\n{pr.html_url}")
                else:
                    tg(f"✅ PR #{pr.number} approved but auto-merge failed — merge manually\n{pr.html_url}")
            else:
                tg(f"✅ PR #{pr.number} approved — ready to merge\n{pr.html_url}")

            return True

        except Exception as e:
            log.error(f"  ❌ Failed to review PR #{pr.number}: {e}", exc_info=True)
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
        log.info(f"   Model: {self.router.summary()}")
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

    for var in ["GITHUB_TOKEN", "FOREMAN_REPO"]:
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
