import pandas as pd
import numpy as np
import os
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime
import matplotlib.pyplot as plt
import seaborn as sns
from ..schemas import Insight, ValidationResult


# Set up plotting style
sns.set_style("whitegrid")
plt.rcParams["figure.dpi"] = 100
plt.rcParams["figure.figsize"] = (12, 6)


class DataLoaderTools:
    """Tools for loading and initial data handling"""

    @staticmethod
    def load_csv(file_path: str) -> Tuple[pd.DataFrame, ValidationResult]:
        """Load CSV file with validation"""
        try:
            df = pd.read_csv(file_path)
            validation = ValidationResult(is_valid=True)

            # Basic validation
            if len(df) == 0:
                validation.errors.append("Empty dataframe loaded")
                validation.is_valid = False

            required_columns = ['date', 'region', 'product', 'category', 'quantity', 'unit_price', 'discount']
            missing_cols = [col for col in required_columns if col not in df.columns]
            if missing_cols:
                validation.errors.append(f"Missing required columns: {missing_cols}")
                validation.is_valid = False

            return df, validation

        except Exception as e:
            return None, ValidationResult(is_valid=False, errors=[f"Failed to load CSV: {str(e)}"])


class DataQualityTools:
    """Data quality assessment and cleaning tools"""

    @staticmethod
    def calculate_missing_values(df: pd.DataFrame) -> Dict[str, int]:
        """Calculate missing values per column"""
        return df.isnull().sum().to_dict()

    @staticmethod
    def calculate_missing_percent(df: pd.DataFrame) -> Dict[str, float]:
        """Calculate missing values percentage per column"""
        return (df.isnull().sum() / len(df) * 100).to_dict()

    @staticmethod
    def detect_anomalies(df: pd.DataFrame) -> Dict[str, List[Dict[str, Any]]]:
        """Detect anomalies in the data"""
        anomalies = {
            "invalid_discount": [],
            "large_quantity": [],
            "negative_values": []
        }

        # Check invalid discounts
        if 'discount' in df.columns:
            bad_discounts = df[(df['discount'] < 0) | (df['discount'] > 1)]
            for idx, row in bad_discounts.iterrows():
                anomalies["invalid_discount"].append({
                    "index": idx,
                    "value": row['discount'],
                    "details": f"Discount {row['discount']} outside valid range 0-1"
                })

        # Check large quantities
        if 'quantity' in df.columns:
            large_qty = df[df['quantity'] > 100]
            for idx, row in large_qty.iterrows():
                anomalies["large_quantity"].append({
                    "index": idx,
                    "value": row['quantity'],
                    "details": f"Quantity {row['quantity']} exceeds threshold of 100"
                })

        # Check negative values in numeric columns
        numeric_cols = df.select_dtypes(include=['int64', 'float64']).columns
        for col in numeric_cols:
            neg_values = df[df[col] < 0]
            for idx, row in neg_values.iterrows():
                anomalies["negative_values"].append({
                    "index": idx,
                    "column": col,
                    "value": row[col],
                    "details": f"Negative value in {col}"
                })

        return anomalies

    @staticmethod
    def clean_data(df: pd.DataFrame) -> Tuple[pd.DataFrame, ValidationResult]:
        """Clean the data by handling missing values and anomalies"""
        cleaned_df = df.copy()
        validation = ValidationResult(is_valid=True, checks_performed=5)

        # 1. Handle missing values
        if 'region' in cleaned_df.columns:
            cleaned_df['region'] = cleaned_df['region'].fillna("Unknown")
            validation.checks_performed += 1

        if 'customer_id' in cleaned_df.columns:
            cleaned_df['customer_id'] = cleaned_df['customer_id'].fillna("Unknown")
            validation.checks_performed += 1

        # 2. Fix invalid discounts
        if 'discount' in cleaned_df.columns:
            cleaned_df['discount'] = cleaned_df['discount'].clip(0, 1)
            cleaned_df['discount'] = cleaned_df['discount'].fillna(0)
            validation.checks_performed += 1

        # 3. Convert date column
        if 'date' in cleaned_df.columns:
            try:
                cleaned_df['date'] = pd.to_datetime(cleaned_df['date'])
                validation.checks_performed += 1
            except:
                validation.warnings.append("Failed to parse date column")

        # 4. Calculate revenue
        required_cols = ['quantity', 'unit_price', 'discount']
        if all(col in cleaned_df.columns for col in required_cols):
            cleaned_df['revenue'] = cleaned_df['quantity'] * cleaned_df['unit_price'] * (1 - cleaned_df['discount'])
            validation.checks_performed += 1

        # 5. Remove duplicates
        duplicates = cleaned_df.duplicated().sum()
        if duplicates > 0:
            cleaned_df = cleaned_df.drop_duplicates()
            validation.warnings.append(f"Removed {duplicates} duplicate rows")
            validation.checks_performed += 1

        if len(validation.errors) > 0:
            validation.is_valid = False

        return cleaned_df, validation


