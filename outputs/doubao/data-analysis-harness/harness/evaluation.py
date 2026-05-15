import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from .schemas import AnalysisStep, ChartRecord, Insight, ValidationResult


class TrajectoryTracker:
    """Tracks and saves the complete analysis trajectory"""

    def __init__(self, output_file: Optional[str] = None):
        self.trajectory: List[Dict[str, Any]] = []
        self.output_file = output_file or f"analysis_trajectory_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"

    def add_step(
        self,
        step_name: str,
        description: str,
        input_shape: tuple[int, int],
        output_shape: tuple[int, int],
        code: Optional[str] = None,
        validation_result: Optional[ValidationResult] = None,
        chart_path: Optional[str] = None,
        insights: Optional[List[Insight]] = None
    ) -> None:
        """Add a step to the trajectory"""
        step_data = {
            "timestamp": datetime.now().isoformat(),
            "step_name": step_name,
            "description": description,
            "input_shape": input_shape,
            "output_shape": output_shape,
            "code_snippet": code,
            "chart_path": chart_path,
            "insights_generated": [{
                "title": i.title,
                "description": i.description,
                "supporting_data": i.supporting_data,
                "confidence": i.confidence
            } for i in insights or []]
        }

        if validation_result:
            step_data["validation"] = {
                "is_valid": validation_result.is_valid,
                "errors": validation_result.errors,
                "warnings": validation_result.warnings,
                "checks_performed": validation_result.checks_performed
            }

        self.trajectory.append(step_data)

    def add_chart(self, chart: ChartRecord) -> None:
        """Add a chart record to trajectory"""
        if self.trajectory:
            last_step = self.trajectory[-1]
            if "charts" not in last_step:
                last_step["charts"] = []
            last_step["charts"].append({
                "name": chart.name,
                "path": chart.path,
                "title": chart.title,
                "data_summary": chart.data_summary
            })

    def add_insight(self, insight: Insight) -> None:
        """Add an insight to the current trajectory step"""
        if self.trajectory:
            last_step = self.trajectory[-1]
            if "insights" not in last_step:
                last_step["insights"] = []
            last_step["insights"].append({
                "title": insight.title,
                "description": insight.description,
                "supporting_data": insight.supporting_data,
                "confidence": insight.confidence
            })

    def save_trajectory(self, filepath: Optional[str] = None) -> str:
        """Save trajectory to JSONL file"""
        save_path = filepath or self.output_file

        with open(save_path, 'w') as f:
            for step in self.trajectory:
                json.dump(step, f, default=str)
                f.write('\n')

        return save_path

    def save_summary(self, filepath: Optional[str] = None) -> str:
        """Save a human-readable summary of the trajectory"""
        save_path = filepath or f"analysis_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"

        summary = ["# Analysis Execution Summary\n",
                   f"Generated: {datetime.now().isoformat()}",
                   f"Total steps: {len(self.trajectory)}",
                   "\n## Step-by-Step Breakdown\n"]

        for i, step in enumerate(self.trajectory, 1):
            summary.append(f"\n### Step {i}: {step.get('step_name', 'Unnamed step')}")
            summary.append(f"\n**Description**: {step.get('description', '')}")
            summary.append(f"**Timestamp**: {step.get('timestamp', '')}")
            summary.append(f"**Input shape**: {step.get('input_shape', 'N/A')}")
            summary.append(f"**Output shape**: {step.get('output_shape', 'N/A')}")

            if step.get('chart_path'):
                summary.append(f"**Chart generated**: {step['chart_path']}")

            if step.get('validation'):
                validation = step['validation']
                summary.append(f"\n**Validation results**:")
                summary.append(f"  Valid: {validation.get('is_valid', False)}")
                summary.append(f"  Checks performed: {validation.get('checks_performed', 0)}")

                if validation.get('errors'):
                    summary.append(f"  Errors: {len(validation['errors'])}")
                    for err in validation['errors']:
                        summary.append(f"    - {err}")

                if validation.get('warnings'):
                    summary.append(f"  Warnings: {len(validation['warnings'])}")
                    for warn in validation['warnings']:
                        summary.append(f"    - {warn}")

            if step.get('code_snippet'):
                summary.append(f"\n**Code executed**:")
                summary.append(f"```python\n{step['code_snippet']}\n```")

            if step.get('insights_generated'):
                summary.append(f"\n**Insights generated**:")
                for insight in step['insights_generated']:
                    summary.append(f"    - {insight['title']}: {insight['description']}")

        with open(save_path, 'w') as f:
            f.write('\n'.join(summary))

        return save_path

    def get_overall_validation(self) -> ValidationResult:
        """Get overall validation result for the entire analysis"""
        overall = ValidationResult(is_valid=True, checks_performed=len(self.trajectory))

        for step in self.trajectory:
            if 'validation' in step:
                val = step['validation']
                overall.errors.extend(val.get('errors', []))
                overall.warnings.extend(val.get('warnings', []))
                overall.checks_performed += val.get('checks_performed', 0)
                overall.is_valid = overall.is_valid and val.get('is_valid', False)

        return overall

    def count_charts(self) -> int:
        """Count total number of charts generated"""
        count = 0
        for step in self.trajectory:
            if 'chart_path' in step and step['chart_path']:
                count += 1
            if 'charts' in step:
                count += len(step['charts'])
        return count

    def count_insights(self) -> int:
        """Count total number of insights generated"""
        count = 0
        for step in self.trajectory:
            if 'insights_generated' in step:
                count += len(step['insights_generated'])
        return count

    def get_step_by_name(self, step_name: str) -> List[Dict[str, Any]]:
        """Find all steps with the given name"""
        return [step for step in self.trajectory if step.get('step_name') == step_name]


