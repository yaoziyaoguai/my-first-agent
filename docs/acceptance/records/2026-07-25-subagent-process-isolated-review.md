# SubAgent Reference Task

- Revision/worktree digest: baseline_commit `7d935ac4af7121c54e1bdcc600763c3f0fbf54c2`；009 未封存继承副本（E3 records 待 reviewer 封存）。
- User-approved task: 真实 HTTP provider in child；同一 bounded 合成设计题，parent direct 与 parent+child review 对照；child 一次 model call、无工具/Memory/workspace；记录 hard deadline/termination receipt、时长/调用数和人工可核对增量。
- Destination/profile identity: provider `anthropic_compatible`；base URL `https://open.bigmodel.cn/api/anthropic`；model `glm-5.2`；timeout 60s（child hard_deadline = timeout+10 = 70s）。child 经 `ChildProcessRunner` 进程隔离（HTTP provider 无 synchronous deadline_contract → 走进程隔离路径，`process_terminated` receipt）；credential 仅按 env name `ANTHROPIC_AUTH_TOKEN` 在子进程内读取，不跨进程序列化。
- Data/effect scope: 合成非敏感设计题（immutable data structures 的优势）；child 无 workspace 访问、无工具、无 Memory；无 secret/真实日志/用户路径。
- Baseline: parent 直接作答同一题（不开 `--subagent`）。
- Success criteria: (1) child 经 governed `subagent__delegate`（approval）调用；(2) child 恰好一次真实 HTTP model call、无工具/Memory/workspace；(3) 在 hard_deadline 内结束（无 UNCONFIRMED/timeout）；(4) 产出人工可核对增量；(5) 时长/调用数被记录。
- Result: **pass**
- Model/tool/effect counts: parent-direct wall=4.2s、0 delegate。parent+child wall=10.6s（child 真实 HTTP 调用 + 进程开销约 6s）、1 approval（`subagent__delegate`）→ 1 tool_result、child 内 `max_model_calls=1`（结构保证）。parent 最终作答含 `Child review:` 段（child 独立内容）。
- Checkpoint terminal status: 非持久会话；rc=0、无悬挂 active_run、未进入 AWAITING_RECOVERY（delegate 正常返回，非 UNCONFIRMED）。
- Observable delta: parent-direct 终答 "…enable safe structural sharing across threads without locks or defensive copies…"；parent+child 终答含 "Child review: They eliminate an entire category of concurrency bugs by guaranteeing that no thread can mutate shared state out from under a reader…"——child 经自身 model call 产出的独立、与 parent-direct 表述不同且人工可核对的观点。delegate preview 显示 `delegate to child agent (provider=https://open.bigmodel.cn/api/anthropic, profile=default, …)`。
- Eligibility: G8/G8.1 的 `ChildProcessRunner` 使 production HTTP provider 经进程边界获得 honest hard-deadline（`process_terminated` receipt），不再 safe-unavailable；本 E3 用真实 HTTP provider in child 完成 bounded review，未触发 UNCONFIRMED/超时。
- Limitations and unverified claims: child 的 TERMINATED/UNCONFIRMED → parent AWAITING_RECOVERY 故障路径（deadline kill / oversized stdout / nonterminal）已由 E1/E2（进程隔离 fake provider 经真实进程边界）证明；本 E3 验证真实 HTTP provider 下 child 正向 bounded review 路径与可核对增量。child model-call 计数=1 与 process_terminated receipt 为 `ChildProcessRunner` 结构保证（E1/E2 已证同一 runner），E3 观察到 delegate 在 deadline 内成功返回 substantive 内容。驱动经 `main.main(input_fn, write_fn)` 真实入口。
