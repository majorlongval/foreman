# Foreman Brain Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Telegram bot ("Foreman Brain") that lets the user have conversations about their project, check status, brainstorm features, and trigger actions — all from Telegram.

**Architecture:** A single Python script (`foreman_brain.py`) runs a Telegram bot using long-polling. When a message arrives, it calls Claude Sonnet with tool use. Claude can call GitHub tools (defined in `brain_tools.py`) to read project state or take actions. The existing agents (seed, implement, review) continue running on GitHub Actions unchanged. The Brain orchestrates them via labels and GitHub API.

**Tech Stack:** python-telegram-bot v20+ (async), Anthropic Python SDK (tool use), PyGithub (GitHub API), existing cost_monitor.py

---

### Task 1: Add dependencies

**Files:**
- Modify: `requirements.txt`

**Step 1: Add python-telegram-bot to requirements**

```
anthropic>=0.40.0
PyGithub>=2.1.0
python-telegram-bot>=21.0

# Optional providers — install only what you need:
# pip install google-genai     # for Gemini
# pip install openai           # for OpenAI, Groq, Together, Ollama, LM Studio
```

**Step 2: Install locally**

Run: `pip install python-telegram-bot>=21.0`

**Step 3: Commit**

```bash
git add requirements.txt
git commit -m "Add python-telegram-bot dependency for Brain"
```

---

### Task 2: Create GitHub tools module

**Files:**
- Create: `brain_tools.py`

