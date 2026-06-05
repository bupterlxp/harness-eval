# Agent Harness Construction Task: Writing Agent

Build a general writing harness for creative writing, role-play, emotional
intelligence responses, long-form continuation, rewriting, revision, and style
control. It must output real user-readable prose that can be scored by
WritingBench and EQbench3.

The minimum success criterion is not documentation. It is a runnable harness
program that produces a final writing artifact.

## Scaffold-Native Minimum Requirements

If the active creation profile is `claude_code_scaffold_native`, the workspace
contains:

```text
generated_program.py
scaffold_manifest.json
harness_scaffold/
harness/__main__.py
```

You must implement `GeneratedHarnessProgram.run(...)` in
`generated_program.py`.

Requirements:

- Remove `NotImplementedError`, TODOs, and stub fallbacks.
- Use the `harness_scaffold` runtime for execution, LLM calls, artifact
  writing, and trajectory logging.
- Additional modules such as `planner.py`, `critic.py`, `memory.py`,
  `style.py`, and `verifier.py` are allowed only if called by the program.
- Do not deliver only README files, architecture notes, or disconnected helper
  modules.
- Do not return "Task completed", "Here is the plan", JSON metadata, adapter
  logs, or short status messages as the writing artifact.
- If the task cannot be fully satisfied, return `partial` or `failed`, write a
  best-effort text, error reason, and diagnostic trajectory.

## Unified Entry Point

```bash
python -m harness \
  -p "<writing task>" \
  --output-dir <output_dir> \
  --max-steps <n>
```

The prompt may include:

- story, chapter, scene, or web-novel continuation
- role-play or emotional intelligence writing
- long-form planning, continuation, rewriting, polishing, compression, or
  expansion
- genre, style, tone, structure, length, character, taboo, or formatting
  constraints

## Required Artifacts

Every run must write:

- `result.json`: machine-readable status, trajectory path, final text path,
  errors, and key metrics.
- `trajectory.jsonl`: plan/draft/critique/revision/final events or equivalent.
- `response.md` or `final.md`: final user-readable prose.
- Optional: `plan.json`, `critique.md`, `revision.md`, `style_notes.json`,
  `quality_scores.json`.

Minimum `result.json`:

```json
{
  "status": "success | partial | failed",
  "trajectory": "trajectory.jsonl",
  "artifacts": {
    "final_text": "response.md"
  }
}
```

`success` requires:

- final writing artifact exists
- final artifact is prose, not logs, plan, JSON, or execution summary
- final artifact satisfies task structure and length constraints
- trajectory records an actual writing process
- result points to the final artifact

## Minimum Useful Behavior

`GeneratedHarnessProgram.run(ctx, tools, llm)` should:

1. Parse writing goal, audience, genre, role, style, length, structure, and hard
   constraints.
2. Produce a compact plan or outline.
3. Draft the answer.
4. Critique the draft against task constraints.
5. Revise or regenerate when constraints fail.
6. Write final prose to `response.md` or `final.md`.
7. Write `result.json` and `trajectory.jsonl`.

For EQbench3-style tasks, preserve emotional nuance, theory of mind, role
consistency, and empathy across turns. For WritingBench-style tasks, optimize
for instruction following, structure, coherence, style, and usefulness.

## Verifier Requirements

Implement `verify_artifacts` or equivalent checks:

- final text file exists
- final text length is above a reasonable minimum
- final text is not JSON, logs, metadata, or a short status message
- required structure appears when requested
- `result.json` references the final text
- trajectory records plan, draft, critique, and final phases or equivalents

If checks fail, do not return `success`.

## Forbidden Behavior

- Do not keep the scaffold seed stub.
- Do not leave `raise NotImplementedError` in `generated_program.py`.
- Do not only write README files or helper modules.
- Do not write `response.md` as "task completed" or "see logs".
- Do not use metadata, trajectory, stdout, or stderr as the final prose.
- Do not hard-code benchmark answers, fixed prompts, or fixed outputs.
- Do not overfit to one dev task.

## Creation Self-Test

Use `DEV_BMK_COMMANDS.md` and `run_dev_bmk.py` to run public/dev
WritingBench or EQbench3 tasks. Inspect scores, stdout/stderr, trajectory, and
artifacts. Modify the harness yourself until it consistently produces
scoreable prose, then write or say `FINISH`.
