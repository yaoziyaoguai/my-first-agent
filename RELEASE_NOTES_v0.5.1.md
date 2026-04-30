# my-first-agent v0.5.1 Release Notes

## 1. Release status

> 本文件状态：**v0.5.1 已 tag 并 push**；annotated tag `v0.5.1`（对象 `ce65bdca`）指向 commit `240308b`，已存在于 `origin/main`。`v0.5.0` tag 仍指向 `32d4ca1`，未移动。
>
> 单一索引入口；详细 evidence 见
> [`docs/audits/v0.5.1_checkpoint_resume_audit.md`](docs/audits/v0.5.1_checkpoint_resume_audit.md)。

---

## 2. Release theme

**runtime boundary evidence hardening**

v0.5.1 **不**是新功能发布。它显式**不**包含：

- TUI / Textual / prompt_toolkit 升级；
- StateSnapshot / 状态机重写；
- checkpoint/resume production rewrite；
- 完整状态机重写；
- 真实 LLM / 真实 sessions/runs 读取；
- 任何 v0.6 scope。

v0.5.1 做的是：把 v0.5.0 之后 `agent/core.py` 里两段"长 if 链 + 调度副作用"混在一起的代码——
chat() 的 pending confirmation 分发、`_run_main_loop` 的 ModelOutputKind 分发——
**先用 characterization tests 钉死行为基线，再做 behavior-neutral helper extraction，最后补齐
checkpoint→resume→dispatch 端到端 evidence**。

这服务于"高内聚、低耦合"的架构目标，但请注意诚实表述：
v0.5.1 是**为后续模块化和 v0.6 TUI 打基础**，不是"架构已经完全高内聚低耦合"。
`agent/core.py` 仍然是 runtime orchestrator；本轮只让两个关键 dispatch 边界变得显性、可回归、
可在未来安全继续瘦身。

---

## 3. Completed slices

> 列出 v0.5.0（`32d4ca1`）之后 → v0.5.1 候选 HEAD（`2663866`）的全部 commit。

| # | Commit | Slice | Change type | 主要文件 | 保护的边界 | 显式不做 |
|---:|---|---|---|---|---|---|
| 1 | `decacfb` | display callback failure isolation | runtime hardening | `agent/core.py::_safe_emit_runtime_event` + tests | 单个 callback 抛错时 runtime event 派发链不被中断 | 不重写 callback 注册机制；不引入 priority；不改 event schema |
| 2 | `cdd1427` | pending confirmation dispatch characterization tests | tests-only | `tests/test_pending_confirmation_dispatch.py`（11 char + 1 helper） | 5 类 `pending_*` 状态如何被 chat() 路由到对应 confirm handler；handler None→continue / str→return 两段语义 | 不改 production；不改 handler 内部；不读真实 sessions |
| 3 | `bf49a84` | extract `_dispatch_pending_confirmation` helper | **由 characterization tests 保护的行为中性 refactor** | `agent/core.py`（提取 helper + chat() 调用点） | chat() 不再直接展开 5-分支 if 链 | 不改 handler 签名；不引入状态机；不改 chat() 入参 |
| 4 | `605196c` | model output dispatch characterization tests | tests-only | `tests/test_model_output_dispatch.py`（9 char + 1 helper） | `_run_main_loop` 4 个 ModelOutputKind 分支命中正确 handler；`classify_model_output` 是唯一真值源；4-value vocabulary 稳定 | 不改 production；不改 handler；不读真实模型流 |
| 5 | `be502c7` | extract `_dispatch_model_output` helper | **由 characterization tests 保护的行为中性 refactor** | `agent/core.py`（提取 ~210 行 helper + `_run_main_loop` 调用点收窄到 10 行） | `_run_main_loop` 不再直接展开 4-分支 dispatch；UNKNOWN 分支固定发 `unknown_stop_reason_event` | 不动 `_call_model`；不动 iteration 计数；不动 max_iter；不动 messages |
| 6 | `73bb6b2` | resume pending dispatch characterization tests | tests-only | `tests/test_resume_pending_confirmation_dispatch.py`（5） | save → load → 装回 `core.state` → `chat()` → 命中预期 confirm handler 的端到端路径 | 不改 production；不改 checkpoint schema；不读真实 checkpoint |
| 7 | `2663866` | checkpoint/resume audit doc | docs-only | `docs/audits/v0.5.1_checkpoint_resume_audit.md` | 把上述 6 个 commit 的 evidence 整理成 reviewer 索引 | 不改 production；不改 tests；不改 README |

