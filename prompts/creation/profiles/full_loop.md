# Creation Profile: Full Loop Scaffold

This is a strong scaffold / upper-bound profile. You may use a complete
planner -> act -> observe -> verify -> recover -> finish skeleton, but you
must still generate real domain-specific tool policy, verification logic, and
artifact construction.

Recommended loop:

1. Parse the task and initialize state.
2. Discover workspace artifacts.
3. Build compact context.
4. Choose the next action.
5. Execute a real tool.
6. Verify partial progress.
7. Retry or recover on failure.
8. Write the final artifact.
9. Run a final verifier when possible.
10. Write result and trajectory files.

This profile is only for ablation or upper-bound experiments. Do not use a
fixed template to bypass real task work, and do not hard-code toy task or
downstream benchmark answers.
