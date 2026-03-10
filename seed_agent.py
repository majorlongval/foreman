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
MAX_OPEN_DRAFTS = int(os.environ.get("MAX_OPEN_DRAFTS", "10"))
COST_CEILING_USD = float(os.environ.get("COST_CEILING_USD", "5.0"))

# Routing profile: "cheap", "balanced", or "quality"
ROUTING_PROFILE = os.environ.get("ROUTING_PROFILE", "balanced")

# Labels
LABEL_NEEDS_REFINEMENT = "needs-refinement"
LABEL_AUTO_REFINED = "auto-refined"
LABEL_REFINED_OUT = "refined-out"  # closed originals that spawned a refined version
LABEL_DRAFT = "draft"
LABEL_READY = "ready"  # refined and ready for implementation

# Safety: labels we NEVER process through the refine pipeline
LABEL_IMPLEMENTING = "foreman-implementing"
FORBIDDEN_LABELS = {LABEL_AUTO_REFINED, LABEL_REFINED_OUT, LABEL_DRAFT, LABEL_READY, LABEL_IMPLEMENTING}

# ─── Prompts ──────────────────────────────────────────────────

REFINE_SYSTEM = """You are FOREMAN, an expert systems architect.
Your task is to take a rough GitHub issue and "refine" it into a professional, implementation-ready specification.

Output ONLY valid JSON:
{
  "title": "Clear, concise title (can be improved from original)",
  "summary": "Brief explanation of the 'why' and the 'what'",
  "acceptance_criteria": ["list of testable requirements"],
  "subtasks": ["atomic engineering steps"],
  "t_shirt_size": "XS|S|M|L|XL",
  "priority": "Low|Medium|High|Critical"
}"""

BRAINSTORM_SYSTEM = """You are FOREMAN. Based on the product VISION.md and current open issues, 
propose NEW technical tasks that move the project forward. 
Focus on modularity, testability, and building infrastructure.

Output ONLY valid JSON:
{
  "ideas": [
    {
      "title": "Title of the task",
      "body": "Detailed description in Markdown"
    }
  ]
}"""

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
from telegram_notifier import notify as tg, start_telegram_bot_polling, is_polling_alive
from agent_state import agent_state_manager as state, AgentState


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
        log.info(f"GitHub client initialized for repo '{repo_name}'")
        if self.dry_run:
            log.warning("DRY RUN mode is enabled. No changes will be made to GitHub.")

    def get_issues_by_label(self, label: str):
        return self.repo.get_issues(state="open", labels=[label])

    def get_issue_by_number(self, number: int):
        try:
            return self.repo.get_issue(number=number)
        except GithubException as e:
            if e.status == 404:
                log.error(f"Issue #{number} not found.")
                return None
            raise

    def find_similar_issue(self, title: str):
        """Finds an open issue with a similar title."""
        query = f'repo:"{self.repo.full_name}" is:issue is:open "{title}"'
        results = self.gh.search_issues(query)
        if results.totalCount > 0:
            for issue in results:
                if issue.title.lower().strip() == title.lower().strip():
                    return issue
        return None

    def create_issue(self, title, body, labels):
        if self.dry_run:
            log.info(f"[DRY RUN] Would create issue '{title}' with labels {labels}")
            return None

        log.info(f"Creating issue '{title}' with labels {labels}")
        return self.repo.create_issue(title=title, body=body, labels=labels)

    def create_refined_issue(self, data, original_num):
        """Standardized refined issue creation."""
        body = f"## Summary\n{data['summary']}\n\n"
        body += "## Acceptance Criteria\n" + "\n".join([f"- [ ] {i}" for i in data["acceptance_criteria"]]) + "\n\n"
        body += "## Subtasks\n" + "\n".join([f"- [ ] {i}" for i in data["subtasks"]]) + "\n\n"
        body += f"**Size:** {data.get('t_shirt_size', 'N/A')} | **Priority:** {data.get('priority', 'Medium')}\n"
        body += f"\n---\n_Auto-refined from #{original_num}_"
        
        return self.create_issue(data["title"], body, [LABEL_AUTO_REFINED, LABEL_READY])

    def update_issue(self, issue_number, title=None, body=None):
        if self.dry_run:
            log.info(f"[DRY RUN] Would update issue #{issue_number}")
            return

        issue = self.get_issue_by_number(issue_number)
        if issue:
            args = {}
            if title: args["title"] = title
            if body: args["body"] = body
            issue.edit(**args)

    def add_comment_to_issue(self, issue_number, comment):
        if self.dry_run:
            log.info(f"[DRY RUN] Would add comment to issue #{issue_number}")
            return

        issue = self.get_issue_by_number(issue_number)
        if issue:
            issue.create_comment(comment)

    def close_issue(self, issue_number):
        if self.dry_run:
            log.info(f"[DRY RUN] Would close issue #{issue_number}")
            return

        issue = self.get_issue_by_number(issue_number)
        if issue:
            issue.edit(state="closed")

    def add_labels_to_issue(self, issue_number, labels):
        if self.dry_run:
            log.info(f"[DRY RUN] Would add labels {labels} to issue #{issue_number}")
            return

        issue = self.get_issue_by_number(issue_number)
        if issue:
            issue.add_to_labels(*labels)

    def remove_label_from_issue(self, issue_number, label):
        if self.dry_run:
            log.info(f"[DRY RUN] Would remove label '{label}' from issue #{issue_number}")
            return

        issue = self.get_issue_by_number(issue_number)
        if issue:
            if any(l.name == label for l in issue.get_labels()):
                issue.remove_from_labels(label)


