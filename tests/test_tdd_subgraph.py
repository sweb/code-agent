import pytest
from langgraph.graph import END

from code_agent.tdd_subgraph import (
    TEMPLATES,
    TDDConfig,
    TaskType,
    after_refactor,
    after_review,
    after_write_tests,
    tdd_graph,
)


@pytest.fixture
def bug_fix_config():
    return TDDConfig(
        task_id="BUG-001",
        task_type=TaskType.BUG_FIX,
        worktree_path="/tmp",
        description="desc",
        details="details",
    )


@pytest.fixture
def bug_fix_config_with_max_attempts():
    return TDDConfig(
        task_id="BUG-001",
        task_type=TaskType.BUG_FIX,
        worktree_path="/tmp",
        description="desc",
        details="details",
        max_review_attempts=3,
    )


class TestTDDConfigDefaults:
    def test_relevant_files_defaults_to_empty_list(self):
        config = TDDConfig(
            task_id="BUG-001",
            task_type=TaskType.BUG_FIX,
            worktree_path="/tmp/worktree",
            description="Fix the bug",
            details="Details",
        )

        assert config.relevant_files == []

    def test_max_review_attempts_defaults_to_3(self):
        config = TDDConfig(
            task_id="BUG-001",
            task_type=TaskType.BUG_FIX,
            worktree_path="/tmp/worktree",
            description="Fix the bug",
            details="Details",
        )

        assert config.max_review_attempts == 3


class TestTemplates:
    def test_templates_has_all_task_types(self):
        assert TaskType.BUG_FIX in TEMPLATES
        assert TaskType.FEATURE in TEMPLATES
        assert TaskType.REFACTOR in TEMPLATES

    def test_bug_fix_has_all_phases(self):
        bug_fix_templates = TEMPLATES[TaskType.BUG_FIX]
        assert "write_tests" in bug_fix_templates
        assert "implement" in bug_fix_templates
        assert "refactor" in bug_fix_templates
        assert "review" in bug_fix_templates

    def test_feature_has_all_phases(self):
        feature_templates = TEMPLATES[TaskType.FEATURE]
        assert "write_tests" in feature_templates
        assert "implement" in feature_templates
        assert "refactor" in feature_templates
        assert "review" in feature_templates

    def test_refactor_skips_refactor_phase(self):
        refactor_templates = TEMPLATES[TaskType.REFACTOR]
        assert "write_tests" in refactor_templates
        assert "implement" in refactor_templates
        assert refactor_templates["refactor"] is None
        assert "review" in refactor_templates

    def test_templates_contain_task_id_placeholder(self):
        for task_type in TaskType:
            for phase, template in TEMPLATES[task_type].items():
                if template is not None:
                    assert "{task_id}" in template, (
                        f"{task_type.value}.{phase} missing {{task_id}}"
                    )


class TestRoutingFunctions:
    def test_after_write_tests_returns_end_when_discarded(self, bug_fix_config):
        state = {
            "config": bug_fix_config,
            "phase": "write_tests",
            "test_file_path": None,
            "implementation_notes": "",
            "review_attempts": 0,
            "status": "DISCARDED",
            "rejection_history": [],
        }

        assert after_write_tests(state) == END

    def test_after_write_tests_returns_implement_when_not_discarded(self, bug_fix_config):
        state = {
            "config": bug_fix_config,
            "phase": "write_tests",
            "test_file_path": "/test.py",
            "implementation_notes": "",
            "review_attempts": 0,
            "status": None,
            "rejection_history": [],
        }

        assert after_write_tests(state) == "implement"

    def test_after_refactor_returns_review(self, bug_fix_config):
        state = {
            "config": bug_fix_config,
            "phase": "refactor",
            "test_file_path": "/test.py",
            "implementation_notes": "",
            "review_attempts": 0,
            "status": None,
            "rejection_history": [],
        }

        assert after_refactor(state) == "review"

    def test_after_review_returns_end_on_success(self, bug_fix_config):
        state = {
            "config": bug_fix_config,
            "phase": "review",
            "test_file_path": "/test.py",
            "implementation_notes": "",
            "review_attempts": 1,
            "status": "SUCCESS",
            "rejection_history": [],
        }

        assert after_review(state) == END

    def test_after_review_returns_end_on_max_attempts(self, bug_fix_config_with_max_attempts):
        state = {
            "config": bug_fix_config_with_max_attempts,
            "phase": "review",
            "test_file_path": "/test.py",
            "implementation_notes": "",
            "review_attempts": 3,
            "status": None,
            "rejection_history": ["r1", "r2", "r3"],
        }

        assert after_review(state) == END

    def test_after_review_loops_back_to_implement_on_rejection(self, bug_fix_config_with_max_attempts):
        state = {
            "config": bug_fix_config_with_max_attempts,
            "phase": "review",
            "test_file_path": "/test.py",
            "implementation_notes": "",
            "review_attempts": 1,
            "status": None,
            "rejection_history": ["rejected"],
        }

        assert after_review(state) == "implement"


class TestTDDGraph:
    def test_graph_has_expected_nodes(self):
        node_names = list(tdd_graph.nodes.keys())
        assert "write_tests" in node_names
        assert "implement" in node_names
        assert "refactor" in node_names
        assert "review" in node_names
