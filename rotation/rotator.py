#!/usr/bin/env python3
"""
Log rotation - cleans up old logs and backups to prevent unbounded growth.
"""
import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

DATA_DIR = Path("/home/reese/claude-evolution/data")
LOGS_DIR = Path("/home/reese/claude-evolution/logs")


class LogRotator:
    """Manages log rotation and cleanup."""

    def __init__(self, config: Dict):
        rotation = config.get("rotation", {})
        self.enabled = rotation.get("enabled", True)
        self.max_log_age_days = rotation.get("max_log_age_days", 30)
        self.max_backups = rotation.get("max_backups", 10)

    def rotate(self) -> Dict:
        """Perform log rotation. Returns summary of what was cleaned."""
        if not self.enabled:
            return {"status": "disabled"}

        removed_logs = []
        removed_backups = []

        # Clean old logs
        if LOGS_DIR.exists():
            cutoff = datetime.now() - timedelta(days=self.max_log_age_days)
            for log_file in LOGS_DIR.glob("*.jsonl"):
                if log_file.stat().st_mtime < cutoff.timestamp():
                    log_file.unlink()
                    removed_logs.append(log_file.name)

        # Clean old backups (keep most recent N)
        backup_dir = DATA_DIR / "backups"
        if backup_dir.exists():
            backups = sorted(
                backup_dir.glob("backup_*.json"),
                key=lambda f: f.stat().st_mtime,
                reverse=True
            )
            for old_backup in backups[self.max_backups:]:
                old_backup.unlink()
                removed_backups.append(old_backup.name)

        return {
            "status": "completed",
            "removed_logs": removed_logs,
            "removed_backups": removed_backups,
            "timestamp": datetime.now().isoformat()
        }


def main():
    """Test rotation."""
    import yaml
    config_file = Path("/home/reese/claude-evolution/config/settings.yaml")
    with open(config_file) as f:
        config = yaml.safe_load(f)

    rotator = LogRotator(config)
    result = rotator.rotate()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
