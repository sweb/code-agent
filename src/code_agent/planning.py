import json
import os
from typing import Literal

from pydantic import BaseModel


class Task(BaseModel):
    id: str
    title: str
    description: str
    status: Literal["idea", "planned", "completed"]
    task_file: str | None = None


class Tasks(BaseModel):
    ideas: list[Task]


def load_tasks(path: str) -> Tasks:
    if os.path.exists(path):
        with open(path, "r") as f:
            return Tasks.model_validate_json(f.read())
    return Tasks(ideas=[])


def save_tasks(path: str, tasks: Tasks):
    with open(path, "w") as f:
        f.write(tasks.model_dump_json(indent=2))
