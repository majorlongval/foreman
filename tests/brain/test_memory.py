"""Tests for brain.memory — read/write with privacy enforcement."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root is in path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from brain.memory import MemoryStore


class TestMemoryStoreWrite(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.memory_root = Path(self.tmp_dir.name)
        shared = self.memory_root / "shared"
        shared.mkdir()
        (shared / "decisions").mkdir()
        (shared / "journal").mkdir()
        (shared / "costs").mkdir()
        (shared / "incidents").mkdir()
        (self.memory_root / "gandalf").mkdir()
        (self.memory_root / "gimli").mkdir()
        (self.memory_root / "galadriel").mkdir()

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_write_to_own_memory(self) -> None:
        store = MemoryStore(self.memory_root, agent_name="gandalf")
        store.write("gandalf", "notes.md", "I found something interesting.")
        content = (self.memory_root / "gandalf" / "notes.md").read_text()
        self.assertEqual(content, "I found something interesting.")

    def test_write_to_shared_memory(self) -> None:
        store = MemoryStore(self.memory_root, agent_name="gandalf")
        store.write("shared", "decisions/use-flash.md", "We decided to use flash.")
        content = (self.memory_root / "shared" / "decisions" / "use-flash.md").read_text()
        self.assertEqual(content, "We decided to use flash.")

    def test_cannot_write_to_other_agent_memory(self) -> None:
        store = MemoryStore(self.memory_root, agent_name="gandalf")
        with self.assertRaisesRegex(PermissionError, "cannot write to gimli"):
            store.write("gimli", "notes.md", "Sneaky write attempt.")

    def test_write_creates_subdirectories(self) -> None:
        store = MemoryStore(self.memory_root, agent_name="gandalf")
        store.write("gandalf", "deep/nested/file.md", "Content")
        self.assertTrue((self.memory_root / "gandalf" / "deep" / "nested" / "file.md").exists())


class TestMemoryStoreRead(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.memory_root = Path(self.tmp_dir.name)
        shared = self.memory_root / "shared"
        shared.mkdir()
        (shared / "decisions").mkdir()
        (shared / "journal").mkdir()
        (shared / "costs").mkdir()
        (shared / "incidents").mkdir()
        (self.memory_root / "gandalf").mkdir()
        (self.memory_root / "gimli").mkdir()
        (self.memory_root / "galadriel").mkdir()

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_read_own_memory(self) -> None:
        (self.memory_root / "gandalf" / "notes.md").write_text("My notes")
        store = MemoryStore(self.memory_root, agent_name="gandalf")
        content = store.read("gandalf", "notes.md")
        self.assertEqual(content, "My notes")

    def test_read_shared_memory(self) -> None:
        (self.memory_root / "shared" / "decisions" / "decision.md").write_text("We decided X")
        store = MemoryStore(self.memory_root, agent_name="gandalf")
        content = store.read("shared", "decisions/decision.md")
        self.assertEqual(content, "We decided X")

    def test_cannot_read_other_agent_memory(self) -> None:
        (self.memory_root / "gimli" / "secret.md").write_text("Gimli's secret")
        store = MemoryStore(self.memory_root, agent_name="gandalf")
        with self.assertRaisesRegex(PermissionError, "cannot read from gimli"):
            store.read("gimli", "secret.md")

    def test_read_missing_file_returns_none(self) -> None:
        store = MemoryStore(self.memory_root, agent_name="gandalf")
        result = store.read("gandalf", "nonexistent.md")
        self.assertIsNone(result)


class TestMemoryStoreList(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.memory_root = Path(self.tmp_dir.name)
        shared = self.memory_root / "shared"
        shared.mkdir()
        (shared / "decisions").mkdir()
        (shared / "journal").mkdir()
        (shared / "costs").mkdir()
        (shared / "incidents").mkdir()
        (self.memory_root / "gandalf").mkdir()
        (self.memory_root / "gimli").mkdir()
        (self.memory_root / "galadriel").mkdir()

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_list_own_memory_files(self) -> None:
        (self.memory_root / "gandalf" / "a.md").write_text("A")
        (self.memory_root / "gandalf" / "b.md").write_text("B")
        store = MemoryStore(self.memory_root, agent_name="gandalf")
        files = store.list_files("gandalf")
        self.assertEqual(sorted(files), ["a.md", "b.md"])

    def test_list_shared_subdirectory(self) -> None:
        (self.memory_root / "shared" / "costs" / "2026-03-15.md").write_text("$1.00")
        store = MemoryStore(self.memory_root, agent_name="gandalf")
        files = store.list_files("shared", subdirectory="costs")
        self.assertEqual(files, ["2026-03-15.md"])

    def test_cannot_list_other_agent_memory(self) -> None:
        store = MemoryStore(self.memory_root, agent_name="gandalf")
        with self.assertRaisesRegex(PermissionError, "cannot list gimli"):
            store.list_files("gimli")

    def test_list_empty_directory(self) -> None:
        store = MemoryStore(self.memory_root, agent_name="gandalf")
        files = store.list_files("gandalf")
        self.assertEqual(files, [])


class TestMemoryStoreSharedAccess(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.memory_root = Path(self.tmp_dir.name)
        shared = self.memory_root / "shared"
        shared.mkdir()
        (shared / "decisions").mkdir()
        (shared / "journal").mkdir()
        (shared / "costs").mkdir()
        (shared / "incidents").mkdir()
        (self.memory_root / "gandalf").mkdir()
        (self.memory_root / "gimli").mkdir()
        (self.memory_root / "galadriel").mkdir()

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_any_agent_reads_shared(self) -> None:
        (self.memory_root / "shared" / "decisions" / "d.md").write_text("Decision")
        for agent in ["gandalf", "gimli"]:
            store = MemoryStore(self.memory_root, agent_name=agent)
            self.assertEqual(store.read("shared", "decisions/d.md"), "Decision")

    def test_any_agent_writes_shared(self) -> None:
        store = MemoryStore(self.memory_root, agent_name="gimli")
        store.write("shared", "journal/entry.md", "Gimli was here")
        content = (self.memory_root / "shared" / "journal" / "entry.md").read_text()
        self.assertEqual(content, "Gimli was here")

    def test_any_agent_lists_shared(self) -> None:
        (self.memory_root / "shared" / "costs" / "today.md").write_text("$1")
        store = MemoryStore(self.memory_root, agent_name="galadriel")
        files = store.list_files("shared", subdirectory="costs")
        self.assertIn("today.md", files)


if __name__ == "__main__":
    unittest.main()
