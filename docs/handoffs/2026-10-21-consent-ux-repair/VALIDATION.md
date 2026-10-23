# 验收与证据合同

本文件与 SPEC 一起冻结。本轮不以“少输出了几行”“不再运行任务”或“operator 自动 yes”
冒充降低确认负担。产品行为的 Red 必须在当前生产路径可失败，不能只测测试替身。

## 1. 计数口径

每个 journey 使用 fresh 合成工作区/会话/ledger，冻结 provider 响应序列和用户回答序列。
ScriptedProvider 只替代远端模型，不替代 Runtime、ContextManager、policy、checkpoint、
CLI 解析/渲染或效果执行。不能 monkeypatch 授权判定、自动添加 receipt、直接设置 grant 后
就宣称整链通过。

分别记录：

- `disclosure_decisions`：用户回答的外发许可决定数，包括拒绝。
- `file_decisions` / `process_decisions`：用户回答的文件/命令审批数。
- `recovery_decisions`：未知结果的人工消歧数；不能混成 yes。
- `business_nudges`：额外“继续”、补文件路径、提示修法、解释失败等业务救场数，正例必须为0。
- `rendered_pending_count`：提示重绘次数，单独记录；`/help` 后重绘不等于新权限决定。
- `provider_attempts` / `effect_calls` / 目标文件 SHA或业务断言 / typed 结果。

一个 fixture 中的“少问”必须对应相同有效任务效果。提前 exit、被拒绝、达到预算、provider
脚本耗尽或只进入待审批状态，都不能算正例完成。明确到某个安全边界的负例单独命名。
真实 provider 请求数与离线 ScriptedProvider 调用数必须分开。

## 2. 固定正例旅程

| ID | 任务/操作与固定选择 | 验收预算与效果 |
| --- | --- | --- |
| U1 普通对话 | 新会话连续3轮文本问答；首次明确选择 SPEC 的会话范围外发许可 | 外发决定恰1；3轮回答都完成；provider实际调用3次；没有工具 |
| U2 精确文件 | Goal已明确含 `notes/a.txt`；同一 `write_file` 连续3次；第一次选择精确文件复用 | 文件决定恰1、文件写效果3次、最终字节等于第三次内容；授权消耗3、剩余13（终态清空前观测） |
| U3 已声明目录 | Goal明确含目录 `notes/`；同一 `write_file` 写 `notes/a.txt`、`notes/b.txt`，再更新a；选择目录复用 | 文件决定恰1、3个效果；越界文件不在此正例；目录必须由已有资格判定给出 |
| U4 精确命令 | 使用合成无外网脚本，通过生产 `local_process` 连续执行3次完全相同 candidate；首次按现有审批语义批准 | 命令决定恰1、实际进程成功3次、lease消费3/8；保留same-UID警告；不使用 shell 通配白名单 |
| U5 恢复 | 普通外发许可后，计划内 `/pause` →关闭→新进程打开同一合成checkpoint→`/resume` | 范围许可仍有效时没有新增外发决定；未消费/未知的效果不重放；恢复确实取得新答案而非停在idle |
| U6 压缩 | 生产ContextManager构造真实可压缩历史，正常→压缩→正常；只涉及已许可范围 | 外发决定恰1；普通和压缩provider均实际执行；archive/CAS成功；不能只调用私有builder比较摘要 |
| U7 旧精确路径 | 与U1相同，但所有回答为旧 `y` / `/ack-provider <digest>` | 不产生任何新范围grant；保留旧精确request语义；不会悄悄享有新范围权限 |

U2/U3/U4 的外发决定另外如实统计，**不得把文件决定=1说成总干预=1**。在隔离验证效果授权时
可以使用本地descriptor；综合交互旅程须启用remote descriptor并报告每类决定。

额外必需综合样本 U8：远端descriptor、Goal明确含 `notes/a.txt`、同一write_file三次修改，
随后真实read_file读回和CompletionClaim。计数从已有合法Goal后的第一次外发提示开始：
使用公开checkpoint fixture构造已接受Goal、权威用户fact及期望第三次字节的admitted
filesystem criterion，不预置任何passed EvidenceRecord或文件结果。初始目标文件不存在，
父目录已存在。按既有Resume/active-run合同启动，不插入一条新的“继续”业务消息。

固定5个模型响应：写one→写two→写final→read_file→从trusted projection生成合法claim。
输入预先固定为 `s → f → y → y`：两个y依次批准首次文件结果稳定范围、最后read-back
的workspace_excerpt（本轮未扩成常规来源）。**外发决定3、文件决定1、合计4；模型调用5，
写效果3、读回1，最终文件字节正确且Goal为VERIFIED_DONE。** 独立读盘核对最终SHA，不
使用文本“done”替代typed终态；原ClosedEvidenceRegistry与完成门不得猴补/修改。

