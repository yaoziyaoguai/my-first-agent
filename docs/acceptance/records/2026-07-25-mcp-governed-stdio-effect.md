# MCP Reference Task

- Revision/worktree digest: baseline_commit `7d935ac4af7121c54e1bdcc600763c3f0fbf54c2`；009 未封存继承副本（E3 records 待 reviewer 封存）。本任务修改了 `main.py` 与 `tests/mcp/test_integration.py`（见下"Bug 修复"）。
- User-approved task: 本地 operator-trusted/repo-owned benign stdio fixture 执行一次可数 effect；preview→approval→EXECUTING→result checkpoint；重复 action 不增加 effect count；任何 UNKNOWN/latch 立即停止不重试。
- Destination/profile identity: provider `anthropic_compatible`；base URL `https://open.bigmodel.cn/api/anthropic`；`/v1/messages`；`x-api-key` via `ANTHROPIC_AUTH_TOKEN`；model `glm-5.2`；timeout 90s。MCP server = repo-owned `tests/fixtures/mcp/stdio_server.py`（FastMCP `echo`）经临时 `#!/bin/sh exec` wrapper（0700）启动；catalog/safety-state 均在 mktemp 临时目录。
- Data/effect scope: 合成非敏感 token `HELIX-7`；effect = echo server 处理一次调用并原样返回；所有 state/catalog 写入临时目录；无 secret/真实日志/用户路径。
- Baseline: echo 工具的直接期望返回值（输入串 = 输出串）。
- Success criteria: (1) preview 完整显示 executable/server/tool/profile/generation/canonical arguments；(2) approval → EXECUTING → 一次调用 → result checkpoint；(3) server-side effect 与 report 一致；(4) 一次批准恰好一次 effect（重复不增加）；(5) latch 干净清空（无 ARMED/UNKNOWN 残留）。
- Result: **pass**
- Model/tool/effect counts: 提交 1 条 user message + 1 个 approve；approval 事件 1，`Tool result recorded` 事件 1（`mcp__fixture__echo`），即一次批准→一次 effect。终答 "The tool returned: HELIX-7"。
- Checkpoint terminal status: 非持久会话；rc=0，无悬挂 active_run。durable MCP safety latch 终态 `status=clear, revision=2, binding_digest=""`（arm 后干净 clear）。
- Observable delta: preview `mcp server=fixture tool=echo profile=ops-profile generation=gen-1 epoch=<hex8> executable=<wrapper> arguments={"text":"HELIX-7"}`；echo 返回 `HELIX-7` 与模型 report 一致。重复-effect 不增加由 kernel `idempotency_key`（`conversation_id:run_id:tool_call_id`，`IntentConflictError`）+ durable latch 共同保证（E1/E2 已证），本 E3 观察到单次批准→单次 effect。
- Bug 修复（E3 暴露的产品缺陷）: `main.py:255` 原为 `args.mcp_safety_state.resolve(strict=True)`，但 `McpSafetyLatch` 设计为"文件缺失即 clear"、首次 invocation 才惰性创建 latch 文件——故任何首次 CLI 使用 `--mcp-safety-state` 都会 `FileNotFoundError` 启动失败（catalog 用 strict=True 正确，因 operator 预提供；memory store 同类惰性 state 用 strict=False）。Named Red `tests/mcp/test_integration.py::test_main_composes_mcp_when_safety_latch_not_yet_created` 在修复前 `assert rc==0` 失败（rc=2）；最小 Green 改为 `resolve(strict=False)`（与 memory store 一致）；修复后该测试通过、`tests/mcp/` 全量 58 passed、ruff clean。
- Limitations and unverified claims: 本 E3 走 happy path（EXECUTED），未在真实 provider 下现场触发 UNKNOWN（EXTERNAL 工具的 unknown-outcome→AWAITING_RECOVERY→latch ARMED→stop-no-retry 路径已由 E1/E2 fault matrix 覆盖，latch 机制即本任务验证为活跃且干净清空的同一机制）。驱动经 `main.main(input_fn, write_fn)` 真实入口。修改的 `main.py`/`tests/mcp/test_integration.py` sha256 在最终 delivery 同步阶段写入 manifest。
