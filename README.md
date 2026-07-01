# Claude Evolution System

A self-evolving AI assistant optimization system that passively observes Claude Code sessions and automatically improves CLAUDE.md and memory files based on execution patterns.

## What This Does

The system runs as a background service on your machine, watching how Claude Code performs tasks over time. When it detects patterns that suggest inefficiency or repeated mistakes, it proposes targeted changes to CLAUDE.md (the file that tells Claude how to behave) or memory files.

The key insight: Claude Code gets better over time by learning from its own execution patterns, not just from manual edits.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Claude Code (active session)                          │
│  ├─ PostToolUse hook ─────────────────────────────┐   │
│  ├─ Stop hook ────────────────────────────────┐   │   │
│  └─ UserPromptSubmit hook ────────────────┐   │   │   │
│                                            │   │   │   │
│  All hooks write to: logs/tool_uses.jsonl  │   │   │   │
│                  logs/sessions.jsonl  ◄────┘   │   │   │
│                  logs/corrections.jsonl ◄──────┘   │   │
└──────────────────────────────────────────────────┘   │
                                                        │
┌───────────────────────────────────────────────────────┘
│
├─ triggers/event_trigger.py
│  ├─ Collects metrics from logs
│  ├─ Evaluates trigger rules
│  └─ Runs orchestrate.py when triggered
│
├─ orchestrate.py (main pipeline)
│  ├─ Phase 0: Log rotation + baseline metrics
│  ├─ Phase 1: analysis/analyzer.py (pattern detection)
│  ├─ Phase 2: evolution/evolver.py (LLM mutation proposals)
│  ├─ Phase 3: verification/validator.py (syntax + structure checks)
│  └─ Phase 4: consolidation (size control for CLAUDE.md)
│
└─ config/settings.yaml (all configuration)
```

## Components

### Observation Layer (hooks/)
Passive logging during real Claude Code work. Zero overhead.

- `post_tool_use.py` — Logs every tool call with name, timing, success
- `session_end.py` — Logs session summaries when Claude Code exits
- `tool_counter.py` — Maintains per-session tool call counts
- `user_correction.py` — Logs user corrections and feedback

### Analysis Layer (analysis/)
Reads JSONL logs and detects patterns.

- `analyzer.py` — Finds repeated tool calls, correction patterns, session complexity
- Generates severity-rated recommendations (P0/P1/P2)

### Evolution Layer (evolution/)
Uses DeepSeek V4 Flash via OpenRouter to propose CLAUDE.md mutations.

- `evolver.py` — Batch LLM calls with deduplication, atomic writes, path validation
- Only modifies CLAUDE.md or memory/*.md (strict path allowlist)
- Tracks API costs and enforces budget limits

### Verification Layer (verification/)
Validates mutations before applying.

- `validator.py` — Checks markdown structure, memory frontmatter, file integrity
- Detects empty files, oversized files, duplicate content

### Trigger System (triggers/)
Event-driven activation based on session metrics.

- `event_trigger.py` — 7 trigger rules with cooldowns
- Fires when: corrections spike, repeated tool calls, session complexity, errors, log size, memory changes, or daily fallback

### Configuration (config/)
- `settings.yaml` — Model, paths, thresholds, budget, rotation
- `triggers.yaml` — Trigger rules and cooldowns

## Setup

### 1. Set API Key

The system uses your existing OpenRouter key (ANTHROPIC_API_KEY env var). No additional setup needed.

### 2. Enable Systemd Timer

```bash
# Enable lingering (so timers survive logout)
loginctl enable-linger reese

# Enable and start the timer
systemctl --user daemon-reload
systemctl --user enable claude-evolution.timer
systemctl --user start claude-evolution.timer
```

### 3. Verify It's Running

```bash
systemctl --user status claude-evolution.timer
systemctl --user list-timers
```

## Manual Usage

### Run a Cycle Manually

```bash
cd /home/reese/claude-evolution
python3 orchestrate.py
```

### Check Status

```bash
# Timer status
systemctl --user status claude-evolution.timer

# Next run time
systemctl --user list-timers

# Last run logs
journalctl --user -u claude-evolution.service -n 50

# Cost tracking
cat data/usage_history.json

# CLAUDE.md size
wc -c /home/reese/CLAUDE.md

# Backup count
ls data/backups/ | wc -l
```

### Trigger Evaluation Only

```bash
python3 triggers/event_trigger.py
```

## Configuration

Edit `config/settings.yaml`:

```yaml
# Model (DeepSeek V4 Flash via OpenRouter)
models:
  evolution:
    model: "deepseek/deepseek-v4-flash"
    temperature: 0.7

