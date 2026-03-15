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

# Promotion logic
AUTO_PROMOTE_DELAY_HOURS = float(os.environ.get("AUTO_PROMOTE_DELAY_HOURS", "2.0"))
AUTO_PROMOTE_MAX_PER_CYCLE = int(os.environ.get("AUTO_PROMOTE_MAX_PER_CYCLE", "3"))

# Routing profile: "cheap", "balanced", or "quality"
ROUTING_PROFILE = os.environ.get("ROUTING_PROFILE", "balanced")

# Labels
LABEL_NEEDS_REFINEMENT = "needs-refinement"
LABEL_AUTO_REFINED = "auto-refined"
LABEL_REFINED_OUT = "refined-out"  # closed originals that spawned a refined version
LABEL_DRAFT = "draft"
LABEL_READY = "ready"  # refined and ready for implementation
LABEL_HOLD = "hold"    # pause auto-promotion
LABEL_REFINEMENT_FAILED = "refinement-failed"

# Safety: labels we NEVER process through the refine pipeline
LABEL_IMPLEMENTING = "foreman-implementing"
FORBIDDEN_LABELS = {LABEL_AUTO_REFINED, LABEL_REFINED_OUT, LABEL_DRAFT, LABEL_READY, LABEL_IMPLEMENTING, LABEL_HOLD, LABEL_REFINEMENT_FAILED}

# ─── Logging ──────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("foreman")
# Suppress internal LiteLLM and Wrapper logs
logging.getLogger("litellm").setLevel(logging.WARNING)

# ─── Cost Tracking & LLM ─────────────────────────────────────

from cost_monitor import CostTracker, CloudCostMonitor, create_cost_system
from llm_client import LLMClient, ModelRouter
from telegram_notifier import notify as tg, start_telegram_bot_polling, is_polling_alive
from agent_state import agent_state_manager as state, AgentState


# ─── Vision Loader ───────────────────────────────────────────

def load_vision() -> str:
    """Load VISION.md from repo root or local fallback."""
    try:
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
    except Exception as e:
        log.error(f"Error loading VISION.md: {e}")
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
        try:
            existing = {l.name for l in self.repo.get_labels()}
            label_configs = {
                LABEL_NEEDS_REFINEMENT: "fbca04",  # yellow
                LABEL_AUTO_REFINED: "0e8a16",      # green
                LABEL_REFINED_OUT: "e4e669",       # muted yellow — closed originals
                LABEL_DRAFT: "c5def5",              # light blue
                LABEL_READY: "0075ca",              # blue — ready for implementation
                LABEL_HOLD: "d93f0b",               # orange
                LABEL_REFINEMENT_FAILED: "e11d21",  # bright red
            }
            for name, color in label_configs.items():
                if name not in existing:
                    if not self.dry_run:
                        self.repo.create_label(name=name, color=color)
                    log.info(f"  Created label: {name}")
        except Exception as e:
            log.error(f"Error ensuring labels: {e}")

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
        """Get open issues labeled 'auto-refined', paginated (don't exhaust all pages)."""
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

    def get_label_applied_at(self, issue, label_name: str):
        """
        Find when a label was most recently applied to an issue using timeline events.
        Returns a timezone-aware datetime, or None if the event is not found.
        """
        try:
            applied_at = None
            for event in issue.get_events():
                if event.event == "labeled" and event.label and event.label.name == label_name:
                    ts = event.created_at
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if applied_at is None or ts > applied_at:
                        applied_at = ts
            return applied_at
        except Exception as e:
            log.warning(f"  Could not fetch timeline for #{issue.number}: {e}")
            return None

    def get_stale_refined_issues(self, delay_hours: float) -> list:
        """
        Return open 'auto-refined' issues (without 'hold') where the label was
        applied more than delay_hours ago, determined via timeline events.
        Falls back to issue.created_at if no labeled event is found.
        """
        try:
            issues = self.repo.get_issues(
                state="open",
                labels=[LABEL_AUTO_REFINED],
                sort="created",
                direction="asc",
            )
            now = datetime.now(timezone.utc)
            stale = []
            for issue in issues:
                labels = {l.name for l in issue.labels}
                if LABEL_HOLD in labels:
                    continue
                labeled_at = self.get_label_applied_at(issue, LABEL_AUTO_REFINED)
                if labeled_at is None:
                    # Fall back to issue creation time
                    labeled_at = issue.created_at
                    if labeled_at.tzinfo is None:
                        labeled_at = labeled_at.replace(tzinfo=timezone.utc)
                age_hours = (now - labeled_at).total_seconds() / 3600
                if age_hours >= delay_hours:
                    stale.append((issue, labeled_at, age_hours))
            return stale
        except Exception as e:
            log.error(f"Error fetching stale refined issues: {e}")
            return []

    def get_all_open_issues(self) -> list:
        """Get all open issues for context (brainstorm dedup)."""
        try:
            return list(self.repo.get_issues(state="open"))
        except Exception as e:
            log.error(f"Error fetching open issues: {e}")
            raise

    def get_closed_issues(self, count: int = 50) -> list:
        """Get recently closed issues for context."""
        try:
            return list(self.repo.get_issues(state="closed", sort="updated", direction="desc")[:count])
        except Exception as e:
            log.error(f"Error fetching closed issues: {e}")
            return []

    def create_refined_issue(self, original_issue, refined_body: str, refined_title: str) -> int:
        """Create a new refined issue and close the original with a link."""
        try:
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
        except Exception as e:
            log.error(f"Error creating refined issue: {e}")
            raise

    def create_draft_issues(self, drafts: list[dict]) -> list[tuple[int, str]]:
        """Create draft issues from brainstorm output. Returns list of (number, title)."""
        created = []
        for draft in drafts:
            try:
                if self.dry_run:
                    log.info(f"  [DRY RUN] Would create draft: {draft['title']}")
                    created.append((-1, draft['title']))
                    continue

                issue = self.repo.create_issue(
                    title=draft["title"],
                    body=draft["body"] + "\n\n---\n_Auto-generated by FOREMAN brainstorm mode_",
                    labels=[self.repo.get_label(LABEL_DRAFT)],
                )
                log.info(f"  📝 Created draft #{issue.number}: {draft['title']}")
                created.append((issue.number, draft["title"]))
            except Exception as e:
                title = draft.get("title", "Unknown") if isinstance(draft, dict) else str(draft)
                log.error(f"Error creating draft issue '{title}': {e}")
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

