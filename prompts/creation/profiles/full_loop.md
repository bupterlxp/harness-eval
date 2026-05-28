# Creation Profile: Full Loop Scaffold

这是强 scaffold / upper-bound profile。你可以采用一个完整的 planner -> act -> observe -> verify -> recover -> finish 骨架，但仍然必须针对当前 domain 生成真实工具策略、验证逻辑和产物构造。

推荐 loop：

1. parse task and initialize state；
2. discover workspace artifacts；
3. build compact context；
4. choose action；
5. execute tool；
6. verify partial progress；
7. retry or recover on failure；
8. write final artifact；
9. run final verifier；
10. write result and trajectory。

这个 profile 只能作为 ablation 或 upper bound。不要用固定模板绕过真实任务，也不要硬编码 toy task 或 downstream benchmark 答案。
