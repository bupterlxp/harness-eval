# Creation Profile: Claude Code Atomic Scaffold

This profile adds a reusable `harness_scaffold/` runtime to the workspace. It
comes from an authorized extraction of Claude Code atomic capabilities:
file I/O, shell, search, patch, git, artifacts, trajectory logging, budget,
permission, timeout, LLM client, adapters, and validation-related utilities.

You may choose to:

- Use the `harness_scaffold` runtime CLI directly.
- Reuse its tools, schemas, adapters, or validation utilities.
- Study its implementation and write a traditional `harness/` package.
- Ignore it if you still produce a runnable harness that satisfies the unified
  interface and downstream BMK contracts.

This is not a Claude Code cloning task and not a template-filling task. The
goal is to create a real agent harness for the target domain.

## Available Resources

The workspace contains:

```text
harness_scaffold/
CLAUDE_CODE_SCAFFOLD.md
```

If you use the scaffold runtime directly:

```bash
python -m harness_scaffold.adapters.cli \
  --task-json task.json \
  --program generated_program.py \
  --out-dir output
```

Traditional structure is also acceptable:

```bash
python -m harness -p "<natural language task>" --workdir <task workspace> --output-dir <artifact output dir>
```

## Downstream Interface

The final artifact must support:

```bash
python -m harness \
  -p "<natural language task>" \
  --workdir <task workspace> \
  --output-dir <artifact output dir> \
  --max-steps <n>
```

Alias support:

- `-p` and `--prompt`
- `--workdir`, `--work-dir`, `--workspace`
- `--max-steps`, `--max-turns`

Every run must write:

- `result.json`: status, errors, key artifact paths, structured metrics.
- `trajectory.jsonl`: action/observation records or equivalent execution trace.
- `stdout.log` and `stderr.log`, or equivalent logs.
- Domain artifacts such as patches, code files, `submission.csv`, `REPORT.md`,
  `risk_scores.csv`, images, evidence, or browser result files.

## BMK Dev Feedback Self-Test

The workspace provides `DEV_BMK_COMMANDS.md` and `run_dev_bmk.py`. You may run
a small public/dev subset of real BMKs and inspect score, stdout/stderr, raw
results, artifacts, and trajectory to judge whether the harness is usable.

During self-testing and revision, at minimum check:

- syntax, import, and CLI probe behavior
- `result.json`, `trajectory.jsonl`, stdout/stderr logs
- at least one real tool call or auditable action trace
- no TODO-only, stub-only, or `NotImplementedError` runnable path
- budget respected; no infinite loops
- best-effort artifacts and errors preserved on failure

There is no external public gate or repair controller that will fix the
harness for you. Run dev BMK feedback, read the evidence, modify the harness,
test again, and write or say `FINISH` when the final harness is ready for
formal evaluation.

## Domain Postconditions

- Code: make real file changes or patches, run tests/build/verifier when
  feasible, and record diffs, commands, and results.
- Data analysis: read data and compute real outputs; produce structured
  result files and reports rather than process-only descriptions.
- Writing: include plan/draft/critique/revision or an equivalent writing
  process; final text must be non-empty and satisfy task constraints.
- Research: include search/evidence traces and grounded sources.
- Browser: include action trace, state changes, and final result.

Success must come from real execution and real artifacts. A fixed template,
file list, or execution plan is not success.
