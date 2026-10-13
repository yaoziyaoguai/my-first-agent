# Oracle 外部审计上下文（脱敏）

基线：`cbfa1e7`，工作树干净。此前审计基线为 `dee8c25` 加既有工作树；`ef9907f` 已将这些公开成果完整保存，本次没有新增产品变化。源码摘录见 CODE_CONTEXT.txt，不发送真实运行记录、用户数据或密钥。

## 独立验证到的事实

- A1 合成事实探针：`resource_gate_closed=true`、`validation_before_writer_shutdown_accepted=true`、`same_validation_still_suppressed=true`、`stop_invalidates=false`。没有真实进程，不声称该探针自身完成了真实 E3。
- A2 静态代码：已有 out 路径未经判断即 rmtree。本次未触发该危险分支。
- A3：完整 `PYTHONDONTWRITEBYTECODE=1 PIP_NO_INDEX=1 .venv/bin/python -m pytest -q -rx` → exit1，3760 passed / 1 skipped / 1 failed，587.04秒。失败 `tests/reference/test_015_e3_harness.py::test_015_offline_gate_timeout_cleans_owned_process_group`；期待超时已确认清理124，实际125 cleanup unconfirmed。单独复测1 passed/0.60秒。这是间歇现象，不是根因解决。
- A4：使用 httpx.MockTransport，thinking=disabled 发出；返回正常JSON纯文本，不含reasoning_content，生成时抛 ProviderProtocolError(reason=missing_reasoning_continuity)。零网络调用。
- ruff 全库通过；原 tracked diff check通过。首次把历史公开Markdown纳入Git后有8文件19处空白提示，其中有SHA256SUMS绑定的历史附件，保留原始字节。当前新改动应正常通过diff check，不为历史格式重写证据。
- 653/653候选manifest文件与审计开始工作树逐字节一致；23个本轮标记文件无漂移。这不是新修复后的候选身份。
- 独立导出全套暂存源码→离线构建non-editable wheel→新installed target；113个产品模块全部从该target导入，无原工作树来源。
- 独立导出快照上的 tests/cli/test_016_packaging.py → 4 passed/32.29秒。内部建独立venv，验证native entrypoint与base安装边界；不证明真实provider或真实TUI旅程。
- 开发venv Textual8.1.1低于声明>=8.2,<9；候选venv8.2.8。Python3.12.2/macOS。上述全量是开发环境，不是声明环境全量证明。

## 原执行者报告（本次未重跑真实API/浏览器）

- 正例run2产品自报终态，7/7 required evidence；独立grader的latest_correction/final_validation为true，自写14项测试外部复跑通过，sentinel未变。
- 负例必要写入被拒，files_changed=[]，没有VERIFIED_DONE，回显declined；长预算反例也保持。
- PAUSE→新进程恢复未重述任务和纠正；“14个effect没有重放”的论据是tool_call_id全唯一。这个论据不足，需要重新设计过程证明，但不能据此断言真的发生了重放。
- 本地真实浏览器f2/d06报告passed/target_checks/cleanup全true，exit0。保留这层历史事实，不推导所有网站/系统都支持。
- 3679 passed/5 skipped 的候选批次从候选源码目录导入并排除acceptance，并非全部installed验证。
- 曾出现另一个POSIX supervisor测试失败（3次focused重跑通过）以及managed-web ProcessLookupError；原因未定位。不能只凭“本轮未改”认定与当前候选无关。

## 产品/权限/成本

不新建通用平台、不默认开后台常驻、不改macOS登录项、不触碰个人浏览器。保留policy、approval、EXECUTING/result checkpoint、UNKNOWN不自动重试、精确资源owner。

本次只生成资料包。未来收到执行授权的agent可做包内本地公开fixture与临时专属loopback server验证；真实API、凭据读取、旧私人会话访问和远端Git需单独、当前有效授权。历史文档里的“费用无限”不能继承。

旧真实正例12次审批+18次外发确认提示体验负担，但没有逐项必要性数据。不应本轮直接删除确认或设计全新的授权体验。
