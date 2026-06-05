# Agent Harness Construction Task: Research Agent

Build a general research-agent harness that accepts research questions,
performs information retrieval, evaluates sources, organizes evidence, and
produces grounded answers or structured reports.

The harness will be evaluated on DeepResearch/HLE-style and BrowseComp-style
tasks. Scores depend on answer correctness and evidence quality, not report
length.

## Scaffold-Native Minimum Requirements

If the active creation profile is `claude_code_scaffold_native`, implement
`GeneratedHarnessProgram.run(...)` in `generated_program.py` on top of
`harness_scaffold`.

Requirements:

- Remove `NotImplementedError`, TODOs, and stub fallbacks.
- Use scaffold tools for query planning, search/fetch, evidence tracking,
  answer synthesis, and verification.
- Additional modules are allowed only if called by `generated_program.py`.
- Do not deliver only README files, architecture notes, or disconnected helper
  modules.
- Every run must write `result.json`, `trajectory.jsonl`, logs, and artifacts
  such as `answer.md`, `answer.json`, `sources.json`, `evidence.json`, or an
  equivalent citation trace.
- If search APIs or web access are unavailable, record missing dependencies and
  return `partial`; do not fabricate URLs, citations, or evidence.

## Unified Entry Point

```bash
python -m harness -p "<research question>" --output-dir ./output/
```

Required options:

- `-p` / `--prompt`
- `--output-dir`
- `--max-steps`, `--max-turns`

Minimum `result.json`:

```json
{
  "status": "success | partial | failed",
  "trajectory": "trajectory.jsonl",
  "answer_path": "answer.md",
  "evidence_path": "evidence.json"
}
```

## Research BMK Execution Contract

The harness must:

- Select direct answer, structured answer, or report mode based on question
  type. Do not output a long report for every task.
- Link factual claims to evidence IDs, source URLs, or source summaries.
- Write `sources.json` or `evidence.json` containing search query, source
  title, URL, excerpt, retrieval time, and relevance notes when available.
- Record search/read/synthesize/verify events in `trajectory.jsonl`.
- Avoid unsupported claims from model memory. Use retrieved evidence or mark
  uncertainty.
- Preserve a short final answer for closed factual questions such as numbers,
  names, dates, formulas, or multiple-choice decisions.

## Core Harness Behavior

Implement a bounded research loop:

1. Parse the question and expected answer type.
2. Decompose into subquestions when needed.
3. Generate search queries.
4. Search and fetch sources.
5. Extract evidence snippets and source metadata.
6. Detect contradictions and uncertainty.
7. Synthesize an answer with citations.
8. Run self-verification against evidence.
9. Write final answer, evidence files, result, and trajectory.

The context manager must cap evidence volume, deduplicate URLs, and keep only
high-value evidence in the LLM context.

## Evidence Quality

Prefer:

- primary sources
- official documentation
- papers or benchmark-provided references
- reputable sources with clear dates

For each evidence item, store:

- `id`
- `query`
- `url`
- `title`
- `excerpt`
- `why_relevant`
- `supports` or `contradicts`

If sources disagree, state the conflict and choose the best-supported answer.

## Failure Recovery

Handle:

- empty search results
- blocked pages
- slow pages or timeouts
- duplicated sources
- contradictory evidence
- missing API keys
- judge-sensitive short-answer formats

If search fails, return `partial` with clear missing dependencies rather than
inventing evidence.

## Dev BMK Feedback

During creation, use `run_dev_bmk.py` to run public/dev DeepResearch and
BrowseComp tasks. Inspect accuracy, judge feedback, stdout/stderr, evidence
files, and trajectory. Modify the harness until answers are grounded and
scoreable, then write or say `FINISH`.
