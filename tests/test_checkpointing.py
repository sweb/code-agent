import os
import tempfile

from code_agent.checkpointing import (
    THREAD_ID_FILE,
    clear_thread_id,
    generate_thread_id,
    get_checkpoint_db_path,
    load_thread_id,
    save_thread_id,
)


class TestGenerateThreadId:
    def test_returns_string_with_run_prefix(self):
        thread_id = generate_thread_id()
        assert thread_id.startswith("run-")

    def test_includes_timestamp_format(self):
        thread_id = generate_thread_id()
        parts = thread_id.split("-")
        assert len(parts) >= 2
        assert len(parts[1]) == 8


class TestGetCheckpointDbPath:
    def test_returns_path_with_db_filename(self):
        path = get_checkpoint_db_path("/some/state/path")
        assert path == "/some/state/path/checkpoints.db"


class TestSaveAndLoadThreadId:
    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            save_thread_id(tmpdir, "test-thread-123")
            loaded = load_thread_id(tmpdir)
            assert loaded == "test-thread-123"

    def test_save_creates_directory_if_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = os.path.join(tmpdir, "nested", "dir")
            save_thread_id(nested, "test-thread")
            assert os.path.exists(nested)
            assert load_thread_id(nested) == "test-thread"

    def test_load_returns_none_when_no_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            loaded = load_thread_id(tmpdir)
            assert loaded is None


class TestClearThreadId:
    def test_removes_thread_id_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            save_thread_id(tmpdir, "test-thread")
            clear_thread_id(tmpdir)
            path = os.path.join(tmpdir, THREAD_ID_FILE)
            assert not os.path.exists(path)

    def test_handles_missing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            clear_thread_id(tmpdir)
