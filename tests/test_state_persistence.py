import json
import os
import tempfile

import pytest

from code_agent.tracking import (
    Bug,
    BugFix,
    BugDetailsPersistence,
    load_initial_state,
    persist_state,
)


class TestLoadInitialState:
    def test_returns_empty_collections_when_no_files_exist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bugs, fixes, entrypoints = load_initial_state(tmpdir)

            assert bugs == {}
            assert fixes == {}
            assert entrypoints == []

    def test_loads_bugs_from_existing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bugs_data = {
                "bugs": {
                    "BUG-001": {
                        "id": "BUG-001",
                        "short_description": "Test bug",
                        "severity": "HIGH",
                        "status": "POTENTIAL",
                        "relevant_files": ["test.py"],
                        "created_at": "2024-01-01T00:00:00",
                        "updated_at": "2024-01-01T00:00:00",
                    }
                }
            }
            with open(os.path.join(tmpdir, "bugs.json"), "w") as f:
                json.dump(bugs_data, f)

            bugs, fixes, entrypoints = load_initial_state(tmpdir)

            assert "BUG-001" in bugs
            assert bugs["BUG-001"].short_description == "Test bug"
            assert bugs["BUG-001"].severity == "HIGH"

    def test_loads_fixes_from_existing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixes_data = {
                "fixes": {
                    "BUG-001": {
                        "bug_id": "BUG-001",
                        "status": "IN_REVIEW",
                        "created_at": "2024-01-01T00:00:00",
                        "updated_at": "2024-01-01T00:00:00",
                    }
                }
            }
            with open(os.path.join(tmpdir, "fixes.json"), "w") as f:
                json.dump(fixes_data, f)

            bugs, fixes, entrypoints = load_initial_state(tmpdir)

            assert "BUG-001" in fixes
            assert fixes["BUG-001"].status == "IN_REVIEW"

    def test_loads_entrypoints_from_existing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entrypoints_data = ["src/main.py", "src/api.py"]
            with open(os.path.join(tmpdir, "entrypoints.json"), "w") as f:
                json.dump(entrypoints_data, f)

            bugs, fixes, entrypoints = load_initial_state(tmpdir)

            assert entrypoints == ["src/main.py", "src/api.py"]


class TestPersistState:
    def test_creates_directory_if_not_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = os.path.join(tmpdir, "new_state")

            persist_state(state_path, {}, {}, [])

            assert os.path.isdir(state_path)

    def test_writes_bugs_to_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bug = Bug(
                id="BUG-001",
                short_description="Test bug",
                severity="HIGH",
                status="POTENTIAL",
                relevant_files=["test.py"],
            )

            persist_state(tmpdir, {"BUG-001": bug}, {}, [])

            with open(os.path.join(tmpdir, "bugs.json")) as f:
                data = json.load(f)
            assert "BUG-001" in data["bugs"]
            assert data["bugs"]["BUG-001"]["short_description"] == "Test bug"

    def test_writes_fixes_to_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fix = BugFix(bug_id="BUG-001", status="IN_REVIEW")

            persist_state(tmpdir, {}, {"BUG-001": fix}, [])

            with open(os.path.join(tmpdir, "fixes.json")) as f:
                data = json.load(f)
            assert "BUG-001" in data["fixes"]
            assert data["fixes"]["BUG-001"]["status"] == "IN_REVIEW"

    def test_writes_entrypoints_to_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entrypoints = ["src/main.py", "src/api.py"]

            persist_state(tmpdir, {}, {}, entrypoints)

            with open(os.path.join(tmpdir, "entrypoints.json")) as f:
                data = json.load(f)
            assert data == ["src/main.py", "src/api.py"]


class TestBugDetailsPersistence:
    def test_load_returns_none_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            details = BugDetailsPersistence(tmpdir)

            result = details.load_bug_details("BUG-001")

            assert result is None

    def test_load_returns_content_when_file_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bugs_dir = os.path.join(tmpdir, "bugs")
            os.makedirs(bugs_dir)
            with open(os.path.join(bugs_dir, "BUG-001.md"), "w") as f:
                f.write("# Bug Details\n\nThis is the bug description.")

            details = BugDetailsPersistence(tmpdir)
            result = details.load_bug_details("BUG-001")

            assert result == "# Bug Details\n\nThis is the bug description."

    def test_save_creates_directory_and_writes_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            details = BugDetailsPersistence(tmpdir)

            details.save_bug_details("BUG-001", "# New Bug\n\nDescription here.")

            file_path = os.path.join(tmpdir, "bugs", "BUG-001.md")
            assert os.path.exists(file_path)
            with open(file_path) as f:
                assert f.read() == "# New Bug\n\nDescription here."

    def test_save_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bugs_dir = os.path.join(tmpdir, "bugs")
            os.makedirs(bugs_dir)
            with open(os.path.join(bugs_dir, "BUG-001.md"), "w") as f:
                f.write("Old content")

            details = BugDetailsPersistence(tmpdir)
            details.save_bug_details("BUG-001", "New content")

            with open(os.path.join(bugs_dir, "BUG-001.md")) as f:
                assert f.read() == "New content"
