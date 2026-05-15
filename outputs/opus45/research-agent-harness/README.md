# Research Agent Harness

A deep research and information retrieval agent harness built with a formal six-component architecture.

## Architecture

**H = (E, T, C, S, L, V)**

| Component | Description | Module |
|-----------|-------------|--------|
| **E** | Execution Loop - 10-state research state machine with multi-hop support | `execution.py` |
| **T** | Tool Registry - Rate-limited tool management with retry strategies | `tools.py` |
| **C** | Context Manager - Three-layer context (evidence, outline, query history) | `context.py` |
| **S** | State Store - Evidence, citations, and drafts with full persistence | `state.py` |
| **L** | Lifecycle Hooks - Quality control (dedup, filtering, validation) | `lifecycle.py` |
| **V** | Evaluation Interface - JSONL trajectory logging for traceability | `evaluation.py` |

## Quick Start

```bash
# Install dependencies
pip install httpx openai pytest pytest-asyncio

# Set environment variables
export OPENAI_BASE_URL="http://127.0.0.1:3457/v1"
export OPENAI_API_KEY="your-api-key"
export MODEL_NAME="gpt-4"

# Run the research agent
python -m harness.cli samples/research_questions.json -o output_report.md

# Or run interactively
python -m harness.cli samples/research_questions.json --interactive-only
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `/sources` | List collected sources with reliability ratings |
| `/gaps` | Show information gaps by section |
| `/outline` | Display report outline and completion progress |
| `/verify <claim>` | Cross-validate a claim against evidence |
| `/status` | Show current research status |
| `/help` | Show help message |
| `/quit` | Exit the CLI |

## State Machine

```
DECOMPOSE → SEARCH → EVALUATE → EXTRACT → ORGANIZE → GAP_FILL →
           ↑                                    ↓
           └──────────── (multi-hop) ───────────┘
                                                ↓
CROSS_VALIDATE → DRAFT → CONSISTENCY_CHECK → FINALIZE → COMPLETED
```

## Key Features

1. **Multi-hop Search**: Automatically fills information gaps with up to 3 additional search rounds
2. **Evidence Traceability**: Every fact traces back to its source URL and paragraph
3. **Citation Integrity**: Validates all citation references; no broken links
4. **Source Evaluation**: Ranks sources by reliability (academic > docs > blogs > news)
5. **Context Compression**: Manages evidence with relevance-based demotion
6. **Rate Limiting**: Built-in rate limiting with exponential backoff

## Project Structure

```
harness/
├── __init__.py          # Package exports
├── schemas.py           # Data types (Source, Evidence, Citation, etc.)
├── state.py             # S: State management
├── tools.py             # T: Tool registry
├── context.py           # C: Context management
├── lifecycle.py         # L: Quality hooks
├── evaluation.py        # V: Trajectory logging
├── execution.py         # E: State machine
├── core.py              # H: Six-component aggregation
├── cli.py               # Interactive CLI
└── domain/
    ├── tools.py         # Domain-specific tools
    └── prompts.py       # LLM prompt templates
```

## Running Tests

```bash
python -m pytest tests/ -v
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_BASE_URL` | LLM API endpoint | `http://127.0.0.1:3457/v1` |
| `OPENAI_API_KEY` | API key | `dummy-key` |
| `MODEL_NAME` | Model identifier | `gpt-4` |

## License

MIT
