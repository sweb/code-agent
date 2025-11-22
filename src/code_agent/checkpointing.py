import os
from datetime import datetime

THREAD_ID_FILE = "current_thread.txt"
CHECKPOINT_DB = "checkpoints.db"


def get_checkpoint_db_path(state_path: str) -> str:
    return os.path.join(state_path, CHECKPOINT_DB)


def generate_thread_id() -> str:
    return f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def save_thread_id(state_path: str, thread_id: str) -> None:
    os.makedirs(state_path, exist_ok=True)
    path = os.path.join(state_path, THREAD_ID_FILE)
    with open(path, "w") as f:
        f.write(thread_id)


def load_thread_id(state_path: str) -> str | None:
    path = os.path.join(state_path, THREAD_ID_FILE)
    if os.path.exists(path):
        with open(path, "r") as f:
            return f.read().strip()
    return None


def clear_thread_id(state_path: str) -> None:
    path = os.path.join(state_path, THREAD_ID_FILE)
    if os.path.exists(path):
        os.remove(path)


async def check_for_incomplete_run(
    checkpointer, state_path: str
) -> tuple[bool, str | None]:
    thread_id = load_thread_id(state_path)
    if not thread_id:
        return False, None

    config = {"configurable": {"thread_id": thread_id}}
    state = await checkpointer.aget(config)
    if state is not None:
        return True, thread_id
    return False, None


def prompt_resume() -> bool:
    while True:
        response = input("Incomplete run detected. Resume? [y/n]: ").strip().lower()
        if response in ("y", "yes"):
            return True
        if response in ("n", "no"):
            return False
        print("Please enter 'y' or 'n'.")
