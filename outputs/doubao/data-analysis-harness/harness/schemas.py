from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime
import pandas as pd


@dataclass
class DataProfile:
    """Data profile information for DataFrame context"""
    shape: Tuple[int, int]
    columns: List[str]
    dtypes: Dict[str, str]
    missing_values: Dict[str, int]
    missing_rate: Dict[str, float]
    summary_stats: Dict[str, Dict[str, float]]


@dataclass
class AnalysisStep:
    """Record of a single analysis step"""
    name: str
    description: str
    input_shape: Tuple[int, int]
    output_shape: Tuple[int, int]
    timestamp: datetime = field(default_factory=datetime.now)
    code_snippet: Optional[str] = None
    validation_result: Optional[Dict[str, Any]] = None
    chart_path: Optional[str] = None


@dataclass
class ChartRecord:
    """Record of generated chart"""
    name: str
    path: str
    title: str
    created_at: datetime = field(default_factory=datetime.now)
    data_summary: str


@dataclass
class Insight:
    """Data-driven business insight"""
    title: str
    description: str
    supporting_data: List[str]
    confidence: float = 1.0


@dataclass
class ValidationResult:
    """Result of data validation"""
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    checks_performed: int = 0


@dataclass
class ExecutionState:
    """Current state of the analysis execution"""
    current_step: str = "LOAD"
    dataframes: Dict[str, pd.DataFrame] = field(default_factory=dict)
    variables: Dict[str, Any] = field(default_factory=dict)
    analysis_history: List[AnalysisStep] = field(default_factory=list)
    charts: List[ChartRecord] = field(default_factory=list)
    insights: List[Insight] = field(default_factory=list)
    validation_results: List[ValidationResult] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)

    def update_timestamp(self) -> None:
        """Update the last_updated timestamp"""
        self.last_updated = datetime.now()
