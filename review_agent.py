"""
FOREMAN PR Reviewer — v0.2
Watches for new pull requests and posts code review comments.
This agent runs alongside the seed agent as a separate process.
It polls for open PRs that haven't been reviewed yet and uses an LLM
to analyze the diff and post review comments.

Usage:
  python review_agent.py                # Run the loop
  python review_agent.py --once         # Single pass then exit
  python review_agent.py --dry-run      # Log without posting comments
  python review_agent.py --cost-summary # Display daily API cost summary
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

LABEL_REVIEWED = "reviewed"
LABEL_SKIP_REVIEW = "skip-review"
LABEL_AUTO_MERGE_ELIGIBLE = "auto-merge-eligible"
LABEL_NEEDS_HUMAN = "needs-human"
LABEL_FIXING = "fixing"

MAX_FIX_CYCLES = int(os.environ.get("MAX_FIX_CYCLES", "3"))
CONFIDENCE_HIGH = int(os.environ.get("CONFIDENCE_HIGH", "80"))
CONFIDENCE_MEDIUM = int(os.environ.get("CONFIDENCE_MEDIUM", "50"))

BOT_SIGNATURE = "\n\n---\n_Review by FOREMAN 🤖_"

# ─── Logging ──────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("foreman-reviewer")


def get_coding_standards() -> str:
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "STANDARDS.md")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
    except Exception as e:
        log.error(f"Error reading STANDARDS.md: {e}")
    return "No specific coding standards provided."


# ─── Review Prompts ──────────────────────────────────────────

REVIEW_SYSTEM = f"""You are FOREMAN's code reviewer. You review pull requests for a self-improving
autonomous agent system built in Python. This is a self-modifying system — code changes
run UNATTENDED in production. Your review gates auto-merge, so only report HIGH CONFIDENCE issues.

Coding Standards to Enforce:
{get_coding_standards()}

You MUST cite specific rules from the coding standards when suggesting changes.

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
- **[CRITICAL/IMPORTANT/SUGGESTION]** `filename:line_range` — Description of the issue.
  **Suggested fix:**
  ```python
  # exact replacement code here
  ```

If no issues, write: No issues found.

## Verdict
One of: APPROVE, REQUEST_CHANGES, or COMMENT
With a one-line justification.

## Review Data
```json
{{
  "verdict": "APPROVE|REQUEST_CHANGES|COMMENT",
  "confidence_score": 0-100,
  "critical_count": 0,
  "important_count": 0,
  "suggestion_count": 0,
  "affected_files": ["file1.py", "file2.py"]
}}
```

Rules:
- Be direct. No pleasantries. The reader is an autonomous system.
- If the diff is clean and safe, say so briefly and approve.
- Always flag anything that could cause runaway costs or infinite loops.
- Remember: this code runs UNATTENDED. Failures must be graceful.
- ALWAYS include a concrete "Suggested fix" code block for every CRITICAL and IMPORTANT issue.
  The fixer is a dumb model that will apply your suggestions literally — be precise and complete.
- The Review Data JSON block MUST be the last section and MUST be valid JSON.
- `confidence_score`: 0-100. High (80+) if the PR is straightforward and issues are certain. Low (<50) if the code is complex, the diff is large, or you are unsure about the severity of found issues.
- BE EXHAUSTIVE. Find ALL critical and important issues in this single pass. The fix/review
  loop costs real money — discovering new issues round by round is expensive. If prior reviews
  exist, first verify each prior critical is resolved, then scan the full diff for any
  remaining issues. Do not hold issues back for future rounds.
- When prior reviews exist: explicitly state for each prior critical whether it is FIXED or
  STILL PRESENT before listing any new issues.
