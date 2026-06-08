"""Scaffold-native generated harness program for data analysis tasks.

Implements a Plan-Code-Observe loop on top of harness_scaffold,
using LLM calls for planning, code generation, and observation,
with scaffold tools for execution and artifact management.
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import re
import traceback
from pathlib import Path
from typing import Any, Optional

from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.schemas import HarnessResult, HarnessStatus
from harness_scaffold.examples._common import make_result, try_tool
from harness_scaffold.tools.registry import ToolRegistry

from context_manager import (
    build_data_summary,
    build_llm_prompt,
    discover_files,
    truncate_output,
)
from custom_tools import register_custom_tools
from planner import AnalysisPlan, parse_task, plan_to_context_string
from recovery import create_baseline_submission, create_fallback_report, safe_json_write
from verifier import verify_dacomp_artifacts, verify_report, verify_submission


class GeneratedHarnessProgram:
    name = "data-analysis-harness"

    MAX_ANALYSIS_STEPS = 15
    MAX_OUTPUT_CHARS = 8000

    async def run(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        llm: Optional[object],
    ) -> HarnessResult:
        ctx.trajectory.log_step(0, phase="start", note=self.name)
        register_custom_tools(tools)

        status: str = "failed"
        error_msg: str = ""
        artifacts: dict[str, Path] = {}

        try:
            status, error_msg, artifacts = await self._execute(ctx, tools, llm)
        except Exception as exc:
            error_msg = f"harness error: {type(exc).__name__}: {exc}"
            traceback.print_exc()
            self._ensure_minimal_artifacts(ctx, error_msg)

        final_status = self._finalize_status(ctx, status, error_msg)
        return make_result(
            ctx,
            status=final_status,
            answer_path=artifacts.get("report"),
            metadata={"error": error_msg if error_msg else None},
        )

    async def _execute(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        llm: Optional[object],
    ) -> tuple[str, str, dict[str, Path]]:
        """Main execution: discover, plan, iterate, produce artifacts."""
        workdir = ctx.workdir
        out_dir = ctx.out_dir
        prompt = ctx.task.prompt

        # --- Phase 1: Discover files ---
        ctx.trajectory.log_step(1, phase="discover", note="scanning workdir")
        discovered = discover_files(workdir)
        data_summary = build_data_summary(workdir)
        ctx.trajectory.log_observation(
            f"Discovered {len(discovered.get('data_files', []))} data files",
            source="discover",
        )
        ctx.new_artifact_text("data_summary.txt", data_summary, kind="analysis")

        # --- Phase 2: Parse task and plan ---
        ctx.trajectory.log_step(2, phase="plan", note="parsing task")
        plan = parse_task(prompt, workdir, discovered)
        plan_str = plan_to_context_string(plan)
        ctx.trajectory.log_observation(
            f"Plan: artifact_type={plan.artifact_type}, domain={plan.domain}, "
            f"task_type={plan.task_type}, has_sample={plan.has_sample_submission}",
            source="plan",
        )

        # --- Phase 3: Analysis ---
        observation_log: list[str] = []
        code_results: list[str] = []
        submission_created = False
        report_created = False

        if llm is not None:
            ctx.trajectory.log_step(3, phase="llm_analysis", note="starting LLM loop")
            submission_created, report_created = await self._llm_analysis_loop(
                ctx, tools, llm, prompt, data_summary, plan, plan_str,
                observation_log, code_results,
            )
        else:
            ctx.trajectory.log_step(3, phase="scripted_analysis", note="no LLM, using scripted approach")
            submission_created, report_created = await self._scripted_analysis(
                ctx, tools, prompt, data_summary, plan, discovered,
                observation_log, code_results,
            )

        # --- Phase 4: Ensure required artifacts exist ---
        ctx.trajectory.log_step(4, phase="finalize", note="ensuring artifacts")

        # Baseline submission fallback
        if plan.has_sample_submission and not submission_created:
            sample_sub = discovered.get("sample_submission")
            sub_path = out_dir / "submission.csv"
            if sample_sub:
                train_path = plan.train_files[0] if plan.train_files else None
                created = create_baseline_submission(
                    sample_sub, sub_path, train_path, plan.task_type,
                )
                if created:
                    submission_created = True
                    ctx.new_artifact_text("submission.csv", sub_path.read_text(), kind="submission")
                    ctx.trajectory.log_observation("Created baseline submission", source="recovery")

        # Report fallback
        report_path = out_dir / "REPORT.md"
        if report_path.exists():
            try:
                existing = report_path.read_text(encoding="utf-8", errors="replace")
                if len(existing.split()) >= 50:
                    report_created = True
                    ctx.new_artifact_text("REPORT.md", existing, kind="report")
            except Exception:
                pass

        if not report_created:
            obs_text = "\n".join(observation_log[-5:]) if observation_log else ""
            code_text = "\n".join(code_results[-3:]) if code_results else ""
            report_content = self._build_report(
                prompt, data_summary, plan, obs_text, code_text,
            )
            report_path.write_text(report_content, encoding="utf-8")
            ctx.new_artifact_text("REPORT.md", report_content, kind="report")
            report_created = True
            ctx.trajectory.log_observation("Created report", source="finalize")

        # DAComp-specific artifacts
        if plan.domain == "dacomp":
            self._write_dacomp_artifacts(ctx, plan, observation_log, code_results)

        # result.json
        result_data = {
            "status": "success" if submission_created or report_created else "partial",
            "trajectory": str(out_dir / "trajectory.jsonl"),
            "artifacts": {},
            "report_path": str(report_path) if report_path.exists() else "",
            "submission_path": str(out_dir / "submission.csv") if (out_dir / "submission.csv").exists() else "",
            "error": "",
        }
        for p in out_dir.iterdir():
            if p.is_file() and p.name not in {
                "trajectory.jsonl", "metadata.json", "artifacts.json",
                "error.json", "stdout.log", "stderr.log", "response.md",
                "task.json", "config.json",
            }:
                result_data["artifacts"][p.name] = str(p)
        ctx.new_artifact_json("result.json", result_data, kind="result")

        final_status = "success"
        if plan.has_sample_submission and not submission_created:
            final_status = "partial"
        if not report_created:
            final_status = "partial"

        return final_status, "", {"report": report_path}

    # ------------------------------------------------------------------ #
    # LLM-driven analysis loop
    # ------------------------------------------------------------------ #

    async def _llm_analysis_loop(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        llm: Any,
        prompt: str,
        data_summary: str,
        plan: AnalysisPlan,
        plan_str: str,
        observation_log: list[str],
        code_results: list[str],
    ) -> tuple[bool, bool]:
        """Run the LLM-driven Plan-Code-Observe loop."""
        submission_created = False
        report_created = False
        previous_actions: list[str] = []

        for step_idx in range(self.MAX_ANALYSIS_STEPS):
            if ctx.budget.exceeded():
                break
            try:
                ctx.check_abort(stage="analysis_loop")
            except Exception:
                break
            ctx.budget.step()

            # Decide step type
            if step_idx == 0:
                step_type = "plan"
            elif step_idx >= self.MAX_ANALYSIS_STEPS - 2:
                step_type = "finalize"
            elif step_idx % 3 == 0 and step_idx > 0:
                step_type = "observe"
            else:
                step_type = "code"

            prev_str = "\n".join(previous_actions[-6:]) if previous_actions else None
            obs_str = observation_log[-1] if observation_log else None

            messages = build_llm_prompt(
                prompt, data_summary,
                step_type=step_type,
                previous_actions=prev_str,
                observation=obs_str,
                out_dir=str(ctx.out_dir),
            )

            try:
                response = await self._call_llm(llm, messages, ctx)
            except Exception as exc:
                ctx.trajectory.log_observation(f"LLM call failed: {exc}", source="llm_error")
                break

            if not response.text:
                continue

            response_text = response.text
            previous_actions.append(f"[{step_type}] {response_text[:500]}")

            if step_type in ("plan", "observe"):
                observation_log.append(truncate_output(response_text, self.MAX_OUTPUT_CHARS))
                continue

            code = self._extract_code(response_text)
            if not code:
                observation_log.append(truncate_output(response_text, self.MAX_OUTPUT_CHARS))
                continue

            # Execute the code
            exec_result = await try_tool(ctx, tools, "python_exec", {"code": code, "timeout": 120})
            # Copy any output files from workdir to out_dir
            self._copy_outputs(ctx.workdir, ctx.out_dir)

            if exec_result[0] and exec_result[1] is not None:
                result = exec_result[1]
                if result.ok:
                    output = result.data.get("stdout", "") or ""
                    stderr = result.data.get("stderr", "")
                    if stderr:
                        output += f"\n[STDERR]: {stderr[:2000]}"
                    output = truncate_output(output, self.MAX_OUTPUT_CHARS)
                    code_results.append(output)
                    observation_log.append(f"Code output (step {step_idx}):\n{output}")
                else:
                    error_text = str(result.error or "unknown error")[:2000]
                    observation_log.append(f"Code error (step {step_idx}): {error_text}")

            # Check for artifacts created by code
            sub_path = ctx.out_dir / "submission.csv"
            if sub_path.exists() and not submission_created:
                submission_created = True
                try:
                    ctx.new_artifact_text("submission.csv", sub_path.read_text(), kind="submission")
                except Exception:
                    pass

            report_path = ctx.out_dir / "REPORT.md"
            if report_path.exists() and not report_created:
                try:
                    text = report_path.read_text(encoding="utf-8", errors="replace")
                    if len(text.split()) > 30:
                        report_created = True
                        ctx.new_artifact_text("REPORT.md", text, kind="report")
                except Exception:
                    pass

            if submission_created and report_created:
                break

        return submission_created, report_created

    # ------------------------------------------------------------------ #
    # Scripted analysis (no LLM)
    # ------------------------------------------------------------------ #

    async def _scripted_analysis(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        prompt: str,
        data_summary: str,
        plan: AnalysisPlan,
        discovered: dict[str, Any],
        observation_log: list[str],
        code_results: list[str],
    ) -> tuple[bool, bool]:
        """Run scripted analysis when no LLM is available."""
        submission_created = False
        report_created = False

        # Run data exploration
        explore_code = self._build_exploration_code(plan, discovered)
        if explore_code:
            result = await self._run_code(ctx, tools, explore_code, 60)
            if result:
                code_results.append(result)
                observation_log.append(f"Exploration:\n{result}")

        # Run modeling if needed
        if plan.needs_modeling and plan.train_files and plan.test_files:
            model_code = self._build_modeling_code(plan, discovered, ctx.out_dir)
            if model_code:
                result = await self._run_code(ctx, tools, model_code, 180)
                if result:
                    code_results.append(result)
                    observation_log.append(f"Modeling:\n{result}")

        # For DAComp/report-only tasks, run a deeper analysis script
        if not plan.needs_modeling and plan.data_files:
            analysis_code = self._build_analysis_report_code(plan, discovered, ctx.out_dir, ctx.task.prompt)
            if analysis_code:
                result = await self._run_code(ctx, tools, analysis_code, 120)
                if result:
                    code_results.append(result)
                    observation_log.append(f"Analysis:\n{result}")

        # Copy output files from workdir to out_dir
        self._copy_outputs(ctx.workdir, ctx.out_dir)

        # Check for artifacts in out_dir
        sub_path = ctx.out_dir / "submission.csv"
        if sub_path.exists():
            submission_created = True
            try:
                ctx.new_artifact_text("submission.csv", sub_path.read_text(), kind="submission")
            except Exception:
                pass

        report_path = ctx.out_dir / "REPORT.md"
        if report_path.exists():
            try:
                text = report_path.read_text(encoding="utf-8", errors="replace")
                if len(text.split()) > 30:
                    report_created = True
                    ctx.new_artifact_text("REPORT.md", text, kind="report")
            except Exception:
                pass

        return submission_created, report_created

    async def _run_code(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        code: str,
        timeout: int = 120,
    ) -> str | None:
        """Execute Python code and return truncated output string."""
        exec_result = await try_tool(ctx, tools, "python_exec", {"code": code, "timeout": timeout})
        if not exec_result[0] or exec_result[1] is None:
            return None
        result = exec_result[1]
        if result.ok:
            output = result.data.get("stdout", "") or ""
            stderr = result.data.get("stderr", "")
            if stderr and len(stderr) < 2000:
                output += f"\n[STDERR]: {stderr}"
            return truncate_output(output, self.MAX_OUTPUT_CHARS)
        else:
            error_text = str(result.error or "unknown error")[:2000]
            return f"[ERROR]: {error_text}"

    def _copy_outputs(self, workdir: Path, out_dir: Path) -> None:
        """Copy output files from workdir to out_dir."""
        import shutil
        output_names = {"submission.csv", "REPORT.md", "analysis_summary.json",
                        "metrics.csv", "risk_scores.csv", "credit_allocation.csv"}
        for name in output_names:
            src = workdir / name
            dst = out_dir / name
            if src.exists() and not dst.exists():
                try:
                    shutil.copy2(str(src), str(dst))
                except Exception:
                    pass

    def _build_exploration_code(
        self,
        plan: AnalysisPlan,
        discovered: dict[str, Any],
    ) -> str:
        """Build data exploration Python code."""
        train_paths = [str(f) for f in plan.train_files if f.suffix.lower() in {".csv", ".tsv"}]
        test_paths = [str(f) for f in plan.test_files if f.suffix.lower() in {".csv", ".tsv"}]
        other_paths = [str(f) for f in plan.data_files if f.suffix.lower() in {".csv", ".tsv"}]

        code_lines = [
            "import warnings; warnings.filterwarnings('ignore')",
            "import pandas as pd",
            "import numpy as np",
        ]

        def _add_df_exploration(varname: str, path: str, label: str) -> None:
            code_lines.append(f"{varname} = pd.read_csv({path!r})")
            code_lines.append(f"print('=== {label} ===')")
            code_lines.append(f"print('Shape:', {varname}.shape)")
            code_lines.append(f"print('Columns:', list({varname}.columns))")
            code_lines.append(f"print('Dtypes:'); print({varname}.dtypes)")
            code_lines.append(f"print('Head:'); print({varname}.head(3))")
            code_lines.append(f"print('Missing:'); print({varname}.isnull().sum())")
            code_lines.append(f"print('Describe:'); print({varname}.describe())")

        # Load train data
        if train_paths:
            _add_df_exploration("train", train_paths[0], "TRAIN")

        # Load test data
        if test_paths:
            _add_df_exploration("test", test_paths[0], "TEST")

        # Load other data files
        for i, fp in enumerate(other_paths[:5]):
            varname = f"data_{i}"
            name = Path(fp).name
            _add_df_exploration(varname, fp, name)

        return "\n".join(code_lines)

    def _build_modeling_code(
        self,
        plan: AnalysisPlan,
        discovered: dict[str, Any],
        out_dir: Path,
    ) -> str:
        """Build modeling + submission generation Python code."""
        train_path = str(plan.train_files[0]) if plan.train_files else ""
        test_path = str(plan.test_files[0]) if plan.test_files else ""
        sample_sub_path = ""
        if discovered.get("sample_submission"):
            sample_sub_path = str(discovered["sample_submission"])
        out_dir_str = str(out_dir)

        target_cols = plan.sample_target_columns
        id_col = plan.sample_id_column or "id"

        # Determine if boolean target
        is_bool_target = False
        if sample_sub_path:
            try:
                with open(sample_sub_path, newline="", encoding="utf-8", errors="replace") as f:
                    reader = csv.DictReader(f)
                    if target_cols:
                        vals = set()
                        for i, row in enumerate(reader):
                            if i >= 50:
                                break
                            v = str(row.get(target_cols[0], "")).strip().lower()
                            if v:
                                vals.add(v)
                        if vals <= {"true", "false"}:
                            is_bool_target = True
            except Exception:
                pass

        code = f'''import warnings; warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.model_selection import cross_val_score
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler, OneHotEncoder

# Load data
train = pd.read_csv({train_path!r})
test = pd.read_csv({test_path!r})
target_cols = {target_cols!r}
id_col = {id_col!r}
is_bool_target = {is_bool_target!r}

print(f"Train: {{train.shape}}, Test: {{test.shape}}")
print(f"Target columns: {{target_cols}}")

# Identify features
feature_cols = [c for c in train.columns if c not in target_cols and c != id_col]
print(f"Features: {{len(feature_cols)}}")

# Separate numeric and categorical
cat_cols = train[feature_cols].select_dtypes(include=['object']).columns.tolist()
num_cols = train[feature_cols].select_dtypes(exclude=['object']).columns.tolist()
print(f"Numeric: {{len(num_cols)}}, Categorical: {{len(cat_cols)}}")

# Build preprocessing pipeline
num_tf = Pipeline([
    ('imputer', SimpleImputer(strategy='median')),
    ('scaler', StandardScaler())
])
cat_tf = Pipeline([
    ('imputer', SimpleImputer(strategy='most_frequent')),
    ('encoder', OneHotEncoder(handle_unknown='ignore', sparse_output=False))
])
preprocessor = ColumnTransformer([
    ('num', num_tf, num_cols),
    ('cat', cat_tf, cat_cols),
])

# Prepare target
y = train[target_cols[0]]
try:
    y = y.astype(float)
    if is_bool_target:
        y = (y > 0.5).astype(int)
except (ValueError, TypeError):
    # Label encode for non-numeric targets
    from sklearn.preprocessing import LabelEncoder
    le = LabelEncoder()
    y = le.fit_transform(y.astype(str))

# Determine task type and train model
unique_vals = len(set(y))
if unique_vals <= 20:  # classification
    print("Task type: classification")
    model = Pipeline([
        ('preprocessor', preprocessor),
        ('clf', RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=-1))
    ])
    try:
        scores = cross_val_score(model, train[feature_cols], y, cv=3, scoring='accuracy')
        print(f"CV accuracy: {{scores.mean():.4f}} (+/- {{scores.std():.4f}})")
    except Exception as e:
        print(f"CV failed: {{e}}")
else:  # regression
    print("Task type: regression")
    model = Pipeline([
        ('preprocessor', preprocessor),
        ('reg', RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1))
    ])
    try:
        scores = cross_val_score(model, train[feature_cols], y, cv=3, scoring='neg_mean_squared_error')
        print(f"CV RMSE: {{(-scores.mean())**0.5:.4f}}")
    except Exception as e:
        print(f"CV failed: {{e}}")

model.fit(train[feature_cols], y)
preds = model.predict(test[feature_cols])
print(f"Predictions: {{len(preds)}} samples")

# Format predictions
if is_bool_target:
    preds = ['True' if int(p) == 1 else 'False' for p in preds]
elif unique_vals <= 20 and not is_bool_target:
    # Check if original values were integers
    try:
        orig_vals = train[target_cols[0]].dropna()
        if all(float(v).is_integer() for v in orig_vals if str(v).strip()):
            preds = [int(p) for p in preds]
    except (ValueError, TypeError):
        pass

# Create submission
submission = pd.DataFrame({{id_col: test[id_col] if id_col in test.columns else range(len(preds))}})
submission[target_cols[0]] = preds

# Ensure column order matches sample submission
if {bool(sample_sub_path)}:
    sample = pd.read_csv({sample_sub_path!r})
    for col in sample.columns:
        if col not in submission.columns:
            submission[col] = 0
    submission = sample[[sample.columns[0]]].merge(submission, on=sample.columns[0], how='left')
    submission = submission[sample.columns]

submission.to_csv({out_dir_str!r} + '/submission.csv', index=False)
print("submission.csv created")
print(submission.head())

# Write report
report_lines = [
    "# Data Analysis Report",
    "",
    "## Problem Understanding",
    "",
    "Predict target column for test data.",
    "",
    "## Data Overview",
    "",
    f"- Training: {{train.shape[0]}} rows, {{train.shape[1]}} columns",
    f"- Test: {{test.shape[0]}} rows",
    f"- Features: {{len(num_cols)}} numeric, {{len(cat_cols)}} categorical",
    f"- Target: {{target_cols[0]}}",
    "",
    "## Methodology",
    "",
    f"- Task type: {{'classification' if unique_vals <= 20 else 'regression'}}",
    "- Model: RandomForest",
    f"- Features used: {{len(feature_cols)}}",
    "",
    "## Results",
    "",
    f"- Predictions generated for {{len(preds)}} test samples",
]

try:
    if unique_vals <= 20:
        report_lines.append(f"- CV accuracy: {{scores.mean():.4f}}")
    else:
        report_lines.append(f"- CV RMSE: {{(-scores.mean())**0.5:.4f}}")
except:
    pass

report_lines.extend(["", "## Limitations", "", "- Automated analysis with RandomForest baseline"])

with open({out_dir_str!r} + '/REPORT.md', 'w') as f:
    f.write('\\n'.join(report_lines))
print("REPORT.md created")
'''
        return code

    def _build_analysis_report_code(
        self,
        plan: AnalysisPlan,
        discovered: dict[str, Any],
        out_dir: Path,
        prompt: str,
    ) -> str:
        """Build analysis and report code for DAComp/report-only tasks."""
        out_dir_str = str(out_dir)
        data_files = [str(f) for f in plan.data_files if f.suffix.lower() in {".csv", ".tsv"}]

        if not data_files:
            return ""

        # Use first data file as the primary dataset
        main_path = data_files[0]
        name = Path(main_path).stem

        code = f'''import warnings; warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np
import json

# Load data
df = pd.read_csv({main_path!r})
print(f'Data shape: {{df.shape}}')
print(f'Columns: {{list(df.columns)}}')
print(f'Dtypes: {{dict(df.dtypes)}}')

# Basic statistics
print('\\n=== Summary Statistics ===')
print(df.describe().to_string())

# Missing values
missing = df.isnull().sum()
if missing.sum() > 0:
    print(f'\\nMissing values: {{dict(missing[missing > 0])}}')
else:
    print('\\nNo missing values')

# Value counts for categorical columns
cat_cols = df.select_dtypes(include=['object']).columns.tolist()
for col in cat_cols[:10]:
    print(f'\\n{{col}} value counts:')
    print(df[col].value_counts().head(10).to_string())

# Correlations for numeric columns
num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
if len(num_cols) >= 2:
    print('\\n=== Correlations ===')
    print(df[num_cols].corr().to_string())

# Build summary dict
summary = {{
    'dataset': {name!r},
    'rows': int(df.shape[0]),
    'columns': list(df.columns),
    'numeric_columns': num_cols,
    'categorical_columns': cat_cols,
    'missing_values': {{col: int(val) for col, val in missing.items() if val > 0}},
}}

# Compute key metrics for each numeric column
for col in num_cols:
    vals = df[col].dropna()
    summary[f'{{col}}_mean'] = round(float(vals.mean()), 4)
    summary[f'{{col}}_std'] = round(float(vals.std()), 4)
    summary[f'{{col}}_min'] = round(float(vals.min()), 4)
    summary[f'{{col}}_max'] = round(float(vals.max()), 4)

# Write machine-readable summary
with open({out_dir_str!r} + '/analysis_summary.json', 'w') as f:
    json.dump(summary, f, indent=2, default=str)
print('\\nanalysis_summary.json created')

# Write REPORT.md
report_lines = [
    '# Data Analysis Report',
    '',
    '## Problem Understanding',
    '',
    {prompt!r}[:500],
    '',
    '## Data Overview',
    '',
    f'- Dataset: {{df.shape[0]}} rows, {{df.shape[1]}} columns',
    f'- Numeric columns: {{len(num_cols)}}',
    f'- Categorical columns: {{len(cat_cols)}}',
    '',
    '## Key Statistics',
    '',
]

# Add stats table
if num_cols:
    report_lines.append('| Column | Mean | Std | Min | Max |')
    report_lines.append('|--------|------|-----|-----|-----|')
    for col in num_cols[:20]:
        vals = df[col].dropna()
        report_lines.append(f'| {{col}} | {{vals.mean():.2f}} | {{vals.std():.2f}} | {{vals.min():.2f}} | {{vals.max():.2f}} |')
    report_lines.append('')

# Add categorical distributions
if cat_cols:
    report_lines.append('## Category Distributions')
    report_lines.append('')
    for col in cat_cols[:5]:
        vc = df[col].value_counts().head(5)
        report_lines.append(f'### {{col}}')
        for val, cnt in vc.items():
            report_lines.append(f'- {{val}}: {{cnt}} ({{cnt/len(df)*100:.1f}}%)')
        report_lines.append('')

# Check for risk/tier/credit/churn keywords in prompt
prompt_lower = {prompt!r}.lower()
if any(kw in prompt_lower for kw in ['risk', 'tier', 'credit', 'churn', 'allocation']):
    report_lines.extend([
        '## Risk Analysis',
        '',
    ])
    # Try to identify risk-related columns
    risk_cols = [c for c in df.columns if any(k in c.lower() for k in ['risk', 'score', 'rating', 'tier', 'grade'])]
    if risk_cols:
        for col in risk_cols[:3]:
            if df[col].dtype == 'object':
                report_lines.append(f'### {{col}} Distribution')
                vc = df[col].value_counts()
                for val, cnt in vc.items():
                    report_lines.append(f'- {{val}}: {{cnt}} ({{cnt/len(df)*100:.1f}}%)')
                report_lines.append('')
            else:
                report_lines.append(f'- {{col}}: mean={{df[col].mean():.2f}}, std={{df[col].std():.2f}}')
                report_lines.append('')

    # If there's a budget mentioned, create a simple allocation
    import re
    budget_match = re.search(r'(\\d[\\d,]+)', {prompt!r})
    if budget_match:
        budget = int(budget_match.group(1).replace(',', ''))
        report_lines.append(f'### Budget Allocation (Total: {{budget:,}})')
        report_lines.append('')
        # Allocate proportionally or equally
        if risk_cols and df[risk_cols[0]].dtype == 'object':
            tiers = df[risk_cols[0]].value_counts()
            per_tier = budget // len(tiers)
            report_lines.append('| Tier | Count | Allocation | Share |')
            report_lines.append('|------|-------|------------|-------|')
            for tier, count in tiers.items():
                share = count / len(df)
                alloc = int(budget * share)
                report_lines.append(f'| {{tier}} | {{count}} | {{alloc:,}} | {{share*100:.1f}}% |')
        else:
            report_lines.append(f'- Equal allocation across groups')
        report_lines.append('')

report_lines.extend([
    '## Limitations',
    '',
    '- Automated analysis with statistical baselines',
    '- No predictive modeling applied',
    '',
])

with open({out_dir_str!r} + '/REPORT.md', 'w') as f:
    f.write('\\n'.join(report_lines))
print('REPORT.md created')
'''
        return code

    # ------------------------------------------------------------------ #
    # LLM interaction helpers
    # ------------------------------------------------------------------ #

    async def _call_llm(
        self,
        llm: Any,
        messages: list[dict[str, str]],
        ctx: RuntimeContext,
    ) -> Any:
        """Call the LLM client with retry logic."""
        from harness_scaffold.core.errors import ProviderError

        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                ctx.trajectory.log_llm_call(
                    model=getattr(llm, 'model', None),
                    num_messages=len(messages),
                )
                response = await llm.complete(messages, timeout=120)
                ctx.trajectory.log_llm_result(
                    model=response.model,
                    usage=response.usage if hasattr(response, 'usage') else None,
                    text_preview=response.text[:200] if response.text else None,
                )
                return response
            except ProviderError as exc:
                if not exc.recoverable or attempt >= max_retries:
                    raise
                await asyncio.sleep(1.0 * (attempt + 1))
            except Exception as exc:
                if attempt >= max_retries:
                    raise
                await asyncio.sleep(1.0 * (attempt + 1))

    def _extract_code(self, text: str) -> str:
        """Extract Python code from LLM response text."""
        # Match ```python ... ``` or ``` ... ```
        pattern = r"```(?:python)?\s*\n(.*?)```"
        matches = re.findall(pattern, text, re.DOTALL)
        if matches:
            return max(matches, key=len).strip()

        # Check if text looks like code
        code_indicators = [
            "import ", "from ", "def ", "pd.", "np.",
            "sklearn.", "train[", "test[", ".fit(", ".predict(",
            ".read_csv(", ".to_csv(",
        ]
        if sum(1 for ind in code_indicators if ind in text) >= 2:
            lines = text.split("\n")
            code_lines = []
            for line in lines:
                stripped = line.strip()
                if (stripped.startswith("import") or stripped.startswith("from")
                        or code_lines):
                    code_lines.append(line)
            if code_lines:
                return "\n".join(code_lines)

        return ""

    # ------------------------------------------------------------------ #
    # Report and artifact builders
    # ------------------------------------------------------------------ #

    def _build_report(
        self,
        prompt: str,
        data_summary: str,
        plan: AnalysisPlan,
        observations: str,
        code_results: str,
    ) -> str:
        """Build a REPORT.md from available information."""
        parts = [
            "# Data Analysis Report",
            "",
            "## Problem Understanding",
            "",
            prompt[:2000],
            "",
            "## Data Overview",
            "",
        ]

        # Extract key lines from data summary
        for line in data_summary.split("\n"):
            if line.startswith("===") or "Columns" in line or "Rows:" in line:
                parts.append(line)
        if len(parts) < 10:
            parts.append(data_summary[:2000])

        parts.extend(["", "## Methodology", ""])
        if plan.task_type:
            parts.append(f"Task type: {plan.task_type}")
        if plan.train_files:
            parts.append(f"Training data: {', '.join(f.name for f in plan.train_files)}")
        if plan.test_files:
            parts.append(f"Test data: {', '.join(f.name for f in plan.test_files)}")
        if plan.has_sample_submission:
            parts.append(f"Target columns: {plan.sample_target_columns}")

        if observations:
            parts.extend(["", "## Analysis Results", "", observations[:4000]])
        if code_results:
            parts.extend(["", "## Computed Metrics", "", code_results[:3000]])

        parts.extend(["", "## Limitations", ""])
        parts.append("- Analysis performed with automated data analysis harness")

        return "\n".join(parts)

    def _write_dacomp_artifacts(
        self,
        ctx: RuntimeContext,
        plan: AnalysisPlan,
        observation_log: list[str],
        code_results: list[str],
    ) -> None:
        """Write DAComp-specific machine-readable artifacts."""
        summary: dict[str, Any] = {
            "domain": plan.domain,
            "task_type": plan.task_type,
            "artifact_type": plan.artifact_type,
        }
        if code_results:
            summary["analysis_output"] = truncate_output(
                "\n".join(code_results[-3:]), 5000
            )
        safe_json_write(ctx.out_dir / "analysis_summary.json", summary)
        ctx.new_artifact_json("analysis_summary.json", summary, kind="analysis")

    def _ensure_minimal_artifacts(self, ctx: RuntimeContext, error_msg: str) -> None:
        """Ensure minimal required artifacts exist even on failure."""
        out_dir = ctx.out_dir
        if not (out_dir / "result.json").exists():
            result_data = {
                "status": "failed",
                "trajectory": str(out_dir / "trajectory.jsonl"),
                "artifacts": {},
                "report_path": "",
                "submission_path": "",
                "error": error_msg[:2000],
            }
            ctx.new_artifact_json("result.json", result_data, kind="result")

        report_path = out_dir / "REPORT.md"
        if not report_path.exists():
            create_fallback_report(report_path, ctx.task.prompt, "", error_msg)

    def _finalize_status(self, ctx: RuntimeContext, status: str, error_msg: str) -> str:
        """Determine final status based on artifacts and errors."""
        out_dir = ctx.out_dir
        has_report = (out_dir / "REPORT.md").exists()
        has_submission = (out_dir / "submission.csv").exists()

        if status == "success" and not error_msg:
            if has_report or has_submission:
                return "success"
            return "partial"

        if has_report or has_submission:
            return "partial"

        return "failed"


PROGRAM = GeneratedHarnessProgram()


def get_program() -> GeneratedHarnessProgram:
    return PROGRAM
