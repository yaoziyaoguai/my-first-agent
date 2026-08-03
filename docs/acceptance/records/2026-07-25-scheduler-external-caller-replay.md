# Scheduler Reference Task

- Revision/worktree digest: baseline_commit `7d935ac4af7121c54e1bdcc600763c3f0fbf54c2`；009 未封存继承副本（E3 records 待 reviewer 封存）。
- User-approved task: 外部 caller fire 一个 benign occurrence → needs_human → 人类从正常 CLI action resolution → duplicate fire；核对 deterministic identity、terminal state、provider/effect count 不增加。
- Destination/profile identity: provider `anthropic_compatible`；base URL `https://open.bigmodel.cn/api/anthropic`；model `glm-5.2`；timeout 60s。入口 `first-agent-schedule`（`main.run_schedule`）与 `first-agent --resume`（`main.main`）。state-root 在 mktemp 临时目录（workspace 之外，0700 owner-only）。
- Data/effect scope: 合成非敏感 occurrence（message 让模型 `write_file marker.txt` 内容 `SCHED-DONE`）；effect = 一次合成文件写入；无 secret/真实日志/用户路径。
- Baseline: 首次 fire 的 needs_human 报告与解决后 authoritative terminal 的对照。
- Success criteria: (1) 首次 fire action identity deterministic、进入 needs_human；(2) 人类经正常 CLI（--resume + /approve，新 seq）完成 resolution；(3) duplicate fire 报告 authoritative terminal（completed）且 provider/effect count 不增加。
- Result: **pass**
- Model/tool/effect counts: FIRE-1：1 次 provider turn（模型调用 write_file → 暂停），0 effect（未批准）。RESOLVE：1 次 provider turn（批准后模型终结），1 tool_result（marker.txt 写入一次）。FIRE-2 与 FIRE-3：0 次 provider turn（`replayed=True`），0 新 effect（marker.txt 仍为解决时写入的那一份，digest 不变）。
- Checkpoint terminal status: occurrence checkpoint `c7accc85…858ce0.json`（= sha256(schedule_id\noccurrence_id)）。FIRE-1 后 active_run=AWAITING_APPROVAL；RESOLVE 后 active_run=null、last_safe_result=completed；FIRE-2/3 重放 seq-1 并报告 authoritative terminal（occ=completed, run=completed, replayed=True）。
- Observable delta: FIRE-1 `occurrence_status=needs_human, pending_kind=ApprovalRequest, pending_request_id=approval-5600c29ea1516706`；RESOLVE 后 marker.txt 落盘（sha256[:16]=`5dd3478c44921580`）；FIRE-2 `occurrence_status=completed, replayed=True, pending=None`，FIRE-3 同。duplicate fire 不增加 provider/effect 由 `accept_action` 返回 `REPLAYED`（已记录 action 直接返回 recorded result，不触达 provider/tool，loop.py 的 replay 分支）保证。
- Limitations and unverified claims: conversation_busy/checkpoint_conflict 一次有界 reconciliation、concurrent first-fire loser fail-closed 已由 E1/E2 覆盖；本 E3 验证真实 provider 下 external-caller fire → needs_human → 正常 CLI resolution → duplicate replay 的正向与不增 effect 路径。驱动经 `main.run_schedule` 与 `main.main(--resume)` 真实入口；pending_request_id 取自 FIRE-1 的 ScheduledReport（--resume 不重渲 pending，故按报告 id 构造 /approve，REPL 依 state 内 pending 的 binding_digest 校验）。
