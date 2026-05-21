# Code Intelligence Harness

A general-purpose code intelligence agent that can accept software engineering task descriptions and autonomously complete code modifications and validation.

## Overview

This harness implements a complete code intelligence agent that can:
- Accept natural language task descriptions (bug fixes, feature development, refactoring, etc.)
- Autonomously complete code modifications across multiple files
- Validate changes through testing
- Maintain full execution trajectory logs
- Support rollback and recovery

## Architecture

The implementation follows the specified architecture with six independent components:

1. **Execution Loop** - State machine-driven task progression
2. **Tool Registry** - Registered tools for file operations, code search, and execution
3. **Context Manager** - LLM context window management with compression
4. **State Store** - Persistent state management with snapshot/rollback
5. **Lifecycle Hooks** - Boundary event handling and backup/restore
6. **Evaluation** - Structured trajectory logging and reporting

## Quick Start

### Installation

```bash
pip install -e .
```

### Usage

```bash
python -m harness -p "Your natural language task description" --output-dir ./output/
```

## Components

### Execution Loop

The core state machine that drives task execution through the following states:
- INITIALIZED → ANALYZING → PLANNING → EXECUTING → TESTING → VERIFYING → COMPLETED/FAILED

Supports nested cycles and proper error handling with rollback capabilities.

### Tool Registry

Provides access to the following tools:
- File operations: read_file, write_file, edit_file
- Search: search_files, grep, glob
- Execution: execute_command

### Context Manager

Manages LLM context window with automatic compression to prevent overflow.
Supports adding files, code snippets, and search results to context.

### State Store

Persists runtime state and supports:
- Creating snapshots at any point
- Rolling back to previous snapshots
- Tracking file changes for recovery

### Lifecycle Hooks

Handles lifecycle events:
- Task start/end
- Automatic backup before operations
- Rollback on failure
- Cleanup of old backups

### Evaluation

Records full execution trajectory in JSONL format and generates summary reports.

## Requirements

- Python 3.11+
- Dependencies listed in `setup.py`

## Project Structure

```
harness/
├── __init__.py              # Package exports
├── __main__.py              # Main entry point
├── execution/              # Execution loop component
├── tools/                   # Tool registry component
├── context/                 # Context manager component
├── state/                   # State store component
├── lifecycle/               # Lifecycle hooks component
└── evaluation/              # Evaluation component
```

## Validation

To verify the harness implementation:

```bash
# Check importability
python -c "import harness"

# Check component imports
python -c "from harness import execution, tools, context, state, lifecycle, evaluation"

# Check CLI
python -m harness --help

# Check tests
python -m pytest tests/ --co -q
```

## License

MIT