# Paths
paths:
  claude_md: "/home/reese/CLAUDE.md"
  memory_dir: "/home/reese/.claude/projects/-home-reese/memory"

# Thresholds
thresholds:
  evolution_cooldown_hours: 24

# Budget
budget:
  max_daily_cost_usd: 2.0

# Consolidation
consolidation:
  threshold_chars: 5000
  target_chars: 3500

# Log rotation
rotation:
  max_log_age_days: 30
  max_backups: 20
```

## Trigger Rules

| Trigger | Metric | Threshold | Cooldown |
|---------|--------|-----------|----------|
| correction_burst | Corrections per session | >= 3 | 6h |
| repeated_pattern | Rapid tool call ratio | >= 30% | 12h |
| session_complexity | Avg turns per task | >= 15 | 24h |
| error_spike | Errors per session | >= 5 | 4h |
| new_memory_files | Files changed in 24h | >= 2 | 12h |
| data_accumulation | Log size MB | >= 5.0 | 48h |
| time_based | Fallback timer | 24h | 20h |

## How It Decides to Evolve

1. Hooks log every tool call, session, and correction during normal Claude Code work
2. When any trigger fires (e.g., 3+ corrections in 24h), the system runs a cycle
3. Analysis detects patterns in the logs
4. LLM proposes targeted mutations to CLAUDE.md or memory files
5. Mutations are validated (syntax, structure, no duplicates)
6. Backup is created before changes
7. Changes are applied with atomic writes
8. Next cycle checks if metrics improved or degraded

## Cost

- **Model:** DeepSeek V4 Flash via OpenRouter
- **Pricing:** $0.098/M input, $0.196/M output
- **Per cycle:** ~$0.002-0.01
- **Monthly:** ~$0.06-0.30
- **Budget limit:** $2/day (configurable)

## File Structure

```
claude-evolution/
├── config/
│   ├── settings.yaml          # All configuration
│   └── triggers.yaml          # Trigger rules
├── hooks/
│   ├── hook_utils.py          # Shared utilities (stdin parsing)
│   ├── post_tool_use.py       # Tool call logging
│   ├── session_end.py         # Session summary logging
│   ├── tool_counter.py        # Per-session tool counting
│   └── user_correction.py     # Correction tracking
├── triggers/
│   └── event_trigger.py       # Event-driven activation
├── analysis/
│   └── analyzer.py            # Pattern detection
├── evolution/
│   └── evolver.py             # LLM mutation proposals
├── verification/
│   └── validator.py           # Mutation validation
├── rotation/
│   └── rotator.py             # Log and backup cleanup
├── logs/                      # JSONL execution logs
├── data/
│   ├── backups/               # Pre-mutation snapshots
│   ├── analysis_report.json   # Latest analysis
│   ├── evolution_log.jsonl    # Mutation history
│   ├── cycle_log.jsonl        # Cycle history
│   ├── baseline.json          # Metrics baseline
│   └── usage_history.json     # API cost tracking
├── orchestrate.py             # Main pipeline
├── run_evolution.sh           # Shell entry point
├── .gitignore                 # Prevents secret/ data leaks
└── README.md                  # This file
```

## Safety

- **Path validation:** Only CLAUDE.md and memory/*.md can be modified
- **Atomic writes:** Temp file + rename pattern prevents corruption
- **Backup before mutation:** Full snapshot before any changes
- **Budget limits:** API calls refused when daily budget exceeded
- **Deduplication:** Prevents same guidance from being added twice
- **Consolidation:** Auto-prunes CLAUDE.md when it exceeds 5,000 chars
- **Outcome measurement:** Tracks if mutations improved or degraded metrics
- **Auto-rollback:** Reverts if metrics degrade >20%

## Troubleshooting

### Timer not running

```bash
systemctl --user status claude-evolution.timer
loginctl show-user reese | grep Linger
```

If Linger=no: `loginctl enable-linger reese`

### No mutations being generated

```bash
# Check if triggers are firing
python3 triggers/event_trigger.py

# Check analysis recommendations
cat data/analysis_report.json | python3 -m json.tool

# Check evolution log
cat data/evolution_log.jsonl
```

### API errors

```bash
# Check API key is set
echo $ANTHROPIC_API_KEY | head -c 10

# Check usage history
cat data/usage_history.json
```

### CLAUDE.md got corrupted

Restore from backup:

```bash
python3 -c "
import json, glob
backups = sorted(glob.glob('data/backups/backup_*.json'))
with open(backups[-1]) as f:
    b = json.load(f)
with open('/home/reese/CLAUDE.md', 'w') as f:
    f.write(b['claude_md'])
print(f'Restored from {backups[-1]}')
"
```
