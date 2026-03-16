"""Memory read/write with privacy enforcement.

Each agent can only access its own memory directory and shared/.
Privacy is enforced at the code level — no prompt-level honor system.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

log = logging.getLogger("foreman.brain.memory")


class MemoryStore:
    """Scoped memory access for one agent.

    An agent can read/write:
      - Its own directory: memory/<agent_name>/
      - Shared directory:  memory/shared/

    Any attempt to access another agent's directory raises PermissionError.
    """

    def __init__(self, root: Path, agent_name: str) -> None:
        self._root = root
        self._agent_name = agent_name

    def _check_access(self, owner: str, operation: str) -> Path:
        """Validate access and return the resolved directory path."""
        if owner != self._agent_name and owner != "shared":
            raise PermissionError(
                f"{self._agent_name} cannot {operation} {owner}'s memory"
            )
        return self._root / owner

    def write(self, owner: str, filename: str, content: str) -> None:
        """Write a memory file. Only own dir or shared/ allowed."""
        base = self._check_access(owner, "write to")
        target = base / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        log.info(f"Memory write: {owner}/{filename} ({len(content)} chars)")

    def read(self, owner: str, filename: str) -> Optional[str]:
        """Read a memory file. Returns None if not found."""
        base = self._check_access(owner, "read from")
        target = base / filename
        if not target.exists():
            return None
        return target.read_text()

    def list_files(
        self, owner: str, subdirectory: str = ""
    ) -> List[str]:
        """List .md files in a memory directory."""
        base = self._check_access(owner, "list")
        search_dir = base / subdirectory if subdirectory else base
        if not search_dir.exists():
            return []
        return sorted(
            f.name
            for f in search_dir.iterdir()
            if f.is_file() and f.suffix == ".md"
        )
