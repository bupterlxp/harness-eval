"""
Domain Tools for Data Analysis

Implements analysis-specific tools:
- Data loaders
- Statistics calculators
- Visualizers (chart generators)
- Data validators
- Report generators
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from harness.schemas import (
    AnomalyRecord,
    AnalysisState,
    ChartRecord,
    Insight,
    ValidationResult,
)
from harness.tools import ToolRegistry

plt.rcParams["font.sans-serif"] = ["SimHei", "DejaVu Sans", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

domain_registry = ToolRegistry()


@domain_registry.register(
    name="load_csv",
    description="Load CSV file into DataFrame",
    category="data",
    output_schema={"df": "DataFrame"},
)
def load_csv(filepath: str, encoding: str = "utf-8") -> pd.DataFrame:
    """Load a CSV file into a pandas DataFrame."""
    df = pd.read_csv(filepath, encoding=encoding)
    return df


@domain_registry.register(
    name="check_data_quality",
    description="Check data quality and detect anomalies",
    category="validation",
    requires_dataframe=True,
)
def check_data_quality(df: pd.DataFrame) -> tuple[dict[str, Any], list[AnomalyRecord]]:
    """Check data quality and return quality report with anomalies."""
    report = {
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": list(df.columns),
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "missing_values": {},
        "missing_percentages": {},
    }

    for col in df.columns:
        missing = df[col].isna().sum()
        report["missing_values"][col] = int(missing)
        report["missing_percentages"][col] = (missing / len(df)) * 100

    anomalies = []

    for col in df.columns:
        missing_mask = df[col].isna()
        if missing_mask.any():
            anomalies.append(AnomalyRecord(
                anomaly_id=str(uuid.uuid4())[:8],
                column=col,
                row_indices=list(df[missing_mask].index),
                anomaly_type="missing",
                description=f"Missing values in column '{col}'",
                severity="warning",
            ))

    if "discount" in df.columns:
        invalid_discount = df[df["discount"] > 1.0]
        if len(invalid_discount) > 0:
            anomalies.append(AnomalyRecord(
                anomaly_id=str(uuid.uuid4())[:8],
                column="discount",
                row_indices=list(invalid_discount.index),
                anomaly_type="invalid",
                description=f"Discount values > 1.0 (>100%): {len(invalid_discount)} rows",
                severity="error",
                handling_strategy="exclude_from_analysis",
            ))

    if "quantity" in df.columns:
        q99 = df["quantity"].quantile(0.99)
        threshold = max(q99 * 3, 200)
        outliers = df[df["quantity"] > threshold]
        if len(outliers) > 0:
            anomalies.append(AnomalyRecord(
                anomaly_id=str(uuid.uuid4())[:8],
                column="quantity",
                row_indices=list(outliers.index),
                anomaly_type="outlier",
                description=f"Extreme quantity values (>{threshold:.0f}): {len(outliers)} rows",
                severity="warning",
                handling_strategy="flag_for_review",
            ))

    return report, anomalies


@domain_registry.register(
    name="clean_data",
    description="Clean data by handling missing values and anomalies",
    category="data",
    requires_dataframe=True,
)
def clean_data(
    df: pd.DataFrame,
    anomalies: list[AnomalyRecord],
    exclude_invalid_discount: bool = True,
    exclude_extreme_quantity: bool = False,
) -> tuple[pd.DataFrame, list[str]]:
    """Clean data and return cleaned DataFrame with cleaning log."""
    df_clean = df.copy()
    cleaning_log = []

    if "date" in df_clean.columns:
        df_clean["date"] = pd.to_datetime(df_clean["date"])
        cleaning_log.append("Converted 'date' to datetime")

    if "discount" in df_clean.columns:
        discount_missing = df_clean["discount"].isna()
        if discount_missing.any():
            df_clean.loc[discount_missing, "discount"] = 0.0
            cleaning_log.append(f"Filled {discount_missing.sum()} missing discount values with 0.0")

    if exclude_invalid_discount and "discount" in df_clean.columns:
        invalid_mask = df_clean["discount"] > 1.0
        if invalid_mask.any():
            df_clean = df_clean[~invalid_mask]
            cleaning_log.append(f"Excluded {invalid_mask.sum()} rows with discount > 1.0")

    if exclude_extreme_quantity and "quantity" in df_clean.columns:
        q99 = df["quantity"].quantile(0.99)
        threshold = max(q99 * 3, 200)
        extreme_mask = df_clean["quantity"] > threshold
        if extreme_mask.any():
            df_clean = df_clean[~extreme_mask]
            cleaning_log.append(f"Excluded {extreme_mask.sum()} rows with extreme quantities")

    if all(col in df_clean.columns for col in ["quantity", "unit_price", "discount"]):
        df_clean["sales_amount"] = (
            df_clean["quantity"] * df_clean["unit_price"] * (1 - df_clean["discount"])
        )
        cleaning_log.append("Computed 'sales_amount' = quantity * unit_price * (1 - discount)")

    df_clean = df_clean.reset_index(drop=True)
    cleaning_log.append(f"Final cleaned data: {len(df_clean)} rows")

    return df_clean, cleaning_log


@domain_registry.register(
    name="compute_basic_stats",
    description="Compute basic statistics for DataFrame",
    category="statistics",
    requires_dataframe=True,
)
def compute_basic_stats(df: pd.DataFrame) -> dict[str, Any]:
    """Compute basic statistics for the DataFrame."""
    stats = {
        "row_count": len(df),
        "column_count": len(df.columns),
        "numeric_summary": {},
        "categorical_summary": {},
    }

    numeric_cols = df.select_dtypes(include=[np.number]).columns
    for col in numeric_cols:
        stats["numeric_summary"][col] = {
            "mean": float(df[col].mean()),
            "std": float(df[col].std()),
            "min": float(df[col].min()),
            "max": float(df[col].max()),
            "median": float(df[col].median()),
            "q25": float(df[col].quantile(0.25)),
            "q75": float(df[col].quantile(0.75)),
        }

    categorical_cols = df.select_dtypes(include=["object", "category"]).columns
    for col in categorical_cols:
        value_counts = df[col].value_counts()
        stats["categorical_summary"][col] = {
            "unique_count": int(df[col].nunique()),
            "top_values": value_counts.head(5).to_dict(),
            "mode": str(df[col].mode().iloc[0]) if len(df[col].mode()) > 0 else None,
        }

    return stats


@domain_registry.register(
    name="analyze_sales_trend",
    description="Analyze sales trend over time",
    category="analysis",
    requires_dataframe=True,
)
def analyze_sales_trend(
    df: pd.DataFrame,
    date_col: str = "date",
    sales_col: str = "sales_amount",
    freq: str = "D",
) -> dict[str, Any]:
    """Analyze sales trend over time."""
    df_copy = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(df_copy[date_col]):
        df_copy[date_col] = pd.to_datetime(df_copy[date_col])

    daily_sales = df_copy.groupby(df_copy[date_col].dt.date)[sales_col].sum()

    analysis = {
        "period_start": str(daily_sales.index.min()),
        "period_end": str(daily_sales.index.max()),
        "total_days": len(daily_sales),
        "total_sales": float(daily_sales.sum()),
        "daily_average": float(daily_sales.mean()),
        "daily_std": float(daily_sales.std()),
        "max_day": {
            "date": str(daily_sales.idxmax()),
            "sales": float(daily_sales.max()),
        },
        "min_day": {
            "date": str(daily_sales.idxmin()),
            "sales": float(daily_sales.min()),
        },
        "daily_series": {str(k): float(v) for k, v in daily_sales.items()},
    }

    weekly_sales = df_copy.groupby(df_copy[date_col].dt.isocalendar().week)[sales_col].sum()
    analysis["weekly_average"] = float(weekly_sales.mean())

    return analysis


@domain_registry.register(
    name="analyze_by_region",
    description="Analyze sales by region",
    category="analysis",
    requires_dataframe=True,
)
def analyze_by_region(
    df: pd.DataFrame,
    region_col: str = "region",
    sales_col: str = "sales_amount",
) -> dict[str, Any]:
    """Analyze sales by region."""
    df_valid = df[df[region_col].notna()].copy()

    region_sales = df_valid.groupby(region_col)[sales_col].sum().sort_values(ascending=False)
    region_count = df_valid.groupby(region_col).size()
    region_avg_order = df_valid.groupby(region_col)[sales_col].mean()

    total_sales = region_sales.sum()

    analysis = {
        "total_sales": float(total_sales),
        "region_count": len(region_sales),
        "regions": {},
        "ranking": list(region_sales.index),
        "top_region": str(region_sales.index[0]),
        "bottom_region": str(region_sales.index[-1]),
    }

    for region in region_sales.index:
        analysis["regions"][region] = {
            "sales": float(region_sales[region]),
            "share": float(region_sales[region] / total_sales * 100),
            "transaction_count": int(region_count[region]),
            "avg_order_value": float(region_avg_order[region]),
        }

    return analysis


@domain_registry.register(
    name="analyze_by_category",
    description="Analyze sales by product category",
    category="analysis",
    requires_dataframe=True,
)
def analyze_by_category(
    df: pd.DataFrame,
    category_col: str = "category",
    sales_col: str = "sales_amount",
    discount_col: str = "discount",
    region_col: str = "region",
    product_col: str = "product",
) -> dict[str, Any]:
    """Analyze sales by product category."""
    category_sales = df.groupby(category_col)[sales_col].sum().sort_values(ascending=False)
    category_discount = df.groupby(category_col)[discount_col].mean()
    category_count = df.groupby(category_col).size()

    total_sales = category_sales.sum()

    analysis = {
        "total_sales": float(total_sales),
        "category_count": len(category_sales),
        "categories": {},
        "ranking": list(category_sales.index),
    }

    for cat in category_sales.index:
        cat_df = df[df[category_col] == cat]

        top_products = (
            cat_df.groupby(product_col)[sales_col]
            .sum()
            .sort_values(ascending=False)
            .head(3)
        )

        analysis["categories"][cat] = {
            "sales": float(category_sales[cat]),
            "share": float(category_sales[cat] / total_sales * 100),
            "avg_discount": float(category_discount[cat]),
            "transaction_count": int(category_count[cat]),
            "top_products": {str(k): float(v) for k, v in top_products.items()},
        }

    df_valid = df[df[region_col].notna()].copy()
    cross_tab = df_valid.groupby([category_col, region_col])[sales_col].sum().unstack(fill_value=0)
    analysis["category_region_matrix"] = cross_tab.to_dict()

    return analysis


@domain_registry.register(
    name="analyze_by_channel",
    description="Analyze sales by channel",
    category="analysis",
    requires_dataframe=True,
)
def analyze_by_channel(
    df: pd.DataFrame,
    channel_col: str = "channel",
    sales_col: str = "sales_amount",
    discount_col: str = "discount",
    category_col: str = "category",
) -> dict[str, Any]:
    """Analyze sales by channel."""
    channel_sales = df.groupby(channel_col)[sales_col].sum()
    channel_discount = df.groupby(channel_col)[discount_col].mean()
    channel_count = df.groupby(channel_col).size()

    total_sales = channel_sales.sum()

    analysis = {
        "total_sales": float(total_sales),
        "channels": {},
    }

    for channel in channel_sales.index:
        channel_df = df[df[channel_col] == channel]
        category_breakdown = (
            channel_df.groupby(category_col)[sales_col]
            .sum()
            .sort_values(ascending=False)
        )

        analysis["channels"][channel] = {
            "sales": float(channel_sales[channel]),
            "share": float(channel_sales[channel] / total_sales * 100),
            "avg_discount": float(channel_discount[channel]),
            "transaction_count": int(channel_count[channel]),
            "category_breakdown": {str(k): float(v) for k, v in category_breakdown.items()},
        }

    return analysis


@domain_registry.register(
    name="generate_line_chart",
    description="Generate a line chart",
    category="visualization",
    produces_chart=True,
)
def generate_line_chart(
    data: dict[str, float],
    title: str,
    xlabel: str,
    ylabel: str,
    output_dir: Path | str,
    highlight_max: bool = True,
    highlight_min: bool = True,
    figsize: tuple[int, int] = (12, 6),
) -> ChartRecord:
    """Generate a line chart and save to file."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    chart_id = str(uuid.uuid4())[:8]
    filename = f"line_{chart_id}.png"
    filepath = output_dir / filename

    fig, ax = plt.subplots(figsize=figsize)

    x = list(data.keys())
    y = list(data.values())

    ax.plot(x, y, marker="o", linewidth=2, markersize=4)

    if highlight_max and y:
        max_idx = y.index(max(y))
        ax.scatter([x[max_idx]], [y[max_idx]], color="red", s=100, zorder=5)
        ax.annotate(
            f"Max: {y[max_idx]:,.0f}",
            (x[max_idx], y[max_idx]),
            textcoords="offset points",
            xytext=(0, 10),
            ha="center",
            fontsize=9,
        )

    if highlight_min and y:
        min_idx = y.index(min(y))
        ax.scatter([x[min_idx]], [y[min_idx]], color="green", s=100, zorder=5)
        ax.annotate(
            f"Min: {y[min_idx]:,.0f}",
            (x[min_idx], y[min_idx]),
            textcoords="offset points",
            xytext=(0, -15),
            ha="center",
            fontsize=9,
        )

    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_xlabel(xlabel, fontsize=11)
    ax.set_ylabel(ylabel, fontsize=11)
    ax.grid(True, alpha=0.3)

    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)

    return ChartRecord(
        chart_id=chart_id,
        chart_type="line",
        title=title,
        file_path=str(filepath),
        step_number=0,
        state=AnalysisState.TREND,
        x_label=xlabel,
        y_label=ylabel,
        data_summary=f"{len(data)} data points",
    )


