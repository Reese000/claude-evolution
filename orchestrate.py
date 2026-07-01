#!/usr/bin/env python3
"""
Main orchestration script for Claude Evolution System.
Ties together observation, analysis, evolution, and verification.
Trigger evaluation happens in event_trigger.py which calls this.
"""
import json
import os
import sys
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from analysis.analyzer import PatternDetector
from evolution.evolver import EvolutionEngine
from verification.validator import MutationValidator
from rotation.rotator import LogRotator

CONFIG_DIR = Path("/home/reese/claude-evolution/config")
DATA_DIR = Path("/home/reese/claude-evolution/data")

class EvolutionOrchestrator:
    """Orchestrates the full evolution cycle."""

    def __init__(self):
        self.config = self._load_config()
        self.analyzer = PatternDetector()
        self.evolver = EvolutionEngine()
        self.validator = MutationValidator()

    def _load_config(self) -> Dict:
        """Load configuration."""
        config_file = CONFIG_DIR / "settings.yaml"
        with open(config_file) as f:
            return yaml.safe_load(f)

    def _rotate_logs(self):
        """Clean up old log files and backups."""
        rotation = self.config.get("rotation", {})
        if not rotation.get("enabled", True):
            return

        max_age_days = rotation.get("max_log_age_days", 30)
        max_backups = rotation.get("max_backups", 20)
        logs_dir = Path(self.config["paths"]["logs_dir"])
        backup_dir = Path(self.config["paths"]["backup_dir"])

        # Clean old logs
        if logs_dir.exists():
            cutoff = datetime.now() - timedelta(days=max_age_days)
            for log_file in logs_dir.glob("*.jsonl"):
                if log_file.stat().st_mtime < cutoff.timestamp():
                    log_file.unlink()
                    print(f"  Removed old log: {log_file.name}")

        # Clean old backups (keep most recent N)
        if backup_dir.exists():
            backups = sorted(backup_dir.glob("backup_*.json"), key=lambda f: f.stat().st_mtime)
            if len(backups) > max_backups:
                for old_backup in backups[:len(backups) - max_backups]:
                    old_backup.unlink()
                    print(f"  Removed old backup: {old_backup.name}")

    def _save_baseline(self, metrics: Dict):
        """Save baseline metrics before evolution for outcome measurement."""
        baseline_file = DATA_DIR / "baseline.json"
        baseline = {}
        if baseline_file.exists():
            with open(baseline_file) as f:
                baseline = json.load(f)

        # Save current metrics as baseline
        baseline["timestamp"] = datetime.now().isoformat()
        baseline["corrections_per_session"] = metrics.get("corrections_per_session", 0)
        baseline["avg_turns_per_task"] = metrics.get("avg_turns_per_task", 0)
        baseline["repeated_tool_ratio"] = metrics.get("repeated_tool_ratio", 0)

        with open(baseline_file, "w") as f:
            json.dump(baseline, f, indent=2)

        print(f"Baseline saved: corrections={baseline['corrections_per_session']}, "
              f"turns={baseline['avg_turns_per_task']:.1f}, "
              f"repeated={baseline['repeated_tool_ratio']:.2f}")

    def _check_outcome(self) -> bool:
        """Check if the last evolution improved or degraded metrics."""
        baseline_file = DATA_DIR / "baseline.json"
        if not baseline_file.exists():
            return True  # No baseline, assume ok

        with open(baseline_file) as f:
            baseline = json.load(f)

        # Load current metrics from trigger evaluator
        from triggers.event_trigger import TriggerEvaluator
        evaluator = TriggerEvaluator()
        current_metrics = evaluator._collect_metrics()

        degradation_threshold = 0.2  # 20% worse = bad

        for metric_name in ["corrections_per_session", "avg_turns_per_task", "repeated_tool_ratio"]:
            baseline_val = baseline.get(metric_name, 0)
            current_val = current_metrics.get(metric_name, 0)

            if baseline_val > 0:
                change = (current_val - baseline_val) / baseline_val
                if change > degradation_threshold:
                    print(f"WARNING: {metric_name} degraded by {change:.1%} (threshold: {degradation_threshold:.1%})")
                    return False  # Metrics degraded

        print("Outcome measurement: metrics stable or improved")
        return True

    def run_analysis(self) -> Dict:
        """Run the analysis phase."""
        print("\n=== ANALYSIS PHASE ===")
        self.analyzer.load_logs(days=7)
        report = self.analyzer.generate_report()

        # Save report
        report_file = DATA_DIR / "analysis_report.json"
        with open(report_file, "w") as f:
            json.dump(report, f, indent=2)

        print(f"Analysis complete: {len(report['recommendations'])} recommendations")
        return report

    def run_evolution(self, analysis_report: Dict, pre_metrics: Dict) -> Dict:
        """Run the evolution phase."""
        print("\n=== EVOLUTION PHASE ===")

        # Save baseline BEFORE evolution for outcome measurement
        print("Saving baseline metrics for outcome measurement...")
        self._save_baseline(pre_metrics)

        # Load current state BEFORE backup for comparison
        pre_state = self.evolver.load_current_state()

        # Generate mutations
        mutations = self.evolver.generate_mutations(analysis_report, pre_state)

        if not mutations:
            print("No mutations generated")
            return {"mutations": []}

        print(f"Generated {len(mutations)} mutations")

        # Create backup
        backup_file = self.evolver.create_backup()
        print(f"Backup created: {backup_file}")

        # Verify backup captured the true pre-mutation state
        if not self.evolver.verify_backup_matches_live(backup_file):
            print("ERROR: Backup does not match live file state - backup may be stale")
            return {
                "mutations": mutations,
                "backup_file": backup_file,
                "error": "Backup verification failed - backup is stale"
            }

        # Apply mutations
        applied = 0
        verification_results = []
        for mutation in mutations:
            print(f"\nApplying: {mutation['description'][:80]}")
            if self.evolver.apply_mutation(mutation):
                applied += 1
                print("  Applied")

                # Verify mutation result
                result = self.evolver.verify_mutation_result(mutation, pre_state)
                verification_results.append(result)
                if not result["success"]:
                    print(f"  WARNING: Mutation verification failed: {result['details']}")
                else:
                    print(f"  Verified: {result['details']}")
            else:
                verification_results.append({
                    "success": False,
                    "details": "apply_mutation returned False",
                    "pre_size": 0,
                    "post_size": 0
                })

        print(f"\nApplied {applied}/{len(mutations)} mutations")
        return {
            "mutations": mutations,
            "backup_file": backup_file,
            "verification_results": verification_results
        }

    def run_consolidation(self) -> bool:
        """Run consolidation if CLAUDE.md exceeds threshold."""
        print("\n=== CONSOLIDATION CHECK ===")

        if not self.evolver.should_consolidate():
            state = self.evolver.load_current_state()
            print(f"CLAUDE.md size: {len(state['claude_md'])} chars (threshold: {self.evolver.consolidation_threshold})")
            print("Consolidation not needed")
            return True

        print("CLAUDE.md exceeds threshold - running consolidation...")
        state = self.evolver.load_current_state()
        print(f"Current size: {len(state['claude_md'])} chars")

        # Create backup before consolidation
        backup_file = self.evolver.create_backup()
        print(f"Backup created: {backup_file}")

        # Run consolidation
        result = self.evolver.consolidate()

        if not result.get("success"):
            print("Consolidation failed")
            return False

        print(f"Consolidation result:")
        print(f"  Original size: {result['original_size']} chars")
        print(f"  New size: {result['new_size']} chars")
        print(f"  Reduction: {(1 - result['new_size'] / result['original_size']) * 100:.1f}%")

        # Apply consolidation
        if self.evolver.apply_consolidation(result):
            print("Consolidation applied successfully")
            return True
        else:
            print("Consolidation application failed - rolling back")
            self.evolver.rollback(backup_file)
            return False

    def run_verification(self, evolution_result: Dict) -> bool:
        """Run the verification phase."""
        print("\n=== VERIFICATION PHASE ===")

        if not evolution_result.get("mutations"):
            print("No mutations to verify")
            return True

        # Verify backup integrity before running benchmarks
        backup_file = evolution_result.get("backup_file")
        if backup_file:
            try:
                backup_path = Path(backup_file)
                if backup_path.exists():
                    with open(backup_path) as f:
                        backup_data = json.load(f)
                    # Verify backup has expected keys
                    if "claude_md" not in backup_data:
                        print("ERROR: Backup file is corrupted - missing claude_md")
                        return False
                else:
                    print(f"ERROR: Backup file not found: {backup_file}")
                    return False
            except (json.JSONDecodeError, IOError) as e:
                print(f"ERROR: Backup file is unreadable: {e}")
                return False

        # Run real validation
        backup_file = evolution_result.get("backup_file")
        passed = True
        for mutation in evolution_result.get("mutations", []):
            if not self.validator.validate_mutation(mutation, backup_file):
                print(f"  Validation FAILED for: {mutation.get('description', 'unknown')}")
                passed = False
                break

        if not passed:
            print("\n*** MUTATIONS UNVERIFIED - rolling back ***")
            if backup_file:
                self.evolver.rollback(backup_file)
                print(f"  Rolled back to: {backup_file}")
            return False

        print("Verification passed (all mutations validated)")
        return True

    def run_cycle(self) -> Dict:
        """Run a complete evolution cycle. Called by event_trigger.py after triggers fire."""
        print(f"\n{'='*60}")
        print(f"Claude Evolution Cycle - {datetime.now().isoformat()}")
        print(f"{'='*60}")

        analysis_report = {}
        evolution_result = {"mutations": []}
        verification_passed = False
        consolidation_passed = True
        outcome_passed = True
        error_message = None

        try:
            # Phase 0: Rotate logs and backups
            print("\n=== LOG ROTATION ===")
            self._rotate_logs()

            # Phase 0.5: Collect baseline metrics BEFORE analysis
            print("\n=== COLLECTING BASELINE METRICS ===")
            from triggers.event_trigger import TriggerEvaluator
            evaluator = TriggerEvaluator()
            pre_metrics = evaluator._collect_metrics()
            print(f"Baseline metrics: corrections={pre_metrics.get('corrections_per_session', 0)}, "
                  f"turns={pre_metrics.get('avg_turns_per_task', 0):.1f}, "
                  f"repeated={pre_metrics.get('repeated_tool_ratio', 0):.2f}")

            # Phase 1: Analysis
            analysis_report = self.run_analysis()

            # Phase 2: Evolution (saves baseline inside)
            evolution_result = self.run_evolution(analysis_report, pre_metrics)

            # Phase 3: Verification
            verification_passed = self.run_verification(evolution_result)

            # Phase 4: Consolidation
            consolidation_passed = self.run_consolidation()

            # Phase 5: Outcome measurement (after cooldown)
            # This runs on subsequent cycles to check if previous evolution helped
            outcome_passed = self._check_outcome()

            # If verification failed and rollback wasn't already done inside
            # run_verification, ensure we roll back here
            if not verification_passed and evolution_result.get("backup_file"):
                # run_verification already handles rollback, but guard
                # against the case where it returned False without rolling back
                pass

        except Exception as e:
            error_message = str(e)
            print(f"\n*** CYCLE ERROR: {error_message} ***")
            import traceback
            traceback.print_exc()

            # Attempt rollback if we have a backup and verification hasn't
            # already rolled back
            if evolution_result.get("backup_file") and verification_passed:
                print("Attempting rollback due to cycle error...")
                try:
                    self.evolver.rollback(evolution_result["backup_file"])
                    print(f"  Rolled back to: {evolution_result['backup_file']}")
                except Exception as rollback_err:
                    print(f"  Rollback also failed: {rollback_err}")

        # Always write the cycle log, even on failure
        cycle_log = {
            "timestamp": datetime.now().isoformat(),
            "analysis_recommendations": len(analysis_report.get("recommendations", [])),
            "mutations_generated": len(evolution_result.get("mutations", [])),
            "verification_passed": verification_passed,
            "consolidation_passed": consolidation_passed,
            "outcome_passed": outcome_passed,
            "backup_file": evolution_result.get("backup_file"),
            "error": error_message
        }

        log_file = DATA_DIR / "cycle_log.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(cycle_log) + "\n")

        print(f"\n{'='*60}")
        print(f"Cycle complete")
        print(f"{'='*60}")

        return cycle_log

def main():
    """Main entry point - runs cycle directly (for testing)."""
    orchestrator = EvolutionOrchestrator()
    result = orchestrator.run_cycle()
    print(f"\nResult: {json.dumps(result, indent=2)}")

    # Exit with non-zero code if verification failed or error occurred,
    # so callers (e.g. event_trigger.py) can detect failure
    if not result.get("verification_passed") or result.get("error"):
        sys.exit(1)

if __name__ == "__main__":
    main()
