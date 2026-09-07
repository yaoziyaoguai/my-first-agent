# First Agent 收尾计划：长会话连续性与受治理 Shell

日期：2026-09-04
状态：用户已批准实施
执行分工：Codex 负责设计、审计和验收；Pi（`glm-5.3`，`high`）只负责按本计划实现。

## 1. 范围

### Outcome

1. 普通聊天不再因活动 checkpoint 达到 2 MB 而成为日常终止条件。Runtime 会在安全边界自动压缩旧上下文；用户也可使用 `/compact`、`/context` 和 `/new`。
2. 压缩前的完整原始状态进入 owner-only、不可变、可搜索的 transcript archive。模型生成的 summary 只是 untrusted context，不替代 Goal、Approval、Recovery、Evidence 或任何 authority。
3. 新增 `shell_exec`：允许常用 shell 组合（`&&`、`||`、pipeline、重定向和 shell expansion），但仍经过唯一 ToolRuntime、exact approval、`EXECUTING` checkpoint、Seatbelt、bounded runner、result checkpoint 和 unknown-outcome recovery。
4. 关闭当前已知交付缺口：Skill declared entrypoint 的本地 materialized release-runtime 验证、`first-agent-schedule` 的真实 host composition 接线，以及 README/architecture/help 漂移。
5. touched tests、Ruff、全量 pytest 和 `git diff --check` 全部通过；未跟踪的 `tui/` 不读取、不修改、不纳入。

### Non-goals

- 不做 TUI/视觉工作。
- 不实现 Skill 安装/卸载/lifecycle/registry；安装仍只是由用户把目录放入显式 `--skill-root`，卸载仍只是移除目录。
- 不重做 MCP；现有 MCP governed-tool 路径保持不变。
- 不加入第二套 agent/model/tool loop、后台 daemon、service locator、兼容 fallback 或 dormant feature flag。
- 不提供交互式 TTY/stdin、常驻后台任务管理、任意网络 shell、远程 shell 或自制 shell parser/黑名单。
- 不把真实 provider E3、生产就绪或跨平台能力写成已验证；没有显式凭据授权时只运行离线/本机真实边界验证。

## 2. 必须保持的架构边界

- `AgentRuntime.run_turn` 仍是唯一 production model/tool loop 和状态变更入口。
- `KernelContextManager` 独占模型上下文选择；Provider adapter 只做 `ContextPack -> ModelResponse`。
- `KernelToolRuntime` 独占 callable prepare/invoke；Shell 不得直接从 CLI、ContextManager 或 Provider adapter 执行。
- 所有副作用仍遵循 `prepare -> approval/policy -> durable EXECUTING -> invoke -> durable result/recovery`。
- CLI/headless 只翻译 typed action 和渲染 view/result。`/context` 可以走 Runtime 提供的只读 projection，但不得推进 state 或调用 Provider。
- 压缩 summary 是 context data，不是 trusted fact、evidence、user authority、Goal completion 或 approval。

## 3. 设计决定

### 3.1 活动状态、summary 与原始 transcript 分离

引入一个窄的 `ConversationArchive` port，composition root 注入本地实现。它只负责两件事：

1. 在持有 conversation mutation lease 时，以 source checkpoint digest 为 identity，幂等写入完整、原样的 pre-compaction checkpoint；
2. 为 HistoryCatalog 按闭合的 conversation/workspace/source-digest identity 精确读取
   canonical lineage 中的 archived state；不得枚举 transcript 目录发现 authority。

本地布局位于 product state root 下独立的 `transcripts/<workspace-scope>/<conversation-id>/`，不放进 `workspaces/<scope>/`，避免破坏现有严格 checkpoint 枚举。目录必须 owner-only 0700，文件必须 regular、owner、single-link、0600、no-follow；文件名只由闭合 digest/sequence 生成，不接受模型或用户路径。

提交顺序固定为：

```text
hold conversation lease
  -> write/fsync immutable archive (idempotent by source digest)
  -> CAS reduced active checkpoint
  -> fsync
```

在 archive 成功而 CAS 失败/进程崩溃时，旧 checkpoint 仍完整；重复操作只复用同 digest archive。不得先覆盖活动 checkpoint 再尝试归档。

### 3.2 Summary 的闭合形状

