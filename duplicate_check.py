import os
import logging
import math
from typing import List, Dict, Optional

log = logging.getLogger("foreman.duplicate_check")

# Configuration for semantic similarity
SIMILARITY_THRESHOLD = float(os.environ.get("SIMILARITY_THRESHOLD", "0.9"))

class DuplicateChecker:
    """
    Utility to prevent creating duplicate issues by checking semantic similarity
    against existing open issues.
    """

    def __init__(self, repo):
        self.repo = repo
        self._open_issues_cache: Optional[Dict] = None
        self._llm_client = None

    def _get_embedding(self, text: str) -> List[float]:
        """
        Generates an embedding for the given text using the unified LLM client.
        """
        try:
            if self._llm_client is None:
                from llm_client import LLMClient
                self._llm_client = LLMClient()
            return self._llm_client.generate_embedding(text)
        except Exception as e:
            log.error(f"Failed to generate embedding: {e}")
            return []

    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        """Computes the cosine similarity between two vectors."""
        if not v1 or not v2 or len(v1) != len(v2):
            return 0.0
        
        dot_product = sum(a * b for a, b in zip(v1, v2))
        magnitude1 = math.sqrt(sum(a * a for a in v1))
        magnitude2 = math.sqrt(sum(b * b for b in v2))
        
        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0
            
        return dot_product / (magnitude1 * magnitude2)

    def _fetch_open_issues(self) -> List[Dict]:
        """Fetch open issues from GitHub, caching embeddings to avoid redundant API calls."""
        try:
            log.info("Fetching open issues for semantic duplicate check...")
            issues = self.repo.get_issues(state="open")
            
            if self._open_issues_cache is None or isinstance(self._open_issues_cache, list):
                self._open_issues_cache = {}
                
            new_cache = {}
            for issue in issues:
                if issue.pull_request:
                    continue
                
                # Use cached embedding if available
                if issue.number in self._open_issues_cache and self._open_issues_cache[issue.number]["title"] == issue.title:
                    new_cache[issue.number] = self._open_issues_cache[issue.number]
                    continue
                
                content = f"{issue.title}\n{issue.body or ''}"
                embedding = self._get_embedding(content)
                
                if embedding:
                    new_cache[issue.number] = {
                        "number": issue.number,
                        "title": issue.title,
                        "embedding": embedding
                    }
            
            self._open_issues_cache = new_cache
            log.info(f"Cached {len(self._open_issues_cache)} open issues for comparison.")
            return list(self._open_issues_cache.values())
        except Exception as e:
            log.error(f"Error fetching open issues: {e}")
            if isinstance(self._open_issues_cache, dict):
                return list(self._open_issues_cache.values())
            return []

    def is_duplicate(self, title: str, body: str) -> Optional[Dict]:
        """
        Checks if the proposed issue is a semantic duplicate.
        Returns the similar issue info if a duplicate is found, else None.
        """
        try:
            proposed_content = f"{title}\n{body}"
            proposed_embedding = self._get_embedding(proposed_content)
            
            if not proposed_embedding:
                return None

            existing_issues = self._fetch_open_issues()
            
            highest_similarity = 0.0
            most_similar_issue = None

            for existing in existing_issues:
                similarity = self._cosine_similarity(proposed_embedding, existing["embedding"])
                
                if similarity > highest_similarity:
                    highest_similarity = similarity
                    most_similar_issue = existing

            if highest_similarity > SIMILARITY_THRESHOLD:
                log.warning(
                    f"Duplicate issue detected! Proposed: '{title}' is {highest_similarity:.2f} "
                    f"similar to existing issue #{most_similar_issue['number']}: '{most_similar_issue['title']}'"
                )
                return {
                    "number": most_similar_issue["number"],
                    "title": most_similar_issue["title"],
                    "score": highest_similarity
                }

            return None
        except Exception as e:
            log.error(f"Error during duplicate check: {e}")
            return None

_global_checker_cache = {}

def is_duplicate_issue(repo, title: str, body: str) -> Optional[Dict]:
    """
    Orchestrator function for checking duplicates.
    """
    repo_name = repo.full_name
    if repo_name not in _global_checker_cache:
        _global_checker_cache[repo_name] = DuplicateChecker(repo)
    return _global_checker_cache[repo_name].is_duplicate(title, body)