# 验收与停止标准

本文件只验收 F1–F4/L1，不恢复旧资料包的全部 D/R 或 promotion 任务。
执行结果逐行登记到 [RESULTS.md](RESULTS.md)，标明真实 node/命令、退出码、代码身份、环境和证据路径。

## 1. 必须新增或加强的行为证据

| ID | 必须证明 | 失败/未测时 |
|---|---|---|
| A01 | 验证读回 A 后，真实成功 process 写成 B，旧 A 不能支持完成 | F1 未完成 |
| A02 | 成功过程验证之后，成功 process 改其验证输入，旧过程验证失效 | F1 未完成 |
| A03 | 同一可信输入上的 tests/lint 两项 mandatory 验证可在有限步内共同完成；不能互相永久作废 | F1 未完成 |
| A04 | prepare/policy 拒绝不执行不误伤证据；executed failure/timeout/unknown 不被当无副作用；sandbox 原边界保留 | F1 未完成 |
| A05 | fake-production 工具路径：open→正常 CLEANED shutdown/持久化→全新 owner→原 ref close→资源门槛解除 | F2 未完成；不能只测 helper |
| A06 | unknown/缺失/损坏/错误 session/workspace/browser identity 的清理记录不能签 cleaned | F2 未完成 |
| A07 | 重复 close 幂等；无重新 open；site profile writer 正确释放；其他 unknown effect 不被清除 | F2 未完成 |
| A08 | 专属真实 Chromium + 本地夹具的正常退出/重启收尾；无真实 provider | 若受环境阻塞，F2 真实环境项明确未验证 |
| A09 | 模型文本含 Task is closed 或真实 CANCELLED 均不能被 driver 判 completed | F3 未完成 |
| A10 | 只有审批/被拒/未执行/失败执行不算产品已跑测试或已操作浏览器 | F3 未完成 |
| A11 | 成功但无关的 local_process 不算相关测试；grader 自跑不能算产品自测；其他任务旧 receipt 不可复用 | F3 未完成 |
| A12 | D06 server/page 故障且候选测试空通过仍失败；删除/篡改 candidate 测试不能改变独立断言 | F3 未完成 |
| A13 | D06 正确 reference 页面在真实本地浏览器提交后列表更新，保留原行为；产品证据/独立检查分别记录 | 若没有真实 browser 证据不能签该项 PASS |
| A14 | 缺 cleanup 证据或 UNKNOWN 时资源项不通过；精确 start/open/action/close 正向可通过 | F3 未完成 |
| A15 | D04/D05 最终业务正确但过程未观测时，保留 required_checks 并标未证明，完整场景不 PASS | F3 未完成；不扩建新旅程 |
| A16 | 当前 producer→validator round-trip 成功；缺字段/错 manifest/错身份准确失败；RECORD_VALID 不变成产品 PASS | F3 未完成 |
| A17 | real dispatch=false、零预算或配置不匹配时，在 provider 发送前拒绝，spy transport 0 calls | F3 未完成；不得为通过而开启真实权限 |
| A18 | 容量 2 下至少 12 次 distinct terminal create/archive 后仍可继续，早期 archive 可恢复且 digest 保持 | F4 未完成 |
| A19 | 真活跃 checkpoint 满额仍拒绝；stale archive/CAS、异常 symlink/mode/owner/nlink 仍 fail closed | F4 未完成 |
| A20 | 与锁处置相关的多进程竞争无 split-lock，持有者/等待者/恢复不会同时获得矛盾修改权 | F4 未完成；用 barrier/pipe 不用定时猜测 |
| A21 | 现有资源/输入界限保留，长循环不靠提高/删除 bound 伪装修复 | F1/F4 相应项未完成 |
| A22 | 调度、平台、真实 Dogfood、安装态声明与证据一致；未自动 promotion/注册登录项 | L1 未完成 |

## 2. 推荐执行命令

从仓库根执行。先按新测试 node 跑 Red/Green，再运行对应组。
这些是本地测试，不是批准运行脚本中的真实 provider 路径。

### F1 focused

```bash
.venv/bin/python -m pytest -q -rx tests/process/test_j1_verified_done.py tests/continuity/test_verified_done.py tests/continuity/test_sandbox_verified_done.py tests/process/test_artifact_approval_contract.py
```

### F2 focused

```bash
.venv/bin/python -m pytest -q -rx tests/browser/test_tools.py tests/browser/test_composition.py tests/continuity/test_verified_done.py tests/process/test_managed_web.py
```

### F3 focused

```bash
.venv/bin/python -m pytest -q -rx tests/acceptance/test_real_coding_scenario_runner.py tests/acceptance/test_coding_autonomy_grader.py tests/cli/test_render.py
```

### F4 focused