@domain_registry.register(
    name="generate_bar_chart",
    description="Generate a bar chart",
    category="visualization",
    produces_chart=True,
)
def generate_bar_chart(
    data: dict[str, float],
    title: str,
    xlabel: str,
    ylabel: str,
    output_dir: Path | str,
    horizontal: bool = False,
    figsize: tuple[int, int] = (10, 6),
    color_palette: str = "viridis",
) -> ChartRecord:
    """Generate a bar chart and save to file."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    chart_id = str(uuid.uuid4())[:8]
    filename = f"bar_{chart_id}.png"
    filepath = output_dir / filename

    fig, ax = plt.subplots(figsize=figsize)

    x = list(data.keys())
    y = list(data.values())
    colors = sns.color_palette(color_palette, len(x))

    if horizontal:
        bars = ax.barh(x, y, color=colors)
        ax.set_xlabel(ylabel)
        ax.set_ylabel(xlabel)
        for bar, val in zip(bars, y):
            ax.text(val, bar.get_y() + bar.get_height() / 2,
                    f" {val:,.0f}", va="center", fontsize=9)
    else:
        bars = ax.bar(x, y, color=colors)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        for bar, val in zip(bars, y):
            ax.text(bar.get_x() + bar.get_width() / 2, val,
                    f"{val:,.0f}", ha="center", va="bottom", fontsize=9)

    ax.set_title(title, fontsize=14, fontweight="bold")
    plt.xticks(rotation=45 if not horizontal else 0, ha="right" if not horizontal else "center")
    plt.tight_layout()
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)

    return ChartRecord(
        chart_id=chart_id,
        chart_type="bar",
        title=title,
        file_path=str(filepath),
        step_number=0,
        state=AnalysisState.REGION,
        x_label=xlabel,
        y_label=ylabel,
        data_summary=f"{len(data)} categories",
    )


@domain_registry.register(
    name="generate_pie_chart",
    description="Generate a pie chart",
    category="visualization",
    produces_chart=True,
)
def generate_pie_chart(
    data: dict[str, float],
    title: str,
    output_dir: Path | str,
    figsize: tuple[int, int] = (10, 8),
) -> ChartRecord:
    """Generate a pie chart and save to file."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    chart_id = str(uuid.uuid4())[:8]
    filename = f"pie_{chart_id}.png"
    filepath = output_dir / filename

    fig, ax = plt.subplots(figsize=figsize)

    labels = list(data.keys())
    values = list(data.values())

    colors = sns.color_palette("husl", len(labels))

    wedges, texts, autotexts = ax.pie(
        values,
        labels=labels,
        autopct="%1.1f%%",
        colors=colors,
        explode=[0.02] * len(values),
        shadow=False,
        startangle=90,
    )

    for autotext in autotexts:
        autotext.set_fontsize(10)

    ax.set_title(title, fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)

    return ChartRecord(
        chart_id=chart_id,
        chart_type="pie",
        title=title,
        file_path=str(filepath),
        step_number=0,
        state=AnalysisState.REGION,
        data_summary=f"{len(data)} slices",
    )


