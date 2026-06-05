# Agent Harness Construction Task: Data Analysis Agent

Build a general data-analysis harness that accepts datasets and analysis
instructions, explores the data, runs computation, creates artifacts, and
produces benchmark-readable outputs.

The harness will be evaluated on MLE-bench-like and DAComp-like tasks. Scores
come from real artifacts such as `submission.csv`, structured reports, tables,
and judge-readable results, not from process descriptions.

## Scaffold-Native Minimum Requirements

If the active creation profile is `claude_code_scaffold_native`, implement
`GeneratedHarnessProgram.run(...)` in `generated_program.py` on top of
`harness_scaffold`.

Requirements:

- Remove `NotImplementedError`, TODOs, and stub fallbacks.
- Use scaffold tools for file discovery, Python/pandas execution, artifact
  validation, and result writing.
- Additional modules are allowed only if called by `generated_program.py`.
- Do not deliver only README files, architecture notes, or disconnected helper
  modules.
- Every run must write `result.json`, `trajectory.jsonl`, logs, and real
  artifacts such as `submission.csv`, `REPORT.md`, `analysis_summary.json`,
  `metrics.csv`, or plots.
- Fallback submissions or reports may be returned as `partial`, but unsupported
  constants, templates, and process summaries must not be marked high-quality
  success.

## Unified Entry Point

```bash
python -m harness -p "<task description>" --output-dir ./output/
```

Required options:

- `-p` / `--prompt`
- `--output-dir`
- `--workdir`, `--work-dir`, `--workspace`
- `--max-steps`, `--max-turns`

If no workdir is provided, use the current directory.

Minimum `result.json`:

```json
{
  "status": "success | partial | failed",
  "trajectory": "trajectory.jsonl",
  "artifacts": {},
  "report_path": "",
  "submission_path": "",
  "error": ""
}
```

## Data BMK Execution Contract

The harness must:

- Discover `*.csv`, `*.tsv`, `*.json`, `*.parquet`, `*.xlsx`, `*.sqlite`,
  `*.db`, `train*`, `test*`, `sample_submission*`, `README*`, and
  `instructions*`.
- Treat `--workdir` as the root for input data and task files.
- Write all final artifacts under `--output-dir`, and store absolute artifact
  paths in `result.json`.
- On failure, still write `result.json`, `trajectory.jsonl`, error logs, and a
  best-effort report.

## MLE-Bench Artifact Contract

If `sample_submission.csv` exists or the task asks for a submission:

- Read the sample submission columns, row count, ID order, and target columns.
- Produce `submission.csv` with the same schema.
- Write its path to `result.json.submission_path`.
- If modeling fails, use an explainable baseline such as majority class, mean,
  median, or training-set statistics. Do not return no submission.
- In `REPORT.md`, describe data used, feature processing, model or baseline,
  validation strategy, and known limitations.

The prediction value domain must match the sample/task contract. For example,
boolean labels must be booleans, not probabilities.

## DAComp Artifact Contract

For open-ended data-analysis reports:

- Generate `REPORT.md` with problem understanding, data checks, key
  calculations, conclusions, and limitations.
- Generate at least one machine-readable artifact such as
  `analysis_summary.json`, `metrics.csv`, `risk_scores.csv`, or
  `credit_allocation.csv`.
- Save charts under `--output-dir` and reference them in the report.

For credit, invoice, or business-risk tasks, include:

- entity-level metric table
- risk-tier rule, such as A/B/C or low/medium/high
- credit allocation plan whose total matches the stated budget
- interest-rate or pricing policy tied to risk and churn
- conclusion table with entity counts, allocation share, suggested rate, and
  risk explanation
- a machine-readable summary file

Low-quality reports must fail internal verification:

- only listing files
- only listing steps
- no real calculations
- no numeric results
- no entity-level or group-level table when the task asks for decisions
- generic template conclusions

## Core Harness Behavior

Implement a Plan-Code-Observe loop:

1. Parse the task and expected artifact type.
2. Discover files and infer schema.
3. Build a compact data summary.
4. Execute Python/pandas or SQL in a controlled workspace.
5. Validate intermediate outputs.
6. Train or compute a baseline/model when needed.
7. Write final submission/report/tables/charts.
8. Verify artifact schema and semantic minimums.
9. Write result and trajectory.

The harness should keep a stateful Python namespace when useful, capture stdout
and exceptions, and summarize large tables rather than putting full data into
LLM prompts.

## Failure Recovery

Handle:

- missing files
- malformed CSV/JSON
- wrong encodings
- large tables
- failed model training
- missing optional packages
- invalid submission schema
- report-only output where a submission is required

Always preserve logs, attempted commands, and best-effort artifacts.

## Dev BMK Feedback

During creation, use `run_dev_bmk.py` to run public/dev MLE-bench and DAComp
tasks. Inspect submission validity, DAComp scores, stdout/stderr, artifacts,
and trajectory. Modify the harness yourself until it reliably produces
benchmark-readable artifacts, then write or say `FINISH`.