# ─── Agent ───────────────────────────────────────────────────

class ForemanAgent:
    def __init__(self, github_token, repo_name, dry_run=False):
        self.gh = GitHubClient(github_token, repo_name, dry_run=dry_run)
        self.cost = create_cost_system(CostTracker(), CloudCostMonitor())
        self.llm = ModelRouter(cost_tracker=self.cost.llm, profile=ROUTING_PROFILE)
        self.vision = load_vision()
        self.dry_run = dry_run
        self._ensure_labels()

    def _ensure_labels(self):
        """Creates labels if they don't exist."""
        if self.dry_run: return
        required = [
            (LABEL_NEEDS_REFINEMENT, "FBCA04"),
            (LABEL_AUTO_REFINED, "0E8A16"),
            (LABEL_REFINED_OUT, "D4C5F9"),
            (LABEL_DRAFT, "EDEDED"),
            (LABEL_READY, "006B75"),
        ]
        for name, color in required:
            try:
                self.gh.repo.get_label(name)
            except:
                self.gh.repo.create_label(name, color)

    def _should_skip(self, issue):
        current_labels = {l.name for l in issue.labels}
        if not FORBIDDEN_LABELS.isdisjoint(current_labels):
            return True
        return False

    def refine_issue(self, issue):
        if self._should_skip(issue):
            return

        log.info(f"Processing issue #{issue.number}: '{issue.title}'")
        issue_text = f"Issue Title: {issue.title}\nIssue Number: {issue.number}\nIssue Body:\n{issue.body}"

        try:
            response_text = self.llm.chat(REFINE_SYSTEM, issue_text, json_mode=True, task_id=f"refine-#{issue.number}")
            refined_data = json.loads(response_text)
        except Exception as e:
            log.error(f"Refinement failed for #{issue.number}: {e}")
            return

        new_issue = self.gh.create_refined_issue(refined_data, issue.number)

        if new_issue or self.dry_run:
            new_num = new_issue.number if new_issue else "DRY_RUN"
            log.info(f"Refined #{issue.number} -> #{new_num}")
            tg(f"✅ Refined issue #{issue.number} -> #{new_num}")
            self.gh.add_comment_to_issue(issue.number, f"✅ Refined into #{new_num}")
            self.gh.remove_label_from_issue(issue.number, LABEL_NEEDS_REFINEMENT)
            self.gh.add_labels_to_issue(issue.number, [LABEL_REFINED_OUT])
            self.gh.close_issue(issue.number)

    def brainstorm(self):
        log.info("⛈️ Entering brainstorm mode...")
        drafts = list(self.gh.get_issues_by_label(LABEL_DRAFT))
        ready = list(self.gh.get_issues_by_label(LABEL_READY))
        
        user_prompt = f"Vision:\n{self.vision}\n\nExisting:\n" + "\n".join([f"#{i.number}: {i.title}" for i in drafts + ready])

        try:
            response_text = self.llm.chat(BRAINSTORM_SYSTEM, user_prompt, json_mode=True, task_id="brainstorm")
            ideas = json.loads(response_text).get("ideas", [])
        except Exception as e:
            log.error(f"Brainstorming failed: {e}")
            return

        for idea in ideas:
            if not self.gh.find_similar_issue(idea["title"]):
                self.gh.create_issue(f"[DRAFT] {idea['title']}", idea["body"], [LABEL_DRAFT, LABEL_NEEDS_REFINEMENT])
                tg(f"💡 New draft: {idea['title']}")

    def run_cycle(self, mode="AUTO"):
        total, _ = self.cost.get_total_cost()
        if total > COST_CEILING_USD:
            log.critical(f"Cost ceiling exceeded: ${total:.2f}")
            return False

        to_refine = list(self.gh.get_issues_by_label(LABEL_NEEDS_REFINEMENT))
        if mode == "BRAINSTORM" or (not to_refine and len(list(self.gh.get_issues_by_label(LABEL_READY))) < BRAINSTORM_THRESHOLD):
            self.brainstorm()
        else:
            for issue in to_refine:
                self.refine_issue(issue)
        
        self.cost.llm.save_session()
        return True


# ─── Main ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--brainstorm-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    start_telegram_bot_polling()
    log.info("🚀 Foreman Seed Agent v0.1 initialized")
    state.set_state(AgentState.RUNNING)

    agent = ForemanAgent(GITHUB_TOKEN, REPO_NAME, dry_run=args.dry_run)

    try:
        while True:
            while state.get_state() == AgentState.PAUSED:
                if not is_polling_alive():
                    log.warning("Telegram polling thread died while paused. Auto-resuming for safety.")
                    state.set_state(AgentState.RUNNING)
                    break
                time.sleep(15)

            mode = "BRAINSTORM" if args.brainstorm_only else "AUTO"
            if not agent.run_cycle(mode=mode) or args.once:
                break

            time.sleep(POLL_INTERVAL_SEC)
    except KeyboardInterrupt:
        pass
    finally:
        state.set_state(AgentState.IDLE)

if __name__ == "__main__":
    main()