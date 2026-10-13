# 接手执行记录

资料包：READY FOR IMPLEMENTATION。
产品修复：NOT STARTED BY THIS PACKAGE。
新候选真实验收：NOT RUN。

本包编制仅新增交接文档，没有修复产品、跑真实 API、注册登录项或 commit/push。
上游已有实现和历史记录保留；本页不能被理解为“整个项目从未做过”。

## 交接基线和历史证据

- HEAD：838cb2b66fbba674311d4d86fc7c4f4322fd8612；main ahead 7，大量既有 dirty/untracked。
- 最新依据：[2026-09-13 结果审计](../../audits/2026-09-13-autonomy-result-audit.md)。
- 历史全量：3597 passed / 3 skipped，392.98 秒；最新审计 focused 37 passed，0.38 秒。
  它们都未覆盖本包新反例修复，不能直接签发本包 PASS。
- 历史真实 v3：24 次请求及 K4 单独 5/8 窗口补证；不是当前 D/R 完成证据。
- 选定公开文件指纹见 BASELINE.sha256；不是完整 dirty 候选摘要，执行者应另建最终候选身份。

## 阶段状态

| 阶段 | 状态 | 实际改动、测试命令/退出码、证据 |
|---|---|---|
| E0 接手与准备 | NOT STARTED | — |
| E1 C1/C2/C3 | NOT STARTED | — |
| E2 S1/S3 | NOT STARTED | S3 为推断，先复现 |
| E3 S2/M1 | NOT STARTED | 真实协议 smoke 另计 |
| E4 C4 验收物化 | NOT STARTED | fixtures/driver/独立 grader 需落地 |
| E5 U1–U5/全量交付 | NOT STARTED | 不新增 scheduler host/跨平台能力 |

## 逐项必填记录

每个 C/S/M/U 及 F01–F24 填：当前结论、Red 节点/实际失败、最小改动路径、Green/回归、
对应 A/D/R、剩余风险。未复现的 S3 要记录反证与范围，不能虚报修复；范围外 U1 记录准确限制。
每个 A01–A24 填实际 node/命令、退出码、候选身份；不只引用历史计数或写“covered”。
新增问题 N01 起，先判断是否本合同必需；范围外只记录，不自动开新优化轮次。

## 真实验收登记

| 场景 | 状态 | run record / 候选 / 独立判定 / 三类救场 / 消耗 |
|---|---|---|
| 协议纯回答与完整工具回合 | NOT RUN | — |
| D01 | NOT RUN | — |
| D02 | NOT RUN | — |
| D03 | NOT RUN | — |
| D04 | NOT RUN | — |
| D05 | NOT RUN | — |
| D06 | NOT RUN | — |
| D07 | NOT RUN | — |
| D08 | NOT RUN | — |
| D09 | NOT RUN | — |
| D10 | NOT RUN | 正常完成与正确暂停分开 |
| D11 | NOT RUN | — |
| D12 | NOT RUN | — |
| R01 | NOT RUN | D01 同候选新环境复测 |
| R02 | NOT RUN | D02 同候选新环境复测 |
| R03 | NOT RUN | D04 同候选新环境复测 |
| 非评测专用的公开/授权项目 | NOT RUN | — |

真实窗口数值与授权摘要、driver/fixture/grader 实际路径和复制命令，由执行者落实后补在此处。
当前无新批准数值，不代表用户从未授权；按 REAL-API 核对缺项。

## 最终交付清单

- [ ] C1–C4/S1–S3/M1/U1–U5 各有处理结论；上游 F01–F24 无遗漏。
- [ ] A01–A24 全 PASS；D01–D12/R01–R03 达到原合同，公开/授权实际项目有结果。
- [ ] 产品自主推进/自测/收尾，三类业务救场为零；必要 consent 和独立评分另计。
- [ ] 完整源码 gate、non-editable wheel、实际安装来源、最终关键任务身份对应。
- [ ] 功能/配置矩阵含 strict、TUI、平台、依赖、in-flight 停止与 scheduler 限制。
- [ ] fresh review 无未解决的本范围阻断；dirty 保留，资源回收，无秘密入包。
- [ ] 首次失败、预算、耗时、unknown、skips、未测完整保留，不自动 promotion。

全部闭合才将产品状态改为 IMPLEMENTED AND ACCEPTED，否则报告准确部分状态及下一解除条件。

## 资料包编制检查（与产品验收分离）

2026-09-13 编制检查通过：

- 7 个文件，16 个本地 Markdown 引用全部存在；明确引用的源码/测试路径存在。
- FIX-PLAN 覆盖 13 个本包问题条目及上游 F01–F24；RESULTS 保留全部 15 个 D/R 待测行。
- `shasum -a 256 -c docs/handoffs/2026-09-13-autonomy-audit-remediation/BASELINE.sha256`
  返回 exit 0，32 个显式公开输入全部匹配。
