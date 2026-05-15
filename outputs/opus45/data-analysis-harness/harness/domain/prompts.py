"""
Domain Prompts for Data Analysis

Provides prompt templates for LLM-assisted analysis steps.
Uses OpenAI-compatible API.
"""

from __future__ import annotations

import os
from typing import Any

from openai import OpenAI


def get_llm_client() -> OpenAI:
    """Get OpenAI-compatible LLM client from environment variables."""
    return OpenAI(
        base_url=os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:3457/v1"),
        api_key=os.environ.get("OPENAI_API_KEY", "dummy-key"),
    )


def get_model_name() -> str:
    """Get model name from environment."""
    return os.environ.get("MODEL_NAME", "gpt-4")


SYSTEM_PROMPT = """You are a data analysis assistant. You help analyze sales data and generate insights.

Key responsibilities:
1. Interpret data patterns accurately
2. Provide quantitative insights with specific numbers
3. Generate actionable recommendations
4. Explain findings in clear, business-relevant terms

Always base your analysis on the actual data provided. Never make up numbers."""


QUALITY_CHECK_PROMPT = """Analyze the following data quality report and anomalies:

## Quality Report
{quality_report}

## Detected Anomalies
{anomalies}

Please provide:
1. Summary of data quality issues
2. Recommended handling strategies for each issue
3. Impact assessment on analysis reliability

Format your response as a structured analysis."""


TREND_INTERPRETATION_PROMPT = """Interpret the following sales trend analysis:

## Trend Data
{trend_data}

## Data Context
{data_context}

Please provide:
1. Key trend patterns observed
2. Explanation of peak and valley dates
3. Seasonal or cyclical patterns if any
4. Business implications

Keep your analysis concise and data-driven."""


REGION_INTERPRETATION_PROMPT = """Interpret the following regional sales analysis:

## Regional Data
{region_data}

## Data Context
{data_context}

Please provide:
1. Regional performance ranking analysis
2. Factors that might explain regional differences
3. Recommendations for underperforming regions
4. Strategic implications for sales territory management

Keep your analysis concise and actionable."""


CATEGORY_INTERPRETATION_PROMPT = """Interpret the following category analysis:

## Category Data
{category_data}

## Category-Region Matrix
{matrix_data}

## Data Context
{data_context}

Please provide:
1. Category performance analysis
2. Cross-analysis of categories and regions
3. Product portfolio recommendations
4. Pricing and discount strategy insights

Keep your analysis concise and data-driven."""


CHANNEL_INTERPRETATION_PROMPT = """Interpret the following channel analysis:

## Channel Data
{channel_data}

## Data Context
{data_context}

Please provide:
1. Channel performance comparison
2. Channel-category preferences
3. Omnichannel strategy recommendations
4. Resource allocation suggestions

Keep your analysis concise and actionable."""


FINAL_REPORT_PROMPT = """Generate a comprehensive analysis report based on all findings:

## Analysis Context
{intent_context}

## Key Findings
{findings_summary}

## Insights Generated
{insights}

## Validation Results
{validation_results}

Please generate a professional report including:
1. Executive Summary (3-5 bullet points)
2. Key Findings by Analysis Area
3. Data-Driven Insights (with supporting numbers)
4. Actionable Recommendations (at least 2)
5. Data Quality Notes and Caveats

Format the report in clear sections with headers."""


def call_llm(prompt: str, system_prompt: str = SYSTEM_PROMPT) -> str:
    """Call LLM with given prompt."""
    try:
        client = get_llm_client()
        response = client.chat.completions.create(
            model=get_model_name(),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=2000,
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        return f"[LLM call failed: {e}]"


def interpret_quality_check(quality_report: dict[str, Any], anomalies: list[Any]) -> str:
    """Get LLM interpretation of quality check results."""
    import json
    prompt = QUALITY_CHECK_PROMPT.format(
        quality_report=json.dumps(quality_report, indent=2, ensure_ascii=False),
        anomalies="\n".join(str(a) for a in anomalies),
    )
    return call_llm(prompt)


def interpret_trend(trend_data: dict[str, Any], data_context: str) -> str:
    """Get LLM interpretation of trend analysis."""
    import json
    trend_summary = {k: v for k, v in trend_data.items() if k != "daily_series"}
    prompt = TREND_INTERPRETATION_PROMPT.format(
        trend_data=json.dumps(trend_summary, indent=2, ensure_ascii=False),
        data_context=data_context,
    )
    return call_llm(prompt)


def interpret_region(region_data: dict[str, Any], data_context: str) -> str:
    """Get LLM interpretation of regional analysis."""
    import json
    prompt = REGION_INTERPRETATION_PROMPT.format(
        region_data=json.dumps(region_data, indent=2, ensure_ascii=False),
        data_context=data_context,
    )
    return call_llm(prompt)


def interpret_category(
    category_data: dict[str, Any],
    matrix_data: dict[str, Any],
    data_context: str,
) -> str:
    """Get LLM interpretation of category analysis."""
    import json
    prompt = CATEGORY_INTERPRETATION_PROMPT.format(
        category_data=json.dumps(
            {k: v for k, v in category_data.items() if k != "category_region_matrix"},
            indent=2,
            ensure_ascii=False,
        ),
        matrix_data=json.dumps(matrix_data, indent=2, ensure_ascii=False),
        data_context=data_context,
    )
    return call_llm(prompt)


def interpret_channel(channel_data: dict[str, Any], data_context: str) -> str:
    """Get LLM interpretation of channel analysis."""
    import json
    prompt = CHANNEL_INTERPRETATION_PROMPT.format(
        channel_data=json.dumps(channel_data, indent=2, ensure_ascii=False),
        data_context=data_context,
    )
    return call_llm(prompt)


def generate_final_report(
    intent_context: str,
    findings_summary: str,
    insights: list[Any],
    validation_results: list[Any],
) -> str:
    """Generate final analysis report using LLM."""
    import json
    insights_text = "\n".join(
        f"- [{i.category}] {i.title}: {i.description}"
        for i in insights
    )
    validation_text = "\n".join(
        f"- {r.check_name}: {'PASS' if r.passed else 'FAIL'} - {r.message}"
        for r in validation_results
    )
    prompt = FINAL_REPORT_PROMPT.format(
        intent_context=intent_context,
        findings_summary=findings_summary,
        insights=insights_text,
        validation_results=validation_text,
    )
    return call_llm(prompt)
