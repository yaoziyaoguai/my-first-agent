# User Journey Static Review — Friction Matrix

- **Date:** 2026-05-25
- **Type:** read-only static audit of user-facing code and docs
- **Scope:** README → startup → chat → tool → memory → subagent → debug/report
- **Method:** trace each stage through implementation code (main.py, core.py, loop.py, cli_renderer.py, display_events.py, run_summary, fake_provider.py, cli_commands.py) and user-facing docs
- **No real dogfood executed.** No new capability implemented.

## Journey Stages

### Stage 1: README / First Impression

**Entry**: `README.md` → `docs/README.zh.md` → `CURRENT_CAPABILITY_STATUS.zh.md`

| # | Friction | Severity | Root cause | Fixable now? |
|---|----------|----------|------------|--------------|
| 1.1 | README ~340 lines — 对首次用户偏长 | P3 | 积累了大量历史 Roadmap、审计索引 | 否 — 需结构性 slimming |
| 1.2 | "文档阅读路径"列出 15 个文档 — 新用户不知道该读哪个 | P3 | docs 随 AutoRun 自然增长 | 否 — 当前已用 `docs/README.zh.md` 做分层 |
| 1.3 | README 安装命令写 `pip install -r requirements.txt`，dogfood template 写 `pip install -e ".[dev]"` — 不一致 | P3 | 不同时期写入，未同步 | **是** — 统一安装命令 |
| 1.4 | Memory Consolidation freeze note 引用 `global-agent-capability-architecture-audit` 而主要审计已是 `global-red-team-product-architecture-audit` | P3 | 审计文档有两份，引用旧的那份 | 否 — 两份审计并存是已知状态 |

### Stage 2: Startup / Provider Banner

**Entry**: `.venv/bin/python main.py --help` / `.venv/bin/python main.py`

| # | Friction | Severity | Root cause | Fixable now? |
|---|----------|----------|------------|--------------|
| 2.1 | `STAGE_LABEL = "Runtime v0.3 basic CLI shell"` — 版本标签过时，项目已过 v0.3 | P2 | cli_renderer.py 未随项目阶段演进同步更新 | **是** — 更新 stage label |
| 2.2 | Session header 显示 "Skill 系统仍是实验性能力" — 与 docs 冲突（Skill System formal safe-local 基线已完成） | P2 | 旧文案未随 Skill 主线完成而更新 | **是** — 更新 session header |
| 2.3 | `render_onboarding()` 产出 ~60 行 help 文本 — 全面但冗长 | P3 | 每个阶段都追加新段落 | 否 — 结构性 redesign |
| 2.4 | Provider banner 只有一行 `[provider] mode=fake...` — 对首次用户足矣，但可更醒目 | P3 | 有意保持最小 | 否 |

### Stage 3: Chat (FakeProvider)

**Entry**: `python main.py` → type message → FakeProvider responds

| # | Friction | Severity | Root cause | Fixable now? |
|---|----------|----------|------------|--------------|
| 3.1 | FakeProvider 响应为 "已收到你的消息：「...」" — 诚实但不像自然对话 | P3 | FakeProvider 设计为 deterministic fixture | 否 — frozen |
| 3.2 | 用户消息在 FakeProvider 中截断到 80 字符 | P3 | `_default_response_fn` 的硬编码限制 | 否 — frozen |
| 3.3 | 回复正文不注明是 fake 响应（只在 startup banner 说明一次） | P3 | 架构设计上 provider 对 runtime 透明 | 否 — 结构性 decision |

### Stage 4: Tool Use

**Entry**: Type "make a demo note" → tool_use detected → Tool Pipeline

| # | Friction | Severity | Root cause | Fixable now? |
|---|----------|----------|------------|--------------|
| 4.1 | Tool detection 是 deterministic 关键词匹配（非 LLM 推理） — 可选触发词集窄 | P2 | FakeProvider 的 FakeToolDecisionPolicy | 否 — frozen |
| 4.2 | Tool confirmation 提示技术性较强（展示 tool_use_id, input preview） | P3 | confirmation UI 偏开发者视角 | 否 — 需 human dogfood 反馈 |
| 4.3 | `demo.write_demo_note` 写入 `workspace/demo/` — 用户可能不知道这个路径 | P3 | 工具设计时假设用户了解项目结构 | 否 — 需 broader UX polish |

