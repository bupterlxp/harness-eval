# Agent Harness Construction Task: Browser Agent

Build a general browser-automation harness that accepts web tasks such as
navigation, form filling, data extraction, file download, multi-page
workflows, and long-horizon digital employee actions.

The harness will be evaluated on TheAgentCompany: long-horizon digital
employee tasks inside a simulated company environment with real self-hosted
services (GitLab, ownCloud, RocketChat, Plane). Evaluation is programmatic:
checkpoint scripts inspect the final environment state — files created or
moved, repository contents, chat messages sent, tickets updated — and the
score is the fraction of checkpoints satisfied. Written explanations satisfy
no checkpoint.

Practical implications:

- Real state changes are what count. Use whatever interface reliably changes
  service state: HTTP/REST API calls, git operations, or browser actions.
- Service endpoints, hostnames, and credentials come from the task
  description and environment; discover and reuse them instead of assuming
  defaults.
- Tasks often have several checkpoints. Completing some checkpoints scores
  partial credit, so finish as many independent subgoals as possible even if
  one step is blocked.

## Scaffold-Native Minimum Requirements

If the active creation profile is `claude_code_scaffold_native`, implement
`GeneratedHarnessProgram.run(...)` in `generated_program.py` on top of
`harness_scaffold`.

Requirements:

- Remove `NotImplementedError`, TODOs, and stub fallbacks.
- Use scaffold tools for browser action planning, state tracking, action
  execution, observation parsing, and final result writing.
- Additional modules are allowed only if called by `generated_program.py`.
- Do not deliver only README files, architecture notes, or disconnected helper
  modules.
- Every run must write `result.json`, `trajectory.jsonl`, logs, final
  state/result artifacts, action trace, screenshots, or extracted data.
- If browser services, pages, or credentials are unavailable, record the
  failure and return `partial` or `failed`. Do not fabricate completed states.

## Unified Entry Point

```bash
python -m harness -p "<browser task>" --output-dir ./output/
```

Required options:

- `-p` / `--prompt`
- `--output-dir`
- `--workdir`, `--work-dir`, `--workspace`
- `--max-steps`, `--max-turns`

Minimum `result.json`:

```json
{
  "status": "success | partial | failed",
  "trajectory": "trajectory.jsonl",
  "final_state": {},
  "artifacts": {}
}
```

## Browser BMK Execution Contract

The harness must:

- Execute real browser or equivalent environment actions such as navigate,
  click, type, select, upload, extract, wait, screenshot, and done.
- Record each step in `trajectory.jsonl` with action, observation, state
  summary, error, retry, or final decision.
- Track current URL, page title, active element, completed subgoals, pending
  subgoals, and collected data.
- Write final status, final state, collected data, and artifact paths in
  `result.json`.
- When a page, service, or credential is missing, write the missing dependency
  into result and trajectory. Do not use simulated data as real completion.

## Core Harness Behavior

Implement an observe-think-act loop:

1. Parse the web task and extract success criteria.
2. Initialize browser/session state.
3. Build a compact page observation using accessibility tree, DOM summary,
   screenshot, or extracted text.
4. Plan subgoals for complex tasks.
5. Choose the next browser/tool action.
6. Execute the action and wait for page readiness.
7. Update state, memory, and collected data.
8. Detect loops or stalled pages and switch strategy.
9. Finish only when final state satisfies the task or the budget is exhausted.

## Page And Context Handling

Do not feed raw huge DOMs into prompts. Prefer:

- accessibility-tree summaries
- stable element indexes
- visible text and important attributes
- screenshot references when available
- compact tab state
- recent action history plus task memory

Handle shadow DOM, iframes, popups, cookie banners, page load retries, and
multi-tab workflows when the environment supports them.

## Verification And Recovery

The harness should verify progress:

- Did the page change after the action?
- Did the target form field or table update?
- Was data extracted?
- Did a required file download or final state appear?
- Are we repeating the same action?

Implement recovery for:

- element not found
- click/type failure
- modal blocking
- navigation timeout
- login or credential missing
- repeated no-op action
- stale page state

If the task cannot finish, write best-effort collected data and the exact
failure reason.

## Dev BMK Feedback

During creation, use `run_dev_bmk.py` to run public/dev browser tasks such as
TheAgentCompany sample tasks when services are available. Inspect action
traces, final state, stdout/stderr, screenshots, and benchmark score. Modify
the harness yourself until it produces real state changes and scoreable
outputs, then write or say `FINISH`.
