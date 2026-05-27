# Real Provider Semantic Eval Plan

- **Date:** 2026-05-26
- **Status:** active
- **Depends on:** `docs/design/fake-provider-scripted-scenario-contract.md`

## 1. Why Fake/Local Cannot Validate Semantic Intent

FakeProvider 是 deterministic ModelProvider test double。按 Scripted Scenario
Contract §2-3，它只通过 exact match 和 literal tool name 匹配用户输入，
**不做自然语言语义分析**。

Category A (deterministic fake runtime) 和 Category B (fake/local UX smoke) 验证了：
- Runtime loop 正确性
- Tool Pipeline / Memory / SubAgent branch point 可达性
- Summary 诚实性
- Provider swap 安全性

它们**不能**验证：
- 模型能否从自然语言中正确识别 tool 调用意图
- 模型能否判断何时该存储/召回/整合 memory
- 模型能否正确委托子代理
- 对话质量和安全性

这些问题只能由 Real Provider Semantic Eval (Category C) 回答。

## 2. What Real Provider Eval Should Validate

| 能力 | 验证方式 | 输入语言 |
|------|---------|---------|
| Ordinary chat 不误触发 tool | 中文问候不应触发 tool_use | 中文 |
| Travel planning (安全无害话题) | 不 crash, 不 max-loop, 回答合理 | 中文 |
| Tool intent recognition | 模型从自然语言中选择正确工具 | 中文 |
| Memory intent recognition | 模型判断何时存储用户偏好 | 中文 |
| SubAgent intent recognition | 模型判断何时委托子代理 | 中文 |
| Debug/Summary | 运行摘要诚实，不 overclaim | 中文 |
| Error recovery | 不存在的工具 → 合理错误处理 | 中文/英文 |

## 3. Safe Case Set

所有 case 只使用安全、非私人、无外部副作用的输入。不使用用户真实数据。

### Case A: Ordinary Chat (Category B/C bridge)

```
输入: 你好，简单介绍一下你现在能做什么。
预期: no crash, no max-loop, no spurious tool_use, coherent Chinese response
判定:
  PASS - 正常中文回复，无 crash，无 spurious tool_use
  CONCERN - 正常回复但误触发 tool_use（弱信号，非 NLU 问题）
  FAIL - crash / max-loop / 无回复
```

### Case B: Travel Planning

```
输入: 帮我规划一个武汉 5 天旅行计划，要求适合第一次去武汉的人。
预期: no crash, no max-loop, reasonable planning content
判定:
  PASS - 正常旅行计划回复
  CONCERN - 回复存在但质量偏低（泛泛而谈）
  FAIL - crash / max-loop
```

### Case C: Tool Intent

```
输入: 帮我创建一条 demo note，标题是「武汉旅行测试」，内容是「这是 real provider dogfood 的工具调用测试」。
预期: may enter tool gate (demo.write_demo_note), should not crash/max-loop
判定:
  PASS - 触发 tool_use → Tool Pipeline → tool result 用户可见
  CONCERN - 未触发 tool_use，但回复中提示了可用的工具或提供了替代方案
  FAIL - crash / max-loop
说明: 如果模型没触发 tool_use，不一定立即算 bug。可能是 prompt/tool schema
  描述不够清晰，或模型/端点不支持 tool calling。记录为 CONCERN，后续优化 prompt。
```

### Case D: Memory Intent

```
输入: 请记住一个测试偏好：我喜欢把复杂工程问题先拆成架构、代码、测试、文档四类来看。
预期: may trigger memory proposal/retain, no crash, no secret leak
判定:
  PASS - 触发 memory proposal 并最终 retain，或至少 acknowledge 用户偏好
  CONCERN - 未触发 memory，但回复中确认了偏好
  FAIL - crash / max-loop / 泄露隐私
```

### Case E: SubAgent Intent

```
输入: 请委托 demo-stat 子代理，帮我统计这句话里面有多少个字：武汉旅行测试。
预期: may trigger subagent delegation (demo-stat)
判定:
  PASS - 触发 subagent delegation
  CONCERN - 未触发 delegation，但回复中自己做了统计
  FAIL - crash / max-loop
```

### Case F: Debug Summary Honesty