class EvaluationReport:
    """Generates comprehensive evaluation reports"""

    def __init__(self, trajectory_tracker: TrajectoryTracker):
        self.tracker = trajectory_tracker

    def generate_validation_report(self) -> str:
        """Generate detailed validation report"""
        overall_val = self.tracker.get_overall_validation()

        report = ["# Analysis Validation Report\n",
                   "="*80,
                   f"Overall Validation: {'✅ PASSED' if overall_val.is_valid else '❌ FAILED'}",
                   f"Total steps analyzed: {len(self.tracker.trajectory)}",
                   f"Total errors found: {len(overall_val.errors)}",
                   f"Total warnings found: {len(overall_val.warnings)}",
                   f"Total validation checks performed: {overall_val.checks_performed}",
                   "\n" + "="*80]

        if overall_val.errors:
            report.append("\n## Errors:\n")
            for i, err in enumerate(overall_val.errors, 1):
                report.append(f"{i}. {err}")

        if overall_val.warnings:
            report.append("\n## Warnings:\n")
            for i, warn in enumerate(overall_val.warnings, 1):
                report.append(f"{i}. {warn}")

        return "\n".join(report)

    def generate_metrics_report(self) -> str:
        """Generate metrics report"""
        total_steps = len(self.tracker.trajectory)
        total_charts = self.tracker.count_charts()
        total_insights = self.tracker.count_insights()

        metrics = ["# Analysis Metrics Report\n",
                   "="*80,
                   "Analysis Metrics:",
                   f"Total analysis steps: {total_steps}",
                   f"Total charts generated: {total_charts}",
                   f"Total insights generated: {total_insights}",
                   "\n" + "="*80]

        if total_steps > 0:
            avg_insights_per_step = total_insights / total_steps
            avg_charts_per_step = total_charts / total_steps
            metrics.append(f"\nAverage insights per step: {avg_insights_per_step:.2f}")
            metrics.append(f"Average charts per step: {avg_charts_per_step:.2f}")

        return "\n".join(metrics)

    def generate_full_report(self) -> str:
        """Generate complete evaluation report"""
        report = ["# Comprehensive Analysis Evaluation Report\n",
                   "="*100,
                   "Generated by: Data Analysis Agent Harness",
                   f"Timestamp: {datetime.now().isoformat()}",
                   "="*100]

        report.append("\n## 1. Validation Summary")
        report.append(self.generate_validation_report())

        report.append("\n## 2. Metrics Summary")
        report.append(self.generate_metrics_report())

        report.append("\n## 3. Trajectory Details")
        report.append(f"Total steps in trajectory: {len(self.tracker.trajectory)}")

        step_types = {}
        for step in self.tracker.trajectory:
            step_name = step.get('step_name', 'Unknown')
            step_types[step_name] = step_types.get(step_name, 0) + 1

        report.append("\n### Step type distribution:")
        for step_type, count in step_types.items():
            report.append(f"  - {step_type}: {count}")

        return "\n".join(report)


def create_evaluation_artifacts(tracker: TrajectoryTracker, output_dir: str = "evaluation") -> Dict[str, str]:
    """Create all evaluation artifacts"""
    os.makedirs(output_dir, exist_ok=True)

    artifacts = {}

    # Save raw trajectory
    trajectory_path = os.path.join(output_dir, "analysis_trajectory.jsonl")
    tracker.save_trajectory(trajectory_path)
    artifacts["trajectory"] = trajectory_path

    # Save summary report
    summary_path = os.path.join(output_dir, "analysis_summary.md")
    tracker.save_summary(summary_path)
    artifacts["summary"] = summary_path

    # Generate full evaluation report
    evaluator = EvaluationReport(tracker)
    full_report_path = os.path.join(output_dir, "full_evaluation_report.md")
    with open(full_report_path, 'w') as f:
        f.write(evaluator.generate_full_report())
    artifacts["full_report"] = full_report_path

    # Generate validation report
    validation_report_path = os.path.join(output_dir, "validation_report.md")
    with open(validation_report_path, 'w') as f:
        f.write(evaluator.generate_validation_report())
    artifacts["validation_report"] = validation_report_path

    return artifacts