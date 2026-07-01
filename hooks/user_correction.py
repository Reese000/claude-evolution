#!/usr/bin/env python3
"""
User correction hook - logs when user submits a prompt (UserPromptSubmit event).
This runs when user provides a new prompt to Claude.

Data source: Claude Code writes hook input as JSON to stdin.
Env vars available: CLAUDE_CODE_SESSION_ID, CLAUDE_PROJECT_DIR, etc.
Custom env vars from settings.json: CORRECTION_TYPE, CORRECTION_CONTEXT.
"""
import sys
import json
import os
from datetime import datetime
from pathlib import Path

# Ensure hook_utils is importable regardless of working directory
sys.path.insert(0, str(Path(__file__).parent))
from hook_utils import read_hook_input, get_session_id, LOGS_DIR

LOGS_DIR = Path(LOGS_DIR)
LOGS_DIR.mkdir(exist_ok=True)


def log_correction():
    """Log the correction event."""
    log_file = LOGS_DIR / "corrections.jsonl"

    hook_input = read_hook_input()

    # UserPromptSubmit provides a "prompt" field in stdin JSON
    prompt = hook_input.get("prompt", "")

    event = {
        "timestamp": datetime.now().isoformat(),
        "session_id": get_session_id(hook_input),
        "event": "user_correction",
        "correction_type": os.environ.get("CORRECTION_TYPE", "user_prompt"),
        "context": os.environ.get("CORRECTION_CONTEXT", ""),
        "prompt_preview": prompt[:200] if prompt else "",
        "working_dir": hook_input.get("cwd", ""),
    }

    with open(log_file, "a") as f:
        f.write(json.dumps(event) + "\n")


if __name__ == "__main__":
    log_correction()
