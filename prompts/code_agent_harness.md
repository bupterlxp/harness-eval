# Agent Harness Construction Task: Code Agent

Build a general code-agent harness that accepts software engineering tasks
such as bug fixing, feature development, refactoring, test repair, and
repository modification. It must modify the actual workspace and verify the
result when possible.

The harness will be evaluated on SWE-bench-like and TerminalBench-like tasks.
The real product is the modified repository or required output file, not a
written explanation.

## Scaffold-Native Minimum Requirements

If the active creation profile is `claude_code_scaffold_native`, the workspace
already contains `generated_program.py`, `scaffold_manifest.json`, and
`harness_scaffold/`. You must directly implement
`GeneratedHarnessProgram.run(...)` in `generated_program.py`.

Requirements:

- Remove or replace `raise NotImplementedError`, TODOs, and stub fallbacks.
- Use the `harness_scaffold` runtime to inspect, edit, and verify code tasks.
- Additional modules are allowed, but they must be called by
  `generated_program.py`.
- Do not deliver only README files, architecture notes, or disconnected helper
  modules.
- Every run must write `result.json`, `trajectory.jsonl`, logs, patch or
  changed files, commands run, and test/verifier results.
- If the task cannot be fully solved, return `partial` or `failed` and keep
  diagnostic artifacts. Do not exit silently.

## Unified Entry Point

```bash
python -m harness -p "<task description>" --output-dir ./output/
```

Required options:

- `-p` / `--prompt`: natural language task.
- `--output-dir`: artifact directory.
- `--workdir`, `--work-dir`, `--workspace`: repository root.
- `--max-steps`, `--max-turns`: execution budget.

If no workdir is passed, use the current directory.

Minimum `result.json`:

```json
{
  "status": "success | partial | failed",
  "trajectory": "trajectory.jsonl",
  "artifacts": {},
  "changed_files": [],
  "commands_run": [],
  "tests": {}
}
```

## Code BMK Execution Contract

The harness must work inside downstream code benchmark runners:

- All file reads, writes, tests, and patch application must happen inside the
  workdir.
- If the task explicitly asks for a path such as `/app/gpt2.c`, `src/foo.py`,
  or `tests/test_x.py`, create a best-effort version of that file within the
  first three execution steps, then improve it.
- For SWE-style tasks, produce a patch or directly modify repository files.
- For Terminal-style tasks, create or modify the exact final files requested by
  the task.
- Do not write only `response.md`, `REPORT.md`, or natural language and mark
  the task as complete.
- `success` requires the requested file or patch to exist, a feasible
  syntax/build/test/verifier command to have been attempted, and evidence to be
  recorded in `result.json`.
- If dependencies are missing or tests cannot run, keep the code changes,
  patch, and failure logs and return `partial`.

When a task requires a compilable program, first write a minimal compilable
version, then iterate toward correctness. Do not spend the whole budget only
exploring.

## Minimum Tool Set

Implement and actually use these tools or equivalent scaffold tools:

- `list_files`, `read_file`, `search_text`
- `write_file`, `edit_file`, `apply_patch`
- `run_command`
- `finish`

All tool calls must be written to `trajectory.jsonl`. The LLM decides and
generates edits, but file changes must be applied by tools.

`verify_artifacts` or an equivalent verifier must check:

- explicit target files exist
- target files are non-empty
- patches or diffs exist for repo-editing tasks
- syntax/build/test/verifier commands were attempted when feasible

If the target file is missing, return failure. Do not treat `response.md` as a
code task completion.

## Core Harness Behavior

A mature code-agent harness should run a structured ReAct-style loop:

1. Parse the task and extract explicit paths, tests, constraints, and success
   criteria.
2. Inspect the repository with bounded file listing and search.
3. Build a compact context with relevant files, symbols, tests, and error logs.
4. Plan edits and update a task state object.
5. Apply patches or write files.
6. Run the most relevant verifier, test, compile, or lint command.
7. Diagnose failures and retry with a different strategy.
8. Stop only when success criteria are met or the budget is exhausted.
9. Write final diff, command logs, result, and trajectory.

## Failure Recovery

The harness should handle:

- missing dependencies
- failing tests
- syntax errors
- patch conflicts
- repeated no-op edits
- command timeouts
- excessive context
- uncertain repository structure

Use rollback/checkpoint when editing. If a patch breaks syntax, revert or
repair it. If a command fails, capture stderr and feed the concise failure
summary into the next step.

## Dev BMK Feedback

During creation, use `run_dev_bmk.py` from the workspace to run public/dev code
BMK tasks such as TerminalBench or SWE-bench-compatible tasks. Inspect
`summary.csv`, `summary.jsonl`, raw logs, diff artifacts, and trajectory, then
modify the harness yourself. When the harness is ready for formal eval, write
or say `FINISH`.
