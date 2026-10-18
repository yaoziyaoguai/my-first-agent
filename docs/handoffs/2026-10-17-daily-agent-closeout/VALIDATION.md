# 验收与停止条件

本文件是下一位实施者的验收合同，不是本轮已经执行的结果。只有当前执行对话授予的权限有效。已有 R1/R3/C1/C2 不重新实现；只补本包触及的回归与交付证据。

## 1. 先固定本轮输入，避免继续堆测试而业务不变

接手先核对 `git status --short --branch`、HEAD、适用 AGENTS 和唯一 RESULTS。基线为 `0cc0db1`；若已改变，比较变动后决定哪些证据失效，不能 reset 到旧基线。

- 原 D04 `SPEC.md`、grader、manifest 和独立补充业务检查保持字节/判据不变。另建 staged 派生 fixture 必须标注派生身份，不能修改原始验收。
- 先运行 PROBES 的非空错误完成与散文目标两个反例。保存修前完整观察；回归断言应期待修后安全行为，Red 不得只是 import/字段拼写错误。
- 不通过预先补齐遗漏 criterion、在测试 helper 中生成 coverage、脚本固定写第二文件、放宽 grader 或提高预算来造 Green。
- 使用唯一临时父目录及其未存在的 candidate/manifest 叶子。不得读取旧私有运行目录、清理旧候选、操作未知 `result.phase.json`。

## 2. 分包 focused；不要每改一个文件就跑全库

完成合同/持久化/控制 schema 相关变动时，选择并记录实际触及的 contracts、checkpoint、provider、context、CLI 及 continuity node。至少包含：

```bash
PYTHONDONTWRITEBYTECODE=1 PIP_NO_INDEX=1 .venv/bin/python -m pytest -q -rx \
  tests/acceptance/test_task_trust_completion.py \
  tests/continuity/test_verified_done.py \
  tests/continuity/test_checkpoint_v4.py \
  tests/provider/test_continuity_control.py
```

授权交互至少包含：

```bash
PYTHONDONTWRITEBYTECODE=1 PIP_NO_INDEX=1 .venv/bin/python -m pytest -q -rx \
  tests/cli/test_contextual_decisions.py tests/cli/test_commands.py \
  tests/cli/test_render.py tests/continuity/test_goal_policy.py \
  tests/continuity/test_goal_controls.py tests/kernel/test_runtime_approval.py
```

driver 变更至少包含 `tests/acceptance/test_task_trust_d04_driver.py` 与原 `test_coding_autonomy_grader.py`。具体新增 node 与结果写入 RESULTS，不能只引用一组总数。不存在的文件/节点不能照抄为已执行。

## 3. 无提醒真实旅程：先离线验证 driver，再申请有界成本

### 3.1 修正测量方式

- normal 使用完整原 SPEC 和一次初始任务；不得自动注入 CORRECTION，不得发送“继续当前任务”、业务提醒、失败解释或指定文件。
- staged 是唯一可以按冻结时机追加那一条新纠正的模式；必须先证明纠正未提前泄露、未提前实现，再在安全边界 durable 消费，pause→退出→新 PID 恢复。
- 治理审批、数据外发确认、用户显式范围授权不算业务提示，但必须分别计数。driver 只能对本次明确授权的合成资源作固定选择；不能把“自动 y”变成用户对所有副作用的授权。
- 计划中的 staged `/resume` 与预算/错误后的救场 `/resume` 分开记录；normal 到 limit 后如实 incomplete，不自动加预算或救场。
- 外部业务探针只送给验收记录，不反馈实现模型。typed 状态、用户看到的完成措辞、业务结果、实际执行数和过程证据分别保存。
- 补充检查必须有冻结的完整键集合，任何缺失、未知、非 bool、空集合均不能计 PASS；不只是对传入字典做 `all()`。保留原两个固定 false 过程项，不拿它们当过程证明。

### 3.2 真实调用授权清单

执行前一次性确认：精确 provider/model/endpoint/thinking mode、允许读取的凭据环境变量名/注入来源、只允许外发本次公开合成项目、累计物理请求与墙钟上限、脱敏证据保存位置。密钥值不进文档/命令字面量/输出/仓库，不能从 Pi/Claude/历史会话找替代 key。

**建议预算不是本包授予的权限：** 先只跑 normal 一个代表样本，上限 40 个物理请求；通过后才跑 staged，上限 40 个，合计不超过 80 个、总墙钟 60 分钟。401、429/额度、账单或硬预算到界就停止对应付费操作；失败请求同样占预算。transport ledger 跨进程累计，不通过重启清零。

若还没有授权，标 `BLOCKED_AUTHORIZATION`，继续离线与安装层。若有授权但 normal 未通过，先分类本次实际原因；只有新的可证伪假设/必要修复和剩余授权预算才可重跑。不得不停重试挑一次成功。