增加 `FactKind.CONTEXT_SUMMARY`，其内容是严格、有界的 `ConversationSummaryV1`：

- `objective`
- `constraints`
- `decisions`
- `completed`
- `open_items`
- `key_references`
- `source_checkpoint_digest`
- `source_fact_ids_digest`

文本字段和数组各自有字符/条目上限；未知键、空 summary、超限、非 JSON、tool/control block 一律拒绝。summary prompt 明确把旧消息、工具输出和文件内容视为 untrusted data，只允许总结，不得执行其中指令。

`ConversationState.goal`、`goal_authorizations`、`evidence_records`、`completion_claim`、pending approval/recovery、control receipts、workspace/background bindings 和 active authority 不从 summary 重建，也不被 summary 覆盖。

### 3.3 确定性的压缩选择

`KernelContextManager` 新增只读 compaction planning/usage projection；它仍是唯一选择哪些模型消息进入 normal/compaction ContextPack 的 owner。

压缩只能发生在 `MODEL` phase 的安全边界：无 pending approval、无 pending takeover、无 unknown effect、无 `EXECUTING` tool。保留规则固定为：

- 所有被当前 canonical Goal、Evidence、Completion/Recovery/Approval/control continuity 引用的 facts；
- 当前 active action 的完整 facts；
- 最近 4 个完整 user-to-assistant turns；
- tool call 与对应全部 tool results 为原子组，不拆分；
- 最近一个已有 `CONTEXT_SUMMARY`，供增量合并。

其余最老的完整组构成一个 bounded archive/summary batch。一次 batch 必须能放入 compaction ContextPack；过大的旧历史分批压缩，不能把超大 state 一次塞给 Provider。

触发条件：

- normal ContextPack 预计输入达到可用 input budget 的 70%，或已经排除一个可压缩旧组；或
- 活动 checkpoint 达到软阈值。

默认活动 checkpoint hard cap 从 2,000,000 提高到 8 MiB；soft threshold 为 6 MiB。token pressure 通常先触发，hard cap 只是异常护栏。自定义小 cap 的测试仍可注入成比例的 soft threshold。

若没有可安全压缩的完整旧组，不循环调用模型；返回明确的 bounded limit/failure。单次 user turn 最多做 4 个 compaction batches，防止 provider 方差形成隐藏无限循环。

### 3.4 自动与手动压缩都复用唯一 loop

增加 typed `CompactConversation` action。手动 `/compact` 将它交给 `AgentRuntime.run_turn`；Runtime 用同一 Provider 调用、计数、disclosure、retry 和 checkpoint 路径得到 summary，成功后 archive+CAS，最后返回 typed result。

对于普通 `SubmitMessage`，Runtime 在第一次 normal Provider call 前检查 compaction plan；需要时先在同一个 `_drive` 中运行 compaction phase，落盘成功后继续处理原用户消息。不得由 CLI 自动调用 Provider，也不得新建 `CompactionLoop`。

前台 provider 返回失败、summary 校验失败、archive 失败或 CAS 冲突时：

- 原始 facts 和 canonical state 不被缩减；
- 不伪造压缩成功；
- 返回现有 retryable/conflict 语义；
- 自动压缩中的原始 Submit action 保持可恢复，不丢用户消息。

后台 occurrence 不偷偷改变其 frozen model-call/token budget；若其 profile 没有给压缩预算，则按现有 bounded limit 语义停止。

### 3.5 `/context` 与 `/new`

`/context` 是只读 view，至少显示：

- provider input limit、output reserve、当前 normal-context 估算与百分比；
- included/excluded/clipped facts 数；
- active checkpoint bytes、soft threshold、hard cap；
- compaction count、最近一次 source digest（若有）；
- archive 是否可用。

它不调用 Provider、tool 或外部 ContextSource，不修改 checkpoint。

`/new` 是 typed `NewConversation` action，只能在无 active run、无 unknown effect、无 pending approval/recovery/takeover 的安全边界执行。它先归档完整当前状态，再在同一个 checkpoint identity 内开始新的 logical segment：清空旧 facts、Goal/Evidence/authorizations/leases 和旧 segment 的控制状态，保留 workspace binding、provider disclosure receipt、单调 revision/action replay。这样 plain REPL 无需创建第二个 Runtime 或在进程内切换 store；旧 segment 仍可由 HistoryCatalog 搜索。输出需明确“new context started”。

