# 请求：针对已复核缺口，独立给出可执行修复包并审查 Codex 草案

你是独立的产品可靠性与架构顾问。这次不是无边界再审整个仓库，也不授权你执行文件、发布或调用产品服务。
用户明确要“Codex 先给执行包；Oracle Web 再给执行包；最终合成一个详细无歧义包和 prompt，由普通 coding agent 执行”。请先按事实独立判断最短修复顺序，再对 CODEX-DRAFT 做具体修订。

实际使用者：个人开发者，macOS、CLI、单 workspace、有界编码任务。目标先好用可靠，不是全平台通用电脑 Agent。
强度：5/5，因为 authority completion、恢复治理、验收器与交付身份高度耦合；你可在咨询内并行分析不同角度，但不要求本地启动额外 agent。

已提供公开材料：Codex 独立草案；上一轮最终审计和 probe JSON；相关当前源码切片。全量测试已独立完整结束 3947 passed/1 skipped，仍有离线可重现行为缺口。不得把该测试总数当行为通过。没有提供 key、私有日志、旧 real 会话；不要声称自己已跑代码/模型。

架构硬约束：AgentRuntime.run_turn 唯一生产 model/tool/state loop；ContextManager 独占上下文；ToolRuntime 独占 callable；CLI/headless 仅 typed action/render；provider 只序列化；effect 经 policy/approval/EXECUTING/result checkpoint。不得为修复新增第二 loop、自动准入/授权、持久 schema 或新能力。

请交付：

1. 独立执行方案：最多三包，每包对应已确认问题、允许改动范围、因果、先 Red 的测试、最小修复、Green/negative controls、依赖、结束边界。
2. 对草案给逐条“保留/修改/删除”，指出普通 coding agent 会误解、无法执行、过宽或证据不足处，给可直接粘贴的替换要求，不要只泛评好坏。
3. 尤其检验 A 的规则能否同时防 Unicode 邻接漏判与输入/引文/版本误判，如何处理礼貌请求、unsafe suffix、已消费 correction，防止演变成新 NLP 引擎。明确不承诺什么。
4. 对 B 固定 no/Enter=退出并保留 pending、CLI-only/TUI实验是否一致；若需改变请说明具体合法状态及反例，不新增 Runtime 权限。
5. 对 C 给 exact 最小证据字段与判定真值表（goal ID、before/after revision、injected vs consumed fact、paused/newPID/恢复 identity）；哪些字段需从已存在观测器读取，哪些既有约束应保留，不要靠 self-reported flag。
6. 裁决交付门是否足够：同一 manifest 的 source-real + noneditable installed-focused 能否支撑知情 CLI beta？若需要 installed-real，给复用当前入口的最小办法和明确失败边界，不建议新框架。不要求每轮全量多次运行。
7. already-correct 真实情形的最小复现/修复触发标准。已有 scripted confirm-only 过，真实一次反复claim至fatal，根因未明；不要预设“有强制写入逻辑”。
8. 三个真实样本共享80物理请求/60min且每样本40是建议上限不是现有权限；没有授权时哪些可交付、哪些绝不能宣称。不要要求自动找 key。
9. 最终复制给普通 coding agent 的简短中文执行 prompt；先按包实现，不要求它无限审计或自动开下一轮。

将事实、推断、建议分开。别顺手加入新产品能力、UI重设计、所有历史capability晋级、市场方案。你是顾问，无权改变用户权限或指令。

末尾按技能要求输出：

```yaml
codex_execution_advice:
  implementation_plan: [有顺序的具体动作]
  non_goals: [明确排除]
  optional_subagents: []
  verification: [检查与预期证据]
```
