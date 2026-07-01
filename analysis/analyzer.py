#!/usr/bin/env python3
"""
Analysis layer - reads JSONL logs and detects patterns.
This runs in the background, not during active work.
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter, defaultdict
from typing import Dict, List, Any

LOGS_DIR = Path("/home/reese/claude-evolution/logs")
DATA_DIR = Path("/home/reese/claude-evolution/data")

class PatternDetector:
    """Detects patterns in execution logs."""

    def __init__(self):
        self.tool_uses = []
        self.sessions = []
        self.corrections = []

    def load_logs(self, days: int = 7):
        """Load logs from the last N days."""
        cutoff = datetime.now() - timedelta(days=days)

        # Load tool uses
        tool_log = LOGS_DIR / "tool_uses.jsonl"
        if tool_log.exists():
            with open(tool_log) as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        ts = datetime.fromisoformat(entry["timestamp"])
                        if ts > cutoff:
                            self.tool_uses.append(entry)
                    except (json.JSONDecodeError, KeyError):
                        continue

        # Load sessions
        session_log = LOGS_DIR / "sessions.jsonl"
        if session_log.exists():
            with open(session_log) as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        ts = datetime.fromisoformat(entry["timestamp"])
                        if ts > cutoff:
                            self.sessions.append(entry)
                    except (json.JSONDecodeError, KeyError):
                        continue

        # Load corrections
        correction_log = LOGS_DIR / "corrections.jsonl"
        if correction_log.exists():
            with open(correction_log) as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        ts = datetime.fromisoformat(entry["timestamp"])
                        if ts > cutoff:
                            self.corrections.append(entry)
                    except (json.JSONDecodeError, KeyError):
                        continue

    def detect_patterns(self) -> Dict[str, Any]:
        """Detect patterns in the loaded data."""
        patterns = {
            "repeated_tools": self._detect_repeated_tools(),
            "correction_patterns": self._detect_correction_patterns(),
            "session_complexity": self._analyze_session_complexity(),
            "tool_success_rates": self._calculate_tool_success_rates(),
            "temporal_patterns": self._detect_temporal_patterns()
        }
        return patterns

    def _detect_repeated_tools(self) -> List[Dict]:
        """Detect tools that are called repeatedly in short succession."""
        repeated = []
        tool_calls = defaultdict(list)

        for use in self.tool_uses:
            tool_calls[use["tool"]].append(datetime.fromisoformat(use["timestamp"]))

        for tool, timestamps in tool_calls.items():
            timestamps.sort()
            for i in range(1, len(timestamps)):
                diff = (timestamps[i] - timestamps[i-1]).total_seconds()
                if diff < 30:  # Called within 30 seconds
                    repeated.append({
                        "tool": tool,
                        "interval_seconds": diff,
                        "count": len(timestamps)
                    })

        return repeated

    def _detect_correction_patterns(self) -> List[Dict]:
        """Detect patterns in user corrections."""
        if not self.corrections:
            return []

        patterns = []
        correction_types = Counter(c.get("correction_type", "unknown") for c in self.corrections)

        for ctype, count in correction_types.items():
            if count >= 2:  # Pattern = 2+ corrections of same type
                patterns.append({
                    "type": ctype,
                    "count": count,
                    "examples": [c.get("context", "") for c in self.corrections if c.get("correction_type") == ctype][:3]
                })

        return patterns

    def _analyze_session_complexity(self) -> Dict:
        """Analyze session complexity metrics."""
        if not self.sessions:
            return {}

        durations = [s.get("duration_seconds", 0) for s in self.sessions]
        tool_counts = [s.get("tool_count", 0) for s in self.sessions]

        return {
            "avg_duration_seconds": sum(durations) / len(durations) if durations else 0,
            "avg_tool_count": sum(tool_counts) / len(tool_counts) if tool_counts else 0,
            "max_duration_seconds": max(durations) if durations else 0,
            "session_count": len(self.sessions)
        }

    def _calculate_tool_success_rates(self) -> Dict[str, float]:
        """Calculate success rates for each tool."""
        tool_success = defaultdict(lambda: {"success": 0, "total": 0})

        for use in self.tool_uses:
            tool = use["tool"]
            tool_success[tool]["total"] += 1
            if use.get("success", True):
                tool_success[tool]["success"] += 1

        rates = {}
        for tool, counts in tool_success.items():
            rates[tool] = counts["success"] / counts["total"] if counts["total"] > 0 else 1.0

        return rates

    def _detect_temporal_patterns(self) -> Dict:
        """Detect patterns based on time of day, day of week, etc."""
        if not self.tool_uses:
            return {}

        hour_counts = Counter()
        for use in self.tool_uses:
            ts = datetime.fromisoformat(use["timestamp"])
            hour_counts[ts.hour] += 1

        peak_hours = hour_counts.most_common(3)
        return {
            "peak_hours": [h for h, _ in peak_hours],
            "total_tool_uses": len(self.tool_uses)
        }

    def generate_report(self) -> Dict:
        """Generate a comprehensive analysis report."""
        patterns = self.detect_patterns()

        report = {
            "generated_at": datetime.now().isoformat(),
            "data_range_days": 7,
            "summary": {
                "total_tool_uses": len(self.tool_uses),
                "total_sessions": len(self.sessions),
                "total_corrections": len(self.corrections)
            },
            "patterns": patterns,
            "recommendations": self._generate_recommendations(patterns)
        }

        return report

    def _generate_recommendations(self, patterns: Dict) -> List[Dict]:
        """Generate actionable recommendations based on patterns."""
        recommendations = []

        # Check for repeated tools
        if patterns.get("repeated_tools"):
            recommendations.append({
                "severity": "P1",
                "category": "efficiency",
                "issue": "Repeated tool calls detected",
                "details": patterns["repeated_tools"][:3],
                "suggestion": "Consider batching tool calls or using more efficient approaches"
            })

        # Check for correction patterns
        if patterns.get("correction_patterns"):
            for pattern in patterns["correction_patterns"]:
                recommendations.append({
                    "severity": "P0",
                    "category": "accuracy",
                    "issue": f"Repeated corrections: {pattern['type']}",
                    "details": pattern["examples"],
                    "suggestion": f"Update CLAUDE.md to prevent {pattern['type']} errors"
                })

        # Check session complexity
        complexity = patterns.get("session_complexity", {})
        if complexity.get("avg_duration_seconds", 0) > 3600:  # > 1 hour avg
            recommendations.append({
                "severity": "P1",
                "category": "efficiency",
                "issue": "Long average session duration",
                "details": {"avg_minutes": complexity["avg_duration_seconds"] / 60},
                "suggestion": "Consider breaking down tasks or improving task decomposition"
            })

        # Check tool success rates
        success_rates = patterns.get("tool_success_rates", {})
        low_success_tools = [tool for tool, rate in success_rates.items() if rate < 0.8]
        if low_success_tools:
            recommendations.append({
                "severity": "P1",
                "category": "reliability",
                "issue": "Low success rates for tools",
                "details": {tool: success_rates[tool] for tool in low_success_tools},
                "suggestion": "Investigate why these tools are failing and fix the root cause"
            })

        return recommendations

def main():
    """Main analysis function."""
    detector = PatternDetector()
    detector.load_logs(days=7)
    report = detector.generate_report()

    # Save report
    report_file = DATA_DIR / "analysis_report.json"
    DATA_DIR.mkdir(exist_ok=True)
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Analysis complete. Report saved to {report_file}")
    print(f"Found {len(report['recommendations'])} recommendations")

    # Print summary
    for rec in report["recommendations"]:
        print(f"  [{rec['severity']}] {rec['issue']}")

    return report

if __name__ == "__main__":
    main()
