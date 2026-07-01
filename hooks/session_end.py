#!/usr/bin/env python3
"""
Session end hook - logs session summary.
This runs when Claude Code session ends.

Data source: Claude Code writes hook input as JSON to stdin.
Env vars available: CLAUDE_CODE_SESSION_ID, CLAUDE_PROJECT_DIR, etc.
"""
import sys
import json
from datetime import datetime
from pathlib import Path

# Ensure hook_utils is importable regardless of working directory
sys.path.insert(0, str(Path(__file__).parent))
from hook_utils import read_hook_input, get_session_id, LOGS_DIR

LOGS_DIR = Path(LOGS_DIR)
LOGS_DIR.mkdir(exist_ok=True)


def log_session_end():
    """Log the session end event."""
    log_file = LOGS_DIR / "sessions.jsonl"

    hook_input = read_hook_input()
    session_id = get_session_id(hook_input)

    # Count tools for this session from a running counter file
    counter_file = LOGS_DIR / f"session_{session_id}_tools.txt"
    tool_count = 0
    if counter_file.exists():
        try:
            tool_count = int(counter_file.read_text().strip())
            counter_file.unlink()  # Clean up
        except ValueError:
            pass

    event = {
        "timestamp": datetime.now().isoformat(),
        "session_id": session_id,
        "event": "session_end",
        "reason": hook_input.get("reason", ""),
        "working_dir": hook_input.get("cwd", ""),
        "tool_count": tool_count,
    }

    with open(log_file, "a") as f:
        f.write(json.dumps(event) + "\n")


if __name__ == "__main__":
    log_session_end()
