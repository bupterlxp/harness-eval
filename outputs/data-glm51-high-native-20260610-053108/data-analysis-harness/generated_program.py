"""Scaffold-native generated harness program for data analysis tasks.

Implements a Plan-Code-Observe loop using harness_scaffold tools:
1. Parse task and infer artifact type
2. Discover files and summarize data
3. Execute Python/pandas analysis or modeling
4. Generate submission.csv / REPORT.md / analysis artifacts
5. Validate artifacts against domain contracts
6. Write result.json and finalize outputs
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Optional

from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.errors import ErrorCode
from harness_scaffold.core.schemas import HarnessResult, HarnessStatus
from harness_scaffold.examples._common import make_result, try_tool
from harness_scaffold.tools.registry import ToolRegistry

from planner import ExecutionPlan, TaskType, build_plan
from context_manager import build_data_context, parse_sample_submission, summarize_file
from verifier import validate_artifacts
from recovery import create_baseline_submission, create_minimal_report, create_analysis_summary_json
from custom_tools import get_custom_tools


class GeneratedHarnessProgram:
    name = "data-analysis-harness"

    # Maximum LLM interaction rounds per step
    MAX_LLM_ROUNDS = 5
    # Maximum characters for context sent to LLM
    MAX_CONTEXT_CHARS = 30_000
    # Maximum python_exec timeout for analysis scripts
    ANALYSIS_TIMEOUT = 120

    async def run(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        llm: Optional[object],
    ) -> HarnessResult:
        """Main harness execution: Plan-Code-Observe loop."""
        status: HarnessStatus = "success"
        error_msg = ""
        answer_path: Optional[Path] = None
        error_path: Optional[Path] = None

        # Register custom tools
        for tool in get_custom_tools():
            if not tools.has(tool.name):
                tools.register(tool, override=False)

        ctx.trajectory.log_step(0, phase="start", note=self.name)

        try:
            # Phase 1: Build plan
            ctx.step()
            plan = build_plan(ctx.task.prompt, ctx.workdir, max_steps=ctx.budget.max_steps)
            ctx.trajectory.log_info(
                "plan_built",
                task_type=plan.task_type.value,
                needs_submission=plan.needs_submission,
                needs_model=plan.needs_model,
                num_steps=len(plan.steps),
            )

            # Phase 2: Discover and summarize data
            data_context = await self._discover_and_summarize(ctx, tools, plan)

            # Phase 3: Parse sample submission if MLE task
            sample_info: dict[str, Any] = {}
            if plan.needs_submission and plan.sample_submission_path:
                sample_info = parse_sample_submission(plan.sample_submission_path)
                ctx.trajectory.log_info("sample_parsed", **{k: str(v) for k, v in sample_info.items()})

            # Phase 4: Execute analysis via LLM-guided or scripted approach
            analysis_result: dict[str, Any] = {}
            report_content = ""
            submission_path: Optional[Path] = None

            if llm is not None:
                analysis_result, report_content, submission_path = await self._llm_guided_analysis(
                    ctx, tools, llm, plan, data_context, sample_info
                )
            else:
                analysis_result, report_content, submission_path = await self._scripted_analysis(
                    ctx, tools, plan, data_context, sample_info
                )

            # Phase 5: Generate fallback artifacts if needed
            report_path = ctx.out_dir / "REPORT.md"
            if report_content:
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(report_content, encoding="utf-8")
                ctx.artifact_store.register("REPORT.md", report_path, kind="report")
            elif not report_path.exists():
                report_content = create_minimal_report(
                    report_path,
                    prompt=ctx.task.prompt,
                    data_summary=data_context[:2000],
                    findings=analysis_result.get("findings", []),
                    error_msg=error_msg,
                ).read_text(encoding="utf-8", errors="replace")
                ctx.artifact_store.register("REPORT.md", report_path, kind="report")

            # Ensure submission.csv exists if needed
            if plan.needs_submission and plan.sample_submission_path:
                sub_path = ctx.out_dir / "submission.csv"
                if submission_path and submission_path.exists():
                    if submission_path != sub_path:
                        import shutil
                        sub_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(submission_path, sub_path)
                    elif not sub_path.exists():
                        import shutil
                        sub_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(submission_path, sub_path)
                if not sub_path.exists():
                    baseline_result = create_baseline_submission(
                        plan.sample_submission_path, sub_path
                    )
                    ctx.trajectory.log_info(
                        "baseline_submission",
                        success=baseline_result.get("success", False),
                        strategy=baseline_result.get("strategy", ""),
                    )
                if sub_path.exists():
                    ctx.artifact_store.register("submission.csv", sub_path, kind="submission")

            # Phase 6: Generate analysis_summary.json
            summary_path = ctx.out_dir / "analysis_summary.json"
            create_analysis_summary_json(
                summary_path,
                metrics=analysis_result.get("metrics", {}),
                data_info=analysis_result.get("data_info", {}),
                error_msg=error_msg,
            )
            ctx.artifact_store.register("analysis_summary.json", summary_path, kind="json")

            # Phase 7: Validate artifacts
            validation = validate_artifacts(
                ctx.out_dir,
                needs_submission=plan.needs_submission,
                sample_submission_path=plan.sample_submission_path,
            )
            ctx.trajectory.log_info(
                "validation",
                passed=validation["passed"],
                failures=validation["failures"],
            )

            if not validation["passed"]:
                status = "partial"
                # Attempt to fix submission issues
                if plan.needs_submission and plan.sample_submission_path:
                    sub_path = ctx.out_dir / "submission.csv"
                    if not sub_path.exists():
                        create_baseline_submission(plan.sample_submission_path, sub_path)

            # Phase 8: Write result.json
            result_data = {
                "status": status,
                "trajectory": str(ctx.out_dir / "trajectory.jsonl"),
                "artifacts": {name: str(p) for name, p in ctx.artifact_store.paths().items()},
                "report_path": str(report_path) if report_path.exists() else "",
                "submission_path": str(ctx.out_dir / "submission.csv") if (ctx.out_dir / "submission.csv").exists() else "",
                "error": error_msg,
                "validation": validation,
            }
            result_path = ctx.out_dir / "result.json"
            result_path.write_text(json.dumps(result_data, ensure_ascii=False, indent=2), encoding="utf-8")
            ctx.artifact_store.register("result.json", result_path, kind="json")

            # Write response.md
            answer_path = ctx.out_dir / "response.md"
            answer_path.write_text(report_content or "# Analysis Complete\n", encoding="utf-8")

        except Exception as exc:
            status = "failed"
            error_msg = f"{type(exc).__name__}: {exc}"
            ctx.trajectory.log_error(
                {"error_code": "failed", "message": error_msg, "stage": "main"},
                step=ctx.budget.steps_used,
            )
            # Still produce best-effort artifacts
            self._write_failure_artifacts(ctx, error_msg)
            answer_path = ctx.out_dir / "response.md"

        return make_result(
            ctx,
            status=status,
            answer_path=answer_path,
            error_path=error_path,
            metadata={"error": error_msg} if error_msg else {},
        )

    async def _discover_and_summarize(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        plan: ExecutionPlan,
    ) -> str:
        """Discover files and build compact data context string."""
        ctx.step()
        ctx.trajectory.log_step(ctx.budget.steps_used, phase="discover", note="discover_and_summarize")

        # Use the data_discovery custom tool
        ok, result = await try_tool(ctx, tools, "data_discovery", {"path": str(ctx.workdir)})
        discovered = result.data if ok and result and result.ok else {}

        # Build compact context
        data_context = build_data_context(plan.data_files, max_summary_bytes=self.MAX_CONTEXT_CHARS)

        # Try reading README/instructions
        readme_content = ""
        for f in plan.data_files.get("readme", []) + plan.data_files.get("instructions", []):
            ok, result = await try_tool(ctx, tools, "file_read", {"path": str(f), "limit": 100})
            if ok and result and result.ok:
                readme_content += result.data.get("content", "") + "\n"

        if readme_content:
            data_context += f"\n\n## README / Instructions\n{readme_content[:5000]}"

        return data_context

    async def _llm_guided_analysis(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        llm: Any,
        plan: ExecutionPlan,
        data_context: str,
        sample_info: dict[str, Any],
    ) -> tuple[dict[str, Any], str, Optional[Path]]:
        """Use LLM to guide the analysis through tool calls.

        Falls back to scripted analysis if the LLM is unavailable or fails.
        """
        analysis_result: dict[str, Any] = {"metrics": {}, "findings": [], "data_info": {}}
        report_content = ""
        submission_path: Optional[Path] = None
        llm_failed = False

        # Build system prompt
        system_prompt = self._build_system_prompt(plan, sample_info)

        # Build initial user message with data context
        user_content = f"## Task\n{ctx.task.prompt}\n\n## Data Context\n{data_context[:self.MAX_CONTEXT_CHARS]}"
        if sample_info:
            user_content += f"\n\n## Sample Submission Info\n{json.dumps(sample_info, ensure_ascii=False, indent=2)}"

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        for round_idx in range(self.MAX_LLM_ROUNDS):
            if ctx.budget.steps_used >= ctx.budget.max_steps - 2:
                break
            ctx.check_abort(stage="llm_loop")

            # Call LLM
            ctx.trajectory.log_llm_call(model=getattr(llm, "model", None), step=ctx.budget.steps_used)
            try:
                response = await llm.complete(
                    messages,
                    tools=self._build_tool_specs(tools),
                    timeout=ctx.policy.max_llm_seconds,
                )
            except Exception as exc:
                ctx.trajectory.log_error(
                    {"error_code": "llm_error", "message": str(exc), "stage": "llm_call"},
                    step=ctx.budget.steps_used,
                )
                llm_failed = True
                break

            ctx.trajectory.log_llm_result(
                model=response.model,
                text_preview=(response.text or "")[:500],
                tool_calls=[tc.get("function", {}).get("name", "") for tc in response.tool_calls] if response.tool_calls else [],
                step=ctx.budget.steps_used,
            )

            # Process LLM response
            if response.text:
                messages.append({"role": "assistant", "content": response.text})
                # Check if this looks like a final report
                if "# " in response.text and len(response.text) > 200:
                    report_content = response.text

            # Process tool calls
            if response.tool_calls:
                tool_results_messages = await self._execute_tool_calls(
                    ctx, tools, response.tool_calls
                )
                messages.extend(tool_results_messages)
                # Check for submission artifact in results
                for msg in tool_results_messages:
                    if isinstance(msg.get("content"), str) and "submission" in msg.get("content", "").lower():
                        for name, path in ctx.artifact_store.paths().items():
                            if "submission" in name.lower():
                                submission_path = path
            else:
                # No tool calls - if we got text, we might be done
                if response.text and len(response.text) > 100:
                    break

        # If LLM failed, fall back to scripted analysis
        if llm_failed:
            ctx.trajectory.log_info("llm_fallback_to_scripted", note="Falling back to scripted analysis")
            return await self._scripted_analysis(ctx, tools, plan, data_context, sample_info)

        return analysis_result, report_content, submission_path

    async def _scripted_analysis(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        plan: ExecutionPlan,
        data_context: str,
        sample_info: dict[str, Any],
    ) -> tuple[dict[str, Any], str, Optional[Path]]:
        """Run analysis using scripted Python execution when no LLM is available."""
        analysis_result: dict[str, Any] = {"metrics": {}, "findings": [], "data_info": {}}
        report_content = ""
        submission_path: Optional[Path] = None

        # Step 1: Summarize all data files
        summaries = []
        for category in ("train", "test", "data"):
            for f in plan.data_files.get(category, []):
                ok, result = await try_tool(ctx, tools, "data_summarize", {"path": str(f)})
                if ok and result and result.ok:
                    summaries.append(result.data)

        # Step 2: Run exploratory data analysis via python_exec
        eda_stdout = ""
        if summaries or plan.data_files.get("data") or plan.data_files.get("train"):
            eda_code = self._build_eda_script(plan, data_context)
            ok, result = await try_tool(ctx, tools, "python_exec", {
                "code": eda_code,
                "timeout": self.ANALYSIS_TIMEOUT,
            })
            if ok and result and result.ok:
                eda_stdout = result.data.get("stdout", "") if result.data else ""
                if eda_stdout:
                    analysis_result["findings"].append(eda_stdout[:5000])

        # Step 3: Run comprehensive statistics script
        stats_code = self._build_stats_script(plan, ctx.out_dir)
        ok, result = await try_tool(ctx, tools, "python_exec", {
            "code": stats_code,
            "timeout": self.ANALYSIS_TIMEOUT,
            "env": {"HARNESS_OUT_DIR": str(ctx.out_dir)},
        })
        stats_stdout = ""
        if ok and result and result.ok:
            stats_stdout = result.data.get("stdout", "") if result.data else ""
            if stats_stdout:
                try:
                    stats_data = json.loads(stats_stdout)
                    analysis_result["metrics"] = stats_data.get("metrics", {})
                    analysis_result["data_info"] = stats_data.get("data_info", {})
                    analysis_result["findings"].extend(stats_data.get("findings", [])[:20])
                except json.JSONDecodeError:
                    analysis_result["findings"].append(stats_stdout[:3000])

        # Step 4: Build model if needed
        if plan.needs_model and plan.data_files.get("train"):
            model_code = self._build_model_script(plan, sample_info)
            ok, result = await try_tool(ctx, tools, "python_exec", {
                "code": model_code,
                "timeout": self.ANALYSIS_TIMEOUT,
                "env": {"HARNESS_OUT_DIR": str(ctx.out_dir)},
            })
            if ok and result and result.ok:
                stdout = result.data.get("stdout", "") if result.data else ""
                if stdout:
                    analysis_result["findings"].append(f"Model output: {stdout[:3000]}")
                sub_path = ctx.out_dir / "submission.csv"
                if sub_path.exists():
                    submission_path = sub_path
                # Also check workdir in case env var wasn't propagated
                workdir_sub = ctx.workdir / "submission.csv"
                if workdir_sub.exists() and not sub_path.exists():
                    import shutil
                    shutil.copy2(workdir_sub, sub_path)
                    submission_path = sub_path

        # Step 5: Generate report from findings
        report_content = self._build_report_from_findings(
            ctx.task.prompt, data_context, analysis_result, summaries, plan
        )
        ctx.step()

        return analysis_result, report_content, submission_path

    def _build_report_from_findings(
        self,
        prompt: str,
        data_context: str,
        analysis_result: dict[str, Any],
        summaries: list[dict],
        plan: ExecutionPlan,
    ) -> str:
        """Build a structured report from analysis findings with concrete numbers."""
        parts = ["# Data Analysis Report\n"]
        parts.append(f"## Task\n{prompt}\n")

        # Data summary section
        parts.append("## Data Summary\n")
        for s in summaries:
            if isinstance(s, dict):
                path = s.get("path", "unknown")
                shape = s.get("shape", "N/A")
                parts.append(f"- **{path}**: {shape}\n")
        parts.append(f"\n{data_context[:3000]}\n")

        # Key findings
        findings = analysis_result.get("findings", [])
        parts.append("## Key Findings\n")
        if findings:
            for i, f in enumerate(findings[:15]):
                text = str(f).strip()
                if text:
                    if "\n" in text:
                        parts.append(f"\n{text}\n")
                    else:
                        parts.append(f"- {text}\n")
        else:
            parts.append("- Basic data summary completed.\n")

        # Metrics table
        metrics = analysis_result.get("metrics", {})
        if metrics:
            parts.append("\n## Metrics\n")
            parts.append("| Metric | Value |\n|--------|-------|\n")
            for k, v in metrics.items():
                parts.append(f"| {k} | {v} |\n")

        # Data info
        data_info = analysis_result.get("data_info", {})
        if data_info:
            parts.append("\n## Data Details\n")
            for k, v in data_info.items():
                parts.append(f"- **{k}**: {v}\n")

        # Method
        parts.append("\n## Method\n")
        if plan.needs_model:
            parts.append("Automated data analysis with predictive modeling using scikit-learn.\n")
        else:
            parts.append("Automated exploratory analysis and descriptive statistics.\n")

        # Limitations
        parts.append("\n## Limitations\n")
        parts.append("- Analysis was performed automatically; domain expertise may improve results\n")
        parts.append("- Statistical findings should be validated with domain knowledge\n")

        return "\n".join(parts)

    def _build_system_prompt(self, plan: ExecutionPlan, sample_info: dict[str, Any]) -> str:
        """Build the system prompt for LLM-guided analysis."""
        parts = [
            "You are a data analysis expert. Analyze the provided data and produce results.",
            "",
            "## Available Tools",
            "Use the provided tools to read files, execute Python code, and write artifacts.",
            "",
            "## Required Outputs",
        ]

        if plan.needs_submission:
            parts.append("- submission.csv matching the sample_submission.csv schema")
            if sample_info:
                parts.append(f"  - Columns: {sample_info.get('columns', [])}")
                parts.append(f"  - ID column: {sample_info.get('id_column', '')}")
                parts.append(f"  - Target columns: {sample_info.get('target_columns', [])}")
                parts.append(f"  - Row count: {sample_info.get('row_count', 'unknown')}")
                parts.append(f"  - Prediction type: {sample_info.get('prediction_type', 'unknown')}")

        parts.append("- REPORT.md with findings, methodology, and limitations")
        parts.append("- analysis_summary.json with structured metrics")

        parts.extend([
            "",
            "## Guidelines",
            "- Read data files before analyzing them",
            "- Use python_exec for computations with pandas/numpy/sklearn",
            "- Always write submission.csv with the exact same columns and row order as the sample",
            "- For boolean targets, output literal True/False, not probabilities",
            "- Write REPORT.md as the final step with substantive findings",
            "- Include concrete numbers, tables, and metrics in the report",
        ])

        return "\n".join(parts)

    def _build_tool_specs(self, tools: ToolRegistry) -> list[dict[str, Any]]:
        """Build tool specs for LLM function calling."""
        allowed = {"file_read", "file_write", "python_exec", "bash", "json_io",
                    "artifact", "data_discovery", "data_summarize", "submission_gen",
                    "glob", "grep"}
        specs = []
        for tool in tools.list():
            if tool.name in allowed:
                spec = tool.spec()
                specs.append({
                    "type": "function",
                    "function": {
                        "name": spec["name"],
                        "description": spec["description"],
                        "parameters": spec["input_schema"],
                    }
                })
        return specs

    async def _execute_tool_calls(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        tool_calls: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Execute LLM-requested tool calls and return observation messages."""
        messages: list[dict[str, Any]] = []
        for tc in tool_calls:
            func = tc.get("function", {})
            name = func.get("name", "")
            args_str = func.get("arguments", "{}")
            tc_id = tc.get("id", "")

            if isinstance(args_str, str):
                try:
                    args = json.loads(args_str)
                except json.JSONDecodeError:
                    args = {}
            else:
                args = args_str

            if not tools.has(name):
                messages.append({
                    "role": "user",
                    "content": f"Tool {name} not available. Available tools: {', '.join(tools.names())}",
                })
                continue

            ctx.step()
            tool = tools.get(name)
            result = await tool.execute(ctx, args)

            # Format result for LLM
            if result.ok:
                content = json.dumps(result.data, ensure_ascii=False, default=str)[:5000] if result.data else "OK"
            else:
                content = f"Error: {json.dumps(result.error, ensure_ascii=False, default=str)[:2000]}" if result.error else "Error: tool call failed"

            messages.append({"role": "user", "content": f"[Tool: {name}] {content}"})

        return messages

    def _build_eda_script(self, plan: ExecutionPlan, data_context: str) -> str:
        """Build a Python EDA script for scripted analysis."""
        train_files = plan.data_files.get("train", [])
        test_files = plan.data_files.get("test", [])
        data_files = plan.data_files.get("data", [])

        file_lines = []
        for f in train_files:
            file_lines.append(f'    train_path = r"{f}"')
        for f in test_files:
            file_lines.append(f'    test_path = r"{f}"')
        for f in data_files:
            file_lines.append(f'    data_path = r"{f}"')

        return f'''
import pandas as pd
import json
import sys

try:
    files = {{
{chr(10).join(file_lines)}
    }}

    summaries = {{}}

    for name, path in files.items():
        try:
            if path.endswith(".csv") or path.endswith(".tsv"):
                df = pd.read_csv(path, nrows=1000)
                summaries[name] = {{
                    "shape": list(df.shape),
                    "columns": list(df.columns),
                    "dtypes": {{c: str(dt) for c, dt in df.dtypes.items()}},
                    "head": df.head(3).to_dict(orient="records"),
                    "nulls": {{c: int(df[c].isnull().sum()) for c in df.columns}},
                    "describe": df.describe().to_dict(),
                }}
            elif path.endswith(".json"):
                import json as _json
                with open(path) as f:
                    obj = _json.load(f)
                if isinstance(obj, list):
                    summaries[name] = {{"type": "array", "length": len(obj), "sample": obj[:2]}}
                elif isinstance(obj, dict):
                    summaries[name] = {{"type": "object", "keys": list(obj.keys())[:20], "num_keys": len(obj)}}
        except Exception as e:
            summaries[name] = {{"error": str(e)}}

    print(json.dumps(summaries, ensure_ascii=False, default=str, indent=2))

except Exception as e:
    print(f"EDA error: {{e}}", file=sys.stderr)
    sys.exit(1)
'''

    def _build_stats_script(self, plan: ExecutionPlan, out_dir: Path) -> str:
        """Build a comprehensive statistics script that computes metrics."""
        all_files = []
        for category in ("train", "test", "data"):
            all_files.extend(plan.data_files.get(category, []))

        if not all_files:
            return 'import json; print(json.dumps({"metrics": {}, "findings": [], "data_info": {}}))'

        file_entries = []
        for f in all_files:
            file_entries.append(f'    r"{f}"')

        return f'''
import pandas as pd
import numpy as np
import json
import sys
import os

try:
    files = [
{chr(10).join(file_entries)}
    ]

    metrics = {{}}
    data_info = {{}}
    findings = []

    for path in files:
        try:
            if not os.path.exists(path):
                continue
            if path.endswith(".csv") or path.endswith(".tsv"):
                df = pd.read_csv(path)
                name = os.path.basename(path)
                data_info[f"{{name}}_shape"] = f"{{df.shape[0]}} rows x {{df.shape[1]}} cols"

                # Numeric column statistics
                numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
                for col in numeric_cols[:10]:
                    metrics[f"{{name}}_{{col}}_mean"] = round(float(df[col].mean()), 4)
                    metrics[f"{{name}}_{{col}}_std"] = round(float(df[col].std()), 4)
                    metrics[f"{{name}}_{{col}}_min"] = round(float(df[col].min()), 4)
                    metrics[f"{{name}}_{{col}}_max"] = round(float(df[col].max()), 4)
                    findings.append(f"{{name}}: {{col}} - mean={{df[col].mean():.2f}}, std={{df[col].std():.2f}}, range=[{{df[col].min():.2f}}, {{df[col].max():.2f}}]")

                # Categorical column statistics
                cat_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()
                for col in cat_cols[:10]:
                    vc = df[col].value_counts()
                    data_info[f"{{name}}_{{col}}_unique"] = int(df[col].nunique())
                    for val, cnt in vc.head(5).items():
                        metrics[f"{{name}}_{{col}}_{{val}}_count"] = int(cnt)
                    top = vc.index[0]
                    findings.append(f"{{name}}: {{col}} has {{df[col].nunique()}} unique values, top={{top}} ({{vc.iloc[0]}}/{{len(df)}})")

                # Null summary
                nulls = df.isnull().sum()
                null_cols = nulls[nulls > 0]
                if len(null_cols) > 0:
                    findings.append(f"{{name}}: missing values - {{dict(null_cols)}}")

                # Correlation for numeric columns (top pairs)
                if len(numeric_cols) >= 2:
                    corr = df[numeric_cols[:10]].corr()
                    pairs = []
                    for i in range(len(corr.columns)):
                        for j in range(i + 1, len(corr.columns)):
                            pairs.append((abs(corr.iloc[i, j]), corr.columns[i], corr.columns[j], corr.iloc[i, j]))
                    pairs.sort(reverse=True)
                    for _, c1, c2, r in pairs[:3]:
                        findings.append(f"{{name}}: correlation {{c1}} vs {{c2}} = {{r:.3f}}")

            elif path.endswith(".json"):
                import json as _json
                with open(path) as f:
                    obj = _json.load(f)
                if isinstance(obj, list):
                    data_info[f"{{os.path.basename(path)}}_length"] = len(obj)
                    findings.append(f"{{os.path.basename(path)}}: JSON array with {{len(obj)}} items")
                elif isinstance(obj, dict):
                    data_info[f"{{os.path.basename(path)}}_keys"] = len(obj)
                    findings.append(f"{{os.path.basename(path)}}: JSON object with {{len(obj)}} keys")
        except Exception as e:
            findings.append(f"Error processing {{path}}: {{e}}")

    result = {{"metrics": metrics, "findings": findings, "data_info": data_info}}
    print(json.dumps(result, ensure_ascii=False, default=str))

except Exception as e:
    print(json.dumps({{"metrics": {{}}, "findings": [f"Stats error: {{e}}"], "data_info": {{}}}}))
    sys.exit(0)
'''

    def _build_model_script(self, plan: ExecutionPlan, sample_info: dict[str, Any]) -> str:
        """Build a Python modeling script for MLE-bench tasks."""
        train_files = plan.data_files.get("train", [])
        test_files = plan.data_files.get("test", [])
        sample_sub = plan.sample_submission_path

        if not train_files:
            return "print('No training data found')"

        train_path = train_files[0]
        test_path = test_files[0] if test_files else None
        sample_path = sample_sub

        target_cols = sample_info.get("target_columns", [])
        id_col = sample_info.get("id_column", "")
        prediction_type = sample_info.get("prediction_type", "")

        # Determine model type
        is_classification = prediction_type.startswith("classification")
        target_col = target_cols[0] if target_cols else ""

        # Build the script using string concatenation to avoid f-string nesting issues
        script_lines = [
            "import pandas as pd",
            "import numpy as np",
            "import json",
            "import sys",
            "import os",
            "",
            "out_dir = os.environ.get('HARNESS_OUT_DIR', '.')",
            "",
            "try:",
            f"    train = pd.read_csv(r'{train_path}')",
        ]
        if test_path:
            script_lines.append(f"    test_df = pd.read_csv(r'{test_path}')")
        else:
            script_lines.append("    test_df = pd.DataFrame()")
        if sample_path:
            script_lines.append(f"    sample = pd.read_csv(r'{sample_path}')")
        else:
            script_lines.append("    sample = pd.DataFrame()")

        script_lines.extend([
            "",
            "    print(f'Train shape: {train.shape}')",
            "    print(f'Test shape: {test_df.shape}')",
            "",
            f"    target_cols = {target_cols}",
            f"    id_col = '{id_col}'",
            f"    is_classification = {is_classification}",
            "",
            "    # Identify target variable",
            "    if target_cols:",
            "        y = train[target_cols[0]]",
            "    else:",
            "        y = train.iloc[:, -1]",
            "",
            "    # Map target for binary classification",
            "    if is_classification and y.dtype == object:",
            "        mapping = {'True': 1, 'False': 0, 'true': 1, 'false': 0}",
            "        y = y.map(mapping).fillna(y).astype(float)",
            "",
            "    # Prepare features",
            "    feature_cols = [c for c in train.columns if c not in target_cols and c != id_col]",
            "    X = train[feature_cols].select_dtypes(include=[np.number])",
            "    X = X.fillna(X.median())",
            "",
            "    # Choose model",
            "    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor",
            "    if is_classification:",
            "        model = RandomForestClassifier(n_estimators=100, random_state=42, max_depth=10)",
            "    else:",
            "        model = RandomForestRegressor(n_estimators=100, random_state=42, max_depth=10)",
            "",
            "    # Train",
            "    model.fit(X, y)",
            "    print(f'Model trained on {X.shape[0]} samples, {X.shape[1]} features')",
            "",
            "    # Predict on test set",
            "    if len(test_df) > 0:",
            "        X_test = test_df[feature_cols].select_dtypes(include=[np.number])",
            "        X_test = X_test.fillna(X.median())",
            "    elif len(sample) > 0:",
            "        sample_feature_cols = [c for c in sample.columns if c in feature_cols]",
            "        X_test = sample[sample_feature_cols].select_dtypes(include=[np.number])",
            "        X_test = X_test.fillna(X.median())",
            "    else:",
            "        X_test = pd.DataFrame()",
            "",
            "    if len(X_test) > 0:",
            "        test_preds = model.predict(X_test)",
            "    else:",
            "        # Fallback: constant prediction",
            "        n_rows = len(sample) if len(sample) > 0 else 100",
            "        if is_classification:",
            "            test_preds = np.full(n_rows, y.mode()[0])",
            "        else:",
            "            test_preds = np.full(n_rows, y.mean())",
            "",
            "    # Convert predictions to proper format",
            "    if is_classification:",
            "        if len(np.unique(y)) <= 2:",
            "            test_preds_labels = (test_preds > 0.5).astype(bool) if test_preds.dtype in [np.float64, float] else test_preds.astype(bool)",
            "        else:",
            "            test_preds_labels = test_preds",
            "    else:",
            "        test_preds_labels = test_preds",
            "",
            "    # Build submission",
            "    if len(sample) > 0:",
            "        submission = sample.copy()",
            "        if target_cols:",
            "            for tc in target_cols:",
            "                if tc in submission.columns:",
            "                    submission[tc] = test_preds_labels",
            "        elif len(submission.columns) > 1:",
            "            submission.iloc[:, 1] = test_preds_labels",
            "    else:",
            "        n = len(test_preds_labels)",
            "        submission = pd.DataFrame({id_col: range(n)})",
            "        if target_cols:",
            "            submission[target_cols[0]] = test_preds_labels",
            "",
            "    # Write submission",
            "    sub_path = os.path.join(out_dir, 'submission.csv')",
            "    submission.to_csv(sub_path, index=False)",
            "    print(f'Submission written: {submission.shape}')",
            "    print(f'Sample: {submission.head(3).to_dict(orient=\"records\")}')",
            "",
            "except Exception as e:",
            "    print(f'Model error: {e}', file=sys.stderr)",
            "    import traceback",
            "    traceback.print_exc(file=sys.stderr)",
            "    sys.exit(1)",
        ])

        return "\n".join(script_lines)

    def _write_failure_artifacts(self, ctx: RuntimeContext, error_msg: str) -> None:
        """Write best-effort artifacts on failure."""
        try:
            # Write a minimal report
            report_path = ctx.out_dir / "REPORT.md"
            if not report_path.exists():
                create_minimal_report(
                    report_path,
                    prompt=ctx.task.prompt,
                    error_msg=error_msg,
                )
                ctx.artifact_store.register("REPORT.md", report_path, kind="report")

            # Write analysis_summary.json
            summary_path = ctx.out_dir / "analysis_summary.json"
            if not summary_path.exists():
                create_analysis_summary_json(summary_path, error_msg=error_msg)
                ctx.artifact_store.register("analysis_summary.json", summary_path, kind="json")

            # Write result.json
            result_data = {
                "status": "failed",
                "trajectory": str(ctx.out_dir / "trajectory.jsonl"),
                "artifacts": {name: str(p) for name, p in ctx.artifact_store.paths().items()},
                "report_path": str(report_path),
                "submission_path": "",
                "error": error_msg,
            }
            result_path = ctx.out_dir / "result.json"
            if not result_path.exists():
                result_path.write_text(json.dumps(result_data, ensure_ascii=False, indent=2), encoding="utf-8")
                ctx.artifact_store.register("result.json", result_path, kind="json")
        except Exception:
            pass


PROGRAM = GeneratedHarnessProgram()


def get_program() -> GeneratedHarnessProgram:
    return PROGRAM
