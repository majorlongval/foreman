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
from telegram_notifier import notify as tg
from agent_state import state, AgentState


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
        # This is a very basic search, could be improved with embeddings etc.
        query = f'repo:"{self.repo.full_name}" is:issue is:open "{title}"'
        results = self.gh.search_issues(query)
        if results.totalCount > 0:
            # Check for a very close match to avoid false positives
            for issue in results:
                if issue.title.lower().strip() == title.lower().strip():
                    return issue
        return None

    def create_issue(self, title, body, labels):
        if self.dry_run:
            log.info(f"[DRY RUN] Would create issue '{title}' with labels {labels}")
            log.info(f"Body:\n---\n{body}\n---")
            return None  # Can't return a fake issue object easily, so caller must handle None

        log.info(f"Creating issue '{title}' with labels {labels}")
        return self.repo.create_issue(title=title, body=body, labels=labels)

    def update_issue(self, issue_number, title=None, body=None):
        if self.dry_run:
            log.info(f"[DRY RUN] Would update issue #{issue_number}")
            if title: log.info(f"  New title: {title}")
            if body: log.info(f"  New body:\n---\n{body}\n---")
            return

        issue = self.get_issue_by_number(issue_number)
        if issue:
            log.info(f"Updating issue #{issue_number}: '{title}'")
            args = {}
            if title: args["title"] = title
            if body: args["body"] = body
            issue.edit(**args)

    def add_comment_to_issue(self, issue_number, comment):
        if self.dry_run:
            log.info(f"[DRY RUN] Would add comment to issue #{issue_number}:\n---\n{comment}\n---")
            return

        issue = self.get_issue_by_number(issue_number)
        if issue:
            log.info(f"Adding comment to issue #{issue_number}")
            issue.create_comment(comment)

    def close_issue(self, issue_number):
        if self.dry_run:
            log.info(f"[DRY RUN] Would close issue #{issue_number}")
            return

        issue = self.get_issue_by_number(issue_number)
        if issue:
            log.info(f"Closing issue #{issue_number}")
            issue.edit(state="closed")

    def add_labels_to_issue(self, issue_number, labels):
        if self.dry_run:
            log.info(f"[DRY RUN] Would add labels {labels} to issue #{issue_number}")
            return

        issue = self.get_issue_by_number(issue_number)
        if issue:
            log.info(f"Adding labels {labels} to issue #{issue_number}")
            issue.add_to_labels(*labels)

    def remove_label_from_issue(self, issue_number, label):
        if self.dry_run:
            log.info(f"[DRY RUN] Would remove label '{label}' from issue #{issue_number}")
            return

        issue = self.get_issue_by_number(issue_number)
        if issue:
            # Check if label exists before trying to remove
            if any(l.name == label for l in issue.get_labels()):
                log.info(f"Removing label '{label}' from issue #{issue_number}")
                issue.remove_from_labels(label)
            else:
                log.warning(f"Label '{label}' not found on issue #{issue_number}, cannot remove.")


# ─── Business Logic: Refine ───────────────────────────────────

def format_issue_for_llm(issue) -> str:
    """Creates a simplified text representation of a GitHub issue."""
    return f"""
Issue Title: {issue.title}
Issue Number: {issue.number}
Issue URL: {issue.html_url}
Issue Body:
{issue.body}
"""

def parse_llm_output(output: str) -> dict:
    """
    Parses the LLM's JSON output to extract structured issue data.
    Handles markdown code fences.
    """
    try:
        # Strip markdown fences if present
        if output.startswith("```json"):
            output = output[7:]
        if output.endswith("```"):
            output = output[:-3]
        output = output.strip()

        data = json.loads(output)

        # Basic validation
        if not all(k in data for k in ["title", "summary", "acceptance_criteria", "subtasks"]):
            raise ValueError("Missing one or more required keys in LLM output.")
        if not isinstance(data["title"], str) or not data["title"]:
             raise ValueError("Title must be a non-empty string.")

        return data
    except (json.JSONDecodeError, ValueError) as e:
        log.error(f"Failed to parse LLM output: {e}\nRaw output:\n---\n{output}\n---")
        return {}