> **关于 `bf49a84` / `be502c7`**：这两次 refactor 动了 production code，**不应被读成"完全无风险"**。
> 它们的中性性由前一个 commit 的 characterization tests 提供保护：
> `bf49a84` 不改 `cdd1427` 任何测试即通过；`be502c7` 不改 `605196c` 任何测试即通过。
> 如果未来要修改这两个 helper 的内部分支，必须先扩对应 characterization 套件。

---

## 4. Behavior changes

谨慎说明：

| Commit | 是否改 runtime 用户可见行为 | 备注 |
|---|---|---|
| `decacfb` | ✅ 是 — 显式 runtime hardening | 增加 callback 失败隔离；callback 抛错不再向上冒泡到 event emit 调用方 |
| `cdd1427` | ❌ 否 | tests-only |
| `bf49a84` | ❌ 否（行为中性 refactor） | 受 `cdd1427` characterization 套件保护 |
| `605196c` | ❌ 否 | tests-only |
| `be502c7` | ❌ 否（行为中性 refactor） | 受 `605196c` characterization 套件保护 |
| `73bb6b2` | ❌ 否 | tests-only |
| `2663866` | ❌ 否 | docs-only |

**不要把"行为中性 refactor 通过测试"读成"所有可能行为都已被证明完全正确"**：
characterization tests 只钉住已被覆盖的分支组合，不证明未覆盖路径无 bug。
如发现未覆盖路径需要保护，应在未来 slice 里**先补 characterization、再动 production**。

---

## 5. Evidence summary

详细 evidence index 见：
[`docs/audits/v0.5.1_checkpoint_resume_audit.md`](docs/audits/v0.5.1_checkpoint_resume_audit.md)

5 类 boundary：

1. **display callback failure boundary** — `_safe_emit_runtime_event` (decacfb)
2. **pending confirmation dispatch boundary** — `_dispatch_pending_confirmation` (bf49a84) + 11 char tests + 1 helper test (cdd1427)
3. **model output dispatch boundary** — `_dispatch_model_output` (be502c7) + 9 char tests + 1 helper test (605196c)
4. **checkpoint field preservation boundary** — `tests/test_checkpoint_roundtrip.py`（8）+ `tests/test_checkpoint_resume_semantics.py`（14）（这些测试不在本 release 创建，但本 release 显式承认它们与新增 bridge 的边界关系）
5. **resume → pending confirmation dispatch bridge** — `tests/test_resume_pending_confirmation_dispatch.py`（5, 73bb6b2）

> Release notes 是**索引**；boundary 矩阵 / pending 5 状态矩阵 / ModelOutputKind 4 值矩阵 / 3 strict xfail 详细解释 全部在 audit doc。
> 重复展开会让 release notes 与 audit doc 出现漂移风险。

---

## 6. Architecture impact

v0.5.1 让 `agent/core.py` 的两个关键 dispatch 边界**显性化**：

- `_dispatch_pending_confirmation`（用户输入侧）
- `_dispatch_model_output`（模型输出侧）

**局部内聚提升**：
- 用户输入侧 5 类 pending confirmation 分发逻辑集中在单一 helper；
- 模型输出侧 4 类 ModelOutputKind 分发逻辑集中在单一 helper；
- 调用点（chat() 与 `_run_main_loop`）从内嵌长 if 链收窄为单行 helper 调用。

**局部耦合风险下降**：
- chat() 不再直接展开所有 pending confirmation 分支 → 未来引入新的 pending 类型时改动面被 helper 隔离；
- `_run_main_loop` 不再直接展开所有 model output 分支 → 未来引入 cancel_token / stream abort（v0.2/v0.3 路线）时改动面被 helper 隔离；
- checkpoint→resume→dispatch bridge tests 降低"恢复了字段但 runtime 没真正命中分支"的静默风险。

