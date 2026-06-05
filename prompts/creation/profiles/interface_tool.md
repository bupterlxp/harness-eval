# Creation Profile: Interface + Tool Scaffold

This setting fixes the interface, tool API contract, logging/result schema, and
budget boundary. The model generates the harness decision layer.

## Fixed Runtime Boundary

The generated harness must support:

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
- `trajectory.jsonl`: one action/observation JSON record per line.
- `stdout.log` and `stderr.log`, or equivalent logs.
- Domain artifacts: patch/code files, `submission.csv`, `REPORT.md`,
  `risk_scores.csv`, images, evidence, or browser result files.

## Recommended Tool Protocol

Use a provider-agnostic JSON action loop rather than provider-specific function
calling:

```json
{"thought": "...", "action": "read_file", "args": {"path": "src/app.py"}}
{"thought": "...", "action": "write_file", "args": {"path": "src/app.py", "content": "..."}}
{"thought": "...", "action": "run_command", "args": {"cmd": "python -m pytest -q"}}
{"thought": "...", "action": "finish", "args": {"status": "success"}}
```

Domain tools may vary, but the harness must execute tools for real:

- Code: `list_files`, `read_file`, `search_text`, `write_file`,
  `edit_file`, `apply_patch`, `run_command`.
- Data: `discover_files`, `summarize_table`, `execute_python`,
  `write_report`, `write_csv`, `create_chart`.
- Research: `search_web`, `read_url`, `extract_evidence`, `write_report`.
- Browser: `navigate`, `click`, `type_text`, `extract_table`, `screenshot`.
- Writing: `plan_outline`, `draft_section`, `critique`, `revise`,
  `write_final`.

## Required Model-Generated Capabilities

Do not fill a template. Implement runnable logic for:

- execution/control loop
- context manager and context packing
- state tracking
- tool-use policy
- verifier/self-check
- retry/fallback/recovery
- final artifact construction

## Finish Condition

`finish` is allowed only after postconditions are met:

- A domain-specific artifact exists and is non-empty.
- A feasible validator/test/grader has run, or the reason it cannot run is
  recorded.
- `result.json` points to real artifacts.
- `trajectory.jsonl` records at least one real tool action.

If the model call or verification fails, write `partial` or `failed` and keep
best-effort artifacts and diagnostic logs. Do not treat templates, file lists,
or step lists as success.
