import json
import os
import tempfile

from code_agent.tracking import BugFix, BugFixes, BugHunterNotebook


def test_load_fixes_returns_empty_collection_when_file_missing():
    with tempfile.TemporaryDirectory() as tmpdir:
        notebook = BugHunterNotebook(path=tmpdir)

        fixes = notebook.load_fixes()

        assert isinstance(fixes, BugFixes)
        assert fixes.fixes == {}


def test_load_fixes_returns_collection_when_file_exists():
    with tempfile.TemporaryDirectory() as tmpdir:
        fixes_data = {
            "fixes": {
                "BUG-001": {
                    "bug_id": "BUG-001",
                    "status": "IN_REVIEW",
                    "rejection_reason": None,
                    "created_at": "2024-01-01T00:00:00",
                    "updated_at": "2024-01-01T00:00:00",
                    "manual_adjustments": None
                }
            }
        }

        fixes_path = os.path.join(tmpdir, "fixes.json")
        with open(fixes_path, "w") as f:
            json.dump(fixes_data, f)

        notebook = BugHunterNotebook(path=tmpdir)
        fixes = notebook.load_fixes()

        assert isinstance(fixes, BugFixes)
        assert len(fixes.fixes) == 1
        assert "BUG-001" in fixes.fixes
        assert fixes.fixes["BUG-001"].bug_id == "BUG-001"
        assert fixes.fixes["BUG-001"].status == "IN_REVIEW"


def test_save_fixes_writes_to_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        notebook = BugHunterNotebook(path=tmpdir)
        fix = BugFix(
            bug_id="BUG-001",
            status="IN_REVIEW"
        )
        notebook.fixes = BugFixes(fixes={"BUG-001": fix})

        notebook.save_fixes()

        fixes_path = os.path.join(tmpdir, "fixes.json")
        assert os.path.exists(fixes_path)
        with open(fixes_path, "r") as f:
            data = json.load(f)
        assert "fixes" in data
        assert "BUG-001" in data["fixes"]
        assert data["fixes"]["BUG-001"]["bug_id"] == "BUG-001"
        assert data["fixes"]["BUG-001"]["status"] == "IN_REVIEW"


def test_add_or_update_fix_adds_new_fix():
    with tempfile.TemporaryDirectory() as tmpdir:
        notebook = BugHunterNotebook(path=tmpdir)
        fix = BugFix(
            bug_id="BUG-001",
            status="IN_REVIEW"
        )

        notebook.add_or_update_fix(fix_id="BUG-001", fix=fix)

        assert "BUG-001" in notebook.fixes.fixes
        assert notebook.fixes.fixes["BUG-001"].bug_id == "BUG-001"
        assert notebook.fixes.fixes["BUG-001"].status == "IN_REVIEW"

        fixes_path = os.path.join(tmpdir, "fixes.json")
        assert os.path.exists(fixes_path)


def test_add_or_update_fix_updates_existing_fix():
    with tempfile.TemporaryDirectory() as tmpdir:
        notebook = BugHunterNotebook(path=tmpdir)
        fix = BugFix(
            bug_id="BUG-001",
            status="IN_REVIEW"
        )
        notebook.add_or_update_fix(fix_id="BUG-001", fix=fix)

        updated_fix = BugFix(
            bug_id="BUG-001",
            status="FINISHED"
        )
        notebook.add_or_update_fix(fix_id="BUG-001", fix=updated_fix)

        assert "BUG-001" in notebook.fixes.fixes
        assert notebook.fixes.fixes["BUG-001"].status == "FINISHED"
        assert len(notebook.fixes.fixes) == 1