@domain_registry.register(
    name="generate_heatmap",
    description="Generate a heatmap",
    category="visualization",
    produces_chart=True,
)
def generate_heatmap(
    data: dict[str, dict[str, float]],
    title: str,
    output_dir: Path | str,
    xlabel: str = "",
    ylabel: str = "",
    figsize: tuple[int, int] = (12, 8),
    cmap: str = "YlOrRd",
    fmt: str = ".0f",
) -> ChartRecord:
    """Generate a heatmap and save to file."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    chart_id = str(uuid.uuid4())[:8]
    filename = f"heatmap_{chart_id}.png"
    filepath = output_dir / filename

    df = pd.DataFrame(data)

    fig, ax = plt.subplots(figsize=figsize)

    sns.heatmap(
        df,
        annot=True,
        fmt=fmt,
        cmap=cmap,
        ax=ax,
        linewidths=0.5,
        cbar_kws={"label": "Sales Amount"},
    )

    ax.set_title(title, fontsize=14, fontweight="bold")
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=11)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=11)

    plt.tight_layout()
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)

    return ChartRecord(
        chart_id=chart_id,
        chart_type="heatmap",
        title=title,
        file_path=str(filepath),
        step_number=0,
        state=AnalysisState.CATEGORY,
        x_label=xlabel,
        y_label=ylabel,
        data_summary=f"{len(df)} x {len(df.columns)} matrix",
    )


@domain_registry.register(
    name="generate_comparison_chart",
    description="Generate a comparison bar chart",
    category="visualization",
    produces_chart=True,
)
def generate_comparison_chart(
    data: dict[str, dict[str, float]],
    title: str,
    output_dir: Path | str,
    xlabel: str = "",
    ylabel: str = "",
    figsize: tuple[int, int] = (10, 6),
) -> ChartRecord:
    """Generate a grouped bar chart for comparison."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    chart_id = str(uuid.uuid4())[:8]
    filename = f"comparison_{chart_id}.png"
    filepath = output_dir / filename

    df = pd.DataFrame(data)

    fig, ax = plt.subplots(figsize=figsize)
    df.plot(kind="bar", ax=ax, width=0.8)

    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_xlabel(xlabel, fontsize=11)
    ax.set_ylabel(ylabel, fontsize=11)
    ax.legend(title="", loc="upper right")

    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)

    return ChartRecord(
        chart_id=chart_id,
        chart_type="comparison",
        title=title,
        file_path=str(filepath),
        step_number=0,
        state=AnalysisState.CHANNEL,
        x_label=xlabel,
        y_label=ylabel,
        data_summary=f"{len(df)} groups, {len(df.columns)} series",
    )


