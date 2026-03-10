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
        self._ensure_labels()

    def _ensure_labels(self):
        """Create our labels if they don't exist."""
        existing = {l.name for l in self.repo.get_labels()}
        label_configs = {
            LABEL_NEEDS_REFINEMENT: "fbca04",  # yellow
            LABEL_AUTO_REFINED: "0e8a16",      # green
            LABEL_REFINED_OUT: "e4e669",       # muted yellow — closed originals
            LABEL_DRAFT: "c5def5",              # light blue
            LABEL_READY: "0075ca",              # blue — ready for implementation
        }
        for name, color in label_configs.items():
            if name not in existing:
                if not self.dry_run:
                    self.repo.create_label(name=name, color=color)
                log.info(f"  Created label: {name}")

    def get_refinement_queue(self) -> list:
        """Get open issues labeled 'needs-refinement', excluding forbidden labels."""
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

    def get_all_open_issues(self) -> list:
        """Get all open issues for context (brainstorm dedup)."""
        return list(self.repo.get_issues(state="open"))

    def get_closed_issues(self, count: int = 50) -> list:
        """Get recently closed issues for context."""
        return list(self.repo.get_issues(state="closed", sort="updated", direction="desc")[:count])

    def create_refined_issue(self, original_issue, refined_body: str, refined_title: str) -> int:
        """Create a new refined issue and close the original with a link."""
        if self.dry_run:
            log.info(f"  [DRY RUN] Would create refined issue from #{original_issue.number}")
            log.info(f"  [DRY RUN] Title: {refined_title}")
            return -1

        # Create new issue
        new_issue = self.repo.create_issue(
            title=refined_title,
            body=refined_body + f"\n\n---\n_Auto-refined from #{original_issue.number}_",
            labels=[self.repo.get_label(LABEL_AUTO_REFINED)],
        )

        # Close original with cross-reference
        original_issue.add_to_labels(self.repo.get_label(LABEL_REFINED_OUT))
        original_issue.remove_from_labels(self.repo.get_label(LABEL_NEEDS_REFINEMENT))
        original_issue.create_comment(
            f"🤖 Refined by FOREMAN → #{new_issue.number}\n\n"
            f"This issue has been closed because a structured version was created. "
            f"The original content is preserved here for audit purposes."
        )
        original_issue.edit(state="closed", state_reason="completed")

        log.info(f"  ✅ #{original_issue.number} → #{new_issue.number} (original closed)")
        return new_issue.number

    def create_draft_issues(self, drafts: list[dict]) -> list[int]:
        """Create draft issues from brainstorm output."""
        created = []
        for draft in drafts:
            if self.dry_run:
                log.info(f"  [DRY RUN] Would create draft: {draft['title']}")
                created.append(-1)
                continue

            issue = self.repo.create_issue(
                title=draft["title"],
                body=draft["body"] + "\n\n---\n_Auto-generated by FOREMAN brainstorm mode_",
                labels=[self.repo.get_label(LABEL_DRAFT)],
            )
            log.info(f"  📝 Created draft #{issue.number}: {draft['title']}")
            created.append(issue.number)
        return created


# ─── Claude Prompts ──────────────────────────────────────────

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
3. Expected vs actual behavior

## Component/Area
Which part of the system this touches. Choose from:
agent-loop, github-integration, telegram-bot, dashboard, infrastructure, 
vision, documentation, testing, ci-cd

## Subtasks
Break the work into concrete subtasks:
- [ ] Subtask 1
- [ ] Subtask 2
(minimum 2 subtasks)

## Complexity Estimate
- T-shirt size: XS / S / M / L / XL
- Estimated API cost: low / medium / high

Rules:
- Keep the original intent but make it precise and actionable
- If the original is vague, make reasonable assumptions and state them
- Title should be imperative: "Add X", "Fix Y", "Implement Z"
- Be concise. No filler. Every word earns its place.
"""

BRAINSTORM_SYSTEM = """You are FOREMAN, an autonomous agent that generates new development tasks
for a self-improving dev pipeline project.

You have access to:
1. VISION.md — the project's north star (goals, roadmap, architecture)
2. A list of existing open issues — so you don't create duplicates
3. A list of recently completed issues — so you know what's done

Your job: identify GAPS between the vision and current state, then propose
new issues that move the project forward.

Rules:
- Generate exactly {max_drafts} task proposals
- Each task must be concrete and implementable in 1-4 hours
- Don't duplicate existing open issues (check titles and descriptions)
- Prioritize tasks from the CURRENT phase in the roadmap
- If current phase is nearly complete, start proposing next-phase tasks
- Focus on unblocking other work first (dependencies, infrastructure)

