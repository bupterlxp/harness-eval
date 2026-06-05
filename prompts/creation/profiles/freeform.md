# Creation Profile: Freeform

This is the weakest scaffold setting. You receive only the task objective,
tool boundary, and output contract. You must decide the code structure,
execution loop, context management strategy, tool policy, verifier, and
failure-recovery behavior.

Even in freeform mode, the final harness must satisfy the unified interface:

- `python -m harness -p "<task>" --output-dir <dir>` works.
- `--workdir`, `--work-dir`, and `--workspace` are accepted.
- `--max-steps` and `--max-turns` are accepted.
- `result.json`, `trajectory.jsonl`, stdout/stderr logs, and real
  task-specific artifacts are written.
- Do not generate only documentation or a template report and mark it success.

This profile is for ablation. It is not the recommended main experiment
setting.
