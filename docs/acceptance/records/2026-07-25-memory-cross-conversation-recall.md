# Memory Reference Task

- Revision/worktree digest: baseline_commit `7d935ac4af7121c54e1bdcc600763c3f0fbf54c2`；009 未封存继承副本（E3 records 待 reviewer 封存）。
- User-approved task: conversation A 经 preview/approval 记住一条合成约定；独立 conversation B 在同 workspace/profile 召回并应用；不相关 query 不召回；记录 revision/candidate digest/budget，不保存 raw inventory。
- Destination/profile identity: provider `anthropic_compatible`；base URL `https://open.bigmodel.cn/api/anthropic`；model `glm-5.2`；timeout 90s。Memory store 在 mktemp 临时目录（workspace 之外），`--memory-profile e3`（profile_id/family/destination 三元在 A/B 一致以通过 store 校验）。
- Data/effect scope: 合成非敏感约定 "The release codename for July 2026 is MARLIN."；无关 query "capital of France"；无 secret/真实日志/用户路径。
- Baseline: conversation B 不配置 Memory（无 `--memory-store`），同一 query。
- Success criteria: (1) A 经 `memory_remember` governed 写入（preview+approval）落盘；(2) B 同 workspace/profile 召回并应用 MARLIN；(3) baseline 不知 MARLIN；(4) 无关 query 不召回（无 MARLIN 泄漏）；(5) store revision 可核对、raw inventory 不暴露给 model。
- Result: **pass**
- Model/tool/effect counts: A：1 approval（`memory_remember`）→ 1 tool_result，store revision=1、records=1。B-baseline：0 memory、模型 list/read 探查空 workspace 后表示找不到（has_MARLIN=False）。B-recall：0 approval、模型直接作答 MARLIN（候选由 `MemoryContextSource` 被动注入为 untrusted context）。B-irrelevant：0 tool_result、答 Paris、has_MARLIN=False。
- Checkpoint terminal status: 非持久会话；各轮 rc=0、无悬挂 active_run。durable Memory store revision=1（A 写入后），B 加载同一 store。
- Observable delta: A 渲染 memory_remember approval preview（含 MARLIN 全文）并落盘（store has_MARLIN=True）；B-recall 终答 "The release codename for July 2026 in this project is MARLIN."，而 B-baseline 终答"找不到"。memory record id（短）`523bff37d279adb4`。召回为被动 ContextSource 投影（`KernelContextManager` 每次 build 调 `snapshot`，按 token 重叠 + 子串评分排序、cap 8、超预算整体丢弃），model 仅见 bounded untrusted 候选，永不见 raw inventory。
- Limitations and unverified claims: budget clipping（candidate 超长被整体排除）与 stale-approval/CAS fault matrix 已由 E1/E2 覆盖；本 E3 验证真实 provider 下 A→B 跨会话 governed remember/recall 正向路径与无关 query 不召回。驱动经 `main.main(input_fn, write_fn)` 真实入口。`--memory-profile`/base_url 在 A/B 必须一致（否则 store profile 校验 fail-closed），已按此约束执行。
