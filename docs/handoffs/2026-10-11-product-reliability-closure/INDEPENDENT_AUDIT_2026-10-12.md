# 日用可靠性收口：独立复核

## 结论与范围

**不能确认“全部完成”。已有大量修复和真实使用证据值得保留，但本候选尚未通过最终验收。**

本次用户请求是审计、确定下一步、整理仓库并归入 main，不是启动新能力开发。审计没有修改产品实现，没有调用真实 API，没有读取凭据、私人会话或根 `tui/` 文件内容，也没有改动系统登录项。唯一当前进度仍是 [RESULTS.md](RESULTS.md)。

基线：`main` / HEAD `dee8c25e550cfa957307c1eaadc4ac20a7b9a8d7`。开始时 139 个 tracked 文件有修改；另有未跟踪的必要产品模块、测试和多轮交付文档，因此不能只提交报告里提到的 23 个文件。它们属于既有用户工作，不全部归功于本轮执行者。

## 必须处理的问题

### A1 / P1：RC-02 仍可接受服务存活期的旧验证

- 定位：`agent/runtime/evidence.py::_may_invalidate_workspace_validation`、`WRITABLE_PROCESS_TOOLS`；`agent/runtime/loop.py::_successful_product_request_inventory`；`agent/runtime/resource_lifecycle.py::active_task_resources`。
- 当前只在 `managed_web_start` 结果处失效旧验证。若顺序为 **start → 验证 A → 服务继续写入 → stop（清理确认）**，stop 不失效 A；资源关闭门通过后，旧 A 仍可被证据 oracle 接受，同参验证仍被去重抑制。
- 独立合成生产格式探针得到：`resource_gate_closed=true`、`validation_before_writer_shutdown_accepted=true`、`same_validation_still_suppressed=true`、`stop_invalidates=false`。探针没有启动真实服务，不冒充真实 E3。
- 可重现探针与命令：[diagnostics/README.md](diagnostics/README.md) 中的 `postclosure_probe.py.txt`。
- 新增真实 server 测试 `test_real_managed_web_start_result_from_tool_runtime_invalidates_validation` 实际覆盖的是“先验证、再 start”，没有覆盖合同 [WORK_ITEMS.md](WORK_ITEMS.md) RC-02 第 3 条要求的“start 后验证、继续写入、再 stop”。因此测试通过不足以关闭该项。
- 最小修复验收：上述时序中的旧 A 被拒、显式同参重验可执行且可用于完成；stop 失败/结果不确定仍不能解除资源门。用生产 ToolRuntime 结果和事件/屏障驱动真实短期 fixture server，再保留正常只读 A/B 组合的回归。不加新守护进程、第二套 loop 或通用事件框架。

### A2 / P1：新候选构建工具无条件删除已有输出目录

- 定位：`scripts/build_candidate_manifest.py::main`，`out.exists()` 后直接 `shutil.rmtree(out)`。
- 未先验证目录所有权，未拒绝仓库本身/其祖先，也不要求新目录。误传已有工作目录会在构建前删除它。这是交付工具缺陷，不是运行时 Agent 的任意删除漏洞。
- 本次只做源码审查，没有对真实已有目录运行这个危险分支。
- 最小修复验收：默认只接受不存在的输出路径，已有路径无修改地失败；拒绝仓库/祖先/符号链接与 manifest 覆盖冲突。用独立临时 fixture 的 sentinel 证明失败后字节不变。不得通过增加一个默认开启的 `--force` 或通用清理框架来规避。
- 在修好之前不要直接复用该脚本重建已有候选；也不要盲目运行 `.local/q3/clean_candidate_build.py`。优先建立全新、明确归属本次任务的输出目录。

### A3 / P1 验收阻塞：独立全量有进程清理失败

本次完整运行：

```text
PYTHONDONTWRITEBYTECODE=1 PIP_NO_INDEX=1 .venv/bin/python -m pytest -q -rx
1 failed, 3760 passed, 1 skipped in 587.04s
exit 1
```

失败节点：`tests/reference/test_015_e3_harness.py::test_015_offline_gate_timeout_cleans_owned_process_group`。期望超时且清理确认 `124`，实际 `125`，stderr 为 `cleanup unconfirmed`。

单独复测一次：`1 passed in 0.60s`。这说明失败不是每次出现，不说明根因解决。它也不是执行者报告中 `test_posix_supervisor_cleanup.py` 的同一测试，不能合并抹去。当前整个待提交差异包含 `scripts/run_015_e3.py::_run` 和此测试的改动；没有证据把它排除为与候选无关。

下一步先区分“实际进程残留”“系统仍保留 group 身份”“测试等待窗口不足”，保留 fail-closed 语义；不能仅将断言放宽为允许 `125`、延长任意等待或重跑到绿。定位后做 focused 验证，最终候选再跑一次必需全量。

### A4 / P2：显式关闭 DeepSeek 思考模式必报连续性错误

- 定位：`agent/provider/openai_http.py::OpenAICompatibleProvider.generate`。`deepseek_family_reasoning` 没有排除显式 `thinking_mode='disabled'`，仍设置 `reasoning_expected=True`。
- 独立 `httpx.MockTransport` 复现：请求确实发送 `thinking={type: disabled}`；返回正常纯文本、无 `reasoning_content` 后抛 `ProviderProtocolError: missing_reasoning_continuity`。零网络请求、无真实凭据。
- 这是原执行者已披露的范围外缺陷，不应算成原 13 项修复失败。下一步建议纳入一个最小 provider 修复：区分未指定、enabled、disabled；保留 enabled 的连续性约束，不能全局删除检查。无需新增模型档案或改预算上限。

