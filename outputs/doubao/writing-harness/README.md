# Short Story Generation Harness

A complete agent harness for generating short stories following formal specifications, built as part of the CLAUDE.md task.

## Overview

This harness implements the six-component architecture (E, T, C, S, L, V) as defined in Meng et al. (2026) for controlled narrative generation. It is designed to produce short stories that match the structural, stylistic, and thematic patterns of Edgar Allan Poe's *The Tell-Tale Heart*.

## Features

- **Structured Generation Pipeline**: Follows a strict state machine-based execution loop
- **Context Management**: Maintains and compresses context including narrator voice, imagery, and plot outlines
- **Persistence**: SQLite-backed state store with snapshot/restore support
- **Approval Hooks**: Built-in approval mechanism for dangerous operations
- **Evaluation Trajectory**: Detailed JSONL logging of all generation steps
- **CLI Interface**: Interactive REPL and single-task command line modes
- **Sample Comparison**: Built-in tools to compare generated stories against the reference sample

## Installation

```bash
# Install dependencies
pip install openai pydantic python-dotenv

# Set up environment variables
export OPENAI_BASE_URL="http://127.0.0.1:3457/v1"
export OPENAI_API_KEY="your-api-key"
export MODEL_NAME="gpt-3.5-turbo"
```

## Quick Start

### Interactive REPL Mode

```bash
python -m harness.cli
```

Then simply type your story request:

```
体裁:心理惊悚 / 哥特短篇
篇幅:约 2000–2500 词(英文)
视角:第一人称不可靠叙述者
核心张力:叙述者向读者倾诉自己策划并实施的一桩谋杀,并坚称自己神志清醒
```

### Single Task Mode

```bash
python -m harness.cli "你的故事任务描述" --output my_story.txt
```

## Project Structure

```
harness/
├── __init__.py              # Package initialization
├── schemas.py               # Pydantic models and data structures
├── state.py                 # State store with SQLite persistence
├── context.py               # Context manager with compression
├── tools.py                 # Tool registry and base tool classes
├── lifecycle.py             # Hook management and approval system
├── evaluation.py            # Trajectory recording and evaluation
├── execution.py             # State machine execution loop
├── core.py                  # Main harness class aggregating all components
├── cli.py                   # CLI interface
└── domain/
    ├── __init__.py          # Domain package initialization
    ├── tools.py             # Domain-specific writing tools
    └── prompts.py           # Prompt templates

samples/
└── the_tell_tale_heart.txt   # Reference sample story

tests/
└── test_harness.py         # Test suite

example.py                  # Usage examples
README.md                   # This file
```

## Core Components

### E: Execution Loop (`execution.py`)

State machine-based execution loop that follows the expected trajectory:
1. Parse task specification
2. Generate narrator profile
3. Create plot outline
4. Generate scene-level outline
5. Draft scenes one by one
6. Perform consistency checks
7. Revise style
8. Assemble final manuscript

### T: Tool Registry (`tools.py`)

Extensible tool registry with domain-specific tools:
- `generate_narrator_profile`: Creates narrator voice profile
- `generate_plot_outline`: Generates structured plot outline
- `generate_scene_outline`: Breaks plot into scenes
- `draft_scene`: Drafts individual scenes
- `check_consistency`: Validates imagery, timeline, and constraints
- `revise_style`: Applies style requirements
- `assemble_final_manuscript`: Combines scenes into final story
- `compare_to_sample`: Compares against reference sample

### C: Context Manager (`context.py`)

Manages all context including:
- Narrator voice profile
- Established imagery table
- Plot outline and scene history
- Task specifications and style requirements

Built-in context compression and retrieval strategies.

### S: State Store (`state.py`)

SQLite-backed persistence with:
- Session management
- State snapshots
- Full trajectory logging
- Crash recovery support

### L: Lifecycle Hooks (`lifecycle.py`)

Event-driven hook system with:
- Tool call/result hooks
- Pre/post generation hooks
- State save/restore hooks
- Approval request system for dangerous operations

### V: Evaluation Interface (`evaluation.py`)

Generates detailed V3-format trajectory logs in JSONL format, including:
- Timestamped state transitions
- Context snapshots
- Tool call and result data
- Full execution history

## CLI Commands

The interactive REPL supports the following commands:

- `/clear`: Clear current session context
- `/resume <session_id>`: Resume a previous session
- `/trajectory`: Show full generation trajectory
- `/diff`: Compare current story to the reference sample
- `help`, `?`: Show help
- `exit`, `quit`: Exit the program

## Example Usage

```python
from harness import Harness, TaskSpec, StoryGenre, Perspective

# Create harness
harness = Harness()

# Define task
 task_spec = TaskSpec(
    genre=[StoryGenre.PSYCHOLOGICAL_THRILLER, StoryGenre.GOTHIC],
    length_words=(2000, 2500),
    perspective=Perspective.FIRST_PERSON,
    core_tension="叙述者向读者倾诉自己策划并实施的一桩谋杀",
    key_constraints={
        "七夜窥伺": True,
        "听觉意象": True,
        "不可靠叙述者": True
    },
    style_requirements={
        "破折号": True,
        "感叹号": True,
        "直接呼告读者": True
    }
)

# Run
session_info = harness.create_session(task_spec)
result = harness.run_to_completion()

# Save and compare
harness.save_manuscript(result['result']['manuscript'], "story.txt")
comparison = harness.compare_to_sample(result['result']['manuscript'])
```

## Testing

```bash
# Run all tests
pytest tests/test_harness.py -v

# Run with coverage
pytest --cov=harness tests/
```

## Key Design Decisions

1. **State Machine Execution Loop**: Avoids ReAct-style anti-patterns with explicit state transitions
2. **SQLite Persistence**: Simple, file-based persistence without external dependencies
3. **Context Compression**: Automatic context management to prevent token overflow
4. **Approval Hooks**: Explicit user approval for dangerous operations
5. **Modular Components**: Six distinct, decoupled components for maintainability

## License

MIT

## References

- Edgar Allan Poe, *The Tell-Tale Heart* (1843)
- Meng et al. (2026), "Agent Harness for Controlled Narrative Generation"