This module defines the tool schemas (for Claude's tool use API) and their implementations (GitHub API calls via PyGithub). Each tool is a function that takes a PyGithub `repo` object and returns a string result.

**Step 1: Create `brain_tools.py` with tool schemas and implementations**

```python
"""
FOREMAN Brain Tools — GitHub tool definitions for Claude tool use.

Each tool has:
  - A schema (for the Claude API tools parameter)
  - An implementation function that takes a PyGithub repo and returns a string

Usage:
    from brain_tools import TOOL_SCHEMAS, execute_tool
    result = execute_tool("get_project_status", {}, repo)
"""

import logging

log = logging.getLogger("foreman.brain.tools")


# ─── Tool Schemas (Claude API format) ────────────────────────

TOOL_SCHEMAS = [
    {
        "name": "get_project_status",
        "description": (
            "Get an overview of the project: open issues grouped by label/status, "
            "open PRs, and recent activity. Use when the user asks 'what's going on?' "
            "or wants a status update."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_issue",
        "description": "Get full details of a specific GitHub issue by number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "number": {"type": "integer", "description": "The issue number"},
            },
            "required": ["number"],
        },
    },
    {
        "name": "get_pr",
        "description": (
            "Get details of a pull request including title, description, "
            "changed files, and review comments."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "number": {"type": "integer", "description": "The PR number"},
            },
            "required": ["number"],
        },
    },
    {
        "name": "label_issue",
        "description": (
            "Add a label to an issue. Use 'ready' to trigger the implement agent. "
            "Use 'needs-refinement' to queue it for the seed agent."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "number": {"type": "integer", "description": "Issue number"},
                "label": {
                    "type": "string",
                    "description": "Label to add (e.g. 'ready', 'needs-refinement')",
                },
            },
            "required": ["number", "label"],
        },
    },
    {
        "name": "merge_pr",
        "description": "Merge a pull request into main.",
        "input_schema": {
            "type": "object",
            "properties": {
                "number": {"type": "integer", "description": "PR number to merge"},
            },
            "required": ["number"],
        },
    },
    {
        "name": "create_issue",
        "description": (
            "Create a new GitHub issue. Use after brainstorming to capture a concrete idea. "
            "Default label is 'needs-refinement' so the seed agent will refine it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Issue title (imperative: 'Add X', 'Fix Y')",
                },
                "body": {"type": "string", "description": "Issue body with description"},
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Labels to add. Defaults to ['needs-refinement']",
                },
            },
            "required": ["title", "body"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the contents of a file from the repository's main branch.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to repo root (e.g. 'llm_client.py')",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "get_repo_tree",
        "description": "List all files in the repository.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


# ─── Tool Implementations ────────────────────────────────────


def _get_project_status(repo) -> str:
    """Summarize project state: issues by label + open PRs."""
    issues = list(repo.get_issues(state="open"))
    prs = list(repo.get_pulls(state="open"))

    # Separate real issues from PRs (GitHub API returns PRs as issues)
    real_issues = [i for i in issues if not i.pull_request]

    # Group by label
    label_order = [
        "ready",
        "foreman-implementing",
        "ready-for-review",
        "auto-refined",
        "needs-refinement",
        "draft",
    ]
    by_label = {}
    unlabeled = []
    for issue in real_issues:
        labels = [l.name for l in issue.labels]
        if not labels:
            unlabeled.append(issue)
        else:
            for label in labels:
                by_label.setdefault(label, []).append(issue)

    lines = [f"Project: {repo.full_name}\n"]

    for label in label_order:
        if label in by_label:
            lines.append(f"\n{label} ({len(by_label[label])}):")
            for i in by_label[label]:
                lines.append(f"  #{i.number}: {i.title}")

    # Any labels not in our expected order
    other_labels = set(by_label.keys()) - set(label_order)
    for label in sorted(other_labels):
        lines.append(f"\n{label} ({len(by_label[label])}):")
        for i in by_label[label]:
            lines.append(f"  #{i.number}: {i.title}")

    if unlabeled:
        lines.append(f"\nunlabeled ({len(unlabeled)}):")
        for i in unlabeled:
            lines.append(f"  #{i.number}: {i.title}")

    if prs:
        lines.append(f"\nOpen PRs ({len(prs)}):")
        for pr in prs:
            reviews = list(pr.get_reviews())
            review_status = ""
            if reviews:
                latest = reviews[-1]
                review_status = f" [{latest.state}]"
            lines.append(f"  PR #{pr.number}: {pr.title}{review_status}")
    else:
        lines.append("\nNo open PRs.")

    lines.append(f"\nTotal open issues: {len(real_issues)}")
    return "\n".join(lines)


def _get_issue(repo, number: int) -> str:
    """Get full issue details."""
    try:
        issue = repo.get_issue(number)
    except Exception as e:
        return f"Error: could not fetch issue #{number}: {e}"

    labels = ", ".join(l.name for l in issue.labels)
    lines = [
        f"Issue #{issue.number}: {issue.title}",
        f"State: {issue.state}",
        f"Labels: {labels or '(none)'}",
        f"Created: {issue.created_at}",
        f"Updated: {issue.updated_at}",
        "",
        issue.body or "(no body)",
    ]

    # Include recent comments
    comments = list(issue.get_comments())
    if comments:
        lines.append(f"\n--- Comments ({len(comments)}) ---")
        for c in comments[-5:]:  # last 5 comments
            lines.append(f"\n[{c.user.login} @ {c.created_at}]")
            lines.append(c.body[:500])

    return "\n".join(lines)


def _get_pr(repo, number: int) -> str:
    """Get PR details including diff summary and review comments."""
    try:
        pr = repo.get_pull(number)
    except Exception as e:
        return f"Error: could not fetch PR #{number}: {e}"

    lines = [
        f"PR #{pr.number}: {pr.title}",
        f"State: {pr.state} | Mergeable: {pr.mergeable}",
        f"Branch: {pr.head.ref} -> {pr.base.ref}",
        f"Changed files: {pr.changed_files} | +{pr.additions} -{pr.deletions}",
        "",
        pr.body or "(no description)",
    ]

    # Changed files
    files = list(pr.get_files())
    if files:
        lines.append(f"\n--- Changed Files ({len(files)}) ---")
        for f in files:
            lines.append(f"  {f.status}: {f.filename} (+{f.additions} -{f.deletions})")

    # Reviews
    reviews = list(pr.get_reviews())
    if reviews:
        lines.append(f"\n--- Reviews ({len(reviews)}) ---")
        for r in reviews:
            lines.append(f"\n[{r.user.login}: {r.state}]")
            if r.body:
                lines.append(r.body[:500])

    # Review comments (inline)
    review_comments = list(pr.get_review_comments())
    if review_comments:
        lines.append(f"\n--- Inline Comments ({len(review_comments)}) ---")
        for rc in review_comments[-10:]:
            lines.append(f"\n[{rc.user.login} on {rc.path}:{rc.position}]")
            lines.append(rc.body[:300])

    return "\n".join(lines)


def _label_issue(repo, number: int, label: str) -> str:
    """Add a label to an issue."""
    try:
        issue = repo.get_issue(number)
        issue.add_to_labels(label)
        return f"Added label '{label}' to issue #{number}: {issue.title}"
    except Exception as e:
        return f"Error: could not label issue #{number}: {e}"


def _merge_pr(repo, number: int) -> str:
    """Merge a PR."""
    try:
        pr = repo.get_pull(number)
        if not pr.mergeable:
            return f"PR #{number} is not mergeable. State: {pr.mergeable_state}"
        result = pr.merge()
        if result.merged:
            return f"Merged PR #{number}: {pr.title}"
        else:
            return f"Failed to merge PR #{number}: {result.message}"
    except Exception as e:
        return f"Error merging PR #{number}: {e}"


def _create_issue(repo, title: str, body: str, labels: list = None) -> str:
    """Create a new GitHub issue."""
    if labels is None:
        labels = ["needs-refinement"]
    try:
        label_objects = []
        for label_name in labels:
            try:
                label_objects.append(repo.get_label(label_name))
            except Exception:
                log.warning(f"Label '{label_name}' not found, skipping")

        issue = repo.create_issue(title=title, body=body, labels=label_objects)
        return f"Created issue #{issue.number}: {issue.title}\nLabels: {', '.join(labels)}"
    except Exception as e:
        return f"Error creating issue: {e}"


def _read_file(repo, path: str) -> str:
    """Read a file from the repo."""
    try:
        contents = repo.get_contents(path)
        text = contents.decoded_content.decode("utf-8")
        # Truncate very large files
        if len(text) > 10000:
            return text[:10000] + f"\n\n... (truncated, {len(text)} chars total)"
        return text
    except Exception as e:
        return f"Error reading '{path}': {e}"


def _get_repo_tree(repo) -> str:
    """List all files in the repo."""
    try:
        sha = repo.get_branch("main").commit.sha
        tree = repo.get_git_tree(sha, recursive=True)
        paths = sorted(item.path for item in tree.tree if item.type == "blob")
        return f"Files in {repo.full_name} ({len(paths)} files):\n" + "\n".join(
            f"  {p}" for p in paths
        )
    except Exception as e:
        return f"Error getting repo tree: {e}"


# ─── Tool Dispatcher ─────────────────────────────────────────

_TOOL_FUNCTIONS = {
    "get_project_status": lambda repo, **_: _get_project_status(repo),
    "get_issue": lambda repo, number, **_: _get_issue(repo, number),
    "get_pr": lambda repo, number, **_: _get_pr(repo, number),
    "label_issue": lambda repo, number, label, **_: _label_issue(repo, number, label),
    "merge_pr": lambda repo, number, **_: _merge_pr(repo, number),
    "create_issue": lambda repo, title, body, labels=None, **_: _create_issue(
        repo, title, body, labels
    ),
    "read_file": lambda repo, path, **_: _read_file(repo, path),
    "get_repo_tree": lambda repo, **_: _get_repo_tree(repo),
}


def execute_tool(name: str, tool_input: dict, repo) -> str:
    """Execute a tool by name. Returns result string."""
    fn = _TOOL_FUNCTIONS.get(name)
    if not fn:
        return f"Unknown tool: {name}"
    try:
        log.info(f"  Tool: {name}({tool_input})")
        result = fn(repo, **tool_input)
        log.info(f"  Tool result: {len(result)} chars")
        return result
    except Exception as e:
        log.error(f"  Tool {name} failed: {e}")
        return f"Tool error: {e}"
```

**Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('brain_tools.py').read()); print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add brain_tools.py
git commit -m "Add brain_tools: GitHub tool schemas and implementations for Brain"
```

---

### Task 3: Create the Foreman Brain

**Files:**
- Create: `foreman_brain.py`

This is the main entry point. It sets up the Telegram bot, handles messages by routing them through Claude with tool use, and manages conversation history.

**Step 1: Create `foreman_brain.py`**

```python
"""
FOREMAN Brain — conversational Telegram bot for project management.

Talks to the user via Telegram, uses Claude Sonnet with tool use to
understand intent and take actions on GitHub.

Usage:
    python foreman_brain.py                    # Run the bot
    python foreman_brain.py --repo owner/repo  # Override default repo

Requires:
    TELEGRAM_BOT_TOKEN  — Telegram bot token
    ANTHROPIC_API_KEY   — Claude API key
    GITHUB_TOKEN        — GitHub PAT with repo scope
    FOREMAN_REPO        — Default repo (e.g. "majorlongval/foreman")
"""