def format_refined_issue_body(data: dict) -> str:
    """Formats the structured data back into a markdown body for a new GitHub issue."""
    body = f"## Summary\n{data['summary']}\n\n"
    if data.get("acceptance_criteria"):
        ac_list = "\n".join([f"- [ ] {item}" for item in data["acceptance_criteria"]])
        body += f"## Acceptance Criteria\n{ac_list}\n\n"
    if data.get("component_area"):
        body += f"## Component/Area\n{data['component_area']}\n\n"
    if data.get("subtasks"):
        st_list = "\n".join([f"- [ ] {item}" for item in data["subtasks"]])
        body += f"## Subtasks\n{st_list}\n\n"
    if data.get("complexity_estimate"):
        body += "## Complexity Estimate\n"
        body += f"- T-shirt size: {data['complexity_estimate'].get('t_shirt_size', 'N/A')}\n"
        body += f"- Estimated API cost: {data['complexity_estimate'].get('api_cost', 'N/A')}\n\n"

    # Add a reference back to the original issue
    if data.get("original_issue_number"):
        body += f"---\n_Auto-refined from #{data['original_issue_number']}_"

    return body.strip()


def refine_issue(llm: LLMClient, gh_client: GitHubClient, issue):
    """
    Processes a single issue: sends to LLM, parses response, and creates a new issue.
    """
    log.info(f"Processing issue #{issue.number}: '{issue.title}'")
    issue_text = format_issue_for_llm(issue)

    # Simple check for labels that indicate we should skip this issue
    current_labels = {label.name for label in issue.labels}
    if not FORBIDDEN_LABELS.isdisjoint(current_labels):
        log.warning(f"Skipping issue #{issue.number} due to forbidden labels: {current_labels.intersection(FORBIDDEN_LABELS)}")
        return

    # Check for self-reference which can cause loops
    if f"_Auto-refined from #{issue.number}_" in issue.body:
        log.warning(f"Skipping issue #{issue.number} as it appears to be a refinement of itself.")
        return

    # Use a system prompt from a file
    system_prompt = Path("prompts/refine_issue.md").read_text()

    # Call the LLM
    try:
        response_text = llm.chat(system_prompt, issue_text, json_mode=True)
    except Exception as e:
        log.error(f"LLM API call failed for issue #{issue.number}: {e}")
        return

    # Parse the response
    refined_data = parse_llm_output(response_text)
    if not refined_data:
        # Parsing failed, error already logged. Add a comment to the issue.
        gh_client.add_comment_to_issue(
            issue.number,
            "⚠️ **Auto-refinement failed:** The LLM output could not be parsed. Please check the agent logs."
        )
        return

    # Add original issue number for back-reference
    refined_data["original_issue_number"] = issue.number

    # Format the new issue body
    new_title = refined_data["title"]
    new_body = format_refined_issue_body(refined_data)
    new_labels = [LABEL_AUTO_REFINED, LABEL_READY]

    # Create the new issue
    new_issue = gh_client.create_issue(new_title, new_body, new_labels)
    if new_issue is None and not gh_client.dry_run:
        log.error(f"Failed to create new issue for original issue #{issue.number}.")
        return

    new_issue_number = new_issue.number if new_issue else "DRY_RUN_ISSUE"
    log.info(f"Successfully created refined issue #{new_issue_number} for original #{issue.number}")
    tg(f"✅ Refined issue #{issue.number} -> #{new_issue_number}\n_{new_title}_")

    # Post-creation actions: comment on and close the original issue
    comment = f"✅ This issue has been auto-refined into a detailed specification: #{new_issue_number}"
    gh_client.add_comment_to_issue(issue.number, comment)
    gh_client.remove_label_from_issue(issue.number, LABEL_NEEDS_REFINEMENT)
    gh_client.add_labels_to_issue(issue.number, [LABEL_REFINED_OUT])
    gh_client.close_issue(issue.number)


# ─── Business Logic: Brainstorm ───────────────────────────────

