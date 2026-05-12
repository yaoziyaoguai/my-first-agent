# Memory Dogfooding Guide

> 目标: 真实使用和观察当前 Memory System（Phase 4 baseline），
> 暴露实际问题，而不是继续设计新功能。
>
> 本文档不是开发指南，是使用和观察指南。

---

## 1. 当前 Memory 能力边界

### 1.1 支持什么（Phase 4 Baseline）

| 能力 | 如何触发 | 说明 |
|------|---------|------|
| **显式 retain** | 在对话中说 "记住 X" 或 "remember that X" | policy 层正则匹配，弹出 confirmation |
| **显式 forget** | 在对话中说 "忘记 X" 或 "forget X" | 无需二次确认，立即删除 |
| **L1 启发式建议** | 对话中含特定关键词模式时自动触发 | 见 §3 四种规则详情 |
| **5 种确认选择** | retain 弹出 confirmation 时 | ACCEPT / EDIT_AND_ACCEPT / REJECT / SESSION_ONLY / OTHER |
| **Filesystem 存储** | 需设置环境变量 | `MEMORY_STORE_BACKEND=filesystem MEMORY_ROOT=~/.my-first-agent/memory` |
| **Recall / Snapshot** | 自动注入 system prompt | 每次对话开始时自动从 store 加载 |
| **Sensitivity 阻断** | 含 secret/password/token 等关键词 | 自动拒绝，不弹出 confirmation |
| **Prompt injection 阻断** | 含 "ignore previous instructions" 等 pattern | 自动拒绝 |
| **去重** | 同内容再次出现时 | SHA256 去重，不重复保存 |
| **频率限制** | 单 session 建议 >3 次 | 第 4 次起自动跳过 |
| **Forget** | 说 "forget X" | 立即删除，无需确认 |

### 1.2 明确不支持

| 不支持 | 原因 |
|--------|------|
| LLM 自动提取 memory | 设计为 Phase 5，当前不做 |
| Session 结束时自动提取 | 设计为 Phase 5，当前不做 |
| 自动写入（不经过 confirmation） | 宪法级禁止（P8） |
| 语义搜索 / 向量检索 | 宪法级不做 |
| 跨设备同步 | 单机、单用户设计 |
| 记忆衰减 / 自动过期 | Phase 6+ 远期研究 |
| Episodic → Procedural 自动升级 | Phase 6+ 远期研究 |

---

## 2. 三种长期记忆的当前真实行为

> 这三种类型属于 Memory Taxonomy 中的 Long-Term Memory Layer（长期记忆层），进 filesystem store 和 governance chain。Working/Session 属于 Runtime/Context Layer，不进 store。详见 MEMORY_CANONICAL_RFC.md §2.1。

### 2.1 Semantic（语义记忆）

**当前实际触发方式**：
- 用户显式说 "记住 X" → policy 匹配 → confirmation → 写入
- L1 规则 `architecture_decision` 匹配 "我们选了/决定用…" → suggestion → confirmation → 写入
- L1 规则 `repeated_preference` 匹配 "我喜欢/习惯…" ×3 → suggestion → confirmation → 写入

**存储后行为**：
- 存入 `semantic/user_preferences.md` 等文件
- 下次对话通过 MemorySnapshot 注入 system prompt
- 对 Agent 行为的影响：prompt 中可见，Agent 可据此调整回答风格

**当前局限**：
- L1 只匹配含关键词的显式偏好，不含关键词的偏好表达会被漏掉
- 不包含 factual correctness 验证

### 2.2 Episodic（情景记忆）

**定义**：以具体事件为中心的叙事性记录，回答"那次发生了什么"。核心特征：有时间锚点（日期/session）、有因果结构（问题→尝试→结果）、可复述为完整叙事。与 Semantic 的边界：Episodic 回答"那次发生了什么"，Semantic 回答"我知道了什么"。

**当前实际触发方式**：
- L1 规则 `bug_fix_lesson` 匹配 "上次就是因为/经验教训…" → suggestion → confirmation → 写入

**存储后行为**：
- 存入 `episodic/YYYY-MM-DD.md`（按日期组织，天然携带时间锚点）
- 下次对话通过 MemorySnapshot 注入
- 用户可参考过去的事件经验

**当前局限**：
- 只有一种触发规则（bug_fix_lesson）
- 不记录 troubleshooting episode、refactor_experience、decision_outcome
- 不会自动从 session 对话中提取事件
- 当前 L1 提取的 episodic 缺少完整的事件叙事结构（只有教训，缺少上下文）

### 2.3 Procedural（程序记忆）

> **术语注意**：RFC 中的 "Procedural Memory" 不完全等同于经典认知心理学中的 *implicit procedural memory*（内隐程序性记忆——技能自动化，如骑自行车）。RFC 中的 procedural memory 指的是从真实交互中浮现的、经过显式确认的行为约束——有意识、可言述、通过交互学习获得。详见 MEMORY_CANONICAL_RFC.md §2.3。

**当前实际触发方式**：
- L1 规则 `project_rule` 匹配 "这个项目规定/禁止/必须…" → suggestion → confirmation → 写入

