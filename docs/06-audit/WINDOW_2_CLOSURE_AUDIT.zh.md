# Window 2 Closure Audit

> **裁决**：`ACCEPT_WITH_TRACKED_DEBT — WINDOW 2 CLOSED`
>
> 关闭时间：2026-06-13
> 关闭 HEAD：`a3e242e5f6f843fa620f62a18a7cab1108391d53`
> 关联 Plan：`docs/plans/2026-06-13-001-window-2-spa1-cr1-plan.md`（commit `e60704d`）
> 实施 commit：`a3e242e`（test(window2): lock SPA-1 masking ownership, CR-1 scheduler governance, and W1-D4 fallback guard）

---

## 1. Window 2 目标回顾

| 目标 | Plan §ID | 状态 |
|---|---|---|
| SPA-1：锁定 masking ownership（Option B） | §5/§8A | ✅ COMPLETED |
| CR-1：governance label + AST boundary tests | §5/§8B | ✅ COMPLETED |
| W1-D4：fallback dispatch guard test-locked | §5/§8C | ✅ COMPLETED |
| 兼容路径 inventory（characterization only） | §5/§8D | ✅ COMPLETED |

---

## 2. 实施证据

### 2.1 SPA-1 — masking ownership locked（Option B）

**决策**：`display_events.py` = canonical masking owner；`safe_metadata.py` = projection wrapper。

| 证据 | 位置 | 结果 |
|---|---|---|
| `_SECRET_MASK_PATTERNS` 只在 display_events 定义 | `test_safe_metadata_ownership.py::TestW2T1SingleOwner` (5 tests) | GREEN |
| projector 委托 `mask_user_visible_secrets`，不重复编译 canonical 正则 | `test_safe_metadata_ownership.py::TestW2T2ProjectionOnlyDelegation` (6 tests) | GREEN |
| `_EXTRA_REDACT_PATTERNS` boundary-local（定位 evidence_persistence trust boundary） | W2-T2c/T2d | GREEN |
| projector thin wrapper docstring 存在 | W2-T2e | GREEN |
| 端到端等价（projector 结果 = canonical masker 结果） | W2-T2f | GREEN |
| 决策文档 | `docs/06-audit/SPA1_MASKING_OWNERSHIP_DECISION.zh.md` | PRESENT |

### 2.2 CR-1 — action_scheduler governance locked

**状态**：`dormant-by-default / registered-not-routed in production`（class 存在，生产入口默认不注入；测试可手工注入 seam）。

| 证据 | 位置 | 结果 |
|---|---|---|
| module docstring 8 行 CR-1 治理标注 | `agent/action_scheduler.py` 顶部 | PRESENT |
| `core.chat()` `action_scheduler=None` default（AST） | `test_cr1_chat_default_action_scheduler_is_none` | GREEN |
| `main.py` 不传 `action_scheduler=` kwarg（AST） | `test_cr1_main_py_does_not_pass_action_scheduler_kwarg` | GREEN |
| `main.py` 不 import `agent.action_scheduler`（AST） | `test_cr1_action_scheduler_not_routed_in_production` | GREEN |
| `ActionScheduler` class 存在 + `core.chat` 默认 None 双重 AST 验证 | `test_cr1_action_scheduler_class_exists_and_is_not_wired` | GREEN |
| compat inventory 登记 | `docs/06-audit/WINDOW_2_COMPAT_INVENTORY.zh.md §5` | PRESENT |

**注**：所有 CR-1 boundary tests 使用 AST，不使用 grep，避免 `action_scheduler.py:221` docstring 字面量污染。

### 2.3 W1-D4 — fallback dispatch guard locked

**语义**：`core.py:2171` `if v0_result.status == "not_supported":` 是唯一 inline fallback 触发点。

