"""
FOREMAN Refine Agent — v0.1
Extracts issues labeled 'needs-refinement' and transforms them into structured specs.
Also handles auto-promotion of 'auto-refined' issues to 'ready' after a delay.

Usage:
  python refine_agent.py [--once] [--dry-run]
"""

import os
import sys
import logging
import argparse
from datetime import datetime, timezone
from github import Github, GithubException

# ─── Configuration ────────────────────────────────────────────

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_NAME = os.environ.get("FOREMAN_REPO", "")

# Agent behavior
AUTO_PROMOTE_DELAY_HOURS = float(os.environ.get("AUTO_PROMOTE_DELAY_HOURS", "2.0"))
AUTO_PROMOTE_MAX_PER_CYCLE = int(os.environ.get("AUTO_PROMOTE_MAX_PER_CYCLE", "3"))
COST_CEILING_USD = float(os.environ.get("COST_CEILING_USD", "5.0"))
ROUTING_PROFILE = os.environ.get("ROUTING_PROFILE", "balanced")

# Labels
LABEL_NEEDS_REFINEMENT = "needs-refinement"
LABEL_AUTO_REFINED = "auto-refined"
LABEL_REFINED_OUT = "refined-out"
LABEL_DRAFT = "draft"
LABEL_READY = "ready"
LABEL_HOLD = "hold"
LABEL_IMPLEMENTING = "foreman-implementing"

# Safety: issues with these labels are ignored by the refinement logic
FORBIDDEN_LABELS = {LABEL_AUTO_REFINED, LABEL_REFINED_OUT, LABEL_DRAFT, LABEL_READY, LABEL_IMPLEMENTING, LABEL_HOLD}

# ─── Logging ──────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("refine-agent")

# ─── Dependencies ───────────────────────────────────────────

try:
    from cost_monitor import CostTracker
    from llm_client import LLMClient, ModelRouter
    from telegram_notifier import notify as tg
    from agent_state import agent_state_manager as state, AgentState
except ImportError as e:
    log.error(f"Missing dependency: {e}")
    sys.exit(1)

# ─── GitHub Helpers ──────────────────────────────────────────

class GitHubClient:
    def __init__(self, token: str, repo_name: str, dry_run: bool = False):
        self.gh = Github(token)
        self.repo = self.gh.get_repo(repo_name)
        self.dry_run = dry_run

    def get_refinement_queue(self) -> list:
        """Get open issues labeled 'needs-refinement', excluding forbidden labels."""
        try:
            issues = self.repo.get_issues(
                state="open",
                labels=[self.repo.get_label(LABEL_NEEDS_REFINEMENT)],
                sort="created",
                direction="asc",
            )
            safe_issues = []
            for issue in issues:
                issue_labels = {l.name for l in issue.labels}
                if issue_labels & FORBIDDEN_LABELS:
                    log.warning(f"  ⛔ Skipping #{issue.number} — has forbidden label: {issue_labels & FORBIDDEN_LABELS}")
                    continue
                safe_issues.append(issue)
            return safe_issues
        except Exception as e:
            log.error(f"Error fetching refinement queue: {e}")
            raise

    def get_auto_refined_issues(self):
        """Get open issues labeled 'auto-refined'."""
        try:
            return self.repo.get_issues(
                state="open",
                labels=[LABEL_AUTO_REFINED],
                sort="created",
                direction="asc",
            )
        except Exception as e:
            log.error(f"Error fetching auto-refined issues: {e}")
            return []

    def create_refined_issue(self, original_issue, refined_body: str, refined_title: str) -> int:
        """Create a new refined issue and close the original with a link."""
        try:
            if self.dry_run:
                log.info(f"  [DRY RUN] Would create refined issue from #{original_issue.number}")
                return -1

            new_issue = self.repo.create_issue(
                title=refined_title,
                body=refined_body + f"\n\n---\n_Auto-refined from #{original_issue.number}_",
                labels=[self.repo.get_label(LABEL_AUTO_REFINED)],
            )

            original_issue.add_to_labels(self.repo.get_label(LABEL_REFINED_OUT))
            original_issue.remove_from_labels(self.repo.get_label(LABEL_NEEDS_REFINEMENT))
            original_issue.create_comment(
                f"🤖 Refined by FOREMAN → #{new_issue.number}\n\n"
                f"This issue has been closed because a structured version was created."
            )
            original_issue.edit(state="closed", state_reason="completed")

            log.info(f"  ✅ #{original_issue.number} → #{new_issue.number}")
            return new_issue.number
        except Exception as e:
            log.error(f"Error creating refined issue: {e}")
            raise

# ─── Prompts ─────────────────────────────────────────────────

REFINE_SYSTEM = """You are FOREMAN, an autonomous agent that refines GitHub issues into 
well-structured, actionable development tasks.

You will receive an issue title and body. Rewrite it into the following structure:

## Summary
One-line description of what this task accomplishes.

## Acceptance Criteria
- [ ] Criterion 1 (specific, testable)
- [ ] Criterion 2
(minimum 3 criteria)

## Steps to Reproduce (include ONLY if this is a bug)
1. Step 1
2. Step 2

## Component/Area
Which part of the system this touches. Choose from:
agent-loop, github-integration, telegram-bot, dashboard, infrastructure, 
vision, documentation, testing, ci-cd

## Subtasks
Break the work into concrete subtasks:
- [ ] Subtask 1
- [ ] Subtask 2

## Complexity Estimate
- T-shirt size: XS / S / M / L / XL
- Estimated API cost: low / medium / high

Rules:
- Keep the original intent but make it precise and actionable
- Title should be imperative: "Add X", "Fix Y", "Implement Z"
- Be concise.
"""

