# Agent Harness Construction Task: Data Analysis Agent

Build a general data-analysis harness that accepts datasets and analysis
instructions, explores the data, runs computation, creates artifacts, and
produces benchmark-readable outputs.

The harness will be evaluated on MLE-bench: real Kaggle competitions scored by
the official MLE-bench grader (`grade_csv`). The score comes from one artifact
only: a `submission.csv` that the official grader accepts and can compute a
numeric metric from. Reports, plans, and process descriptions earn nothing.

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
  artifacts. For competition tasks the primary artifact is `submission.csv`;
  `REPORT.md` and summary tables are secondary diagnostics.
- Fallback submissions may be returned as `partial`, but they must still be
  grader-valid. Unsupported constants, templates, and process summaries must
  not be marked high-quality success.

## Runtime LLM Requirement

The harness must use the runtime LLM provided by the scaffold (the `llm`
object passed to `GeneratedHarnessProgram.run`) as its reasoning engine —
for example task interpretation, strategy selection, code or content
generation, and self-review. How you use it is your design decision, but a
harness that completes tasks without a single LLM call is a hard-coded
pipeline, not a harness, and is non-compliant: downstream eval records
`llm_used=false` for such runs and they are excluded from harness-quality
comparison.

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
  `*.db`, `train*`, `test*`, `sample_submission*`, `README*`,
  `description*`, and `instructions*`.
- Treat `--workdir` as the root for input data and task files.
- Write all final artifacts under `--output-dir`, and store absolute artifact
  paths in `result.json`.
- On failure, still write `result.json`, `trajectory.jsonl`, error logs, and a
  best-effort report.

## MLE-Bench Grader Contract

Matching `sample_submission.csv` columns, row count, and ID order is necessary
but NOT sufficient. The official grader enforces competition-specific
semantics that the sample file alone does not reveal. The harness must:

- Read the full competition description / task instructions before modeling.
  The required submission semantics are defined there and in the metric, not
  only in `sample_submission.csv`.
- Detect the prediction value type the grader expects and produce it exactly:
  - class labels as strings vs. probabilities as floats;
  - multi-class probability columns that must form a distribution;
  - run-length-encoded (RLE) mask strings for segmentation tasks — an empty
    or integer cell where an RLE string is expected makes the whole
    submission invalid;
  - ordered ID sequences for ranking/ordering tasks — the predicted sequence
    must contain exactly the same elements as the ground truth, in the
    predicted order;
  - free-text answers for QA/normalization tasks.
- Never submit degenerate constant predictions when the metric is a
  correlation or rank statistic (Spearman, Pearson, AUC over a single class):
  constants make the metric NaN or undefined and score zero. The fallback for
  such metrics must still produce varying predictions (e.g. a simple feature
  - based model or noisy baseline derived from training statistics, recorded
  honestly in the report).
- Validate the finished `submission.csv` before declaring success: same row
  count and IDs as the sample, no missing/NaN cells, value types and ranges
  consistent with the description, predictions not all identical unless the
  task genuinely allows it.
- Write the submission path to `result.json.submission_path`.
- If modeling fails, fall back to the strongest grader-valid baseline
  available (majority class, per-group mean/median, training-set statistics)
  rather than returning no submission — but keep the value-type and
  non-degeneracy rules above.

In `REPORT.md`, describe data used, feature processing, model or baseline,
validation strategy, and known limitations.

## Core Harness Behavior

Implement a Plan-Code-Observe loop:

1. Parse the task, the competition description, and the expected submission
   semantics.
2. Discover files and infer schema.
3. Build a compact data summary.
4. Execute Python/pandas or SQL in a controlled workspace.
5. Validate intermediate outputs.
6. Train or compute a baseline/model when needed.
7. Write the final submission and diagnostics.
8. Verify the submission against the grader contract above.
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

During creation, use `run_dev_bmk.py --bench mle_bench` to run public/dev
MLE-bench tasks. Inspect `valid_submission`, the numeric score, grader
stdout/stderr, artifacts, and trajectory. A run where `valid_submission` is
false or the score is null/NaN is a failure signal you must fix. Modify the
harness yourself until it reliably produces grader-valid submissions, then
write or say `FINISH`.