class AnalysisTools:
    """Core analysis tools"""

    @staticmethod
    def calculate_daily_revenue(df: pd.DataFrame) -> Tuple[pd.Series, ValidationResult]:
        """Calculate total revenue per day"""
        validation = ValidationResult(is_valid=True)

        if 'date' not in df.columns or 'revenue' not in df.columns:
            return None, ValidationResult(is_valid=False, errors=["Missing date or revenue columns"])

        try:
            daily_revenue = df.groupby('date')['revenue'].sum().sort_index()
            validation.checks_performed = 1
            return daily_revenue, validation
        except Exception as e:
            return None, ValidationResult(is_valid=False, errors=[f"Failed to calculate daily revenue: {str(e)}"])

    @staticmethod
    def calculate_region_revenue(df: pd.DataFrame) -> Tuple[pd.Series, ValidationResult]:
        """Calculate total revenue per region"""
        validation = ValidationResult(is_valid=True)

        if 'region' not in df.columns or 'revenue' not in df.columns:
            return None, ValidationResult(is_valid=False, errors=["Missing region or revenue columns"])

        try:
            region_revenue = df.groupby('region')['revenue'].sum().sort_values(ascending=False)
            validation.checks_performed = 1
            return region_revenue, validation
        except Exception as e:
            return None, ValidationResult(is_valid=False, errors=[f"Failed to calculate region revenue: {str(e)}"])

    @staticmethod
    def calculate_category_revenue(df: pd.DataFrame) -> Tuple[pd.Series, ValidationResult]:
        """Calculate total revenue per category"""
        validation = ValidationResult(is_valid=True)

        if 'category' not in df.columns or 'revenue' not in df.columns:
            return None, ValidationResult(is_valid=False, errors=["Missing category or revenue columns"])

        try:
            category_revenue = df.groupby('category')['revenue'].sum().sort_values(ascending=False)
            validation.checks_performed = 1
            return category_revenue, validation
        except Exception as e:
            return None, ValidationResult(is_valid=False, errors=[f"Failed to calculate category revenue: {str(e)}"])

    @staticmethod
    def calculate_channel_revenue(df: pd.DataFrame) -> Tuple[pd.Series, ValidationResult]:
        """Calculate total revenue per channel"""
        validation = ValidationResult(is_valid=True)

        if 'channel' not in df.columns or 'revenue' not in df.columns:
            return None, ValidationResult(is_valid=False, errors=["Missing channel or revenue columns"])

        try:
            channel_revenue = df.groupby('channel')['revenue'].sum().sort_values(ascending=False)
            validation.checks_performed = 1
            return channel_revenue, validation
        except Exception as e:
            return None, ValidationResult(is_valid=False, errors=[f"Failed to calculate channel revenue: {str(e)}"])

    @staticmethod
    def get_top_products(df: pd.DataFrame, n: int = 3) -> Tuple[pd.Series, ValidationResult]:
        """Get top N products by revenue"""
        validation = ValidationResult(is_valid=True)

        if 'product' not in df.columns or 'revenue' not in df.columns:
            return None, ValidationResult(is_valid=False, errors=["Missing product or revenue columns"])

        try:
            top_products = df.groupby('product')['revenue'].sum().sort_values(ascending=False).head(n)
            validation.checks_performed = 1
            return top_products, validation
        except Exception as e:
            return None, ValidationResult(is_valid=False, errors=[f"Failed to get top products: {str(e)}"])


