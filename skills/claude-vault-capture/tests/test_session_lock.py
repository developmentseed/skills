"""Two SessionEnds for one session id: the second worker waits for the first."""

import fcntl
import pathlib
import threading
import time
import zlib

from conftest import read_log

ADR = (
    pathlib.Path(__file__).parent.parent
    / "eval"
    / "fixtures"
    / "transcripts"
    / "adr-worthy.jsonl"
)


def test_second_worker_waits_then_sees_the_first(
    run_main, mock_from_responses, temp_vault
):
    mock_from_responses("adr-worthy")
    sid = "10c4ed0011223344"
    locks = temp_vault.index_path.parent / "locks"
    locks.mkdir()
    bucket = locks / f"{zlib.crc32(sid.encode()) % 64:02d}.lock"

    with open(bucket, "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        worker = threading.Thread(target=run_main, args=(ADR, sid, "/tmp"), daemon=True)
        worker.start()
        time.sleep(0.3)
        assert read_log(temp_vault.log_path) == [], "worker ran without the lock"
    # Closing the file released the lock.
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert read_log(temp_vault.log_path)[-1]["skip_reason_a"] is None

    entries = run_main(ADR, sid, "/tmp")
    assert entries[-1]["skip_reason_a"] == "duplicate"
