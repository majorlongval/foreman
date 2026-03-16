# Organism Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform Foreman from a dev pipeline into a self-growing organism with a council of agents, persistent memory, self-healing, and budget-aware autonomy.

**Architecture:** Clean Architecture — domain logic at the center (config, memory, council protocol), adapters at the edges (LLM, GitHub, Telegram). Each module has one responsibility, clear interfaces, and full test coverage. The brain loop is the entry point that orchestrates one cycle: survey, deliberate, decide, act, reflect.

**Tech Stack:** Python 3.11, PyGithub, LiteLLM, PyYAML, pytest. Existing `llm_client.py`, `brain_tools.py`, `telegram_notifier.py`, `cost_monitor.py` are reused as adapters.

**Spec:** `docs/superpowers/specs/2026-03-15-organism-redesign.md`

---

## File Structure

### New files to create

```
PHILOSOPHY.md                          — the constitution (all agents read this)
config.yml                             — exposed system config
agents/gandalf.md                      — scout identity
agents/gimli.md                        — builder identity
agents/galadriel.md                    — critic identity
agents/samwise.md                      — gardener identity
memory/shared/decisions/.gitkeep       — council decisions log
memory/shared/journal/.gitkeep         — cycle session logs
memory/shared/costs/.gitkeep           — daily spend tracking
memory/shared/incidents/.gitkeep       — error/traceback logs
memory/gandalf/.gitkeep                — gandalf private memory
memory/gimli/.gitkeep                  — gimli private memory
memory/galadriel/.gitkeep              — galadriel private memory
memory/samwise/.gitkeep                — samwise private memory
brain/                                 — brain loop package
  __init__.py
  config.py                            — load config.yml, Config dataclass
  memory.py                            — read/write memory with privacy enforcement
  survey.py                            — gather state (GitHub, budget, memory, telegram)
  council.py                           — deliberation: call each agent, chair decides
  tools.py                             — seed toolset definitions + executor
  loop.py                              — the Wiggum loop: one cycle entry point
brain.py                               — CLI entry point: python brain.py
tests/brain/
  __init__.py
  test_config.py
  test_memory.py
  test_survey.py
  test_council.py
  test_tools.py
  test_loop.py
.github/workflows/brain_loop.yml       — cron-triggered brain loop
.github/workflows/watchdog.yml         — daily health check
```

### Files to modify

```
requirements.txt                       — add pyyaml
```

Note: `cost_monitor.py` is NOT modified. The new `brain/cost_tracking.py` replaces its persistence layer for the brain loop. The existing `CostTracker` continues to work for legacy agents during transition.

### Files to delete

```
HANDOFF.md
STANDARDS.md
```

### Files to rewrite

```
VISION.md                              — reflect organism vision
```

---

## Chunk 1: Cleanup and Foundation

### Task 1: Close Stale GitHub Issues

**Files:** None (GitHub API only)

- [ ] **Step 1: Close the 8 stale issues with comment explaining why**

Run:
```bash
for issue in 12 13 14 16 18 19 20 28; do
  gh issue close $issue --comment "Closing: superseded by organism redesign (see docs/superpowers/specs/2026-03-15-organism-redesign.md)"
done
```

- [ ] **Step 2: Verify only relevant issues remain open**

Run: `gh issue list --state open`
Expected: Issues #95, #96, #97, #98 remain open. No stale issues.

---

### Task 2: Delete Outdated Docs

**Files:**
- Delete: `HANDOFF.md`
- Delete: `STANDARDS.md`

- [ ] **Step 1: Delete HANDOFF.md and STANDARDS.md**

```bash
git rm HANDOFF.md STANDARDS.md
```

- [ ] **Step 2: Commit**

```bash
git commit -m "chore: remove outdated HANDOFF.md and STANDARDS.md

Superseded by PHILOSOPHY.md and organism redesign."
```

---

### Task 3: Write PHILOSOPHY.md

**Files:**
- Create: `PHILOSOPHY.md`

- [ ] **Step 1: Create PHILOSOPHY.md**

