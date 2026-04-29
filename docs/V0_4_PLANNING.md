# Runtime v0.4 Planning

> 本文件目的：在 v0.3 已 release 的基础上，定义 v0.4 的目标、非目标、
> milestone 顺序与完成标准。**这是 planning，不是承诺**——任何 milestone
> 在真正开始实现前，仍要逐项跟用户确认范围。
>
> v0.4 沿袭 v0.3 的克制：**不是新能力大爆炸**。优先选 backlog 里
> 「人工日常使用 + 长期维护」语境下、能带来明确可观测增益的项；
> 不引入 Reflect / Self-Correction / sub-agent / 完整 Textual 多面板。

---

## 1. 目标（in scope，候选）

v0.4 计划在以下 backlog 主题中**择一为主线**（待用户确认）：

- **A · Health Maintenance dry-run / archive 命令**
  在 v0.3 M2 「只可视化、不动文件」的基础上，引入 `python main.py health
  archive logs --dry-run` 和 `health archive sessions --dry-run`，
  **dry-run 默认**、必须显式 `--apply` 才动文件、归档后产物可回滚。
  价值：长期运行的 agent_log.jsonl / sessions/ 真实可控制。

  > **已知 gap（待主线 A 收口）**：本仓库实际跑出的 `agent_log.jsonl`
  > 已超过 100MB（已 gitignore，不会被 track，但仍是真实磁盘压力）。
  > 当前没有任何轮转 / 压缩 / 截断 / 归档策略，所有日志都追加到同一个
  > 文件。这是 v0.4 主线 A 必须解决的「真实长跑」问题，**不属于** v0.4
  > Phase 1 transition slice 范围；本条目仅作为后续 patch 的锚点，避免
  > 在 transition 工作过程中临时加入 ad-hoc 清理脚本。本轮（v0.3.x
  > hygiene）只在文档层面记录这个 gap，不引入任何 rotation 实现。

- **B · Checkpoint / Session 管理增强**
  在现有 `agent/session.py` / `agent/checkpoint.py` 之上，引入
  `python main.py sessions list` / `sessions show <id-prefix>` /
  `sessions resume <id-prefix>` / `sessions delete <id-prefix> --dry-run`，
  让 checkpoint resume 不再依赖默认 `state.json` 单文件。
  价值：人工试用积累的 sessions/ 可被结构化检索与复用。

- **C · Observer / Logs 深化**
  在 v0.3 M4 之上引入 `python main.py logs --since <iso>` /
  `--until <iso>` / `--stat`（按 event/tool 统计计数）/
  `--export <path>` 子命令；不引入 SQLite/ELK。
  价值：长期 jsonl 日志能被人工抽样分析。

- **D · Skill 子系统下一步（仍非完整 marketplace）**
  在 v0.3 M3 状态澄清之上，给 Skill 系统加：
  skill 单元测试基线、skill 级 tool 白名单（**仅描述层**，不引入新工具
  权限语义）、安全审查 dry-run 报告。
  价值：让 `agent/skills/` 从「实验性脚手架」走到「最小可信」。

> 用户最终选哪个或几个为主线，等本文件 §3 milestone 拆解时再定。

## 2. 非目标（explicitly out of scope）

下面这些**在 v0.4 一律不做**。如有需要，开 v0.5+ planning：

- ❌ Reflect / Self-Correction / LLM judge / self-evaluation loop
  （**没有用户明确同意，禁止引入**）
- ❌ sub-agent / multi-agent 协作（仍归 v1.0）
- ❌ 完整 Textual 多面板 / timeline viewer / event replay
- ❌ generation cancellation（cancel_token + stream abort + Esc cancel）
- ❌ 复杂 topic switch（已撤销过一次，不要复活）
- ❌ slash command 体系
- ❌ Skill marketplace / Skill lifecycle 完整化
- ❌ 真实 LLM live smoke 自动化
- ❌ HTTP transport 重写、新 provider 接入（除非 v0.4 主线明确包含）
- ❌ 健康检查 metric → Prometheus / Grafana 等 SRE pipeline
- ❌ 把项目写成成熟 LLM 平台
- ❌ Runtime 主循环 / RuntimeEvent / DisplayEvent / InputIntent 大改
- ❌ keyword 黑名单扩张（v0.3 patch 已锁死历史 patterns 上限）

