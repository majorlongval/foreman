"""
FOREMAN Feedback Processor
Orchestrates the post-review pipeline: auto-merge, human review, or automated fixes.
Calculates a confidence score based on verdict, issue severity, and PR size.

Usage:
    python feedback_processor.py <pr_number>
"""

import os
import re
import logging
from github import Github, GithubException
from telegram_notifier import notify as tg_notify
from fix_agent import FixAgent

log = logging.getLogger("foreman.feedback_processor")

# --- Configuration ---
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_NAME = os.environ.get("FOREMAN_REPO", "")
MAX_FIX_ATTEMPTS = int(os.environ.get("MAX_FIX_ATTEMPTS", "3"))
HIGH_CONFIDENCE_THRESHOLD = float(os.environ.get("HIGH_CONFIDENCE_THRESHOLD", "0.8"))
MEDIUM_CONFIDENCE_THRESHOLD = float(os.environ.get("MEDIUM_CONFIDENCE_THRESHOLD", "0.5"))

class FeedbackProcessor:
    def __init__(self):
        """Initializes the processor with GitHub and Fixer agent access."""
        try:
            if not GITHUB_TOKEN:
                raise ValueError("GITHUB_TOKEN environment variable is missing")
            if not REPO_NAME:
                raise ValueError("FOREMAN_REPO environment variable is missing")
            
            # Using imported Auth to match existing style if possible, or direct token
            self.gh = Github(auth=__import__("github").Auth.Token(GITHUB_TOKEN))
            self.repo = self.gh.get_repo(REPO_NAME)
            
            # Initialize the Fixer agent to reuse its patching and merging logic
            self.fixer = FixAgent(GITHUB_TOKEN, REPO_NAME)
            log.info(f"FeedbackProcessor initialized for {REPO_NAME}")
        except Exception as e:
            log.error(f"Failed to initialize FeedbackProcessor: {e}")
            raise

    def calculate_confidence(self, verdict: str, body: str, additions: int, deletions: int) -> float:
        """
        Calculates a confidence score (0.0 - 1.0) based on review metadata.
        Weights: Verdict (Base), Severity (Penalty), PR Size (Multiplier).
        """
        # 1. Verdict Weight
        verdict_map = {
            "APPROVED": 1.0,
            "COMMENTED": 0.6,
            "CHANGES_REQUESTED": 0.2,
            "DISMISSED": 0.0
        }
        base_score = verdict_map.get(verdict.upper(), 0.5)

        # 2. Issue Penalties
        # Critical issues indicate high uncertainty or blocking bugs
        critical_count = len(re.findall(r"\[CRITICAL\]", body, re.IGNORECASE))
        # Important issues indicate notable concerns
        important_count = len(re.findall(r"\[IMPORTANT\]", body, re.IGNORECASE))
        
        penalty = (critical_count * 0.3) + (important_count * 0.1)
        score = base_score - penalty
        
        # 3. Size Multiplier (Risk scaling)
        total_lines = additions + deletions
        if total_lines < 50:
            multiplier = 1.0
        elif total_lines < 200:
            multiplier = 0.9
        else:
            multiplier = 0.7
            
        final_score = score * multiplier
        result = max(0.0, min(1.0, final_score))
        
        log.info(f"  Confidence: {result:.2f} (Verdict: {verdict}, Penalty: -{penalty}, Size Mult: {multiplier})")
        return result

    def process_review_feedback(self, pr_number: int):
        """
        Processes the latest FOREMAN review for a PR and routes it to the appropriate path.
        """
        try:
            pr = self.repo.get_pull(pr_number)
            log.info(f"--- Feedback Processor: PR #{pr_number} ---")

            # Fetch all reviews and find the most recent one by FOREMAN
            reviews = list(pr.get_reviews())
            foreman_reviews = [r for r in reviews if r.body and "Review by FOREMAN" in r.body]
            
            if not foreman_reviews:
                log.info(f"  No FOREMAN reviews found for PR #{pr_number}. Nothing to process.")
                return

            latest_review = foreman_reviews[-1]
            verdict = latest_review.state # APPROVED, CHANGES_REQUESTED, or COMMENTED
            body = latest_review.body
            
            # Track cycles using FixAgent's internal logic
            fix_cycles = self.fixer._count_fix_cycles(pr)
            
            # Calculate Confidence Score
            score = self.calculate_confidence(verdict, body, pr.additions, pr.deletions)
            
            log.info(f"  Final Score: {int(score*100)}% | Verdict: {verdict} | Cycle: {fix_cycles}/{MAX_FIX_ATTEMPTS}")

            # --- Routing Logic ---

            # High Confidence Path: Auto-merge
            if score >= HIGH_CONFIDENCE_THRESHOLD and verdict == "APPROVED":
                self._handle_high_confidence(pr)
            
            # Low Confidence Path: Trigger Fix Agent
            elif verdict == "CHANGES_REQUESTED" or score < MEDIUM_CONFIDENCE_THRESHOLD:
                self._handle_low_confidence(pr, fix_cycles)
            
            # Medium Confidence Path: Notify Human
            else:
                self._handle_medium_confidence(pr, score, verdict)

        except Exception as e:
            log.error(f"Error processing review feedback for PR #{pr_number}: {e}", exc_info=True)

    def _handle_high_confidence(self, pr):
        """Attempts auto-merge for high-confidence approvals."""
        log.info(f"  [PATH] High Confidence - Routing to Auto-merge")
        try:
            # Respect global auto-merge setting before proceeding
            if os.environ.get("AUTO_MERGE_ENABLED", "false").lower() != "true":
                log.info("  Auto-merge is disabled by environment config. Routing to human review.")
                self._handle_medium_confidence(pr, 0.9, "APPROVED (Auto-merge disabled)")
                return

            # Delegate to FixAgent's robust merge logic (checks CI, labels, and sends TG notification)
            self.fixer._try_auto_merge(pr)
        except Exception as e:
            log.error(f"  Auto-merge routine failed for PR #{pr.number}: {e}")
            tg_notify(f"❌ <b>High Confidence Auto-merge Failed</b>\nPR #{pr.number}: {e}\n{pr.html_url}")

    def _handle_medium_confidence(self, pr, score: float, verdict: str):
        """Notifies a human operator for manual review."""
        log.info(f"  [PATH] Medium Confidence - Notifying Human")
        message = (
            f"⚖️ <b>FOREMAN Review: Human Intervention Requested</b>\n"
            f"PR #{pr.number}: {pr.title}\n"
            f"Confidence Score: {int(score*100)}%\n"
            f"Verdict: {verdict}\n"
            f"Reason: Score is within medium confidence bounds. Manual approval required to proceed.\n\n"
            f"🔗 <a href='{pr.html_url}'>View Pull Request</a>"
        )
        tg_notify(message)

    def _handle_low_confidence(self, pr, fix_cycles: int):
        """Triggers the Fix Agent to attempt automated repairs."""
        log.info(f"  [PATH] Low Confidence - Triggering Fix Agent")
        
        # Prevent infinite loops
        if fix_cycles >= MAX_FIX_ATTEMPTS:
            log.warning(f"  Max fix attempts ({MAX_FIX_ATTEMPTS}) reached for PR #{pr.number}. Escalating.")
            tg_notify(
                f"🛑 <b>Fix Cycle Limit Reached</b>\n"
                f"PR #{pr.number} still has issues after {fix_cycles} cycles.\n"
                f"Manual intervention required — automated fixing stopped.\n"
                f"{pr.html_url}"
            )
            return

        try:
            # Delegate to FixAgent to analyze review comments and apply patches
            self.fixer.fix_pr(pr)
        except Exception as e:
            log.error(f"  Fix Agent failed to execute for PR #{pr.number}: {e}")
            tg_notify(f"❌ <b>Fix Agent Error</b>\nPR #{pr.number}: {e}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="FOREMAN Feedback Processor")
    parser.add_argument("pr", type=int, help="The Pull Request number to evaluate")
    args = parser.parse_args()

    # Match existing logging format
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    try:
        processor = FeedbackProcessor()
        processor.process_review_feedback(args.pr)
    except Exception as e:
        log.critical(f"Feedback Processor failed to run: {e}")
        exit(1)