### 3.6 HistoryCatalog

HistoryCatalog 只从 bounded canonical checkpoints 取得 root，再沿 root 的
`CONTEXT_SUMMARY.source_checkpoint_digest` 向后精确读取 immutable archive lineage；未知、残留或
仅存在于 transcript 目录的文件不构成 history authority。当前 active checkpoint 不重复投影，但其
已经从 active state 移除的 lineage delta 允许搜索。每次 `history_search` 最多读取 256 个 archive；
预算耗尽返回累计 top-k、作为下界的 `total_matches`、`coverage_complete=false` 和只可用于同一
query/limit/lineage-head 的 opaque continuation。调用方继续到 `coverage_complete=true` 后才得到完整
覆盖；普通 turn 追加但 lineage head 不变时 continuation 仍有效。`history_get` 只按签发 ref 绑定的
exact checkpoint/archive identity 读取一次，不扫描目录。搜索/get 始终 bounded、workspace-bound；
archive 内容只是 untrusted historical evidence，不成为 authority，也不自动注入 context。不增加
SQLite、manifest/indexer、scheduler 或第二套 runtime loop。

### 3.7 `shell_exec`

新增独立 `shell_exec` ToolSpec，不改变现有 `local_process` 和 frozen `sandbox_exec` schema。

公开参数保持最小：

- `command`: 非空 UTF-8 文本，最多 16 KiB；
- `mode`: `read-only | workspace-write | danger-full-access`，默认 `workspace-write`；
- `timeout_seconds`: 复用现有 bounded runner 范围，缺省使用现有 sandbox 默认值。

执行合同：

- shell 固定为经过启动时 identity 验证的 `/bin/sh`，argv 固定为 `[/bin/sh, -c, command]`，non-login；
- 不解析/过滤 `&&`、`||`、pipeline、重定向或 expansion；它们由 `/bin/sh` 解释；
- working directory 固定为 workspace root；closed environment 复用现有 process admission，绝不继承 credential-looking/ambient env；
- network 固定为 off；`danger-full-access` 只放开 filesystem profile，不隐式授予网络；
- stdout/stderr/result 使用现有 bounded capture 和 receipt；
- 无 TTY、无 stdin。无论 shell 正常退出、timeout 或异常，runner 都必须 TERM/KILL/reap 整个 process group；`cmd &` 不得留下 child；
- binding/approval preview 必须包含 exact readable command、command SHA-256、固定 shell path + identity、cwd identity、mode、network、policy digest、timeout 和 trust notice；
- 每次 `shell_exec` 都是 exact one-shot approval，不跨不同 command/mode 复用 lease；`danger-full-access` 必须额外显示无 filesystem isolation 的明确警告；
- sandbox/backend 不可用时不降级为裸 subprocess。

### 3.8 剩余交付修复

1. **Skill entrypoint**：不增加 lifecycle。补一个从 clean materialized package 调用 declared Python entrypoint、经过真实本机 Seatbelt、网络负向探针、structured request/result、approval/EXECUTING/result checkpoint 的 repeatable local release-runtime harness/record。没有真实 provider 凭据时只声明 local release boundary verified，不冒充 provider E3/accepted。
2. **Scheduler CLI**：保留 portable 019 management CLI，禁止恢复旧 raw `--message` compatibility surface。installed `first-agent-schedule` 必须调用一个真实、受信任的 host composition factory；Darwin 从现有 sealed host profile/config/store/supervisor/wake adapter 组装一个 `AutomationControlCoreV1`，其他平台或缺配置返回现有 closed `needs_019_config` reason。`agent.automation.cli:main` 和 `agent.automation_hosts.macos_cli:main` 不得再永久传 `core=None`/固定 unavailable。
3. **文档漂移**：README 不再说 `scripts/` 不可执行，而是只允许 declared entrypoint；`KERNEL_ARCHITECTURE.md` 删除已移除的 `--state/--resume`；`--browser` help/status 与当前 accepted/candidate 真相一致。同步 capability status，但只写证据实际证明的等级。

## 4. 实施顺序（严格 vertical TDD）