**存储后行为**：
- 存入 `procedural/learned.md`
- 下次对话通过 MemorySnapshot 注入
- T1 confirmation 强制（宪法级锁定）

**风险注意**：
- L1 关键词匹配可能将 coding_rule 误标为 procedural memory
- 要观察是否出现 "coding rule 被当成 behavioral constraint" 的情况
- 参见 MEMORY_CANONICAL_RFC.md §2.4 的法定判定标准

---

## 3. 如何触发 Retain

### 3.1 显式触发（最可靠路径）

在对话中输入以下模式之一：
```
记住我喜欢 pytest
remember that I prefer concise answers
记住这个项目用 PostgreSQL
```

系统会弹出 confirmation：选择 1-5 对应不同处理方式。

### 3.2 L1 启发式触发（概率性）

在对话中包含以下模式之一，系统可能自动建议 retain：

| 规则 | 关键词 | memory_type | 示例 |
|------|--------|:--:|------|
| project_rule | 这个项目规定/禁止/必须 | procedural | "这个项目禁止使用 any type" |
| bug_fix_lesson | 上次就是因为/经验教训 | episodic | "上次就是因为没加索引，迁移超时了" |
| architecture_decision | 我们选了/决定用 | semantic | "我们选了 FastAPI 而不是 Flask" |
| repeated_preference | 我喜欢/习惯… (≥3次) | semantic | 第 3 次说 "我喜欢用 pytest" |

### 3.3 不会触发的情况

- 不含关键词的隐式偏好（"以后 SQL 少写嵌套子查询" — 不含 marker）
- 单次表达的偏好（repeated_preference 需要 ≥3 次）
- 含 secret/password/token 的内容
- 含 prompt injection pattern 的内容
- 本 session 已建议 ≥3 次

---

## 4. Confirmation 流程

### 4.1 确认选项

当系统建议 retain 时，会展示：
```
我可以长期记住这条信息吗？
[内容预览]
来源: [来源标识]
原因: [原因说明]

1. 记住          — 确认保留
2. 编辑后记住     — 修改内容后保留
3. 仅本次使用     — 当前 session 可用，不长期保留
4. 不要记住       — 拒绝
5. Other/free-text — 自由文本说明意图
```

### 4.2 选择后果

| 选择 | store 写入 | 下次 session 可见 |
|------|:--:|:--:|
| ACCEPT | 是 | 是 |
| EDIT_AND_ACCEPT | 是（编辑后内容） | 是 |
| SESSION_ONLY | 是（session scope） | 否 |
| REJECT | 否 | — |
| OTHER | 否（等待澄清） | — |

---

## 5. Recall / Snapshot

### 5.1 自动 Snapshot

每次对话启动时，`MemoryRuntime.snapshot_for_prompt()` 自动：
1. 从 filesystem store 读取所有 memory
2. 按 scope 过滤
3. 排除 sensitive
4. 最多取 5 条
5. 总计 ≤500 字符
6. 注入 system prompt

用户不需要做任何操作。

### 5.2 手动查看 Memory

```bash
# 查看所有 memory 的 index
cat ~/.my-first-agent/memory/index.json | python -m json.tool

# 查看所有 markdown 文件
ls -la ~/.my-first-agent/memory/semantic/
ls -la ~/.my-first-agent/memory/episodic/
ls -la ~/.my-first-agent/memory/procedural/

# 查看具体内容
cat ~/.my-first-agent/memory/semantic/user_preferences.md
```

### 5.3 验证 Snapshot 的当前内容

在对话中问 Agent："你当前记住了什么？" — Agent 可以列出 MemorySnapshot 中的内容（如果有接入）。

---

## 6. 查看 Filesystem Memory

### 6.1 目录结构

```
~/.my-first-agent/memory/
├── index.json              # 派生索引，可重建
├── semantic/
│   ├── user_preferences.md
│   ├── user_facts.md
│   ├── project_rules.md
│   └── project_decisions.md
├── episodic/
│   └── 2026-05-11.md       # 按日期组织
├── procedural/
│   └── learned.md
└── _pending_confirmation/   # 跨 session pending（Phase 5）
```

### 6.2 Markdown 文件格式

```markdown
---
id: memory:fake:abc123def456
memory_type: semantic
scope: user
source_type: agent_suggested
approval_status: approved
created_at: 2026-05-11T10:30:00Z
updated_at: 2026-05-11T10:30:00Z
source_summary: candidate:arch_decision_abc
safety_summary: 无额外安全标记
audit_id: audit:fake:789xyz
sensitive_redacted: false
created_by_operation: retain_intent
updated_by_operation: retain_intent
stability: stable
confidence: 0.75
---

用户偏好 pytest 而不是 unittest 进行测试
```

### 6.3 重建索引

```bash
# 索引会被自动重建，也可以手动触发（在 Python 中）：
python -c "
from agent.memory_fs_store import FilesystemMemoryStore
store = FilesystemMemoryStore()
# 构造函数自动 rebuild index
print(f'加载了 {len(store._index)} 条记录')
"
```

