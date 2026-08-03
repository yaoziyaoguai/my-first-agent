# TUI Reference Task

- Revision/worktree digest: baseline_commit `7d935ac4af7121c54e1bdcc600763c3f0fbf54c2`；009 未封存继承副本（E3 records 待 reviewer 封存）。
- User-approved task: 纯键盘 submit→approve/reject或recovery→terminal；从 durable pending checkpoint 重启；与 CLI 同 state 的 action digest/checkpoint/result 对照；events 不改变 authoritative controls。
- Destination/profile identity: provider `anthropic_compatible`；base URL `https://open.bigmodel.cn/api/anthropic`；model `glm-5.2`；timeout 60s。入口：`agent.tui.app.build_app(TuiAdapter(runtime, store, event_sink=QueueingEventSink()))`，Pilot 驱动（TUI 的设计 headless 钩子，等价于 REPL 的 input_fn）；runtime 用真实 provider + 真实 file tools + durable `LocalCheckpointStore`（与 `main()` 的 `--tui` 同构）。
- Data/effect scope: 合成非敏感任务（write_file 创建 `tuimark.txt`/`pend.txt`）；effect = 一次合成文件写入；durable state 在 mktemp 临时目录（0700 owner-only）；无 secret/真实日志/用户路径。
- Baseline: CLI 同 authoritative state 经 `agent.cli.actions.build_resolve_approval` 构造的 typed action digest。
- Success criteria: (1) 键盘 submit→approval→approve→terminal（真实 provider）；(2) action digest 与 CLI 等价；(3) 从 durable pending checkpoint 重启零 provider/tool 调用；(4) events 不改 authoritative controls。
- Result: **pass**
- Model/tool/effect counts: journey：2 次 provider 调用（submit→write_file tool_call + 批准后终结）、1 次 write_file effect（tuimark.txt 写入，sha256[:16]=`c6438564b1e95548`）、terminal=completed。restart：0 次 provider 调用、0 effect（仅 load checkpoint + project）。
- Checkpoint terminal status: journey 后 durable state `active_run=null`、`last_safe_result.status=completed`。restart 从另一 durable pending checkpoint（`active_run=AWAITING_APPROVAL`）重开，projection `actions=('approve','reject')`。
- Observable delta: TUI 键盘 "a" 派发的 approve action `canonical_action_digest` = `714b94349b7a6a88`，与 CLI `build_resolve_approval(同 authoritative state, request_id, binding_digest, approved=True)` 的 digest 完全一致（结构等价：两者经同一 `agent.cli.actions` builder 从 authoritative `conversation_id/action_seq/expected_revision` 构造）。重启时 `provider.generate` 计数保持 0，证明重开只从 checkpoint 投影、零额外 model/tool 调用（R19）。
- Limitations and unverified claims: keyboard reject/recovery→terminal 与 event loss/duplicate/reorder 不改 authoritative checkpoint 的完整 fault matrix 已由 E1/E2（R19/R20/N2 oracle）证明；本 E3 在真实 provider 下验证键盘 approve 正向 journey + CLI digest 等价 + durable 重开零调用。TUI 经 Pilot 驱动（设计 headless 钩子），runtime/provider/checkpoint/file-tools 与 `main()` 的 `--tui` 同构，未调用 store/runtime 内部 API 冒充 E3。
