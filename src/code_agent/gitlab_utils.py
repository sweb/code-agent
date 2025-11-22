import os
import re
import subprocess


def get_default_branch(cwd: str | None = None) -> str:
    result = subprocess.run(
        ["git", "remote", "show", "origin"],
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
    )
    match = re.search(r"HEAD branch:\s*(\S+)", result.stdout)
    if not match:
        raise ValueError("Could not determine default branch from origin")
    return match.group(1)


def create_worktree_from_origin(worktree_path: str, cwd: str | None = None) -> str:
    subprocess.run(
        ["git", "fetch", "origin"],
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
    )
    branch = get_default_branch(cwd=cwd)
    new_branch = os.path.basename(worktree_path)
    subprocess.run(
        ["git", "worktree", "add", "-b", new_branch, worktree_path, f"origin/{branch}"],
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
    )
    return worktree_path


def get_mr_diff(cwd: str | None = None) -> str:
    result = subprocess.run(
        "glab mr diff $(git branch --show-current) --raw",
        shell=True,
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd
    )
    return result.stdout
