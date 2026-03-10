"""
FOREMAN Brain — conversational Telegram bot powered by Claude with tool use.

The Brain is the human interface to Foreman's autonomous pipeline.  It holds
per-chat conversations with Claude (Sonnet), backed by GitHub tool calls
defined in brain_tools.py.

Usage:
  python foreman_brain.py                    # Run the bot
  python foreman_brain.py --repo owner/repo  # Override default repo
"""

import os
import sys
import asyncio
import logging
import argparse

import anthropic
from github import Github

from brain_tools import TOOL_SCHEMAS, execute_tool, get_project_status
from cost_monitor import CostTracker

# ─── Configuration ────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
DEFAULT_REPO = os.environ.get("FOREMAN_REPO", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
BRAIN_MODEL = os.environ.get("BRAIN_MODEL", "claude-sonnet-4-6")
BRAIN_MAX_TOKENS = int(os.environ.get("BRAIN_MAX_TOKENS", "4096"))
BRAIN_COST_CEILING = float(os.environ.get("BRAIN_COST_CEILING", "1.0"))
ALLOWED_CHAT_IDS = os.environ.get("ALLOWED_CHAT_IDS", "")  # comma-separated, empty = allow all

# ─── Logging ──────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("foreman.brain")

# ─── Cost Tracking ────────────────────────────────────────────

_cost_tracker = CostTracker(ceiling_usd=BRAIN_COST_CEILING)

# ─── GitHub (lazy-init) ──────────────────────────────────────

_github_client = None
_repo_cache: dict = {}


def _get_github():
    global _github_client
    if _github_client is None:
        _github_client = Github(GITHUB_TOKEN)
    return _github_client


def get_github_repo(repo_name: str):
    """Return a PyGithub repo object, cached by name."""
    if repo_name not in _repo_cache:
        _repo_cache[repo_name] = _get_github().get_repo(repo_name)
    return _repo_cache[repo_name]


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
- Help the human make decisions efficiently."""

# ─── Content Serialization ───────────────────────────────────


def serialize_content(content) -> list[dict]:
    """Convert Anthropic ContentBlock objects to plain dicts for history storage."""
    serialized = []
    for block in content:
        if block.type == "text":
            serialized.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            serialized.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })
        else:
            # Preserve unknown block types (e.g. thinking) as-is
            try:
                serialized.append(block.model_dump())
            except Exception:
                log.warning(f"Skipping unknown content block type: {block.type}")
    return serialized


# ─── Core Conversation Logic ─────────────────────────────────


def process_message(user_message: str, chat_data: dict) -> str:
    """Process a user message through Claude with tool use.  Synchronous."""
    history = chat_data.setdefault("history", [])
    repo_name = chat_data.get("repo", DEFAULT_REPO)

    if not repo_name:
        return "No repo configured. Use /switch owner/repo to set one."

    # Append user message
    history.append({"role": "user", "content": user_message})

    # Get repo object
    try:
        repo = get_github_repo(repo_name)
    except Exception as e:
        history.pop()  # undo append on failure
        log.error(f"Failed to get repo '{repo_name}': {e}")
        return f"Failed to access repo '{repo_name}': {e}"

    # Check cost ceiling
    if not _cost_tracker.check_ceiling():
        history.pop()
        return (
            f"Cost ceiling reached ({_cost_tracker.summary()}). "
            "Wait for a new session or raise BRAIN_COST_CEILING."
        )

    # Initial Claude call
    client = anthropic.Anthropic()
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
        log.error(f"Anthropic API error: {e}")
        return f"Claude API error: {e}"

    _cost_tracker.record(BRAIN_MODEL, response.usage, agent="brain", action="chat")

    # Tool use loop (max 10 rounds)
    rounds = 0
    while response.stop_reason == "tool_use" and rounds < 10:
        rounds += 1

        # Serialize and store assistant response
        assistant_content = serialize_content(response.content)
        history.append({"role": "assistant", "content": assistant_content})

        # Execute each tool call and build results
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                log.info(f"Tool call: {block.name}")
                result = execute_tool(block.name, block.input, repo)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(result),
                })

        history.append({"role": "user", "content": tool_results})

        # Check ceiling before next call
        if not _cost_tracker.check_ceiling():
            # Roll back orphaned assistant+tool_result entries
            del history[-2:]
            return (
                "I was using tools but hit the cost ceiling mid-conversation. "
                f"({_cost_tracker.summary()})"
            )

        try:
            response = client.messages.create(
                model=BRAIN_MODEL,
                max_tokens=BRAIN_MAX_TOKENS,
                system=system,
                tools=TOOL_SCHEMAS,
                messages=history,
            )
        except Exception as e:
            # Roll back orphaned assistant+tool_result entries
            del history[-2:]
            log.error(f"Anthropic API error during tool loop: {e}")
            return f"Claude API error during tool use: {e}"

        _cost_tracker.record(BRAIN_MODEL, response.usage, agent="brain", action="tool_loop")

    # Extract final text
    text_parts = []
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
    final_text = "\n".join(text_parts) or "(no response)"

    # Store final assistant message
    history.append({"role": "assistant", "content": serialize_content(response.content)})

    # Trim history to last 40 messages
    if len(history) > 40:
        chat_data["history"] = history[-40:]

    return final_text


# ─── Telegram Security & Concurrency ────────────────────────

_chat_locks: dict[int, asyncio.Lock] = {}


def is_allowed(chat_id: int) -> bool:
    """Check if a chat ID is in the allow-list (empty = allow all)."""
    if not ALLOWED_CHAT_IDS:
        return True
    allowed = {int(cid.strip()) for cid in ALLOWED_CHAT_IDS.split(",") if cid.strip()}
    return chat_id in allowed


# ─── Telegram Handlers ──────────────────────────────────────

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start — welcome message."""
    if not is_allowed(update.effective_chat.id):
        return
    repo = context.chat_data.get("repo", DEFAULT_REPO) or "(not set)"
    await update.message.reply_text(
        f"Foreman Brain online.\n"
        f"Repo: {repo}\n\n"
        f"Commands:\n"
        f"  /new — fresh conversation\n"
        f"  /switch owner/repo — change repo\n"
        f"  /status — quick project status\n"
        f"  /cost — session cost summary\n"
        f"  /stop — shut down the bot\n\n"
        f"Or just send a message to chat."
    )


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /new — clear conversation history."""
    if not is_allowed(update.effective_chat.id):
        return
    context.chat_data["history"] = []
    await update.message.reply_text("Fresh start. What's up?")


async def cmd_switch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /switch owner/repo — change the active repository."""
    if not is_allowed(update.effective_chat.id):
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /switch owner/repo")
        return

    repo_name = args[0]
    try:
        get_github_repo(repo_name)
    except Exception as e:
        await update.message.reply_text(f"Can't access '{repo_name}': {e}")
        return

    context.chat_data["repo"] = repo_name
    context.chat_data["history"] = []
    await update.message.reply_text(f"Switched to {repo_name}. History cleared.")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status — quick status bypass, no LLM."""
    if not is_allowed(update.effective_chat.id):
        return
    repo_name = context.chat_data.get("repo", DEFAULT_REPO)
    if not repo_name:
        await update.message.reply_text("No repo configured. Use /switch owner/repo")
        return

    await update.message.reply_chat_action(ChatAction.TYPING)
    try:
        repo = get_github_repo(repo_name)
        loop = asyncio.get_running_loop()
        status = await loop.run_in_executor(None, get_project_status, repo)
    except Exception as e:
        status = f"Error getting status: {e}"

    # Split if needed
    for chunk in _split_message(status):
        await update.message.reply_text(chunk)


async def cmd_cost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cost — show session cost summary."""
    if not is_allowed(update.effective_chat.id):
        return
    await update.message.reply_text(_cost_tracker.summary())


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stop — shut down the bot gracefully."""
    if not is_allowed(update.effective_chat.id):
        return
    await update.message.reply_text(
        f"Shutting down. {_cost_tracker.summary()}"
    )
    # Send SIGINT to trigger clean shutdown (same as Ctrl+C)
    import signal
    os.kill(os.getpid(), signal.SIGINT)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle free-text messages — run through Claude."""
    if not is_allowed(update.effective_chat.id):
        return
    if not update.message or not update.message.text:
        return

    # Serialize per-chat to avoid concurrent mutation of chat_data
    chat_id = update.effective_chat.id
    lock = _chat_locks.setdefault(chat_id, asyncio.Lock())

    async with lock:
        await update.message.reply_chat_action(ChatAction.TYPING)

        try:
            loop = asyncio.get_running_loop()
            reply = await loop.run_in_executor(
                None, process_message, update.message.text, context.chat_data,
            )
        except Exception as e:
            log.error(f"process_message failed: {e}", exc_info=True)
            reply = f"Something went wrong: {e}"

        for chunk in _split_message(reply):
            await update.message.reply_text(chunk)


# ─── Helpers ─────────────────────────────────────────────────


def _split_message(text: str, limit: int = 4096) -> list[str]:
    """Split text into chunks that fit Telegram's message limit."""
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        chunks.append(text[:limit])
        text = text[limit:]
    return chunks


# ─── Main ────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="FOREMAN Brain — Telegram bot")
    parser.add_argument("--repo", default=None, help="Override default repo (owner/repo)")
    args = parser.parse_args()

    if args.repo:
        global DEFAULT_REPO
        DEFAULT_REPO = args.repo

    # Validate required env vars
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not GITHUB_TOKEN:
        missing.append("GITHUB_TOKEN")
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if missing:
        log.error(f"Missing required env vars: {', '.join(missing)}")
        sys.exit(1)

    log.info("FOREMAN Brain starting")
    log.info(f"  Repo: {DEFAULT_REPO or '(not set, use /switch)'}")
    log.info(f"  Model: {BRAIN_MODEL}")
    log.info(f"  Max tokens: {BRAIN_MAX_TOKENS}")
    log.info(f"  Cost ceiling: ${BRAIN_COST_CEILING:.2f}")
    log.info(f"  Allowed chats: {ALLOWED_CHAT_IDS or '(all)'}")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("switch", cmd_switch))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("cost", cmd_cost))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Polling for updates...")
    app.run_polling()


if __name__ == "__main__":
    main()
