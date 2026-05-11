# Memory Constitution

**创建日期**: 2026-05-11
**性质**: Constitution — my-first-agent Memory 体系的宪章级原则
**状态**: Canonical — Constitution-level principles only
**上级文档**: 无（本文件是 Memory 体系的宪法根文档）

> **注意**: 本文档仅承载 Constitution-level principles（§1-§7）。
> 实现设计、governance 细节、extraction lifecycle、phase boundaries 的
> **唯一 canonical source** 是 `docs/rfc/MEMORY_CANONICAL_RFC.md`。
> 本文档与 canonical RFC 有冲突时，以 canonical RFC 为准。

---

## 0. 定位

**Memory 不是"存东西"。Memory 是 Agent 长期行为塑形与认知组织的治理层。**

---

## 1. Memory 是什么

### 1.1 正向定义

> **跨越单次会话的、被治理的、可解释的、人类可审查的 Agent 行为塑形信息。**

拆解：
- **跨越单次会话** — 不随进程退出而消失
- **被治理的** — 经过 policy → proposal → human adjudication 的完整链路
- **可解释的** — 每条 memory 必须能回答"为什么记住这个"
- **人类可审查的** — 用户可以看到、编辑、删除任何 memory
- **行为塑形** — 最终目标是改变 Agent 的长期行为，不是积累文本

### 1.2 Memory 不是什么

| 不是 | 为什么 | 属于什么 |
|------|--------|----------|
| **不是 retrieval system** | Memory 的目标是行为变化，不是"搜到相关内容" | Retrieval 是可选 backend |
| **不是 checkpoint** | Checkpoint 是 crash recovery，memory 是 cross-session continuity | State / Checkpoint |
| **不是 context** | Context 是当前 token window，memory 是跨会话持久信息 | Context Builder |
| **不是 task list** | Task 是当前执行单元，memory 是长期沉淀 | Task Runtime |
| **不是 RAG** | RAG 是 retrieval-augmented generation，memory 是 cognition | RAG 是可能的 recall backend |
| **不是 skill system** | Skill 是操作能力模板，memory 是从交互中沉淀的行为约束 | Skill System |

### 1.3 核心等式

```
Memory = Proposal + Governance + Storage + Consolidation + Forgetting

不是:
Memory = KV Store + Vector Search
```

---

## 2. 治理哲学

### 2.1 核心原则：Agent proposes, Human adjudicates

```
Agent 的权利边界：可以提出"我认为这值得记住"
Agent 永远不能：单方面决定"这已经被记住了"

用户的权利：接受、编辑、拒绝、仅本次使用、要求澄清
用户永远不需要：猜测 Agent 记住了什么
```

### 2.2 为什么 silent auto-write 是反模式

1. **Hallucinated memory**：Agent 可能"记住"从未发生的事
2. **Memory pollution**：不重要的信息挤掉重要信息
3. **Over-personalization**：过多偏好导致行为过度拟合
4. **Manipulation risk**：prompt injection 可诱导 Agent "记住"恶意内容
5. **信任侵蚀**：用户不知道 Agent 记住了什么 → 不敢自由对话

### 2.3 治理等级

| 等级 | 含义 | 示例 |
|------|------|------|
| **Explicit retain (用户主动)** | 用户明确说"记住 X" | "记住我喜欢 pytest" |
| **Agent proposal (agent 建议)** | Agent 提议给用户 | "我注意到你多次用 pytest，要记住吗？" |
| **Auto-write (自动写入)** | Agent 自己决定并写入 | **永远不做** |

---

## 3. 行为塑形哲学

### 3.1 Memory 如何改变行为

```
Memory Record
  → Snapshot Injection (prompt 可见)
  → Agent 在决策时参考
  → 用户反馈（纠正/确认/批评）
  → Memory 更新/强化/遗忘
  → Agent 行为持续调整
```

关键洞察：**单条 memory 不改变行为。Memory + feedback loop 才改变行为。**

### 3.2 Critique-driven adaptation

```
用户批评 Agent 行为
  → Agent 提取批评中的行为模式
  → proposal: "要形成长期行为约束吗？"
  → 用户确认
  → Agent 行为在未来改变
```

这是最纯粹的行为塑形路径：不是"记住用户喜欢什么"，而是"从错误中学习怎么做得更好"。

---

## 4. 数据主权

### 4.1 本地优先

