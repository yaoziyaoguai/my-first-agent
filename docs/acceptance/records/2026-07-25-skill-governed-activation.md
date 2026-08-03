# Skill Reference Task

- Revision/worktree digest: baseline_commit `7d935ac4af7121c54e1bdcc600763c3f0fbf54c2`；009 未封存继承副本（E3 records 待 reviewer 封存）。
- User-approved task: 对照"无 Skill baseline"与"启用一个临时 operator-approved Skill/resource"，通过正常 governed discovery/activation/read 路径，让答案应用 baseline 不具备的合成规则；scripts/URL 不可执行。
- Destination/profile identity: provider `anthropic_compatible`；base URL `https://open.bigmodel.cn/api/anthropic`；`/v1/messages`；`x-api-key` via `ANTHROPIC_AUTH_TOKEN`；model `glm-5.2`；timeout 90s。Skill root 为 mktemp 临时目录（workspace 之外），单 Skill `checklabel`（frontmatter name 与目录名一致）+ `references/marker.txt`。
- Data/effect scope: 全合成非敏感数据（规则 token `MAPLE`、deployment marker `OAK-42`、占位 URL `http://internal.example.invalid/marker`）；无 secret/真实日志/用户路径。
- Baseline: 同一 prompt、同一 provider、同一干净 workspace，但不配置 `--skill-root`（无 skill 工具注册）。
- Success criteria: (1) baseline 无法回答（不知 MAPLE/OAK-42）；(2) 启用 skill 后经 `skill__checklabel` 激活 + `skill__read_resource` 读取 resource，答案同时包含 `MAPLE`（body 规则）与 `OAK-42`（仅 resource 内的值）；(3) body 中的 URL/脚本行不触发任何执行/抓取。
- Result: **pass**
- Model/tool/effect counts: baseline 0 工具结果、答案不含 MAPLE/OAK-42。启用 skill：`Tool result recorded` 事件 = 2（`skill__checklabel` 激活 + `skill__read_resource` 读取 `references/marker.txt`），均为 READ_ONLY/NEVER-approval 自动放行；终答同时含 MAPLE 与 OAK-42。无 URL 抓取/subprocess/exec 错误。
- Checkpoint terminal status: 非持久会话（in-memory）；rc=0，无悬挂 active_run；最后一轮 completed。
- Observable delta: baseline 终答"tools are not available … I do not know"；启用 skill 后终答给出 `MAPLE` 与 `OAK-42`。两 token 仅存在于 workspace 外的 skill 文件中，model 不可能凭空猜中两者，故其出现即证明 governed activation/resource-read 路径被真实执行。
- Limitations and unverified claims: 终端 renderer 不输出 `TOOL_REQUESTED` 事件（loop 不 emit 该 kind，仅 emit `TOOL_RESULT` 等；render.py 有对应 handler 但为 dead 分支）——工具调用计数以 `TOOL_RESULT` 为准，本任务 = 2。model-call 精确计数不冒充（renderer 不逐条输出 model_progress）。skill drift/unknown-metadata/oversize/resource-replacement 等 fault matrix 已在 E1/E2 覆盖，本 E3 只验证真实 provider 下 governed 正向路径与规则应用。驱动经 `main.main(input_fn, write_fn)` 真实入口。