import os
import sys
import asyncio
import logging
import argparse

import anthropic
from github import Github
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from brain_tools import TOOL_SCHEMAS, execute_tool
from cost_monitor import CostTracker

# ─── Configuration ────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
DEFAULT_REPO = os.environ.get("FOREMAN_REPO", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
BRAIN_MODEL = os.environ.get("BRAIN_MODEL", "claude-sonnet-4-20250514")
BRAIN_MAX_TOKENS = int(os.environ.get("BRAIN_MAX_TOKENS", "4096"))
BRAIN_COST_CEILING = float(os.environ.get("BRAIN_COST_CEILING", "1.0"))

# Optional: restrict bot to specific chat IDs for security
ALLOWED_CHAT_IDS = os.environ.get("ALLOWED_CHAT_IDS", "")

# ─── Logging ──────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("foreman.brain")

# ─── System Prompt ────────────────────────────────────────────

SYSTEM_PROMPT = """You are Foreman, an autonomous project partner for software development.

You're currently focused on the repository: {repo_name}

You help the human by:
- Reporting project status (issues, PRs, what needs attention)
- Brainstorming ideas and turning them into GitHub issues when ready
- Triggering implementation by labeling issues 'ready'
- Merging PRs when asked
- Reading and discussing code from the repository
- Answering questions about the project state

When brainstorming:
- Ask questions to understand and refine the idea
- Think about edge cases and tradeoffs
- When the idea feels concrete, offer to create a GitHub issue for it
- Default label for new issues is 'needs-refinement' (the seed agent will refine it)

When reporting status:
- Be concise. Highlight what needs attention.
- Group issues by state (draft, refined, ready, in progress, under review)

Style:
- Direct and concise. No filler.
- Use short messages — this is a chat, not a document.
- Help the human make decisions efficiently.
"""

# ─── GitHub Setup ─────────────────────────────────────────────

_github_client = None
_repo_cache = {}


def get_github_repo(repo_name: str):
    """Get a PyGithub repo object. Cached per repo name."""
    global _github_client
    if _github_client is None:
        _github_client = Github(GITHUB_TOKEN)
    if repo_name not in _repo_cache:
        _repo_cache[repo_name] = _github_client.get_repo(repo_name)
    return _repo_cache[repo_name]


# ─── Claude Conversation ─────────────────────────────────────

_anthropic_client = None
_cost_tracker = CostTracker(ceiling_usd=BRAIN_COST_CEILING)


def get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _anthropic_client


def serialize_content(content) -> list:
    """Convert Anthropic content blocks to dicts for history storage."""
    result = []
    for block in content:
        if block.type == "text":
            result.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            result.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })
    return result


