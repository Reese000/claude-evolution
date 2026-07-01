#!/usr/bin/env python3
"""
Evolution layer - uses LLM to propose CLAUDE.md mutations.
This runs periodically based on analysis results.
"""
import json
import os
import sys
import re
import time
import yaml
import fcntl
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from difflib import SequenceMatcher
from typing import Dict, List, Any
import httpx

DATA_DIR = Path("/home/reese/claude-evolution/data")
CONFIG_DIR = Path("/home/reese/claude-evolution/config")

# Security: Only these paths are valid mutation targets
VALID_TARGETS = re.compile(r"^(CLAUDE\.md|memory/[a-zA-Z0-9_-]+\.md)$")
MAX_MUTATION_SIZE = 50_000  # 50KB limit per mutation content

class LLMClient:
    """Simple LLM client for DeepSeek with cost tracking."""

    def __init__(self, model_config: Dict, budget_config: Dict = None):
        self.base_url = model_config["base_url"]
        self.model = model_config["model"]
        self.max_tokens = model_config.get("max_tokens", 4000)
        self.temperature = model_config.get("temperature", 0.3)
        self._client = httpx.Client()  # Reuse connection pool

        # Cost tracking
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.cost_per_1m_input = 0.098  # DeepSeek V4 Flash pricing
        self.cost_per_1m_output = 0.196

        # Budget limits
        self.max_daily_cost = budget_config.get("max_daily_cost_usd", 2.0) if budget_config else 2.0
        self.max_monthly_cost = budget_config.get("max_monthly_cost_usd", 30.0) if budget_config else 30.0

        # Load historical usage
        self._load_usage_history()

        # Validate API key
        api_key_env = model_config.get("api_key_env")
        if api_key_env:
            self.api_key = os.environ.get(api_key_env)
            if not self.api_key:
                raise ValueError(
                    f"API key environment variable '{api_key_env}' is not set or empty. "
                    f"Please set it before initializing the LLM client."
                )
        else:
            self.api_key = None

    def _load_usage_history(self):
        """Load historical token usage from file."""
        usage_file = DATA_DIR / "usage_history.json"
        if usage_file.exists():
            try:
                with open(usage_file) as f:
                    history = json.load(f)
                self.total_input_tokens = history.get("total_input_tokens", 0)
                self.total_output_tokens = history.get("total_output_tokens", 0)
            except Exception:
                pass

    def _save_usage_history(self):
        """Save token usage to file."""
        usage_file = DATA_DIR / "usage_history.json"
        with open(usage_file, "w") as f:
            json.dump({
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
                "last_updated": datetime.now().isoformat()
            }, f, indent=2)

    def _calculate_cost(self) -> Dict:
        """Calculate current costs."""
        input_cost = (self.total_input_tokens / 1_000_000) * self.cost_per_1m_input
        output_cost = (self.total_output_tokens / 1_000_000) * self.cost_per_1m_output
        total_cost = input_cost + output_cost

        return {
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "input_cost": input_cost,
            "output_cost": output_cost,
            "total_cost": total_cost
        }

    def _check_budget(self) -> bool:
        """Check if we're within budget limits."""
        costs = self._calculate_cost()
        if costs["total_cost"] > self.max_daily_cost:
            print(f"WARNING: Daily budget exceeded (${costs['total_cost']:.4f} > ${self.max_daily_cost})")
            return False
        return True

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        """Generate a response from the LLM with retry logic and cost tracking."""
        # Check budget before making request
        if not self._check_budget():
            return ""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature
        }

        max_retries = 3
        retry_delays = [1.0, 2.0, 4.0]  # Exponential backoff base delays

        for attempt in range(max_retries):
            try:
                response = self._client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=60.0
                )

                # Track usage if response successful
                if response.status_code == 200:
                    data = response.json()
                    usage = data.get("usage", {})
                    self.total_input_tokens += usage.get("prompt_tokens", 0)
                    self.total_output_tokens += usage.get("completion_tokens", 0)
                    self._save_usage_history()

                    # Check budget after request
                    costs = self._calculate_cost()
                    if costs["total_cost"] > self.max_daily_cost:
                        print(f"WARNING: Budget exceeded after request (${costs['total_cost']:.4f})")

                    return data["choices"][0]["message"]["content"]
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < max_retries - 1:
                        retry_after = retry_delays[attempt]
                        # Respect Retry-After header if present
                        if "Retry-After" in response.headers:
                            try:
                                retry_after = max(retry_after, float(response.headers["Retry-After"]))
                            except ValueError:
                                pass
                        print(f"LLM request returned {response.status_code}, retrying in {retry_after}s (attempt {attempt + 1}/{max_retries})")
                        time.sleep(retry_after)
                        continue

                # Non-retryable error
                print(f"LLM generation failed: HTTP {response.status_code}")
                return ""

            except httpx.HTTPStatusError as e:
                if attempt < max_retries - 1 and e.response.status_code in (429, 500, 502, 503, 504):
                    retry_after = retry_delays[attempt]
                    print(f"LLM generation failed: HTTP {e.response.status_code}, retrying in {retry_after}s")
                    time.sleep(retry_after)
                    continue
                print(f"LLM generation failed: HTTP {e.response.status_code}")
                return ""
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as e:
                if attempt < max_retries - 1:
                    retry_after = retry_delays[attempt]
                    print(f"LLM generation failed: {type(e).__name__}, retrying in {retry_after}s")
                    time.sleep(retry_after)
                    continue
                print(f"LLM generation failed: {type(e).__name__}")
                return ""
            except Exception as e:
                print(f"LLM generation failed: {type(e).__name__}")
                return ""

        return ""

