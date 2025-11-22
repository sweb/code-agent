import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from code_agent.tracking import Bug, BugFix
from bug_hunter import merge_bugs, merge_fixes, replace_entrypoints


class TestMergeBugs:
    def test_returns_new_bugs_when_existing_is_empty(self):
        existing: dict[str, Bug] = {}
        new_bug = Bug(
            id="BUG-001",
            short_description="Test bug",
            severity="HIGH",
            status="POTENTIAL",
            relevant_files=["test.py"],
        )
        new = {"BUG-001": new_bug}

        result = merge_bugs(existing, new)

        assert "BUG-001" in result
        assert result["BUG-001"].short_description == "Test bug"

    def test_returns_existing_when_new_is_empty(self):
        existing_bug = Bug(
            id="BUG-001",
            short_description="Existing bug",
            severity="HIGH",
            status="POTENTIAL",
            relevant_files=["test.py"],
        )
        existing = {"BUG-001": existing_bug}
        new: dict[str, Bug] = {}

        result = merge_bugs(existing, new)

        assert "BUG-001" in result
        assert result["BUG-001"].short_description == "Existing bug"

    def test_merges_new_bugs_with_existing(self):
        existing_bug = Bug(
            id="BUG-001",
            short_description="Existing bug",
            severity="HIGH",
            status="POTENTIAL",
            relevant_files=["test.py"],
        )
        new_bug = Bug(
            id="BUG-002",
            short_description="New bug",
            severity="MEDIUM",
            status="POTENTIAL",
            relevant_files=["new.py"],
        )
        existing = {"BUG-001": existing_bug}
        new = {"BUG-002": new_bug}

        result = merge_bugs(existing, new)

        assert len(result) == 2
        assert "BUG-001" in result
        assert "BUG-002" in result

    def test_new_bug_overwrites_existing_with_same_id(self):
        existing_bug = Bug(
            id="BUG-001",
            short_description="Old description",
            severity="HIGH",
            status="POTENTIAL",
            relevant_files=["test.py"],
        )
        updated_bug = Bug(
            id="BUG-001",
            short_description="Updated description",
            severity="HIGH",
            status="IN_ANALYSIS",
            relevant_files=["test.py"],
        )
        existing = {"BUG-001": existing_bug}
        new = {"BUG-001": updated_bug}

        result = merge_bugs(existing, new)

        assert len(result) == 1
        assert result["BUG-001"].short_description == "Updated description"
        assert result["BUG-001"].status == "IN_ANALYSIS"


class TestMergeFixes:
    def test_returns_new_fixes_when_existing_is_empty(self):
        existing: dict[str, BugFix] = {}
        new_fix = BugFix(bug_id="BUG-001", status="IN_REVIEW")
        new = {"BUG-001": new_fix}

        result = merge_fixes(existing, new)

        assert "BUG-001" in result
        assert result["BUG-001"].status == "IN_REVIEW"

    def test_merges_new_fixes_with_existing(self):
        existing_fix = BugFix(bug_id="BUG-001", status="IN_REVIEW")
        new_fix = BugFix(bug_id="BUG-002", status="FINISHED")
        existing = {"BUG-001": existing_fix}
        new = {"BUG-002": new_fix}

        result = merge_fixes(existing, new)

        assert len(result) == 2
        assert "BUG-001" in result
        assert "BUG-002" in result

    def test_new_fix_overwrites_existing_with_same_id(self):
        existing_fix = BugFix(bug_id="BUG-001", status="IN_REVIEW")
        updated_fix = BugFix(bug_id="BUG-001", status="FINISHED")
        existing = {"BUG-001": existing_fix}
        new = {"BUG-001": updated_fix}

        result = merge_fixes(existing, new)

        assert len(result) == 1
        assert result["BUG-001"].status == "FINISHED"


class TestReplaceEntrypoints:
    def test_returns_new_when_provided(self):
        existing = ["old.py"]
        new = ["new1.py", "new2.py"]

        result = replace_entrypoints(existing, new)

        assert result == ["new1.py", "new2.py"]

    def test_returns_existing_when_new_is_none(self):
        existing = ["existing.py"]

        result = replace_entrypoints(existing, None)

        assert result == ["existing.py"]

    def test_returns_empty_list_when_new_is_empty(self):
        existing = ["existing.py"]
        new: list[str] = []

        result = replace_entrypoints(existing, new)

        assert result == []