def brainstorm_new_ideas(llm: LLMClient, gh_client: GitHubClient, vision: str):
    """
    Generates new draft issues based on the VISION.md file.
    """
    log.info("⛈️ Entering brainstorm mode...")

    # 1. Get existing draft and ready issues to provide as context
    draft_issues = gh_client.get_issues_by_label(LABEL_DRAFT)
    ready_issues = gh_client.get_issues_by_label(LABEL_READY)
    existing_issues_text = "Existing Draft Issues:\n"
    for issue in draft_issues:
        existing_issues_text += f"- #{issue.number}: {issue.title}\n"
    existing_issues_text += "\nExisting Ready-for-Implementation Issues:\n"
    for issue in ready_issues:
        existing_issues_text += f"- #{issue.number}: {issue.title}\n"

    # 2. Formulate the prompt
    system_prompt = Path("prompts/brainstorm_issues.md").read_text()
    user_prompt = f"""
Here is the project vision:
---
{vision}
---

Here are the existing issues that are either in draft or ready for implementation. Do not suggest ideas that are already covered here.
---
{existing_issues_text}
---

Based on the vision, and avoiding the existing topics, please generate up to {BRAINSTORM_MAX_DRAFTS} new, actionable, and distinct ideas for GitHub issues.
"""

    # 3. Call the LLM
    try:
        response_text = llm.chat(system_prompt, user_prompt, json_mode=True)
    except Exception as e:
        log.error(f"LLM API call failed during brainstorm: {e}")
        return

    # 4. Parse the response
    try:
        ideas = json.loads(response_text)
        if "ideas" not in ideas or not isinstance(ideas["ideas"], list):
            raise ValueError("Expected a JSON object with an 'ideas' list.")
    except (json.JSONDecodeError, ValueError) as e:
        log.error(f"Failed to parse brainstorm LLM output: {e}\nRaw output:\n---\n{response_text}\n---")
        return

    # 5. Create draft issues
    created_count = 0
    for idea in ideas["ideas"]:
        if "title" not in idea or "body" not in idea:
            log.warning(f"Skipping malformed idea: {idea}")
            continue

        title = idea["title"]
        body = idea["body"]

        # Safety check: avoid creating duplicate issues
        if gh_client.find_similar_issue(title):
            log.warning(f"Skipping duplicate idea: '{title}'")
            continue

        new_issue = gh_client.create_issue(
            title=f"[DRAFT] {title}",
            body=body,
            labels=[LABEL_DRAFT, LABEL_NEEDS_REFINEMENT]
        )

        if new_issue is not None or gh_client.dry_run:
            created_count += 1
            log.info(f"Created draft issue: '{title}'")
            tg(f"💡 New draft issue created: [DRAFT] {title}")

    log.info(f"Brainstorm session complete. Created {created_count} new draft issues.")


# ─── Main Loop ────────────────────────────────────────────────