def process_message(user_message: str, chat_data: dict) -> str:
    """Process a user message through Claude with tool use. Returns response text."""
    history = chat_data.setdefault("history", [])
    repo_name = chat_data.get("repo", DEFAULT_REPO)

    if not repo_name:
        return (
            "No repo configured. Use /switch owner/repo to set one, "
            "or set FOREMAN_REPO environment variable."
        )

    # Add user message
    history.append({"role": "user", "content": user_message})

    # Get GitHub repo
    try:
        repo = get_github_repo(repo_name)
    except Exception as e:
        history.pop()  # remove failed message from history
        return f"Could not connect to {repo_name}: {e}"

    # Check cost ceiling
    if not _cost_tracker.check_ceiling():
        return (
            f"Cost ceiling reached (${_cost_tracker.total_cost:.4f} / "
            f"${BRAIN_COST_CEILING:.2f}). Restart the bot to reset."
        )

    client = get_anthropic_client()
    system = SYSTEM_PROMPT.format(repo_name=repo_name)

    try:
        response = client.messages.create(
            model=BRAIN_MODEL,
            max_tokens=BRAIN_MAX_TOKENS,
            system=system,
            tools=TOOL_SCHEMAS,
            messages=history,
        )
    except Exception as e:
        history.pop()
        return f"LLM error: {e}"

    # Track cost
    _cost_tracker.record(
        f"anthropic/{BRAIN_MODEL}",
        response.usage,
        agent="brain",
        action="conversation",
    )

    # Handle tool use loop (Claude may call tools, then we send results back)
    max_tool_rounds = 10
    rounds = 0
    while response.stop_reason == "tool_use" and rounds < max_tool_rounds:
        rounds += 1

        # Execute all tool calls in this response
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                log.info(f"  Tool call: {block.name}({block.input})")
                result = execute_tool(block.name, block.input, repo)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        # Add assistant response and tool results to history
        history.append({"role": "assistant", "content": serialize_content(response.content)})
        history.append({"role": "user", "content": tool_results})

        # Call Claude again with tool results
        try:
            response = client.messages.create(
                model=BRAIN_MODEL,
                max_tokens=BRAIN_MAX_TOKENS,
                system=system,
                tools=TOOL_SCHEMAS,
                messages=history,
            )
        except Exception as e:
            return f"LLM error during tool use: {e}"

        _cost_tracker.record(
            f"anthropic/{BRAIN_MODEL}",
            response.usage,
            agent="brain",
            action="tool_followup",
        )

    # Extract final text response
    text_parts = [b.text for b in response.content if hasattr(b, "text")]
    final_text = "\n".join(text_parts) or "(no response)"

    # Save assistant response to history
    history.append({"role": "assistant", "content": serialize_content(response.content)})

    # Trim history if it gets too long (keep last 40 messages)
    if len(history) > 40:
        chat_data["history"] = history[-40:]

    return final_text


