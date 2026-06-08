# Downstream BMK Dev Feedback Commands

This workspace provides real public/dev benchmark feedback for harness creation.

There is no public-validation gate and no external repair controller. You, the
meta harness + LLM creation agent, should decide when to test, how to read the
results, how to revise the harness, and when to stop.

## Default command

```bash
python3 run_dev_bmk.py --bench auto --max-tasks 3
```

`auto` selects the public/dev BMKs for this creation task:

```text
mle_bench
```

You may also choose a specific BMK:

```bash
python3 run_dev_bmk.py --bench mle_bench --max-tasks 3
python3 run_dev_bmk.py --bench terminal_2_bench --max-tasks 3
python3 run_dev_bmk.py --bench browsecomp --max-tasks 3
```

## What to inspect

Each run writes under `dev_bmk_runs/<timestamp>/`:

- `summary.csv`
- `summary.jsonl`
- `validation.json` with minimal adapter/CLI status only
- per-BMK stdout/stderr/raw result artifacts

Use these files, plus any generated `trajectory.jsonl`, harness artifacts, and
stdout/stderr, to decide what to change.

## Finish condition

When you believe the harness is ready for formal downstream eval, write or say
`FINISH` and leave the final harness files in this workspace. The outer runner
will freeze the workspace after your Claude Code task exits.
