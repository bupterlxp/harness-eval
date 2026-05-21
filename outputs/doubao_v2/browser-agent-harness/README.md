# Browser Automation Harness

A general-purpose browser automation harness that can accept Web task descriptions and autonomously complete multi-step operations in browsers.

## Features

- **Modular Architecture**: Six core components as specified: Execution Loop, Tool Registry, Context Manager, State Store, Lifecycle Hooks, and Evaluation Logger
- **LLM-Powered**: Uses OpenAI compatible models for task planning and execution
- **Playwright Integration**: Uses Playwright for reliable browser automation
- **Breakpoint Resumption**: Supports continuing from last successful step
- **Smart Popup Handling**: Automatically detects and handles cookie banners, modals, and dialogs
- **Structured Data Extraction**: Extracts and structures data from web pages
- **Trajectory Logging**: Detailed JSONL logging of all execution steps
- **Screenshot Capture**: Automatic screenshot capture on errors and key steps

## Architecture

The implementation follows the six-component architecture defined in CLAUDE.md:

1. **Execution Loop**: Main driver that coordinates the entire automation process
2. **Tool Registry**: Registry of browser automation tools (navigation, interaction, extraction, etc.)
3. **Context Manager**: Manages browser contexts and compresses page state
4. **State Store**: Persists task state for breakpoint resumption
5. **Lifecycle Hooks**: Handles page events, popups, and automatic cleanup
6. **Evaluation Logger**: Logs execution trajectory in JSONL format

## Installation

```bash
pip install -r requirements.txt
playwright install chromium
```

## Usage

### Basic Usage

```bash
python -m harness -p "Extract all product information from the page" --url "https://example.com/products" --output-dir ./output
```

### With Credentials

```bash
python -m harness -p "Login to the dashboard and extract user data" \
    --url "https://example.com/login" \
    --credentials '{"username": "test@example.com", "password": "secret"}' \
    --output-dir ./output
```

### Options

- `-p, --prompt`: Natural language task description (required)
- `--url`: Target URL to start from
- `--output-dir`: Directory to save results (default: ./output)
- `--max-steps`: Maximum number of steps to execute (default: 50)
- `--credentials`: JSON string of credentials for authentication

## Project Structure

```
harness/
├── __init__.py              # Core TaskSpec and Result definitions
├── __main__.py             # Main entry point
├── execution/              # Execution loop component
│   └── __init__.py
├── tools/                  # Tool registry and implementations
│   └── __init__.py
├── context/                # Context manager and page state
│   └── __init__.py
├── state/                  # State store for breakpoint resumption
│   └── __init__.py
├── lifecycle/              # Page event handlers and popup handling
│   └── __init__.py
└── evaluation/            # Trajectory logging
    └── __init__.py
```

## Technical Stack

- **Python 3.11+**
- **Playwright**: Browser automation
- **OpenAI SDK**: LLM integration
- **Type Hints**: Full type safety

## Configuration

The following environment variables can be used:

- `OPENAI_BASE_URL`: Base URL for OpenAI compatible API
- `OPENAI_API_KEY`: API key for OpenAI compatible service
- `MODEL_NAME`: LLM model to use (default: gpt-3.5-turbo)

## Key Features Explained

### Context Manager

The Context Manager handles browser contexts and compresses page state to avoid sending full DOM/HTML to the LLM. Instead, it provides:
- Accessibility tree summary
- Key elements list
- Basic page metadata

### State Store

The State Store persists task state including:
- Completed steps
- Extracted data
- Current execution position

This allows the harness to resume from the last successful step if interrupted.

### Lifecycle Hooks

Automatically handles:
- Cookie consent banners
- Modal dialogs
- Alert/confirm/prompt dialogs
- Page load waiting
- Network idle detection

### Evaluation Logger

Logs every step in JSONL format with:
- Timestamp
- Step number
- Current URL
- Action performed
- Target element
- Result status
- Screenshot path (if any)
- Error details (if any)

## Testing

```bash
python -m pytest tests/ --co -q
```

## License

MIT