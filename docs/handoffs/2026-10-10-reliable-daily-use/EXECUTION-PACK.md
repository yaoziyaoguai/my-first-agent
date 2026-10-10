# 日用基线固化与有界可靠性收尾执行包（已验证）

日期：2026-10-10。来源：Oracle Web（第 5 档 max，滑块 Power 5/5，17m37s，
会话 `fa-next-steps-package-20261010`；原始答复 [ORACLE-PACKAGE-RAW.log](ORACLE-PACKAGE-RAW.log)）。
本文件为 Oracle 冻结合同 + 执行者交叉核对附录。交叉核对只补齐事实，不改产品目标。

## 执行者交叉核对附录（验证记录）

1. **归因事实已独立核实**：BASELINE.sha256 仅含哈希；15 个基线改动文件中 13 个
   在打包时即相对 HEAD dirty（用户未提交改动），仅 `agent/tui/adapter.py`、
   `tests/tui/test_adapter.py` 打包时干净（本轮独有）。故 MIXED_SEPARABLE 的
   B 内容对 13 个文件不可恢复——按 §4.4/§9 规则，拆分提交路径将停止；
   唯一可提交形态为用户对"混合文件整体 + 本轮新文件"的明确整文件授权，
   否则 READY_NOT_COMMITTED。执行者在 S5 授权门向用户呈报此决策。
2. **命令/路径核对**：包引用的测试文件、脚本、git 命令全部存在/有效；
   `diagnose_session_lifecycle.py` 为待建诊断脚本（接口已冻结于 §5.4）。
3. **skipped 原因核对义务**（§1.1）：执行者须在 S5 前核对全量 gate 唯一
   skip 的具体原因并记录。
4. **上轮补证增量归属**：contracts/checkpoint/loop 等 usage 持久化与
   DU-10/14/22 补证发生在打包后，属"上一轮完成后的当前内容"，纳入
   OWNERSHIP.tsv 的本轮差异（B→C 仍以打包基线为准）。

## 摘要（详细条款见 ORACLE-PACKAGE-RAW.log）

- **Goal**：已验收 Agent → 可追溯、可独立安装运行、已知故障有明确处置的日用版本。
  P0=S1 改动归属与可提交基线；P1=S2 会话生命周期有界诊断、S3 日用入口与恢复说明；
  P2=S4 Provider 边界（本轮零真实调用）；P0 收口=S5 独立候选验证与授权提交。
- **Non-goals**：无新 loop/框架/调度器/Provider adapter/自动安装/自动重试安全错误；
  冻结合同不动；不重写旧 handoff。
- **预算**：真实 API ¥0/0 次；诊断 stress 首轮 ≤100 对（600s/轮）；全量 gate ≤3 次；
  本地 commit ≤2 次（需用户明确授权，模板见包 §8.2）。
- **验收行 ND-01..ND-26** 与各切片停止条件以 ORACLE-PACKAGE-RAW.log 为准。
- **最终判定**：GO / GO_WITH_KNOWN_BOUNDARY / READY_NOT_COMMITTED /
  NO-GO（封版|日用安全）。