1. **所有 memory 默认本地存储**。不上传、不同步、不依赖外部服务
2. **用户完全拥有数据**。文件在用户机器上，用户决定备份/删除/迁移
3. **离线可用**。不需要网络、不需要 API key

### 4.2 可解释性优先

Memory 存储形式必须满足：
- 人类可以直接打开阅读（不依赖专用工具）
- 人类可以直接编辑（不依赖 CLI/API）
- 版本控制系统可以 diff（纯文本）

Filesystem-native（Markdown + YAML frontmatter）是满足这些约束的 validated approach，但适用范围受以下项目约束限定：

- **local-first** — 单机存储，无外部依赖
- **single-user** — 无并发竞争
- **single-process** — 无分布式一致性需求
- **≤200 active memories** — consolidation 保持 active set 可控
- **governance-first** — 人类可读性优先于查询能力

这组约束使 filesystem-native 成为当前项目的合适选择。在其他约束下（multi-user、高并发、>1000 active records、需语义搜索），filesystem-native 的优势递减，传统数据库方案更合适。不应将 filesystem-native 泛化为 universally superior。

---

## 5. 人类权利

用户对 memory 拥有不可剥夺的权利：

| 权利 | 含义 | 当前状态 |
|------|------|----------|
| **知情权** | 知道 Agent 记住了什么 | list/inspect 未实现 |
| **编辑权** | 直接修改 memory 内容 | edit_and_accept 已支持 |
| **删除权** | 立即删除任何 memory | forget flow 已支持 |
| **解释权** | 知道 memory 如何影响行为 | 未实现 |
| **拒绝权** | 拒绝 Agent 的 memory proposal | confirmation flow 已支持 |

---

## 6. 设计原则

1. **Agent proposes, Human adjudicates** — 不可绕过
2. **Memory ≠ Retrieval** — Memory 是认知，retrieval 是工具
3. **Local-first, human-readable** — 用户拥有并可直接阅读数据
4. **Governance before storage** — Policy/Confirmation 链不可跳过
5. **Behavior shaping over data accumulation** — 少而精
6. **Forgetting is first-class** — 删除与写入同等重要
7. **Explainable provenance** — 每条 memory 回答"谁、何时、为什么"
8. **No silent auto-write** — 用户永远知道 Agent 记住了什么
9. **Sensitive content never enters memory** — 安全红线
10. **Memory must not swallow neighboring systems** — 不与 Skill/Checkpoint/Task 系统重叠

---

## 7. Groundedness

并非所有宪章原则都已有代码支撑。以下标注当前落地状态：

| 原则 | 状态 | 说明 |
|------|------|------|
| Agent proposes, Human adjudicates | ✅ implemented | explicit retain + heuristic suggestion + confirmation |
| Memory ≠ Retrieval | ✅ implemented | 当前不做 retrieval |
| Local-first, human-readable | 🟡 partial | in-memory only（生产代码未持久化；spike 已验证 filesystem-native 方案可行） |
| Governance before storage | ✅ implemented | Policy → Confirmation → Store |
| Behavior shaping | 🟡 partial | 当前 store 文本，尚未 consolidation |
| Forgetting is first-class | ✅ implemented | forget flow |
| Explainable provenance | 🟡 partial | candidate 有 provenance，但用户不可查询 |
| No silent auto-write | ✅ implemented | 所有路径需确认 |
| Sensitive content blocked | ✅ implemented | policy + suggestion engine 双重过滤 |
| Memory must not swallow neighbors | 🟡 partial | 本文档定义边界，尚未被代码强制 |

**图例**：✅ implemented = 代码中已存在 | 🟡 partial = 设计已明确，部分实现 | ❌ speculative = 纯设计，无代码

---

## 8. 文档关系

```
MEMORY_CONSTITUTION.md (本文件)
  ├── 宪章层：Memory 是什么、为什么、不可妥协的原则
  ├── 所有其他 memory 文档的上级原则文档
  └── 本文件应保持稳定，不随实现细节变化而变化

MEMORY_TAXONOMY.md
  └── 遵循本文件的分类哲学，定义 memory 类型及其边界

PROACTIVE_MEMORY_ARCHITECTURE.md
  └── 遵循本文件的治理原则，设计 agent proposal 分层架构

MEMORY_LIFECYCLE.md
  └── 遵循本文件的行为塑形哲学，定义 memory 完整生命周期
```