class EvolutionEngine:
    """Uses LLM to propose CLAUDE.md mutations."""

    def __init__(self):
        self.config = self._load_config()
        self.llm = LLMClient(
            self.config["models"]["evolution"],
            self.config.get("budget", {})
        )
        self._lock_fd = None

        # Consolidation settings
        consolidation = self.config.get("consolidation", {})
        self.consolidation_enabled = consolidation.get("enabled", True)
        self.consolidation_threshold = consolidation.get("threshold_chars", 5000)
        self.consolidation_target = consolidation.get("target_chars", 3500)
        self.consolidation_temperature = consolidation.get("temperature", 0.3)

    def _load_config(self) -> Dict:
        """Load configuration."""
        config_file = CONFIG_DIR / "settings.yaml"
        with open(config_file) as f:
            return yaml.safe_load(f)

    def load_current_state(self) -> Dict:
        """Load current CLAUDE.md and memory files."""
        claude_md_path = Path(self.config["paths"]["claude_md"])
        memory_dir = Path(self.config["paths"]["memory_dir"])

        state = {
            "claude_md": "",
            "memory_files": {}
        }

        if claude_md_path.exists():
            state["claude_md"] = claude_md_path.read_text()

        if memory_dir.exists():
            for md_file in memory_dir.glob("*.md"):
                state["memory_files"][md_file.name] = md_file.read_text()

        return state

    def load_analysis_report(self) -> Dict:
        """Load the latest analysis report."""
        report_file = DATA_DIR / "analysis_report.json"
        if report_file.exists():
            with open(report_file) as f:
                return json.load(f)
        return {}

    def generate_mutations(self, analysis_report: Dict, current_state: Dict) -> List[Dict]:
        """Use LLM to generate mutation proposals."""
        if not analysis_report.get("recommendations"):
            return []

        # Batch all recommendations into a single LLM call
        mutations = self._propose_mutations_batch(analysis_report["recommendations"], current_state)
        return mutations

    def should_consolidate(self) -> bool:
        """Check if CLAUDE.md exceeds consolidation threshold."""
        if not self.consolidation_enabled:
            return False
        state = self.load_current_state()
        return len(state["claude_md"]) > self.consolidation_threshold

    def consolidate(self) -> Dict:
        """Consolidate CLAUDE.md to reduce size while preserving essential content."""
        state = self.load_current_state()
        claude_md = state["claude_md"]
        current_size = len(claude_md)

        system_prompt = """You are an expert at optimizing AI agent instructions. Your task is to consolidate
CLAUDE.md to reduce its size while preserving all essential behavioral guidance.
Be ruthless: remove redundancy, merge similar sections, tighten language.
Keep the structure clear with markdown headers."""

        prompt = f"""This CLAUDE.md has grown to {current_size} chars. Consolidate it to ~{self.consolidation_target} chars.

Current CLAUDE.md:
{claude_md}

Rules:
1. Preserve ALL essential behavioral instructions (delegation, quality, tool usage)
2. Merge duplicate sections (e.g., multiple efficiency tips → one section)
3. Remove verbose explanations — use bullet points
4. Remove anything that's obvious or doesn't change Claude's behavior
5. Keep markdown structure with ## headers
6. Target: {self.consolidation_target} chars (currently {current_size})

Respond with a JSON object:
{{
    "consolidated_md": "The full consolidated CLAUDE.md content",
    "sections_removed": ["list of what was removed"],
    "sections_merged": ["list of what was merged"],
    "size_reduction": "percentage reduced"
}}"""

        # Use lower temperature for precise consolidation
        old_temp = self.llm.temperature
        self.llm.temperature = self.consolidation_temperature
        response = self.llm.generate(prompt, system_prompt)
        self.llm.temperature = old_temp

        try:
            # Extract JSON
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                result = json.loads(json_match.group())
                consolidated = result.get("consolidated_md", "")
                if consolidated and len(consolidated) < current_size:
                    return {
                        "success": True,
                        "original_size": current_size,
                        "new_size": len(consolidated),
                        "consolidated_md": consolidated,
                        "sections_removed": result.get("sections_removed", []),
                        "sections_merged": result.get("sections_merged", [])
                    }
        except (json.JSONDecodeError, KeyError):
            pass

        return {"success": False, "reason": "LLM consolidation failed"}

    def apply_consolidation(self, consolidation_result: Dict) -> bool:
        """Apply consolidation result to CLAUDE.md."""
        if not consolidation_result.get("success"):
            return False

        claude_md_path = Path(self.config["paths"]["claude_md"])
        consolidated = consolidation_result["consolidated_md"]

        try:
            # Atomic write
            temp_file = claude_md_path.with_suffix(".tmp")
            temp_file.write_text(consolidated)
            temp_file.rename(claude_md_path)
            return True
        except Exception as e:
            print(f"Failed to apply consolidation: {e}")
            return False

    def _propose_mutations_batch(self, recommendations: List[Dict], current_state: Dict) -> List[Dict]:
        """Use LLM to propose all mutations in a single call."""
        system_prompt = """You are an expert at optimizing AI agent instructions. You analyze execution patterns
and propose targeted mutations to improve performance. Be concise and specific.
You MUST respond with a valid JSON array of mutations."""

        recs_text = "\n".join([
            f"- [{r['severity']}] {r['category']}: {r['issue']} (suggestion: {r['suggestion']})"
            for r in recommendations
        ])

        prompt = f"""Based on these analysis recommendations, propose mutations to CLAUDE.md or memory files.

Recommendations:
{recs_text}

Full current CLAUDE.md:
{current_state['claude_md']}

Current memory files: {json.dumps(list(current_state['memory_files'].keys()))}

Respond with a JSON array of mutations (or empty array if none are valuable):
[
  {{
    "target_file": "CLAUDE.md" or "memory/filename.md",
    "mutation_type": "add" | "modify" | "remove",
    "description": "What this mutation does",
    "old_content": "Content to replace (if modifying/removing)",
    "new_content": "New content (if adding/modifying)",
    "confidence": 0.0-1.0,
    "reasoning": "Why this mutation will help"
  }}
]

CRITICAL RULES:
- DO NOT add guidance that already exists in the file. Read the full CLAUDE.md content above carefully and check for existing content before proposing ANY mutation.
- If a recommendation describes something already covered in the file, skip it entirely.
- target_file must be exactly "CLAUDE.md" or "memory/some-filename.md"
- Only include mutations with confidence > 0.6
- old_content must be exact text from the current file
- new_content must be under 5000 characters"""

        response = self.llm.generate(prompt, system_prompt)

        try:
            # Try to extract JSON array from response - check code blocks first
            json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', response)
            if json_match:
                json_text = json_match.group(1).strip()
            else:
                # Fall back to finding a JSON array directly with non-greedy match
                json_match = re.search(r'\[[\s\S]*?\]', response)
                if json_match:
                    json_text = json_match.group()
                else:
                    return []

            # Try to parse the extracted text as a JSON array
            if json_text.startswith('['):
                mutations = json.loads(json_text)
            else:
                return []

            # Filter, validate, and deduplicate
            valid_mutations = []
            seen_content = []  # Track accepted new_content for intra-batch dedup
            for mutation in mutations:
                if not self._validate_mutation(mutation):
                    continue
                if mutation.get("confidence", 0) > 0.6:
                    # Deduplicate: skip if new_content is similar to an already-accepted mutation
                    new_content = (mutation.get("new_content") or "").strip()
                    if new_content and self._is_content_similar_to_any(new_content, seen_content):
                        print(f"Rejected mutation: duplicate of earlier mutation in batch ({mutation.get('description', '')[:60]})")
                        continue
                    # Deduplicate: skip if adding content that already exists in the target file
                    if mutation.get("mutation_type") == "add" and new_content:
                        target_file = mutation.get("target_file", "")
                        existing = self._get_target_content(target_file, current_state)
                        if existing and self._is_content_similar_to_existing(new_content, existing):
                            print(f"Rejected mutation: content already exists in {target_file} ({mutation.get('description', '')[:60]})")
                            continue
                    if new_content:
                        seen_content.append(new_content)
                    mutation["timestamp"] = datetime.now().isoformat()
                    valid_mutations.append(mutation)

            return valid_mutations

        except json.JSONDecodeError:
            return []

    def _validate_mutation(self, mutation: Dict) -> bool:
        """Validate a mutation for safety."""
        target_file = mutation.get("target_file", "")

        # Security: Validate target path
        if not VALID_TARGETS.match(target_file):
            print(f"Rejected mutation: invalid target '{target_file}'")
            return False

        # Security: Validate content size
        new_content = mutation.get("new_content") or ""
        old_content = mutation.get("old_content") or ""

        if len(new_content) > MAX_MUTATION_SIZE:
            print(f"Rejected mutation: new_content exceeds {MAX_MUTATION_SIZE} bytes")
            return False

        if len(old_content) > MAX_MUTATION_SIZE:
            print(f"Rejected mutation: old_content exceeds {MAX_MUTATION_SIZE} bytes")
            return False

        # Validate mutation type
        if mutation.get("mutation_type") not in ("add", "modify", "remove"):
            print(f"Rejected mutation: invalid type '{mutation.get('mutation_type')}'")
            return False

        return True

    def _normalize_text(self, text: str) -> str:
        """Normalize text for comparison: lowercase, collapse whitespace, strip markdown formatting."""
        text = text.lower().strip()
        # Collapse all whitespace runs to single space
        text = re.sub(r'\s+', ' ', text)
        # Strip common markdown formatting for comparison
        text = re.sub(r'[*_#`>-]', '', text)
        return text

    def _similarity_ratio(self, a: str, b: str) -> float:
        """Return a 0.0-1.0 similarity ratio between two strings using SequenceMatcher."""
        na = self._normalize_text(a)
        nb = self._normalize_text(b)
        if not na or not nb:
            return 0.0
        return SequenceMatcher(None, na, nb).ratio()

    def _is_content_similar_to_any(self, new_content: str, existing_list: List[str], threshold: float = 0.75) -> bool:
        """Check if new_content is similar to any string in existing_list."""
        for existing in existing_list:
            if self._similarity_ratio(new_content, existing) >= threshold:
                return True
        return False

    def _is_content_similar_to_existing(self, new_content: str, file_content: str, threshold: float = 0.75) -> bool:
        """
        Check if new_content is similar to any chunk already in the target file.
        Splits the file into paragraph-sized chunks and compares each one.
        """
        # Split file into paragraphs (double newline separated)
        paragraphs = re.split(r'\n{2,}', file_content)
        new_norm = self._normalize_text(new_content)

        # Also check if the normalized new content is a substring of the normalized file
        file_norm = self._normalize_text(file_content)
        if len(new_norm) > 30 and new_norm in file_norm:
            return True

        # Check similarity against each paragraph
        for paragraph in paragraphs:
            if len(paragraph.strip()) < 10:
                continue
            if self._similarity_ratio(new_content, paragraph) >= threshold:
                return True

        return False

    def _get_target_content(self, target_file: str, current_state: Dict) -> str:
        """Get the current content of the target file from state."""
        if target_file == "CLAUDE.md":
            return current_state.get("claude_md", "")
        elif target_file.startswith("memory/"):
            mem_name = target_file.split("/", 1)[1]
            return current_state.get("memory_files", {}).get(mem_name, "")
        return ""

    def apply_mutation(self, mutation: Dict) -> bool:
        """Apply a mutation to the file system with atomic writes and locking."""
        try:
            target_file = mutation["target_file"]

            # Resolve to actual path using config
            if target_file == "CLAUDE.md":
                target = Path(self.config["paths"]["claude_md"])
            elif target_file.startswith("memory/"):
                memory_dir = Path(self.config["paths"]["memory_dir"])
                # Security: strip any directory traversal
                safe_name = Path(target_file.split("/", 1)[1]).name
                target = memory_dir / safe_name
            else:
                target = Path(target_file)

            # Apply mutation with file locking
            with self._file_lock(target):
                if mutation["mutation_type"] == "add":
                    # Atomic write: use existing content or empty string, append, then rename
                    existing_content = target.read_text() if target.exists() else ""
                    new_content = existing_content + "\n" + mutation["new_content"]
                    temp_file = target.with_suffix(".tmp")
                    temp_file.write_text(new_content)
                    temp_file.rename(target)

                elif mutation["mutation_type"] == "modify":
                    if target.exists():
                        content = target.read_text()
                        if mutation["old_content"] in content:
                            new_content = content.replace(
                                mutation["old_content"],
                                mutation["new_content"]
                            )
                            # Atomic write: write to temp then rename
                            temp_file = target.with_suffix(".tmp")
                            temp_file.write_text(new_content)
                            temp_file.rename(target)
                        else:
                            print(f"Warning: old_content not found in {target}")
                            return False

                elif mutation["mutation_type"] == "remove":
                    if target.exists():
                        content = target.read_text()
                        if mutation["old_content"] in content:
                            new_content = content.replace(mutation["old_content"], "")
                            temp_file = target.with_suffix(".tmp")
                            temp_file.write_text(new_content)
                            temp_file.rename(target)
                        else:
                            print(f"Warning: old_content not found in {target}")
                            return False

            return True

        except Exception as e:
            print(f"Failed to apply mutation: {e}")
            return False

    @contextmanager
    def _file_lock(self, path: Path):
        """Context manager for file locking."""
        lock_file = path.with_suffix(".lock")
        fd = None
        try:
            fd = open(lock_file, "w")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            if fd is not None:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except Exception:
                    pass
                fd.close()
            lock_file.unlink(missing_ok=True)

    def create_backup(self) -> str:
        """Create a backup before applying mutations."""
        backup_dir = Path(self.config["paths"]["backup_dir"])
        backup_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = backup_dir / f"backup_{timestamp}.json"

        state = self.load_current_state()
        with open(backup_file, "w") as f:
            json.dump(state, f, indent=2)

        # Set restrictive permissions
        backup_file.chmod(0o600)

        # Read back and verify the backup was written correctly
        with open(backup_file) as f:
            readback = json.load(f)

        # Compare read-back content sizes against live file sizes
        claude_md_path = Path(self.config["paths"]["claude_md"])
        if claude_md_path.exists():
            live_size = len(claude_md_path.read_text())
            backup_size = len(readback.get("claude_md", ""))
            if live_size != backup_size:
                msg = (
                    f"Backup verification failed: CLAUDE.md size mismatch "
                    f"(live={live_size}, backup={backup_size})"
                )
                print(f"WARNING: {msg}")
                raise RuntimeError(msg)

        memory_dir = Path(self.config["paths"]["memory_dir"])
        if memory_dir.exists():
            for md_file in memory_dir.glob("*.md"):
                live_size = len(md_file.read_text())
                backup_size = len(readback.get("memory_files", {}).get(md_file.name, ""))
                if live_size != backup_size:
                    msg = (
                        f"Backup verification failed: memory file '{md_file.name}' "
                        f"size mismatch (live={live_size}, backup={backup_size})"
                    )
                    print(f"WARNING: {msg}")
                    raise RuntimeError(msg)

        return str(backup_file)

    def rollback(self, backup_file: str):
        """Rollback to a backup with path validation."""
        backup_path = Path(backup_file)

        # Security: Validate backup path
        backup_dir = Path(self.config["paths"]["backup_dir"]).resolve()
        if not backup_path.resolve().is_relative_to(backup_dir):
            raise ValueError(f"Backup path escapes backup directory: {backup_file}")

        with open(backup_path) as f:
            state = json.load(f)

        # Restore CLAUDE.md
        claude_md_path = Path(self.config["paths"]["claude_md"])
        temp_file = claude_md_path.with_suffix(".tmp")
        temp_file.write_text(state["claude_md"])
        temp_file.rename(claude_md_path)

        # Restore memory files with path sanitization
        memory_dir = Path(self.config["paths"]["memory_dir"])
        for filename, content in state["memory_files"].items():
            safe_name = Path(filename).name  # Strip any directory components
            target = memory_dir / safe_name
            temp_file = target.with_suffix(".tmp")
            temp_file.write_text(content)
            temp_file.rename(target)

    def verify_mutation_result(self, mutation: Dict, pre_state: Dict) -> dict:
        """Verify that a mutation was applied correctly after the fact."""
        target_file = mutation["target_file"]

        # Resolve to actual path using config (same logic as apply_mutation)
        if target_file == "CLAUDE.md":
            target = Path(self.config["paths"]["claude_md"])
        elif target_file.startswith("memory/"):
            memory_dir = Path(self.config["paths"]["memory_dir"])
            safe_name = Path(target_file.split("/", 1)[1]).name
            target = memory_dir / safe_name
        else:
            target = Path(target_file)

        # Determine pre-size from the pre_state snapshot
        if target_file == "CLAUDE.md":
            pre_size = len(pre_state.get("claude_md", ""))
        else:
            mem_name = target_file.split("/", 1)[1] if "/" in target_file else target_file
            pre_size = len(pre_state.get("memory_files", {}).get(mem_name, ""))

        # Read current file content after mutation
        if not target.exists():
            return {
                "success": False,
                "details": f"Target file does not exist: {target}",
                "pre_size": pre_size,
                "post_size": 0,
            }

        post_content = target.read_text()
        post_size = len(post_content)
        mutation_type = mutation.get("mutation_type", "")
        success = True
        details = ""

        if mutation_type == "add":
            if post_size <= pre_size:
                success = False
                details = f"File size did not increase (pre={pre_size}, post={post_size})"
            else:
                details = f"Add verified: size increased from {pre_size} to {post_size}"

        elif mutation_type == "modify":
            old_content = mutation.get("old_content", "")
            new_content = mutation.get("new_content", "")
            if old_content and old_content in post_content:
                success = False
                details = "old_content still present after modification"
            elif new_content and new_content not in post_content:
                success = False
                details = "new_content not found after modification"
            else:
                details = f"Modify verified: size changed from {pre_size} to {post_size}"

        elif mutation_type == "remove":
            old_content = mutation.get("old_content", "")
            if old_content and old_content in post_content:
                success = False
                details = "old_content still present after removal"
            else:
                details = f"Remove verified: size changed from {pre_size} to {post_size}"

        else:
            success = False
            details = f"Unknown mutation_type: {mutation_type}"

        # Check the file is still valid markdown
        if success:
            has_heading = bool(re.search(r'^#+\s', post_content, re.MULTILINE))
            if not has_heading:
                success = False
                details += " | WARNING: no markdown headings found"

            # Check for obviously broken syntax (unmatched triple backticks)
            backtick_count = post_content.count("```")
            if backtick_count % 2 != 0:
                success = False
                details += " | WARNING: unmatched triple backticks detected"

        return {
            "success": success,
            "details": details,
            "pre_size": pre_size,
            "post_size": post_size,
        }

    def verify_backup_matches_live(self, backup_file: str) -> bool:
        """Check that a backup file matches the current live file state."""
        backup_path = Path(backup_file)
        if not backup_path.exists():
            return False

        with open(backup_path) as f:
            backup_data = json.load(f)

        live_state = self.load_current_state()

        # Compare claude_md content
        if backup_data.get("claude_md") != live_state.get("claude_md"):
            return False

        # Compare memory files content
        backup_mem = backup_data.get("memory_files", {})
        live_mem = live_state.get("memory_files", {})
        if set(backup_mem.keys()) != set(live_mem.keys()):
            return False
        for key in backup_mem:
            if backup_mem[key] != live_mem[key]:
                return False

        return True