> 任何写在「非目标」里的能力，如果在 v0.4 进行中被发现需要，**先停下来跟
> 用户确认是否扩 roadmap，不要默默扩**。

---

## 3. Milestone 顺序（待用户选定主线后细化）

候选 milestone（每个独立可发布，按依赖与价值排序）：

### v0.4 M0 · planning 收口（本文件）
- 写完 v0.4 planning（本文件）
- 跟用户确认主线（A/B/C/D 或组合）
- 不引入任何代码改动

### v0.4 M1 · 主线 milestone（待选）
- 由用户从 §1 候选中选定
- 拆解到 §4 完成标准、§5 测试策略、§6 风险

### v0.4 M2+ · 后续 milestone
- 等 M1 落地后再细化，避免承诺过早

---

## 4. 完成标准（v0.4 release readiness 时再核对）

候选条目（待 §3 主线选定后再补主线特定条目）：

- 主线 milestone 全部 ship 或显式登记为 partial（带原因）
- ruff 0 错；pytest 全绿（允许永久 xfail，但每个都必须有归属说明）
- 至少一次真实人工 smoke，结果记录在 `docs/V0_4_MANUAL_SMOKE_RESULT.md`
- 防泄漏审计延续：`tests/test_gitignore_runtime_artifacts.py` 通过；
  `git ls-files` 复核命令在 `RELEASE_NOTES_v0.4.md` 写明
- v0.3/v0.4 backlog 没有被偷偷做掉（§2 非目标依然为非目标）
- final answer / request_user_input 协议边界（v0.3 patch）保持不退化：
  `tests/test_final_answer_user_input_separation.py` 通过

---

## 5. 测试策略（候选）

- **单元测试**：每个新子命令的入参解析、dry-run 默认、结构化输出 schema
- **集成测试**：fake provider + 一段 scripted 对话验证不破 v0.2/v0.3 输出契约
- **回归测试**：所有 v0.2/v0.3 已有的 cross-layer guards 必须通过；不允许
  通过削弱测试来「让自己绿」
- **不**做 snapshot 大文件比较；用关键字 + 字段断言

---

## 6. 风险（候选主线共性）

- **过度设计风险**：每个 milestone 容易被带去做"顺便加面板/快捷键/cancel"。
  锚点：v0.4 输出仍是 plain stdout + jsonl。
- **状态泄漏风险**：任何 archive / dry-run 命令必须脱敏；不得把
  raw prompt / raw completion / api key 写进归档产物。
- **测试脆性风险**：渲染断言用关键字 + 字段，不用整段字符串等价比较。
- **与 v0.3 输出契约冲突风险**：v0.3 已冻结 4 类 tool outcome 文案、
  banner、Skill experimental 文案、health/logs 入口；v0.4 不破坏。
- **范围蔓延风险**：每个 milestone 上限是「一个主线 + 必要文档/测试」，
  不要在 v0.4 把 v0.5/v1.0 的 sub-agent / Reflect / 多 Agent 拉进来。

---

## 7. 跟 ROADMAP 的关系

- 本文件不替代 `docs/ROADMAP.md`，只是 v0.4 阶段的 **详细 planning**
- 等 v0.4 主线选定后，再回 ROADMAP 同步一行「v0.4 主线」并指向本文件
- v0.3 已完成内容见 `docs/V0_3_PLANNING.md` / `RELEASE_NOTES_v0.3.md` /
  `docs/V0_3_MANUAL_SMOKE_RESULT.md`