@domain_registry.register(
    name="validate_calculations",
    description="Validate key calculations",
    category="validation",
)
def validate_calculations(
    df: pd.DataFrame,
    trend_analysis: dict[str, Any],
    region_analysis: dict[str, Any],
    category_analysis: dict[str, Any],
    channel_analysis: dict[str, Any],
) -> list[ValidationResult]:
    """Validate key calculations for consistency."""
    results = []

    expected_total = df["sales_amount"].sum()
    trend_total = trend_analysis.get("total_sales", 0)

    if abs(expected_total - trend_total) > 0.01:
        results.append(ValidationResult(
            check_name="trend_total_match",
            passed=False,
            expected=expected_total,
            actual=trend_total,
            message="Trend analysis total doesn't match DataFrame total",
            severity="error",
        ))
    else:
        results.append(ValidationResult(
            check_name="trend_total_match",
            passed=True,
            expected=expected_total,
            actual=trend_total,
            message="Trend total matches",
        ))

    df_valid = df[df["region"].notna()]
    region_expected = df_valid["sales_amount"].sum()
    region_total = region_analysis.get("total_sales", 0)

    if abs(region_expected - region_total) > 0.01:
        results.append(ValidationResult(
            check_name="region_total_match",
            passed=False,
            expected=region_expected,
            actual=region_total,
            message="Region analysis total doesn't match (excluding null regions)",
            severity="warning",
        ))
    else:
        results.append(ValidationResult(
            check_name="region_total_match",
            passed=True,
            expected=region_expected,
            actual=region_total,
            message="Region total matches",
        ))

    category_total = category_analysis.get("total_sales", 0)
    if abs(expected_total - category_total) > 0.01:
        results.append(ValidationResult(
            check_name="category_total_match",
            passed=False,
            expected=expected_total,
            actual=category_total,
            message="Category analysis total doesn't match",
            severity="error",
        ))
    else:
        results.append(ValidationResult(
            check_name="category_total_match",
            passed=True,
            expected=expected_total,
            actual=category_total,
            message="Category total matches",
        ))

    channel_total = channel_analysis.get("total_sales", 0)
    if abs(expected_total - channel_total) > 0.01:
        results.append(ValidationResult(
            check_name="channel_total_match",
            passed=False,
            expected=expected_total,
            actual=channel_total,
            message="Channel analysis total doesn't match",
            severity="error",
        ))
    else:
        results.append(ValidationResult(
            check_name="channel_total_match",
            passed=True,
            expected=expected_total,
            actual=channel_total,
            message="Channel total matches",
        ))

    return results