class VisualizationTools:
    """Tools for generating visualizations"""

    @staticmethod
    def plot_daily_revenue(daily_revenue: pd.Series, output_dir: str = "plots") -> Tuple[str, ValidationResult]:
        """Plot daily revenue time series"""
        validation = ValidationResult(is_valid=True)

        try:
            os.makedirs(output_dir, exist_ok=True)

            plt.figure(figsize=(14, 7))
            plt.plot(daily_revenue.index, daily_revenue.values, marker='o', linestyle='-', color='#1f77b4')
            plt.title('Daily Total Revenue', fontsize=16, pad=20)
            plt.xlabel('Date', fontsize=12)
            plt.ylabel('Revenue ($)', fontsize=12)
            plt.xticks(rotation=45)
            plt.tight_layout()

            # Save plot
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            plot_path = os.path.join(output_dir, f"daily_revenue_{timestamp}.png")
            plt.savefig(plot_path, dpi=300, bbox_inches='tight')
            plt.close()

            validation.checks_performed = 1
            return plot_path, validation

        except Exception as e:
            return None, ValidationResult(is_valid=False, errors=[f"Failed to plot daily revenue: {str(e)}"])

    @staticmethod
    def plot_region_revenue(region_revenue: pd.Series, output_dir: str = "plots") -> Tuple[str, ValidationResult]:
        """Plot region revenue bar chart"""
        validation = ValidationResult(is_valid=True)

        try:
            os.makedirs(output_dir, exist_ok=True)

            plt.figure(figsize=(12, 8))
            colors = sns.color_pattern("viridis", len(region_revenue))
            ax = region_revenue.plot(kind='bar', color=colors)
            plt.title('Revenue by Region', fontsize=16, pad=20)
            plt.xlabel('Region', fontsize=12)
            plt.ylabel('Revenue ($)', fontsize=12)
            plt.xticks(rotation=45)

            # Add value labels
            for i, v in enumerate(region_revenue.values):
                ax.text(i, v + (v * 0.01), f"${v:,.0f}", ha='center', fontsize=10)

            plt.tight_layout()

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            plot_path = os.path.join(output_dir, f"region_revenue_{timestamp}.png")
            plt.savefig(plot_path, dpi=300, bbox_inches='tight')
            plt.close()

            validation.checks_performed = 1
            return plot_path, validation

        except Exception as e:
            return None, ValidationResult(is_valid=False, errors=[f"Failed to plot region revenue: {str(e)}"])

    @staticmethod
    def plot_category_revenue(category_revenue: pd.Series, output_dir: str = "plots") -> Tuple[str, ValidationResult]:
        """Plot category revenue pie chart"""
        validation = ValidationResult(is_valid=True)

        try:
            os.makedirs(output_dir, exist_ok=True)

            plt.figure(figsize=(10, 10))
            wedges, texts, autotexts = plt.pie(
                category_revenue.values,
                labels=category_revenue.index,
                autopct='%1.1f%%',
                startangle=90,
                pctdistance=0.85
            )

            # Draw circle in the center to make it a donut chart
            center_circle = plt.Circle((0, 0), 0.70, fc='white')
            fig = plt.gcf()
            fig.gca().add_artist(center_circle)

            plt.title('Revenue by Category', fontsize=16, pad=20)
            plt.tight_layout()

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            plot_path = os.path.join(output_dir, f"category_revenue_{timestamp}.png")
            plt.savefig(plot_path, dpi=300, bbox_inches='tight')
            plt.close()

            validation.checks_performed = 1
            return plot_path, validation

        except Exception as e:
            return None, ValidationResult(is_valid=False, errors=[f"Failed to plot category revenue: {str(e)}"])

    @staticmethod
    def plot_channel_comparison(channel_revenue: pd.Series, output_dir: str = "plots") -> Tuple[str, ValidationResult]:
        """Plot channel revenue comparison"""
        validation = ValidationResult(is_valid=True)

        try:
            os.makedirs(output_dir, exist_ok=True)

            plt.figure(figsize=(10, 6))
            colors = ['#ff7f0e', '#1f77b4']
            ax = channel_revenue.plot(kind='bar', color=colors)
            plt.title('Revenue by Sales Channel', fontsize=16, pad=20)
            plt.xlabel('Channel', fontsize=12)
            plt.ylabel('Revenue ($)', fontsize=12)

            # Add value labels
            for i, v in enumerate(channel_revenue.values):
                ax.text(i, v + (v * 0.01), f"${v:,.0f}", ha='center', fontsize=10)

            plt.tight_layout()

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            plot_path = os.path.join(output_dir, f"channel_comparison_{timestamp}.png")
            plt.savefig(plot_path, dpi=300, bbox_inches='tight')
            plt.close()

            validation.checks_performed = 1
            return plot_path, validation

        except Exception as e:
            return None, ValidationResult(is_valid=False, errors=[f"Failed to plot channel comparison: {str(e)}"])

    @staticmethod
    def plot_category_heatmap(df: pd.DataFrame, output_dir: str = "plots") -> Tuple[str, ValidationResult]:
        """Plot category x region heatmap"""
        validation = ValidationResult(is_valid=True)

        try:
            if 'category' not in df.columns or 'region' not in df.columns or 'revenue' not in df.columns:
                return None, ValidationResult(is_valid=False, errors=["Missing required columns for heatmap"])

            # Create pivot table
            pivot_data = df.pivot_table(
                values='revenue',
                index='category',
                columns='region',
                aggfunc='sum',
                fill_value=0
            )

            plt.figure(figsize=(14, 10))
            sns.heatmap(pivot_data, annot=True, fmt='$.2f', cmap='YlGnBu')
            plt.title('Revenue by Category and Region', fontsize=16, pad=20)
            plt.xlabel('Region', fontsize=12)
            plt.ylabel('Category', fontsize=12)
            plt.tight_layout()

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            plot_path = os.path.join(output_dir, f"category_region_heatmap_{timestamp}.png")
            plt.savefig(plot_path, dpi=300, bbox_inches='tight')
            plt.close()

            validation.checks_performed = 1
            return plot_path, validation

        except Exception as e:
            return None, ValidationResult(is_valid=False, errors=[f"Failed to plot category heatmap: {str(e)}"])


