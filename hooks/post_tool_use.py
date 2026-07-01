#!/usr/bin/env python3
"""
PostToolUse hook - logs tool calls during real work.
This runs passively on every tool use.

Data source: Claude Code writes hook input as JSON to stdin.
Env vars available: CLAUDE_CODE_SESSION_ID, CLAUDE_PROJECT_DIR, etc.
"""
import sys
import json
import re
from datetime import datetime
from pathlib import Path

# Ensure hook_utils is importable regardless of working directory
sys.path.insert(0, str(Path(__file__).parent))
from hook_utils import read_hook_input, get_session_id, get_tool_name, LOGS_DIR

LOGS_DIR = Path(LOGS_DIR)
LOGS_DIR.mkdir(exist_ok=True)


def sanitize_tool_input(raw) -> str:
    """Redact potential secrets and truncate."""
    if not raw:
        return ""
    if not isinstance(raw, str):
        raw = json.dumps(raw)
    # Redact common secret patterns
    redacted = re.sub(
        r'(api[_-]?key|token|secret|password|authorization)[\s:=]+\S+',
        r'\1=[REDACTED]',
        raw,
        flags=re.IGNORECASE
    )
    # Truncate to prevent unbounded log growth
    if len(redacted) > 1000:
        redacted = redacted[:1000] + "...[truncated]"
    return redacted


def log_tool_use():
    """Log the tool use event to JSONL."""
    log_file = LOGS_DIR / "tool_uses.jsonl"

    hook_input = read_hook_input()

    event = {
        "timestamp": datetime.now().isoformat(),
        "tool": get_tool_name(hook_input),
        "tool_input": sanitize_tool_input(hook_input.get("tool_input", "")),
        "tool_use_id": hook_input.get("tool_use_id", "unknown"),
        "session_id": get_session_id(hook_input),
        "duration_ms": hook_input.get("duration_ms"),
        "success": True,  # Hook runs after successful use (PostToolUseFailure handles failures)
        "working_dir": hook_input.get("cwd", ""),
    }

    with open(log_file, "a") as f:
        f.write(json.dumps(event) + "\n")


if __name__ == "__main__":
    log_tool_use()