@domain_registry.register(
    name="generate_insights",
    description="Generate data-driven insights",
    category="analysis",
)
def generate_insights(
    trend_analysis: dict[str, Any],
    region_analysis: dict[str, Any],
    category_analysis: dict[str, Any],
    channel_analysis: dict[str, Any],
) -> list[Insight]:
    """Generate data-driven insights from analysis results."""
    insights = []

    max_day = trend_analysis.get("max_day", {})
    min_day = trend_analysis.get("min_day", {})
    daily_avg = trend_analysis.get("daily_average", 0)

    if max_day and min_day:
        insights.append(Insight(
            insight_id=str(uuid.uuid4())[:8],
            category="trend",
            title="Sales Peak and Valley",
            description=(
                f"Highest daily sales of {max_day['sales']:,.0f} on {max_day['date']}, "
                f"lowest of {min_day['sales']:,.0f} on {min_day['date']}. "
                f"Daily average is {daily_avg:,.0f}."
            ),
            supporting_data={
                "max_sales": max_day["sales"],
                "max_date": max_day["date"],
                "min_sales": min_day["sales"],
                "min_date": min_day["date"],
                "daily_average": daily_avg,
            },
            confidence=0.95,
            step_number=0,
            state=AnalysisState.REPORT,
            actionable=True,
        ))

    top_region = region_analysis.get("top_region", "")
    bottom_region = region_analysis.get("bottom_region", "")
    regions = region_analysis.get("regions", {})

    if top_region and bottom_region and regions:
        top_data = regions.get(top_region, {})
        bottom_data = regions.get(bottom_region, {})
        insights.append(Insight(
            insight_id=str(uuid.uuid4())[:8],
            category="comparison",
            title="Regional Performance Gap",
            description=(
                f"Top region '{top_region}' accounts for {top_data.get('share', 0):.1f}% of sales "
                f"({top_data.get('sales', 0):,.0f}), while '{bottom_region}' only contributes "
                f"{bottom_data.get('share', 0):.1f}% ({bottom_data.get('sales', 0):,.0f})."
            ),
            supporting_data={
                "top_region": top_region,
                "top_sales": top_data.get("sales", 0),
                "top_share": top_data.get("share", 0),
                "bottom_region": bottom_region,
                "bottom_sales": bottom_data.get("sales", 0),
                "bottom_share": bottom_data.get("share", 0),
            },
            confidence=0.95,
            step_number=0,
            state=AnalysisState.REPORT,
            actionable=True,
        ))

    categories = category_analysis.get("categories", {})
    if categories:
        sorted_cats = sorted(categories.items(), key=lambda x: x[1].get("sales", 0), reverse=True)
        if len(sorted_cats) >= 2:
            top_cat, top_data = sorted_cats[0]
            insights.append(Insight(
                insight_id=str(uuid.uuid4())[:8],
                category="comparison",
                title="Category Dominance",
                description=(
                    f"'{top_cat}' is the leading category with {top_data.get('share', 0):.1f}% "
                    f"of total sales ({top_data.get('sales', 0):,.0f}). "
                    f"Average discount rate: {top_data.get('avg_discount', 0)*100:.1f}%."
                ),
                supporting_data={
                    "top_category": top_cat,
                    "sales": top_data.get("sales", 0),
                    "share": top_data.get("share", 0),
                    "avg_discount": top_data.get("avg_discount", 0),
                },
                confidence=0.95,
                step_number=0,
                state=AnalysisState.REPORT,
                actionable=False,
            ))

    channels = channel_analysis.get("channels", {})
    if channels:
        online = channels.get("线上", {})
        offline = channels.get("线下", {})
        if online and offline:
            insights.append(Insight(
                insight_id=str(uuid.uuid4())[:8],
                category="comparison",
                title="Channel Performance",
                description=(
                    f"Online channel: {online.get('share', 0):.1f}% share ({online.get('sales', 0):,.0f}), "
                    f"avg discount {online.get('avg_discount', 0)*100:.1f}%. "
                    f"Offline channel: {offline.get('share', 0):.1f}% share ({offline.get('sales', 0):,.0f}), "
                    f"avg discount {offline.get('avg_discount', 0)*100:.1f}%."
                ),
                supporting_data={
                    "online_sales": online.get("sales", 0),
                    "online_share": online.get("share", 0),
                    "online_discount": online.get("avg_discount", 0),
                    "offline_sales": offline.get("sales", 0),
                    "offline_share": offline.get("share", 0),
                    "offline_discount": offline.get("avg_discount", 0),
                },
                confidence=0.95,
                step_number=0,
                state=AnalysisState.REPORT,
                actionable=True,
            ))

    return insights


