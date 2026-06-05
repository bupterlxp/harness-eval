# Creation Profile: Claude Code Scaffold Native

This is the strongest scaffold setting. The workspace already contains
`harness_scaffold/`, an authorized fixed runtime extracted from Claude Code
atomic capabilities. Build the harness on top of this runtime instead of
bypassing it and rewriting an unrelated agent system from scratch.

The experiment tests whether an LLM can perform high-level harness design on a
strong atomic substrate:

- planning
- tool selection
- context organization
- verification
- recovery
- artifact construction

The scaffold should prevent failures caused by low-level file I/O, logging,
stdout contracts, CLI wiring, trajectory writing, and budget plumbing.

## Fixed Runtime

The workspace contains:

```text
harness_scaffold/
generated_program.py
scaffold_manifest.json
harness/__main__.py
CLAUDE_CODE_SCAFFOLD.md
```

`harness_scaffold/` provides atomic capabilities:

- file read/write/edit
- glob / grep / tree
- bash / python execution
- patch / git diff / git status
- JSON I/O, artifact writing, trajectory logging
- budget, timeout, permission, retry
- LLM client
- web search / web fetch
- browser, notebook, LSP
- task graph, checkpoint / rollback
- context compaction
- domain artifact validators
- dev feedback and failure-report parsing
- cost tracking

You may add custom tools, modules, policy files, and verifiers, but new
capabilities should be registered with or called through the scaffold runtime.
Do not ignore `harness_scaffold/` and build an unrelated independent tool
system.

## Required Scaffold-Native Contract

The final artifact must satisfy:

```text
scaffold_manifest.json points to a program file.
The program exposes PROGRAM or get_program().
program.run(ctx, tools, llm) uses RuntimeContext / ToolRegistry / HarnessResult.
python -m harness ... is a compatibility wrapper that still calls harness_scaffold.
```

Recommended primary edit target:

```text
generated_program.py
```

You may add:

```text
policy.py
planner.py
context_manager.py
verifier.py
recovery.py
custom_tools.py
```

`scaffold_manifest.json` must still point to the final program.

## Allowed Extensions And Forbidden Bypasses

Allowed:

- Implement domain-specific control flow in `generated_program.py`.
- Use `tools.dispatch(...)` or registry tools to perform real actions.
- Add custom tools and call them from the program.
- Add domain verifiers, artifact writers, context packing, memory/state
  modules.
- Improve `harness/__main__.py` wrapper compatibility if needed.

Forbidden:

- Completely ignore `harness_scaffold/` and write an unrelated
  `harness/tools.py` plus independent loop.
- Output only a traditional `harness/` package without a scaffold program.
- Treat a fixed template, file list, or execution plan as success.
- Bypass trajectory, result, and artifact contracts.

## Downstream Interface

External BMK runners still call:

```bash
python -m harness \
  -p "<natural language task>" \
  --workdir <task workspace> \
  --output-dir <artifact output dir> \
  --max-steps <n>
```

This entrypoint must work, but it should invoke the scaffold runtime. It is a
compatibility layer, not a second independent implementation.

## Output Contract

Every run must write:

- `result.json`: status, errors, key artifact paths, structured metrics.
- `trajectory.jsonl`: action/observation or equivalent execution trace.
- `stdout.log` and `stderr.log`, or equivalent logs.
- Domain artifacts: patch/code files, `submission.csv`, `REPORT.md`,
  `risk_scores.csv`, charts, evidence, or browser result files.

## Domain Postconditions

- Code: inspect the repo, modify files or write a patch, run tests or verifier
  when feasible, and output changed files, diff/patch, commands, and results.
- Data analysis / MLE: read train/test/sample submission. If
  `sample_submission.csv` exists, output a compatible `submission.csv` with
  matching columns, row count, ID order, and value domain. Do not mark an
  unsupported all-constant fallback as high-quality success.
- Data analysis / DAComp: read data and compute numeric outputs. Reports must
  contain concrete values, tables, or structured decisions, not only workflow
  templates.
- Writing: the final writing artifact must be user-readable prose, not JSON,
  adapter logs, or execution summaries. Include plan/draft/critique/revision or
  an equivalent process.
- Research: record search, reading, evidence, or citation traces. Answers must
  be source-traceable.
- Browser: record navigate/click/type/extract actions and final state/result
  artifacts.

## Downstream BMK Dev Feedback Loop

The workspace provides `DEV_BMK_COMMANDS.md` and `run_dev_bmk.py`. They allow
you to run a small public/dev subset of real BMKs during creation and inspect
score, stdout/stderr, trajectory, artifacts, and raw results.

This is not a public validation gate and there is no external repair
controller. You must decide:

- when to run `python3 run_dev_bmk.py --bench auto --max-tasks 3`
- how to read BMK score, logs, failed artifacts, and trajectories
- how to modify `generated_program.py`, policy, verifier, context, recovery, or
  custom tools
- when to run dev BMK again
- when the harness is ready for formal evaluation, signaled by writing or
  saying `FINISH`

Do not hard-code dev task IDs, instance IDs, answers, or fixed outputs. Formal
evaluation will run the final harness on isolated BMK subsets and will not give
you another chance to modify the harness.