这是对Oracle四响应示例的收紧：它未覆盖本产品完成门所需read-back，不能把未验证的收尾
省掉来凑合计3次。若前置fixture不合法，先按已有合法Goal测试夹具修正前置并冻结，不能
在失败后删除read-back/终态、改权限或改序列让数字好看。

U8旧版基线使用相同响应/效果序列，旧y/slash的人工固定选择，记录全部次数；不覆盖BASELINE。
新测试多出一个提示立即失败，不用“while pending就yes”。只通过聊天U1不算本轮收口。

U9：生产ContextManager/Runtime的五次发送A→B→A→B→B（A常规，B同一可信文件来源），
初次s一次、B披露y一次，共2次外发决定、5次实际模型调用；中间A不抹掉B例外。
禁止只用 `_required_disclosure` 的摘要比较替代整链。

## 3. 必须保留的负控

### 输入与展示

1. 没有pending时，新单键/数字是普通用户消息，不抢占业务文本；不适用范围不展示且不接受。
2. 未显示的选项拒绝且不回落到单笔批准。显示和解析用同一snapshot；等待输入中state漂移→
   CAS conflict，provider/工具调用增量0，不偷偷改批新请求。
3. 文件y依旧只批准本笔；外发y依旧只承认当前精确request类别，不能误标“只允许一次HTTP”。
4. 空回车、n、EOF、Ctrl-C均不扩大任何权限；外发拒绝退出保留任务；已有非外发空输入行为
   保持。unknown outcome仍只有原消歧动作，yes和新短选项不能代替。
5. 确认中路径、argv、provider/model与长文本使用原terminal escaping；恶意换行/ANSI不得
   伪造选项、scope、批准记录。正常提示中不要求用户抄内部request ID或digest。

### 范围和生命周期

6. 同一模型换endpoint、同一endpoint换model/descriptor、换conversation/workspace，均不能
   使用原范围许可。空或未知workspace不能当通配符。
7. 新来源/未知类别/通用tool_results不因会话许可自动通过；Memory、MCP、Skill、SubAgent、
   web等各至少一个未覆盖来源反例。不得只用字面工具名或工具自报metadata授信。
8. 覆盖的类别集合收缩/再次扩展、历史/控制回执加入，不触发重复决定；actual data_classes
   仍与真正ContextPack一致。未覆盖类别无论在普通build还是compaction都在provider前拦住。
9. 到期、撤销、`/new`后无复用；撤销成功后的后续发送必须重新许可，不能回落到同次范围
   批准遗留的exact receipt。清楚区分已发出的请求（无法撤回）与尚未发送的下一次请求。
10. 文件越界、不同操作write/edit、Goal revision变化、租约到期/耗尽/撤销，维持既有审批。
    散文Goal未准入的目标不可伪装scope；不得自动扩到父目录。
11. 进程argv/cwd/executable/env/profile/Goal身份任一变化仍要审批；第9次不能借8次lease通过。
    原暂停/取消会清除进程租约，本包不得改成自动保留或自动重建。

### 持久化、恢复与其它入口

12. 新schema正常roundtrip；无active run但有许可时也不落回遗失字段的旧编码版本。
13. 旧支持版本与v10正常加载，新范围字段缺省为空；旧receipt、pending不被升级为宽授权。
    新版本未知字段、损坏digest/时间/枚举/绑定严格拒绝。旧数据迁移不能变成宽松解码。
14. 特别覆盖旧pending外发→pause→新进程→resume→回答：孤儿请求可恢复；取消/拒绝不派发。
15. 授权保存失败/CAS冲突在provider前停；保存成功后崩溃不伪造许可或隐式延长有效期。
    未知效果仍走已有恢复；既有provider intent/persisted response链不可被新门禁绕过。
16. headless/TUI旧typed action行为不扩大；新权限只能通过显式新action/新字段合法值取得，
    CLI不是另一个权限权威。后台caller不得把交互式会话许可当自行获得用户批准的办法。
17. 同一grant第32次成功、第33次零自动派发；普通/压缩/重试共用durable计数，失败不退款。
    已保存response恢复零新派发/零新扣次；过期后的单次明确许可不恢复额度。
18. 新工具/同名schema变化/control schema变化不得继承；减少已批准工具可复用。
    summary来源继承、未知旧summary、工具伪造来源字段、同名非内置工具全部有负控。