## 证据需要降级或补齐的地方

1. **候选身份已核实。** 653/653 manifest 文件在候选和审计开始时工作树的 SHA-256 均匹配，没有丢失、路径越界或符号链接；23 个本轮标记文件无漂移。这不等于原 HEAD 自包含，也不等于验收通过。后续代码改变后必须重建身份，不能继续借用该数字。
2. **源码测试与安装测试分开。** 执行者明确记录 `3679 passed` 的产品导入来自 `.local/candidate/`，并排除了 `tests/acceptance`。保留为“候选源码态回归”；已安装 `--help`、离线任务、TUI smoke 等另列。已有 installed import guard 可复用，不新建另一套测试框架。最终 Git 快照要从中立目录确认安装入口及必要闭包，防止依赖工作树。
3. **零重放证据不足。** `tool_call_id` 唯一并不能排除相同副作用被新的调用 ID 再执行。应在暂停前后关联 durable intent、调用内容/幂等标识与执行 receipt，最好使用 fixture 的可观察副作用计数。当前仅降级证据强度，没有断言已发生重放，也不需要因此盲目重跑付费任务。
4. **真实使用证据未推翻，也未独立重演。** 正例终态 7/7、负例拒绝、恢复、浏览器 f2/d06 PASS 保留为执行者报告。普通源码测试或本次离线探针不能冒充这些真实结果；不能据两个旅程外推所有网站、平台和模型。
5. **历史 flaky 保留。** 原报告的 POSIX supervisor 和 managed-web 时序失败尚无根因。本次并未证明它们已修复；“本轮没有改那片代码”本身不是原因证据。

## 本次独立检查

| 检查 | 结果与限制 |
| --- | --- |
| `git diff --check` | 审计开始时 tracked 差异通过。首次暂存历史未跟踪文档后，全量 staged 检查发现 8 份历史 Markdown 中 19 处行尾/末尾空白，exit 2；其中原始 evidence 有 SHA256SUMS 绑定，保留原始字节，不为了变绿改写历史证据。源码/测试/脚本的 staged 检查通过 |
| `.venv/bin/ruff check .` | 审计开始和文档整理后均 All checks passed；未修改产品代码 |
| 全量 pytest | 3760 passed / 1 skipped / 1 failed，exit 1；不合格 |
| 失败节点单独复测 | 1 passed / 0.60 秒；不覆盖完整失败结论 |
| RC-02 时序探针 | 复现漏修；合成事实层，不是真实服务器 E3 |
| DeepSeek disabled 离线响应 | 复现 `missing_reasoning_continuity`；MockTransport，零 API 消耗 |
| manifest | 653/653 匹配；只证明审计开始时文件身份 |
| 暂存快照独立构建 | `git checkout-index` 导出到全新临时目录，离线 non-editable wheel 构建与独立 target 安装成功；wheel SHA-256 `233f2bcbff83637756f543616d0d2b7ae21a737951eaf3348ea5fcae029e63d6` |
| 安装来源检查 | 中立 cwd + isolated Python 进程导入 113 个产品模块，全部来自新的 installed target；包含 main、composition、五个必要新模块中的直接运行入口与 TUI。此检查借用原候选 venv 的第三方依赖，不冒称全新依赖安装矩阵 |
| 导出快照的原生安装回归 | 声明范围内 Textual 的 candidate-venv 运行 `tests/cli/test_016_packaging.py`：4 passed，32.29 秒，exit 0；该测试内部建立无 system-site-packages 的新 venv，验证原生 wrapper/基础离线启动/额外依赖不可用边界。非付费 provider 或真实 TUI 产品旅程 |

开发环境为 Python 3.12.2 / Textual 8.1.1；后者低于项目声明的 `>=8.2,<9`。原执行者候选环境记录为 Textual 8.2.8。这次全量是开发工作树验证，不能冒称声明依赖环境的全部验证。

## 下一步冻结范围

只做 A1、A2、A3，以及用户批准后的 A4；修正证据措辞并补必要安装/零重放证明。不加 Memory、MCP、SubAgent、跨平台 sandbox 或后台调度能力；不按文件行数重构；不修改 frozen grader；不降低清理/终态判据。

顺序：保存完整现有成果 → 最小修复及各自回归 → 一次最终全量与安装入口验证 → 对剩余真实证据按授权补齐 → 独立复核。修复前不将候选晋级为 accepted/delivered。

## Git 整理原则

- 用户本轮已授权本地提交并归入 main。本次成果已经位于 main 的工作树，保存采用一个完整依赖闭包的候选快照，不为此虚构 merge；不自动合入无关历史分支，不重写历史、不 reset、不 stash、不打发布 tag。
- 公开源码、必要未跟踪模块、测试、工具和交付文档一起保存；不把 23 个文件当作全部依赖。
- 私人根 `tui/agent_log.jsonl` 和 `tui/memory/checkpoint.json` 只从 Git 文件名元数据识别，内容未读。保留原位，以精确 `.gitignore` 路径排除；不删除、搬迁或纳入提交。`.local/` 候选和真实试验材料继续留在本地，不提交。
- 本地提交不是最终验收通过；当前没有 push/publish 授权，不能把缓存的 `origin/main` 当成已同步远端的证明。

构建与安装检查材料留在 `/private/tmp/first-agent-delivery-audit-20261012.be9P3w`，不纳入产品提交。报告和精确忽略规则以外，本次没有修改任何既有产品、测试或历史证据正文。