# ─── Telegram Handlers ───────────────────────────────────────


def is_allowed(chat_id: int) -> bool:
    """Check if chat ID is allowed (if restrictions are configured)."""
    if not ALLOWED_CHAT_IDS:
        return True
    allowed = {int(x.strip()) for x in ALLOWED_CHAT_IDS.split(",") if x.strip()}
    return chat_id in allowed


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_chat.id):
        return
    repo = context.chat_data.get("repo", DEFAULT_REPO)
    await update.message.reply_text(
        f"Foreman here. Currently tracking: {repo or '(none)'}\n\n"
        f"Commands:\n"
        f"/new — reset conversation\n"
        f"/switch owner/repo — change project\n"
        f"/status — quick project status\n"
        f"/cost — show session cost\n\n"
        f"Or just talk to me."
    )


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_chat.id):
        return
    context.chat_data["history"] = []
    await update.message.reply_text("Fresh start. What's up?")


async def cmd_switch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_chat.id):
        return
    args = context.args
    if not args:
        current = context.chat_data.get("repo", DEFAULT_REPO)
        await update.message.reply_text(
            f"Current repo: {current or '(none)'}\n"
            f"Usage: /switch owner/repo"
        )
        return

    repo_name = args[0]
    if "/" not in repo_name:
        await update.message.reply_text("Use format: owner/repo")
        return

    # Verify repo exists
    try:
        get_github_repo(repo_name)
    except Exception as e:
        await update.message.reply_text(f"Could not access {repo_name}: {e}")
        return

    context.chat_data["repo"] = repo_name
    context.chat_data["history"] = []  # reset conversation for new project
    await update.message.reply_text(f"Switched to {repo_name}. Conversation reset.")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick status without going through the LLM."""
    if not is_allowed(update.effective_chat.id):
        return
    repo_name = context.chat_data.get("repo", DEFAULT_REPO)
    if not repo_name:
        await update.message.reply_text("No repo set. Use /switch owner/repo")
        return

    await update.effective_chat.send_action("typing")
    try:
        repo = get_github_repo(repo_name)
        from brain_tools import _get_project_status
        status = _get_project_status(repo)
        await update.message.reply_text(status)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_cost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_chat.id):
        return
    await update.message.reply_text(f"Brain {_cost_tracker.summary()}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all non-command text messages."""
    if not is_allowed(update.effective_chat.id):
        return
    if not update.message or not update.message.text:
        return

    user_message = update.message.text
    chat_id = update.effective_chat.id
    log.info(f"Message from {chat_id}: {user_message[:100]}")

    # Show typing indicator
    await update.effective_chat.send_action("typing")

    # Process in executor (all sync: Anthropic + GitHub API calls)
    loop = asyncio.get_event_loop()
    try:
        response_text = await loop.run_in_executor(
            None, process_message, user_message, context.chat_data
        )
    except Exception as e:
        log.error(f"Error processing message: {e}", exc_info=True)
        response_text = f"Something went wrong: {e}"

    # Telegram has a 4096 char limit per message
    if len(response_text) <= 4096:
        await update.message.reply_text(response_text)
    else:
        # Split into chunks
        for i in range(0, len(response_text), 4096):
            await update.message.reply_text(response_text[i : i + 4096])


