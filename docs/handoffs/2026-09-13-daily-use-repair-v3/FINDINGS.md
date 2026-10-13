# 事实、根因与范围

审计依据：`docs/audits/2026-09-13-daily-usability-followup.md`。以下保留足够事实，不要求接手者阅读全部历史资料。

| ID | 已确认事实 | 对普通用户的影响 | 处理 |
|---|---|---|---|
| U1 | `DEFAULT_PRIVATE_ROOTS` 包含 config、pytest.ini 等普通名字；合成无秘密内容也被拒绝 | 读项目配置、找测试入口时拿不到必要文件 | D1 必修 |
| U2 | write_file 对缺失父目录返回 workspace_parent_missing，没有创建目录 | 普通保存报告任务需要手工准备目录 | D2 必修 |
| U3 | 17 个无 Goal conversation 只有前 16 个可见，界面没有下一页；未显示 candidate 无法被选择 | 数据未丢失，但部分会话不能恢复 | D3 必修 |
| U4 | 同一 endpoint 仅 model-a 改成 model-b，空 owner preference store 也因 trust mismatch 被拒绝 | 整个启动失败，提示换 state root 导致历史不便继续使用 | D4 必修 |
| U5 | 上轮真实只读任务申请额外写文件；精确命令任务 58 次请求后未执行 | 有围栏但普通任务不能稳定交付 | D0 控成本；D5 先复验后按证据修 |

U1–U4 已在当前源码上离线合成复现。U5 的真实失败发生在上轮提示词及 8-call 补救之前；最终候选未复验，不能先假定新版本仍失败，也不能先假定已修好。新测试应验证行为，不是检查 prompt 包含几个字符串。

## 源码导航

- 文件可见性：`agent/tools/file_ops.py::DEFAULT_PRIVATE_ROOTS`、`build_file_tool_registrations`；`agent/tools/path_safety.py::WorkspaceBoundary`、`_is_sensitive`；`main.py` 的文件工具 composition。
- 文件 effect：`agent/tools/write.py::prepare_write_binding`、`write_file`；`WorkspaceBoundary.inspect_mutation/atomic_replace`；`agent/runtime/tools.py` 的 binding 二次验证、approval 和 invoke。
- 会话：`agent/continuity/sessions.py::open_workspace_session`、`_open_workspace_session_locked`、`select_workspace_candidate`；`main.py` 的 SELECT_REQUIRED 分支。
- 模型切换：`main.py` 的 owner preference 装配；`agent/composition.py::build_owner_preference_resources`；`agent/memory/preferences.py`；`ProviderDescriptor.identity_digest` 包含 model。
- 请求计数：`agent/transport_audit.py::TransportAttemptLedger.record`；两个 HTTP adapter 的 attempt_recorder；`main.py::_build_provider`、`agent/runtime/loop.py::_drive`。
- 任务路由：`main.py::EVERYDAY_SYSTEM_POLICY`、`agent/runtime/context.py`、`agent/provider/normalize.py`；测试优先读 `tests/continuity/test_entry_routing.py`、`tests/reference/test_016_first_agent_1_0.py`、`tests/process/test_j1_production_verified_done.py`。

## 已有证据

- 上轮最终 source：3449 passed，3 skipped；Ruff/diff check PASS。不是本包新实现的通过证据。
- 本轮准备前探针：U1 公共 config/app.yaml 与 pytest.ini 被拒绝，normal.txt 可读；U2 reports/daily.md 失败且 reports 不存在；U3 stored=17/visible=16，第 17 项选择 exit 2；U4 空偏好库换 model 被拒绝；真实网络请求 0。
- 三个定向测试 3 passed，证明当前限制与 8-call 暂停机制确实存在，不代表这些产品缺口被修复。
- 上轮新 key 曾通过 G1 服务端认证；key 值不在本包。G1、拒绝写入、stale 写入修复有成功真实记录，全部只绑定当时候选。

## 暂不扩大的事项

完整 Scheduler host、GLM wire 兼容、DeepSeek 流式响应、无凭据下取消/unknown recovery、256 条历史的归档管理、减少 disclosure 次数、跨平台和 capability promotion 本轮 deferred。保留准确说明，不把这些一起扩成新平台。

Skill/MCP/Memory/SubAgent 代码有离线修复证据，最终真实任务仍未证明。本轮 D5 先完成核心日常任务；扩展只在剩余预算及准确依赖齐备时做补证，结果单列，不为“ready”贴 PASS。
