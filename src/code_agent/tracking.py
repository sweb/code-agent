import json
import os
from datetime import datetime
from typing import Literal, TypeVar

from pydantic import BaseModel, Field


T = TypeVar("T", bound=BaseModel)


BUGS_FILENAME = "bugs.json"
FIXES_FILENAME = "fixes.json"
ENTRYPOINTS_FILENAME = "entrypoints.json"
BUGS_DIRNAME = "bugs"


def load_json_model(path: str, model_cls: type[T], default: T) -> T:
    if os.path.exists(path):
        with open(path, "r") as f:
            return model_cls.model_validate_json(f.read())
    return default


def save_json_model(path: str, model: BaseModel) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(model.model_dump_json(indent=2))


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


class Entrypoints(BaseModel):
    entrypoints: list[str]


class BugHunterNotebook:
    def __init__(self, path: str):
        self.path = path
        self.bugs = self.load_bugs()
        self.fixes = self.load_fixes()
        self.entrypoints = self.load_entrypoints()

    def load_bugs(self) -> Bugs:
        return load_json_model(
            os.path.join(self.path, BUGS_FILENAME), Bugs, Bugs(bugs={})
        )

    def load_fixes(self) -> BugFixes:
        return load_json_model(
            os.path.join(self.path, FIXES_FILENAME), BugFixes, BugFixes(fixes={})
        )

    def load_bug_details(self, bug_id: str) -> str | None:
        detail_path = os.path.join(self.path, BUGS_DIRNAME, f"{bug_id}.md")
        if os.path.exists(detail_path):
            with open(detail_path, "r") as f:
                return f.read()
        return None

    def save_bug_details(self, bug_id: str, details: str):
        detail_path = os.path.join(self.path, BUGS_DIRNAME, f"{bug_id}.md")
        os.makedirs(os.path.dirname(detail_path), exist_ok=True)
        with open(detail_path, "w") as f:
            f.write(details)

    def save_bugs(self):
        save_json_model(os.path.join(self.path, BUGS_FILENAME), self.bugs)

    def save_fixes(self):
        save_json_model(os.path.join(self.path, FIXES_FILENAME), self.fixes)

    def save_entrypoints(self):
        save_json_model(
            os.path.join(self.path, ENTRYPOINTS_FILENAME),
            Entrypoints(entrypoints=self.entrypoints),
        )

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
        self.save_entrypoints()

    def load_entrypoints(self) -> list[str]:
        return load_json_model(
            os.path.join(self.path, ENTRYPOINTS_FILENAME),
            Entrypoints,
            Entrypoints(entrypoints=[]),
        ).entrypoints

    def pop_entrypoint(self) -> str | None:
        if not self.entrypoints:
            return None
        entrypoint = self.entrypoints.pop(0)
        self.save_entrypoints()
        return entrypoint

    def clear(self) -> None:
        self.entrypoints = []
        self.save_entrypoints()

        bug_ids_to_remove = [
            bug_id
            for bug_id, bug in self.bugs.bugs.items()
            if bug.status in ("POTENTIAL", "IN_ANALYSIS")
        ]

        for bug_id in bug_ids_to_remove:
            detail_path = os.path.join(self.path, BUGS_DIRNAME, f"{bug_id}.md")
            if os.path.exists(detail_path):
                os.remove(detail_path)
            del self.bugs.bugs[bug_id]

        self.save_bugs()