class InsightTools:
    """Tools for generating business insights"""

    @staticmethod
    def generate_insights(df: pd.DataFrame, daily_revenue: Optional[pd.Series] = None) -> List[Insight]:
        """Generate data-driven business insights"""
        insights = []

        # 1. Overall revenue insight
        if 'revenue' in df.columns:
            total_revenue = df['revenue'].sum()
            insights.append(Insight(
                title="Total Revenue",
                description=f"Total revenue for the period is ${total_revenue:,.2f}",
                supporting_data=[f"Total transactions: {len(df)}"],
                confidence=0.95
            ))

        # 2. Daily peak insight
        if daily_revenue is not None and len(daily_revenue) > 0:
            peak_day = daily_revenue.idxmax()
            peak_revenue = daily_revenue.max()
            insights.append(Insight(
                title="Peak Revenue Day",
                description=f"Highest revenue day was {peak_day.strftime('%Y-%m-%d')} with ${peak_revenue:,.2f}",
                supporting_data=[f"Daily revenue range: ${daily_revenue.min():,.2f} to ${peak_revenue:,.2f}"],
                confidence=0.9
            ))

        # 3. Top product insight
        if 'product' in df.columns and 'revenue' in df.columns:
            top_product = df.groupby('product')['revenue'].sum().idxmax()
            top_product_rev = df.groupby('product')['revenue'].sum().max()
            insights.append(Insight(
                title="Top Performing Product",
                description=f"Top product is {top_product} with ${top_product_rev:,.2f} in revenue",
                supporting_data=[f"Total products: {df['product'].nunique()}"],
                confidence=0.9
            ))

        # 4. Region insight
        if 'region' in df.columns and 'revenue' in df.columns:
            top_region = df.groupby('region')['revenue'].sum().idxmax()
            top_region_rev = df.groupby('region')['revenue'].sum().max()
            insights.append(Insight(
                title="Top Performing Region",
                description=f"Top region is {top_region} with ${top_region_rev:,.2f} in revenue",
                supporting_data=[f"Total regions: {df['region'].nunique()}"],
                confidence=0.85
            ))

        return insights


class ValidationTools:
    """Tools for validation and verification"""

    @staticmethod
    def validate_revenue_calculation(df: pd.DataFrame) -> ValidationResult:
        """Validate revenue calculation accuracy"""
        validation = ValidationResult(is_valid=True, checks_performed=1)

        if 'revenue' not in df.columns:
            validation.errors.append("Revenue column not found")
            validation.is_valid = False
            return validation

        # Check a sample of rows manually
        sample = df.sample(min(5, len(df)))
        for idx, row in sample.iterrows():
            if 'quantity' in row and 'unit_price' in row and 'discount' in row:
                calculated = row['quantity'] * row['unit_price'] * (1 - row['discount'])
                if abs(row['revenue'] - calculated) > 0.01:
                    validation.warnings.append(
                        f"Row {idx}: Revenue mismatch - calculated ${calculated:.2f}, stored ${row['revenue']:.2f}"
                    )

        if len(validation.warnings) > 0:
            validation.is_valid = False

        return validation

    @staticmethod
    def check_data_integrity(df: pd.DataFrame) -> ValidationResult:
        """Check overall data integrity"""
        validation = ValidationResult(is_valid=True)

        # Check for empty dataframe
        if len(df) == 0:
            validation.errors.append("Dataframe is empty")
            validation.is_valid = False
            return validation

        # Check required columns
        required_columns = ['date', 'region', 'product', 'category', 'quantity', 'unit_price', 'discount']
        missing_cols = [col for col in required_columns if col not in df.columns]
        if missing_cols:
            validation.errors.append(f"Missing required columns: {missing_cols}")
            validation.is_valid = False

        # Check for negative values in critical columns
        numeric_cols = ['quantity', 'unit_price', 'discount']
        for col in numeric_cols:
            if col in df.columns:
                if (df[col] < 0).any():
                    validation.warnings.append(f"Column '{col}' contains negative values")

        validation.checks_performed = 3
        return validation