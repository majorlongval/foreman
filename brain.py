#!/usr/bin/env python3
"""FOREMAN Brain — the Wiggum loop entry point.

Usage:
    python brain.py

Runs one brain cycle: survey, deliberate, decide, act, reflect.
Designed to be triggered by GitHub Actions cron every 2 hours.
"""

from brain.loop import main

if __name__ == "__main__":
    main()
