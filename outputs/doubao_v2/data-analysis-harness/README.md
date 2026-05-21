# Data Analysis Agent Harness

A comprehensive data analysis automation tool built according to CLAUDE.md specifications.

## Quick Start

```bash
# Install dependencies
pip install pandas numpy matplotlib seaborn openpyxl pyarrow

# Run analysis with your data files
python -m harness -p "Analyze sales trends and customer behavior" --output-dir ./output/
```

## Features

- **Multiple File Format Support**: CSV, Excel, JSON, Parquet
- **Comprehensive Data Analysis**: Descriptive stats, correlations, trends, distributions
- **Visualization**: Automatic chart generation (heatmaps, line charts, box plots, histograms)
- **Quality Assessment**: Missing values, duplicates, outlier detection
- **State Tracking**: Step-by-step execution with rollback capability
- **Reproducible Results**: Generates full analysis scripts and reports

## Architecture

The implementation follows the exact 6-component architecture specified:

1. **Execution Loop**: Explicit state machine driving the analysis flow
2. **Tool Registry**: Modular tools for different analysis tasks
3. **Context Manager**: Efficient LLM context handling
4. **State Store**: Persists execution state for rollback
5. **Lifecycle Hooks**: Validation at execution boundaries
6. **Evaluation**: Structured trajectory logging

## License

MIT