### Stage 5: Memory

**Entry**: `show memories` / `remember` / `forget`

| # | Friction | Severity | Root cause | Fixable now? |
|---|----------|----------|------------|--------------|
| 5.1 | Memory 两阶段确认流程对新用户不直观（先 propose → 确认 → 再 retain） | P3 | 架构设计的安全性要求 | 否 — safety by design |
| 5.2 | `forget` 需要先 `show memories` 获取短 ID — 两步操作 | P3 | 这是 forget-by-ID 的必要前提 | 否 — 已支持关键词 forget |
| 5.3 | `show memories` 空状态只显示 "暂无已保存的记忆。" — 缺少 "如何创建记忆" 的 hint | P3 | 最小化设计 | **是** — 可加一行 hint |

### Stage 6: SubAgent

**Entry**: `show subagents` / `delegate to demo-stat: ...`

| # | Friction | Severity | Root cause | Fixable now? |
|---|----------|----------|------------|--------------|
| 6.1 | SubAgent 列表标注 DEMO-ONLY，但委托时用户体验类似真实功能 | P2 | L0 deterministic 行为容易过分解读 | 否 — 标签已足够 |
| 6.2 | NL delegation 只支持固定短语匹配（"帮我统计 demo workspace" / "summarize files"） | P3 | deterministic fixture | 否 — frozen |
| 6.3 | `delegate to` 语法对非技术用户不直观（冒号分隔符） | P3 | CLI meta-command 设计 | 否 — 这是 transitional affordance |

### Stage 7: Debug / Report

**Entry**: Run summary at turn end, `python main.py health`, `python main.py logs`

| # | Friction | Severity | Root cause | Fixable now? |
|---|----------|----------|------------|--------------|
| 7.1 | Run summary 显示 "循环次数" 等技术指标 — 对普通用户无意义 | P3 | 当前 summary 偏开发者视角 | 否 — 需 UX polish |
| 7.2 | 纯聊天 turn 也显示 "本轮活动：未调用工具 / 未写入 Memory / 未委托 SubAgent" — 冗余 | P3 | zero-activity 消息设计 | 否 — 已在上轮 polish 中改过 |
| 7.3 | Status line 显示内部状态名如 "awaiting_tool_confirmation" | P3 | 内部状态直接映射到 UI | 否 — 需 broader UX polish |
| 7.4 | `--help` 和 `health`/`logs` 的引用混在 session header 中 | P3 | 维护命令与交互提示混排 | 否 — 结构性调整 |

## Friction Summary

| Stage | P2 | P3 | Total |
|-------|----|----|-------|
| README/First Impression | 0 | 4 | 4 |
| Startup/Banner | 2 | 2 | 4 |
| Chat (FakeProvider) | 0 | 3 | 3 |
| Tool Use | 1 | 2 | 3 |
| Memory | 0 | 3 | 3 |
| SubAgent | 1 | 2 | 3 |
| Debug/Report | 0 | 4 | 4 |
| **Total** | **4** | **20** | **24** |

## Fixable Now (this loop)

| # | Fix | File | Effort |
|---|-----|------|--------|
| F-1 | 更新 STAGE_LABEL 从 "Runtime v0.3 basic CLI shell" 到当前阶段描述 | `agent/cli_renderer.py` | 1 line |
| F-2 | 更新 session header 中 skill 状态文案 | `agent/cli_renderer.py` | 2 lines |
| F-3 | 对齐 README 安装命令与 dogfood template | `README.md` | 1 line |
| F-4 | `show memories` 空状态加 hint | `agent/display_events.py` | 1 line |

## Needs Human Dogfood (P2, cannot auto-fix)

- Tool confirmation UX 是否清晰可信
- Memory 两阶段确认是否易理解
- SubAgent DEMO-ONLY 标签是否足够醒目
- Startup banner 信息是否足够
- Run summary 是否帮助用户理解发生了什么

## Structural (requires broader loop)

- 版本标签体系整体更新（多处 v0.3 引用）
- README/doc 精简
- Onboarding help 重构
- Status line 用户友好化
- FakeProvider 响应透明度
