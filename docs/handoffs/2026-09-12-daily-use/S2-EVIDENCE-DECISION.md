# S2 结果证据与产物确认决策

日期：2026-09-13。范围：S2；不改变 `AgentRuntime.run_turn` 的唯一 loop 所有权。

## 现有 closed oracle 实际证明什么

| Oracle | 绑定 | 能证明 | 不能证明 |
|---|---|---|---|
| `FILESYSTEM_DIGEST` | 当前 Goal/revision、workspace-relative path、用户批准或 Runtime 展示确认的 SHA-256、同 Goal 的受治理 read-back | 指定路径的当前字节与已绑定字节完全一致 | 报告数字、推理、结论或业务语义正确 |
| `process_v1` | 当前 Goal/revision、workspace identity、lease、tool identity、command fingerprint、argv/cwd/environment policy、outcome/exit code | 精确获批的本地进程按回执退出；要求为成功时 exit code 为 0 | 程序本身正确、输出语义正确、任意其他命令或产物正确 |
| `native_sandbox_v1` | 当前 Goal/revision、sandbox lease、workspace/snapshot/environment/command identity、结构化回读与 outcome | 精确获批的隔离命令产生匹配的成功回执 | 测试设计充分、业务结论正确、未绑定文件正确 |
| `RESEARCH_PROVENANCE` | 当前 artifact/manifest 字节、当前 Goal、来源 receipt、最少来源与 freshness 条件 | 产物引用与受治理来源记录存在精确联系 | 来源陈述必然为真，或模型综合判断无误 |
| `BROWSER_READBACK` | 当前 Goal、批准的 browser action receipt、同 session 的新鲜 observe | 动作及后续页面观察匹配绑定 | 页面背后的业务最终状态在所有系统中成立 |

内部状态名 `VERIFIED_DONE` 表示“所有 mandatory closed-oracle 条件已闭合”，不是通用真值证明。用户界面必须显示具体 evidence scope，不能把 file digest 或 `exit 0` 表述为数值/语义已经独立核验。

## 文件的三个时点

1. 普通 `write_file/edit_file`：prepare 阶段固定目标前置条件、新内容摘要和可读的新内容预览；用户批准的是这一个 exact proposal。invoke 前再次 prepare，任何漂移都拒绝。
2. 程序未来生成文件：批准进程时文件字节尚不可知。批准只铸造 process lease/receipt obligation，`FILESYSTEM_DIGEST` 保持 pending，不能让用户猜未来 SHA，也不能由模型自报摘要。
3. 已存在或刚生成的产物：`confirm_file` 经同一 `ToolRuntime` 读取受限 UTF-8 文件，把当前完整内容放入审批预览并绑定当前 snapshot/digest；用户确认后才准入文件 criterion。invoke 前再读一次，漂移即 fail closed。

`/approve-artifact` 保留为高级兼容入口，但正常 CLI/TUI 流程不依赖用户手抄 SHA。

## 数值正确性的边界

本次不新增“通用语义评分器”或第二套验证 loop。数值任务只有在用户或任务合同绑定了一个具体 validator，并且该 validator 的精确进程回执与最终产物字节都闭合时，才可以陈述“该检查已运行且通过”。即使如此，产品仍只声明 validator 的实际检查范围；独立 QA 负责判断 validator 是否覆盖了 count/errors/P95 等业务规则。

历史 U2B 的 local-process requirement 来自 fixture 的显式 Goal/criterion。它不能单独证明所有生产任务都天然需要进程。本次未把普通写作任务强制升级为 process 任务。

## 选择与未选择

- 选择：复用现有 file capability、`ApprovalRequest`、CAS、`EXECUTING` checkpoint、source receipt 和 closed evidence registry。
- 选择：新增一个窄的 `confirm_file` governed tool；它是现有文件工具族成员，不拥有 model loop 或状态变更权。
- 选择：完成时投影可信的 evidence scope，并明确“不独立证明数值或语义正确”。
- 未选择：自动接受进程产物摘要、模型自证、CLI 绕过 `ToolRuntime` 直接读文件、通用 LLM judge、第二套 runtime 或后台验证器。

