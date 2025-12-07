from unittest.mock import Mock, patch

from code_agent.gitlab_utils import (
    create_worktree_from_origin,
    get_default_branch,
    get_mr_diff,
)


def test_get_mr_diff_returns_stdout():
    mock_result = Mock()
    mock_result.stdout = "diff content here"

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        result = get_mr_diff()

    mock_run.assert_called_once_with(
        "glab mr diff $(git branch --show-current) --raw",
        shell=True,
        capture_output=True,
        text=True,
        check=True,
        cwd=None
    )
    assert result == "diff content here"


def test_get_mr_diff_uses_cwd_parameter():
    mock_result = Mock()
    mock_result.stdout = "diff output"

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        result = get_mr_diff(cwd="/path/to/repo")

    mock_run.assert_called_once_with(
        "glab mr diff $(git branch --show-current) --raw",
        shell=True,
        capture_output=True,
        text=True,
        check=True,
        cwd="/path/to/repo"
    )
    assert result == "diff output"


def test_get_default_branch_returns_main():
    mock_result = Mock()
    mock_result.stdout = """* remote origin
  Fetch URL: git@github.com:user/repo.git
  Push  URL: git@github.com:user/repo.git
  HEAD branch: main
  Remote branches:
    main tracked
"""

    with patch("code_agent.gitlab_utils.subprocess.run", return_value=mock_result) as mock_run:
        result = get_default_branch()

    mock_run.assert_called_once_with(
        ["git", "remote", "show", "origin"],
        capture_output=True,
        text=True,
        check=True,
        cwd=None,
    )
    assert result == "main"


def test_get_default_branch_returns_master():
    mock_result = Mock()
    mock_result.stdout = """* remote origin
  Fetch URL: git@github.com:user/repo.git
  Push  URL: git@github.com:user/repo.git
  HEAD branch: master
  Remote branches:
    master tracked
"""

    with patch("code_agent.gitlab_utils.subprocess.run", return_value=mock_result) as mock_run:
        result = get_default_branch()

    assert result == "master"


def test_get_default_branch_uses_cwd_parameter():
    mock_result = Mock()
    mock_result.stdout = "  HEAD branch: main\n"

    with patch("code_agent.gitlab_utils.subprocess.run", return_value=mock_result) as mock_run:
        result = get_default_branch(cwd="/custom/path")

    mock_run.assert_called_once_with(
        ["git", "remote", "show", "origin"],
        capture_output=True,
        text=True,
        check=True,
        cwd="/custom/path",
    )
    assert result == "main"


def test_create_worktree_from_origin_fetches_and_creates_worktree():
    mock_result = Mock()
    mock_result.stdout = "  HEAD branch: main\n"

    with patch("code_agent.gitlab_utils.subprocess.run", return_value=mock_result) as mock_run:
        result = create_worktree_from_origin("/tmp/worktree")

    assert mock_run.call_count == 3
    calls = mock_run.call_args_list

    assert calls[0][0][0] == ["git", "fetch", "origin"]
    assert calls[0][1]["cwd"] is None

    assert calls[1][0][0] == ["git", "remote", "show", "origin"]

    assert calls[2][0][0] == ["git", "worktree", "add", "-b", "worktree", "/tmp/worktree", "origin/main"]
    assert calls[2][1]["cwd"] is None

    assert result == "/tmp/worktree"


def test_create_worktree_from_origin_uses_master_when_default():
    mock_result = Mock()
    mock_result.stdout = "  HEAD branch: master\n"

    with patch("code_agent.gitlab_utils.subprocess.run", return_value=mock_result) as mock_run:
        result = create_worktree_from_origin("/tmp/worktree")

    calls = mock_run.call_args_list
    assert calls[2][0][0] == ["git", "worktree", "add", "-b", "worktree", "/tmp/worktree", "origin/master"]


def test_create_worktree_from_origin_uses_cwd_parameter():
    mock_result = Mock()
    mock_result.stdout = "  HEAD branch: main\n"

    with patch("code_agent.gitlab_utils.subprocess.run", return_value=mock_result) as mock_run:
        result = create_worktree_from_origin("/tmp/worktree", cwd="/repo/path")

    calls = mock_run.call_args_list
    assert calls[0][1]["cwd"] == "/repo/path"
    assert calls[1][1]["cwd"] == "/repo/path"
    assert calls[2][1]["cwd"] == "/repo/path"