| 证据 | 位置 | 结果 |
|---|---|---|
| `not_supported` → inline-local fallback 触发 | `TestW2T4FallbackOnlyOnNotSupported` (2 tests) | GREEN |
| `rejected` / `failed` / `policy_blocked` / `success` 不触发 fallback | `TestW2T4NoFallbackOnOtherStatus` (4 tests) | GREEN |
| known status 枚举 + fallback 只在 handler-missing 时产生 | `TestW2T4UnknownStatusGuard` (3 tests) | GREEN |
| 源码级：guard 行后 10 行内有 `_execute_subagent_delegation` 调用 | source-level test | GREEN |

### 2.4 兼容路径 Inventory

| 路径 | 性质 | 测试类型 | 结果 |
|---|---|---|---|
| inline-local fallback（`subagent_inline.py:63 local_fake`） | rollback path | characterization（W2-T5e/T6d/T6e） | GREEN |
| pre-loop delegation seam（`core.py:1975`） | rollback path | existence snapshot（W2-T6c） | GREEN |
| L1 attempt dead-ish branch（`core.py:2217`） | dead code | inventory only（无 retention test） | N/A（intentional） |
| local_fake execution mode | rollback-safe execution | characterization（W2-T5e） | GREEN |

**总计**：W2 专项 34 tests，全 GREEN。

---

## 3. Full Suite 结果

```
pytest tests/ -x -q
4720 passed, 12 skipped, 26 xfailed in 120.68s
```

- 26 xfailed：全部为预先标注的已知失败（config.yaml 环境依赖，RFC 文件路径等），无新增。
- 0 unexpected failures。
- golden_e2e：8 passed（`tests/golden_e2e/`）。

---

## 4. Ruff 状态

```
ruff check tests/runtime_integration/test_subagent_v0_fallback_dispatch.py \
  tests/runtime_integration/test_safe_metadata_ownership.py \
  tests/runtime_integration/test_legacy_path_inventory.py \
  tests/test_architecture_boundaries.py
All checks passed!
```

`git diff --check`：无 trailing whitespace / conflict markers。

---

## 5. 红线合规检查

| 红线（来自 Plan §12 / AGENTS.md） | 状态 |
|---|---|
| 不删 inline-local fallback / L1 attempt / pre-loop seam | ✅ 保留 |
| 不接入 action_scheduler（不传 `action_scheduler=` kwarg） | ✅ 遵守 |
| 不修改 North Star / Window 1 Plan / AGENTS.md | ✅ 未改 |
| 不 push / force push | ✅ 未 push |
| 不改 masking 正则行为（behavior-neutral） | ✅ 零行为改动 |
| 不 commit graphify-out/ | ✅ 未包含 |
| AST boundary tests 不用 grep（避免 docstring 污染） | ✅ 全 AST |
| 不实施 OD-7（human approval hook） | ✅ 未实施 |

---

## 6. 延伸债务（Window 2 registered）

| ID | 描述 | Severity | 阻塞 W2 关闭 |
|---|---|---|---|
| W2-D1 | `_EXTRA_REDACT_PATTERNS` 长期归属（boundary-local vs. canonical owner） | Low | 否 |
| W2-D2 | OD-7：Human approval hook 生产化 | Low | 否（Open Decision） |
| W2-D3 | SPA-2：permission vs. policy staging 口径 doc-align | Low | 否 |
| W2-D4 | L1 attempt dead-code removal | Low | 否（独立 cleanup 窗口） |

全部 debt 均已在 `CURRENT_ARCHITECTURE_REPAIR_ROADMAP.zh.md §9.4` 登记，均不阻塞 Window 2 关闭。

---

## 7. 裁决

**`ACCEPT_WITH_TRACKED_DEBT — WINDOW 2 CLOSED`**

- SPA-1：canonical masking ownership 已 test-locked（Option B，11 tests GREEN）。
- CR-1：action_scheduler dormant-by-default 状态已 governance-labeled + AST boundary test-locked（4 tests GREEN）。
- W1-D4：fallback dispatch guard 已 test-locked（9 tests GREEN）。
- 兼容路径 inventory 已作为 characterization snapshot 存档，不是 no-delete guarantee。
- 全套 4720 tests 无意外失败；ruff clean；所有红线遵守。
- 4 项 tracked debt 均为 Low，已登记，不阻塞关闭。
