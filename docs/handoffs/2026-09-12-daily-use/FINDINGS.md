# 问题清单与证据强度

## 审计边界

Oracle session：`first-agent-daily-use-audit-20260912-7f3c`。已验证第 5 档、`promptSubmitted=true`、答案捕获和 session 专属 Chrome/Profile 清理。Oracle 收到 20 个文件摘录，未拿到完整 runtime/provider/host/test 实现，也未执行真实模型任务或全量测试。

Oracle 原文中的 `3398 passed, 3 skipped` 来自此前调度复核报告。随后 Codex 运行 `tests/cli/test_render.py`、`tests/automation_hosts/test_wake_management.py`、`tests/subagent/test_tools.py`：`17 passed`。这些既有测试通过，不能证明新发现的问题不存在。

源码位置为打包时定位线索，函数名与行为优先于行号。以下 F1–F7 沿用 Oracle 编号；B1–B5 是对其后置建议的交接编号。

## 必须处理的前台主线

| ID | 优先级 / 切片 | 已知事实 | 证据及源码入口 |
|---|---|---|---|
| F1 | P0，S2 | CSV 报告 12 组 errors 有 3 组错误，仍 `COMPLETED / VERIFIED_DONE` | 9 月 10 日历史真实任务；本轮未重跑。`docs/audits/2026-09-10-product-baseline-tasks.md:24`；`agent/runtime/evidence.py::ClosedEvidenceRegistry`、`agent/runtime/loop.py`、`agent/runtime/state.py` 为待追踪消费链 |
| F3 | P1，S1 | CLI delta 原样输出，最终文本却转义 | Codex 直接调用生产 renderer 复现 ESC 原样抵达 sink。`agent/cli/render.py:44`、`main.py:1091` |
| F4 | P1，S1 | CLI 流式缓存跨轮积累，第二轮重复输出；默认忽略进度事件 | Codex 对同一 renderer 连续两轮得到 `["first", "second", "second"]`。`TerminalRenderer.emit/render_result/_result_message`、`agent/cli/app.py::run_repl` |
| F5 | P1，S2 | 特殊 artifact 审批要求手抄摘要 | 源码确认。`agent/cli/app.py::_parse_action`、`agent/cli/actions.py::parse_artifact_confirmation`、`agent/cli/render.py::_approval_message`；新文件“未来摘要死路”需要专门复现，旧基线并未实际触发 |
| F6 | P1，S1 | 当前安装制品＋自有配置＋真实模型多步任务证据不足 | 历史 Anthropic-compatible 多步任务存在；9 月 12 日 GLM 路线只有一次无工具 smoke。两者不能互相代证。`agent/provider/profile.py`、`main.py`、`tests/cli/test_016_packaging.py` |

F3 证明的是显示边界缺陷，未证明任意真实 Provider 能发动终端攻击或工具越权。F4 当前直接复现的是 CLI，不应未经验证就宣布 TUI 同样出错。

F1 的“P0”表示阻断“数值已核验”的产品承诺，不是所有工作区任务完全不可用。不要为了消除标签而删除所有完成门禁，也不要承诺证明任意自然语言结论。

## 仅在交付调度时必须处理

| ID | 优先级 / 切片 | 事实与影响 | 入口 |
|---|---|---|---|
| F2 | 调度 P0，S3 | `first-agent-schedule` 指向固定 `core=None` 的 main；补配置也不会自然接通。macOS main 同样是 unavailable 占位 | `pyproject.toml:39`、`agent/automation/cli.py::main`、`agent/automation_hosts/macos_cli.py::main` |
| F7 | P1，S3 | 管理要求 definition JSON、CAS token、digest；open 仅输出 handoff；除两个 code 外 CLI 全返回 0，失败或未知也会被脚本当成功 | `agent/automation/cli.py::build_parser/run_cli/_dispatch`、`agent/automation/management.py`、`tests/automation/test_open_handoff.py` |

需要保留的已有改动：manual create/preview/approve 不依赖 wake；批准 cold-wake 任务不隐式安装系统项；普通 preflight 只读。它们已有实现和测试，见 evidence/scheduling-review.md，不能在接线时退回旧语义。

## 后置清单：不要顺手一起改

| ID | 问题 | 证据强度与最小下一步 |
|---|---|---|
| B1 | SubAgent 静默截到 2,000 字符 | 源码确认 `agent/subagent/tools.py:102`；Oracle 做了桩探针。未来用已有 bounded result 机制标明不完整，不能悄悄补发 child 请求。先检查 `agent/runtime/tools.py::_render_model_visible_output`，避免重复机制 |
| B2 | Memory update/forget 的前置元数据可能拿不到 | `memory_get` 返回正文、search 返回 ID＋正文、写入回执只有摘要前 8 位，而 update/forget 要完整 digest 和 revision。完整模型可见上下文需复核；用正常工具链而非测试预填内部值复现，再决定最小 get 输出修改 |
| B3 | 缺模型凭据时可能无法查看已有恢复信息 | `main.py:961` 在 session 打开前检查凭据。未来复用现有只读投影，使查看不触发模型/effect；禁止 FakeProvider 兜底 |
| B4 | 当前能力文档混有历史限制 | 只修确认过的当前说明与证据日期，保留历史 receipt，不重写历史；不要仅依据旧文字删除新实现 |
| B5 | 长任务累计成本缺少实证 | Oracle 指出累计上限/耗时证据不足；不是已证明资源泄漏。本轮真实任务记录调用数和耗时即可，不新建计费平台或调度器 |

## 已纠偏的判断

- “调度只是缺配置”不充分：安装装配确实缺失；`--help` 可用不是任务能用。
- “Sandbox 成功等于命令目标完成”不成立：必须追踪目标与回执的绑定；U2B fixture 提交 BlockedClaim 不能直接推出生产缺陷。
- “新文件审批已经普遍复现死路”证据不足：需要 S2 Named Red 验证其真实输入/产物语义。
- “Graphify 证明调用链完整”不成立：现有图主要给出历史文档关系，细节以当前源码为准。
- “工程做重等于运行耗资源”不成立：没有 CPU/内存/耗电基准。
- “借用 Pi 配置可重复验收”不成立：历史临时授权不构成本次读取其他产品凭据的授权。

## 范围取舍

保留内核所有权和安全合同；补齐安装后的真实任务与结果核对；把 SHA、CAS 等内部复杂度从普通操作中收回。暂缓新 Provider 家族、OpenAI SSE 重做、个人浏览器接管、向量 Memory、并发 swarm、Skill registry、第三方 MCP 扩展、跨平台 host、Redis/微服务及新的常驻调度器。
