#!/usr/bin/env python3
"""
Event-driven trigger system for Claude Evolution.
Activates based on session metrics, not just time.
"""
import json
import os
import sys
import yaml
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional

LOGS_DIR = Path("/home/reese/claude-evolution/logs")
DATA_DIR = Path("/home/reese/claude-evolution/data")
CONFIG_DIR = Path("/home/reese/claude-evolution/config")

class TriggerEvaluator:
    """Evaluates whether evolution should run based on multiple criteria."""

    def __init__(self):
        self.config = self._load_config()
        self.triggers = self._load_triggers()

    def _load_config(self) -> Dict:
        config_file = CONFIG_DIR / "settings.yaml"
        with open(config_file) as f:
            return yaml.safe_load(f)

    def _load_triggers(self) -> List[Dict]:
        trigger_file = CONFIG_DIR / "triggers.yaml"
        if trigger_file.exists():
            with open(trigger_file) as f:
                return yaml.safe_load(f).get("triggers", [])
        return self._default_triggers()

    def _default_triggers(self) -> List[Dict]:
        return [
            {"name": "correction_burst", "type": "count", "metric": "corrections_per_session", "threshold": 3, "cooldown_hours": 6},
            {"name": "repeated_pattern", "type": "ratio", "metric": "repeated_tool_ratio", "threshold": 0.3, "cooldown_hours": 12},
            {"name": "session_complexity", "type": "threshold", "metric": "avg_turns_per_task", "threshold": 15, "cooldown_hours": 24},
            {"name": "error_spike", "type": "count", "metric": "errors_per_session", "threshold": 5, "cooldown_hours": 4},
            {"name": "time_based", "type": "timer", "interval_hours": 24, "cooldown_hours": 20},
            {"name": "data_accumulation", "type": "size", "metric": "log_size_mb", "threshold": 5.0, "cooldown_hours": 48},
            {"name": "new_memory_files", "type": "count", "metric": "memory_files_added", "threshold": 2, "cooldown_hours": 12},
        ]

    def evaluate_all(self) -> Dict[str, Any]:
        """Evaluate all triggers and return decision."""
        metrics = self._collect_metrics()
        triggered = []

        for trigger in self.triggers:
            result = self._evaluate_trigger(trigger, metrics)
            if result["triggered"]:
                triggered.append(result)

        should_run = len(triggered) > 0
        reason = self._select_primary_reason(triggered) if triggered else "no_trigger"

        return {
            "should_run": should_run,
            "reason": reason,
            "triggered_rules": triggered,
            "metrics": metrics,
            "timestamp": datetime.now().isoformat()
        }

    def _collect_metrics(self) -> Dict[str, Any]:
        """Collect current metrics from logs."""
        metrics = {}

        # Correction count (last 24h)
        metrics["corrections_per_session"] = self._count_recent("corrections.jsonl", hours=24)
        metrics["total_corrections"] = self._count_recent("corrections.jsonl", hours=168)

        # Tool usage patterns
        tool_uses = self._load_recent("tool_uses.jsonl", hours=24)
        metrics["total_tool_uses_24h"] = len(tool_uses)
        metrics["repeated_tool_ratio"] = self._calc_repeated_ratio(tool_uses)

        # Session metrics
        sessions = self._load_recent("sessions.jsonl", hours=168)
        metrics["sessions_7d"] = len(sessions)
        metrics["avg_turns_per_task"] = self._avg_tool_count(sessions)
        metrics["avg_session_duration"] = self._avg_duration(sessions)

        # Error count (inferred from tool failures)
        metrics["errors_per_session"] = self._count_failures(tool_uses, sessions)

        # Log size
        metrics["log_size_mb"] = self._log_size_mb()

        # Memory file changes
        metrics["memory_files_added"] = self._detect_memory_changes()

        # Last evolution time
        metrics["hours_since_last_evolution"] = self._hours_since_last_evolution()

        return metrics

    def _count_recent(self, filename: str, hours: int) -> int:
        filepath = LOGS_DIR / filename
        if not filepath.exists():
            return 0
        cutoff = datetime.now() - timedelta(hours=hours)
        count = 0
        with open(filepath) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    ts = datetime.fromisoformat(entry["timestamp"])
                    if ts > cutoff:
                        count += 1
                except (json.JSONDecodeError, KeyError):
                    continue
        return count

    def _load_recent(self, filename: str, hours: int) -> List[Dict]:
        filepath = LOGS_DIR / filename
        if not filepath.exists():
            return []
        cutoff = datetime.now() - timedelta(hours=hours)
        entries = []
        with open(filepath) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    ts = datetime.fromisoformat(entry["timestamp"])
                    if ts > cutoff:
                        entries.append(entry)
                except (json.JSONDecodeError, KeyError):
                    continue
        return entries

    def _calc_repeated_ratio(self, tool_uses: List[Dict]) -> float:
        if len(tool_uses) < 2:
            return 0.0
        timestamps = sorted([datetime.fromisoformat(u["timestamp"]) for u in tool_uses])
        rapid_calls = sum(1 for i in range(1, len(timestamps))
                         if (timestamps[i] - timestamps[i-1]).total_seconds() < 5)
        return rapid_calls / len(timestamps) if tool_uses else 0.0

    def _avg_tool_count(self, sessions: List[Dict]) -> float:
        counts = [s.get("tool_count", 0) for s in sessions]
        return sum(counts) / len(counts) if counts else 0.0

    def _avg_duration(self, sessions: List[Dict]) -> float:
        durations = [s.get("duration_seconds", 0) for s in sessions]
        return sum(durations) / len(durations) if durations else 0.0

    def _count_failures(self, tool_uses: List[Dict], sessions: List[Dict]) -> float:
        failures = sum(1 for u in tool_uses if not u.get("success", True))
        return failures / len(sessions) if sessions else 0.0

    def _log_size_mb(self) -> float:
        total = 0
        for f in LOGS_DIR.glob("*.jsonl"):
            total += f.stat().st_size
        return total / (1024 * 1024)

    def _detect_memory_changes(self) -> int:
        memory_dir = Path(self.config["paths"]["memory_dir"])
        if not memory_dir.exists():
            return 0
        cutoff = datetime.now() - timedelta(hours=24)
        count = 0
        for f in memory_dir.glob("*.md"):
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime > cutoff:
                count += 1
        return count

    def _hours_since_last_evolution(self) -> float:
        evolution_log = DATA_DIR / "evolution_log.jsonl"
        if not evolution_log.exists():
            return 999
        last_ts = None
        with open(evolution_log) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    last_ts = datetime.fromisoformat(entry["timestamp"])
                except (json.JSONDecodeError, KeyError):
                    continue
        if last_ts:
            return (datetime.now() - last_ts).total_seconds() / 3600
        return 999

    def _evaluate_trigger(self, trigger: Dict, metrics: Dict) -> Dict:
        """Evaluate a single trigger against metrics."""
        name = trigger["name"]
        ttype = trigger["type"]
        cooldown = trigger.get("cooldown_hours", 24)

        # Check cooldown
        last_triggered = DATA_DIR / f"trigger_{name}_last.json"
        if last_triggered.exists():
            with open(last_triggered) as f:
                last_data = json.load(f)
            last_time = datetime.fromisoformat(last_data["timestamp"])
            if (datetime.now() - last_time).total_seconds() / 3600 < cooldown:
                return {"name": name, "triggered": False, "reason": "cooldown_active"}

        if ttype == "timer":
            interval = trigger.get("interval_hours", 24)
            hours = metrics.get("hours_since_last_evolution", 999)
            triggered = hours >= interval
            return {"name": name, "triggered": triggered, "reason": f"timer: {hours:.1f}h since last", "value": hours}

        elif ttype == "count":
            metric = metrics.get(trigger["metric"], 0)
            threshold = trigger["threshold"]
            triggered = metric >= threshold
            return {"name": name, "triggered": triggered, "reason": f"{trigger['metric']}: {metric} >= {threshold}", "value": metric}

        elif ttype == "ratio":
            metric = metrics.get(trigger["metric"], 0)
            threshold = trigger["threshold"]
            triggered = metric >= threshold
            return {"name": name, "triggered": triggered, "reason": f"{trigger['metric']}: {metric:.2f} >= {threshold}", "value": metric}

        elif ttype == "threshold":
            metric = metrics.get(trigger["metric"], 0)
            threshold = trigger["threshold"]
            triggered = metric >= threshold
            return {"name": name, "triggered": triggered, "reason": f"{trigger['metric']}: {metric:.1f} >= {threshold}", "value": metric}

        elif ttype == "size":
            metric = metrics.get(trigger["metric"], 0)
            threshold = trigger["threshold"]
            triggered = metric >= threshold
            return {"name": name, "triggered": triggered, "reason": f"{trigger['metric']}: {metric:.2f}MB >= {threshold}MB", "value": metric}

        return {"name": name, "triggered": False, "reason": "unknown_type"}

    def _select_primary_reason(self, triggered: List[Dict]) -> str:
        """Select the most important trigger reason."""
        priority = ["error_spike", "correction_burst", "repeated_pattern", "session_complexity", "data_accumulation", "new_memory_files", "time_based"]
        for p in priority:
            for t in triggered:
                if t["name"] == p:
                    return t["reason"]
        return triggered[0]["reason"] if triggered else "unknown"

    def record_trigger(self, trigger_name: str):
        """Record that a trigger fired."""
        DATA_DIR.mkdir(exist_ok=True)
        record_file = DATA_DIR / f"trigger_{trigger_name}_last.json"
        with open(record_file, "w") as f:
            json.dump({"timestamp": datetime.now().isoformat(), "trigger": trigger_name}, f)

def main():
    """Evaluate triggers and optionally run evolution."""
    evaluator = TriggerEvaluator()
    result = evaluator.evaluate_all()

    print(json.dumps(result, indent=2))

    if result["should_run"]:
        print(f"\n>>> TRIGGER FIRED: {result['reason']}")
        print(f">>> Running evolution cycle...")

        # Run the evolution cycle BEFORE recording cooldowns
        proc = subprocess.run(
            [sys.executable, "/home/reese/claude-evolution/orchestrate.py"],
            cwd="/home/reese/claude-evolution"
        )

        if proc.returncode == 0:
            print(">>> Evolution succeeded. Recording trigger cooldowns.")
            for trigger in result["triggered_rules"]:
                evaluator.record_trigger(trigger["name"])
        else:
            print(f">>> Evolution FAILED (exit code {proc.returncode}). "
                  "Cooldowns NOT recorded — triggers can retry.")
    else:
        print(f"\n>>> No triggers fired. Next evaluation based on shortest cooldown.")

if __name__ == "__main__":
    main()
