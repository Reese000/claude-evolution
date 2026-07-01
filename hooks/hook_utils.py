"""
Shared utilities for Claude Code hooks.

Claude Code passes hook data via:
  1. stdin as a JSON object (primary source for tool_name, tool_input, session_id, etc.)
  2. Environment variables (limited: CLAUDE_CODE_SESSION_ID, CLAUDE_PROJECT_DIR, CLAUDECODE, etc.)

There are NO env vars for tool names or tool inputs -- those only exist in stdin JSON.
The session_id is available in BOTH stdin JSON and CLAUDE_CODE_SESSION_ID env var.
"""
import json
import os
import sys

LOGS_DIR = "/home/reese/claude-evolution/logs"


def read_hook_input() -> dict:
    """
    Read the JSON input that Claude Code writes to stdin for hooks.

    Claude Code always writes a JSON object followed by a newline to the hook's stdin.
    Returns the parsed dict, or an empty dict if stdin is empty or unparseable.
    """
    try:
        raw = sys.stdin.read().strip()
        if raw:
            return json.loads(raw)
    except (json.JSONDecodeError, IOError):
        pass
    return {}


def get_session_id(hook_input: dict = None) -> str:
    """
    Get session ID with multiple fallback strategies:
    1. From stdin JSON (hook_input["session_id"])
    2. From CLAUDE_CODE_SESSION_ID env var
    3. "unknown" as last resort
    """
    if hook_input and "session_id" in hook_input:
        return hook_input["session_id"]
    return os.environ.get("CLAUDE_CODE_SESSION_ID", "unknown")


def get_tool_name(hook_input: dict = None) -> str:
    """
    Get tool name from stdin JSON. There is no env var for this.

    Falls back to "unknown" if not available.
    """
    if hook_input and "tool_name" in hook_input:
        return hook_input["tool_name"]
    return "unknown"
