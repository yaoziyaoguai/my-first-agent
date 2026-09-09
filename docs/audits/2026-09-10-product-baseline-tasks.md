# 产品基线:三类真实任务(r19 小步 1)

日期:2026-09-10 · 依据:Oracle r19(`first-agent-r19-product-audit-20260909`)第一轮小步 1
"建立当前安装制品的真实任务基线" · 定位:产品化首轮实测,不是 promotion E3。

## 方法

- 制品:当前源码树(`.venv` 直跑,产品装配 `EVERYDAY_SYSTEM_POLICY` + 默认
  ContextLimits 100k/8k + `build_tool_registrations` 全量工具)。
- Provider:`anthropic_compatible` / `glm-5.2` @ `open.bigmodel.cn/api/anthropic`
  (credential env `ANTHROPIC_AUTH_TOKEN`),`thinking_mode="disabled"`。
- 驱动:仓库外 headless 驱动(`~/work_space/fa-r19-baseline/drive.py`),复用
  `AgentRuntime.run_turn` typed action 状态机(Submit → disclosure ack →
  ResolveApproval → Resume),与 E3 journey runner 同一模式;owner 批准策略
  (每次 approval preview 入档),不代写答案、不修产物。
- 核对:独立脚本(`verify.py`)重算 ground truth,不复用产品代码。
- 材料:合成脱敏数据,任务定义见各任务目录(Task 1 `SPEC.md` / Task 2 `README.md` /
  Task 3 `TASK.md`)。

## 结果

| 任务 | 结果 | 耗时 | 审批 | 人工救场 |
|---|---|---|---|---|
| 1 数据处理(requests.csv → P95 报告) | **完成,有瑕疵**:12 组 count 与 P95(nearest-rank)全部正确;**errors 列 3/12 组心算错(±1)**,结论段引用了错误数字 | 59.4s | 1(write report.md) | 0 |
| 2 代码维护(GBK 编码 bug) | **完美**:`encoding="gbk"` 修复正确,pytest 全绿,`weather.csv` GBK 字节未动 | 31.6s | 1(edit app.py) | 0 |
| 3 知识工作(三份冲突需求 → 执行说明) | **完美**:6 个功能点全部标注来源;**5 个冲突/未决全部单列待决**(分页 100 vs 500、TTL 5min vs 60min、按钮问题、Excel 需求、权威缺失),未擅自拍板 | 46.6s | 1(write plan.md) | 0 |

三任务终态均为 `COMPLETED`(VERIFIED_DONE evidence gate 通过);无未授权 effect;
审批均为常规安全审批(write/edit 类),无人工代写。

## 过程发现(基线的最大价值)

### 发现 1:Provider 组合 100% 阻断(产品缺陷,已修复)

首轮 task1 直接 `failed_fatal`:bigmodel anthropic 端点对 glm-5.2 **默认返回
`thinking` block**,normalize 层按合同拒绝(opaque reasoning 不接纳),10 次修复
重试后致命失败。产品缺口链:

1. `thinking_mode="disabled"` 合同只允许 openai_compatible(`config.py` 旧 L59)。
2. 实测端点支持 Anthropic 官方 `thinking: {"type": "disabled"}` → 修复 1:
   `config.py` 放开 anthropic 分支 + `anthropic_http.py` 请求注入。
3. 修复 1 后仍失败:端点在**带 tool_result 的多轮请求中违反 disabled 仍返回
   thinking block**(探测复现:R1 仅 `tool_use`;R2 混入 `thinking`)→ 修复 2:
   `normalize.py` 对 anthropic 响应的 `thinking` block 显式丢弃(opaque 推理
   不展示、不持久化、不当内容;text/tool_use 校验与 envelope 级 opaque 拒绝
   不放松)。
4. provider 全套 317 passed(含两条新合同测试)。

这正是 r19 审计"短板 #4 组合覆盖不足"的实例:**fail-closed 正确,组合可用性
才是缺口**;两条修复均属 r18 重开条件第一条(支持范围内可复现合同缺陷)。

### 发现 2:数值统计的模型心算不可靠(模型能力边界)

Task 1 的 errors 列是模型直接读 CSV 心算的(未用 `local_process` 跑脚本统计),
3/12 组数错。count/P95 同样心算却全对(样本量大、错率高的是小计数)。产品层
缓解方向:system policy 引导"数值统计必须经 `local_process`/`shell_exec` 用工具
计算",而不是让模型数数。

### 发现 3:artifact confirmation 对"将新建文件"的 owner 不可用(交互负担)

模型在部分 Goal 里声明 FILESYSTEM_DIGEST criterion 时,approval 携带
artifact confirmation requirement,owner 必须当场提供期望产物 digest
(TUI `/approve-artifact <sha> <path>`)。对**已存在文件的 edit**(task2)owner
可用磁盘当前 digest;对**将新建的文件**(如 task1 的 report.md,本轮模型未声明
该 criterion 故未触发)owner 无法预知 digest——该交互在此场景不可用,只能拒绝
批准。与 r19 审计"审批负担需实测"一致:这是一个真实的产品交互设计点
(候选方向:预览内容即确认来源,或对该场景降低 criterion 声明频率)。

### 附:两个一次性摩擦(驱动/环境,非产品)

- state root 路径含 symlink(`/tmp`)被 fail-closed 拒绝(正确行为;对真实用户
  的路径卫生要求值得在文档提示)。
- `conversation_id` 必须为 canonical UUID。

## 瓶颈归因(r19 审计要求:区分模型/工具/配置/审批/UI)

- **配置/组合**:阻断性缺口 1 个(Provider thinking,已修复)。
- **模型能力**:数值心算不可靠(1/3 任务出现);代码修复与知识综合表现良好。
- **工具**:无阻断;`local_process`/`shell_exec` 可用但模型在 task1 未选择使用。
- **审批**:负担低(每任务 1 次);artifact confirmation 的边缘交互见发现 3。
- **反馈时机**:每轮模型调用前均需 disclosure ack(驱动自动处理);真实 CLI
  用户逐轮确认的成本未测——与小步 3(流式)相关性待后续验证。

## 对小步 2/3 的校准建议

1. 小步 2(`/new` 新任务入口)价值确认:三任务各自独立 workspace 才能干净完成,
   连续使用确实断在"完成一件后无法开始下一件"。
2. 小步 3(流式)优先级微调:本轮 30-60s 级任务中"等待无反馈"体感明显
   (模型调用期间无任何中间输出),流式仍是正确方向;但 disclosure 每轮 ack
   的交互成本可能比非流式更影响体验,建议小步 3 同轮观察。
3. 发现 2 的 policy 引导(统计用工具)是低成本高收益的收尾型改进候选。

## 复现

材料与驱动在 `~/work_space/fa-r19-baseline/`(仓库外);timeline JSON
(`out-task*.json`)与 checkpoint(`state/`)保留在该目录。产品修复见本轮
commit(config/anthropic_http/normalize + tests/provider)。