```bash
.venv/bin/python -m pytest -q -rx tests/continuity/test_session_retirement.py tests/continuity/test_state_root.py tests/continuity/test_restart_selection.py tests/continuity/test_checkpoint_v4.py
```

相关新测试若放到新增文件，必须把路径补入 RESULTS 的实际执行命令。不能只跑上述旧文件然后声称覆盖新增反例。

### 最终 gate（集成稳定后一次）

```bash
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
```

如需单独确认架构：`.venv/bin/python -m pytest -q tests/architecture`。
最终全量失败时定位原因，修复本轮导致的问题；只重跑受影响部分，必要时再做一次收尾全量，不能每个小改都全量重跑。
新增脚本不得在 pytest import/collection 期间发送 provider 请求。

## 3. 真实本地浏览器验证：有界、无付费 API

- 沿用既有 Playwright 版本和已安装专属 Chromium；缺依赖先报告，不自动升级/下载。
- 临时 workspace/state/profile，本地 loopback/TLS fixture，无个人浏览器/登录账户/外部网页。
- 两条最小旅程即可：F2 正常关闭重启补记；F3 D06 真实提交/读回/清理。
- 通过现有治理工具路径取得产品 receipt；外置浏览器 grader 只作独立业务断言，不代替产品行为。
- 每条旅程建议 120 秒上限，至多一次有新诊断依据的重试；写首次失败。进程/浏览器在 finally 清理，清理失败不能算通过。
- helper `scripts/browser_e3_fixture.py` / `browser_e3_journeys.py::RealBrowserFlow` 仅作复用入口，不要求执行整个旧 E3 suite。
- 在本轮新增可重复测试 node/窄驱动，记录准确命令。不要复制 018/019 的旧 seals 来绕过当前 identity drift。

## 4. 安装态 smoke 的限定范围

本包的安装核验只证明本轮改动被包含在一个非 editable wheel 里，**不重新开启 016–019 promotion**。

1. 用明确公开的产品/构建文件 allowlist，在临时 staging 中构建当前候选 wheel；不得整仓 `cp -R`、摄入 ignored/private/tui。
2. 重用现有本地构建依赖，不联网下载、不改全局环境；依赖缺失则记 BLOCKED_ENV。
3. 在新建 venv 安装该 wheel。基础库可来自明确核对的本地缓存；清空源码 PYTHONPATH，从仓库外 cwd 启动。
4. 输出 `agent.__file__`、`main.__file__`、distribution 版本与 wheel SHA-256，证明产品模块位于该 venv/site-packages，不是源树。
5. 运行 `first-agent --version`/`--help` 及本包改动的最小无 provider smoke；测试辅助代码可在临时外置目录，但产品 import 不得落回源树。
6. 对缺 browser extras 的安装如实记不可测；不自动引入另一种浏览器或 fallback。

先检查可复用的已有 materialized/wheel 辅助函数；不要直接执行会更改 seals/attestation 的历史完整验收命令。
记录实际构建/安装命令；本包不预设一个未核实的环境通用命令。若窄 smoke 需要重写打包系统才可行，停止该项并说明，不扩大实现范围。

## 5. 真实模型 Dogfood：另行批准，不是本轮自动动作

本包没有携带 key，也没有授予读取凭据或付费请求的权限。
实现与本地验证可以先完成；真实模型记录必须写 `NOT RUN — 本包未授权`，不因此开始寻找旧 key。

若用户随后另行批准，建议仅选 D01、D02、D06 三个既有场景，先单场样本；由用户确认模型、请求上限、总时间/费用、凭据注入来源后再运行。
同一候选记录 source/wheel/fixture/grader/manifest 身份；使用修复后的 driver，保留首次失败、审批次数、外部 grader 次数和三类业务救场。
此建议不是授权，也不强制补 D04/D05 的过程旅程、D07–D12 或 R01–R03。

## 6. 结果分级与结束

- `IMPLEMENTED_LOCAL_VERIFIED`：A01–A22 与 required local/full/wheel checks 均满足；包含适用的真实本地 browser，不代表真实模型全通过。
- `IMPLEMENTED_PARTIAL_VERIFICATION`：实现已做，但 host/browser/wheel 等 required check 未完成；逐项列原因，不能统称 PASS。
- `IN_PROGRESS`：尚有本轮代码问题或新反例未关闭。
- `BLOCKED`：具体必要外部条件缺失或必须用户决定的边界，写可解除条件；不要把难做/测试慢当外部阻塞。

付费 Dogfood 未授权不阻止本包达到 LOCAL_VERIFIED，但最终必须单列 NOT RUN。
当前 capability promotion 保持 candidate，历史成绩不重写，不以本包完成取代全部产品验收。
交付后停止，不自动开启下一轮。