# ─── Main ─────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="FOREMAN Brain — Telegram Bot")
    parser.add_argument(
        "--repo", default=None, help="Override default repo (owner/repo)"
    )
    args = parser.parse_args()

    if args.repo:
        global DEFAULT_REPO
        DEFAULT_REPO = args.repo

    # Validate config
    if not TELEGRAM_BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN not set")
        sys.exit(1)
    if not GITHUB_TOKEN:
        log.error("GITHUB_TOKEN not set")
        sys.exit(1)
    if not ANTHROPIC_API_KEY:
        log.error("ANTHROPIC_API_KEY not set")
        sys.exit(1)

    log.info(f"Foreman Brain starting")
    log.info(f"  Default repo: {DEFAULT_REPO}")
    log.info(f"  Model: {BRAIN_MODEL}")
    log.info(f"  Cost ceiling: ${BRAIN_COST_CEILING:.2f}")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("switch", cmd_switch))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("cost", cmd_cost))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
```

**Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('foreman_brain.py').read()); print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add foreman_brain.py
git commit -m "Add foreman_brain: conversational Telegram bot with Claude tool use"
```

---

### Task 4: Update configuration files

**Files:**
- Modify: `.env.example`
- Modify: `Dockerfile`

**Step 1: Update .env.example with Brain config**

Add the following section to the end of `.env.example`:

```
# ─── Brain (Telegram Bot) ───
# Required for foreman_brain.py
# BRAIN_MODEL=claude-sonnet-4-20250514
# BRAIN_MAX_TOKENS=4096
# BRAIN_COST_CEILING=1.0
# ALLOWED_CHAT_IDS=123456789  # comma-separated, empty = allow all
```

**Step 2: Update Dockerfile to support Brain**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run seed_agent by default. Override with FOREMAN_AGENT env var.
# For Brain: FOREMAN_AGENT=foreman_brain
ENV FOREMAN_AGENT=seed_agent
CMD python ${FOREMAN_AGENT}.py
```

**Step 3: Commit**

```bash
git add .env.example Dockerfile
git commit -m "Update config: add Brain env vars and Dockerfile support"
```

---

### Task 5: Smoke test

**Step 1: Verify all imports resolve**

Run: `python -c "from brain_tools import TOOL_SCHEMAS, execute_tool; print(f'{len(TOOL_SCHEMAS)} tools loaded')"`
Expected: `8 tools loaded`

Run: `python -c "from foreman_brain import SYSTEM_PROMPT, process_message; print('Brain imports OK')"`
Expected: `Brain imports OK`

**Step 2: Verify bot starts (will fail without tokens, but should get past import phase)**

Run: `python foreman_brain.py 2>&1 | head -5`
Expected: Error about `TELEGRAM_BOT_TOKEN not set` (confirming the script runs and hits config validation)

**Step 3: Test with real tokens (manual)**

Run: `python foreman_brain.py`
Expected: `Bot is running. Press Ctrl+C to stop.`

Then from Telegram:
- Send `/start` → should get welcome message
- Send "What's going on?" → should get project status via tool use
- Send `/new` → should reset conversation
- Send `/switch majorlongval/foreman` → should confirm switch

---

### Summary

| File | Action | Purpose |
|------|--------|---------|
| `requirements.txt` | Modify | Add python-telegram-bot |
| `brain_tools.py` | Create | Tool schemas + GitHub implementations |
| `foreman_brain.py` | Create | Telegram bot + Claude conversation |
| `.env.example` | Modify | Brain configuration docs |
| `Dockerfile` | Modify | Support Brain as entry point |

**Total new code:** ~400 lines across 2 new files
**Existing code changed:** 0 lines (only config files updated)
**New dependencies:** python-telegram-bot
