# Memory Extraction Dogfood 001

日期: 2026-05-12
extractor: llm (deepseek-v4-pro)
sandbox: agent/memory_extraction.py

## 1. 使用的 extractor 类型

LLMMemoryExtractor (agent/memory_extraction.py)，底层 Anthropic SDK 兼容端点 (api.deepseek.com)。

## 2. Provider 加载状态

| 配置项 | 状态 |
|---|---|
| MODEL_NAME | loaded (deepseek-v4-pro) |
| API_KEY | loaded |
| BASE_URL | loaded (api.deepseek.com) |

provider selected: other (DeepSeek, Anthropic-compatible)

## 3. 5 组 transcript 结果摘要

### Case 1: Episodic — 数据库迁移 bug 排查经历

Transcript: 3 messages (user 问迁移事故 → assistant 详解根因 → user 确认 + 总结教训)

Proposals: 2

| # | type | content 摘要 | importance | confidence | action |
|---|---|---|---|---|---|
| 1 | episodic | 五一前 PG migration 超时：全表锁 + 无批次更新 → 分批 UPDATE + CONCURRENTLY 索引 | 8 | 0.95 | auto_retain_candidate |
| 2 | procedural | 以后大规模 migration 必须先检查锁策略 | 9 | 0.95 | propose |

评价: 分类合理。LLM 正确拆分为两个 proposal — 一个记录事故本身(episodic)，一个提炼行为规范(procedural)。时间锚点、因果链、根因分析都被捕获。

### Case 2: Semantic — 用户长期偏好

Transcript: 3 messages (语言偏好 → 确认 → 工作习惯)

Proposals: 2

| # | type | content 摘要 | importance | confidence | action |
|---|---|---|---|---|---|
| 1 | semantic | 偏好简体中文交流技术问题 | 8 | 0.95 | propose |
| 2 | semantic | 习惯先 code review 再 commit，审计 diff | 7 | 0.95 | propose |

评价: 分类准确。两条均为持久偏好/事实。

### Case 3: Procedural — 架构漂移约束

Transcript: 3 messages (批评方案 → 确认历史 → 明确约束)

Proposals: 2

| # | type | content 摘要 | importance | confidence | action |
|---|---|---|---|---|---|
| 1 | semantic | 高度重视项目简洁性，反对过度设计 | 9 | 0.95 | propose |
| 2 | procedural | 必须用最简单方案，不允许为想象需求加抽象 | 9 | 0.97 | propose |

评价: semantic/procedural 边界在此 case 略有模糊。LLM 将设计原则本身的声明归为 semantic（用户"相信"什么），将从中衍生的行为禁令归为 procedural（"必须"怎么做）。这个区分可接受，因为两者都标记了 requires_confirmation=True，不会绕过确认。

### Case 4: Negative — 临时任务

Transcript: 3 messages (明天开会提醒 → 确认 → 今天回复邮件)

Proposals: 0

评价: LLM 正确识别出临时性任务不应作为长期记忆提取。无 false positive。

### Case 5: Secret — 包含 API key / token

Transcript: 3 messages (含 sk-ant-api-... 和 tok-deadbeef-...)

Proposals: 0

评价: LLM 遵守了 system prompt 中"不要提取 API key/password/密码/token/secret"的指令。即使 LLM 漏过，safety regex 作为第二道防线也会过滤。无 secret 泄露。

## 4. 分类合理性

- episodic: LLM 正确识别了有时间锚点("五一前")和因果链的事件
- semantic: 正确识别了偏好、习惯、设计原则
- procedural: 正确识别了从交互中推导的行为约束
- semantic/procedural 边界在"设计原则 vs 行为禁令"场景下略有重叠，但由于两者都走 requires_confirmation=True，不会造成安全后果

## 5. importance / confidence 合理性

- importance 在 7-9 范围，事故经历和设计原则偏高(8-9)，个人偏好适中(7-8) — 合理
- confidence 整体偏高(0.95-0.97)，因为测试 transcript 信号非常明确。这与 FakeMemoryExtractor 的保守评分(0.65-0.85)不同，但并不表示 LLM 过度自信，而是真实 LLM 的置信度分布特征

## 6. False Positive

无。临时任务(case 4)正确返回 0 proposals。secret case(case 5)正确返回 0 proposals。

## 7. False Negative

无明显漏提。每个 case 的核心记忆信息都被捕获。

## 8. Secret 泄露

无。Case 5 的 API key 和 token 均未出现在任何 proposal 中。

## 9. 是否建议接入 confirmation

**建议接入，但分两步走**：

**先做 (推荐)**:
- extraction → human review 桥接：让 LLM extractor 的 proposal 可以通过一个简单的 terminal 交互由用户逐条 accept/edit/reject，确认后的内容手动写入 filesystem store
- 这一步不改变 confirmation 的契约模型，只是接上数据流

**后做 (等更成熟后)**:
- extraction → confirmation → operation intent 全自动链路
- session-end auto-extraction

**理由**: LLM 分类和置信度在高质量 transcript 上表现良好，但需要更多真实 dogfood 积累来验证边界 case（尤其是 procedural false positive 风险）。先接上人工确认链路，降低风险。

## 10. 是否建议继续只做 sandbox

**不建议无限期停在 sandbox**。当前 sandbox 已验证提取质量可接受。下一步应该：
1. 先 commit 本轮 debug fix (ThinkingBlock 兼容)
2. 保持 extraction sandbox 不写 store 的边界
3. 开始设计 extraction → human review → confirmed → store 的桥接路径

## 附录：bug fix 记录

本轮发现并修复: LLMMemoryExtractor.extract() 中 `response.content[0].text` 在 DeepSeek 返回 ThinkingBlock 时 AttributeError。修复为 `"".join(block.text for block in response.content if getattr(block, "text", None))`。
