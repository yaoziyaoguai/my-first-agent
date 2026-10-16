# 2026-10-14 接续审计结论

**结论：保留现有半成品继续做，不重开架构优化。R1/R3主体已经做了；R2部分实现但业务验收没有闭合；R4未做。** 本次是review、Oracle咨询、接续资料包与本地检查点整理，不是替下一执行者完成产品修复。

## 1. 审计对象与实际验证

- 基线：`main @ ff686bd14642e8ec5041cced6a21daf7c03f8d17`，与本地origin/main在审计开始时同步；没有新远程查询/写入。
- 接手：30个已跟踪文件修改，2931+/283-，另有原四文件执行包未跟踪。29个产品/测试/脚本完整身份固定在 [SOURCE-IDENTITY](oracle-input/SOURCE-IDENTITY.json)，第30个是既有RESULTS。
- 环境：macOS；Python 3.12.2、pytest 9.0.2、ruff 0.15.12。
- 已优先查询Graphify；旧图没有RequirementCoverage，未刷新索引，以当前源码/diff为准。

| 检查 | 独立结果 | 对应范围/限制 |
| --- | --- | --- |
| 8文件focused | 377 passed / 5.87s / exit 0 | R1、R3及部分R2/wire；不代表业务完整 |
| 完整source | 3839 passed, 1 skipped / 617.78s / exit 0 | 审计输入树，未修功能；新增缺失业务测试不在这3839项中 |
| skip定点确认 | 1 skipped / 0.06s / exit 0 | `test_launchd_real.py:30`，显式host gate未开；未安装登录项 |
| 初始ruff | 7 errors / exit 1 | 1缺失类型import、4未使用import、1等价bool写法、1import排序 |
| 仓库整理后的ruff/diff | 全通过 / exit 0 | 仅修上述6文件的导入/等价格式，不修下列行为缺口 |
| 整理后受影响回归 | 239 passed / 2.35s / exit 0 | privacy/research/tool_outcomes/compaction/provider continuity/verified_done六文件 |
| 独立纯内存探针 | 见[AUDIT-PROBES](AUDIT-PROBES.md) | 复现上下文原文缺失、旧healer弱检查、claim身份/解码问题 |
| 当前安装态/真实模型 | NOT_RUN / BLOCKED_AUTHORIZATION | 本轮未读取凭据、旧私人日志或调用产品真实API |

完整source命令：

```bash
PYTEST_ADDOPTS='' PYTHONDONTWRITEBYTECODE=1 PIP_NO_INDEX=1 .venv/bin/python -m pytest -q -rx --tb=short --color=no
```

完整门在导入/等价格式整理前执行；整理后只重跑受影响239项及ruff/diff，没有又跑一遍十分钟全库。身份变化仅上述机械清理，不能把此证据引用给未来功能补丁。

## 2. 上一位Agent做到哪里

| 项 | 已有成果 | 仍需做 |
| --- | --- | --- |
| R1 UNKNOWN | 连续保存失败保留intent；安全边界同CAS闭合suffix；跨进程恢复与零重放测试 | 严格核对旧拒绝prefix的联合字段/UNKNOWN矛盾；C2组合补证 |
| R3明确校验要求 | 冻结中文正负表、模型flag对照、禁止/撤回处理已有实现 | 保持实现；真实已admitted process→撤回→后续完成的跨层证明还需补齐 |
| R2完成可信度 | RequirementCoverage、部分wire/checkpoint/context同步、移除自动readback结束 | 需求原文可见性、测试助手不代填、字段身份/类型、D04两条真实Runtime反例与完整正例、blocked指引、真实样本 |
| R4 CLI入口 | 底层能力原来就存在 | 无参数范围授权、默认提示与snapshot精确绑定、帮助顺序及交互测试尚未改 |
| C1/C2 | C2已有纯未执行suffix到wire的测试 | C1同参重验后wire未证；C2成功prefix及实际continuation未证 |
| I1/G1/E1 | 本次source全量通过，lint现已清理 | 最终功能完成后的新wheel/installed/full身份；真实两样本待当前授权 |

## 3. 需要进入接续包的发现

### P1：R2复核输入和验收尚未可信

1. `context.py::_pin_groups`只固定最新用户消息等；`trusted_goal.source_fact_ids`不携带原文。探针在4000预算下原始用户原文消失但ID仍存在，6000预算下原文出现。durable compaction保护并不等于ContextPack可见。修复要有界，不永久固定无限历史。
2. `tests/kernel/fakes.py::bind_runtime_goal`给空coverage自动注入泛化satisfied声明。它不是产品绕权漏洞，但会隐藏本应失败的缺复核测试，须停止隐式代填。
3. 新的report文件测试不能代替D04业务验收：当前没有从原始双组件用户输入经真实admission、文件效果与独立grader验证的两条必要路径。不能预补CLI criterion，也不能仅凭coverage字段存在声称语义正确。

