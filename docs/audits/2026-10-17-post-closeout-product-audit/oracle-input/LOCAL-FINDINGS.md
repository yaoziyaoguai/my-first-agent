# 本次独立证据（2026-10-17；提交 Oracle 时的快照）

## 已有进展
- git HEAD=0cc0db1（PR5），17 tracked changed，2135 insertions/149 deletions；仍未提交候选。
- 产品变化：state新增authoritative_deliverable_file_paths；完成门/blocked指引对齐；精确文件授权兼容admitted paths；恢复孤儿provider disclosure的yes；driver无催促+七键严格校验。
- 独立 focused 7 files：285 passed in30.84s；ruff+diffcheck通过。完整门在跑，一次，不按每个探针反复全测。
- 上一执行者公开 RESULTS 自报r3 full3947/1skip，installed58/58、153安装来源模块，双污染负对照；r3 normal15requests/11治理决定/1scope授权，staged16requests/15治理决定，typed VERIFIED_DONE+业务七项通过。未独立读原始真实日志/安装证据，此处明确为自报。
- r3 normal首次使用已完成fixture，15requests后 FAILED_FATAL；记录归类“测试污染、产品正确”，但“已正确的正常工作区无法收尾”是否仍有产品风险需要独立判断。不要否认门拒绝无证据本身正确。

## F1 确认：只改空格仍能漏做却 VERIFIED_DONE
完整production composition/AgentRuntime/文件工具/审批/LocalCheckpointStore，仅provider脚本化；复用新增验收 _NonemptyOmissionProvider，非空泛化coverage引用全部source/mandatory；只完成service，CLI从不修改。
- 原D04_TASK包含“命令行适配器 retry_app/cli.py 必须使用同一个值”
  => goal_ready，deliverable_paths=[retry_app/cli.py]，provider calls5，CLI原字节未变，外部cli_both_names=false。
- 只删“适配器”后的一个空格，改成“命令行适配器retry_app/cli.py 必须使用同一个值”
  => VERIFIED_DONE，deliverable_paths=[]，provider calls4，CLI原字节未变，外部cli_both_names=false。
根因候选：_DELIVERABLE_PATH_TOKEN前置(?<![/\\w.])把中文视为word，拒绝紧邻中文的英文路径。不是所有自然语言都要识别，但这一直接明确同义要求仍可穿透已宣称的完成下界。

## F2 确认纯函数误提取，影响待结合完成门审核
同当前Goal权威USER_MESSAGE：
- “修改 app/config.py”=>{app/config.py}；“修改app/config.py”=>{}。
- “Update Python to 3.12”=>{3.12}，版本号被当文件。
- “Implement SPEC.md requirements”=>{SPEC.md}，输入规范被当产物。
- “解释“创建 app/example.py；修改 app/other.py”的含义，不要修改任何文件。”=>{app/example.py,app/other.py}。
- “日志显示：创建 app/old.py；请说明原因，不要修改文件。”=>{app/old.py}。
- “Could you update app/config.py?”=>{}。疑问句排除与礼貌任务请求的冲突是边界，不应为此构建NLP大系统。
识别器先split clause后去引文，跨分句引文去除失效。当前完成门要求这些路径有mandatory FILESYSTEM_DIGEST admission，可能造成阻塞或诱导无关文件确认；无权从此推论越权写入（approval仍在）。

## F3 确认：恢复披露yes修了，no和TUI未闭合
当前孤儿形状：provider_disclosure_request非空/receiptNone/active_runNone/Goal=GOAL_READY（pause+resume真实路径可达）。
- CLI render_pending显示“Allow this information to be sent? [y/N]”。
- _parse_action(y)=>AcknowledgeProviderDisclosure（正确新修复）。
- n/no/否：_contextual_exit_message=>None；_parse_action=>SubmitMessage，不是拒绝/退出。
- 同state的TUI project=>main_text ready, form_kindNone, actions=(pause_goal,correct_goal,cancel_goal)，没有ack_provider。
这是交互/goal污染风险，尚未证明外发绕过；不可夸大成数据泄漏。旧active AWAITING_DISCLOSURE的no仍可正常退出。

## F4 确认源码：staged完成证据仍宽松
scripts/run_task_trust_d04.py:_consumption_view.version_changed =
bool(goal_version_changed OR state_version_changed)。
_staged_evidence的correction_durable检查injected_fact_id属于a_final correction_fact_ids；correction_consumed单独取consumption.fact_id属于consumption.created_from_fact_ids；未显式要求两个fact_id相同。已观察新真实自报版本双推进，不据此推断真实旅程必失败；问题是driver不能严格排除伪阳性，与旧W3合同未闭合。

## 状态文档问题
RESULTS当前摘要仍保留“无产品代码修改”“下一步执行W1”、旧3897测试数字，同时后文写W1-W3/G/r3完成；汇总表real列仍NOT_RUN/待授权，G行却PASS。README/current status把所有current cap都candidate。这需要一个当前identity的一致摘要，不需重写所有历史文档。