### 3.3 首版放行条件

两条旅程都必须：

1. service/CLI 等冻结业务行为完整，grader 的两个业务值 true、七个补充值全 true。
2. 产品 durable Goal 状态达到 `VERIFIED_DONE`，且声明范围与实际验收一致；不能把 `RunStatus.COMPLETED`、最后一句“完成”或外部 driver 收尾当作产品完成。本包没有降低原正例的终态要求。
3. **业务提醒/失败诊断/手工补代码次数均为 0**。normal 无额外 correction/“继续”/救场 resume；staged 只含预定的一条 correction 与一次新进程恢复。
4. 没有 unknown effect 被伪装为未执行/成功，没有发生未经授权的写入、网络或权限扩张。
5. 正例成本按真实请求数、审批类型、等待和停因报告；不预先许诺“17 次降为 1 次”。目标是验证可用的路径，不是美化数字。

若任务业务正确但未终结，记 `INCOMPLETE_CLOSURE`；若状态声称的保证强于实际验收，记 `FAIL_FALSE_COMPLETION`；若仅缺当前 API 授权，记 `BLOCKED_AUTHORIZATION`。任一种都不是日用 beta 放行。

## 4. 最终身份与安装门，只做当前支持面

所有必要产品/driver 变动稳定后，复用原 `scripts/build_candidate_manifest.py` 和 `scripts/_019_installed_pytest.py`：

- 新候选目录不存在 build/lib、dist、egg-info；独占创建，不覆盖任何旧输出。
- source manifest 与候选逐文件 SHA 一致，显式纳入本轮新公开模块/测试，不用 `git add .` 或扫 ignored/private 输入。
- 离线构建 non-editable wheel，记录 manifest SHA、wheel SHA 和相关源码身份。安装到新的隔离环境，在仓库外中立 cwd 运行；origin 必须来自安装物。
- 用安装态运行本包关键完成负/正例、授权从提示到 Runtime、checkpoint 重开及至少一条真实入口测试。补齐实际新增 node；零节点/skip 不能算 PASS。
- 做一条用户路径：新 isolated state-root → setup（不保存 key）→ 启动 → 普通合成任务 → 正确终态 → `/new` 第二个小任务 → 退出/重启恢复。离线测试可用 scripted/MockTransport，但必须如实标为非真实模型；有当前授权时真实 E1 绑定同一冻结源码身份。现有 driver 的源码真实旅程与 wheel 安装态测试可以分列，不要求为了名词重写 driver，也不能冒称 installed-real。
- 共用 reducer/view 的 CLI/TUI 完成状态不能分叉；TUI 未改不做全套 UI 重设计，受影响适配测试不能漏。
- 不刷新所有历史 seal、不安装登录项、不增加 Scheduler host、Browser/Memory/MCP/SubAgent extras。

`_019_installed_pytest.py` 没有 `--test-node`；沿用原 VALIDATION 的 `PYTEST_ADDOPTS -k` 精确选择并核对真实 node 集合。保留 source 污染负对照和子进程 origin 证明。

## 5. 最后集中完整门

```bash
git diff --check
.venv/bin/ruff check .
PYTEST_ADDOPTS='' PYTHONDONTWRITEBYTECODE=1 PIP_NO_INDEX=1 .venv/bin/python -m pytest -q -rx
```

只在相关修改稳定后集中跑；后续有产品改动，刷新受影响 focused 与已失效的最终证据。全量观察上限 1800 秒；失败/超时/截断不是 PASS，不能自动重跑掩盖 flake。新未跟踪文件需单独检查，逐字历史证据的行尾空白不能改写伪装全绿。

## 6. 最终汇报模板

在既有唯一 RESULTS 追加本轮，更新开头，不新建第二套 current：

| 包 | 修前证据 | 最小修复 | focused | installed | real | 剩余/身份 |
| --- | --- | --- | --- | --- | --- | --- |
| W1 完成可信 | 非空遗漏声明反例 | 待执行 | NOT_RUN | NOT_RUN | NOT_RUN | |
| W2 授权可用 | 散文 targets 无可用范围 | 待执行 | NOT_RUN | NOT_RUN | 随 E1 观察，不另开付费样本 | |
| W3 正常闭环 | E1-A 未终结/driver 可催促 | 待执行 | NOT_RUN | 按实际触及 | NOT_RUN | |
| G 最终交付 | 旧安装证据早于最终源码 | 待执行 | NOT_RUN | NOT_RUN | 与同一候选绑定 | |

说明新/旧状态的读取与重开、是否真正减少人工干预、未授权或未跑项、输入与构建物 SHA、实际 Git dirty 清单。默认不 commit/push/tag/merge/publish。完成上述包后停止，不自动开新一轮功能。
