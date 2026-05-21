# Research Agent Harness

A general-purpose deep research harness that accepts research questions, autonomously performs information retrieval, source evaluation, evidence organization, and structured report generation.

## Quick Start

```bash
python -m harness -p "Your research question here" --output-dir ./output/
```

## Architecture

The harness implements six core components as specified:

1. **Execution Loop** - Driver of the research process with explicit state machine
2. **Tool Registry** - Collection of research tools (search, content extraction, evaluation)
3. **Context Manager** - Manages evidence context and fact attribution
4. **State Store** - Persists research progress and maintains state
5. **Lifecycle Hooks** - Handles research boundary control and validation
6. **Evaluation** - Tracks research trajectory and evaluates progress

## Components

### Execution Loop
Drives the research process with explicit state management. Supports multi-hop retrieval with max_hops termination condition.

### Tool Registry
Provides access to research tools including:
- Web search
- Content extraction
- Source credibility evaluation

### Context Manager
Maintains a library of sources and extracted facts, with full attribution tracking.

### State Store
Persists research progress including:
- Source list
- Extracted facts
- Section drafts
- Citation mappings
- Full research trajectory

### Lifecycle Hooks
Implements validation and control:
- Search query deduplication
- URL deduplication
- Evidence sufficiency checking
- Citation integrity validation

### Evaluation
Tracks research trajectory and provides quality metrics:
- Source distribution
- Credibility scoring
- Step-by-step trajectory logging

## Task Specification

```python
{
    "research_questions": list[str],  # Research questions list
    "min_sources": int,               # Minimum sources required (default 10)
    "max_words": int,                 # Maximum report words (default 4000)
    "required_sections": list[str],   # Required report sections
    "max_hops": int,                  # Maximum research hops (default 3)
    "output_dir": str,                # Output directory
    "constraints": list[str],         # Additional constraints
}
```

## Output Format

```python
{
    "status": str,                    # "success" | "partial" | "failed"
    "report_path": str,               # Path to structured report
    "sources": list[{                 # List of used sources
        "id": int,
        "url": str,
        "title": str,
        "credibility": str,           # "high" | "medium" | "low"
    }],
    "citation_integrity": {           # Citation validation results
        "total_citations": int,
        "orphaned": int,
        "unused": int
    },
    "gaps": list[str],                # Unanswered subquestions
    "trajectory": str,                # Path to JSONL trajectory file
}
```

## Development

The project requires Python 3.11+ and uses type hints. Install dependencies:

```bash
pip install openai httpx
```

## Testing

Run validation checks:

```bash
python -c "import harness"
python -c "from harness import execution, tools, context, state, lifecycle, evaluation"
python -m harness --help
```

## License

MIT