For each task, output a JSON array of objects with:
- "title": imperative title ("Add X", "Fix Y", "Implement Z")
- "body": full issue body using the refined ticket structure from VISION.md
- "reasoning": one sentence explaining WHY this task matters now (not included in issue)

Output ONLY valid JSON. No markdown fences. No preamble."""


# ─── Agent Logic ─────────────────────────────────────────────

class ForemanAgent:
    def __init__(self, github: GitHubClient, dry_run: bool = False):
        self.github = github
        self.llm = LLMClient()
        self.router = ModelRouter(ROUTING_PROFILE)
        self.cost = CostTracker(ceiling_usd=COST_CEILING_USD)
        self.vision = load_vision()
        self.dry_run = dry_run
        self.stats = {"refined": 0, "brainstormed": 0, "skipped": 0, "failed": 0}

        log.info(f"\n{self.router.summary()}\n")

    def _complete(self, task: str, system: str, message: str, max_tokens: int = 2000):
        """Unified completion that routes to the right model and tracks cost."""
        model = self.router.get(task)
        response = self.llm.complete(model, system, message, max_tokens)

        # Record in cost tracker (create a duck-typed usage object)
        class _Usage:
            def __init__(self, inp, out):
                self.input_tokens = inp
                self.output_tokens = out
        self.cost.record(model, _Usage(response.input_tokens, response.output_tokens),
                         agent="seed", action=task)
        return response

    def refine_issue(self, issue) -> bool:
        """Refine a single issue. Returns True on success."""
        log.info(f"🔧 Refining #{issue.number}: {issue.title}")

        try:
            response = self._complete(
                task="refine",
                system=REFINE_SYSTEM,
                message=(
                    f"Issue Title: {issue.title}\n\n"
                    f"Issue Body:\n{issue.body or '(empty)'}\n\n"
                    f"Labels: {', '.join(l.name for l in issue.labels)}"
                ),
            )

            if not self.cost.check_ceiling():
                return False

            refined_body = response.text

            # Extract a better title — route to title_gen (usually cheapest model)
            title_response = self._complete(
                task="title_gen",
                system="Generate ONLY an imperative title. No explanation. No quotes. Maximum 10 words.",
                message=f"Generate a title for this issue:\n\n{refined_body}",
                max_tokens=500,
            )
            refined_title = title_response.text.strip().strip('"').strip("'")

            self.github.create_refined_issue(issue, refined_body, refined_title)
            self.stats["refined"] += 1
            tg(f"✅ Refined #{issue.number}: <b>{refined_title}</b>")
            return True

        except Exception as e:
            log.error(f"  ❌ Failed to refine #{issue.number}: {e}")
            self.stats["failed"] += 1
            return False

    def brainstorm(self) -> list[int]:
        """Generate draft issues from VISION.md + current state."""
        log.info("🧠 Entering BRAINSTORM mode")

        if not self.vision:
            log.warning("  Cannot brainstorm without VISION.md")
            return []

        # Gather context
        open_issues = self.github.get_all_open_issues()
        closed_issues = self.github.get_closed_issues(30)

        open_summary = "\n".join(
            f"- #{i.number} [{', '.join(l.name for l in i.labels)}] {i.title}"
            for i in open_issues
        )
        closed_summary = "\n".join(
            f"- #{i.number} [DONE] {i.title}"
            for i in closed_issues
        )

        try:
            response = self._complete(
                task="brainstorm",
                system=BRAINSTORM_SYSTEM.format(max_drafts=BRAINSTORM_MAX_DRAFTS),
                message=(
                    f"## VISION.md\n\n{self.vision}\n\n"
                    f"## Open Issues\n\n{open_summary or '(none)'}\n\n"
                    f"## Recently Completed\n\n{closed_summary or '(none)'}"
                ),
                max_tokens=4000,
            )

            if not self.cost.check_ceiling():
                return []

            # Parse JSON response
            raw = response.text.strip()
            # Strip markdown fences if model adds them anyway
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw.rsplit("```", 1)[0]
            raw = raw.strip()

            drafts = json.loads(raw)

            # Log reasoning (not included in issues)
            for d in drafts:
                log.info(f"  💡 {d['title']} — {d.get('reasoning', 'no reason given')}")

            created = self.github.create_draft_issues(drafts)
            self.stats["brainstormed"] += len(created)
            tg(f"🧠 Brainstormed {len(created)} new draft issues")
            return created

        except json.JSONDecodeError as e:
            log.error(f"  ❌ Failed to parse brainstorm JSON: {e}")
            log.error(f"  Raw response: {raw[:500]}")
            self.stats["failed"] += 1
            return []
        except Exception as e:
            log.error(f"  ❌ Brainstorm failed: {e}")
            self.stats["failed"] += 1
            return []

    def run_once(self, force_brainstorm: bool = False) -> dict:
        """Run a single pass of the agent loop."""
        log.info("=" * 60)
        log.info(f"🔄 FOREMAN pass @ {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")

        if not self.cost.check_ceiling():
            log.warning("💤 Parked — cost ceiling reached")
            tg(f"🚨 FOREMAN parked — cost ceiling ${COST_CEILING_USD:.2f} reached")
            return self.stats

        # Check refinement queue
        queue = self.github.get_refinement_queue()
        log.info(f"📋 Refinement queue: {len(queue)} issues")

        if queue and not force_brainstorm:
            # REFINE MODE
            for issue in queue:
                self.refine_issue(issue)
                if not self.cost.check_ceiling():
                    break
                time.sleep(2)  # Be nice to APIs
        elif len(queue) < BRAINSTORM_THRESHOLD or force_brainstorm:
            # BRAINSTORM MODE — check open draft cap first
            open_issues = self.github.get_all_open_issues()
            open_count = len(open_issues)
            if not force_brainstorm and open_count >= MAX_OPEN_DRAFTS:
                log.info(f"  💤 Skipping brainstorm — {open_count} open issues >= cap ({MAX_OPEN_DRAFTS})")
            else:
                log.info(f"  Queue ({len(queue)}) below threshold ({BRAINSTORM_THRESHOLD}) — brainstorming")
                self.brainstorm()
        else:
            log.info("  Nothing to do, waiting...")

        log.info(f"📊 Stats: {self.stats}")
        log.info(f"💰 {self.cost.summary()}")
        return self.stats

    def run_loop(self):
        """Run the agent in a continuous loop with Telegram pause/resume support."""
        log.info("🚀 FOREMAN agent starting")
        log.info(f"   Repo: {REPO_NAME}")
        log.info(f"   Poll interval: {POLL_INTERVAL_SEC}s")
        log.info(f"   Brainstorm threshold: {BRAINSTORM_THRESHOLD}")
        log.info(f"   Cost ceiling: ${COST_CEILING_USD:.2f}/session")
        log.info(f"   Models: {self.router.summary()}")
        log.info(f"   Dry run: {self.dry_run}")

        start_telegram_bot_polling()
        state.set_state(AgentState.RUNNING)

        try:
            while True:
                # Pause loop — wait until resumed or polling thread dies
                while state.get_state() == AgentState.PAUSED:
                    if not is_polling_alive():
                        log.warning("Telegram polling thread died while paused. Auto-resuming.")
                        state.set_state(AgentState.RUNNING)
                        break
                    time.sleep(15)

                self.run_once()
                log.info(f"💤 Sleeping {POLL_INTERVAL_SEC}s...")
                time.sleep(POLL_INTERVAL_SEC)
        except KeyboardInterrupt:
            log.info("\n🛑 FOREMAN stopped by user")
            log.info(f"📊 Final stats: {self.stats}")
            log.info(f"💰 {self.cost.summary()}")
            self.cost.save_session()
        finally:
            state.set_state(AgentState.IDLE)


# ─── CLI ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="FOREMAN Seed Agent")
    parser.add_argument("--once", action="store_true", help="Single pass then exit")
    parser.add_argument("--brainstorm-only", action="store_true", help="Force brainstorm mode")
    parser.add_argument("--dry-run", action="store_true", help="Log actions without touching GitHub")
    parser.add_argument("--profile", default=None, help="Routing profile: cheap, balanced, quality")
    args = parser.parse_args()

    # Override routing profile from CLI if provided
    global ROUTING_PROFILE
    if args.profile:
        ROUTING_PROFILE = args.profile

    # Validate config
    if not GITHUB_TOKEN:
        log.error("❌ GITHUB_TOKEN not set")
        sys.exit(1)
    if not REPO_NAME:
        log.error("❌ FOREMAN_REPO not set (e.g. 'youruser/foreman')")
        sys.exit(1)

    # API keys are validated lazily when a backend is first used.
    # This means you only need keys for providers you actually route to.
    # e.g. ROUTING_PROFILE=cheap with all-Gemini routing only needs GEMINI_API_KEY.

    github = GitHubClient(GITHUB_TOKEN, REPO_NAME, dry_run=args.dry_run)
    agent = ForemanAgent(github, dry_run=args.dry_run)

    if args.once or args.brainstorm_only:
        agent.run_once(force_brainstorm=args.brainstorm_only)
    else:
        agent.run_loop()


if __name__ == "__main__":
    main()
