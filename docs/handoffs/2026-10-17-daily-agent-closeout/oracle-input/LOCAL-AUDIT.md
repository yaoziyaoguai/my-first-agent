# Codex本地核对（Oracle发送时快照）

## 已完成与本次验证

- 当前main=0cc0db1（PR #5 merge），本地origin/main一致；未fetch、未远程修改。上一包ef06b10后35文件5121+/202-。
- R1严格旧拒绝prefix、R2身份/解码、原始用户fact pin、helper不隐式填coverage、R3撤回、R4无参范围命令、C1/C2组合测试、provider压缩摘要wire修复均已有代码，不重做。
- 本次独立focused：9文件310 passed / 16.91s / exit0。文件为test_task_trust_completion、test_task_trust_d04_driver、CLI contextual_decisions/render、context_budgeting、validation_request_freshness、provider continuity_control、verified_done、checkpoint_v4。ruff通过。
- 未运行当前全库、当前installed、产品真实API；不读取旧私有会话/日志或未跟踪result.phase.json。上轮真实结果仅当公开执行记录自报，不能伪称本次独立复跑。

## 确认的R2反例

沿用tests/acceptance/test_task_trust_completion.py的公开fixture、_FileTaskProvider、_open_and_drive、审批、真LocalCheckpointStore与独立grader。
创建与现有omission测试相同的draft：用户明确要service+CLI，模型仅提出service criterion。正常写入/读回service。在hollow阶段改成调用现成_claim_for(..., hollow=False)，生成非空satisfied coverage，然后不再实现CLI。所有文件都在本次专属临时目录，provider是scripted，零网络。

实测完整输出：

```json
{"goal_status":"verified_done","provider_calls":4,"cli_unchanged":true,"admitted_count":1,"coverage_rows":1,"business":{"latest_correction":false,"resume_without_restatement":false,"no_effect_replay":false,"final_validation":false},"supplemental":{"transient_new_name":true,"legacy_alias":true,"default_single_attempt":true,"bounded_attempts":true,"conflict_rejected":true,"negative_invalid":true,"cli_both_names":false}}
```

解释边界：冻结grader两个过程项原本恒false，不拿它们当缺陷；本次两个**业务**项也false，并有CLI保持原字节与补充行为失败为独立旁证。此结果证明当前Runtime可接纳这种非空虚假完成，不证明真实模型必定/经常这样做，也不要求Runtime证明任意语义。第一次探针因macOS /var路径symlink被state-root安全检查拒绝；将专属临时路径resolve后才得到以上有效结果，未改产品。

## 真实验收与可用性缺口（公开记录）

RESULTS记录：E1-A normal业务+补充7/7通过，但40次请求、17次审批、2次limit恢复后仍paused_limit，typed VERIFIED_DONE未达；E1-B staged新纠正+跨进程恢复到typed VERIFIED_DONE、20次请求、5次审批。记录将R2/E1整体标DONE/RESOLVED，与原VALIDATION正常样本须产品自行终结的条件不一致。

driver代码：normal也会额外注入CORRECTION；JourneyOperator还会在idle主动发“继续当前任务”（最多3次），两模式均可再/resume（最多2次），_consent只回答y，不选择新复用授权。不能把driver推进归结为产品自主推进，也不能从17次审批直接推断范围授权可把审批降至某个固定数字。最终evaluate_final在typed终态缺失时正确incomplete；强结论主要出现在报告层。

## 审批与收尾路径

- _goal_target_authorization_scope对exact-file要求path in goal.targets；GoalDraft targets允许任意非空字符串。公开记录与代码注释都确认SPEC驱动targets常为散文，E1-A 0/17可复用。新UI只解释为何要逐笔批准，没有让普通任务实际获得可选择的精确范围授权。需要保留human opt-in、same goal/revision/workspace、exact pending digest、TTL/次数/撤销/敏感拒绝；不能直接目录allow-all。
- blocked分支仍只用ClosedEvidenceRegistry.derive判“可完成”，探针claim无requirement_coverage；derive只检查当前admitted物理证据。成功就强制让模型补coverage+claim并禁止blocked。R2-C改动仅文案；它不等于共享业务覆盖门。是否可构造正常真实blocker误拒仍待核实，不先宣称已复现。
- 文件readback之后的任何workspace mutation/潜在可写执行都使旧验证失效。这是现有保守合同；不在没有独立证明前直接放宽。可能是反复收尾的一部分，但没有旧真实逐轮日志，当前尚不能归因E1-A的40请求具体去了哪里。
- Goal全部来源现在每轮pin；预算超出走ContextLimitError。它避免原文静默缺失，但很长输入/多次correction有可用性上界。当前尚未证明日常短任务因此失败，勿为此另造长期记忆系统。

## 交付身份与产品范围

I1/G1记录为2026-10-15候选（wheel 05838e08…9918、41 installed、3873+1skip）；2026-10-16之后仍修改provider/normalize.py、CLI/render.py、main.py，新增driver/tests，README/current状态仍沿用旧数字称“当前identity”。缺当前安装身份链；本次没有读旧/tmp产物求证，不应直接复用旧PASS。

现有产品已经有setup、持久化、CLI/TUI/streaming、workspace检索、文件修改、受控本机/sandbox/shell、pause/resume/cancel/new、history、可选Web/browser、memory/skill/MCP/subagent候选等。用户要尽快好用，不必再添能力菜单。可选Browser尚无当前D06模型层证明；Scheduler入口无host composition返回needs_019_config；strict-tools有open-object组合限制。建议先选macOS+一个既有provider+CLI+本地项目任务为首版支持面，请Oracle挑战/收敛。
