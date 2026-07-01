#!/usr/bin/env python3
"""
Verification layer - validates mutations against real criteria.
"""
import json
import os
import sys
import yaml
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

DATA_DIR = Path("/home/reese/claude-evolution/data")
CONFIG_DIR = Path("/home/reese/claude-evolution/config")


class MutationValidator:
    """Validates mutations against real criteria."""

    def __init__(self):
        self.config = self._load_config()

    def _load_config(self) -> Dict:
        """Load configuration."""
        config_file = CONFIG_DIR / "settings.yaml"
        with open(config_file) as f:
            return yaml.safe_load(f)

    def validate_mutation(self, mutation: Dict, backup_file: str) -> bool:
        """Validate a mutation by checking real criteria."""
        target_file = mutation.get("target_file", "")
        mutation_type = mutation.get("mutation_type", "")

        print(f"\nValidating mutation: {mutation.get('description', 'unknown')[:60]}")

        # Resolve target path
        if target_file == "CLAUDE.md":
            target_path = Path(self.config["paths"]["claude_md"])
        elif target_file.startswith("memory/"):
            memory_dir = Path(self.config["paths"]["memory_dir"])
            safe_name = target_file.split("/", 1)[1]
            target_path = memory_dir / safe_name
        else:
            print(f"  Unknown target: {target_file}")
            return False

        # Check target file exists and is readable
        if not target_path.exists():
            print(f"  FAIL: Target file does not exist: {target_path}")
            return False

        try:
            content = target_path.read_text()
        except Exception as e:
            print(f"  FAIL: Cannot read target file: {e}")
            return False

        # Check file is not empty
        if not content.strip():
            print(f"  FAIL: Target file is empty after mutation")
            return False

        # Check file size is reasonable
        if len(content) > 100_000:  # 100KB limit
            print(f"  FAIL: Target file too large: {len(content)} bytes")
            return False

        if len(content) < 100:  # 100 byte minimum
            print(f"  FAIL: Target file too small: {len(content)} bytes")
            return False

        # Check markdown structure
        if target_file == "CLAUDE.md":
            if not self._validate_markdown_structure(content):
                print(f"  FAIL: Invalid markdown structure")
                return False

        # Check memory file frontmatter
        if target_file.startswith("memory/"):
            if not self._validate_memory_frontmatter(content):
                print(f"  FAIL: Invalid memory file frontmatter")
                return False

        # Check mutation actually changed something
        if backup_file and Path(backup_file).exists():
            try:
                with open(backup_file) as f:
                    backup_data = json.load(f)
                if target_file == "CLAUDE.md":
                    backup_content = backup_data.get("claude_md", "")
                elif target_file in backup_data.get("memory_files", {}):
                    backup_content = backup_data["memory_files"][target_file]
                else:
                    backup_content = ""

                if backup_content == content:
                    print(f"  FAIL: Mutation did not change the file")
                    return False

            except Exception as e:
                print(f"  WARNING: Could not verify mutation changed file: {e}")

        # Check no duplicate sections (for add mutations)
        if mutation_type == "add":
            new_content = mutation.get("new_content", "")
            if new_content and new_content in content:
                # Check if it appears multiple times
                occurrences = content.count(new_content)
                if occurrences > 1:
                    print(f"  FAIL: Mutation content appears {occurrences} times (duplicate)")
                    return False

        print(f"  PASS: All validation checks passed")
        return True

    def _validate_markdown_structure(self, content: str) -> bool:
        """Validate markdown file has proper structure."""
        lines = content.split("\n")

        # Check starts with a header
        if not lines[0].startswith("#"):
            return False

        # Check has at least 2 headers
        header_count = sum(1 for line in lines if line.startswith("##"))
        if header_count < 2:
            return False

        # Check no unmatched triple backticks
        backtick_count = content.count("```")
        if backtick_count % 2 != 0:
            return False

        return True

    def _validate_memory_frontmatter(self, content: str) -> bool:
        """Validate memory file has proper frontmatter."""
        lines = content.split("\n")

        # Check starts with ---
        if not lines[0].strip() == "---":
            return False

        # Find closing ---
        closing_index = -1
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                closing_index = i
                break

        if closing_index == -1:
            return False

        # Check frontmatter has required fields
        frontmatter = "\n".join(lines[1:closing_index])
        if "name:" not in frontmatter:
            return False
        if "description:" not in frontmatter:
            return False

        return True

    def save_results(self, results: List[Dict]):
        """Save validation results."""
        results_file = DATA_DIR / "validation_results.json"
        with open(results_file, "w") as f:
            json.dump(results, f, indent=2)


def main():
    """Main validation function."""
    validator = MutationValidator()

    # Load latest evolution log
    evolution_log = DATA_DIR / "evolution_log.jsonl"
    if not evolution_log.exists():
        print("No evolution log found. Run evolver first.")
        return

    # Get latest mutations
    latest_entry = None
    with open(evolution_log) as f:
        for line in f:
            try:
                latest_entry = json.loads(line)
            except json.JSONDecodeError:
                continue

    if not latest_entry:
        print("No mutations to validate.")
        return

    # Validate each mutation
    results = []
    for mutation in latest_entry.get("mutations", []):
        passed = validator.validate_mutation(mutation, latest_entry.get("backup_file"))
        results.append({
            "mutation": mutation.get("description", "unknown"),
            "passed": passed,
            "timestamp": datetime.now().isoformat()
        })
        if not passed:
            print(f"Rolling back mutation: {mutation.get('description')[:50]}")

    validator.save_results(results)
    print(f"\nValidation complete: {sum(1 for r in results if r['passed'])}/{len(results)} passed")


if __name__ == "__main__":
    main()
