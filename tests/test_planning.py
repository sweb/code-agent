import os
import tempfile
from code_agent.planning import Task, Tasks, load_tasks, save_tasks

def test_load_save_tasks():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    # close it so we can remove/write

    try:
        # Ensure it's gone for first test
        os.remove(path)

        # Test loading non-existent
        tasks = load_tasks(path)
        assert len(tasks.ideas) == 0

        # Test save
        t1 = Task(id="1", title="T1", description="D1", status="idea")
        tasks = Tasks(ideas=[t1])
        save_tasks(path, tasks)

        assert os.path.exists(path)

        # Test reload
        loaded = load_tasks(path)
        assert len(loaded.ideas) == 1
        assert loaded.ideas[0].title == "T1"
        assert loaded.ideas[0].status == "idea"

    finally:
        if os.path.exists(path):
            os.remove(path)
