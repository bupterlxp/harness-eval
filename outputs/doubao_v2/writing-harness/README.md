# Creative Writing Agent Harness

A generic creative writing harness that accepts writing task specifications and completes the full创作流程 from planning to final manuscript.

## Features

- **Modular Architecture**: Six core components that work together to create a complete writing workflow
- **State Management**: Persistent scene-level state with rollback capabilities
- **Context Management**: Maintains style anchors and prevents consistency drift
- **Tool Registry**: Extensible set of writing tools for planning, generation, and evaluation
- **Lifecycle Hooks**: Customizable hooks for every stage of the writing process
- **Detailed Evaluation**: Full trajectory logging and analysis

## Architecture

The harness implements six core components as specified:

1. **Execution Loop**: Drives the multi-stage创作流程
2. **Tool Registry**: Collection of writing tools with standardized interfaces
3. **Context Manager**: Maintains writing context and prevents drift
4. **State Store**: Persists and manages scene-level state
5. **Lifecycle Hooks**: Controls boundaries and triggers events
6. **Evaluation**: Logs full workflow trajectory for analysis

## Installation

```bash
pip install -e .
```

## Quick Start

```bash
python -m harness -p "Write a psychological thriller story about a detective investigating a mysterious disappearance" --output-dir ./output/
```

## Task Specification

The harness accepts a task specification with the following schema:

```python
{
    "genre": str,               # Genre (e.g., "psychological thriller", "science fiction")
    "premise": str,             # Core premise/story seed
    "target_words": int,        # Target word count
    "pov": str,                 # Narrative perspective
    "style_directives": list[str],  # Style requirements
    "structural_constraints": list[str],  # Structural constraints
    "max_revisions": int,       # Maximum revisions per scene
    "output_dir": str,          # Output directory
}
```

## Components

### Execution Loop
Drives the creative workflow through multiple stages:
1. Planning - Generate story outline
2. Scene Generation - Create each scene individually
3. Consistency Checking - Detect and fix inconsistencies
4. Revision - Revise scenes based on feedback
5. Final Assembly - Combine scenes into complete manuscript

### Context Manager
Maintains writing context and prevents drift:
- Style anchor tracking
- Character and setting consistency
- Plot point tracking
- Previously used elements monitoring

### State Store
Provides persistent storage with:
- Scene-level snapshot and rollback
- Persistent storage across sessions
- Easy access to all scenes
- Manuscript state management

### Tool Registry
Extensible set of tools:
- Outline generation
- Scene generation
- Consistency checking
- Style refinement

### Lifecycle Hooks
Customizable hooks for every stage:
- before_outline/after_outline
- before_scene/after_scene
- before_revision/after_revision
- before_evaluation/after_evaluation
- workflow_started/workflow_completed/workflow_failed

### Evaluation Logger
Comprehensive trajectory logging:
- JSONL format for easy processing
- Full workflow visibility
- Performance metrics
- Analysis tools

## Environment Variables

The harness uses the following environment variables for LLM integration:

- `OPENAI_BASE_URL`: Base URL for OpenAI compatible API
- `OPENAI_API_KEY`: API key for LLM service
- `MODEL_NAME`: LLM model to use (default: gpt-3.5-turbo)

## Development

The project follows Python 3.11+ best practices with type hints and modular design.

### Running Tests

```bash
python -m pytest tests/
```

## License

MIT
