# Minimal Runtime Kernel Reference Task

- Revision/worktree digest: baseline_commit `7d935ac4af7121c54e1bdcc600763c3f0fbf54c2`; unsealed 009 successor worktree (E3 records not yet reviewer-sealed). `--check-membership` 947 entries, `--control-seal` verified immediately before this run.
- User-approved task: 用真实 provider 走完多轮对话、上下文预算、读取一个合成文件、一次需 approval 的合成写入、一次拒绝后恢复，并核对 checkpoint terminal state 与 model/tool/effect count。
- Destination/profile identity: provider `anthropic_compatible`; base URL `https://open.bigmodel.cn/api/anthropic`; endpoint `/v1/messages`; auth `x-api-key` via env name `ANTHROPIC_AUTH_TOKEN`; model code `glm-5.2`（approved `glm-5.2[1M]` 的 `[1M]` 为上下文窗口标注，非 API model code；endpoint 回显 `model=glm-5.2`）；timeout 90s。
- Data/effect scope: 全部合成非敏感数据（codename RED-PANDA / pin 7 / report.txt / secret.txt）；所有 effect 写入 mktemp 临时 workspace 外的临时目录；无 secret / 真实日志 / 用户路径进入 record。
- Baseline: 同一 provider 路径的只读轮次作为上下文/计数基线。
- Success criteria: (1) 多轮上下文累积；(2) read_file 自动放行并返回正确内容；(3) write_file 经 preview→approval 写入；(4) 拒绝的 write 不产生 effect；(5) checkpoint 收敛到 terminal、无悬挂 active_run；(6) 计数可核对。
- Result: **pass**
- Model/tool/effect counts: 提交 3 条 user message + 2 个 resolution（1 approve / 1 reject），`next_action_seq=6`，`revision=27`，facts=12。工具结果事件 2（read_file + 已批准 write_file）；approval 事件 2（两次 write_file）；被拒的 write_file 执行 0 effect。终轮前至少 4 次 model invocation（由工具调用/结果/作答轮次推断；终端 renderer 不逐条输出 model_progress，故不冒充精确 model-call 计数）。
- Checkpoint terminal status: durable v1 state `active_run=null`，`last_safe_result.status=completed`（message digest `f53d76f6d12e996c`，仅摘取前 16 hex，不保存全文）。
- Observable delta: read_file 返回 `RED-PANDA`（与种子 notes.txt 一致）；批准后 `report.txt` 写入成功，内容 sha256[:16]=`5d7850e290f45121`；拒绝后渲染 "rejected, so the file was not created"，`secret.txt` 在工作树不存在。approval request_id（短）approve=`approval-0bbf17da…`、reject=`approval-19844da3…`；preview 分别为 "write report.txt (28 bytes)" / "write secret.txt (9 bytes)"。
- Limitations and unverified claims: 本任务覆盖 Kernel 的多轮/上下文/文件读写/approval/reject 路径。unknown-outcome recovery（AWAITING_RECOVERY）在确定性文件工具上不可自然触发，留待 MCP E3（EXTERNAL 工具可触发）覆盖；此处 "拒绝后恢复" 以 reject 路径满足。驱动通过 `main.main(input_fn, write_fn)` 设计好的 headless 钩子（即 stdin/Pilot 等价），每轮经真实 `main()->run_repl()->run_turn()` 与真实 provider；未调用 store/runtime 内部 API 冒充 E3。
