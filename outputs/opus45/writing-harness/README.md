# Short Story Writing Harness

A structured agent harness implementing the **H = (E, T, C, S, L, V)** formalism for generating psychological thriller short stories in the style of Poe's "The Tell-Tale Heart".

## Architecture

This harness implements the six-component framework from Meng et al. (2026):

| Component | Module | Description |
|-----------|--------|-------------|
| **E** Execution Loop | `execution.py` | Explicit state machine with match-based transitions |
| **T** Tool Registry | `tools.py` | Pydantic schema validation, structured exceptions |
| **C** Context Manager | `context.py` | Compression, retrieval, priority interfaces |
| **S** State Store | `state.py` | SQLite backend with commit/recover/snapshot |
| **L** Lifecycle Hooks | `lifecycle.py` | Pre/post hook bus, approval gates, audit logging |
| **V** Evaluation Interface | `evaluation.py` | V3-level JSONL trajectory recording |

## Quick Start

### 1. Install Dependencies

```bash
pip install pydantic openai rich
```

### 2. Set Environment Variables

```bash
export OPENAI_BASE_URL=http://127.0.0.1:3457/v1
export OPENAI_API_KEY=your-api-key
export MODEL_NAME=gpt-4
```

### 3. Run the Example

```bash
# Interactive mode with approval prompts
python example.py

# Auto-approve all LLM calls
python example.py --auto-approve
```

### 4. Use the CLI

```bash
# REPL mode
python -m harness.cli

# Single task
python -m harness.cli "Your task description here"

# Commands
/help       - Show available commands
/diff       - Compare output with sample
/trajectory - Show trajectory file path
/status     - Show current session state
/resume <id> - Resume a previous session
```

## Project Structure

```
harness/
├── __init__.py
├── schemas.py        # Pydantic models (states, events, specs)
├── state.py          # S: StateStore + SQLite
├── tools.py          # T: ToolRegistry + base classes
├── context.py        # C: ContextManager
├── lifecycle.py      # L: HookManager
├── evaluation.py     # V: TrajectoryRecorder
├── execution.py      # E: ExecutionLoop state machine
├── core.py           # Harness aggregation class
├── cli.py            # CLI interface
└── domain/
    ├── tools.py      # Writing-specific tools
    └── prompts.py    # LLM prompt templates

samples/
└── the_tell_tale_heart.txt   # Reference sample (Poe)

tests/
├── test_state_machine.py     # E safety + liveness tests
├── test_recovery.py          # S crash recovery tests
├── test_hooks.py             # L decoupling tests
├── test_imagery_consistency.py # C imagery table tests
└── test_e2e.py               # Full pipeline tests
```

## State Machine

The execution loop follows this state graph:

```
INIT → PARSE_SPEC → NARRATOR_VOICE → PLOT_OUTLINE → SCENE_OUTLINE
                                                          ↓
                    ┌─────────────────────────────── DRAFT_SCENE ←┐
                    │                                      │      │
                    ↓                                      ↓      │
              CONSISTENCY_CHECK ──[failed]─────────────────┘      │
                    │                                             │
                    │ [passed]                                    │
                    ↓                                             │
              STYLE_REVISION                                      │
                    │                                             │
                    ↓                                             │
              FINAL_ASSEMBLY                                      │
                    │                                             │
                    ↓                                             │
                COMPLETE                                          │
                                                                  │
    All states can transition to ERROR or SUSPENDED ──────────────┘
```

## Seven-Beat Narrative Structure

The harness generates stories following a seven-beat structure:

1. **Obsession Establishment** (~10%): Introduce narrator and obsession object
2. **Delay/Stalking Period** (~25%): Build tension through repeated approach-and-wait
3. **Trigger Event** (~5%): Break the pattern, force action
4. **Climax** (~15%): The main event (murder/confrontation)
5. **Concealment** (~15%): Hide evidence, believe in success
6. **External Pressure** (~15%): Outside force tests the narrator
7. **Breakdown/Confession** (~15%): Sensory signal overwhelms, narrator cracks

## Running Tests

```bash
pip install pytest

# Run all tests
pytest tests/

# Run specific test files
pytest tests/test_state_machine.py -v
pytest tests/test_recovery.py -v
pytest tests/test_hooks.py -v
pytest tests/test_imagery_consistency.py -v
pytest tests/test_e2e.py -v
```

## Sample Comparison

The `/diff` command compares generated output against the reference sample across three dimensions:

- **Structure**: Seven-beat coverage, beat proportions, pacing
- **Style**: Dash/exclamation density, reader address frequency, repetition
- **Imagery**: Obsession object consistency, metaphor chain, sensory signals

## Design Decisions

### C Layer: Truncation-based compression
Narrator voice and imagery table are pinned and always survive compression. Scene history is compressed by recency. This ensures stylistic consistency while managing context window limits.

### S Layer: Per-scene snapshots
Snapshots are created after each scene draft, enabling recovery to any scene boundary. This balances recovery granularity against storage overhead.

### T Layer: Approval for LLM calls
All tools that invoke the LLM require approval by default. This enables human-in-the-loop control over generation costs and quality.

### E Layer: Match-based transitions
The state machine uses explicit `match` statements rather than `if/elif` chains. This ensures all state transitions are explicitly defined and auditable.

### V Layer: JSONL streaming
Trajectory entries are appended to JSONL files as they occur, enabling real-time monitoring and post-hoc analysis without losing data on crashes.

## Known Limitations

- Style revision tool currently returns input unchanged when parsing fails
- Consistency check uses heuristic LLM-based analysis, may miss subtle issues
- No streaming token output in current implementation
- Context compression doesn't use semantic similarity, only priority/recency

## Next Steps for Production

1. Add semantic search for context retrieval (embedding-based)
2. Implement streaming output for better UX
3. Add retry logic with exponential backoff for LLM calls
4. Create evaluation metrics beyond sample comparison
5. Add support for multiple genre templates beyond psychological thriller