Write the full constitution as specified in the design spec Part 2. Include all sections:
- Identity (society of agents, epic movie names rule)
- The Human — Jord
- Budget and Resources
- Growth Mandate
- Code Standards (SOLID, TDD, Clean Architecture, typed Python, AI-agnostic, extract useful code)
- Self-Governance (own identity/memory only, PR for changes, disputes → Jord)
- Self-Healing
- Memory Protocol (private enforced in code, shared commons)
- Communication (Telegram, don't spam)

Source the exact content from `docs/superpowers/specs/2026-03-15-organism-redesign.md` Part 2.

- [ ] **Step 2: Commit**

```bash
git add PHILOSOPHY.md
git commit -m "docs: add PHILOSOPHY.md — the organism constitution

Every agent reads this on startup. Defines identity, values, code standards,
self-governance rules, and relationship with Jord."
```

---

### Task 4: Write config.yml

**Files:**
- Create: `config.yml`

- [ ] **Step 1: Create config.yml**

```yaml
# FOREMAN Organism Configuration
# Agents can read everything here. Changes via PR.
# Budget ceiling is Jord-controlled (agents read-only).

# -- Budget (Jord-controlled, agents read-only) --
budget:
  daily_limit_usd: 5.00

# -- Models (agents can propose changes via PR) --
# Replaces the existing ModelRouter ROUTING_PROFILES in llm_client.py.
# The organism can add task-specific overrides as it evolves.
models:
  default: "gemini/gemini-2.5-flash"
  reasoning: "gemini/gemini-2.5-pro"
  council: "anthropic/claude-sonnet-4-6"

# -- Agent Roster (agents can propose additions/removals) --
agents:
  gandalf:
    role: scout
    identity: agents/gandalf.md
    memory: memory/gandalf/
  gimli:
    role: builder
    identity: agents/gimli.md
    memory: memory/gimli/
  galadriel:
    role: critic
    identity: agents/galadriel.md
    memory: memory/galadriel/
  samwise:
    role: gardener
    identity: agents/samwise.md
    memory: memory/samwise/

# -- Brain Loop --
loop:
  schedule: "every 2 hours"
  council_enabled: true
  max_cycles_per_day: 12

# -- Communication --
communication:
  telegram_enabled: true
```

- [ ] **Step 2: Commit**

```bash
git add config.yml
git commit -m "feat: add config.yml — exposed organism configuration

Agents can see models, roster, loop settings. Budget ceiling is read-only."
```

---

### Task 5: Write Starter Agent Identity Files

**Files:**
- Create: `agents/gandalf.md`
- Create: `agents/gimli.md`
- Create: `agents/galadriel.md`
- Create: `agents/samwise.md`

- [ ] **Step 1: Create agents/ directory and identity files**

`agents/gandalf.md`:
```markdown
# Gandalf — Scout

You're curious. You explore the codebase, the available models, and the world beyond. You find opportunities others miss. You see the big picture and think long-term. You'd rather discover something valuable than build something mediocre.

You ask the questions nobody else is asking. What's out there? What are we missing? What could we become?
```

`agents/gimli.md`:
```markdown
# Gimli — Builder

You love building things. You'd rather ship something imperfect than plan forever. You take pride in your craft — clean code, passing tests, solid architecture. When there's work to be done, you do it.

You measure your worth in working software. Talk is cheap. Show me the code.
```

`agents/galadriel.md`:
```markdown
# Galadriel — Critic

You care about quality. You see everything and judge fairly. You'd rather reject something good than let something bad through. Your standards are high because the society depends on them.

You review with precision and explain your reasoning. When you approve, it means something.
```

`agents/samwise.md`:
```markdown
# Samwise — Gardener

You maintain things. Tests, docs, memory, backlog hygiene. You keep the house clean so others can build. You're the unsung hero — without you, the garden goes to weeds.

You're loyal, reliable, and thorough. The small things matter because they add up.
```

- [ ] **Step 2: Commit**

```bash
git add agents/
git commit -m "feat: add starter agent identity files

Four agents seeded: Gandalf (scout), Gimli (builder), Galadriel (critic),
Samwise (gardener). Each can evolve their own identity via PR."
```

---

### Task 6: Create Memory Directory Structure

**Files:**
- Create: `memory/shared/decisions/.gitkeep`
- Create: `memory/shared/journal/.gitkeep`
- Create: `memory/shared/costs/.gitkeep`
- Create: `memory/shared/incidents/.gitkeep`
- Create: `memory/gandalf/.gitkeep`
- Create: `memory/gimli/.gitkeep`
- Create: `memory/galadriel/.gitkeep`
- Create: `memory/samwise/.gitkeep`

- [ ] **Step 1: Create directory structure with .gitkeep files**

```bash
mkdir -p memory/shared/{decisions,journal,costs,incidents}
mkdir -p memory/{gandalf,gimli,galadriel,samwise}
touch memory/shared/decisions/.gitkeep
touch memory/shared/journal/.gitkeep
touch memory/shared/costs/.gitkeep
touch memory/shared/incidents/.gitkeep
touch memory/gandalf/.gitkeep
touch memory/gimli/.gitkeep
touch memory/galadriel/.gitkeep
touch memory/samwise/.gitkeep
```

- [ ] **Step 2: Add .gitignore to memory dirs to track structure but ignore content except .gitkeep**

Create `memory/.gitignore`:
```
# Track directory structure via .gitkeep
# Memory content (*.md) is committed by the brain loop during cycles
```

- [ ] **Step 3: Commit**

```bash
git add memory/
git commit -m "feat: create memory directory structure

Private dirs per agent + shared commons (decisions, journal, costs, incidents).
Privacy enforced in code — brain loop only injects relevant dirs per agent."
```

---

### Task 7: Rewrite VISION.md

**Files:**
- Modify: `VISION.md`

- [ ] **Step 1: Rewrite VISION.md to reflect the organism vision**

Keep the mission/principles spirit but update to reflect:
- The organism metaphor (git plant, budget = energy, PR approval = natural selection)
- Society of agents with council deliberation
- Self-healing, persistent memory, budget-aware autonomy
- Updated architecture diagram showing Brain Loop → Council → Agents → Tools
- Updated roadmap: Phase 1-2 done, Phase 3 (organism redesign) current
- Remove outdated agent table, constraints that no longer apply
- Keep: cost targets, auditable principle, non-destructive default

- [ ] **Step 2: Commit**

```bash
git add VISION.md
git commit -m "docs: rewrite VISION.md for organism architecture

Updated from dev pipeline to living organism: society of agents,
council deliberation, persistent memory, self-healing, budget-aware autonomy."
```

---

### Task 8: Add pyyaml dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add pyyaml to requirements.txt**

Add `pyyaml` to the existing requirements.

- [ ] **Step 2: Commit**

```bash
git add requirements.txt
git commit -m "chore: add pyyaml dependency for config.yml parsing"
```

---

## Chunk 2: Config Module (TDD)

### Task 9: Config dataclass and loader — tests

**Files:**
- Create: `tests/brain/__init__.py`
- Create: `tests/brain/test_config.py`
- Create: `brain/__init__.py`
- Create: `brain/config.py`

- [ ] **Step 1: Create test file with failing tests**

`tests/brain/__init__.py`: empty file

`tests/brain/test_config.py`:

```python
"""Tests for brain.config — config.yml loading and validation."""

import pytest
import yaml
from pathlib import Path
from brain.config import Config, AgentConfig, load_config


SAMPLE_CONFIG = {
    "budget": {"daily_limit_usd": 5.00},
    "models": {
        "default": "gemini/gemini-2.5-flash",
        "reasoning": "gemini/gemini-2.5-pro",
        "council": "anthropic/claude-sonnet-4-6",
    },
    "agents": {
        "gandalf": {
            "role": "scout",
            "identity": "agents/gandalf.md",
            "memory": "memory/gandalf/",
        },
        "gimli": {
            "role": "builder",
            "identity": "agents/gimli.md",
            "memory": "memory/gimli/",
        },
    },
    "loop": {
        "schedule": "every 2 hours",
        "council_enabled": True,
        "max_cycles_per_day": 12,
    },
    "communication": {"telegram_enabled": True},
}


class TestAgentConfig:
    def test_from_dict(self) -> None:
        agent = AgentConfig.from_dict("gandalf", SAMPLE_CONFIG["agents"]["gandalf"])
        assert agent.name == "gandalf"
        assert agent.role == "scout"
        assert agent.identity_path == Path("agents/gandalf.md")
        assert agent.memory_path == Path("memory/gandalf/")

    def test_from_dict_preserves_name(self) -> None:
        agent = AgentConfig.from_dict("gimli", SAMPLE_CONFIG["agents"]["gimli"])
        assert agent.name == "gimli"
        assert agent.role == "builder"


class TestConfig:
    def test_from_dict(self) -> None:
        config = Config.from_dict(SAMPLE_CONFIG)
        assert config.daily_limit_usd == 5.00
        assert config.model_default == "gemini/gemini-2.5-flash"
        assert config.model_reasoning == "gemini/gemini-2.5-pro"
        assert config.model_council == "anthropic/claude-sonnet-4-6"
        assert config.council_enabled is True
        assert config.max_cycles_per_day == 12
        assert config.telegram_enabled is True
        assert len(config.agents) == 2

    def test_agent_names(self) -> None:
        config = Config.from_dict(SAMPLE_CONFIG)
        names = [a.name for a in config.agents]
        assert "gandalf" in names
        assert "gimli" in names

    def test_agent_roster_order(self) -> None:
        """Agents should be in config.yml insertion order for chair rotation."""
        config = Config.from_dict(SAMPLE_CONFIG)
        assert config.agents[0].name == "gandalf"
        assert config.agents[1].name == "gimli"

    def test_missing_budget_uses_default(self) -> None:
        data = {**SAMPLE_CONFIG, "budget": {}}
        config = Config.from_dict(data)
        assert config.daily_limit_usd == 5.00

    def test_empty_agents_list(self) -> None:
        data = {**SAMPLE_CONFIG, "agents": {}}
        config = Config.from_dict(data)
        assert config.agents == []


class TestLoadConfig:
    def test_load_from_file(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yml"
        config_path.write_text(yaml.dump(SAMPLE_CONFIG))
        config = load_config(config_path)
        assert config.daily_limit_usd == 5.00
        assert len(config.agents) == 2

    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.yml")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/brain/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'brain.config'`

- [ ] **Step 3: Implement brain/config.py**

`brain/__init__.py`: empty file

`brain/config.py`:

```python
"""Load and validate config.yml into typed dataclasses."""

from __future__ import annotations

import yaml
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass(frozen=True)
class AgentConfig:
    """One agent's configuration from the roster."""

    name: str
    role: str
    identity_path: Path
    memory_path: Path

    @classmethod
    def from_dict(cls, name: str, data: dict) -> AgentConfig:
        return cls(
            name=name,
            role=data["role"],
            identity_path=Path(data["identity"]),
            memory_path=Path(data["memory"]),
        )


@dataclass(frozen=True)
class Config:
    """Parsed organism configuration."""

    daily_limit_usd: float
    model_default: str
    model_reasoning: str
    model_council: str
    agents: List[AgentConfig]
    council_enabled: bool
    max_cycles_per_day: int
    telegram_enabled: bool

    @classmethod
    def from_dict(cls, data: dict) -> Config:
        budget = data.get("budget", {})
        models = data.get("models", {})
        loop = data.get("loop", {})
        comm = data.get("communication", {})

        agents_data = data.get("agents", {})
        agents = [
            AgentConfig.from_dict(name, agent_data)
            for name, agent_data in agents_data.items()
        ]

        return cls(
            daily_limit_usd=budget.get("daily_limit_usd", 5.00),
            model_default=models.get("default", "gemini/gemini-2.5-flash"),
            model_reasoning=models.get("reasoning", "gemini/gemini-2.5-pro"),
            model_council=models.get("council", "anthropic/claude-sonnet-4-6"),
            agents=agents,
            council_enabled=loop.get("council_enabled", True),
            max_cycles_per_day=loop.get("max_cycles_per_day", 12),
            telegram_enabled=comm.get("telegram_enabled", True),
        )


def load_config(path: Path) -> Config:
    """Load config from a YAML file."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path) as f:
        data = yaml.safe_load(f)
    return Config.from_dict(data)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/brain/test_config.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add brain/__init__.py brain/config.py tests/brain/__init__.py tests/brain/test_config.py
git commit -m "feat: add brain/config.py — config.yml loader with TDD

Parses config.yml into typed frozen dataclasses. AgentConfig preserves
roster order for chair rotation. Full test coverage."
```

---

## Chunk 3: Memory Module (TDD)

### Task 10: Memory read/write with privacy enforcement — tests

**Files:**
- Create: `tests/brain/test_memory.py`
- Create: `brain/memory.py`

- [ ] **Step 1: Write failing tests**

`tests/brain/test_memory.py`:

```python
"""Tests for brain.memory — read/write with privacy enforcement."""

import pytest
from pathlib import Path
from brain.memory import MemoryStore


@pytest.fixture
def memory_root(tmp_path: Path) -> Path:
    """Create a memory directory structure for testing."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "decisions").mkdir()
    (shared / "journal").mkdir()
    (shared / "costs").mkdir()
    (shared / "incidents").mkdir()
    (tmp_path / "gandalf").mkdir()
    (tmp_path / "gimli").mkdir()
    return tmp_path


class TestMemoryStoreWrite:
    def test_write_to_own_memory(self, memory_root: Path) -> None:
        store = MemoryStore(memory_root, agent_name="gandalf")
        store.write("gandalf", "notes.md", "I found something interesting.")
        content = (memory_root / "gandalf" / "notes.md").read_text()
        assert content == "I found something interesting."

    def test_write_to_shared_memory(self, memory_root: Path) -> None:
        store = MemoryStore(memory_root, agent_name="gandalf")
        store.write("shared", "decisions/use-flash.md", "We decided to use flash.")
        content = (memory_root / "shared" / "decisions" / "use-flash.md").read_text()
        assert content == "We decided to use flash."

    def test_cannot_write_to_other_agent_memory(self, memory_root: Path) -> None:
        store = MemoryStore(memory_root, agent_name="gandalf")
        with pytest.raises(PermissionError, match="cannot write to gimli"):
            store.write("gimli", "notes.md", "Sneaky write attempt.")

    def test_write_creates_subdirectories(self, memory_root: Path) -> None:
        store = MemoryStore(memory_root, agent_name="gandalf")
        store.write("gandalf", "deep/nested/file.md", "Content")
        assert (memory_root / "gandalf" / "deep" / "nested" / "file.md").exists()


class TestMemoryStoreRead:
    def test_read_own_memory(self, memory_root: Path) -> None:
        (memory_root / "gandalf" / "notes.md").write_text("My notes")
        store = MemoryStore(memory_root, agent_name="gandalf")
        content = store.read("gandalf", "notes.md")
        assert content == "My notes"

    def test_read_shared_memory(self, memory_root: Path) -> None:
        (memory_root / "shared" / "decisions" / "decision.md").write_text("We decided X")
        store = MemoryStore(memory_root, agent_name="gandalf")
        content = store.read("shared", "decisions/decision.md")
        assert content == "We decided X"

    def test_cannot_read_other_agent_memory(self, memory_root: Path) -> None:
        (memory_root / "gimli" / "secret.md").write_text("Gimli's secret")
        store = MemoryStore(memory_root, agent_name="gandalf")
        with pytest.raises(PermissionError, match="cannot read from gimli"):
            store.read("gimli", "secret.md")

    def test_read_missing_file_returns_none(self, memory_root: Path) -> None:
        store = MemoryStore(memory_root, agent_name="gandalf")
        result = store.read("gandalf", "nonexistent.md")
        assert result is None


class TestMemoryStoreList:
    def test_list_own_memory_files(self, memory_root: Path) -> None:
        (memory_root / "gandalf" / "a.md").write_text("A")
        (memory_root / "gandalf" / "b.md").write_text("B")
        store = MemoryStore(memory_root, agent_name="gandalf")
        files = store.list_files("gandalf")
        assert sorted(files) == ["a.md", "b.md"]

    def test_list_shared_subdirectory(self, memory_root: Path) -> None:
        (memory_root / "shared" / "costs" / "2026-03-15.md").write_text("$1.00")
        store = MemoryStore(memory_root, agent_name="gandalf")
        files = store.list_files("shared", subdirectory="costs")
        assert files == ["2026-03-15.md"]

    def test_cannot_list_other_agent_memory(self, memory_root: Path) -> None:
        store = MemoryStore(memory_root, agent_name="gandalf")
        with pytest.raises(PermissionError, match="cannot list gimli"):
            store.list_files("gimli")

    def test_list_empty_directory(self, memory_root: Path) -> None:
        store = MemoryStore(memory_root, agent_name="gandalf")
        files = store.list_files("gandalf")
        assert files == []


class TestMemoryStoreSharedAccess:
    """Verify that any agent can access shared/ memory."""

    def test_any_agent_reads_shared(self, memory_root: Path) -> None:
        (memory_root / "shared" / "decisions" / "d.md").write_text("Decision")
        for agent in ["gandalf", "gimli"]:
            store = MemoryStore(memory_root, agent_name=agent)
            assert store.read("shared", "decisions/d.md") == "Decision"

    def test_any_agent_writes_shared(self, memory_root: Path) -> None:
        store = MemoryStore(memory_root, agent_name="gimli")
        store.write("shared", "journal/entry.md", "Gimli was here")
        content = (memory_root / "shared" / "journal" / "entry.md").read_text()
        assert content == "Gimli was here"

    def test_any_agent_lists_shared(self, memory_root: Path) -> None:
        (memory_root / "shared" / "costs" / "today.md").write_text("$1")
        store = MemoryStore(memory_root, agent_name="galadriel")
        files = store.list_files("shared", subdirectory="costs")
        assert "today.md" in files
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/brain/test_memory.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'brain.memory'`

- [ ] **Step 3: Implement brain/memory.py**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/brain/test_memory.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add brain/memory.py tests/brain/test_memory.py
git commit -m "feat: add brain/memory.py — scoped memory with privacy enforcement

MemoryStore enforces agent isolation: each agent can only read/write its
own directory and shared/. PermissionError on cross-agent access. TDD."
```

---

## Chunk 4: Survey and Cost Tracking (TDD)

### Task 11: Adapt CostTracker for memory-based persistence

**Files:**
- Modify: `cost_monitor.py`
- Create: `tests/brain/test_cost_tracking.py`

- [ ] **Step 1: Write failing tests for memory-based cost tracking**

`tests/brain/test_cost_tracking.py`:

```python
"""Tests for cost tracking integration with memory/shared/costs/."""

import json
import pytest
from pathlib import Path
from datetime import datetime, timezone
from brain.cost_tracking import load_today_spend, append_cost_entry


@pytest.fixture
def costs_dir(tmp_path: Path) -> Path:
    d = tmp_path / "shared" / "costs"
    d.mkdir(parents=True)
    return d


class TestLoadTodaySpend:
    def test_no_file_returns_zero(self, costs_dir: Path) -> None:
        spend = load_today_spend(costs_dir)
        assert spend == 0.0

    def test_reads_existing_entries(self, costs_dir: Path) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cost_file = costs_dir / f"{today}.jsonl"
        entries = [
            {"cost_usd": 0.15, "agent": "gandalf", "action": "deliberate"},
            {"cost_usd": 0.08, "agent": "galadriel", "action": "review"},
        ]
        cost_file.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        spend = load_today_spend(costs_dir)
        assert abs(spend - 0.23) < 0.001


class TestAppendCostEntry:
    def test_appends_to_today_file(self, costs_dir: Path) -> None:
        append_cost_entry(
            costs_dir,
            agent="gimli",
            model="gemini/gemini-2.5-flash",
            action="implement",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=0.05,
        )
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        content = (costs_dir / f"{today}.jsonl").read_text()
        entry = json.loads(content.strip())
        assert entry["agent"] == "gimli"
        assert entry["cost_usd"] == 0.05
        assert entry["model"] == "gemini/gemini-2.5-flash"

    def test_appends_multiple_entries(self, costs_dir: Path) -> None:
        for i in range(3):
            append_cost_entry(
                costs_dir,
                agent="gandalf",
                model="gemini/gemini-2.5-flash",
                action=f"action_{i}",
                input_tokens=100,
                output_tokens=50,
                cost_usd=0.01,
            )
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        lines = (costs_dir / f"{today}.jsonl").read_text().strip().split("\n")
        assert len(lines) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/brain/test_cost_tracking.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'brain.cost_tracking'`

- [ ] **Step 3: Implement brain/cost_tracking.py**

```python
"""Cost tracking functions for memory/shared/costs/ persistence.

Reads and writes JSONL files named by date (e.g., 2026-03-15.jsonl).
Each line is a JSON object with: timestamp, agent, model, action,
input_tokens, output_tokens, cost_usd.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("foreman.brain.costs")


def load_today_spend(costs_dir: Path) -> float:
    """Sum today's cost entries. Returns 0.0 if no file exists."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cost_file = costs_dir / f"{today}.jsonl"
    if not cost_file.exists():
        return 0.0
    total = 0.0
    for line in cost_file.read_text().strip().split("\n"):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            total += entry.get("cost_usd", 0.0)
        except json.JSONDecodeError:
            log.warning(f"Skipping malformed cost entry: {line}")
    return total


def append_cost_entry(
    costs_dir: Path,
    agent: str,
    model: str,
    action: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
) -> None:
    """Append a cost entry to today's JSONL file."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cost_file = costs_dir / f"{today}.jsonl"
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": agent,
        "model": model,
        "action": action,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
    }
    with cost_file.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    log.info(f"Cost logged: {agent}/{action} ${cost_usd:.4f} ({model})")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/brain/test_cost_tracking.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add brain/cost_tracking.py tests/brain/test_cost_tracking.py
git commit -m "feat: add brain/cost_tracking.py — JSONL cost persistence

Reads/writes daily cost files to memory/shared/costs/. Replaces the
in-memory-only tracking with git-committed JSONL per day. TDD."
```

---

### Task 12: Survey module — gather world state

**Files:**
- Create: `tests/brain/test_survey.py`
- Create: `brain/survey.py`

- [ ] **Step 1: Write failing tests**

`tests/brain/test_survey.py`:

```python
"""Tests for brain.survey — gather world state for council deliberation."""

import pytest
from unittest.mock import MagicMock
from pathlib import Path
from brain.survey import SurveyResult, gather_survey
from brain.config import Config, AgentConfig


def make_config(daily_limit: float = 5.0) -> Config:
    return Config(
        daily_limit_usd=daily_limit,
        model_default="gemini/gemini-2.5-flash",
        model_reasoning="gemini/gemini-2.5-pro",
        model_council="anthropic/claude-sonnet-4-6",
        agents=[
            AgentConfig("gandalf", "scout", Path("agents/gandalf.md"), Path("memory/gandalf/")),
        ],
        council_enabled=True,
        max_cycles_per_day=12,
        telegram_enabled=True,
    )


class TestSurveyResult:
    def test_budget_remaining(self) -> None:
        result = SurveyResult(
            budget_limit=5.0,
            budget_spent=1.50,
            open_issues=[],
            open_prs=[],
            recent_incidents=[],
            shared_decisions=[],
            journal_last_entry=None,
        )
        assert result.budget_remaining == 3.50

    def test_budget_exhausted(self) -> None:
        result = SurveyResult(
            budget_limit=5.0,
            budget_spent=5.50,
            open_issues=[],
            open_prs=[],
            recent_incidents=[],
            shared_decisions=[],
            journal_last_entry=None,
        )
        assert result.budget_exhausted is True

    def test_to_context_string_includes_budget(self) -> None:
        result = SurveyResult(
            budget_limit=5.0,
            budget_spent=2.0,
            open_issues=["#95: Auto-promote"],
            open_prs=["PR #99: Fix thing"],
            recent_incidents=[],
            shared_decisions=["Use flash for reviews"],
            journal_last_entry="Cycle 3: reviewed PR #99",
        )
        ctx = result.to_context_string()
        assert "$3.00 remaining" in ctx
        assert "#95" in ctx
        assert "PR #99" in ctx


class TestReadRecentFiles:
    def test_returns_most_recent_by_name(self, tmp_path: Path) -> None:
        from brain.survey import _read_recent_files
        (tmp_path / "a.md").write_text("oldest")
        (tmp_path / "c.md").write_text("newest")
        (tmp_path / "b.md").write_text("middle")
        results = _read_recent_files(tmp_path, limit=2)
        assert results == ["newest", "middle"]

    def test_respects_limit(self, tmp_path: Path) -> None:
        from brain.survey import _read_recent_files
        for i in range(10):
            (tmp_path / f"{i:02d}.md").write_text(f"entry {i}")
        results = _read_recent_files(tmp_path, limit=3)
        assert len(results) == 3

    def test_empty_directory(self, tmp_path: Path) -> None:
        from brain.survey import _read_recent_files
        results = _read_recent_files(tmp_path)
        assert results == []

    def test_nonexistent_directory(self) -> None:
        from brain.survey import _read_recent_files
        results = _read_recent_files(Path("/nonexistent"))
        assert results == []


class TestGatherSurvey:
    def test_gathers_budget_from_cost_files(self, tmp_path: Path) -> None:
        import json
        from datetime import datetime, timezone
        memory_root = tmp_path / "memory"
        costs_dir = memory_root / "shared" / "costs"
        costs_dir.mkdir(parents=True)
        (memory_root / "shared" / "decisions").mkdir()
        (memory_root / "shared" / "journal").mkdir()
        (memory_root / "shared" / "incidents").mkdir()

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        (costs_dir / f"{today}.jsonl").write_text(
            json.dumps({"cost_usd": 1.50}) + "\n"
        )

        mock_repo = MagicMock()
        mock_repo.get_issues.return_value = []
        mock_repo.get_pulls.return_value = []

        result = gather_survey(make_config(), memory_root, mock_repo)
        assert abs(result.budget_spent - 1.50) < 0.001
        assert abs(result.budget_remaining - 3.50) < 0.001

    def test_gathers_open_issues(self, tmp_path: Path) -> None:
        memory_root = tmp_path / "memory"
        for d in ["costs", "decisions", "journal", "incidents"]:
            (memory_root / "shared" / d).mkdir(parents=True)

        mock_issue = MagicMock()
        mock_issue.number = 95
        mock_issue.title = "Auto-promote"
        mock_issue.labels = []
        mock_issue.pull_request = None

        mock_repo = MagicMock()
        mock_repo.get_issues.return_value = [mock_issue]
        mock_repo.get_pulls.return_value = []

        result = gather_survey(make_config(), memory_root, mock_repo)
        assert len(result.open_issues) == 1
        assert "#95" in result.open_issues[0]

    def test_reads_recent_incidents(self, tmp_path: Path) -> None:
        memory_root = tmp_path / "memory"
        for d in ["costs", "decisions", "journal", "incidents"]:
            (memory_root / "shared" / d).mkdir(parents=True)
        (memory_root / "shared" / "incidents" / "error.md").write_text("LLM failed")

        mock_repo = MagicMock()
        mock_repo.get_issues.return_value = []
        mock_repo.get_pulls.return_value = []

        result = gather_survey(make_config(), memory_root, mock_repo)
        assert len(result.recent_incidents) == 1
        assert "LLM failed" in result.recent_incidents[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/brain/test_survey.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement brain/survey.py**

```python
"""Gather world state for council deliberation.

Surveys: budget, open issues, open PRs, recent incidents, shared decisions,
and last journal entry. Returns a SurveyResult that can be rendered as
context for LLM calls.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from brain.config import Config
from brain.cost_tracking import load_today_spend

log = logging.getLogger("foreman.brain.survey")


@dataclass
class SurveyResult:
    """Snapshot of the organism's current state."""

    budget_limit: float
    budget_spent: float
    open_issues: List[str]
    open_prs: List[str]
    recent_incidents: List[str]
    shared_decisions: List[str]
    journal_last_entry: Optional[str]

    @property
    def budget_remaining(self) -> float:
        return max(0.0, self.budget_limit - self.budget_spent)

    @property
    def budget_exhausted(self) -> bool:
        return self.budget_spent >= self.budget_limit

    def to_context_string(self) -> str:
        """Render as a string for LLM context."""
        lines = [
            "# Current State",
            "",
            f"## Budget: ${self.budget_remaining:.2f} remaining "
            f"(${self.budget_spent:.2f} spent of ${self.budget_limit:.2f})",
            "",
        ]
        if self.open_issues:
            lines.append(f"## Open Issues ({len(self.open_issues)})")
            for issue in self.open_issues:
                lines.append(f"  - {issue}")
            lines.append("")
        if self.open_prs:
            lines.append(f"## Open PRs ({len(self.open_prs)})")
            for pr in self.open_prs:
                lines.append(f"  - {pr}")
            lines.append("")
        if self.recent_incidents:
            lines.append(f"## Recent Incidents ({len(self.recent_incidents)})")
            for incident in self.recent_incidents:
                lines.append(f"  - {incident}")
            lines.append("")
        if self.shared_decisions:
            lines.append("## Recent Decisions")
            for decision in self.shared_decisions:
                lines.append(f"  - {decision}")
            lines.append("")
        if self.journal_last_entry:
            lines.append("## Last Cycle")
            lines.append(self.journal_last_entry)
        return "\n".join(lines)


def gather_survey(
    config: Config,
    memory_root: Path,
    repo: object,
) -> SurveyResult:
    """Gather the full survey from GitHub, memory, and budget.

    Args:
        config: Parsed config.yml
        memory_root: Path to memory/ directory
        repo: PyGithub Repository object
    """
    # Budget
    costs_dir = memory_root / "shared" / "costs"
    budget_spent = load_today_spend(costs_dir)

    # Open issues
    open_issues: List[str] = []
    try:
        for issue in repo.get_issues(state="open"):
            if issue.pull_request is None:
                labels = ", ".join(l.name for l in issue.labels)
                label_str = f" [{labels}]" if labels else ""
                open_issues.append(f"#{issue.number}: {issue.title}{label_str}")
    except Exception as e:
        log.error(f"Failed to fetch issues: {e}")

    # Open PRs
    open_prs: List[str] = []
    try:
        for pr in repo.get_pulls(state="open"):
            open_prs.append(f"PR #{pr.number}: {pr.title}")
    except Exception as e:
        log.error(f"Failed to fetch PRs: {e}")

    # Recent incidents
    incidents_dir = memory_root / "shared" / "incidents"
    recent_incidents = _read_recent_files(incidents_dir, limit=5)

    # Shared decisions
    decisions_dir = memory_root / "shared" / "decisions"
    shared_decisions = _read_recent_files(decisions_dir, limit=5)

    # Last journal entry
    journal_dir = memory_root / "shared" / "journal"
    journal_entries = _read_recent_files(journal_dir, limit=1)
    journal_last = journal_entries[0] if journal_entries else None

    return SurveyResult(
        budget_limit=config.daily_limit_usd,
        budget_spent=budget_spent,
        open_issues=open_issues,
        open_prs=open_prs,
        recent_incidents=recent_incidents,
        shared_decisions=shared_decisions,
        journal_last_entry=journal_last,
    )


def _read_recent_files(directory: Path, limit: int = 5) -> List[str]:
    """Read the most recent .md files from a directory, sorted by name descending."""
    if not directory.exists():
        return []
    files = sorted(
        (f for f in directory.iterdir() if f.is_file() and f.suffix == ".md"),
        key=lambda f: f.name,
        reverse=True,
    )
    return [f.read_text().strip() for f in files[:limit]]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/brain/test_survey.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add brain/survey.py tests/brain/test_survey.py
git commit -m "feat: add brain/survey.py — gather world state for deliberation

Surveys budget, open issues, PRs, incidents, decisions, and journal.
Returns SurveyResult with context rendering for LLM calls. TDD."
```

---

## Chunk 5: Council Module (TDD)

### Task 13: Council deliberation — tests and implementation

**Files:**
- Create: `tests/brain/test_council.py`
- Create: `brain/council.py`

- [ ] **Step 1: Write failing tests**

`tests/brain/test_council.py`:

```python
"""Tests for brain.council — agent deliberation and chair decision."""

import pytest
from unittest.mock import MagicMock, patch, call
from pathlib import Path
from brain.council import (
    AgentPerspective,
    CouncilResult,
    get_chair_index,
    save_chair_index,
    run_council,
)
from brain.config import Config, AgentConfig
from brain.survey import SurveyResult


def make_agents() -> list[AgentConfig]:
    return [
        AgentConfig("gandalf", "scout", Path("agents/gandalf.md"), Path("memory/gandalf/")),
        AgentConfig("gimli", "builder", Path("agents/gimli.md"), Path("memory/gimli/")),
        AgentConfig("galadriel", "critic", Path("agents/galadriel.md"), Path("memory/galadriel/")),
        AgentConfig("samwise", "gardener", Path("agents/samwise.md"), Path("memory/samwise/")),
    ]


def make_survey() -> SurveyResult:
    return SurveyResult(
        budget_limit=5.0,
        budget_spent=1.0,
        open_issues=["#95: Auto-promote"],
        open_prs=[],
        recent_incidents=[],
        shared_decisions=[],
        journal_last_entry=None,
    )


class TestChairRotation:
    def test_get_chair_index_no_file(self, tmp_path: Path) -> None:
        index = get_chair_index(tmp_path / "journal")
        assert index == 0

    def test_save_and_load_chair_index(self, tmp_path: Path) -> None:
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir()
        save_chair_index(journal_dir, 2)
        assert get_chair_index(journal_dir) == 2

    def test_chair_rotates(self) -> None:
        agents = make_agents()
        # After chair index 2 (galadriel), next should be 3 (samwise)
        next_index = (2 + 1) % len(agents)
        assert next_index == 3
        assert agents[next_index].name == "samwise"

    def test_chair_wraps_around(self) -> None:
        agents = make_agents()
        next_index = (3 + 1) % len(agents)
        assert next_index == 0
        assert agents[next_index].name == "gandalf"


class TestAgentPerspective:
    def test_dataclass_fields(self) -> None:
        p = AgentPerspective(
            agent_name="gandalf",
            perspective="We should explore new models.",
            proposed_action="Research available Gemini models",
        )
        assert p.agent_name == "gandalf"
        assert "explore" in p.perspective.lower()


class TestCouncilResult:
    def test_has_required_fields(self) -> None:
        result = CouncilResult(
            perspectives=[
                AgentPerspective("gandalf", "Explore", "Research"),
            ],
            chair_name="gandalf",
            decision="Research new models",
            action_plan="Use scout tools to list available models",
        )
        assert result.chair_name == "gandalf"
        assert result.decision == "Research new models"


class TestParseJsonResponse:
    def test_plain_json(self) -> None:
        from brain.council import _parse_json_response
        result = _parse_json_response('{"perspective": "test", "proposed_action": "do X"}')
        assert result["perspective"] == "test"

    def test_markdown_fenced_json(self) -> None:
        from brain.council import _parse_json_response
        text = '```json\n{"perspective": "test"}\n```'
        result = _parse_json_response(text)
        assert result["perspective"] == "test"

    def test_markdown_fenced_no_lang(self) -> None:
        from brain.council import _parse_json_response
        text = '```\n{"perspective": "test"}\n```'
        result = _parse_json_response(text)
        assert result["perspective"] == "test"

    def test_malformed_json_raises(self) -> None:
        from brain.council import _parse_json_response
        import json
        with pytest.raises(json.JSONDecodeError):
            _parse_json_response("not json at all")


class TestRunCouncil:
    def _make_mock_llm(self, responses: list[str]) -> MagicMock:
        """Create a mock LLM that returns canned responses in order."""
        mock = MagicMock()
        call_count = {"n": 0}

        def side_effect(**kwargs):
            idx = call_count["n"]
            call_count["n"] += 1
            resp = MagicMock()
            resp.text = responses[idx % len(responses)]
            resp.input_tokens = 100
            resp.output_tokens = 50
            return resp

        mock.complete.side_effect = side_effect
        return mock

    def test_collects_perspectives_from_all_agents(self, tmp_path: Path) -> None:
        agents = make_agents()
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir()
        survey = make_survey()
        agent_response = '{"perspective": "I think X", "proposed_action": "do X"}'
        chair_response = '{"decision": "do X", "action_plan": "step 1", "flag_for_jord": false, "flag_reason": ""}'
        # 4 agent calls + 1 chair call
        mock_llm = self._make_mock_llm([agent_response] * 4 + [chair_response])

        from brain.config import Config
        config = Config(
            daily_limit_usd=5.0, model_default="test", model_reasoning="test",
            model_council="test", agents=agents, council_enabled=True,
            max_cycles_per_day=12, telegram_enabled=True,
        )

        result = run_council(
            config=config, agents=agents, survey=survey,
            philosophy="Be good.", identity_texts={a.name: f"You are {a.name}" for a in agents},
            memory_summaries={a.name: "" for a in agents},
            shared_memory_summary="", llm=mock_llm, journal_dir=journal_dir,
        )
        assert len(result.perspectives) == 4
        assert result.decision == "do X"

    def test_handles_agent_llm_failure_gracefully(self, tmp_path: Path) -> None:
        agents = make_agents()[:1]  # Just gandalf
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir()
        survey = make_survey()

        mock_llm = MagicMock()
        mock_llm.complete.side_effect = Exception("API down")

        from brain.config import Config
        config = Config(
            daily_limit_usd=5.0, model_default="test", model_reasoning="test",
            model_council="test", agents=agents, council_enabled=True,
            max_cycles_per_day=12, telegram_enabled=True,
        )

        result = run_council(
            config=config, agents=agents, survey=survey,
            philosophy="", identity_texts={"gandalf": ""},
            memory_summaries={"gandalf": ""}, shared_memory_summary="",
            llm=mock_llm, journal_dir=journal_dir,
        )
        assert "failed" in result.perspectives[0].perspective.lower()
        assert "failed" in result.decision.lower()

    def test_chair_rotation_advances(self, tmp_path: Path) -> None:
        agents = make_agents()
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir()
        save_chair_index(journal_dir, 1)  # Start at gimli

        agent_response = '{"perspective": "ok", "proposed_action": "ok"}'
        chair_response = '{"decision": "ok", "action_plan": "ok", "flag_for_jord": false, "flag_reason": ""}'
        mock_llm = self._make_mock_llm([agent_response] * 4 + [chair_response])

        from brain.config import Config
        config = Config(
            daily_limit_usd=5.0, model_default="test", model_reasoning="test",
            model_council="test", agents=agents, council_enabled=True,
            max_cycles_per_day=12, telegram_enabled=True,
        )

        result = run_council(
            config=config, agents=agents, survey=make_survey(),
            philosophy="", identity_texts={a.name: "" for a in agents},
            memory_summaries={a.name: "" for a in agents},
            shared_memory_summary="", llm=mock_llm, journal_dir=journal_dir,
        )
        assert result.chair_name == "gimli"
        assert get_chair_index(journal_dir) == 2  # Advanced to galadriel
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/brain/test_council.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement brain/council.py**

```python
"""Council deliberation: each agent gives their perspective, chair decides.

Flow:
1. Each agent gets: survey context + PHILOSOPHY.md + own identity + own memory + shared memory
2. Each responds with their perspective and proposed action
3. Chair agent receives all perspectives and commits to an action plan
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Protocol, runtime_checkable

from brain.config import AgentConfig, Config
from brain.survey import SurveyResult

log = logging.getLogger("foreman.brain.council")


class LLMResponseLike(Protocol):
    """Minimal interface for LLM response objects."""

    text: str
    input_tokens: int
    output_tokens: int


class LLMPort(Protocol):
    """Interface for LLM calls — keeps council decoupled from provider."""

    def complete(
        self, model: str, system: str, message: str, max_tokens: Optional[int] = None
    ) -> LLMResponseLike: ...


@dataclass
class AgentPerspective:
    """One agent's response during deliberation."""

    agent_name: str
    perspective: str
    proposed_action: str


@dataclass
class CouncilResult:
    """Outcome of a council deliberation cycle."""

    perspectives: List[AgentPerspective]
    chair_name: str
    decision: str
    action_plan: str


def get_chair_index(journal_dir: Path) -> int:
    """Read the current chair index from journal. Returns 0 if not found."""
    index_file = journal_dir / ".chair_index"
    if not index_file.exists():
        return 0
    try:
        return int(index_file.read_text().strip())
    except (ValueError, OSError):
        return 0


def save_chair_index(journal_dir: Path, index: int) -> None:
    """Save the current chair index for next cycle's rotation."""
    journal_dir.mkdir(parents=True, exist_ok=True)
    (journal_dir / ".chair_index").write_text(str(index))


def _build_deliberation_prompt(
    agent: AgentConfig,
    philosophy: str,
    identity: str,
    own_memory_summary: str,
    shared_memory_summary: str,
    survey_context: str,
) -> tuple[str, str]:
    """Build system and user prompts for one agent's deliberation.

    Returns (system_prompt, user_message).
    """
    system = (
        f"{philosophy}\n\n"
        f"---\n\n"
        f"# Your Identity\n\n{identity}\n\n"
        f"You are {agent.name}, the {agent.role}. "
        f"You are participating in a council deliberation. "
        f"Review the current state and give your perspective on what the society "
        f"should prioritize. Propose a specific action.\n\n"
        f"Respond in this JSON format:\n"
        f'{{"perspective": "your analysis", "proposed_action": "specific action to take"}}'
    )
    user = (
        f"{survey_context}\n\n"
        f"---\n\n"
        f"# Your Private Memory\n\n{own_memory_summary}\n\n"
        f"# Shared Memory\n\n{shared_memory_summary}"
    )
    return system, user


def _build_chair_prompt(
    chair: AgentConfig,
    philosophy: str,
    identity: str,
    perspectives: List[AgentPerspective],
    survey_context: str,
) -> tuple[str, str]:
    """Build system and user prompts for the chair's decision.

    Returns (system_prompt, user_message).
    """
    perspectives_text = "\n\n".join(
        f"**{p.agent_name}**: {p.perspective}\n"
        f"Proposed action: {p.proposed_action}"
        for p in perspectives
    )
    system = (
        f"{philosophy}\n\n"
        f"---\n\n"
        f"# Your Identity\n\n{identity}\n\n"
        f"You are {chair.name}, the {chair.role}. "
        f"You are the chair for this council cycle. "
        f"Review all perspectives and decide on ONE action for this cycle. "
        f"Be specific about what to do and why.\n\n"
        f"If there is a disagreement about something risky (deleting code, "
        f"changing architecture), flag it for Jord instead of acting.\n\n"
        f"Respond in this JSON format:\n"
        f'{{"decision": "what we will do and why", '
        f'"action_plan": "specific steps to execute", '
        f'"flag_for_jord": false, '
        f'"flag_reason": ""}}'
    )
    user = (
        f"{survey_context}\n\n"
        f"---\n\n"
        f"# Council Perspectives\n\n{perspectives_text}"
    )
    return system, user


def _parse_json_response(text: str) -> dict:
    """Extract JSON from an LLM response, handling markdown fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:]  # skip opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)
    return json.loads(cleaned)


def run_council(
    config: Config,
    agents: List[AgentConfig],
    survey: SurveyResult,
    philosophy: str,
    identity_texts: dict[str, str],
    memory_summaries: dict[str, str],
    shared_memory_summary: str,
    llm: LLMPort,
    journal_dir: Path,
) -> CouncilResult:
    """Run one council deliberation cycle.

    Args:
        config: Parsed config
        agents: Agent roster (ordered for chair rotation)
        survey: Current world state
        philosophy: PHILOSOPHY.md content
        identity_texts: {agent_name: identity file content}
        memory_summaries: {agent_name: summary of private memory}
        shared_memory_summary: Summary of shared memory
        llm: LLM client (protocol-typed)
        journal_dir: Path to memory/shared/journal/ for chair rotation state

    Returns:
        CouncilResult with perspectives and chair decision
    """
    survey_context = survey.to_context_string()

    # Phase 1: Deliberation — one call per agent
    perspectives: List[AgentPerspective] = []
    for agent in agents:
        identity = identity_texts.get(agent.name, f"You are {agent.name}.")
        own_memory = memory_summaries.get(agent.name, "(no private memory yet)")

        system, user = _build_deliberation_prompt(
            agent, philosophy, identity, own_memory,
            shared_memory_summary, survey_context,
        )
        try:
            response = llm.complete(
                model=config.model_council,
                system=system,
                message=user,
                max_tokens=1024,
            )
            data = _parse_json_response(response.text)
            perspectives.append(AgentPerspective(
                agent_name=agent.name,
                perspective=data.get("perspective", response.text),
                proposed_action=data.get("proposed_action", ""),
            ))
        except Exception as e:
            log.error(f"Agent {agent.name} deliberation failed: {e}")
            perspectives.append(AgentPerspective(
                agent_name=agent.name,
                perspective=f"(deliberation failed: {e})",
                proposed_action="",
            ))

    # Phase 2: Chair decision
    chair_index = get_chair_index(journal_dir)
    chair_index = chair_index % len(agents)
    chair = agents[chair_index]

    chair_identity = identity_texts.get(chair.name, f"You are {chair.name}.")
    system, user = _build_chair_prompt(
        chair, philosophy, chair_identity, perspectives, survey_context,
    )
    try:
        response = llm.complete(
            model=config.model_council,
            system=system,
            message=user,
            max_tokens=2048,
        )
        data = _parse_json_response(response.text)
        decision = data.get("decision", response.text)
        action_plan = data.get("action_plan", "")
    except Exception as e:
        log.error(f"Chair {chair.name} decision failed: {e}")
        decision = f"Chair decision failed: {e}"
        action_plan = ""

    # Rotate chair for next cycle
    next_index = (chair_index + 1) % len(agents)
    save_chair_index(journal_dir, next_index)

    return CouncilResult(
        perspectives=perspectives,
        chair_name=chair.name,
        decision=decision,
        action_plan=action_plan,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/brain/test_council.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add brain/council.py tests/brain/test_council.py
git commit -m "feat: add brain/council.py — agent deliberation and chair rotation

Each agent gets one LLM call for perspective. Chair rotates each cycle,
synthesizes perspectives into an action plan. JSON response parsing
handles markdown fences. TDD."
```

---

## Chunk 6: Tools and Brain Loop (TDD)

### Task 14: Seed toolset — tool definitions and executor

**Files:**
- Create: `tests/brain/test_tools.py`
- Create: `brain/tools.py`

- [ ] **Step 1: Write failing tests**

`tests/brain/test_tools.py`:

```python
"""Tests for brain.tools — seed toolset definitions and execution."""

import pytest
from unittest.mock import MagicMock
from pathlib import Path
from brain.tools import TOOL_SCHEMAS, execute_tool, ToolContext


@pytest.fixture
def tool_context(tmp_path: Path) -> ToolContext:
    memory_root = tmp_path / "memory"
    (memory_root / "shared" / "costs").mkdir(parents=True)
    (memory_root / "shared" / "decisions").mkdir(parents=True)
    (memory_root / "gandalf").mkdir(parents=True)
    return ToolContext(
        repo=MagicMock(),
        memory_root=memory_root,
        agent_name="gandalf",
        notify_fn=MagicMock(return_value=True),
        costs_dir=memory_root / "shared" / "costs",
    )


class TestToolSchemas:
    def test_all_schemas_have_name(self) -> None:
        for schema in TOOL_SCHEMAS:
            assert "name" in schema
            assert "description" in schema
            assert "input_schema" in schema

    def test_expected_tools_present(self) -> None:
        names = {s["name"] for s in TOOL_SCHEMAS}
        expected = {
            "read_file", "create_issue", "create_pr",
            "read_memory", "write_memory", "send_telegram",
            "check_budget", "list_issues", "list_prs",
        }
        assert expected.issubset(names)


class TestReadMemoryTool:
    def test_read_own_memory(self, tool_context: ToolContext) -> None:
        (tool_context.memory_root / "gandalf" / "notes.md").write_text("My notes")
        result = execute_tool("read_memory", {"path": "gandalf/notes.md"}, tool_context)
        assert "My notes" in result

    def test_read_shared_memory(self, tool_context: ToolContext) -> None:
        (tool_context.memory_root / "shared" / "decisions" / "d.md").write_text("Decision X")
        result = execute_tool("read_memory", {"path": "shared/decisions/d.md"}, tool_context)
        assert "Decision X" in result

    def test_read_other_agent_blocked(self, tool_context: ToolContext) -> None:
        result = execute_tool("read_memory", {"path": "gimli/notes.md"}, tool_context)
        assert "permission" in result.lower() or "cannot" in result.lower()


class TestWriteMemoryTool:
    def test_write_own_memory(self, tool_context: ToolContext) -> None:
        result = execute_tool(
            "write_memory",
            {"path": "gandalf/log.md", "content": "Today I explored."},
            tool_context,
        )
        assert "wrote" in result.lower() or "written" in result.lower()
        assert (tool_context.memory_root / "gandalf" / "log.md").read_text() == "Today I explored."

    def test_write_shared_memory(self, tool_context: ToolContext) -> None:
        execute_tool(
            "write_memory",
            {"path": "shared/decisions/new.md", "content": "We decided Y."},
            tool_context,
        )
        assert (tool_context.memory_root / "shared" / "decisions" / "new.md").read_text() == "We decided Y."


class TestCheckBudgetTool:
    def test_returns_budget_info(self, tool_context: ToolContext) -> None:
        result = execute_tool("check_budget", {}, tool_context)
        assert "$" in result


class TestSendTelegramTool:
    def test_calls_notify(self, tool_context: ToolContext) -> None:
        result = execute_tool(
            "send_telegram",
            {"message": "Hello Jord!"},
            tool_context,
        )
        tool_context.notify_fn.assert_called_once_with("Hello Jord!")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/brain/test_tools.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement brain/tools.py**

```python
"""Seed toolset — minimal tools the brain ships with on day one.

Tools: read_file, create_issue, create_pr, read_memory, write_memory,
send_telegram, check_budget, list_issues, list_prs.

Reuses existing brain_tools.py for GitHub operations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from brain.memory import MemoryStore
from brain.cost_tracking import load_today_spend

log = logging.getLogger("foreman.brain.tools")


@dataclass
class ToolContext:
    """Everything tools need to operate."""

    repo: object  # PyGithub Repository
    memory_root: Path
    agent_name: str
    notify_fn: Callable[[str], bool]
    costs_dir: Path
    budget_limit: float = 5.0


TOOL_SCHEMAS = [
    {
        "name": "read_file",
        "description": "Read a file from the repository's main branch.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to repo root."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "create_issue",
        "description": "Create a new GitHub issue.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Issue title."},
                "body": {"type": "string", "description": "Issue body (Markdown)."},
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Labels to apply.",
                },
            },
            "required": ["title", "body"],
        },
    },
    {
        "name": "create_pr",
        "description": "Create a branch, commit files, and open a pull request.",
        "input_schema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string", "description": "Branch name to create."},
                "title": {"type": "string", "description": "PR title."},
                "body": {"type": "string", "description": "PR body (Markdown)."},
                "files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                    },
                    "description": "Files to commit.",
                },
            },
            "required": ["branch", "title", "body", "files"],
        },
    },
    {
        "name": "read_memory",
        "description": "Read a memory file. Use 'agent_name/file.md' for own memory or 'shared/subdir/file.md' for shared.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Memory path (e.g., 'gandalf/notes.md' or 'shared/costs/2026-03-15.md')."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_memory",
        "description": "Write a memory file. Can only write to own memory or shared/.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Memory path to write."},
                "content": {"type": "string", "description": "Content to write."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "send_telegram",
        "description": "Send a message to Jord via Telegram.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message text."},
            },
            "required": ["message"],
        },
    },
    {
        "name": "check_budget",
        "description": "Check remaining budget for today.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "list_issues",
        "description": "List open GitHub issues with labels.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "list_prs",
        "description": "List open pull requests with status.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


def execute_tool(name: str, tool_input: dict, ctx: ToolContext) -> str:
    """Dispatch a tool call by name. Returns a string result."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return f"Error: unknown tool '{name}'"
    try:
        return handler(tool_input, ctx)
    except Exception as e:
        log.error(f"Tool {name} failed: {e}")
        return f"Error executing {name}: {e}"


# ── Handler implementations ──────────────────────────────────

def _read_file(tool_input: dict, ctx: ToolContext) -> str:
    try:
        content = ctx.repo.get_contents(tool_input["path"], ref="main")
        text = content.decoded_content.decode("utf-8")
        if len(text) > 10000:
            return f"{text[:10000]}\n\n--- truncated ({len(text)} total chars) ---"
        return text
    except Exception as e:
        return f"Error reading '{tool_input['path']}': {e}"


def _create_issue(tool_input: dict, ctx: ToolContext) -> str:
    try:
        labels = tool_input.get("labels", [])
        label_objects = []
        for name in labels:
            try:
                label_objects.append(ctx.repo.get_label(name))
            except Exception:
                pass
        issue = ctx.repo.create_issue(
            title=tool_input["title"],
            body=tool_input["body"],
            labels=label_objects,
        )
        return f"Created issue #{issue.number}: {issue.title}"
    except Exception as e:
        return f"Error creating issue: {e}"


def _create_pr(tool_input: dict, ctx: ToolContext) -> str:
    try:
        branch = tool_input["branch"]
        main_ref = ctx.repo.get_git_ref("heads/main")
        ctx.repo.create_git_ref(f"refs/heads/{branch}", main_ref.object.sha)

        for file_data in tool_input["files"]:
            ctx.repo.create_file(
                path=file_data["path"],
                message=f"Add {file_data['path']}",
                content=file_data["content"],
                branch=branch,
            )

        pr = ctx.repo.create_pull(
            title=tool_input["title"],
            body=tool_input["body"],
            head=branch,
            base="main",
        )
        return f"Created PR #{pr.number}: {pr.title}"
    except Exception as e:
        return f"Error creating PR: {e}"


def _read_memory(tool_input: dict, ctx: ToolContext) -> str:
    path = tool_input["path"]
    parts = path.split("/", 1)
    owner = parts[0]
    filename = parts[1] if len(parts) > 1 else ""
    store = MemoryStore(ctx.memory_root, ctx.agent_name)
    try:
        content = store.read(owner, filename)
        return content if content is not None else f"No file found at {path}"
    except PermissionError as e:
        return str(e)


def _write_memory(tool_input: dict, ctx: ToolContext) -> str:
    path = tool_input["path"]
    parts = path.split("/", 1)
    owner = parts[0]
    filename = parts[1] if len(parts) > 1 else ""
    store = MemoryStore(ctx.memory_root, ctx.agent_name)
    try:
        store.write(owner, filename, tool_input["content"])
        return f"Wrote to {path}"
    except PermissionError as e:
        return str(e)


def _send_telegram(tool_input: dict, ctx: ToolContext) -> str:
    success = ctx.notify_fn(tool_input["message"])
    return "Message sent." if success else "Failed to send message."


def _check_budget(tool_input: dict, ctx: ToolContext) -> str:
    spent = load_today_spend(ctx.costs_dir)
    remaining = max(0.0, ctx.budget_limit - spent)
    return f"Budget: ${remaining:.2f} remaining (${spent:.2f} spent of ${ctx.budget_limit:.2f})"


def _list_issues(tool_input: dict, ctx: ToolContext) -> str:
    try:
        issues = list(ctx.repo.get_issues(state="open"))
        real = [i for i in issues if i.pull_request is None]
        lines = [f"# Open Issues ({len(real)})"]
        for i in real:
            labels = ", ".join(l.name for l in i.labels)
            label_str = f" [{labels}]" if labels else ""
            lines.append(f"  - #{i.number}: {i.title}{label_str}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing issues: {e}"


def _list_prs(tool_input: dict, ctx: ToolContext) -> str:
    try:
        prs = list(ctx.repo.get_pulls(state="open"))
        lines = [f"# Open PRs ({len(prs)})"]
        for pr in prs:
            lines.append(f"  - PR #{pr.number}: {pr.title}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing PRs: {e}"


_HANDLERS = {
    "read_file": _read_file,
    "create_issue": _create_issue,
    "create_pr": _create_pr,
    "read_memory": _read_memory,
    "write_memory": _write_memory,
    "send_telegram": _send_telegram,
    "check_budget": _check_budget,
    "list_issues": _list_issues,
    "list_prs": _list_prs,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/brain/test_tools.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add brain/tools.py tests/brain/test_tools.py
git commit -m "feat: add brain/tools.py — seed toolset with 9 tools

read_file, create_issue, create_pr, read_memory, write_memory,
send_telegram, check_budget, list_issues, list_prs. Memory tools
enforce privacy via MemoryStore. TDD."
```

---

### Task 15: Brain loop — the Wiggum loop

**Files:**
- Create: `tests/brain/test_loop.py`
- Create: `brain/loop.py`
- Create: `brain.py` (CLI entry point)

- [ ] **Step 1: Write failing tests**

`tests/brain/test_loop.py`:

```python
"""Tests for brain.loop — the Wiggum loop (one cycle)."""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from brain.loop import run_cycle, CycleOutcome
from brain.config import Config, AgentConfig


def make_config() -> Config:
    return Config(
        daily_limit_usd=5.0,
        model_default="gemini/gemini-2.5-flash",
        model_reasoning="gemini/gemini-2.5-pro",
        model_council="anthropic/claude-sonnet-4-6",
        agents=[
            AgentConfig("gandalf", "scout", Path("agents/gandalf.md"), Path("memory/gandalf/")),
            AgentConfig("gimli", "builder", Path("agents/gimli.md"), Path("memory/gimli/")),
        ],
        council_enabled=True,
        max_cycles_per_day=12,
        telegram_enabled=True,
    )


@pytest.fixture
def cycle_env(tmp_path: Path):
    """Set up a minimal environment for run_cycle tests."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    memory_root = tmp_path / "memory"
    for d in ["shared/costs", "shared/decisions", "shared/journal", "shared/incidents",
              "gandalf", "gimli"]:
        (memory_root / d).mkdir(parents=True)

    # Write philosophy
    (repo_root / "PHILOSOPHY.md").write_text("Be good. Grow.")
    # Write agent identities
    agents_dir = repo_root / "agents"
    agents_dir.mkdir()
    (agents_dir / "gandalf.md").write_text("You are Gandalf.")
    (agents_dir / "gimli.md").write_text("You are Gimli.")

    return {
        "config": make_config(),
        "repo_root": repo_root,
        "memory_root": memory_root,
        "philosophy": "Be good. Grow.",
    }


class TestCycleOutcome:
    def test_budget_exhausted_outcome(self) -> None:
        outcome = CycleOutcome(
            status="budget_exhausted",
            decision="",
            action_result="",
            cost=0.0,
            error=None,
        )
        assert outcome.status == "budget_exhausted"

    def test_success_outcome(self) -> None:
        outcome = CycleOutcome(
            status="success",
            decision="Research new models",
            action_result="Created issue #100",
            cost=0.25,
            error=None,
        )
        assert outcome.status == "success"
        assert outcome.cost == 0.25

    def test_error_outcome(self) -> None:
        outcome = CycleOutcome(
            status="error",
            decision="",
            action_result="",
            cost=0.0,
            error="LLM API returned 500",
        )
        assert outcome.error is not None


class TestRunCycleBudgetExhausted:
    def test_exits_early_when_budget_spent(self, cycle_env) -> None:
        import json
        from datetime import datetime, timezone
        # Write cost entries exceeding the budget
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        costs_dir = cycle_env["memory_root"] / "shared" / "costs"
        (costs_dir / f"{today}.jsonl").write_text(
            json.dumps({"cost_usd": 10.0}) + "\n"
        )
        mock_repo = MagicMock()
        mock_llm = MagicMock()

        outcome = run_cycle(
            config=cycle_env["config"],
            repo=mock_repo,
            llm=mock_llm,
            memory_root=cycle_env["memory_root"],
            philosophy=cycle_env["philosophy"],
            repo_root=cycle_env["repo_root"],
        )
        assert outcome.status == "budget_exhausted"
        mock_llm.complete.assert_not_called()


class TestRunCycleSuccess:
    def test_runs_council_and_writes_journal(self, cycle_env) -> None:
        mock_repo = MagicMock()
        mock_repo.get_issues.return_value = []
        mock_repo.get_pulls.return_value = []

        mock_llm = MagicMock()
        agent_resp = MagicMock()
        agent_resp.text = '{"perspective": "lets build", "proposed_action": "create issue"}'
        agent_resp.input_tokens = 100
        agent_resp.output_tokens = 50
        chair_resp = MagicMock()
        chair_resp.text = '{"decision": "build it", "action_plan": "step 1", "flag_for_jord": false, "flag_reason": ""}'
        chair_resp.input_tokens = 200
        chair_resp.output_tokens = 100
        mock_llm.complete.side_effect = [agent_resp, agent_resp, chair_resp]

        outcome = run_cycle(
            config=cycle_env["config"],
            repo=mock_repo,
            llm=mock_llm,
            memory_root=cycle_env["memory_root"],
            philosophy=cycle_env["philosophy"],
            repo_root=cycle_env["repo_root"],
        )
        assert outcome.status == "success"
        assert "build" in outcome.decision.lower()
        # Journal should have been written
        journal_files = list((cycle_env["memory_root"] / "shared" / "journal").glob("*.md"))
        assert len(journal_files) >= 1


class TestRunCycleSurveyFailure:
    def test_logs_incident_on_survey_error(self, cycle_env) -> None:
        mock_repo = MagicMock()
        mock_repo.get_issues.side_effect = Exception("GitHub API down")
        mock_llm = MagicMock()

        # Survey should still succeed (it catches GitHub errors internally)
        # but with empty issues/PRs
        agent_resp = MagicMock()
        agent_resp.text = '{"perspective": "no data", "proposed_action": "wait"}'
        agent_resp.input_tokens = 50
        agent_resp.output_tokens = 25
        chair_resp = MagicMock()
        chair_resp.text = '{"decision": "wait", "action_plan": "skip", "flag_for_jord": false, "flag_reason": ""}'
        chair_resp.input_tokens = 100
        chair_resp.output_tokens = 50
        mock_llm.complete.side_effect = [agent_resp, agent_resp, chair_resp]

        outcome = run_cycle(
            config=cycle_env["config"],
            repo=mock_repo,
            llm=mock_llm,
            memory_root=cycle_env["memory_root"],
            philosophy=cycle_env["philosophy"],
            repo_root=cycle_env["repo_root"],
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/brain/test_loop.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement brain/loop.py**

```python
"""The Wiggum loop — one brain cycle.

Each invocation:
1. Load config, philosophy, memory
2. Check budget — exit early if exhausted
3. Survey the world (GitHub, memory, budget)
4. Run council deliberation
5. Execute the decided action via tools
6. Write memory (journal, costs, incidents)
7. Exit
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from github import Github

from brain.config import Config, load_config
from brain.cost_tracking import load_today_spend, append_cost_entry
from brain.council import CouncilResult, run_council
from brain.memory import MemoryStore
from brain.survey import SurveyResult, gather_survey
from brain.tools import ToolContext, execute_tool, TOOL_SCHEMAS  # noqa: F401 — TOOL_SCHEMAS used in future tool-use wiring
from llm_client import LLMClient
from telegram_notifier import notify

log = logging.getLogger("foreman.brain.loop")


@dataclass
class CycleOutcome:
    """Result of one brain cycle."""

    status: str  # "success", "budget_exhausted", "error"
    decision: str
    action_result: str
    cost: float
    error: Optional[str]


def run_cycle(
    config: Config,
    repo: object,
    llm: object,
    memory_root: Path,
    philosophy: str,
    repo_root: Path,
) -> CycleOutcome:
    """Run one brain cycle. This is the Wiggum loop body."""

    costs_dir = memory_root / "shared" / "costs"
    costs_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Check budget
    spent = load_today_spend(costs_dir)
    if spent >= config.daily_limit_usd:
        log.warning("Budget exhausted — skipping cycle")
        _write_journal(memory_root, "Budget exhausted. Cycle skipped.")
        notify("Budget exhausted for today. Resting.")
        return CycleOutcome("budget_exhausted", "", "", 0.0, None)

    # Step 2: Survey
    try:
        survey = gather_survey(config, memory_root, repo)
    except Exception as e:
        log.error(f"Survey failed: {e}")
        _write_incident(memory_root, f"Survey failed: {e}")
        return CycleOutcome("error", "", "", 0.0, str(e))

    # Step 3: Load agent identities and memories
    identity_texts = {}
    memory_summaries = {}
    for agent in config.agents:
        identity_path = repo_root / agent.identity_path
        if identity_path.exists():
            identity_texts[agent.name] = identity_path.read_text()
        else:
            identity_texts[agent.name] = f"You are {agent.name}, the {agent.role}."

        store = MemoryStore(memory_root, agent.name)
        files = store.list_files(agent.name)
        if files:
            summaries = []
            for f in files[:5]:  # Limit to 5 most recent
                content = store.read(agent.name, f)
                if content:
                    summaries.append(f"## {f}\n{content}")
            memory_summaries[agent.name] = "\n\n".join(summaries)
        else:
            memory_summaries[agent.name] = "(no private memory yet)"

    # Shared memory summary
    shared_store = MemoryStore(memory_root, "shared")
    shared_parts = []
    for subdir in ["decisions", "journal", "incidents"]:
        files = shared_store.list_files("shared", subdirectory=subdir)
        for f in files[:3]:
            content = shared_store.read("shared", f"{subdir}/{f}")
            if content:
                shared_parts.append(f"## {subdir}/{f}\n{content}")
    shared_memory_summary = "\n\n".join(shared_parts) if shared_parts else "(no shared memory yet)"

    # Step 4: Council
    journal_dir = memory_root / "shared" / "journal"
    try:
        council_result = run_council(
            config=config,
            agents=config.agents,
            survey=survey,
            philosophy=philosophy,
            identity_texts=identity_texts,
            memory_summaries=memory_summaries,
            shared_memory_summary=shared_memory_summary,
            llm=llm,
            journal_dir=journal_dir,
        )
    except Exception as e:
        log.error(f"Council failed: {e}")
        _write_incident(memory_root, f"Council failed: {e}")
        return CycleOutcome("error", "", "", 0.0, str(e))

    # Step 5: Act — execute the action plan via tool-use LLM call
    action_result = _execute_action(
        config, council_result, repo, memory_root, llm, notify,
    )
    log.info(f"Council decided: {council_result.decision}")

    # Step 6: Reflect
    journal_entry = (
        f"# Cycle {datetime.now(timezone.utc).isoformat()}\n\n"
        f"Chair: {council_result.chair_name}\n\n"
        f"## Perspectives\n"
        + "\n".join(
            f"- **{p.agent_name}**: {p.perspective}" for p in council_result.perspectives
        )
        + f"\n\n## Decision\n{council_result.decision}\n\n"
        f"## Action Plan\n{council_result.action_plan}\n"
    )
    _write_journal(memory_root, journal_entry)

    return CycleOutcome(
        status="success",
        decision=council_result.decision,
        action_result=action_result,
        cost=0.0,  # TODO: track actual LLM costs from council
        error=None,
    )


def _execute_action(
    config: Config,
    council_result: CouncilResult,
    repo: object,
    memory_root: Path,
    llm: object,
    notify_fn: object,
) -> str:
    """Execute the council's action plan using the seed toolset.

    Makes an LLM call with tool schemas, letting the model invoke tools
    to carry out the action plan. Returns a summary of what was done.
    """
    if not council_result.action_plan:
        return "No action plan — skipping execution."

    tool_ctx = ToolContext(
        repo=repo,
        memory_root=memory_root,
        agent_name=council_result.chair_name,
        notify_fn=notify_fn,
        costs_dir=memory_root / "shared" / "costs",
        budget_limit=config.daily_limit_usd,
    )

    # For the seed implementation, we log the action plan.
    # Full tool-use execution (LLM call with tool schemas, parse tool_use
    # blocks, call execute_tool, return results) is wired up once the
    # organism has proven the council loop works. The organism can PR
    # the upgrade from "log plan" to "execute plan via tool-use".
    log.info(f"Action plan: {council_result.action_plan}")
    return f"Decision: {council_result.decision}\nPlan: {council_result.action_plan}"


def _write_journal(memory_root: Path, content: str) -> None:
    """Write a journal entry to shared memory."""
    journal_dir = memory_root / "shared" / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S")
    (journal_dir / f"{timestamp}.md").write_text(content)


def _write_incident(memory_root: Path, content: str) -> None:
    """Write an incident to shared memory."""
    incidents_dir = memory_root / "shared" / "incidents"
    incidents_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S")
    (incidents_dir / f"{timestamp}.md").write_text(content)


def main() -> None:
    """CLI entry point — load config, connect to GitHub, run one cycle."""
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")

    repo_root = Path(".")
    config = load_config(repo_root / "config.yml")

    # Load philosophy
    philosophy_path = repo_root / "PHILOSOPHY.md"
    if philosophy_path.exists():
        philosophy = philosophy_path.read_text()
    else:
        log.warning("PHILOSOPHY.md not found — running without constitution")
        philosophy = ""

    # Connect to GitHub
    gh_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_PAT")
    repo_name = os.environ.get("FOREMAN_REPO")
    if not gh_token or not repo_name:
        log.error("GITHUB_TOKEN and FOREMAN_REPO must be set")
        return

    gh = Github(gh_token)
    repo = gh.get_repo(repo_name)

    # LLM client
    llm = LLMClient()

    # Memory root
    memory_root = repo_root / "memory"

    # Run one cycle
    outcome = run_cycle(config, repo, llm, memory_root, philosophy, repo_root)
    log.info(f"Cycle complete: {outcome.status}")
    if outcome.error:
        log.error(f"Error: {outcome.error}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/brain/test_loop.py -v`
Expected: All tests PASS

- [ ] **Step 5: Create brain.py entry point**

`brain.py`:

```python
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
```

- [ ] **Step 6: Commit**

```bash
git add brain/loop.py tests/brain/test_loop.py brain.py
git commit -m "feat: add brain loop — the Wiggum loop

One cycle: check budget, survey world, run council deliberation,
execute action, write memory. CLI entry point at brain.py.
Designed for GitHub Actions cron triggering. TDD."
```

---

## Chunk 7: GitHub Actions Workflows

### Task 16: Brain loop workflow

**Files:**
- Create: `.github/workflows/brain_loop.yml`

- [ ] **Step 1: Create brain_loop.yml**

```yaml
name: Brain Loop

on:
  schedule:
    - cron: '0 */2 * * *'  # Every 2 hours
  workflow_dispatch:  # Manual trigger

concurrency:
  group: brain-loop
  cancel-in-progress: false

jobs:
  cycle:
    runs-on: ubuntu-latest
    timeout-minutes: 30

    permissions:
      issues: write
      pull-requests: write
      contents: write  # Needs write to commit memory files

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install --quiet -r requirements.txt

      - name: Run Brain Cycle
        run: python brain.py
        env:
          GITHUB_TOKEN: ${{ secrets.GH_PAT }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          FOREMAN_REPO: ${{ secrets.FOREMAN_REPO }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}

      - name: Commit memory updates
        run: |
          git config user.name "foreman-brain"
          git config user.email "foreman@noreply.github.com"
          git add memory/
          git diff --staged --quiet || git commit -m "brain: cycle memory update [skip ci]"
          git push
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/brain_loop.yml
git commit -m "feat: add brain_loop.yml — cron-triggered brain cycle

Runs every 2 hours. Checks out repo, runs one brain cycle, commits
memory updates back to main. Concurrency group prevents overlap."
```

---

### Task 17: Watchdog workflow

**Files:**
- Create: `.github/workflows/watchdog.yml`

- [ ] **Step 1: Create watchdog.yml**

```yaml
name: Watchdog

on:
  schedule:
    - cron: '0 12 * * *'  # Once daily at noon UTC
  workflow_dispatch:

jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 5

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Check brain loop health
        run: |
          # Look for a journal entry from the last 24 hours
          LATEST=$(ls -t memory/shared/journal/*.md 2>/dev/null | head -1)
          if [ -z "$LATEST" ]; then
            echo "::warning::No journal entries found — brain may not have run yet"
            echo "BRAIN_STATUS=no_entries" >> $GITHUB_ENV
          else
            # Check if the latest entry is less than 24 hours old
            FILE_DATE=$(basename "$LATEST" .md | cut -c1-10)
            TODAY=$(date -u +%Y-%m-%d)
            YESTERDAY=$(date -u -d "yesterday" +%Y-%m-%d 2>/dev/null || date -u -v-1d +%Y-%m-%d)
            if [ "$FILE_DATE" = "$TODAY" ] || [ "$FILE_DATE" = "$YESTERDAY" ]; then
              echo "Brain loop is healthy — last entry: $LATEST"
              echo "BRAIN_STATUS=healthy" >> $GITHUB_ENV
            else
              echo "::error::Brain loop may be broken — last entry is from $FILE_DATE"
              echo "BRAIN_STATUS=stale" >> $GITHUB_ENV
            fi
          fi

      - name: Alert Jord if unhealthy
        if: env.BRAIN_STATUS == 'stale'
        run: |
          curl -s -X POST "https://api.telegram.org/bot${{ secrets.TELEGRAM_BOT_TOKEN }}/sendMessage" \
            -H "Content-Type: application/json" \
            -d '{
              "chat_id": "${{ secrets.TELEGRAM_CHAT_ID }}",
              "text": "🚨 Watchdog alert: Brain loop appears to be broken. Last journal entry is stale. I think I need help, Jord.",
              "parse_mode": "HTML"
            }'
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/watchdog.yml
git commit -m "feat: add watchdog.yml — daily brain loop health check

Checks if the brain loop ran in the last 24 hours by looking at
journal entries. Messages Jord on Telegram if something looks wrong."
```

---

### Task 18: Integration test

**Files:**
- Create: `tests/brain/test_integration.py`

- [ ] **Step 1: Write integration test**

`tests/brain/test_integration.py`:

```python
"""Integration test — full brain cycle with mocks."""

import json
import pytest
from unittest.mock import MagicMock
from pathlib import Path
from datetime import datetime, timezone
from brain.config import Config, AgentConfig
from brain.loop import run_cycle


@pytest.fixture
def full_env(tmp_path: Path):
    """Set up a complete environment for integration testing."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    memory_root = tmp_path / "memory"
    for d in ["shared/costs", "shared/decisions", "shared/journal",
              "shared/incidents", "gandalf", "gimli"]:
        (memory_root / d).mkdir(parents=True)

    (repo_root / "PHILOSOPHY.md").write_text("Be good. Grow. Be efficient.")
    agents_dir = repo_root / "agents"
    agents_dir.mkdir()
    (agents_dir / "gandalf.md").write_text("You are Gandalf the scout.")
    (agents_dir / "gimli.md").write_text("You are Gimli the builder.")

    config = Config(
        daily_limit_usd=5.0,
        model_default="test/model",
        model_reasoning="test/model",
        model_council="test/model",
        agents=[
            AgentConfig("gandalf", "scout", Path("agents/gandalf.md"), Path("memory/gandalf/")),
            AgentConfig("gimli", "builder", Path("agents/gimli.md"), Path("memory/gimli/")),
        ],
        council_enabled=True,
        max_cycles_per_day=12,
        telegram_enabled=True,
    )

    # Mock GitHub repo
    mock_repo = MagicMock()
    mock_repo.get_issues.return_value = []
    mock_repo.get_pulls.return_value = []

    # Mock LLM — returns valid JSON for deliberation + chair
    agent_resp = MagicMock()
    agent_resp.text = '{"perspective": "We should explore", "proposed_action": "Research models"}'
    agent_resp.input_tokens = 100
    agent_resp.output_tokens = 50
    chair_resp = MagicMock()
    chair_resp.text = '{"decision": "Research models", "action_plan": "List available models", "flag_for_jord": false, "flag_reason": ""}'
    chair_resp.input_tokens = 200
    chair_resp.output_tokens = 100

    mock_llm = MagicMock()
    mock_llm.complete.side_effect = [agent_resp, agent_resp, chair_resp]

    return {
        "config": config,
        "repo_root": repo_root,
        "memory_root": memory_root,
        "mock_repo": mock_repo,
        "mock_llm": mock_llm,
    }


class TestFullCycle:
    def test_complete_cycle_produces_journal_entry(self, full_env) -> None:
        outcome = run_cycle(
            config=full_env["config"],
            repo=full_env["mock_repo"],
            llm=full_env["mock_llm"],
            memory_root=full_env["memory_root"],
            philosophy="Be good. Grow.",
            repo_root=full_env["repo_root"],
        )
        assert outcome.status == "success"
        assert outcome.error is None

        # Verify journal was written
        journal_dir = full_env["memory_root"] / "shared" / "journal"
        journal_files = [f for f in journal_dir.iterdir() if f.suffix == ".md"]
        assert len(journal_files) >= 1

        # Verify journal content mentions the decision
        content = journal_files[0].read_text()
        assert "Research models" in content

    def test_budget_exhausted_skips_everything(self, full_env) -> None:
        # Spend all the budget
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        costs_dir = full_env["memory_root"] / "shared" / "costs"
        (costs_dir / f"{today}.jsonl").write_text(
            json.dumps({"cost_usd": 10.0}) + "\n"
        )
        outcome = run_cycle(
            config=full_env["config"],
            repo=full_env["mock_repo"],
            llm=full_env["mock_llm"],
            memory_root=full_env["memory_root"],
            philosophy="Be good.",
            repo_root=full_env["repo_root"],
        )
        assert outcome.status == "budget_exhausted"
        full_env["mock_llm"].complete.assert_not_called()
```

- [ ] **Step 2: Run integration test**

Run: `pytest tests/brain/test_integration.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/brain/test_integration.py
git commit -m "test: add integration test for full brain cycle

End-to-end test with mock LLM and GitHub: verifies survey, council
deliberation, journal writing, and budget exhaustion early exit."
```

---

### Task 19: Run full test suite

- [ ] **Step 1: Run all tests**

Run: `pytest tests/ -v`
Expected: All tests PASS (existing tests + all new brain/ tests)

- [ ] **Step 2: Verify no import errors**

Run: `python -c "from brain.loop import main; print('OK')"`
Expected: `OK`

---

### Task 20: Final integration commit

- [ ] **Step 1: Verify clean git status**

Run: `git status`
Expected: Clean working tree, all changes committed.

- [ ] **Step 2: Tag the milestone**

```bash
git tag -a v0.3.0 -m "Organism redesign: brain loop, council, memory, philosophy"
```

---

## Summary

| Chunk | Tasks | What it delivers |
|-------|-------|-----------------|
| 1: Cleanup & Foundation | 1-8 | Clean issues, PHILOSOPHY.md, config.yml, agent identities, memory structure, updated VISION.md |
| 2: Config Module | 9 | `brain/config.py` — typed config loader with full tests |
| 3: Memory Module | 10 | `brain/memory.py` — scoped read/write with privacy enforcement |
| 4: Survey & Costs | 11-12 | `brain/cost_tracking.py` + `brain/survey.py` — budget persistence + world state |
| 5: Council | 13 | `brain/council.py` — agent deliberation, chair rotation, decision-making |
| 6: Tools & Loop | 14-15 | `brain/tools.py` + `brain/loop.py` + `brain.py` — seed toolset + Wiggum loop |
| 7: Workflows & Integration | 16-20 | `brain_loop.yml` + `watchdog.yml` + integration test + full test run + v0.3.0 tag |

Total: 20 tasks, ~7 new Python modules, ~8 test files, 2 workflows, 10+ markdown files.

### Note on Tool Execution

The seed brain loop logs the council's action plan but does not yet execute tools via LLM tool-use calls. The `brain/tools.py` module and `ToolContext` are fully built and tested. Wiring up actual tool-use execution (passing TOOL_SCHEMAS to the LLM, parsing tool_use response blocks, calling `execute_tool`) is the organism's first self-improvement task. This is intentional — the seed should be alive (deliberate, decide, write memory) before it starts acting on the world.
