# SPA-1: Masking Ownership Decision — Option B

> **决策状态：APPROVED**
> 批准时间：Window 2（2026-06-13）
> 批准依据：用户明确批准 Option B；Window 2 Plan §8A / §5 记录。

---

## 1. 问题描述

`agent/display_events.py` 和 `agent/runtime_integration/safe_metadata.py` 均涉及
secret masking，需要确认哪个模块是 canonical masking owner，防止未来维护时
masking 逻辑漂移到多个文件中。

---

## 2. 候选方案

### Option A（拒绝）

将 masking 实现从 `display_events.py` 迁移到 `safe_metadata.py`，
`display_events.py` 改为 import 并复用。

**拒绝原因**：
- 需要 ~15 个 call-site edit，触及 `tool_executor`、`tool_result_contract` 等稳定路径
- 会破坏 `test_architecture_boundaries.py` 的 import allowlist 契约
- 违反 behavior-neutral 原则（本窗口性质是治理标注，不是功能变更）
- `display_events.py` 与 UI-projection 逻辑高度内聚，masking 应留在该层

### Option B（已批准）

确认 `display_events.py` 是 canonical masking owner；
`safe_metadata.py` 保持 projection wrapper / truncation / boundary-local extra redaction 角色。

**批准原因**：
- 现有代码已处于 Option B 形态（~0 production 代码改动）
- `safe_metadata.py` 已有 "thin wrapper, not a replacement" 的 module docstring 声明
- `_EXTRA_REDACT_PATTERNS` 的 boundary-local 用途已有注释说明
- ownership test 证明当前结构满足 single-owner 契约

---

## 3. 技术证据

### display_events.py（canonical masking owner）

- `_SECRET_MASK_PATTERNS`（`:104`）：module-level tuple，包含全套 canonical 正则
- `_mask_preview_secrets()`（`:120`）：内部 masking 函数
- `mask_user_visible_secrets()`（`:129`）：public API，统一脱敏入口

### safe_metadata.py（projection wrapper）

- module docstring（`:1`）：`"This module is a thin wrapper, not a replacement."`
- `from agent.display_events import mask_user_visible_secrets`（`:31`）：委托 canonical masker
- `_EXTRA_REDACT_PATTERNS`（`:39`）：
  - 仅在 `project_safe_metadata_text_with_marker()` 中应用（`:93`）
  - 注释明确：`"Defense-in-depth redactors for the evidence_persistence trust boundary (D2)"`
  - 定位为 boundary-local extra redaction，不是 canonical masking 的第二份实现

### 测试锁定

- `tests/runtime_integration/test_safe_metadata_ownership.py`（Window 2 新增）：
  - W2-T1：`_SECRET_MASK_PATTERNS` 只在 `display_events.py` 定义（5 个断言，全 GREEN）
  - W2-T2：projector 委托 `mask_user_visible_secrets`；`_EXTRA_REDACT_PATTERNS` boundary-local（6 个断言，全 GREEN）
- `tests/runtime_integration/test_safe_metadata_projector.py`（Window 1 已有）：
  - projector 契约行为已覆盖（masking 等价、mask-then-truncate 顺序等）
- `tests/runtime_integration/test_safe_metadata_leak_gate.py`（Window 1 已有）：
  - 端到端 leak-gate 保护（24 seeds，全 GREEN）

---

## 4. 决策

**Option B 已批准**：

1. `display_events.py` = **canonical secret-masking owner**（不变）
2. `safe_metadata.py` = **projection wrapper / truncation / boundary-local extra redaction**（不变）
3. `_EXTRA_REDACT_PATTERNS` 保留在 `safe_metadata.py`，定位为 evidence_persistence 边界专用额外脱敏层
4. 不做 call-site sweep（Roadmap 红线 §12 #12）
5. 不改变任何 masking regex 行为

---

## 5. 延伸债务

- **W2-D1**：`_EXTRA_REDACT_PATTERNS` 长期是否收归 canonical owner（`display_events.py`）—— 待 trust-boundary contract 演进时复议，本窗口维持 boundary-local 定位。
