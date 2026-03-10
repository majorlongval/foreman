import os
import logging
from github import Github
from llm_client import LLMClient, ModelRouter

log = logging.getLogger("foreman.brain")

# Initialize GitHub
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
gh = Github(GITHUB_TOKEN)
_repo_cache = {}

def get_github_repo(repo_name: str):
    if repo_name not in _repo_cache:
        _repo_cache[repo_name] = gh.get_repo(repo_name)
    return _repo_cache[repo_name]


# ─── System Prompt ────────────────────────────────────────────

SYSTEM_PROMPT = """You are FOREMAN, an expert software engineer specialized in managing repositories.
Your goal is to maintain the codebase by creating and managing issues.

When you identify a problem or a task:
1. Use 'create_issue' to document it.
2. If you are uncertain about the implementation, use 'search_code' to explore the codebase.
3. Use 'list_issues' to see current state.

CRITICAL: Always check for duplicates using 'create_issue' (which has built-in duplicate detection) 
before opening a new issue. Do not open redundant issues.
"""

# ─── Tool Definitions ────────────────────────────────────────

def search_code(repo, query: str):
    """Search for code in the repository."""
    results = repo.search_code(query)
    return [f"{f.path}: {f.html_url}" for f in results[:10]]

def list_issues(repo):
    """List open issues."""
    issues = repo.get_issues(state="open")
    return [f"#{i.number}: {i.title}" for i in issues[:20]]

def create_issue(repo, title: str, body: str):
    """Create a new issue if it is not a duplicate."""
    from brain_tools import _is_duplicate_issue
    
    if _is_duplicate_issue(repo, title, body):
        return "Duplicate issue detected. Not created."
    
    issue = repo.create_issue(title=title, body=body)
    return f"Created issue #{issue.number}: {issue.title}"

# ─── Tool Execution ──────────────────────────────────────────

def execute_tool(name, input_data, repo):
    if name == "search_code":
        return search_code(repo, input_data["query"])
    if name == "list_issues":
        return list_issues(repo)
    if name == "create_issue":
        return create_issue(repo, input_data["title"], input_data["body"])
    return "Unknown tool"

# ─── Brain Loop ─────────────────────────────────────────────

def process_message(repo, messages):
    client = LLMClient()
    router = ModelRouter()
    
    # Simple loop: get LLM action -> execute -> report back
    response = client.complete(
        model=router.get("implement"),
        system=SYSTEM_PROMPT,
        message=str(messages),
    )

    tool_results = []
    
    if hasattr(response.raw, "content"):
        for block in response.content:
            if block.type == "tool_use":
                log.info(f"Tool call: {block.name}")
                result = execute_tool(block.name, block.input, repo)
                
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(result)
                })

    return response.text, tool_results