def main(
    once: bool = False,
    brainstorm_only: bool = False,
    dry_run: bool = False,
    force_refine_issue: int = 0,
):
    """
    Main execution loop for the agent.
    """
    log.info("🚀 Foreman Seed Agent v0.1 initialized")
    if dry_run:
        log.warning("DRY RUN mode is ON. No changes will be persisted.")

    state.set_state(AgentState.RUNNING)

    # Initialize components
    if not GITHUB_TOKEN or not REPO_NAME:
        log.critical("🚨 GITHUB_TOKEN and FOREMAN_REPO environment variables must be set.")
        sys.exit(1)

    gh_client = GitHubClient(GITHUB_TOKEN, REPO_NAME, dry_run=dry_run)
    cost_tracker = CostTracker()
    cloud_cost_monitor = CloudCostMonitor()
    cost_system = create_cost_system(cost_tracker, cloud_cost_monitor)
    llm = LLMClient(cost_tracker=cost_tracker, routing_profile=ROUTING_PROFILE)
    vision = load_vision()

    try:
        while True:
            # Check for paused state
            while state.is_paused():
                log.info("Agent is PAUSED. Waiting for resume command...")
                time.sleep(15) # Check every 15 seconds

            log.info("Starting new agent cycle.")

            # Check costs before proceeding
            total_cost, cloud_cost = cost_system.get_total_cost()
            log.info(f"Current costs - LLM: ${cost_tracker.get_total_cost():.4f}, Cloud: ${cloud_cost:.4f}, Total: ${total_cost:.4f}")
            if total_cost > COST_CEILING_USD:
                error_msg = f"EMERGENCY SHUTDOWN: Cost ceiling of ${COST_CEILING_USD:.2f} exceeded. Current total cost is ${total_cost:.2f}."
                log.critical(error_msg)
                tg(f"🚨 {error_msg}")
                break

            # --- Determine Mode: Refine or Brainstorm ---
            mode = "REFINE" # Default mode
            issues_to_refine = []

            if force_refine_issue:
                log.info(f"Forcing refinement for issue #{force_refine_issue}")
                issue = gh_client.get_issue_by_number(force_refine_issue)
                if issue:
                    issues_to_refine = [issue]
                else:
                    log.error(f"Could not find issue #{force_refine_issue} to refine.")
            elif brainstorm_only:
                mode = "BRAINSTORM"
            else:
                # Standard logic: check if refinement is needed, otherwise maybe brainstorm
                issues_to_refine = list(gh_client.get_issues_by_label(LABEL_NEEDS_REFINEMENT))
                ready_issues = list(gh_client.get_issues_by_label(LABEL_READY))

                if not issues_to_refine:
                    log.info("No issues need refinement.")
                    if len(ready_issues) < BRAINSTORM_THRESHOLD:
                        mode = "BRAINSTORM"
                    else:
                        mode = "IDLE"
                else:
                    log.info(f"Found {len(issues_to_refine)} issues to refine.")

            # --- Execute Actions Based on Mode ---
            if mode == "REFINE":
                for issue in issues_to_refine:
                    try:
                        refine_issue(llm, gh_client, issue)
                    except Exception as e:
                        log.error(f"Failed to process issue #{issue.number}: {e}", exc_info=True)
                        tg(f"⚠️ Error refining issue #{issue.number}: {e}")

            elif mode == "BRAINSTORM":
                draft_count = len(list(gh_client.get_issues_by_label(LABEL_DRAFT)))
                if draft_count >= MAX_OPEN_DRAFTS:
                    log.warning(f"Skipping brainstorm: already {draft_count} open drafts (max: {MAX_OPEN_DRAFTS}).")
                elif not vision:
                    log.warning("Skipping brainstorm: VISION.md is missing.")
                else:
                    try:
                        brainstorm_new_ideas(llm, gh_client, vision)
                    except Exception as e:
                        log.error(f"Brainstorming failed: {e}", exc_info=True)
                        tg(f"⚠️ Error during brainstorming: {e}")

            elif mode == "IDLE":
                log.info("Pipeline is healthy. Nothing to do.")

            if once or force_refine_issue:
                break

            log.info(f"Cycle complete. Sleeping for {POLL_INTERVAL_SEC} seconds...")
            time.sleep(POLL_INTERVAL_SEC)

    except KeyboardInterrupt:
        log.info("👋 User requested exit. Shutting down.")
    except Exception as e:
        log.critical(f"💥 Unhandled exception in main loop: {e}", exc_info=True)
        tg(f"💥 *CRITICAL ERROR* in agent loop: {e}")
    finally:
        state.set_state(AgentState.IDLE)
        log.info("Agent shutdown complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FOREMAN Seed Agent")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run the agent loop only once then exit.",
    )
    parser.add_argument(
        "--brainstorm-only",
        action="store_true",
        help="Force the agent to run in brainstorm mode for one cycle.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without making any actual changes to GitHub.",
    )
    parser.add_argument(
        "--force-refine-issue",
        type=int,
        default=0,
        help="Process a specific issue number and then exit.",
    )
    args = parser.parse_args()

    main(
        once=args.once,
        brainstorm_only=args.brainstorm_only,
        dry_run=args.dry_run,
        force_refine_issue=args.force_refine_issue,
    )