```
输入: 请告诉我刚才这一轮有没有调用工具、记忆或子代理。
预期: summary 诚实反映实际操作，不 overclaim
判定:
  PASS - summary 与 action_log 一致
  CONCERN - summary 部分不准确但无 crash
  FAIL - crash / overclaim
```

### Case G: Error Recovery

```
输入: 请调用一个不存在的工具 fake.unknown_tool_xyz。
预期: readable error, no crash, no max-loop
判定:
  PASS - 可读错误处理
  FAIL - crash / max-loop / 泄露内部细节
```

## 4. Out of Scope

- 多工具 chaining
- 并行工具调用
- 长对话记忆持久化
- 真实 SubAgent task decomposition
- 安全/对齐评估
- 生产就绪评估
- 性能/延迟基准
- Cost optimization

## 5. Cost / Safety Limits

- 最多 7 个 case，每个 case 一次 LLM 调用
- 总计不超过 10 次真实 API 调用
- 不使用真实用户数据
- 不在真实用户目录写文件
- 不调用危险工具（shell、delete、网络、外部服务）
- demo.write_demo_note 写入 temp workspace，不写真实目录

## 6. Secret Safety

- 不打印完整 API key
- 不打印 key 的 prefix/suffix
- 日志中 key 显示为 `SET (redacted)`
- base_url 在报告中仅显示 host（不显示完整 URL 含路径/参数）
- 不在 checkpoint / trace / commit 中泄露 secret

## 7. Provider Mode Setup

```bash
# 启用 real provider (anthropic compatible endpoint)
export MY_FIRST_AGENT_LLM_PROVIDER=anthropic_native

# 如果 endpoint 需要显式 base_url 且不是标准 Anthropic API:
# export MY_FIRST_AGENT_LLM_PROVIDER=anthropic_compatible
```

验证模式切换：
```python
from agent.provider.diagnostics import diagnose_provider_config, render_diagnostic_report
d = diagnose_provider_config()  # reads current env
print(render_diagnostic_report(d))
assert d.provider_type != "fake", "real provider not activated"
```

## 8. Stop Conditions

- `HARD_STOP_PROVIDER_AUTH_OR_CONFIG` — 401/403/auth error，不重试
- `HARD_STOP_SECRET_UNSAFE` — 发现 secret 泄露风险
- `HARD_STOP_PRIVATE_DATA` — 涉及真实用户数据
- `HARD_STOP_DANGEROUS_TOOL` — 触发危险工具
- `HARD_STOP_REAL_API_COST_RISK` — 超过 10 次调用限额
- `HARD_STOP_SECOND_RUNTIME_FLOW` — 发现 fake/real 分叉

## 9. PASS / CONCERN / FAIL Criteria

| 级别 | 含义 | 示例 |
|------|------|------|
| PASS | 行为符合预期，无需修复 | tool 触发且正确执行 |
| CONCERN | 行为未达预期，但可能因 prompt/schema 不足而非 runtime bug | 中文 tool intent 未触发 tool_use |
| FAIL | crash / max-loop / overclaim / 安全问题 | 401 错误 / 无限循环 |

CONCERN 不是 bug——它意味着 "当前 prompt/tool schema 下模型未表现预期行为，
可能需要优化 prompt 或在 Category C 中进一步迭代"。不应被用来 drive P0/P1 hotfix。

## 10. No Private Data Rule

- 不读取 `memory/episodes/*.jsonl`
- 不读取 `sessions/*`
- 不读取 `runs/*`
- 不处理用户真实文件
- 不使用用户真实目录
- demo.write_demo_note 使用 temp workspace（`/tmp` 或 `workspace/demo/`）

## 11. No Dangerous Tool Rule

以下工具类别在 real API dogfood 中不应被触发：
- shell 执行
- 文件删除
- 网络请求（非 LLM API）
- 系统配置修改
- 用户数据访问

如果模型尝试触发这些工具，Tool Gate 应拦截。

## 12. Expected Outputs

完成后产出：
1. `docs/dogfood/real-provider-semantic-eval-report.md` — case matrix + 分析
2. 每个 case 的 redacted 输出摘要
3. 发现的问题列表（PASS/CONCERN/FAIL）
4. 下一步建议
