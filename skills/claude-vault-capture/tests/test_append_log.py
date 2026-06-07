"""Unit tests for concurrent append_log() correctness — cross-process case."""

import sys
import pathlib
import json
import subprocess

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "hooks"))


_HOOKS_DIR = str(pathlib.Path(__file__).parent.parent / "hooks")

# Helper script run by subprocesses
_HELPER = f"""
import sys, json, pathlib
sys.path.insert(0, {_HOOKS_DIR!r})
# Wait briefly so both processes overlap
import time; time.sleep(0.05)
from curate import append_log
entry = json.loads(sys.argv[1])
log_path = pathlib.Path(sys.argv[2])
append_log(entry, log_path=log_path)
"""


class TestAppendLog:
    def test_concurrent_writes_no_interleaving(self, tmp_path):
        """Two subprocesses writing to the same log file must produce 2 clean lines."""
        log_file = tmp_path / "log.md"
        entry1 = {"session_id": "aaa", "data": "A" * 100}
        entry2 = {"session_id": "bbb", "data": "B" * 100}

        helper_path = tmp_path / "helper.py"
        helper_path.write_text(_HELPER)

        p1 = subprocess.Popen(
            [sys.executable, str(helper_path), json.dumps(entry1), str(log_file)]
        )
        p2 = subprocess.Popen(
            [sys.executable, str(helper_path), json.dumps(entry2), str(log_file)]
        )
        p1.wait(timeout=10)
        p2.wait(timeout=10)

        lines = [line for line in log_file.read_text().splitlines() if line.strip()]
        assert len(lines) == 2

        parsed = [json.loads(line) for line in lines]
        session_ids = {e["session_id"] for e in parsed}
        assert session_ids == {"aaa", "bbb"}

    def test_single_append_creates_file(self, tmp_path):
        from curate import append_log

        log_file = tmp_path / "new_log.md"
        assert not log_file.exists()
        append_log({"key": "value"}, log_path=log_file)
        assert log_file.exists()
        data = json.loads(log_file.read_text().strip())
        assert data["key"] == "value"

    def test_multiple_appends_each_valid_json(self, tmp_path):
        from curate import append_log

        log_file = tmp_path / "log.md"
        for i in range(5):
            append_log({"i": i}, log_path=log_file)
        lines = [line for line in log_file.read_text().splitlines() if line.strip()]
        assert len(lines) == 5
        for line in lines:
            json.loads(line)  # must not raise
