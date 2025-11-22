import json
import os
import tempfile

from code_agent.cli import run_cli
from code_agent.tracking import BugHunterNotebook


def test_clear_removes_all_entrypoints():
    with tempfile.TemporaryDirectory() as tmpdir:
        entrypoints_path = os.path.join(tmpdir, "entrypoints.json")
        with open(entrypoints_path, "w") as f:
            json.dump(["path/to/file1.py", "path/to/file2.py"], f)

        notebook = BugHunterNotebook(path=tmpdir)

        notebook.clear()

        assert notebook.entrypoints == []
        with open(entrypoints_path, "r") as f:
            assert json.load(f) == []


def test_clear_removes_potential_and_in_analysis_bugs():
    with tempfile.TemporaryDirectory() as tmpdir:
        bugs_data = {
            "bugs": {
                "BUG-001": {
                    "id": "BUG-001",
                    "short_description": "Potential bug",
                    "severity": "HIGH",
                    "status": "POTENTIAL",
                    "relevant_files": [],
                    "created_at": "2024-01-01T00:00:00",
                    "updated_at": "2024-01-01T00:00:00",
                },
                "BUG-002": {
                    "id": "BUG-002",
                    "short_description": "Solved bug",
                    "severity": "MEDIUM",
                    "status": "SOLVED",
                    "relevant_files": [],
                    "created_at": "2024-01-01T00:00:00",
                    "updated_at": "2024-01-01T00:00:00",
                },
                "BUG-003": {
                    "id": "BUG-003",
                    "short_description": "Another potential",
                    "severity": "LOW",
                    "status": "POTENTIAL",
                    "relevant_files": [],
                    "created_at": "2024-01-01T00:00:00",
                    "updated_at": "2024-01-01T00:00:00",
                },
                "BUG-004": {
                    "id": "BUG-004",
                    "short_description": "In analysis bug",
                    "severity": "HIGH",
                    "status": "IN_ANALYSIS",
                    "relevant_files": [],
                    "created_at": "2024-01-01T00:00:00",
                    "updated_at": "2024-01-01T00:00:00",
                },
            }
        }

        bugs_path = os.path.join(tmpdir, "bugs.json")
        with open(bugs_path, "w") as f:
            json.dump(bugs_data, f)

        notebook = BugHunterNotebook(path=tmpdir)

        notebook.clear()

        assert len(notebook.bugs.bugs) == 1
        assert "BUG-002" in notebook.bugs.bugs
        assert "BUG-001" not in notebook.bugs.bugs
        assert "BUG-003" not in notebook.bugs.bugs
        assert "BUG-004" not in notebook.bugs.bugs


def test_clear_removes_bug_detail_files_for_potential_bugs():
    with tempfile.TemporaryDirectory() as tmpdir:
        bugs_dir = os.path.join(tmpdir, "bugs")
        os.makedirs(bugs_dir)

        bugs_data = {
            "bugs": {
                "BUG-001": {
                    "id": "BUG-001",
                    "short_description": "Potential bug",
                    "severity": "HIGH",
                    "status": "POTENTIAL",
                    "relevant_files": [],
                    "created_at": "2024-01-01T00:00:00",
                    "updated_at": "2024-01-01T00:00:00",
                },
                "BUG-002": {
                    "id": "BUG-002",
                    "short_description": "Solved bug",
                    "severity": "MEDIUM",
                    "status": "SOLVED",
                    "relevant_files": [],
                    "created_at": "2024-01-01T00:00:00",
                    "updated_at": "2024-01-01T00:00:00",
                },
            }
        }
        bugs_path = os.path.join(tmpdir, "bugs.json")
        with open(bugs_path, "w") as f:
            json.dump(bugs_data, f)

        with open(os.path.join(bugs_dir, "BUG-001.md"), "w") as f:
            f.write("# BUG-001 Details")
        with open(os.path.join(bugs_dir, "BUG-002.md"), "w") as f:
            f.write("# BUG-002 Details")

        notebook = BugHunterNotebook(path=tmpdir)

        notebook.clear()

        assert not os.path.exists(os.path.join(bugs_dir, "BUG-001.md"))
        assert os.path.exists(os.path.join(bugs_dir, "BUG-002.md"))


def test_clear_handles_empty_state():
    with tempfile.TemporaryDirectory() as tmpdir:
        notebook = BugHunterNotebook(path=tmpdir)

        notebook.clear()

        assert notebook.entrypoints == []
        assert notebook.bugs.bugs == {}


def test_cli_clear_command():
    with tempfile.TemporaryDirectory() as tmpdir:
        entrypoints_path = os.path.join(tmpdir, "entrypoints.json")
        with open(entrypoints_path, "w") as f:
            json.dump(["path/to/file.py"], f)

        bugs_data = {
            "bugs": {
                "BUG-001": {
                    "id": "BUG-001",
                    "short_description": "Test bug",
                    "severity": "HIGH",
                    "status": "POTENTIAL",
                    "relevant_files": [],
                    "created_at": "2024-01-01T00:00:00",
                    "updated_at": "2024-01-01T00:00:00",
                },
            }
        }
        bugs_path = os.path.join(tmpdir, "bugs.json")
        with open(bugs_path, "w") as f:
            json.dump(bugs_data, f)

        run_cli(["--state-dir", tmpdir, "clear"])

        notebook = BugHunterNotebook(path=tmpdir)
        assert notebook.entrypoints == []
        assert notebook.bugs.bugs == {}
