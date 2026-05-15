"""
H - Core Harness

Aggregates all six components:
- E: Execution Loop
- T: Tool Registry
- C: Context Manager
- S: State Store
- L: Lifecycle Hooks
- V: Evaluation Interface

Provides step handlers and unified API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from harness.context import ContextManager
from harness.evaluation import EvaluationInterface
from harness.execution import ExecutionLoop, StepResult
from harness.lifecycle import (
    HookType,
    LifecycleHooks,
    check_discount_validity,
    check_quantity_outliers,
)
from harness.schemas import AnalysisState, ChartRecord, Insight, ValidationResult
from harness.state import ExecutionState
from harness.tools import ToolRegistry

from harness.domain.tools import (
    analyze_by_category,
    analyze_by_channel,
    analyze_by_region,
    analyze_sales_trend,
    check_data_quality,
    clean_data,
    compute_basic_stats,
    generate_bar_chart,
    generate_comparison_chart,
    generate_heatmap,
    generate_insights,
    generate_line_chart,
    generate_pie_chart,
    generate_recommendations,
    get_domain_registry,
    load_csv,
    validate_calculations,
)


@dataclass
class AnalysisConfig:
    """Configuration for analysis."""
    data_file: str
    output_dir: str = "./output"
    analysis_goal: str = ""
    exclude_invalid_discount: bool = True
    exclude_extreme_quantity: bool = False
    required_analyses: list[str] = field(default_factory=lambda: [
        "trend", "region", "category", "channel"
    ])
    sales_formula: str = "quantity * unit_price * (1 - discount)"


class DataAnalysisHarness:
    """
    Main harness for data analysis tasks.

    Integrates all six components (E, T, C, S, L, V) and provides
    a unified API for running analyses.
    """

    def __init__(self, config: AnalysisConfig):
        self.config = config
        self.output_dir = Path(config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.state = ExecutionState(output_dir=self.output_dir)
        self.context = ContextManager()
        self.tools = get_domain_registry()
        self.hooks = LifecycleHooks()
        self.evaluation = EvaluationInterface(output_dir=self.output_dir)

        self.execution = ExecutionLoop(
            state=self.state,
            context=self.context,
            tools=self.tools,
            hooks=self.hooks,
            evaluation=self.evaluation,
        )

        self._register_hooks()
        self._register_handlers()
        self._set_intent()

    def _register_hooks(self) -> None:
        """Register domain-specific hooks."""
        self.hooks.register(HookType.PRE_EXECUTE, "check_discount", check_discount_validity)
        self.hooks.register(HookType.PRE_EXECUTE, "check_quantity", check_quantity_outliers)

    def _register_handlers(self) -> None:
        """Register step handlers for each state."""
        self.execution.register_handler(AnalysisState.INIT, self._handle_init)
        self.execution.register_handler(AnalysisState.LOAD, self._handle_load)
        self.execution.register_handler(AnalysisState.QUALITY_CHECK, self._handle_quality_check)
        self.execution.register_handler(AnalysisState.PREPROCESS, self._handle_preprocess)
        self.execution.register_handler(AnalysisState.EXPLORE, self._handle_explore)
        self.execution.register_handler(AnalysisState.TREND, self._handle_trend)
        self.execution.register_handler(AnalysisState.REGION, self._handle_region)
        self.execution.register_handler(AnalysisState.CATEGORY, self._handle_category)
        self.execution.register_handler(AnalysisState.CHANNEL, self._handle_channel)
        self.execution.register_handler(AnalysisState.VALIDATE, self._handle_validate)
        self.execution.register_handler(AnalysisState.REPORT, self._handle_report)
        self.execution.register_handler(AnalysisState.COMPLETE, self._handle_complete)

    def _set_intent(self) -> None:
        """Set analysis intent from config."""
        self.context.set_intent(
            goal=self.config.analysis_goal,
            data_file=self.config.data_file,
            required_analyses=self.config.required_analyses,
            formulas={"sales_amount": self.config.sales_formula},
        )

    def _handle_init(self, loop: ExecutionLoop, inputs: dict[str, Any]) -> StepResult:
        """Handle INIT state: set up configuration."""
        return StepResult(
            success=True,
            outputs={"config": self.config},
            findings=["Analysis configuration initialized"],
            charts=[],
            insights=[],
            validation_results=[],
        )

    def _handle_load(self, loop: ExecutionLoop, inputs: dict[str, Any]) -> StepResult:
        """Handle LOAD state: load data from CSV."""
        df = load_csv(self.config.data_file)
        self.context.update_data_context(df)

        return StepResult(
            success=True,
            outputs={"df_raw": df},
            findings=[
                f"Loaded {len(df)} rows × {len(df.columns)} columns",
                f"Date range: {df['date'].min()} to {df['date'].max()}",
            ],
            charts=[],
            insights=[],
            validation_results=[],
        )

    def _handle_quality_check(self, loop: ExecutionLoop, inputs: dict[str, Any]) -> StepResult:
        """Handle QUALITY_CHECK state: check data quality."""
        df = inputs["df_raw"]
        quality_report, anomalies = check_data_quality(df)

        findings = [
            f"Total rows: {quality_report['row_count']}",
            f"Columns: {', '.join(quality_report['columns'])}",
        ]

        for col, pct in quality_report["missing_percentages"].items():
            if pct > 0:
                findings.append(f"Missing in '{col}': {pct:.1f}%")

        for anomaly in anomalies:
            findings.append(f"Anomaly [{anomaly.anomaly_type}]: {anomaly.description}")

        return StepResult(
            success=True,
            outputs={"quality_report": quality_report, "anomalies": anomalies},
            findings=findings,
            charts=[],
            insights=[],
            validation_results=[],
        )

    def _handle_preprocess(self, loop: ExecutionLoop, inputs: dict[str, Any]) -> StepResult:
        """Handle PREPROCESS state: clean data and compute derived columns."""
        df = inputs["df_raw"]
        anomalies = inputs["anomalies"]

        df_clean, cleaning_log = clean_data(
            df,
            anomalies,
            exclude_invalid_discount=self.config.exclude_invalid_discount,
            exclude_extreme_quantity=self.config.exclude_extreme_quantity,
        )

        self.context.update_data_context(df_clean)
        for log_entry in cleaning_log:
            self.context.record_cleaning(log_entry)
        self.context.record_derived_column("sales_amount")

        return StepResult(
            success=True,
            outputs={"df_clean": df_clean, "cleaning_log": cleaning_log},
            findings=cleaning_log,
            charts=[],
            insights=[],
            validation_results=[],
        )

    def _handle_explore(self, loop: ExecutionLoop, inputs: dict[str, Any]) -> StepResult:
        """Handle EXPLORE state: compute basic statistics."""
        df = inputs["df_clean"]
        stats = compute_basic_stats(df)

        findings = [
            f"Total sales: {stats['numeric_summary'].get('sales_amount', {}).get('sum', df['sales_amount'].sum()):,.2f}",
            f"Average order value: {stats['numeric_summary'].get('sales_amount', {}).get('mean', df['sales_amount'].mean()):,.2f}",
        ]

        for col, summary in stats.get("categorical_summary", {}).items():
            findings.append(f"Unique {col}: {summary['unique_count']}")

        return StepResult(
            success=True,
            outputs={"exploration_stats": stats},
            findings=findings,
            charts=[],
            insights=[],
            validation_results=[],
        )

    def _handle_trend(self, loop: ExecutionLoop, inputs: dict[str, Any]) -> StepResult:
        """Handle TREND state: analyze sales trends."""
        df = inputs["df_clean"]
        trend_analysis = analyze_sales_trend(df)

        chart = generate_line_chart(
            data=trend_analysis["daily_series"],
            title="Daily Sales Trend (January 2024)",
            xlabel="Date",
            ylabel="Sales Amount",
            output_dir=self.output_dir,
        )
        chart.step_number = self.state.step_number
        chart.state = AnalysisState.TREND

        findings = [
            f"Period: {trend_analysis['period_start']} to {trend_analysis['period_end']}",
            f"Total sales: {trend_analysis['total_sales']:,.2f}",
            f"Daily average: {trend_analysis['daily_average']:,.2f}",
            f"Peak day: {trend_analysis['max_day']['date']} ({trend_analysis['max_day']['sales']:,.2f})",
            f"Lowest day: {trend_analysis['min_day']['date']} ({trend_analysis['min_day']['sales']:,.2f})",
        ]

        return StepResult(
            success=True,
            outputs={"trend_analysis": trend_analysis, "trend_charts": [chart]},
            findings=findings,
            charts=[chart],
            insights=[],
            validation_results=[],
        )

    def _handle_region(self, loop: ExecutionLoop, inputs: dict[str, Any]) -> StepResult:
        """Handle REGION state: analyze regional sales."""
        df = inputs["df_clean"]
        region_analysis = analyze_by_region(df)

        region_sales = {
            r: data["sales"]
            for r, data in region_analysis["regions"].items()
        }
        region_shares = {
            r: data["share"]
            for r, data in region_analysis["regions"].items()
        }

        bar_chart = generate_bar_chart(
            data=region_sales,
            title="Sales by Region",
            xlabel="Region",
            ylabel="Sales Amount",
            output_dir=self.output_dir,
        )
        bar_chart.step_number = self.state.step_number
        bar_chart.state = AnalysisState.REGION

        pie_chart = generate_pie_chart(
            data=region_shares,
            title="Regional Sales Distribution",
            output_dir=self.output_dir,
        )
        pie_chart.step_number = self.state.step_number
        pie_chart.state = AnalysisState.REGION

        findings = [
            f"Top region: {region_analysis['top_region']} "
            f"({region_analysis['regions'][region_analysis['top_region']]['share']:.1f}%)",
            f"Bottom region: {region_analysis['bottom_region']} "
            f"({region_analysis['regions'][region_analysis['bottom_region']]['share']:.1f}%)",
        ]

        return StepResult(
            success=True,
            outputs={"region_analysis": region_analysis, "region_charts": [bar_chart, pie_chart]},
            findings=findings,
            charts=[bar_chart, pie_chart],
            insights=[],
            validation_results=[],
        )

    def _handle_category(self, loop: ExecutionLoop, inputs: dict[str, Any]) -> StepResult:
        """Handle CATEGORY state: analyze category sales."""
        df = inputs["df_clean"]
        category_analysis = analyze_by_category(df)

        category_sales = {
            c: data["sales"]
            for c, data in category_analysis["categories"].items()
        }

        bar_chart = generate_bar_chart(
            data=category_sales,
            title="Sales by Category",
            xlabel="Category",
            ylabel="Sales Amount",
            output_dir=self.output_dir,
        )
        bar_chart.step_number = self.state.step_number
        bar_chart.state = AnalysisState.CATEGORY

        heatmap_chart = generate_heatmap(
            data=category_analysis["category_region_matrix"],
            title="Category × Region Sales Heatmap",
            xlabel="Region",
            ylabel="Category",
            output_dir=self.output_dir,
        )
        heatmap_chart.step_number = self.state.step_number
        heatmap_chart.state = AnalysisState.CATEGORY

        findings = []
        for cat, data in category_analysis["categories"].items():
            findings.append(
                f"{cat}: {data['sales']:,.0f} ({data['share']:.1f}%), "
                f"avg discount {data['avg_discount']*100:.1f}%"
            )

        return StepResult(
            success=True,
            outputs={
                "category_analysis": category_analysis,
                "category_charts": [bar_chart, heatmap_chart]
            },
            findings=findings,
            charts=[bar_chart, heatmap_chart],
            insights=[],
            validation_results=[],
        )

    def _handle_channel(self, loop: ExecutionLoop, inputs: dict[str, Any]) -> StepResult:
        """Handle CHANNEL state: analyze channel sales."""
        df = inputs["df_clean"]
        channel_analysis = analyze_by_channel(df)

        channel_sales = {
            ch: data["sales"]
            for ch, data in channel_analysis["channels"].items()
        }

        comparison_data = {}
        for ch, data in channel_analysis["channels"].items():
            comparison_data[ch] = data["category_breakdown"]

        bar_chart = generate_bar_chart(
            data=channel_sales,
            title="Sales by Channel",
            xlabel="Channel",
            ylabel="Sales Amount",
            output_dir=self.output_dir,
        )
        bar_chart.step_number = self.state.step_number
        bar_chart.state = AnalysisState.CHANNEL

        findings = []
        for ch, data in channel_analysis["channels"].items():
            findings.append(
                f"{ch}: {data['sales']:,.0f} ({data['share']:.1f}%), "
                f"avg discount {data['avg_discount']*100:.1f}%"
            )

        return StepResult(
            success=True,
            outputs={"channel_analysis": channel_analysis, "channel_charts": [bar_chart]},
            findings=findings,
            charts=[bar_chart],
            insights=[],
            validation_results=[],
        )

    def _handle_validate(self, loop: ExecutionLoop, inputs: dict[str, Any]) -> StepResult:
        """Handle VALIDATE state: validate all calculations."""
        df = inputs["df_clean"]
        trend = inputs["trend_analysis"]
        region = inputs["region_analysis"]
        category = inputs["category_analysis"]
        channel = inputs["channel_analysis"]

        validation_results = validate_calculations(df, trend, region, category, channel)

        findings = []
        for result in validation_results:
            status = "✓" if result.passed else "✗"
            findings.append(f"{status} {result.check_name}: {result.message}")

        return StepResult(
            success=all(r.passed or r.severity != "error" for r in validation_results),
            outputs={"validation_results": validation_results},
            findings=findings,
            charts=[],
            insights=[],
            validation_results=validation_results,
        )

    def _handle_report(self, loop: ExecutionLoop, inputs: dict[str, Any]) -> StepResult:
        """Handle REPORT state: generate final report with insights."""
        trend = inputs["trend_analysis"]
        region = inputs["region_analysis"]
        category = inputs["category_analysis"]
        channel = inputs["channel_analysis"]

        insights = generate_insights(trend, region, category, channel)
        recommendations = generate_recommendations(insights)

        report = self._generate_report(
            trend=trend,
            region=region,
            category=category,
            channel=channel,
            insights=insights,
            recommendations=recommendations,
        )

        report_path = self.output_dir / "analysis_report.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)

        findings = [
            f"Generated {len(insights)} insights",
            f"Generated {len(recommendations)} recommendations",
            f"Report saved to: {report_path}",
        ]

        return StepResult(
            success=True,
            outputs={"final_report": report, "insights": insights, "recommendations": recommendations},
            findings=findings,
            charts=[],
            insights=insights,
            validation_results=[],
        )

    def _handle_complete(self, loop: ExecutionLoop, inputs: dict[str, Any]) -> StepResult:
        """Handle COMPLETE state: finalize analysis."""
        return StepResult(
            success=True,
            outputs={},
            findings=["Analysis complete"],
            charts=[],
            insights=[],
            validation_results=[],
        )

    def _generate_report(
        self,
        trend: dict[str, Any],
        region: dict[str, Any],
        category: dict[str, Any],
        channel: dict[str, Any],
        insights: list[Insight],
        recommendations: list[str],
    ) -> str:
        """Generate markdown analysis report."""
        lines = [
            "# Sales Analysis Report",
            "",
            f"**Analysis Period:** {trend['period_start']} to {trend['period_end']}",
            f"**Total Sales:** ¥{trend['total_sales']:,.2f}",
            "",
            "## Executive Summary",
            "",
        ]

        for insight in insights[:3]:
            lines.append(f"- {insight.description}")
        lines.append("")

        lines.extend([
            "## 1. Sales Trend Analysis",
            "",
            f"- **Daily Average:** ¥{trend['daily_average']:,.2f}",
            f"- **Peak Day:** {trend['max_day']['date']} (¥{trend['max_day']['sales']:,.2f})",
            f"- **Lowest Day:** {trend['min_day']['date']} (¥{trend['min_day']['sales']:,.2f})",
            "",
        ])

        lines.extend([
            "## 2. Regional Analysis",
            "",
            f"**Top Region:** {region['top_region']}",
            "",
            "| Region | Sales | Share | Avg Order |",
            "|--------|-------|-------|-----------|",
        ])
        for r in region["ranking"]:
            data = region["regions"][r]
            lines.append(
                f"| {r} | ¥{data['sales']:,.0f} | {data['share']:.1f}% | ¥{data['avg_order_value']:,.0f} |"
            )
        lines.append("")

        lines.extend([
            "## 3. Category Analysis",
            "",
            "| Category | Sales | Share | Avg Discount |",
            "|----------|-------|-------|--------------|",
        ])
        for cat in category["ranking"]:
            data = category["categories"][cat]
            lines.append(
                f"| {cat} | ¥{data['sales']:,.0f} | {data['share']:.1f}% | {data['avg_discount']*100:.1f}% |"
            )
        lines.append("")

        lines.extend([
            "## 4. Channel Analysis",
            "",
            "| Channel | Sales | Share | Avg Discount |",
            "|---------|-------|-------|--------------|",
        ])
        for ch, data in channel["channels"].items():
            lines.append(
                f"| {ch} | ¥{data['sales']:,.0f} | {data['share']:.1f}% | {data['avg_discount']*100:.1f}% |"
            )
        lines.append("")

        lines.extend([
            "## 5. Key Insights",
            "",
        ])
        for i, insight in enumerate(insights, 1):
            lines.append(f"### Insight {i}: {insight.title}")
            lines.append(f"{insight.description}")
            lines.append("")

        lines.extend([
            "## 6. Recommendations",
            "",
        ])
        for i, rec in enumerate(recommendations, 1):
            lines.append(f"{i}. {rec}")
        lines.append("")

        lines.extend([
            "---",
            "*Report generated by Data Analysis Harness*",
        ])

        return "\n".join(lines)

    def run(self) -> list[StepResult]:
        """Run complete analysis."""
        return self.execution.execute_all()

    def run_until(self, state: AnalysisState) -> list[StepResult]:
        """Run analysis until a specific state."""
        return self.execution.execute_until(state)

    def execute_step(self, state: AnalysisState) -> StepResult:
        """Execute a single step."""
        return self.execution.execute_state(state)

    def rollback_to(self, state: AnalysisState) -> bool:
        """Rollback to a specific state."""
        return self.execution.rollback_to(state)

    def rollback_to_step(self, step_number: int) -> bool:
        """Rollback to after a specific step."""
        return self.execution.rollback_to_step(step_number)

    def get_progress(self) -> dict[str, Any]:
        """Get current progress."""
        return self.execution.get_progress()

    def get_context_summary(self) -> str:
        """Get context summary for display."""
        return self.context.get_progress_summary()

    def get_variable(self, name: str) -> Any:
        """Get a variable by name."""
        return self.state.get_variable(name)

    def get_dataframe(self, name: str = "df_clean") -> pd.DataFrame | None:
        """Get a DataFrame variable."""
        return self.state.get_dataframe(name)

    def get_charts(self) -> list[ChartRecord]:
        """Get all generated charts."""
        return self.state.charts

    def get_insights(self) -> list[Insight]:
        """Get all generated insights."""
        return self.state.insights

    def get_trajectory(self) -> str:
        """Get formatted execution trajectory."""
        return self.evaluation.format_trajectory_report()

    def export_script(self, filepath: Path | str) -> str:
        """Export analysis as standalone Python script."""
        filepath = Path(filepath)
        script = self._generate_export_script()
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(script)
        return str(filepath)

    def _generate_export_script(self) -> str:
        """Generate standalone analysis script."""
        lines = [
            '"""',
            "Auto-generated Sales Analysis Script",
            '"""',
            "",
            "import pandas as pd",
            "import matplotlib.pyplot as plt",
            "import seaborn as sns",
            "",
            f'DATA_FILE = "{self.config.data_file}"',
            f'OUTPUT_DIR = "{self.config.output_dir}"',
            "",
            "# Load data",
            'df = pd.read_csv(DATA_FILE)',
            'df["date"] = pd.to_datetime(df["date"])',
            "",
            "# Clean data",
            'df_clean = df[df["discount"] <= 1.0].copy()',
            'df_clean["sales_amount"] = df_clean["quantity"] * df_clean["unit_price"] * (1 - df_clean["discount"])',
            "",
            "# Analysis",
            "print(f'Total Sales: {df_clean[\"sales_amount\"].sum():,.2f}')",
            "print(f'Total Records: {len(df_clean)}')",
            "",
            "# Daily trend",
            'daily_sales = df_clean.groupby(df_clean["date"].dt.date)["sales_amount"].sum()',
            "print(f'Daily Average: {daily_sales.mean():,.2f}')",
            "",
            "# Regional analysis",
            'region_sales = df_clean.groupby("region")["sales_amount"].sum().sort_values(ascending=False)',
            "print('Regional Sales:')",
            "print(region_sales)",
            "",
            "# Category analysis",
            'category_sales = df_clean.groupby("category")["sales_amount"].sum().sort_values(ascending=False)',
            "print('Category Sales:')",
            "print(category_sales)",
            "",
            "# Channel analysis",
            'channel_sales = df_clean.groupby("channel")["sales_amount"].sum()',
            "print('Channel Sales:')",
            "print(channel_sales)",
        ]
        return "\n".join(lines)
