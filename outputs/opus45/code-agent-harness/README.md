# Code Agent Harness

A structured agent harness for automated bug fixing using the six-component architecture:

**H = (E, T, C, S, L, V)**

## Components

| Component | Module | Responsibility |
|-----------|--------|----------------|
| **E** Execution | `execution.py` | State machine with explicit `match/case` transitions |
| **T** Tools | `tools.py`, `domain/tools.py` | Pydantic-validated tool registry |
| **C** Context | `context.py` | Source/test/history context with compression |
| **S** State | `state.py` | Bug tracking, snapshots, progress |
| **L** Lifecycle | `lifecycle.py` | Backup, validation, rollback hooks |
| **V** Evaluation | `evaluation.py` | JSONL trajectory recording |

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables for LLM
export OPENAI_BASE_URL="http://127.0.0.1:3457/v1"
export OPENAI_API_KEY="your-key"
export MODEL_NAME="gpt-4"

# Run in single mode
python3 -m harness.cli run --work-dir ./samples

# Run interactively
python3 -m harness.cli interactive --work-dir ./samples
```

## Architecture

### State Machine (E)

```
IDLE → INDEX → TEST → CLASSIFY → PRIORITIZE → FIX_LOOP → REGRESSION → REPORT → COMPLETED
                                       ↓
                              LOCATE → ANALYZE → FIX → VERIFY → COMMIT
                                        ↑                ↓
                                        └────────────────┘ (on verify fail)
```

### Tool Registry (T)

- `CodeSearcher`: Regex search across files
- `FileEditor`: Read/write/patch operations
- `TestRunner`: Selective or full pytest execution
- `GitOperator`: Stage, commit, diff
- `StaticAnalyzer`: AST-based code analysis

### Lifecycle Hooks (L)

| Event | Pre-Hook | Post-Hook |
|-------|----------|-----------|
| File Modify | Backup | - |
| Test Run | Snapshot | - |
| Commit | Validation | - |
| Fix Failure | - | Rollback |

## Sample Bug Fixes

The `samples/` directory contains a task management server with 8 bugs:

| Bug | Category | Severity | Description |
|-----|----------|----------|-------------|
| 1 | Correctness | Medium | JSON not encoded to bytes |
| 2 | Logic | High | OR instead of AND in filters |
| 3 | Correctness | Low | Missing ORDER BY |
| 4 | **Security** | **Critical** | SQL injection |
| 5 | Validation | Medium | Silent status correction |
| 6 | Timing | High | Query after connection close |
| 7 | Correctness | Medium | Updated_at not maintained |
| 8 | Spec | Medium | Wrong status code (200 vs 404) |

## CLI Commands

```
/run           - Run full bug fixing workflow
/test [pat]    - Run tests (optionally filtered)
/status        - Show current progress
/clear         - Clear state and restart
/compact       - Compact context
/resume        - Resume from saved state
/help          - Show help
/quit          - Exit
```

## Evaluation Output

Trajectory is recorded to `.harness/trajectories/<session>.jsonl`:

```json
{
  "step_number": 1,
  "timestamp": "2026-05-14T10:00:00",
  "state": "INDEX",
  "action": "scanning_project",
  "tool_calls": [...],
  "duration_ms": 150.5
}
```

## Testing

```bash
python3 -m pytest tests/ -v
```

## Project Structure

```
harness/
├── __init__.py
├── schemas.py        # Pydantic models
├── state.py          # S: Bug tracking + snapshots
├── tools.py          # T: Tool registry + base class
├── context.py        # C: Context management
├── lifecycle.py      # L: Hooks
├── evaluation.py     # V: Trajectory recording
├── execution.py      # E: State machine
├── core.py           # H: Component assembly
├── cli.py            # CLI interface
└── domain/
    ├── tools.py      # Concrete tools
    └── prompts.py    # LLM prompts
samples/
├── buggy_server.py   # Target file with 8 bugs
└── test_server.py    # Test suite
tests/
├── test_state_machine.py
├── test_fix_rollback.py
├── test_commit_atomicity.py
└── test_e2e.py
```

## Key Design Decisions

1. **Explicit State Machine**: Uses `match/case` for all transitions, no `while True` + if chains
2. **Nested Fix Loop**: VERIFY failure returns to ANALYZE (not LOCATE) for iterative refinement
3. **Bug-Level Snapshots**: Each bug gets independent snapshot/rollback capability
4. **OpenAI-Compatible API**: Uses `openai` SDK with configurable base URL
5. **Pydantic Validation**: All tool I/O validated at registration time

## Next Steps

1. Add MCP integration for richer tool ecosystem
2. Implement parallel bug fixing for independent bugs
3. Add support for multi-file bugs
4. Integrate with CI/CD pipelines