## Tests
Provide concrete definition-of-done via pytest stubs.
Include at least two `pytest` function stubs: one happy path and one edge/failure case.
Use Given/When/Then comment structure inside the stubs.
Tests must use mocks/fixtures for external boundaries (GitHub API, LLMs).

Example:
def test_happy_path_example(mocker):
    # Given: ...
    # When: ...
    # Then: ...
    pass

## Complexity Estimate
- T-shirt size: XS / S / M / L / XL
- Estimated API cost: low / medium / high

Rules:
- Keep the original intent but make it precise and actionable
- If the original is vague, make reasonable assumptions and state them
- Title should be imperative: "Add X", "Fix Y", "Implement Z"
- Be concise. No filler. Every word earns its place.
- EVERY refined issue MUST include the ## Tests section with at least two stubs.
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
    def __init__(self, github: GitHubClient, dry_run: bool = False, once: bool = False):
        self.github = github
        self.llm = LLMClient()
        self.router = ModelRouter(ROUTING_PROFILE)
        self.cost = CostTracker(ceiling_usd=COST_CEILING_USD)
        self.vision = load_vision()
        self.dry_run = dry_run
        self.once = once
        self.stats = {"refined": 0, "brainstormed": 0, "skipped": 0, "failed": 0, "promoted": 0}

        log.info(f"\n{self.router.summary()}\n")

    def _complete(self, task: str, system: str, message: str, max_tokens: int = 2000):
        """Unified completion that routes to the right model and tracks cost."""
        try:
            model = self.router.get(task)
            response = self.llm.complete(model, system, message, max_tokens)

            # Record in cost tracker (create a duck-typed usage object)
            class _Usage:
                def __init__(self, inp, out):
                    self.input_tokens = inp
                    self.output_tokens = out
            
            usage = _Usage(response.input_tokens, response.output_tokens)
            cost_value = self.cost.record(model, usage, agent="seed", action=task)
            log.info(f"  💰 Cost: ${cost_value:.4f} | Model: {model}")
            return response
        except Exception as e:
            log.error(f"Error in LLM completion: {e}")
            raise

    def auto_promote_refined_issues(self) -> int:
        """Find 'auto-refined' issues labeled longer than threshold ago and promote to 'ready'."""
        log.info("⏫ Checking for issues to auto-promote...")
        promoted_count = 0

        try:
            stale = self.github.get_stale_refined_issues(AUTO_PROMOTE_DELAY_HOURS)

            for issue, labeled_at, age_hours in stale:
                if promoted_count >= AUTO_PROMOTE_MAX_PER_CYCLE:
                    log.info(f"  Reached max auto-promotions per cycle ({AUTO_PROMOTE_MAX_PER_CYCLE})")
                    break

                log.info(f"  ⏫ Promoting #{issue.number} to ready (labeled {age_hours:.1f}h ago)")

                if self.dry_run:
                    log.info(f"  [DRY RUN] Would promote #{issue.number} and send notification")
                else:
                    try:
                        # Relabel
                        issue.remove_from_labels(LABEL_AUTO_REFINED)
                        issue.add_to_labels(LABEL_READY)

                        # Comment
                        issue.create_comment(
                            f"⏫ Auto-promoted to `ready` after {AUTO_PROMOTE_DELAY_HOURS}h delay.\n\n"
                            f"Implementation agent will pick this up soon. Add `{LABEL_HOLD}` label to pause."
                        )

                        # Notify
                        tg(f"⏫ Auto-promoted #{issue.number} to <b>ready</b>: {issue.title}")
                    except Exception as e:
                        log.error(f"  ❌ Failed to promote #{issue.number}: {e}")
                        continue

                promoted_count += 1
                self.stats["promoted"] += 1

        except Exception as e:
            log.error(f"Error during auto-promotion: {e}")

        return promoted_count

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

            # Validation: Ensure ## Tests section and at least 2 pytest stubs
            if "## tests" not in refined_body.lower() or refined_body.count("def test_") < 2:
                log.warning(f"  ⚠️ Refinement of #{issue.number} failed validation: missing or insufficient ## Tests section")
                try:
                    if not self.dry_run:
                        issue.create_comment("⚠️ **FOREMAN Auto-Refinement Failed**\nThe LLM failed to generate the required `## Tests` section with at least 2 pytest stubs. Human intervention required.")
                        issue.add_to_labels(LABEL_REFINEMENT_FAILED)
                    else:
                        log.info(f"  [DRY RUN] Would comment and label #{issue.number} as {LABEL_REFINEMENT_FAILED}")
                except Exception as e:
                    log.warning(f"Could not comment or label issue #{issue.number}: {e}")
                self.stats["failed"] += 1
                return False

            # Extract a better title — route to title_gen (usually cheapest model)
            title_response = self._complete(
                task="title_gen",
                system="Generate ONLY an imperative title. No explanation. No quotes. Maximum 10 words.",
                message=f"Generate a title for this issue:\n\n{refined_body}",
                max_tokens=500,
            )
            refined_title = title_response.text.strip().strip('"').strip("'")
            log.info(f"  ✨ Refined title: {refined_title}")

            self.github.create_refined_issue(issue, refined_body, refined_title)
            self.stats["refined"] += 1
            tg(f"✅ Refined #{issue.number}: <b>{refined_title}</b>")
            return True

        except Exception as e:
            log.error(f"  ❌ Failed to refine #{issue.number}: {e}")
            self.stats["failed"] += 1
            return False

    def brainstorm(self) -> list[tuple[int, str]]:
        """Generate draft issues from VISION.md + current state."""
        log.info("🧠 Entering BRAINSTORM mode")

        if not self.vision:
            log.warning("  Cannot brainstorm without VISION.md")
            return []

        # Gather context
        try:
            open_issues = self.github.get_all_open_issues()
            closed_issues = self.github.get_closed_issues(30)
            log.info(f"  📊 Brainstorm context: {len(open_issues)} open issues, {len(closed_issues)} closed issues")

            open_summary = "\n".join(
                f"- #{i.number} [{', '.join(l.name for l in i.labels)}] {i.title}"
                for i in open_issues
            )
            closed_summary = "\n".join(
                f"- #{i.number} [DONE] {i.title}"
                for i in closed_issues
            )

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
                if isinstance(d, dict):
                    log.info(f"  💡 {d.get('title', 'Unknown')} — {d.get('reasoning', 'no reason given')}")
                else:
                    log.info(f"  💡 {d}")
            if not self.once:
                log.info("  ⏸️ Pausing agent after brainstorm as requested by VISION.md contract.")
                state.set_state(AgentState.PAUSED)

            created = self.github.create_draft_issues(drafts)
            self.stats["brainstormed"] += len(created)
            
            if created:
                bullets = "\n".join([f"• #{n}: {t}" for n, t in created])
                msg = (
                    f"🧠 Brainstorm complete — created {len(created)} draft issue(s):\n"
                    f"{bullets}\n\n"
                    "Go review and label the ones you want → needs-refinement.\n"
                    "Agent is paused. Send /resume when ready."
                )
            else:
                msg = "🧠 Brainstorm complete, but no drafts were created. Agent is paused."
            
            try:
                if not self.dry_run:
                    tg(msg)
                else:
                    log.info(f"  [DRY RUN] Would send Telegram: {msg}")
            except Exception as e:
                log.error(f"Failed to send Telegram notification: {e}")

            return created

        except json.JSONDecodeError as e:
            if not self.once:
                log.warning("  ⏸️ Pausing agent on JSON decode failure to prevent infinite retry loop.")
                state.set_state(AgentState.PAUSED)
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

        try:
            if not self.cost.check_ceiling():
                log.warning("💤 Parked — cost ceiling reached")
                tg(f"🚨 FOREMAN parked — cost ceiling ${COST_CEILING_USD:.2f} reached")
                return self.stats

            # Auto-promote eligible issues
            self.auto_promote_refined_issues()

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
        except Exception as e:
            log.error(f"Error in run_once: {e}")
            if not getattr(self, "once", False):
                log.warning("  ⏸️ Pausing agent on unexpected error to prevent infinite retry loop.")
                state.set_state(AgentState.PAUSED)
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
                try:
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
                except Exception as e:
                    log.error(f"Error in main loop iteration: {e}")
                    log.warning("  ⏸️ Pausing agent on unexpected loop error to prevent infinite retry loop.")
                    state.set_state(AgentState.PAUSED)
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
    agent = ForemanAgent(github, dry_run=args.dry_run, once=args.once)

    if args.once or args.brainstorm_only:
        agent.run_once(force_brainstorm=args.brainstorm_only)
    else:
        agent.run_loop()


if __name__ == "__main__":
    main()