import json
import os
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Bug(BaseModel):
    id: str
    short_description: str
    severity: Literal["HIGH", "MEDIUM", "LOW"]
    status: Literal[
        "POTENTIAL",
        "IN_ANALYSIS",
        "PREPARED_FOR_FIX",
        "READY_FOR_REVIEW",
        "SOLVED",
        "DISCARDED",
    ]
    relevant_files: list[str]
    reproducibility_chance: Literal["EASY", "MEDIUM", "HARD"] | None = None
    reproducibility_approach: (
        Literal["UNIT_TEST", "MANUAL", "INTEGRATION_TEST"] | None
    ) = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class Bugs(BaseModel):
    bugs: dict[str, Bug]


class BugFix(BaseModel):
    bug_id: str
    status: Literal["IN_REVIEW", "REJECTED", "FINISHED"]
    rejection_reason: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    manual_adjustments: str | None = None


class BugFixes(BaseModel):
    fixes: dict[str, BugFix]


class BugDetailsPersistence:
    def __init__(self, path: str):
        self.path = path

    def load_bug_details(self, bug_id: str) -> str | None:
        detail_path = os.path.join(self.path, "bugs", f"{bug_id}.md")
        if os.path.exists(detail_path):
            with open(detail_path, "r") as f:
                return f.read()
        return None

    def save_bug_details(self, bug_id: str, details: str):
        detail_path = os.path.join(self.path, "bugs", f"{bug_id}.md")
        os.makedirs(os.path.dirname(detail_path), exist_ok=True)
        with open(detail_path, "w") as f:
            f.write(details)


def load_initial_state(state_path: str) -> tuple[dict[str, Bug], dict[str, BugFix], list[str]]:
    bugs: dict[str, Bug] = {}
    fixes: dict[str, BugFix] = {}
    entrypoints: list[str] = []

    bugs_path = os.path.join(state_path, "bugs.json")
    if os.path.exists(bugs_path):
        with open(bugs_path, "r") as f:
            bugs = Bugs.model_validate_json(f.read()).bugs

    fixes_path = os.path.join(state_path, "fixes.json")
    if os.path.exists(fixes_path):
        with open(fixes_path, "r") as f:
            fixes = BugFixes.model_validate_json(f.read()).fixes

    entrypoints_path = os.path.join(state_path, "entrypoints.json")
    if os.path.exists(entrypoints_path):
        with open(entrypoints_path, "r") as f:
            entrypoints = json.loads(f.read())

    return bugs, fixes, entrypoints


def persist_state(
    state_path: str,
    bugs: dict[str, Bug],
    fixes: dict[str, BugFix],
    entrypoints: list[str],
):
    os.makedirs(state_path, exist_ok=True)

    with open(os.path.join(state_path, "bugs.json"), "w") as f:
        f.write(Bugs(bugs=bugs).model_dump_json(indent=2))

    with open(os.path.join(state_path, "fixes.json"), "w") as f:
        f.write(BugFixes(fixes=fixes).model_dump_json(indent=2))

    with open(os.path.join(state_path, "entrypoints.json"), "w") as f:
        f.write(json.dumps(entrypoints, indent=2))


class BugHunterNotebook:
    def __init__(self, path: str):
        self.path = path
        self.bugs = self.load_bugs()
        self.fixes = self.load_fixes()
        self.entrypoints = self.load_entrypoints()

    def load_bugs(self):
        bugs_path = os.path.join(self.path, "bugs.json")
        if os.path.exists(bugs_path):
            with open(bugs_path, "r") as f:
                return Bugs.model_validate_json(f.read())
        return Bugs(bugs={})

    def load_fixes(self):
        fixes_path = os.path.join(self.path, "fixes.json")
        if os.path.exists(fixes_path):
            with open(fixes_path, "r") as f:
                return BugFixes.model_validate_json(f.read())
        return BugFixes(fixes={})

    def load_bug_details(self, bug_id: str) -> str | None:
        detail_path = os.path.join(self.path, "bugs", f"{bug_id}.md")
        if os.path.exists(detail_path):
            with open(detail_path, "r") as f:
                return f.read()
        return None

    def save_bug_details(self, bug_id: str, details: str):
        detail_path = os.path.join(self.path, "bugs", f"{bug_id}.md")
        os.makedirs(os.path.dirname(detail_path), exist_ok=True)
        with open(detail_path, "w") as f:
            f.write(details)

    def save_bugs(self):
        with open(os.path.join(self.path, "bugs.json"), "w") as f:
            f.write(self.bugs.model_dump_json(indent=2))

    def save_fixes(self):
        with open(os.path.join(self.path, "fixes.json"), "w") as f:
            f.write(self.fixes.model_dump_json(indent=2))

    def add_or_update_bug(self, bug_id: str, bug: Bug):
        bug.updated_at = datetime.now()
        bugs = {**self.bugs.bugs, bug_id: bug}
        self.bugs = Bugs(bugs=bugs)
        self.save_bugs()

    def add_or_update_fix(self, fix_id: str, fix: BugFix):
        fixes = {**self.fixes.fixes, fix_id: fix}
        self.fixes = BugFixes(fixes=fixes)
        self.save_fixes()

    def add_entrypoints(self, path: list[str]) -> None:
        self.entrypoints.extend(path)
        with open(os.path.join(self.path, "entrypoints.json"), "w") as f:
            f.write(json.dumps(self.entrypoints, indent=2))

    def load_entrypoints(self) -> list[str]:
        entrypoints_path = os.path.join(self.path, "entrypoints.json")
        if os.path.exists(entrypoints_path):
            with open(entrypoints_path, "r") as f:
                return json.loads(f.read())
        return []

    def pop_entrypoint(self) -> str | None:
        if not self.entrypoints:
            return None
        entrypoint = self.entrypoints.pop(0)
        with open(os.path.join(self.path, "entrypoints.json"), "w") as f:
            f.write(json.dumps(self.entrypoints, indent=2))
        return entrypoint

    def clear(self) -> None:
        self.entrypoints = []
        with open(os.path.join(self.path, "entrypoints.json"), "w") as f:
            f.write(json.dumps(self.entrypoints, indent=2))

        bug_ids_to_remove = [
            bug_id
            for bug_id, bug in self.bugs.bugs.items()
            if bug.status in ("POTENTIAL", "IN_ANALYSIS")
        ]

        for bug_id in bug_ids_to_remove:
            detail_path = os.path.join(self.path, "bugs", f"{bug_id}.md")
            if os.path.exists(detail_path):
                os.remove(detail_path)
            del self.bugs.bugs[bug_id]

        self.save_bugs()
