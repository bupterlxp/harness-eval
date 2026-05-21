"""
Execution Loop component - drives the analysis flow with explicit state machine and step backtracking support
"""

import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path

from .context import ContextManager
from .tools import ToolRegistry, ToolResult
from .lifecycle import LifecycleHooks
from .evaluation import Evaluator


class ExecutionState:
    """Represents the state of the execution loop at any given step"""
    def __init__(self):
        self.step = 0
        self.data: Dict[str, Any] = {}
        self.context: Dict[str, Any] = {}
        self.insights: List[str] = []
        self.charts: List[Dict[str, str]] = []
        self.trajectory: List[Dict[str, Any]] = []
        self.completed = False
        self.failed = False
        self.error_message: Optional[str] = None


class ExecutionLoop:
    """Main execution loop that drives the analysis process"""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        context_manager: ContextManager,
        state_store,
        lifecycle_hooks: LifecycleHooks,
        evaluator: Evaluator,
        max_steps: int = 20
    ):
        # Import locally to avoid circular import
        from .state import StateStore

        self.tool_registry = tool_registry
        self.context_manager = context_manager
        self.state_store = state_store
        self.lifecycle_hooks = lifecycle_hooks
        self.evaluator = evaluator
        self.max_steps = max_steps
        self.current_state: ExecutionState = ExecutionState()
        self._initialize_state()

    def _initialize_state(self) -> None:
        """Initialize the execution state"""
        self.current_state = ExecutionState()
        self.state_store.save_snapshot(self.current_state)

    def run(
        self,
        data_files: List[str],
        analysis_goal: str,
        output_dir: str
    ) -> Dict[str, Any]:
        """Run the full analysis workflow"""
        # Save initial parameters
        self.current_state.data["data_files"] = data_files
        self.current_state.data["analysis_goal"] = analysis_goal
        self.current_state.data["output_dir"] = output_dir

        # Pre-execution lifecycle hooks
        self.lifecycle_hooks.on_before_execution(data_files, analysis_goal, output_dir)

        try:
            # Step 1: Load and validate data
            self._execute_step("load_data", {"data_files": data_files})

            # Step 2: Data quality assessment
            self._execute_step("assess_data_quality", {})

            # Step 3: Exploratory analysis
            self._execute_step("exploratory_analysis", {})

            # Main analysis loop
            while (self.current_state.step < self.max_steps and
                   not self.current_state.completed and
                   not self.current_state.failed):

                self.current_state.step += 1
                self._execute_analysis_step()

            # Post-execution lifecycle hooks
            self.lifecycle_hooks.on_after_execution(
                self.current_state.data,
                self.current_state.insights,
                self.current_state.charts
            )

            # Generate final output
            return self._generate_final_result(output_dir)

        except Exception as e:
            self.current_state.failed = True
            self.current_state.error_message = str(e)
            self.lifecycle_hooks.on_execution_failure(str(e))
            raise

    def _execute_step(self, tool_name: str, params: Dict[str, Any]) -> None:
        """Execute a single tool step"""
        tool = self.tool_registry.get_tool(tool_name)
        if not tool:
            raise ValueError(f"Tool {tool_name} not found in registry")

        # Execute the tool
        result = tool.execute(self.current_state.data, params)

        # Update state
        self.current_state.data.update(result.data_updates)
        self.current_state.context = self.context_manager.update_context(
            self.current_state.context, result.context_updates
        )

        # Add insights if provided
        if result.insights:
            self.current_state.insights.extend(result.insights)

        # Add charts if provided
        if result.charts:
            self.current_state.charts.extend(result.charts)

        # Save trajectory
        self.current_state.trajectory.append({
            "step": self.current_state.step,
            "tool": tool_name,
            "params": params,
            "input_shape": result.input_shape,
            "output_shape": result.output_shape,
            "timestamp": datetime.now().isoformat()
        })

        # Save state snapshot
        self.state_store.save_snapshot(self.current_state)

    def _execute_analysis_step(self) -> None:
        """Execute a single analysis iteration"""
        # This would typically use LLM to decide next step
        # For now, implement a simple heuristic based on analysis goal

        goal = self.current_state.data.get("analysis_goal", "").lower()
        data = self.current_state.data.get("df")

        if data is None:
            self._execute_step("load_data", {})
            return

        # Simple heuristic-based tool selection
        if "correl" in goal or "relationship" in goal:
            self._execute_step("correlation_analysis", {})
        elif "group" in goal or "compare" in goal:
            self._execute_step("grouped_analysis", {})
        elif "trend" in goal or "time" in goal:
            self._execute_step("trend_analysis", {})
        elif "distribut" in goal or "distribution" in goal:
            self._execute_step("distribution_analysis", {})
        elif "summary" in goal or "describe" in goal or "overview" in goal:
            self._execute_step("descriptive_stats", {})
        else:
            # Default to exploratory analysis
            self._execute_step("exploratory_analysis", {})

        # Check if we should complete
        if self.current_state.step >= self.max_steps * 0.75:
            self.current_state.completed = True

    def rollback(self, step: int) -> None:
        """Rollback to a specific step"""
        self.current_state = self.state_store.load_snapshot(step)
        self.context_manager.clear_cache()

    def _generate_final_result(self, output_dir: str) -> Dict[str, Any]:
        """Generate the final result object"""
        # Save trajectory
        trajectory_path = os.path.join(output_dir, "trajectory.jsonl")
        with open(trajectory_path, 'w') as f:
            for entry in self.current_state.trajectory:
                json.dump(entry, f)
                f.write('\n')

        # Generate report
        report_path = os.path.join(output_dir, "analysis_report.md")
        self._generate_report(report_path)

        # Generate analysis script
        script_path = os.path.join(output_dir, "analysis_script.py")
        self._generate_analysis_script(script_path)

        return {
            "status": "success" if not self.current_state.failed and self.current_state.completed else "partial",
            "charts": self.current_state.charts,
            "insights": self.current_state.insights,
            "report_path": report_path,
            "script_path": script_path,
            "trajectory": trajectory_path
        }

    def _generate_report(self, report_path: str) -> None:
        """Generate the analysis report"""
        with open(report_path, 'w') as f:
            f.write(f"# Data Analysis Report\n\n")
            f.write(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(f"## Analysis Goal\n\n{self.current_state.data.get('analysis_goal', 'N/A')}\n\n")

            f.write(f"## Data Files\n\n")
            for file in self.current_state.data.get('data_files', []):
                f.write(f"- {file}\n")
            f.write('\n')

            f.write(f"## Key Insights\n\n")
            for i, insight in enumerate(self.current_state.insights, 1):
                f.write(f"{i}. {insight}\n")
            f.write('\n')

            f.write(f"## Generated Charts\n\n")
            for chart in self.current_state.charts:
                f.write(f"### {chart['description']}\n")
                f.write(f"![{chart['description']}]({os.path.basename(chart['path'])})\n\n")

    def _generate_analysis_script(self, script_path: str) -> None:
        """Generate the reproducible analysis script"""
        with open(script_path, 'w') as f:
            f.write("#!/usr/bin/env python3\n")
            f.write("# Reproducible analysis script\n\n")
            f.write("import pandas as pd\n")
            f.write("import matplotlib.pyplot as plt\n")
            f.write("import seaborn as sns\n")
            f.write("import os\n\n")

            f.write("# Set style\n")
            f.write("sns.set_style('whitegrid')\n\n")

            f.write("# Load data\n")
            f.write(f"data_files = {self.current_state.data.get('data_files', [])}\n")
            f.write("# TODO: Implement data loading logic based on file types\n\n")

            f.write("# Analysis steps\n")
            for entry in self.current_state.trajectory:
                if entry['tool'] not in ['load_data', 'assess_data_quality']:
                    f.write(f"# Step {entry['step']}: {entry['tool']}\n")
                    f.write(f"# Tool params: {json.dumps(entry['params'], indent=2)}\n")
                    f.write("# TODO: Implement this step\n\n")