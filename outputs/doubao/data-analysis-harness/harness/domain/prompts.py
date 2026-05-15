"""
Prompt templates for the data analysis agent
"""

from typing import Dict, List, Optional


ANALYSIS_INTRO_PROMPT = """
You are a data analysis agent performing a comprehensive analysis of sales data.

Analysis Goal: {analysis_goal}
Data File: {data_file}

Please follow the analysis plan and complete all the requested requirements.
"""


DATA_QUALITY_PROMPT = """
## Data Quality Analysis

Please perform a thorough data quality assessment:
1. Count missing values for each column
2. Calculate missing value percentages
3. Detect any anomalies:
   - Discount values outside valid range (0-1)
   - Extremely large quantity values (>100)
   - Negative values in numeric columns
4. Identify any other data quality issues you observe
5. Recommend a data cleaning strategy
"""


TREND_ANALYSIS_PROMPT = """
## Sales Trend Analysis

Please analyze the sales trends over time:
1. Calculate daily total revenue
2. Create a time series plot of daily revenue
3. Identify the dates with highest and lowest revenue
4. Calculate average daily revenue
5. Compare revenue during peak periods (e.g., Jan 1-3, Jan 25-27) with regular days
6. Note any patterns or seasonal effects you observe
"""


REGION_ANALYSIS_PROMPT = """
## Regional Sales Analysis

Please analyze sales performance by region:
1. Calculate total revenue per region
2. Create a bar chart showing regional revenue
3. Create a pie chart showing revenue distribution by region
4. Calculate average revenue per transaction for each region
5. Identify the top-performing and bottom-performing regions
6. Compare the regional performance
"""


CATEGORY_ANALYSIS_PROMPT = """
## Product Category Analysis

Please analyze sales performance by product category:
1. Calculate total revenue per category
2. Create a visualization showing category revenue
3. Calculate average discount rate for each category
4. Create a category × region revenue heatmap
5. Identify the top 3 products in each category by revenue
6. Analyze which categories perform best in which regions
"""


CHANNEL_ANALYSIS_PROMPT = """
## Sales Channel Analysis

Please analyze sales performance between online and offline channels:
1. Calculate total revenue for online vs offline channels
2. Compare the revenue between channels
3. Analyze which categories perform better online vs offline
4. Compare average discount rates between channels
5. Identify any channel-specific patterns
"""


INSIGHT_GENERATION_PROMPT = """
## Key Business Insights and Recommendations

Based on your analysis so far, please provide:
1. At least 3 data-driven business insights with specific numbers to support each
2. At least 2 actionable business recommendations based on the findings
3. A summary of the most important findings
4. Any additional recommendations for improving sales or operations

Please make sure each insight is clearly supported by the data you've analyzed.
"""


FINAL_REPORT_PROMPT = """
## Final Analysis Report

Please compile a complete analysis report including:
1. Executive summary of key findings
2. Data quality assessment and cleaning process
3. Detailed analysis for each of the following areas:
   - Sales trends over time
   - Regional performance
   - Category performance
   - Channel performance
4. Key business insights
5. Actionable recommendations
6. Conclusion

Include all relevant visualizations and reference the charts you generated.
"""


# Full analysis workflow prompt
FULL_ANALYSIS_PROMPT = """
You are a senior data analyst performing a comprehensive sales data analysis.

Please follow this complete workflow:

1. First, load and inspect the data
2. Perform data quality assessment and cleaning
3. Conduct exploratory data analysis
4. Analyze sales trends over time
5. Analyze sales performance by region
6. Analyze sales performance by product category
7. Analyze sales performance by sales channel
8. Generate data-driven business insights
9. Create a comprehensive final report

For each step, provide detailed analysis, visualizations, and interpretations.
Make sure all calculations are accurate and all visualizations are properly labeled.
"""


# Prompt templates for specific validation checks
VALIDATION_PROMPTS: Dict[str, str] = {
    "revenue_calculation": "Please verify that the revenue calculations are correct. For each row, revenue should equal quantity * unit_price * (1 - discount).",
    "data_integrity": "Please check the overall data integrity and identify any remaining issues.",
    "numerical_consistency": "Please verify that all numerical calculations are consistent and accurate."
}


def get_analysis_prompt(requirements: List[str]) -> str:
    """Get full analysis prompt based on requirements"""
    prompt = [ANALYSIS_INTRO_PROMPT]

    for req in requirements:
        if "trend" in req.lower() or "time" in req.lower():
            prompt.append(TREND_ANALYSIS_PROMPT)
        elif "region" in req.lower():
            prompt.append(REGION_ANALYSIS_PROMPT)
        elif "category" in req.lower() or "product" in req.lower():
            prompt.append(CATEGORY_ANALYSIS_PROMPT)
        elif "channel" in req.lower() or "online" in req.lower() or "offline" in req.lower():
            prompt.append(CHANNEL_ANALYSIS_PROMPT)
        elif "quality" in req.lower() or "clean" in req.lower():
            prompt.append(DATA_QUALITY_PROMPT)
        elif "insight" in req.lower() or "recommendation" in req.lower():
            prompt.append(INSIGHT_GENERATION_PROMPT)

    return "\n\n".join(prompt)