- 工作树 `git diff --check` exit 0；另对本包未跟踪文本检查行尾空白、换行及代码围栏，均通过。
- 本包密钥形状扫描未发现 token；编制过程中未读取凭据。扫描不是绝对无秘密保证。
- 未重跑产品全量/付费任务：本次仅准备执行资料，产品源码未修改；产品验收仍为上方 NOT RUN。

这些仅证明交接完整性，不是产品测试。实现者应保留本段历史，在自己的执行记录另记新证据。

## 2026-09-13 当前执行记录

本节是对上方交接时状态的追加，不覆盖原始 NOT STARTED 记录。

| 阶段 | 当前结论 | 实际证据与剩余边界 |
|---|---|---|
| E1 C1/C2/C3 | PARTIAL PASS | 两个成功 process validator 可并存；后续受治理编辑、已执行失败 process、workspace-write/error sandbox 会使旧 process/file/sandbox 验证失效。`test_j1_verified_done.py` + `test_sandbox_verified_done.py` + `test_verified_done.py`：37 passed。尚未证明 same-uid 成功 validator 自身没有偷改 workspace；此限制不得改写为完整 input identity。 |
| E2 S1 | PASS | 直接 child 退出时 supervisor 回收同组后代，包含拒绝 TERM 的合成后代。`test_managed_web.py` 全部和 browser composition 合计 25 passed。 |
| E2 S3 | PARTIAL PASS | 正常 owner shutdown 确认 OS 资源消失后，在 owner-only state root 写最小 cleanup receipt；新 composition 可用旧 opaque ref 准确产生 stop receipt。异常断电/SIGKILL 后跨进程 cleanup receipt 尚未证明，不宣称全闭环。 |
| E3 S2 | PASS | compaction provider 调用发送前持久化扣账，失败不退款，多批及 CAS/archive 故障语义保留。`test_runtime_compaction.py`：19 passed；运行预算/传输/child 联合回归：56 passed。 |
| E3 M1 | PASS | 2026-09-14 真实 `/models` 与 Chat Completions 证明新 key 可用；旧 shell `DEEPSEEK_API_KEY` 是另一把失效 key。官方请求名 `deepseek-v4-flash` 的 response identity 实际回显 `deepseek-flash`，现以两个精确别名闭集接受，其他 model 仍拒绝。精确官方 identity 的 capacity 档案投影 1M context / 384K output，并联动有界 SSE 字节预算；第三方 compatible endpoint 不继承。真实最小请求 `max_tokens=384000` 返回 200/stop，仅用 8 tokens。Provider/CLI focused 156 passed，最终全量 3625 passed / 3 skipped。M1 合同闭合；此结论不外推为所有 D/R 场景通过。 |
| E4 C4 | IN PROGRESS | D01/D02/D04 已物化为可复制 fixture，并有 workspace 外部业务 grader。原始缺陷均为 FAIL，reference behavior 均为 PASS；验收设施 10 passed，复制后可见测试分别 1/2/1 passed。2026-09-14 新鲜 D01 真实运行在独立 candidate/state/ledger 上闭环：First Agent 自主修改、读回并运行项目测试，Runtime 3/3 evidence，13 次 model attempt；外部 grader `scenario_contract_pass=true`，candidate 项目测试 1 passed，业务提醒/检查/收尾救场均为 0。过程仍有两次 sandbox precondition 失败、无价值 `__pycache__` 探索和较长 Max-thinking 延迟。D02/D04 及 D03、D05–D12、R01–R03 仍未获得同等级真实成绩。 |

最终源码 gate：`git diff --check`、`.venv/bin/ruff check .` 均 exit 0；
`.venv/bin/python -m pytest -q -rx` 为 3625 passed / 3 skipped，405.73 秒。
wheel 安装态仍未运行；真实付费 dogfood 只完成 D01，上表不得解读为整包 PASS。

### 新鲜 dogfood 新增问题

- **N01 / fixed candidate**：D01 启动时显示 `Sandbox: ready`，但两次 `sandbox_exec`
  都在 effect 前返回 `binding_failure`。独立复现显示 macOS `tempfile.gettempdir()` 返回
  `/var/...`，而 sandbox policy 正确要求 canonical `/private/var/...`；composition 创建目录后
  未 canonicalize。现在系统 temp root 在派生 session 目录前先 `resolve(strict=True)`。
  symlink 反例以及 sandbox composition/executor focused gate 共 42 passed；同机真实
  `workspace-write/network-off` binding 已成功准备。尚未把这条修复后的 sandbox 路径重新加入
  新鲜付费 D 场景，故这里只签 fixed candidate，不冒充 E3 PASS。