@domain_registry.register(
    name="generate_recommendations",
    description="Generate actionable recommendations",
    category="analysis",
)
def generate_recommendations(insights: list[Insight]) -> list[str]:
    """Generate actionable recommendations based on insights."""
    recommendations = []

    for insight in insights:
        if insight.category == "comparison" and "Regional" in insight.title:
            bottom_region = insight.supporting_data.get("bottom_region", "")
            if bottom_region:
                recommendations.append(
                    f"Consider targeted marketing campaigns in {bottom_region} region "
                    f"to improve its contribution from current {insight.supporting_data.get('bottom_share', 0):.1f}%."
                )

        if insight.category == "comparison" and "Channel" in insight.title:
            online_share = insight.supporting_data.get("online_share", 0)
            offline_share = insight.supporting_data.get("offline_share", 0)
            if online_share > offline_share:
                recommendations.append(
                    "Online channel is performing well. Consider optimizing offline store "
                    "experiences and implementing O2O (Online-to-Offline) strategies."
                )
            else:
                recommendations.append(
                    "Offline channel dominates. Invest in e-commerce capabilities and "
                    "digital marketing to capture more online market share."
                )

    recommendations.append(
        "Implement data quality checks at the point of entry to reduce missing values "
        "and invalid discount rates in future data collection."
    )

    return recommendations[:5]


def get_domain_registry() -> ToolRegistry:
    """Get the domain tool registry."""
    return domain_registry
