# Claude Code Atomic Scaffold

This workspace includes a reusable `harness_scaffold/` runtime distilled from
authorized Claude Code source for academic research. It is available as an
optional implementation aid for harness creation.

You may use it, inspect it, copy parts of it, wrap it, or ignore it. The final
generated harness only needs to satisfy the public downstream interface:

```bash
python -m harness -p "<task>" --workdir <workspace> --output-dir <output_dir> --max-steps <n>
```

If you choose to use the scaffold directly, the stable runtime CLI is:

```bash
python -m harness_scaffold.adapters.cli \
  --task-json task.json \
  --program generated_program.py \
  --out-dir output
```

The scaffold provides atomic runtime capabilities such as file tools, shell,
search, patching, git diff/status, artifact writing, trajectory logging,
timeouts, budgets, permission checks, optional LLM clients, and a strict stdout
contract. These capabilities are resources, not mandatory APIs.

Before downstream BMK, generated harnesses are checked for real execution
evidence: runnable syntax/import/CLI, `result.json`, `trajectory.jsonl`,
stdout/stderr logs, non-empty domain artifacts, no TODO/stub-only output, and
budget-respecting tool/action traces.
