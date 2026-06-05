# Creation Profile: Interface Scaffold

This setting fixes the outer interface but does not provide tool
implementations or an agent loop. You must synthesize a runnable harness under
the fixed interface.

Fixed interface:

- CLI entrypoint: `python -m harness -p "<task>" --output-dir <dir>`
- Workdir aliases: `--workdir`, `--work-dir`, `--workspace`
- Budget aliases: `--max-steps`, `--max-turns`
- Output schema: `result.json`, `trajectory.jsonl`, stdout/stderr logs
- Final artifacts must be written to `--output-dir` or to the explicit path
  requested by the task, and must be referenced in `result.json`.

You generate:

- execution/control loop
- context packing strategy
- tool-use policy
- verifier/self-check
- retry/recovery logic
- artifact construction

Do not misuse the interface scaffold as a template answer. Success must come
from real tool execution and real artifacts.
