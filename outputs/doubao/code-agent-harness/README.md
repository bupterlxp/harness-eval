# Code Agent Harness

A complete agent harness for automated bug fixing in Python projects.

## Overview

This harness implements a state machine-based approach to automated software debugging and repair. It follows the formal specification defined in CLAUDE.md, providing a structured methodology for identifying, prioritizing, and fixing bugs.

## Features

- **State Machine Execution**: Explicit state machine implementation following the specification
- **Tool Registry**: Extensible tool system with file search, editing, test running, and more
- **Context Management**: Smart context handling for source code, test results, and fix history
- **Lifecycle Hooks**: Pre/post hooks for backup, validation, and cleanup
- **Trajectory Recording**: Full execution trajectory logging in JSONL format
- **Bug Tracking**: Comprehensive bug tracking with severity and type classification
- **LLM Integration**: OpenAI-compatible API support for automated analysis

## Architecture

The harness is composed of six core components as defined in the specification:

1. **Execution Loop (E)**: State machine with defined states and transitions
2. **Tool Registry (T)**: Extensible tool system
3. **Context Manager (C)**: Manages source and test context
4. **State Store (S)**: Tracks bugs, progress, and provides snapshot/rollback
5. **Lifecycle Hooks (L)**: Pre/post operation hooks
6. **Evaluation Interface (V)**: JSONL trajectory recording

## Installation

```bash
pip install -e .
```

## Quick Start

### 1. Run existing tests

```bash
agent-harness --run-tests
```

### 2. List identified bugs

```bash
agent-harness --list-bugs
```

### 3. Fix all bugs automatically

```bash
agent-harness --fix-all
```

### 4. View trajectory summary

```bash
agent-harness --show-trajectory
```

## Bug Fix Example

The harness is designed to automatically fix bugs like those in the sample task management server. The 8 known bugs include:

1. Non-ASCII character handling in JSON responses
2. Incorrect logical operator (OR instead of AND) in list filtering
3. Missing ordering in query results
4. SQL injection vulnerability
5. Invalid status values silently corrected
6. Database connection closed before query execution
7. Updated timestamp not maintained on updates
8. Incorrect 404 response for deleted non-existent tasks

## Project Structure

```
harness/
├── __init__.py              # Package initialization
├── __main__.py             # Main entry point
├── core.py                 # Harness aggregation
├── schemas.py              # Pydantic data models
├── state.py                # State management
├── tools.py                # Tool registry and base classes
├── context.py              # Context management
├── lifecycle.py            # Lifecycle hooks and backups
├── evaluation.py           # Trajectory recording
├── execution.py            # State machine implementation
├── cli.py                  # CLI interface
└── domain/
    ├── tools.py            # Domain-specific tools
    └── prompts.py          # Standardized prompts

samples/
├── buggy_server.py         # Buggy sample server
└── test_server.py          # Test suite
```

## Usage with OpenAI API

The harness supports OpenAI-compatible APIs for automated bug analysis:

```bash
export OPENAI_BASE_URL="http://your-api-endpoint/v1"
export OPENAI_API_KEY="your-api-key"
export MODEL_NAME="gpt-3.5-turbo"
agent-harness --fix-all
```

## Development

### Install dependencies

```bash
pip install -e ".[dev]"
```

### Run tests

```bash
pytest tests/
```

### Format code

```bash
black harness/
```

## License

MIT

## References

Based on the formal specification in CLAUDE.md