19. 同一文件成功结果的每次执行证明不同而stable scope相同；不同文件/操作/Goal revision/
    registration/policy身份即不同。失败/未执行结果不得取得稳定复用资格。
20. 真实mutation lease顺序：发送持锁时竞争revoke明确busy而非假成功；revoke先落盘则
    后续发送为0。两发送路径都覆盖。不得绕锁造一个“已接受撤销”的测试假象。

## 4. 测试执行顺序

1. 接手读取入口/源码身份；先跑 `baseline_probe.py`，保留原BASELINE，不覆盖审计证据。
2. 每工作包新增最小失败测试，记录失败节点与准确原因，再最小实现。相邻修改只跑touched-area。
3. 本轮新增测试统一用 `test_consent_ux_` 前缀，便于在源码与安装态冻结完全相同的节点集。
   测试名建议按U1–U9/N1–N20对应；一个参数化测试可覆盖多个安全负控。
4. 受影响现有套件至少包括：

```bash
PYTEST_ADDOPTS='' PYTHONDONTWRITEBYTECODE=1 PIP_NO_INDEX=1 \
  .venv/bin/python -m pytest -q -rx \
  tests/cli/test_contextual_decisions.py tests/cli/test_render.py \
  tests/provider/test_remote_disclosure.py \
  tests/cli/test_process_authority_parity.py \
  tests/kernel/test_runtime_process_authority.py \
  tests/kernel/test_runtime_compaction.py tests/kernel/test_checkpoint.py \
  tests/kernel/test_checkpoint_corruption.py tests/continuity/test_checkpoint_v2.py \
  tests/continuity/test_checkpoint_v4.py
```

新增测试文件也加入focused命令。修改context来源投影则运行对应source/continuity套件；
只做CLI文案时不必逐次全库。

5. 最终源码稳定后，集中一次项目门：

```bash
git diff --check
.venv/bin/ruff check .
PYTEST_ADDOPTS='' PYTHONDONTWRITEBYTECODE=1 PIP_NO_INDEX=1 \
  .venv/bin/python -m pytest -q -rx
```

需要等待长命令时使用可轮询进程，持续给简洁进度。单次全库建议硬上限1800s；超时不算PASS。
如果发现本轮引入失败，最小修复后按风险补跑相应门；不能为了“一次”掩盖失败，也不能无依据
循环全库。预存失败要有复证才可如此标记。设计内host skip逐条解释，不为去掉skip注册系统服务。

## 5. 安装身份和用户交付

- 使用既有安全candidate builder的当前CLI（先读其 `--help` 与对应测试），只物化显式公开输入；
  fresh唯一输出，不覆盖已有候选。禁止复用有build/lib残留的输出；不动未知用户文件。
- 离线 `pip wheel --no-deps --no-build-isolation --no-index`，全新非editable venv安装；
  依赖不足记阻塞，不擅自联网安装。不要使用system-site-packages冒充干净安装。
- 冻结最终源码/候选manifest/wheel SHA；核对产品文件逐一一致。中立cwd、无源码回落，
  用既有 `scripts/_019_installed_pytest.py`（先读CLI）跑本轮冻结节点；collect==executed，
  session_completed且所有产品origin来自新wheel。用户旅程子进程同样需要origin证明。
- 另创建新的专用preview和state位置；**仅在用户发送本包执行prompt授权该交付后**创建，
  保留旧 `/Users/jinkun.wang/.local/share/first-agent/previews/20261018-cli-9rmRS6`。
  启动脚本不内嵌凭据；只引用调用进程已有的环境变量。不要修改shell profile/PATH/登录项。
- 交付精确新启动路径、workspace参数示例、许可选项含义和撤销命令。中立cwd走启动帮助、
  fake对话→退出→重开；真实API没运行就明确说，不用假provider证明模型品质。

## 6. 可选真实测试，不是当前授权

只有收到新明确授权后，才运行一项小型合成工作区旅程。建议申请：用户指定当前可用的
provider/model/endpoint、仅调用进程环境凭据、最多20次物理请求（含失败）/15分钟；
只发合成数据，达到任一上限停止。若用户选择不同预算，以新授权为准，不能累加重试额度。
禁止读取历史聊天中的key或凭据文件。没有授权不阻塞本地/安装交付，不得称真实用户验收完成。

## 7. 最终报告必须包含

逐包状态；每个Red→Green；U1–U9计数和任务效果；N1–N20结果；全库/ruff/diff结果及版本；
候选/安装origin；新启动命令；未验证项及原因；没有做的范围外事项。保留所有失败尝试，
用最新冻结身份说明修复后结果，不删除失败样本、不修改原BASELINE/Oracle附件。
