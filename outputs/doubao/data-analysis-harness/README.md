# Data Analysis Agent Harness

A comprehensive, stateful data analysis agent harness built for sales data analysis and reporting.

## Features

- **Stateful Execution**: Full state management with snapshot/rollback capabilities
- **Modular Architecture**: Clean separation of concerns with well-defined components
- **Comprehensive Analysis**: Covers all required analysis modules:
  - Data quality assessment
  - Sales trend analysis over time
  - Regional performance comparison
  - Product category analysis
  - Sales channel analysis
  - Business insight generation
- **Visualization**: Built-in plotting tools with matplotlib/seaborn
- **Evaluation Tracking**: Full trajectory tracking and reporting
- **CLI Interface**: Command-line interface for easy interaction

## Architecture

The harness follows the formal specification from CLAUDE.md:

```
harness/
├── __init__.py          # Package initialization
├── schemas.py         # Data structures and dataclasses
├── state.py           # Execution state management
├── tools.py           # Generic tool registry
├── context.py         # Context management (data, history, intent)
├── lifecycle.py       # Pre/post execution hooks
├── evaluation.py      # Trajectory tracking and reporting
├── execution.py       # State machine execution loop
├── core.py            # Main agent API
├── cli.py             # Command-line interface
└── domain/
    ├── tools.py      # Domain-specific analysis tools
    └── prompts.py      # Analysis prompt templates
```

## Quick Start

### Install Dependencies

```bash
pip install pandas numpy matplotlib seaborn
```

### Run a Basic Analysis

```bash
python -m harness.cli analyze samples/sales_data.csv \
    --goal "Sales analysis for January 2024" \
    --requirements "Data overview" "Sales trends" "Regional analysis"
```

### Using the Python API

```python
from harness.core import AgentHarness

# Run standard analysis
results = AgentHarness.run_standard_analysis(
    data_file="samples/sales_data.csv",
    analysis_goal="Sales data analysis",
    requirements=[
        "Data overview and quality checks",
        "Sales trend analysis",
        "Regional sales comparison",
        "Category performance analysis",
        "Channel sales comparison",
        "Key business insights and recommendations"
    ]
)

if results["success"]:
    print("Analysis completed successfully!")
    print(f"Results saved to: {results['save_paths']}")
```

## Key Components

### 1. Execution State Machine

Manages the analysis workflow through defined states:
- `LOAD` - Load input data
- `QUALITY_CHECK` - Data quality assessment
- `PREPROCESS` - Data cleaning and preprocessing
- `EXPLORE` - Exploratory data analysis
- `TREND` - Sales trend analysis
- `REGION` - Regional performance analysis
- `CATEGORY` - Category performance analysis
- `CHANNEL` - Channel performance analysis
- `REPORT` - Generate final report
- `ERROR` - Error handling state

### 2. State Management

Supports snapshot creation and rollback to any previous step:
```python
from harness.state import ExecutionStateManager

manager = ExecutionStateManager()
# Create snapshot
state_id = manager.create_snapshot("after_preprocessing")

# Later rollback
manager.rollback(state_id)
```

### 3. Domain Tools

Pre-built tools for sales data analysis:
- Data loading and validation
- Data quality assessment
- Revenue calculation
- Trend analysis
- Regional/category/channel analysis
- Visualization generation

### 4. Evaluation & Reporting

Tracks full analysis trajectory and generates comprehensive reports:
- JSONL trajectory tracking
- Human-readable summary reports
- Validation reports
- Metrics tracking

## CLI Commands

The harness provides a comprehensive command-line interface:

```
usage: harness.cli [-h] {analyze,continue,preview,plot,info,export} ...

Data Analysis Agent Harness - Perform comprehensive data analysis with stateful execution

optional arguments:
  -h, --help            show this help message and exit

Available commands:
  {analyze,continue,preview,plot,info,export}
                        Available commands
    analyze             Run a new analysis
    continue            Continue from saved state
    preview             Preview data variables
    plot                Generate plots
    info                Show analysis information
    export              Export analysis
```

## Examples

### Analyze Sales Data

```bash
python -m harness.cli analyze samples/sales_data.csv \
    --goal "2024年1月电商销售数据分析" \
    --requirements "数据概览与质量检查" "销售趋势分析" "区域对比分析" "品类分析" "渠道分析" "关键洞察与建议"
```

### Continue from Saved State

```bash
python -m harness.cli continue analysis_results/analysis_state_20240514_123456.json
```

### Preview Data

```bash
python -m harness.cli preview --var main_processed --head 10
```

## Testing

Run all tests:

```bash
# Unit tests
python tests/test_unit.py

# Integration tests
python tests/test_integration.py

# All tests
python tests/test_all.py
```

## Requirements

- Python 3.11+
- pandas
- numpy
- matplotlib
- seaborn

## Key Features

✅ **Full State Management**: Snapshot and rollback to any analysis step
✅ **Comprehensive Analysis**: Covers all 6 required analysis modules
✅ **Data Quality**: Built-in validation and anomaly detection
✅ **Visualization**: Generate multiple chart types
✅ **Evaluation**: Full trajectory tracking and reporting
✅ **CLI Interface**: Easy-to-use command line interface
✅ **Modular Design**: Extensible architecture

## License

MIT License