"""

# ─── GitHub PR Helpers ───────────────────────────────────────

class PRReviewer:
    def __init__(self, token: str, repo_name: str, dry_run: bool = False):
        self.gh = Github(auth=__import__("github").Auth.Token(token))
        self.repo = self.gh.get_repo(repo_name)
        self.bot_login = self.gh.get_user().login
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
        files = pr.get_files()
        diff_parts = []
        for f in files:
            header = f"--- a/{f.filename}\n+++ b/{f.filename}\n"
            patch = f.patch or "(binary or empty)"
            diff_parts.append(f"{header}{patch}")
        return "\n\n".join(diff_parts)

    def get_changed_files(self, pr) -> list[str]:
        return [f.filename for f in pr.get_files()]

    def _parse_review_data(self, review_body: str) -> dict:
        defaults = {
            "verdict": "COMMENT",
            "confidence_score": 50,
            "critical_count": 0,
            "important_count": 0,
            "suggestion_count": 0,
            "affected_files": [],
        }
        try:
            marker = "## Review Data"
            idx = review_body.find(marker)
            if idx == -1:
                return defaults
            after_marker = review_body[idx + len(marker):]
            json_start = after_marker.find("```json")
            if json_start == -1:
                return defaults
            json_content_start = after_marker.find("\n", json_start) + 1
            json_end = after_marker.find("```", json_content_start)
            if json_end == -1:
                return defaults
            json_str = after_marker[json_content_start:json_end].strip()
            data = json.loads(json_str)
            result = {
                "verdict": data.get("verdict", defaults["verdict"]),
                "confidence_score": int(data.get("confidence_score", defaults["confidence_score"])),
                "critical_count": int(data.get("critical_count", 0)),
                "important_count": int(data.get("important_count", 0)),
                "suggestion_count": int(data.get("suggestion_count", 0)),
                "affected_files": data.get("affected_files", []),
            }
            return result
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            log.warning(f"  ⚠️ Failed to parse review JSON: {e}")
            return defaults

    def _calculate_confidence_score(self, pr, data: dict) -> int:
        """Calculate a confidence score weighted by verdict, severity, and PR size."""
        # LLM reports its own confidence
        llm_score = data.get("confidence_score", 50)
        
        # Penalties
        # Size penalty: -5 points for every 100 lines changed, max -30
        total_changes = (pr.additions or 0) + (pr.deletions or 0)
        size_penalty = min(30, (total_changes // 100) * 5)
        
        # Severity penalty: -15 per critical, -5 per important
        severity_penalty = (data.get("critical_count", 0) * 15) + (data.get("important_count", 0) * 5)
        
        # Verdict penalty
        verdict_penalty = 0
        verdict = data.get("verdict", "").upper()
        if verdict == "REQUEST_CHANGES":
            verdict_penalty = 20
        elif verdict == "COMMENT":
            verdict_penalty = 10
            
        final_score = llm_score - size_penalty - severity_penalty - verdict_penalty
        return max(0, min(100, int(final_score)))

    def _count_fix_cycles(self, pr) -> int:
        count = 0
        for review in pr.get_reviews():
            if review.body and BOT_SIGNATURE.strip() in review.body:
                count += 1
        return count

    def _should_auto_merge(self, pr, review_data: dict, high_confidence: bool = False) -> bool:
        """Check if PR is safe for automated merging."""
        if review_data.get("critical_count", 0) > 0:
            return False
        if review_data.get("important_count", 0) > 0:
            return False
        if review_data.get("verdict", "").upper() != "APPROVE":
            return False

        # AC: High confidence auto-merges regardless of label
        if high_confidence:
            return True

        pr_labels = {l.name for l in pr.labels}
        if LABEL_AUTO_MERGE_ELIGIBLE not in pr_labels:
            return False
        
        return True

    def _auto_merge(self, pr) -> bool:
        try:
            pr.update()
            if pr.mergeable is None or not pr.mergeable:
                log.warning(f"  ⚠️ PR #{pr.number} is not mergeable at this time")
                return False
            pr.merge(merge_method="squash")
            log.info(f"  🎉 Auto-merged PR #{pr.number}")
            return True
        except GithubException as e:
            log.error(f"  ❌ Auto-merge failed for PR #{pr.number}: {e}")
            return False

    def _trigger_fix_agent(self, pr):
        """Trigger the fix agent workflow via GitHub API."""
        try:
            # Assumes a workflow file named fix_agent.yml exists
            workflow = self.repo.get_workflow("fix_agent.yml")
            workflow.create_dispatch(pr.head.ref, {"pr_number": str(pr.number)})
            log.info(f"  📡 Dispatched fix_agent.yml for PR #{pr.number}")
        except Exception as e:
            log.warning(f"  📡 Could not dispatch fix_agent.yml workflow: {e}")

    def _process_review_result(self, pr, body, data) -> bool:
        """Route the review result to merge, human review, or fix agent."""
        # Calculate final confidence score
        raw_score = data.get("confidence_score", 50)
        final_score = self._calculate_confidence_score(pr, data)
        data["confidence_score"] = final_score
        
        verdict = data.get("verdict", "COMMENT").upper()
        log.info(f"  Final Confidence Score: {final_score} (LLM base: {raw_score})")
        log.info(f"  Verdict: {verdict}")

        # Routing logic based on AC
        if final_score > CONFIDENCE_HIGH and verdict == "APPROVE":
            # HIGH CONFIDENCE PATH
            log.info(f"  Routing: HIGH CONFIDENCE")
            if not self.dry_run:
                is_own_pr = pr.user.login == self.bot_login
                event = "COMMENT" if is_own_pr else "APPROVE"
                pr.create_review(body=body + BOT_SIGNATURE, event=event)
                pr.add_to_labels(self.repo.get_label(LABEL_REVIEWED))
                
                if self._should_auto_merge(pr, data, high_confidence=True):
                    if self._auto_merge(pr):
                        tg(f"✅ <b>High Confidence Auto-merge</b>\nPR #{pr.number}: {pr.title}\n{pr.html_url}")
                    else:
                        tg(f"✅ PR #{pr.number} approved but auto-merge failed.\n{pr.html_url}")
                else:
                    tg(f"✅ PR #{pr.number} approved (manual merge required).\n{pr.html_url}")
            self.stats["reviewed"] += 1
            return True

        elif final_score < CONFIDENCE_MEDIUM or verdict == "REQUEST_CHANGES":
            # LOW CONFIDENCE PATH
            log.info(f"  Routing: LOW CONFIDENCE")
            if not self.dry_run:
                # If LLM said REQUEST_CHANGES, use it. Otherwise use COMMENT for automated fixes.
                event = "REQUEST_CHANGES" if verdict == "REQUEST_CHANGES" else "COMMENT"
                pr.create_review(body=body + BOT_SIGNATURE, event=event)
                
                # Check cycle limit
                fix_cycles = self._count_fix_cycles(pr)
                if fix_cycles < MAX_FIX_CYCLES:
                    self._trigger_fix_agent(pr)
                    tg(f"🔧 <b>Low Confidence Review</b>\nPR #{pr.number} (Score: {final_score}) - Triggering automated fixes.\n{pr.html_url}")
                else:
                    pr.add_to_labels(self.repo.get_label(LABEL_NEEDS_HUMAN))
                    tg(f"⚠️ <b>Max Fix Cycles Reached</b>\nPR #{pr.number} requires manual intervention (Score: {final_score}).\n{pr.html_url}")
            self.stats["reviewed"] += 1
            return True

        else:
            # MEDIUM CONFIDENCE PATH (50-80 and not REQUEST_CHANGES)
            log.info(f"  Routing: MEDIUM CONFIDENCE")
            if not self.dry_run:
                pr.create_review(body=body + BOT_SIGNATURE, event="COMMENT")
                pr.add_to_labels(self.repo.get_label(LABEL_NEEDS_HUMAN))
                tg(f"🤔 <b>Medium Confidence Review</b>\nPR #{pr.number} requires human operator attention (Score: {final_score}).\n{pr.html_url}")
            self.stats["reviewed"] += 1
            return True

    def _get_prior_reviews(self, pr) -> list[str]:
        return [
            r.body for r in pr.get_reviews()
            if r.body and BOT_SIGNATURE.strip() in r.body
        ]

    def _already_reviewed_head(self, pr) -> bool:
        head_sha = pr.head.sha
        for r in pr.get_reviews():
            if r.body and BOT_SIGNATURE.strip() in r.body and r.commit_id == head_sha:
                return True
        return False

    def _build_review_message(self, pr, diff: str, files: list[str], prior_reviews: list[str] = None) -> str:
        history = ""
        if prior_reviews:
            formatted = "\n\n---\n".join(
                f"**Round {i+1}:**\n{r}" for i, r in enumerate(prior_reviews)
            )
            history = (
                f"\n\n## Prior Review History\n{formatted}\n\n"
                f"## Your Tasks This Round\n"
                f"1. For each CRITICAL and IMPORTANT issue from prior rounds, explicitly state "
                f"whether it is **FIXED** or **STILL PRESENT** in the current diff.\n"
                f"2. Scan the entire diff for any remaining issues — be exhaustive. "
                f"Do not discover new issues in future rounds."
            )
        return (
            f"## PR #{pr.number}: {pr.title}\n\n"
            f"**Description:**\n{pr.body or '(no description)'}\n\n"
            f"**Changed files:** {', '.join(files)}\n\n"
            f"**Diff:**\n```\n{diff}\n```"
            + history
        )

    def review_pr(self, pr) -> bool:
        log.info(f"🔍 Reviewing PR #{pr.number}: {pr.title}")
        try:
            if self._already_reviewed_head(pr):
                log.info(f"  Already reviewed head commit — skipping")
                self.stats["skipped"] += 1
                return True

            fix_cycles = self._count_fix_cycles(pr)
            if fix_cycles >= MAX_FIX_CYCLES:
                log.info(f"  Max fix cycles ({MAX_FIX_CYCLES}) reached — escalating")
                if not self.dry_run:
                    pr.add_to_labels(self.repo.get_label(LABEL_NEEDS_HUMAN))
                    pr.create_issue_comment(
                        f"⚠️ Escalating to human review. {fix_cycles} fix cycles exhausted."
                        + BOT_SIGNATURE
                    )
                    tg(f"🔍 PR #{pr.number} needs human review — {fix_cycles} fix cycles exhausted\n{pr.html_url}")
                self.stats["skipped"] += 1
                return True

            diff = self.get_pr_diff(pr)
            files = self.get_changed_files(pr)
            prior_reviews = self._get_prior_reviews(pr)

            MAX_DIFF_CHARS = 100000
            if len(diff) > MAX_DIFF_CHARS:
                diff = diff[:MAX_DIFF_CHARS] + f"\n\n... [TRUNCATED]"

            review_message = self._build_review_message(pr, diff, files, prior_reviews=prior_reviews)

            # Pass 1: Analysis
            model_pass1 = self.router.get("review")
            response1 = self.llm.complete(model_pass1, REVIEW_SYSTEM, review_message)
            self.cost.record(model_pass1, response1, agent="review", action="review_pass1")
            
            if not self.cost.check_ceiling(): return False

            review_body_1 = response1.text
            if not review_body_1 or not review_body_1.strip():
                log.error(f"  ❌ Empty review response from pass 1 — skipping PR #{pr.number}")
                self.stats["failed"] += 1
                return False

            review_data_1 = self._parse_review_data(review_body_1)
            
            # If Pass 1 finds problems or is unsure, we route immediately to save costs
            if review_data_1["critical_count"] > 0 or review_data_1["important_count"] > 0 or review_data_1["verdict"] != "APPROVE":
                return self._process_review_result(pr, review_body_1, review_data_1)

            # Pass 2: Confirmation (only if Pass 1 was clean)
            log.info(f"  Pass 1 clean. Running confirmation pass.")
            model_pass2 = self.router.get("review_confirm")
            response2 = self.llm.complete(model_pass2, REVIEW_SYSTEM, review_message)
            self.cost.record(model_pass2, response2, agent="review", action="review_pass2")
            
            if not self.cost.check_ceiling(): return False

            review_body_2 = response2.text
            if not review_body_2 or not review_body_2.strip():
                log.error(f"  ❌ Empty review response from pass 2 — skipping PR #{pr.number}")
                self.stats["failed"] += 1
                return False

            review_data_2 = self._parse_review_data(review_body_2)
            
            # Final routing based on Pass 2 (the confirmation)
            return self._process_review_result(pr, review_body_2, review_data_2)

        except Exception as e:
            log.error(f"  ❌ Failed to review PR #{pr.number}: {e}", exc_info=True)
            self.stats["failed"] += 1
            return False

    def run_once(self) -> dict:
        log.info("=" * 60)
        log.info(f"🔄 FOREMAN reviewer @ {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
        
        if not self.cost.check_ceiling():
            return self.stats

        queue = self.get_review_queue()
        for pr in queue:
            try:
                self.review_pr(pr)
            except Exception as e:
                log.error(f"  ❌ Unhandled exception in PR review loop: {e}")
            
            if not self.cost.check_ceiling():
                break
            time.sleep(5)

        log.info(f"📊 Stats: {self.stats}")
        log.info(f"💰 {self.cost.summary()}")
        return self.stats

    def run_loop(self):
        log.info("🚀 FOREMAN PR reviewer starting")
        try:
            while True:
                self.run_once()
                time.sleep(POLL_INTERVAL_SEC)
        except KeyboardInterrupt:
            log.info("\n🛑 Reviewer stopped")
        except Exception as e:
            log.critical(f"CRITICAL: Reviewer loop crashed: {e}", exc_info=True)


def main():
    parser = argparse.ArgumentParser(description="FOREMAN PR Reviewer")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cost-summary", action="store_true", help="Display daily API cost summary")
    args = parser.parse_args()

    # Handle cost summary request
    if args.cost_summary:
        try:
            from cost_monitor import print_daily_summary
            print_daily_summary()
        except Exception as e:
            log.error(f"Error printing cost summary: {e}")
        sys.exit(0)

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