### P2：当前半成品的小范围收口

4. R1历史healer只核对`rejected is True`，矛盾`executed=True/is_error=False`或UNKNOWN也会补未执行suffix。探针是合成损坏状态。定点源码确认普通`_tool_result_fact`只写固定键并将metadata嵌套，不传播顶层rejected；审批拒绝分支生成的是严格False/True/True组合。因此**不升级成正常生产P1或远程漏洞**，保留为旧历史验证的必要防御补丁。
5. R2 claim receipt digest遗漏coverage；checkpoint吞显式false/null/0等；normalize嵌套未知字段被忽略；持久化ModelResponse的ID数组允许非字符串。均已本地复现。完成门仍有其他限制，不夸大为已绕过权限。
6. R4入口仍要求不可见ID；按原合同接线即可，不需要重新设计授权系统。

R3/C1/C2是验收缺口，不先假定为产品bug。`apply_goal_delta`现有代码已移除旧TOOL_RECEIPT admission并清证据/claim/相关leases，补真实链路证明即可；现有Web共享撤回变化不等于新Web能力或已放宽权限。

## 4. Oracle核验与采纳

- 新唯一会话：`mfa-resume-audit-20261014-64be7c`，2026-10-14 14:31–14:42（Asia/Shanghai）。
- 两次发送前ARIA确认：`Power, item 5 of 5 (slider ARIA)`；不是凭CLI请求模型名推断最高档。
- 新会话已提交并有完整答案：[原答复](ORACLE-ANSWER.md)、[身份/输入SHA/清理收据](ORACLE-RECEIPT.json)。
- 本次精确Chrome PID 1276已退出，临时Profile已不存在；未清理源Profile，未手动点击发送、复用会话或升级CLI。

| Oracle观点 | 本地处理 |
| --- | --- |
| R2应标IN_PROGRESS；保留R1/R3主体 | 采纳。旧表NOT_STARTED已不符合代码事实 |
| B1测试自动补coverage掩盖负例 | 采纳，接续包禁止隐式注入 |
| B2原文可见性待证 | 本地额外探针已证实ContextPack裁剪缺口；没有声称durable事实被删除 |
| B3字段身份/解码四处不一致 | 四项逐一核验/复现，按P2一起收口 |
| B4 healer严格标记缺口 | 采纳P2分级；核对普通生产结果映射，未发现正常顶层rejected传播 |
| B5 R3已准入撤回待证 | 已读实际过滤/失效源码；保留待补跨层回归，不预先新增修复 |
| B6 R4入口未完成 | 采纳原合同，不扩展权限 |
| C2成功prefix/continuation未证；旧自动收尾注释因果错误 | 核验后采纳，要求补真实断言并纠正注释 |
| G1尚未通过 | Oracle输入只含377通过与ruff失败。之后本地full 3839通过，机械清理后ruff通过；更新为当前源码门证据，非未来候选通过 |

Oracle建议不是执行授权。没有引入第二loop、语义裁判平台、通用迁移或新产品能力。

## 5. 保存与授权

用户在本次对话明确同意“本地检查点提交，不推送”。因此保存公开半成品和资料包；不reset/stash、不删用户文件、不改remote、不push/merge/tag/publish。

提交时使用现有`GRAPHIFY_SKIP_HOOK=1`仅跳过自动索引刷新，以免摄入ignored/private输入；原secret/ruff pre-commit检查保留。该开关不影响产品，也不是绕过测试门。

产品修复状态仍按上表；仓库clean只代表成果已保存，不代表R2/R4完成。下一执行者收到用户执行指令后按本包继续；产品真实API与Git远程操作仍需独立当前授权。

交接材料校验：4份主文档的17个本地链接有效；Oracle的6份输入与1份答案SHA全部匹配；10个包内文件的key-like/private-key模式检查零命中。原样归档的`ORACLE-ANSWER.md`、`oracle-input/SOURCE-CONTEXT.md`、`oracle-input/WORKING-TREE.patch`分别有24、95、95行行尾空白（含原答复Markdown换行与嵌套diff上下文）。保留这些字节以维持收据身份，未把原文格式化；因此不能声称包含三份原始证据的全部新增文档通过whitespace门。产品改动及手写交接文档的diff检查通过，后续修复只需对其实际新差异运行正常项目门。