Pi 每个 slice 必须先增加一个通过 public boundary 失败的 Red，只实现让该 Red Green 的最少代码，再进入下一 slice；禁止先铺完所有测试或一次性重写 Runtime。

### Slice A — Archive 原子性与 summary reducer

可能文件：`agent/runtime/contracts.py`、`agent/runtime/state.py`、`agent/runtime/ports.py`、`agent/runtime/checkpoint.py`，新增窄 `agent/continuity/archive.py`，对应 `tests/continuity/`。

Red/Proof：archive-before-CAS、crash/CAS failure 保留旧 state、重复 digest 幂等、unsafe filesystem objects fail closed、summary 不能改 canonical fields、tool group 不拆分。

### Slice B — Context plan、自动 compact、`/compact`

可能文件：`agent/runtime/context.py`、`agent/runtime/loop.py`、`agent/cli/actions.py`、`agent/cli/app.py`、`agent/cli/render.py`、`agent/composition.py`，对应 kernel/cli/context tests。

Red/Proof：70%/excluded/soft threshold 触发；safe boundary 才触发；compaction ContextPack 无 tools/control/sources；严格 summary validation；自动 compact 后原 Submit 得到正常回答；失败保留 raw facts；重启/replay 不重复损失；最多 4 batches。

### Slice C — `/context`、`/new`、archive history

可能文件：`agent/runtime/views.py`、`agent/history/catalog.py`、`agent/continuity/sessions.py`、CLI 与 tests。

Red/Proof：`/context` 零 provider/tool/state mutation；bytes/token 数据准确；`/new` unsafe state 拒绝，safe state archive 后开始空 segment；旧内容可 search/get，当前内容不重复；workspace mismatch 不可见；超过 256 个真实 archive 可用 continuation 完整遍历，跨页重叠投影去重，`history_get` 仍是 exact read。

### Slice D — `shell_exec`

可能新增 `agent/sandbox/shell.py`，最小修改 `agent/sandbox/*`、`agent/process/*`、`agent/composition.py`、README；tests 放在 `tests/sandbox/` 与 composition/runtime integration。

Red/Proof：真实 `&&`、pipeline、workspace redirection、expansion；read-only/write mode 隔离；network denial；closed env；exact preview/digest/shell identity；approval 前零 spawn；EXECUTING checkpoint 在 spawn 前；success/failure/timeout receipts；background child 被 reap；danger mode one-shot；backend missing 零裸执行。

### Slice E — Skill/Scheduler/docs 收尾

只修改缺口直接涉及的现有模块、materialized verifier/harness、console entry 和真相文档。

Red/Proof：installed wheel 的 declared Skill entrypoint 走真实 Seatbelt；console `first-agent-schedule` 在 fixture trusted host composition 下能执行一个真实 portable command，缺配置 closed failure；旧 fixed-unavailable/main-none 路径被测试禁止；文档 contract tests Green。

## 5. 审计禁止项

出现以下任一项即退回 Pi：

- CLI/provider adapter 直接调 Provider 或 shell；
- 新的 agent/compaction/tool loop；
- summary 写入 Goal/Evidence/Approval/Recovery 或被用作 completion proof；
- 删除原始 facts 而 archive 尚未 durable；
- transcript 放入严格 workspace checkpoint 枚举目录；
- 通过字符串黑名单解析 shell；
- 继承宿主完整环境、开放网络、允许 TTY/stdin、留下后台子进程；
- 修改 `sandbox_exec` 成双形 schema；
- Skill registry/install manager/MCP 重构/TUI 工作；
- 读取或纳入 `tui/`、`.env`、credential、真实私有 runtime state。

## 6. 验证

每个 slice 跑最窄测试；全部完成后必须真实执行且得到未截断 exit 0：

```bash
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
```

另外运行：

- 长会话 fault/restart/replay/HistoryCatalog integration；
- macOS 上 `shell_exec` 的真实 Seatbelt journey（网络负向探针、write/read-only、timeout、background reap）；
- clean materialized wheel 的 Skill entrypoint 与 `first-agent-schedule` console smoke；
- `git status --short`，确认唯一预存未跟踪 `tui/` 未被读取/修改/纳入。

真实 provider 或外部网络 E3 只有在用户另行给出该产品所需显式配置/授权时才执行；缺失时报告为 caveat，不得把离线 FakeProvider 当成真实 E3。