---

## 7. 手工编辑 Markdown Memory

### 7.1 编辑内容

直接编辑 `.md` 文件中的 body（YAML frontmatter 之后的内容）：

```bash
vim ~/.my-first-agent/memory/semantic/user_preferences.md
# 修改 body 内容，保留 frontmatter
```

### 7.2 删除某条记录

找到对应文件，删除整个 `---` section（包括 frontmatter 和 body）。

### 7.3 修改 memory_type

编辑 frontmatter 中的 `memory_type` 字段，然后重建索引。

### 7.4 注意事项

- 手工编辑后建议删除 `index.json`，下次启动自动重建
- frontmatter YAML 是 stdlib-only parser，不兼容复杂 YAML 语法（anchors、tags 等）
- 不要修改 `id` 和 `audit_id` 字段（影响去重和审计链）

---

## 8. 观察 Memory Pollution

### 8.1 Pollution 信号

| 信号 | 观察方式 |
|------|---------|
| 无关内容进入 memory | 检查 filesystem store 中的 body 内容是否真的值得长期保留 |
| 过多 semantic 记录 | `ls -la ~/.my-first-agent/memory/semantic/` 数文件数量 |
| Snapshot 质量下降 | 检查 system prompt 中的 memory section 是否包含无关内容 |
| 重复记录 | 搜索 index.json 中相似 content |
| 错误事实 | 检查 memory 中是否有与实际情况不符的内容 |

### 8.2 记录方式

发现 pollution 时记录：
- 什么内容被错误地 retained
- 是通过什么路径 retain 的（显式指令 / L1 哪个规则）
- 为什么你认为这是 pollution

---

## 9. 观察 Procedural Over-Retention

### 9.1 什么是 Procedural Over-Retention

L1 `project_rule` 规则将 "这个项目规定/禁止/必须..." 标记为 `procedural`。
但 MEMORY_CANONICAL_RFC.md §2.4 规定：procedural memory 必须是**从真实交互中涌现**的行为约束，
不是预定义的 coding rule。注意 RFC 中的 procedural 不等于经典认知心理学的 implicit procedural memory（技能自动化）。

**过度 retention 示例**：
- 用户："这个项目禁止使用 any type" → L1 标记为 procedural
- 实际上：这可能是 coding_rule / skill / config，不应该进入 procedural memory

### 9.2 观察方式

```bash
# 查看所有 procedural memory
cat ~/.my-first-agent/memory/procedural/learned.md

# 检查每条是否符合 procedural 判定标准：
# 1. 是否来自真实交互/纠正？
# 2. 是否经过 explicit confirmation？
# 3. 是否可以事先写好？（如果可以，不是 procedural memory）
```

### 9.3 记录方式

发现 over-retention 时记录：
- 什么内容被标记为 procedural
- 是否符合 5 条法定判定标准
- 如果不符合，它应该属于什么（skill / config / semantic）

---

## 10. 观察 Session Friction

### 10.1 Friction 信号

| 信号 | 含义 |
|------|------|
| Confirmation 弹出太频繁 | 频率限制 (≤3/session) 可能不够 |
| Confirmation 打断了工作流 | 触发时机不当（task 中途弹出） |
| 用户多次 REJECT | L1 规则产生了低质量建议 |
| 用户选择 SESSION_ONLY | 内容可能有价值但用户不信任长期 retain |
| 用户选择 EDIT | preview 内容不准确 |

### 10.2 观察方式

在每次 confirmation 弹出时注意：
- 此刻你正在做什么？（task 中途 / task 边界 / 闲聊）
- 建议内容是否相关？
- 你是否愿意停下来处理这个 confirmation？

---

## 11. Dogfooding 反馈记录格式

### 11.1 每条反馈记录

```markdown
### [日期] [类型] 简短标题

**触发路径**: explicit_retain / L1_project_rule / L1_bug_fix_lesson / L1_architecture_decision / L1_repeated_preference
**memory_type**: semantic / episodic / procedural
**内容摘要**: [一句话描述 retain 的内容]
**观察**:
- 这条 memory 是否有价值？
- 是否在合适的时机触发？
- Snapshot 中看到它时是否有用？
**问题**: [如有]
**建议**: [如有]
```

### 11.2 反馈归档位置

建议将 feedback 记录在 `docs/review/DOGFOODING_RUN_YYYY-MM-DD.md` 中，作为 dogfooding session 的 review 文档。

---

## 12. 当前 Dogfooding 环境变量

```bash
# 启用 filesystem memory store
export MEMORY_STORE_BACKEND=filesystem

# 设置 memory 存储目录
export MEMORY_ROOT=~/.my-first-agent/memory

# 查看配置
python -c "
from agent.memory_runtime import create_memory_runtime
from agent.memory_fs_store import FilesystemMemoryStore
rt = create_memory_runtime()
print(f'Store type: {type(rt._store).__name__}')
print(f'Store root: {getattr(rt._store, \"root_dir\", \"N/A\")}')
print(f'Records: {len(rt._store.list_records())}')
"
```
