"""
FOREMAN Review Agent — v0.1
Watches for 'ready-for-review' PRs, analyzes code, adds comments, requests changes/approves.

Usage:
  python review_agent.py                 # Run the loop
  python review_agent.py --once          # Single pass then exit
"""

import os
import sys
import time
import logging
import argparse
from github import Github

from llm_client import LLMClient, ModelRouter
from cost_monitor import CostTracker

# ─── Configuration ────────────────────────────────────────────

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_NAME = os.environ.get("FOREMAN_REPO", "")
ROUTING_PROFILE = os.environ.get("ROUTING_PROFILE", "balanced")
COST_CEILING_USD = float(os.environ.get("COST_CEILING_USD", "5.0"))
POLL_INTERVAL_SEC = int(os.environ.get("POLL_INTERVAL", "300"))

LABEL_READY_FOR_REVIEW = "ready-for-review"
LABEL_REVIEWED = "reviewed"
LABEL_CHANGES_REQUESTED = "changes-requested"

# ─── Logging ──────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("foreman.review")

# ─── Standards Utility ────────────────────────────────────────

def get_coding_standards() -> str:
    """Reads STANDARDS.md from the repository root."""
    try:
        standards_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "STANDARDS.md")
        if os.path.exists(standards_path):
            with open(standards_path, "r", encoding="utf-8") as f:
                content = f.read()
            log.info("Successfully loaded STANDARDS.md")
            return content
        log.warning("STANDARDS.md not found in root")
        return "No specific coding standards provided."
    except Exception as e:
        log.error(f"Error reading STANDARDS.md: {e}")
        return "Error loading coding standards."

# ─── Prompts ──────────────────────────────────────────────────

SYSTEM_PROMPT = f"""You are FOREMAN, an expert code reviewer.

Your job: Review a GitHub Pull Request against the repository coding standards.
Focus on logic errors, maintainability, security, and adherence to the standards.

Coding Standards:
{get_coding_standards()}

Output format:
- A brief summary of your review.
- Any specific issues found (if none, say "LGTM").
- A final decision: "APPROVE", "COMMENT", or "REQUEST_CHANGES".

If you request changes, be specific about what needs to be fixed.
"""

# ─── GitHub Client ────────────────────────────────────────────

class GitHubClient:
    def __init__(self, token: str, repo_name: str):
        self.gh = Github(auth=__import__("github").Auth.Token(token))
        self.repo = self.gh.get_repo(repo_name)

    def get_prs_to_review(self):
        """Get PRs labeled 'ready-for-review'."""
        prs = self.repo.get_pulls(state="open", sort="created", direction="asc")
        return [pr for pr in prs if LABEL_READY_FOR_REVIEW in [l.name for l in pr.labels]]

    def get_pr_diff(self, pr):
        """Fetch the diff of the PR."""
        # Using the GitHub API to get the diff text directly
        return pr.get_files()

# ─── Review Agent ─────────────────────────────────────────────

class ReviewAgent:
    def __init__(self):
        self.github = GitHubClient(GITHUB_TOKEN, REPO_NAME)
        self.llm = LLMClient()
        self.router = ModelRouter(ROUTING_PROFILE)
        self.cost = CostTracker(ceiling_usd=COST_CEILING_USD)

    def review_pr(self, pr):
        log.info(f"🔍 Reviewing PR #{pr.number}: {pr.title}")
        
        files = self.github.get_pr_diff(pr)
        diff_context = ""
        for f in files:
            diff_context += f"\nFile: {f.filename}\nStatus: {f.status}\nDiff:\n{f.patch}\n"

        prompt = f"Review the following PR:\n\nTitle: {pr.title}\nBody: {pr.body}\n\nDiffs:\n{diff_context}"
        
        model = self.router.get("review")
        response = self.llm.complete(model, SYSTEM_PROMPT, prompt)
        self.cost.record(model, response, agent="review", action="review_pr")

        review_text = response.text
        
        # Apply labels/actions based on review
        if "REQUEST_CHANGES" in review_text:
            pr.create_issue_comment(f"## FOREMAN Review\n\n{review_text}")
            self._update_labels(pr, LABEL_CHANGES_REQUESTED)
        elif "APPROVE" in review_text:
            pr.create_issue_comment(f"## FOREMAN Review\n\n{review_text}")
            pr.create_review(event="APPROVE")
            self._update_labels(pr, LABEL_REVIEWED)
        else:
            pr.create_issue_comment(f"## FOREMAN Review\n\n{review_text}")
            self._update_labels(pr, LABEL_REVIEWED)

        log.info(f"✅ Reviewed PR #{pr.number}")

    def _update_labels(self, pr, new_label):
        pr.remove_from_labels(LABEL_READY_FOR_REVIEW)
        pr.add_to_labels(new_label)

    def run(self):
        log.info("🚀 FOREMAN review agent starting")
        while True:
            prs = self.github.get_prs_to_review()
            if not prs:
                log.info("💤 No PRs to review. Sleeping...")
            else:
                for pr in prs:
                    self.review_pr(pr)
            
            time.sleep(POLL_INTERVAL_SEC)

# ─── Main ─────────────────────────────────────────────────────

if __name__ == "__main__":
    if not GITHUB_TOKEN or not REPO_NAME:
        log.error("❌ GITHUB_TOKEN or FOREMAN_REPO not set")
        sys.exit(1)
    
    agent = ReviewAgent()
    agent.run()