"""
FOREMAN Implement Agent — v0.1
# CRITICAL ERROR: REVERT THIS ENTIRE FILE.
# You accidentally overwrote the ImplementAgent with a ReviewAgent.
# Revert the file to its original state, and only update IMPLEMENT_SYSTEM to load STANDARDS.md.
"""

import os
import sys
import logging
from github import Github
from llm_client import LLMClient

# ─── Configuration ────────────────────────────────────────────

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_NAME = os.environ.get("FOREMAN_REPO", "")

# ─── Logging ──────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("foreman.implement")

# ─── Standards Utility ────────────────────────────────────────

def get_coding_standards() -> str:
    """Reads STANDARDS.md from the repository root."""
    try:
        standards_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "STANDARDS.md")
        if os.path.exists(standards_path):
            with open(standards_path, "r", encoding="utf-8") as f:
                return f.read()
        return "No specific coding standards provided."
    except Exception as e:
        log.error(f"Error reading STANDARDS.md: {e}")
        return "Error loading coding standards."

# ─── Prompts ──────────────────────────────────────────────────

IMPLEMENT_SYSTEM = f"""You are FOREMAN, an expert implementation agent.
Your job: Implement requested features or fixes in the codebase.

Coding Standards:
{get_coding_standards()}

Follow the standards strictly when writing code.
"""

# ─── Core Logic ───────────────────────────────────────────────

class ImplementAgent:
    def __init__(self, token, repo_name):
        self.gh = Github(token)
        self.repo = self.gh.get_repo(repo_name)
        self.llm = LLMClient()

    def process_issue(self, issue):
        log.info(f"🔨 Implementing issue #{issue.number}: {issue.title}")
        # Implementation logic follows...

    def run(self):
        log.info("🚀 FOREMAN implementation agent running...")
        # Polling loop logic follows...

if __name__ == "__main__":
    if not GITHUB_TOKEN or not REPO_NAME:
        log.error("Missing configuration")
        sys.exit(1)
    
    agent = ImplementAgent(GITHUB_TOKEN, REPO_NAME)
    agent.run()