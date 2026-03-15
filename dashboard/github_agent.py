import os
import logging
import json
import requests
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from llm_client import LLMClient

log = logging.getLogger("foreman.github_agent")

@dataclass
class ToolResult:
    """Result of a tool execution."""
    success: bool
    output: str
    error: Optional[str] = None

class GitHubAgent:
    """
    A conversational agent that can interact with GitHub repositories.
    It uses an LLM to process user intent and executes tools via the GitHub API.
    """

    def __init__(self, repo_full_name: str, github_token: str):
        self.repo_full_name = repo_full_name
        self.github_token = github_token
        self.base_url = "https://api.github.com"
        self.headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.v3+json"
        }
        self.llm = LLMClient()
        self.model = os.environ.get("AGENT_MODEL", "anthropic/claude-3-5-sonnet-20241022")
        
        # Define available tools for the LLM
        self.tools = [
            {
                "name": "list_issues",
                "description": "List open issues in the repository.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "state": {"type": "string", "enum": ["open", "closed", "all"], "default": "open"}
                    }
                }
            },
            {
                "name": "read_issue",
                "description": "Read the full content of a specific issue by its number.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "issue_number": {"type": "integer"}
                    },
                    "required": ["issue_number"]
                }
            },
            {
                "name": "create_issue",
                "description": "Create a new issue in the repository.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "body": {"type": "string"}
                    },
                    "required": ["title", "body"]
                }
            },
            {
                "name": "add_label",
                "description": "Add a label to an existing issue.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "issue_number": {"type": "integer"},
                        "label": {"type": "string"}
                    },
                    "required": ["issue_number", "label"]
                }
            }
        ]

    def _get_system_prompt(self) -> str:
        return f"""You are FOREMAN, an autonomous GitHub agent. 
You help users manage the repository: {self.repo_full_name}.
You have access to tools to interact with GitHub. 
When a user asks you to perform an action, use the appropriate tool.
Always explain what you are doing. If a tool fails, inform the user why.
Maintain a professional, helpful, and concise tone.

Response Format:
If you need to use a tool, output a JSON block with the tool call.
Example: {{"tool": "list_issues", "parameters": {{"state": "open"}}}}
Otherwise, just respond with text.
"""

    def list_issues(self, state: str = "open") -> ToolResult:
        """Fetch issues from GitHub API."""
        try:
            log.info(f"Listing {state} issues for {self.repo_full_name}")
            url = f"{self.base_url}/repos/{self.repo_full_name}/issues"
            params = {"state": state}
            resp = requests.get(url, headers=self.headers, params=params)
            resp.raise_for_status()
            issues = resp.json()
            
            summary = [f"#{i['number']}: {i['title']} (state: {i['state']})" for i in issues if "pull_request" not in i]
            return ToolResult(True, "\n".join(summary) if summary else "No issues found.")
        except Exception as e:
            log.error(f"Failed to list issues: {e}")
            return ToolResult(False, "", str(e))

    def read_issue(self, issue_number: int) -> ToolResult:
        """Fetch a single issue's content."""
        try:
            log.info(f"Reading issue #{issue_number} for {self.repo_full_name}")
            url = f"{self.base_url}/repos/{self.repo_full_name}/issues/{issue_number}"
            resp = requests.get(url, headers=self.headers)
            resp.raise_for_status()
            issue = resp.json()
            
            content = f"Title: {issue['title']}\nState: {issue['state']}\nLabels: {', '.join(l['name'] for l in issue['labels'])}\n\n{issue['body']}"
            return ToolResult(True, content)
        except Exception as e:
            log.error(f"Failed to read issue #{issue_number}: {e}")
            return ToolResult(False, "", str(e))

    def create_issue(self, title: str, body: str) -> ToolResult:
        """Create a new issue via GitHub API."""
        try:
            log.info(f"Creating new issue in {self.repo_full_name}: {title}")
            url = f"{self.base_url}/repos/{self.repo_full_name}/issues"
            data = {"title": title, "body": body}
            resp = requests.post(url, headers=self.headers, json=data)
            resp.raise_for_status()
            issue = resp.json()
            return ToolResult(True, f"Successfully created issue #{issue['number']}: {issue['html_url']}")
        except Exception as e:
            log.error(f"Failed to create issue: {e}")
            return ToolResult(False, "", str(e))

    def add_label(self, issue_number: int, label: str) -> ToolResult:
        """Add a label to an issue."""
        try:
            log.info(f"Adding label '{label}' to issue #{issue_number} in {self.repo_full_name}")
            url = f"{self.base_url}/repos/{self.repo_full_name}/issues/{issue_number}/labels"
            data = {"labels": [label]}
            resp = requests.post(url, headers=self.headers, json=data)
            resp.raise_for_status()
            return ToolResult(True, f"Successfully added label '{label}' to issue #{issue_number}")
        except Exception as e:
            log.error(f"Failed to add label to issue #{issue_number}: {e}")
            return ToolResult(False, "", str(e))

    def handle_message(self, message: str, history: List[Dict[str, str]] = None) -> str:
        """
        Process a user message, potentially call tools, and return a final response.
        This handles a single turn of conversation but supports history.
        """
        try:
            history = history or []
            context = "\n".join([f"{m['role']}: {m['content']}" for m in history])
            
            user_input = f"Conversation History:\n{context}\n\nUser: {message}\n\nAvailable Tools: {json.dumps(self.tools)}"
            
            response = self.llm.complete(
                model=self.model,
                system=self._get_system_prompt(),
                message=user_input
            )
            
            text = response.text.strip()
            
            # Simple tool parsing - look for JSON
            if text.startswith("{") and "tool" in text:
                try:
                    tool_call = json.loads(text)
                    tool_name = tool_call.get("tool")
                    params = tool_call.get("parameters", {})
                    
                    result = None
                    if tool_name == "list_issues":
                        result = self.list_issues(**params)
                    elif tool_name == "read_issue":
                        result = self.read_issue(**params)
                    elif tool_name == "create_issue":
                        result = self.create_issue(**params)
                    elif tool_name == "add_label":
                        result = self.add_label(**params)
                    
                    if result:
                        if result.success:
                            # Feed tool result back to LLM for final natural response
                            follow_up = f"Tool '{tool_name}' executed successfully. Output:\n{result.output}\n\nPlease summarize this for the user."
                            final_resp = self.llm.complete(
                                model=self.model,
                                system=self._get_system_prompt(),
                                message=follow_up
                            )
                            return final_resp.text
                        else:
                            return f"I encountered an error while trying to {tool_name}: {result.error}"
                except json.JSONDecodeError:
                    log.warning(f"LLM output looked like a tool call but failed to parse: {text}")
                    return text
            
            return text
            
        except Exception as e:
            log.error(f"Agent failed to handle message: {e}")
            return f"I'm sorry, I encountered an internal error: {str(e)}"