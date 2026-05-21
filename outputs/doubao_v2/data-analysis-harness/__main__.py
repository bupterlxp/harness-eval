#!/usr/bin/env python3
"""
Data Analysis Agent Harness

A generic data analysis harness that accepts data files and analysis requirements,
automatically completes data exploration, statistical analysis, visualization,
and report generation.
"""

import argparse
import json
import os
import sys
import traceback
from typing import List, Dict, Any, Optional
from pathlib import Path

# Import required modules
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns

# Set style for plots
sns.set_style("whitegrid")

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))


def main():
    parser = argparse.ArgumentParser(description="Data Analysis Agent Harness")
    parser.add_argument("-p", "--prompt", required=True, help="Natural language task description")
    parser.add_argument("--output-dir", default="./output", help="Output directory for charts and reports")
    parser.add_argument("--max-steps", type=int, default=20, help="Maximum analysis steps")
    args = parser.parse_args()

    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)

    # Import internal modules
    from harness import execution, tools, context, state, lifecycle, evaluation

    # Initialize components
    tool_registry = tools.ToolRegistry()
    context_manager = context.ContextManager()
    state_store = state.StateStore(args.output_dir)
    lifecycle_hooks = lifecycle.LifecycleHooks()
    evaluator = evaluation.Evaluator()

    # Initialize execution loop
    exec_loop = execution.ExecutionLoop(
        tool_registry=tool_registry,
        context_manager=context_manager,
        state_store=state_store,
        lifecycle_hooks=lifecycle_hooks,
        evaluator=evaluator,
        max_steps=args.max_steps
    )

    # Discover data files in current directory
    data_files = []
    valid_extensions = ['.csv', '.xlsx', '.xls', '.json', '.parquet', '.pq']
    for ext in valid_extensions:
        data_files.extend(list(Path(".").glob(f"*{ext}")))

    # Convert Path objects to strings
    data_files = [str(f) for f in data_files]

    # Run analysis
    try:
        result = exec_loop.run(
            data_files=data_files,
            analysis_goal=args.prompt,
            output_dir=args.output_dir
        )

        # Save result to output directory
        result_path = os.path.join(args.output_dir, "result.json")
        with open(result_path, 'w') as f:
            json.dump(result, f, indent=2, default=str)

        print(f"Analysis completed successfully! Results saved to {result_path}")
        print(f"Report: {result['report_path']}")
        print(f"Script: {result['script_path']}")

    except Exception as e:
        print(f"Analysis failed: {str(e)}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()