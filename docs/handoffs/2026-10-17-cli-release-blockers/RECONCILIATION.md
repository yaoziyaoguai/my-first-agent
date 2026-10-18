# 合并裁决与本包准备证据（2026-10-18）

这是冻结的决策说明，不是第二份当前进度。进度只更新旧唯一 RESULTS。

## 1. 两份方案、一个执行合同

- [Codex 独立草案](oracle-input/CODEX-DRAFT.md)：在本次 Oracle 提交前写成，保留送审时字节。
- [Oracle Web 原答](ORACLE-ANSWER.md)：新会话、实际 Power 5/5，完整捕获；只做静态审查，不声称执行过代码。
- 最终权威入口为 [START-HERE](START-HERE.md)、[WORK-PACKAGES](WORK-PACKAGES.md)、[VALIDATION](VALIDATION.md)、[PROMPT](PROMPT.md)。当前用户/AGENTS/宿主权限始终优先。

双方同意：不重建内核、不加第四包。先修 A 完成判定、B 恢复确认，再做 C 严谨证据与安装候选。首发 CLI-only，TUI 保留实验性，不将其缺口写成已修复。

## 2. 采纳与限制

| 外审建议/分歧 | 最终裁决与核对 |
| --- | --- |
| A 不能只改 Unicode lookbehind | 采纳。保留 F1/F2 两个完整 Runtime Red，并固定完整 token/上下文正负矩阵；新增负控是验收要求，不宣称都是已复现事故 |
| 引文先于分句；日志跨分号需有范围 | 采纳有限范围：当前成对引文/围栏与表内“日志显示：”，到明确新请求结束；不发展任意 NLP 分类器 |
| 礼貌请求、SPEC 的输入/输出、版本号需正反对照 | 采纳。直接编辑与解释请求分开；保留有效数字目录，不用 basename 黑名单 |
| 引文/日志不能撤回 authority | 采纳。与不能新增同等保护；原消费/纠正/撤回/re-add 行为保留 |
| B 孤儿分支 active=None 应显式限定 | 源码 `app.py` 第二 OR 确实比 renderer/reducer 宽，采纳共享只读 predicate；这是不一致，不报告成已发生越权 |
| no/Enter 不是持久 DENIED | 采纳。退出当前 CLI，不调 Runtime、不造 receipt、不清 pending。ready 重开直接展示，不多发 ResumeGoal |
| paused yes/no 仅解释 | 采纳窄范围 `active=None、Goal paused、request有、receipt无`。Oracle 表述个别位置对 receipt 边界略混，定稿以精确谓词为准，不截获已有 receipt 的普通消息 |
| B 不能只检查 exit=0 | 采纳。第二次读取输入立即失败的测试，另检查 action/请求/效果/fact/receipt/版本/保存增量 |
| C 锁定新增 correction、同 Goal 和整个 checkpoint 链 | 采纳。以真实 raw observations 判定；增加 conversation/workspace 身份，防跨会话同名 ID 混用。仅扩验收 JSON，不改产品 schema |
| staged 恢复不要求 run ID 相同，也不能要求必写文件 | 采纳。保持同 Goal/来源/paused checkpoint，沿用原 advancement OR 条件；不套到 already-correct |
| source-real + installed-offline 不足以签当前安装版 beta | 采纳。原定三样本改在同一 wheel 上执行，不新增三次 API 样本；最小装配复用既有 import guard + JourneyOperator。接不通就阻塞，不能 fallback 后仍签通过 |
| helper 参数、七键在附件不完整，需现场核对 | 已由 Codex 读取 parser、运行两个 --help 并读取常量。VALIDATION 给的是已核实参数；安装目标两个参数明确标为本包待新增，非假称存在 |
| physical requests 不可由参数名推断 | 已读 `TransportAttemptLedger` 和 `openai_http.py`：发送前计 model 尝试并有累计上限。失败/重试算入；driver max-resumes 不控制计划 Resume，已明确而非当作安全保证 |
| 顾问 prompt 要执行者同时以终审覆盖草案 | 不采用其多文档优先关系。改为只执行合成后的四份合同，原答与草案作理由来源，防止两套当前计划 |

没有采纳无限增补同义词、无根因修改 no-op 路径、重晋级所有能力、重新制作 TUI 或增加真实 UNKNOWN 场景。

## 3. 事实与未证实的界限

F1/F2/F3/F4 的基线证据来自上一轮 Codex 独立 probe 与源码。F3 的 provider 请求增量为 0，不能说已经未授权外发；F4 是 evaluator 不能排除伪证据，不能倒推旧真实旅程必然消费错误。
already-correct 历史 real 曾反复 claim 到 fatal，但 scripted confirm-only 已可通；只在当前候选定位到合法证据被错拒或错误补证指引时实施局部修复，否则如实报告真实收尾未过。

本包构成待实施合同，不等于任一 bug 已修好。准备阶段没有产品 API、installed-real、产品代码/测试/driver 修改或 Git 发布。

## 4. 准备校验（非修复门）

- 技能完整重读：oracle-web 与执行建议；dev_co 的交接/证据/交付参考。按单一当前记录组织，而非重开产品立项。
- wrapper doctor 正常；五份显式公开附件，约 20.5k tokens；常见 key/private-key/Bearer 模式扫描 0 命中。未发送完整含私人配置提示的 RESULTS，未读 key/旧私有日志。
- 实际档位两次验证 5/5（附件后再验）；committed 新 conversation；完整答案捕获。UTC 完成时间 `2026-10-17T16:10:54.651Z`，北京时间 2026-10-18 00:10:54。
- 记录 Chrome PID 24441 已不存在、该次临时 Profile 已删除；没有复用旧 session、followup、手动发送或升级官方 CLI。细节见 [回执](ORACLE-RECEIPT.json)。
- 安装 runner / D04 journey 的 --help 均 exit 0，指令引用的相关测试文件已核对。最终文档链接/围栏/空白与秘密模式检查见 [包校验](PACKAGE-CHECK.json)。
- 原审计 IDENTITY 所列 13 份产品/测试/driver SHA 全保持一致；只新增本包与更新唯一 RESULTS 的当前摘要。未为文档准备再跑全库；上轮 3947/1skip 仅作明确标注的基线。

本包完成边界：方案定稿并交给用户。产品实施由下一次明确执行指令启动；真实 API 和发布仍按当次权限决定。
