#!/usr/bin/env python3
"""
Tool counter - tracks tool calls per session for session_end.py.
Runs on every tool use to maintain a running count.
Uses atomic rename to prevent race conditions between concurrent hooks.

Data source: Claude Code writes hook input as JSON to stdin.
"""
import sys
import os
import tempfile
from pathlib import Path

# Ensure hook_utils is importable regardless of working directory
sys.path.insert(0, str(Path(__file__).parent))
from hook_utils import read_hook_input, get_session_id, LOGS_DIR

LOGS_DIR = Path(LOGS_DIR)


def increment_counter():
    hook_input = read_hook_input()
    session_id = get_session_id(hook_input)
    counter_file = LOGS_DIR / f"session_{session_id}_tools.txt"
    lock_file = LOGS_DIR / f"session_{session_id}_tools.lock"

    # Use a lock file to serialize concurrent increments
    # open() with 'x' mode is atomic: raises FileExistsError if already locked
    lock_fd = None
    try:
        while True:
            try:
                lock_fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                # Another process holds the lock; retry briefly
                import time
                time.sleep(0.01)

        # Read current count
        count = 0
        if counter_file.exists():
            try:
                count = int(counter_file.read_text().strip())
            except (ValueError, OSError):
                pass

        # Write new count atomically via temp file + rename
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(counter_file.parent), suffix=".tmp"
        )
        try:
            os.write(tmp_fd, str(count + 1).encode())
            os.fsync(tmp_fd)
            os.close(tmp_fd)
            os.replace(tmp_path, str(counter_file))
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    finally:
        # Release lock
        if lock_fd is not None:
            os.close(lock_fd)
        try:
            os.unlink(str(lock_file))
        except OSError:
            pass

if __name__ == "__main__":
    increment_counter()
