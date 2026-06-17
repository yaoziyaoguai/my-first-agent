# Code Evidence Index — Independent S1 Priority Audit (2026-06-16 run 3)

> 中间产物（非权威）。本轮**独立**只读核验的事实，带 file:line / 命令。秘密一律掩码（字母→A、数字→9、标点原样），**不打印明文**。

## 入口 / runtime spine
- G-01 入口链 ✓：`main()@main.py:637` → `main_loop()@main.py:335` → `_run_chat_for_backend()@main.py:195` → `chat()@agent/core.py:763`（graphify #1 命中，节点位置一致）。
- G-04 same-spine ✓：
  - `agent/provider/factory.py:44-45`：「FakeProvider 和 RealProvider 共享同一条 core.chat/loop.py 路径，这不是 fake/real 双 runtime。」
  - `agent/loop.py:249`：「loop 层不接触 provider 对象、不读 provider_type、不做 white-list 判断」。
  - `agent/loop.py:690-691`：同义重申，`provider_kind` 仅 coarse 三态。
  - `agent/provider/factory.py:~89`：`# 4. default fake` → `return FakeProvider()`（默认 fake）。
- G-05 provider 协议薄 ✓：`ModelProvider@agent/provider/protocol.py:78`（graphify #2）。

## 工具 / evidence
- G-10/G-11 ✓：`record_evidence()@agent/evidence_recorder.py:728`（graphify #1）；`event_log.py:153 EventLogWriter`。
- evidence 不存正文 ✓：`agent/evidence_persistence.py:34 MAX_TOOL_RESULT_BYTES = 2048`；`:108/:133 content_persisted: false`；`summarize_content_for_persistence()@:90`。

## 多步任务 / checkpoint / scheduler
- G-07b 大结果 resume：`evidence_persistence.py` 确有 2048B 摘要 + `content_persisted=false`。tests 中 `test_checkpoint_roundtrip.py`、`test_evidence_storage_hygiene.py` 提及 2048/large，但**本轮只读未确证**「摘要后 resume 的消息形态被下一轮模型调用接受（API-valid）」→ 维持 `unknown_needs_audit`。
- G-13 scheduler dormant ✓：`grep -nc -iE "scheduler|action_scheduler" main.py` = **0**。

## acceptance 测试盘点（G-02 / G-17）
- `tests/golden_e2e/`：`test_golden_simple_conversation.py`、`test_golden_tool_success.py`、`test_golden_memory_checkpoint.py`、`test_golden_policy_evidence.py`、`test_golden_skill_l3_core_loop.py`、`test_golden_skill_system.py`、`test_golden_subagent_delegation.py`（全链路 + FakeProvider）。
- `tests/runtime_integration/`：`test_phase1_real_core_loop.py`、`test_mcp_l3_real_core_loop.py`。
- `tests/smoke/test_first_usable_task_e2e.py`。
- 结论：候选齐备，但**未被「指定」为 S1 acceptance 子集**（G-17 gap）。

## G-15 config 秘密结构（独立核验，掩码，无明文）
命令：`git ls-files -v config/config.yaml`、`git show HEAD:`/`:`(index)/工作树 读取 + 长度/结构掩码、`git log --format=%H -- config/config.yaml` 历史扫描。

| 来源 | api_key 长度 | 结构掩码 | 判定 |
|---|---|---|---|
| HEAD | 13 | `AA-AAAAAAA_AA` | 占位符 |
| INDEX(staged) | 13 | `AA-AAAAAAA_AA` | 占位符 |
| WORKTREE | 35 | `AA-AAAA99AA99A9999A99AA9AA9A99A999A` | **真实长度 key** |

其它事实：
- `git ls-files -v config/config.yaml` → `S config/config.yaml`（**skip-worktree** 位已设）。
- `git status --porcelain config/config.yaml` → 空（git 因 skip-worktree 看不到工作树改动）。
- `config/config.yaml` **被跟踪**；`config/config.example.yaml`、`config/config.local.example.yaml` 模板存在。
- `.gitignore`：忽略 `.env`、`.venv`、`config/config.local.yaml`；**未**忽略 `config/config.yaml`。
- 历史扫描：config.yaml 的 4 个 commit **从未**出现 ≥30 字符 key（`ever_long_key(>=30): no`）→ **真实 key 从未被提交**。

**结论（独立）**：
1. 已提交/被跟踪内容是占位符 → 上一轮「占位符、非已暴露真实密钥、无需轮换」对**已提交内容**成立。
2. 但真实 key 此刻就在**被跟踪路径**的工作树里，仅靠脆弱的 `skip-worktree` 位遮挡；`config/config.yaml` 仍被跟踪 → 一旦 skip-worktree 被重置 / `git add -f` / re-clone reset，真实 key 可能被提交。
3. 因此 G-15 的 must-fix 动作（`git rm --cached config/config.yaml` + `.gitignore` + 保留 example）**更被强化**；按任务 P0 判据「安全/config hygiene 发布风险」应为 **P0 / release_blocker**；但仍**不是**「已暴露真实密钥 / 需轮换」。