def main():
    """Main evolution function."""
    engine = EvolutionEngine()

    # Load current state
    current_state = engine.load_current_state()
    analysis_report = engine.load_analysis_report()

    if not analysis_report:
        print("No analysis report found. Run analyzer first.")
        return

    # Generate mutations
    mutations = engine.generate_mutations(analysis_report, current_state)

    if not mutations:
        print("No high-confidence mutations generated.")
        return

    print(f"Generated {len(mutations)} mutations")

    # Create backup
    backup_file = engine.create_backup()
    print(f"Backup created: {backup_file}")

    # Apply mutations
    applied = 0
    for mutation in mutations:
        print(f"\nApplying mutation: {mutation['description'][:80]}")
        print(f"  Target: {mutation['target_file']}")
        print(f"  Type: {mutation['mutation_type']}")
        print(f"  Confidence: {mutation['confidence']:.2f}")

        if engine.apply_mutation(mutation):
            applied += 1
            print("  ✓ Applied successfully")
        else:
            print("  ✗ Failed to apply")

    print(f"\nApplied {applied}/{len(mutations)} mutations")
    print(f"Backup available at: {backup_file}")

    # Log the evolution (metadata only, no full content for security)
    log_file = DATA_DIR / "evolution_log.jsonl"
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "mutations_proposed": len(mutations),
        "mutations_applied": applied,
        "backup_file": backup_file,
        "costs": self.llm._calculate_cost(),
        "mutation_summaries": [
            {
                "target": m["target_file"],
                "type": m["mutation_type"],
                "description": m["description"][:100],
                "confidence": m["confidence"]
            }
            for m in mutations
        ]
    }
    with open(log_file, "a") as f:
        f.write(json.dumps(log_entry) + "\n")

if __name__ == "__main__":
    main()
