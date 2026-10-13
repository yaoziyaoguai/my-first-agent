# 接手基线

## 当前身份

- 仓库：`my-first-agent`；采集于 2026-09-13。
- 分支：`main`。
- HEAD：`838cb2b66fbba674311d4d86fc7c4f4322fd8612`。
- **被测对象是 HEAD 加已有工作树改动**；HEAD 不足以标识被测代码。
- `BASELINE.sha256` 记录相关文件字节，可在仓库根用 `shasum -a 256 -c docs/handoffs/2026-09-13-dogfood-remediation/BASELINE.sha256` 核对。指纹不携带源码，也不包含私有状态。
- GitHub/remote 未在本次联网核对；不保证远端与本地一致。本包不包含自动同步或覆盖脚本。

## 重要已有工作，不要重做

先看 [前一资料包执行记录](../2026-09-12-daily-use/EXECUTION-LOG.md)。当前 dirty tree 已含：

- S1：终端输出净化、streaming/final answer 去重、即时 Working 反馈。
- S2：完整文件 preview；进程先批准生成，生成后 `confirm_file` 单独确认当前内容；`defer_artifact_confirmation` 已存在。
- `/new` 的 Memory create→load 同进程重装配修复。
- 019 调度相关实现、测试和文档改动，非本轮修复目标。

这些改动涉及 `main.py`、`agent/runtime/`、`agent/cli/`、`agent/tools/`、`agent/tui/`、`agent/automation/` 及相关 tests/docs/scripts。不要把它们当成接手者的新 diff。根未跟踪 `tui/` 属于用户内容，不纳入。

本次 Graphify 只读查询用于模块导航；图早于当前改动，结论已对照源码，不刷新/扫描 ignored 或 private 输入。

## 历史 dogfood 证据

来源：[真实模型丰富 dogfood](../../audits/2026-09-13-real-model-rich-dogfood.md)。报告需配合本包 FINDINGS 的勘误阅读。

- 历史 wheel：`first_agent-1.0.0-py3-none-any.whl`。
- SHA-256：`ed3c80f2229ea2dcf6997d559dec0f7aa4e672d902f4d243d1f2e800d9353394`。
- 历史运行在临时 synthetic workspace，产品从 venv 的 `site-packages` 加载；venv 使用过 `system-site-packages`，不是纯净依赖隔离证明。
- 本包不依赖旧 `/private/tmp` 存活，也不提供旧运行私有 state。复现必须重新创建合成 fixture。
- 原报告未完整保存 MCP/child 成功 receipt、每次 HTTP 开始结束时间与 token 使用量；不可从观察推导这些事实。

## 本次已做的检查

仅运行以下定向现有测试：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx \
  tests/kernel/test_runtime_approval.py \
  tests/process/test_artifact_approval_contract.py \
  tests/memory/test_agent_fact_scope.py \
  tests/cli/test_contextual_decisions.py \
  tests/continuity/test_entry_routing.py
```

结果：**89 passed，1.74s，exit 0**。它们保护现有合同，不覆盖所有新发现；不能据此说问题不存在或已经修复。

本次没有重跑数千项 full gate，没有真实 provider 调用、Browser/调度 E3 或 capability promotion。前一资料包记载的 `3412 passed, 3 skipped` 是历史结果，不冒充本次结果。

资料包交付检查：69 个基线文件的 SHA-256 全部匹配；7 份 Markdown 的本地链接、尾随空白及常见 key 模式检查通过；`git diff --check` 与 `.venv/bin/ruff check .` 均 exit 0。新增文档不在普通 Git diff 的 whitespace 覆盖内，因此另做文档检查。本次没有产品修改，全量产品验收留给执行者的最终修复候选。
