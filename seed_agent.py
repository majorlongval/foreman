"""
FOREMAN Seed Agent — v0.1 (Legacy Wrapper)
The smallest unit that can work on itself.

This file now acts as a thin wrapper around specialized Brainstorm and Refine agents.
New workflows and manual triggers should use the specific agents directly.

Modes:
  REFINE     — Processes issues labeled 'needs-refinement' via refine_agent.py
  BRAINSTORM — Generates new draft issues from VISION.md via brainstorm_agent.py

Usage:
  python seed_agent.py                    # Legacy loop mode
  python seed_agent.py --once             # Single pass then exit
  python seed_agent.py --brainstorm-only  # Force brainstorm mode only
  python seed_agent.py --dry-run          # Pass dry-run to specialized agents
"""

import os
import sys
import time
import argparse
import logging
import subprocess

# ─── Configuration ────────────────────────────────────────────

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_NAME = os.environ.get("FOREMAN_REPO", "")
POLL_INTERVAL_SEC = int(os.environ.get("POLL_INTERVAL", "60"))

# ─── Logging ──────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("foreman-legacy")

# ─── Execution Logic ──────────────────────────────────────────

def run_agent(script: str, args: argparse.Namespace):
    """Executes a sub-agent script with the provided CLI arguments."""
    cmd = [sys.executable, script]
    
    if args.once:
        cmd.append("--once")
    if args.dry_run:
        cmd.append("--dry-run")
    if args.profile:
        cmd.extend(["--profile", args.profile])
        
    log.info(f"▶️  Invoking specialized agent: {script}")
    try:
        # Use subprocess.run to wait for completion of the pass
        subprocess.run(cmd, check=False)
    except Exception as e:
        log.error(f"❌ Execution failed for {script}: {e}")

# ─── Main ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="FOREMAN Seed Agent (Legacy Wrapper)")
    parser.add_argument("--once", action="store_true", help="Single pass then exit")
    parser.add_argument("--brainstorm-only", action="store_true", help="Force brainstorm mode")
    parser.add_argument("--dry-run", action="store_true", help="Log actions without touching GitHub")
    parser.add_argument("--profile", default=None, help="Routing profile: cheap, balanced, or quality")
    args = parser.parse_args()

    # Safety checks
    if not GITHUB_TOKEN or not REPO_NAME:
        log.error("❌ Environment variables GITHUB_TOKEN and FOREMAN_REPO must be set.")
        sys.exit(1)

    log.info("⚠️  DEPRECATION NOTICE: seed_agent.py is now a wrapper. Use brainstorm_agent.py or refine_agent.py directly.")

    try:
        while True:
            try:
                if args.brainstorm_only:
                    run_agent("brainstorm_agent.py", args)
                else:
                    # In legacy mode, we process refinement then brainstorm
                    run_agent("refine_agent.py", args)
                    run_agent("brainstorm_agent.py", args)
                    
            except Exception as e:
                log.error(f"Error in legacy wrapper loop: {e}")

            if args.once:
                log.info("✅ Single pass finished.")
                break
                
            log.info(f"💤 Sleeping {POLL_INTERVAL_SEC}s...")
            time.sleep(POLL_INTERVAL_SEC)
            
    except KeyboardInterrupt:
        log.info("\n🛑 Legacy wrapper stopped by user.")
    except Exception as e:
        log.error(f"Fatal exception: {e}")
    finally:
        log.info("🏁 Legacy wrapper shut down.")

if __name__ == "__main__":
    main()