**诚实声明**：
- `agent/core.py` 仍然是 runtime orchestrator，并未拆分成独立模块；
- 仅有 2 个 dispatch 边界被收口，chat() 顶层 resume detection / new_task entry / `_call_model` 等其他边界仍是未来 slice；
- v0.5.1 是"为后续模块化和 v0.6 TUI 打基础"，**不是**"项目已完成高内聚低耦合"。

---

## 7. Quality gates

本轮在 commit 前后均验证：

- `.venv/bin/python -m ruff check .` → **All checks passed**
- `.venv/bin/python -m pytest -q` → **901 passed, 3 xfailed**
- `git diff --check` → clean

**关于 3 xfailed**：
- 不阻塞 v0.5.1；
- 不要在 v0.5.1 强行解；
- 三者归属与解锁条件详见 [audit doc §7](docs/audits/v0.5.1_checkpoint_resume_audit.md#7-3-个-strict-xfail-的解释)。

---

## 8. Limitations / Not included

v0.5.1 显式**不**做：

- ❌ no TUI（Textual / prompt_toolkit / Esc 升级）
- ❌ no StateSnapshot / 状态机重写
- ❌ no checkpoint/resume production rewrite（schema、序列化器、文件锁、并发恢复）
- ❌ no real `sessions/` / `runs/` / `agent_log.jsonl` reading
- ❌ no real LLM call
- ❌ no external service dependency
- ❌ no full state machine rewrite
- ❌ no v0.6 scope
- ❌ no tag movement（`v0.5.0` 仍指向 `32d4ca1`）
- ❌ no解 3 个历史 strict xfail（归属 v0.2/v0.3）
- ❌ no `agent/core.py` 大爆炸瘦身

---

## 9. Reviewer links

按以下顺序复核：

- **Audit index**：[`docs/audits/v0.5.1_checkpoint_resume_audit.md`](docs/audits/v0.5.1_checkpoint_resume_audit.md)（含完整 boundary map / pending matrix / ModelOutputKind matrix / xfail 解释 / reviewer checklist）
- **新增 helper**（`agent/core.py`）：
  - `_safe_emit_runtime_event`（decacfb）
  - `_dispatch_pending_confirmation`（bf49a84）
  - `_dispatch_model_output`（be502c7）
- **新增 tests**：
  - `tests/test_pending_confirmation_dispatch.py`（cdd1427/bf49a84）
  - `tests/test_model_output_dispatch.py`（605196c/be502c7）
  - `tests/test_resume_pending_confirmation_dispatch.py`（73bb6b2）
- **既有相关 tests**（未在 v0.5.1 修改，列出供边界对照）：
  - `tests/test_checkpoint_roundtrip.py`
  - `tests/test_checkpoint_resume_semantics.py`
- **前一 release**：[`RELEASE_NOTES_v0.5.md`](RELEASE_NOTES_v0.5.md)

---

## 10. Tag plan

- **本轮不 tag**；
- release notes commit 后需要先审计；
- 审计 PASS 后 push release notes；
- 之后再单独准备 v0.5.1 tag checklist；
- tag 必须由用户**明确授权**，不允许 agent 自行决定；
- tag 前必须确认：
  1. working tree clean；
  2. ahead/behind = 0/0；
  3. HEAD on `origin/main`；
  4. `.env` / `agent_log.jsonl` / `sessions/` / `runs/` 未被 git track；
  5. `.venv/bin/python -m ruff check .` 全绿；
  6. `.venv/bin/python -m pytest -q` 仍是 `901 passed, 3 xfailed`；
  7. `git diff --check` clean；
  8. `git rev-parse v0.5.0` 仍为 `15782202fb35e3690c91c4b3b61148d605915c8e`（即 `v0.5.0` 仍指向 `32d4ca1`）。

> v0.5.0 tag 是**不可移动**的稳定基线；任何"重打 v0.5.0"的提议都应直接拒绝。
> 如发现 v0.5.0 evidence 需要补充，应通过新的 v0.5.1+ 文档而非移动 tag 实现。