# ─── Agent Logic ─────────────────────────────────────────────

class RefineAgent:
    def __init__(self, github: GitHubClient, dry_run: bool = False):
        self.github = github
        self.llm = LLMClient()
        self.router = ModelRouter(ROUTING_PROFILE)
        self.cost = CostTracker(ceiling_usd=COST_CEILING_USD)
        self.dry_run = dry_run
        self.stats = {"refined": 0, "promoted": 0, "failed": 0}

    def _complete(self, task: str, system: str, message: str, max_tokens: int = 2000):
        model = self.router.get(task)
        response = self.llm.complete(model, system, message, max_tokens)
        
        class _Usage:
            def __init__(self, inp, out):
                self.input_tokens = inp
                self.output_tokens = out
        
        self.cost.record(model, _Usage(response.input_tokens, response.output_tokens),
                         agent="refine", action=task)
        return response

    def run_refinement(self):
        """Process the 'needs-refinement' queue."""
        log.info("🔍 Checking refinement queue...")
        try:
            queue = self.github.get_refinement_queue()
            if not queue:
                log.info("  Queue empty.")
                return

            for issue in queue:
                if not self.cost.check_ceiling():
                    log.warning("Cost ceiling reached. Stopping cycle.")
                    break
                
                self.refine_issue(issue)
        except Exception as e:
            log.error(f"Error in refinement loop: {e}")

    def refine_issue(self, issue):
        log.info(f"🔧 Refining #{issue.number}: {issue.title}")
        try:
            response = self._complete(
                task="refine",
                system=REFINE_SYSTEM,
                message=f"Issue Title: {issue.title}\n\nIssue Body:\n{issue.body or '(empty)'}"
            )
            
            refined_body = response.text
            
            title_response = self._complete(
                task="title_gen",
                system="Generate ONLY an imperative title. No explanation. No quotes. Max 10 words.",
                message=f"Generate a title for this issue:\n\n{refined_body}",
                max_tokens=100,
            )
            refined_title = title_response.text.strip().strip('"').strip("'")

            self.github.create_refined_issue(issue, refined_body, refined_title)
            self.stats["refined"] += 1
            tg(f"✅ Refined #{issue.number}: <b>{refined_title}</b>")
        except Exception as e:
            log.error(f"  ❌ Failed to refine #{issue.number}: {e}")
            self.stats["failed"] += 1

    def run_promotion(self):
        """Promote 'auto-refined' issues to 'ready' after delay."""
        log.info("⏫ Checking for auto-promotions...")
        try:
            issues = self.github.get_auto_refined_issues()
            now = datetime.now(timezone.utc)
            count = 0

            for issue in issues:
                if count >= AUTO_PROMOTE_MAX_PER_CYCLE:
                    break
                
                labels = {l.name for l in issue.labels}
                if LABEL_HOLD in labels:
                    continue

                created_at = issue.created_at.replace(tzinfo=timezone.utc)
                age_hours = (now - created_at).total_seconds() / 3600

                if age_hours >= AUTO_PROMOTE_DELAY_HOURS:
                    log.info(f"  ⏫ Promoting #{issue.number} to ready")
                    if not self.dry_run:
                        issue.remove_from_labels(LABEL_AUTO_REFINED)
                        issue.add_to_labels(LABEL_READY)
                        issue.create_comment(f"⏫ Auto-promoted to `ready` after {AUTO_PROMOTE_DELAY_HOURS}h delay.")
                        tg(f"⏫ Auto-promoted #{issue.number} to <b>ready</b>")
                    
                    self.stats["promoted"] += 1
                    count += 1
        except Exception as e:
            log.error(f"Error in promotion loop: {e}")

# ─── Main ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--dry-run", action="store_true", help="Don't modify GitHub")
    args = parser.parse_args()

    if not GITHUB_TOKEN or not REPO_NAME:
        log.error("Missing GITHUB_TOKEN or FOREMAN_REPO env vars.")
        sys.exit(1)

    gh = GitHubClient(GITHUB_TOKEN, REPO_NAME, dry_run=args.dry_run)
    agent = RefineAgent(gh, dry_run=args.dry_run)

    log.info("🚀 Refine Agent started")

    while True:
        try:
            if state.get_state() == AgentState.PAUSED:
                log.info("Agent is PAUSED. Skipping cycle.")
            else:
                agent.run_refinement()
                agent.run_promotion()

            log.info(f"Cycle complete. Stats: {agent.stats}")
            
            if args.once:
                break
            
            # Use state manager for sleep to allow remote wake
            state.sleep(300) 
        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error(f"Unhandled exception in main loop: {e}")
            state.sleep(60)

if __name__ == "__main__":
    main()