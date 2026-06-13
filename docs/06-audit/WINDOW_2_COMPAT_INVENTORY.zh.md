# Window 2 兼容路径 Inventory

> **性质**：current-behavior characterization snapshot，**不是 no-delete guarantee**。
> 本文档记录"当前存在哪些路径、它们的用途、为何本窗口不删除"，
> 使未来变更可见而非静默。
>
> 生成于 Window 2（HEAD `e60704d` + W2 implementation commits）。
> 最终版本在 Window 2 closure 时以实际 HEAD 修订。

---

## 1. inline-local fallback

| 项目 | 内容 |
|---|---|
| **位置** | `agent/subagent_inline.py:63`（`execution_mode="local_fake"`）；`agent/core.py:2178`（调用点） |
| **触发条件** | V0 routing 关闭（`SUBAGENT_V0_ROUTING_ENABLED` 未设置或为 falsy），**或** V0 handler missing → `not_supported` 状态 |
| **Guard** | `core.py:2171` `if v0_result.status == "not_supported":` — 只有此状态触发 fallback（W1-D4 guard，本窗口 test-locked） |
| **用途** | Rollback-safe 执行路径：flag off 或 handler missing 时，用户仍得到 local_fake 响应 |
| **是否为 rollback path** | **是** — 这是 V0 routing 的 rollback 地板 |
| **本窗口动作** | 保留；`test_legacy_path_inventory.py::TestW2T5FlagOffLegacyPath` + `TestW2T6HandlerMissingFallback` 做 characterization |
| **未来评估触发** | 当 V0 routing 成为 default-on 且经生产验证后，可考虑是否保留 fallback |

---

## 2. pre-loop delegation seam

| 项目 | 内容 |
|---|---|
| **位置** | `agent/core.py:1975` — `_dispatch_or_fallback_delegation()` 函数定义；调用点 `:898`（CLI meta-command）和 `:931`（NL delegation） |
| **用途** | Loop 3.2a pre-loop seam：在 `run_main_loop()` 启动之前处理 delegation 请求，兼容"无 loop context" 的 CLI 路径 |
| **是否为 rollback path** | **是** — pre-loop seam 是 run_main_loop 内 V0 路由和 L0 inline fallback 的共同入口 |
| **本窗口动作** | 不动；`test_legacy_path_inventory.py::TestW2T6HandlerMissingFallback::test_pre_loop_seam_exists_in_core` 做存在性快照 |
| **未来评估触发** | V0 routing 完全接管 + loop context 改造后可评估 seam 生命周期 |

---

## 3. L1 attempt（dead-ish compatibility path）

| 项目 | 内容 |
|---|---|
| **位置** | `agent/core.py:2217`（`delegate_l1_called` 读取点，handler 未注册） |
| **状态** | **Dead-ish retained** — SUBAGENT_DELEGATE_L1 handler 从未注册；dispatcher.route() 直接返回 not_supported；`delegate_l1_called` payload key 永远为 falsy |
| **用途** | 历史上为 L1 handler 留的 payload check；当前是 dead branch（handler 缺失时 not_supported 走 fallback） |
| **是否为 rollback path** | 否（此分支永远不会执行，handler 缺失） |
| **本窗口动作** | 只做 inventory 登记（此处），**不加 retention test**（Plan §8D 明确：不写 no-delete guarantee 避免固化待清理行为） |
| **未来评估触发** | W2-D4（`docs/06-audit/WINDOW_2_CLOSURE_AUDIT.zh.md` §debt）——L1 dead-code 移除可在独立 cleanup 窗口评估 |

---

## 4. local_fake path

| 项目 | 内容 |
|---|---|
| **位置** | `agent/subagent_inline.py:63` — `SubAgentRequest(execution_mode="local_fake", ...)` |
| **用途** | 无 LLM 的 subagent 执行模式；调用 registry descriptor → `delegate_once()` → 返回 fake rendered result |
| **触发条件** | 所有 `execute_subagent_delegation()` 调用（inline-local fallback path）均使用此 mode |
| **是否为 rollback path** | **是** — local_fake 是 rollback-safe 的 execution mode（无副作用，无实际 API 调用） |
| **本窗口动作** | 保留；`test_legacy_path_inventory.py::TestW2T5FlagOffLegacyPath::test_inline_local_fallback_uses_local_fake_execution_mode` 做存在性快照 |
| **未来评估触发** | V0 routing 切换到 real_opt_in 后，local_fake 路径演变为纯测试路径时可重新评估 |

---

## 5. action_scheduler（registered-not-routed / inert）

| 项目 | 内容 |
|---|---|
| **位置** | `agent/action_scheduler.py:215`（`class ActionScheduler`）；`agent/core.py:697/:772/:1333/:1735`（参数 `action_scheduler=None`） |
| **状态** | **Inert** — class 定义存在但 core 默认不注入（`action_scheduler=None`）；`main.py:118/:177` 的 `chat()` 调用不传此参数 |
| **用途** | Loop 3.4 Advanced Scheduler 的骨架实现；registered（代码存在）但 not-routed（默认 None）；当 `action_scheduler is not None` 时才激活（生产路径无法触达） |
| **是否为 rollback path** | 否（未接入生产，不是 rollback path） |
| **本窗口动作** | 加 inert 治理标注（CR-1）；加 AST boundary test（`test_architecture_boundaries.py`）；不接入、不删除 |
| **未来评估触发** | OD-7 / CR-2 阶段，当 multi-turn planning 需求明确后 |

---

## 6. W1-D4 fallback dispatch guard（本窗口已落地）

| 项目 | 内容 |
|---|---|
| **位置** | `agent/core.py:2171` `if v0_result.status == "not_supported":` |
| **状态** | **Medium debt → test-guarded（本窗口落地）** — Window 1 记录为 negative-match；Window 2 补 `test_subagent_v0_fallback_dispatch.py` |
| **Guard 语义** | 只有 `not_supported` 触发 inline fallback；rejected / failed / policy_blocked / unknown status 不 fallback、不被当成 success |
| **测试** | `tests/runtime_integration/test_subagent_v0_fallback_dispatch.py`（全部 GREEN） |

---

## 7. 本窗口不删除的路径汇总

| 路径 | 原因 |
|---|---|
| inline-local fallback | Rollback path for V0 routing；V0 未完全 default-on |
| pre-loop delegation seam | Loop 3.2a 入口；没有替代实现 |
| L1 attempt dead branch | 只删除需要独立 cleanup 窗口（W2-D4） |
| local_fake execution mode | Rollback-safe execution；无 LLM 依赖 |
| action_scheduler class | CR-1 规定只做 governance 标注，不删除 |

---

## 8. 未来 CR 阶段再评估的路径

| 路径 | 评估触发 | 窗口建议 |
|---|---|---|
| L1 attempt dead branch | V0 default-on + 生产验证 | W2-D4（独立 cleanup） |
| action_scheduler | OD-7 / multi-turn planning 需求 | CR-2 或后续专项 |
| inline-local fallback | V0 default-on + local_fake 退为纯测试路径 | V0 rollout 后评估 |
| pre-loop seam | Loop context 改造完成 | 独立 seam 演进窗口 |
