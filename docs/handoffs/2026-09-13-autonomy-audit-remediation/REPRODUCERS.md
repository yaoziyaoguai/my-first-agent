# Red 测试落点与反例

以下是新增回归测试的实施规格，不冒称这些测试已落盘或已通过。
现有文件/节点均在交接时核对。无需真实 Key；process 反例只用测试自己创建的资源。
先打开对应文件完整相关路径，再就近补测试；私有 helper 探针只能作定位，最终补公共 Runtime 旅程。

## C1：tests 与 lint 互相作废

- 起点：`tests/process/test_j1_verified_done.py` 的 `ProcessReceiptV1.create` 及 criterion/fact 构造；
  `agent/runtime/state.py` 不同 command fingerprint 的 mandatory criterion 保留规则。
- 用同一 Goal/revision/workspace 的两个不同命令 A/B，生成真实结构的成功 receipt。
  criterion 使用各自准确 command fingerprint，不固定单次 receipt digest，允许合法重跑。
- 顺序 A→B，分别 derive 两个 mandatory criterion。当前审计结果为 A=False、B=True。
  再追加 A 的新执行 receipt，当前为 A=True、B=False。
- Red 断言：如果两次已批准验证覆盖的相关输入未变，A/B 最终都成立，Runtime 能闭合；
  两次结果并存不是删除历史或放弃任一必需检查。
- 反面：B 确实修改相关输入时 A 必须失效。不能用模型自报 readonly 代替输入/执行事实。

## C2：写坏文件后退出 1

- 同一文件先有成功验证。随后准确批准的合成命令实际修改文件，再以 exit 1 退出。
  在真实 tool 结果中应见 executed=True、is_error=True，不能只虚构不可能的 metadata。
- 当前 evidence helper 会跳过 error fact；审计 receipt 探针中旧验证仍为 True。
- Red：旧验证失效，完成被拒；对超时/异常/unknown 的可能副作用亦保守处理。
- 对照：执行前被 policy 拒绝且确实无 effect，不因“报错”本身伪造 workspace 修改。

## C3：文件及 native sandbox 的最终版本

- 起点：`tests/continuity/test_sandbox_verified_done.py` 的 `_receipt`、`_receipt_fact`、
  `_readback_facts`、`_filesystem_criterion`、`_receipt_criterion`、`_state`、`_claim`。
- 组合原有效 read-back + sandbox receipt，追加后续成功 edit_file TOOL_RESULT；用公共
  `REGISTRY.derive` 判断。当前两个 oracle 都仍为 True（见审计记录）。
- Red：修改相关输入后，旧 filesystem/sandbox 验证不再满足最终完成。
- 再通过公共 Runtime 对合成真实文件运行读取/验证→编辑→完成声明，证明不是只修测试 helper。
  分别覆盖源码、测试、配置、依赖声明、外部并发变化与可证明无关说明变化。

## S1：启动器退出但后代还活着

- 起点：`tests/process/test_managed_web.py` 中
  `test_managed_web_supervisor_closes_service_when_parent_pipe_disappears` 和
  `test_managed_web_supervisor_enforces_lifetime_with_parent_alive`。
- 复用现有独立 session/process-group/pipe fixture。直接 child 启动同组长寿命后代后立刻退出；
  supervisor 的 lifetime 设为短但足够稳定的有界值，父 control pipe 保持打开。
- 当前审计：supervisor exit 0；过 2 秒 lifetime 后 descendant group 仍存活。
- Red：直接 child 退出触发有界整组回收，必须确认测试所属后代已退出，不只 assert supervisor exit。
- 参数化正常后代与拒绝 TERM 后代；保留父 EOF、期限、取消测试。使用 monotonic deadline，
  不靠无限 sleep。finally 只清理此 fixture 已持有并验证的 group，不按端口搜索/kill 用户程序。

## S2：压缩绕过默认持久化 cap

- 起点：`tests/kernel/test_runtime_compaction.py::test_auto_compaction_archives_then_continues_same_run`。
- 复用它的 state/store/archive/context_manager 及两次 ScriptedProvider 响应，仅把 limits 改为
  `InvocationLimits(max_model_calls=None, max_run_model_calls=1)`。
- 当前审计结果：provider.calls 长度 2，result.model_calls_used 为 1，status=completed。
- Red：一次压缩已消耗唯一额度，第二次普通 provider 不得发送；状态准确预算暂停、计数为 1。
- 补压缩失败也计数、扣账持久化失败零发送、resume/reopen 不清零、共享 child/HTTP ledger
  最后一格竞用。逻辑 run 计数与物理 transport 尝试分别断言，避免双扣或漏扣。

## S3：重开旧任务还能否正确收尾（先证实）

- 起点：`tests/process/test_managed_web.py`、`tests/continuity/test_restart_selection.py`，以及
  managed_web owner `close/_record` 与 resource_lifecycle 的 start/stop 配对。
- 合成 workspace：公开入口启动服务，保存 checkpoint → 正常退出 owner → 确认实际 OS 资源 →
  用全新 composition 重开旧任务 → 提交正常清理/完成 action。
- 记录是否永久因旧 ref 而拒绝闭合。若实际不发生，保留 PASS 反证并将 S3 标为 NOT REPRODUCED，
  不编造修复；补齐其依赖条件说明。若发生，先 Red 再最小恢复核对路径。
- 反面：旧 start 仍活、身份不可确认、PID/端口复用、checkpoint 失败时不得假成功或误杀。

## M1：当前模型 identity 的 MockTransport 反例

- 起点：`tests/provider/test_deepseek_flash.py` 的 `_config/_context/_chunk/_sse`。
- `_config(model="deepseek-flash")` 当前在 enabled thinking 下抛 ProviderConfigurationError。
- 把已通过 SSE fixture 的 model 字段统一改为 deepseek-flash，其余 chunk 保持相同，
  当前解析抛 ProviderStreamInterruptedError。先确认完整/合法 SSE，不把不完整流当 alias 问题。
- 按当日官方文档定义支持的 requested/returned identity 成对合同，加入新名正常工具回合、
  旧名明确支持/拒绝策略及其他模型不被误收的反例。禁止任何字符串都放行。
- 原有缺 usage/finish/[DONE]、多工具、reasoning 续接、取消、大小/时间限制测试不能退化。
  MockTransport 不证明服务器当前 alias 返回什么；真实 smoke 按 REAL-API 单列。
