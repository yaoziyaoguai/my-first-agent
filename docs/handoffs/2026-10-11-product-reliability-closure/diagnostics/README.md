# 历史合成反例附件

这三份 `.py.txt` 是独立审计探针的公开副本，供接手者理解修前失败。它们不是产品代码、固定成功 oracle，也不会被 pytest 自动发现。

运行方式和限制见上级 [VALIDATION.md](../VALIDATION.md) §1。必须从仓库根目录运行；runtime 可用 `--repo` 显式指定。没有真实 Key/用户数据；driver 只管理本次创建的短期子进程。

修复后优先把反例转成现有测试目录里的正常 regression tests。内部接口改变造成探针报错并不证明产品坏或已修好；应保持等价行为检查，而不是修改历史结论让输出好看。

不要用本目录的 PYTHONPATH 设置做安装物验证。不要把诊断 exit 0 等同产品 PASS。

## 2026-10-12 收口复核反例

`postclosure_probe.py.txt` 是新增独立反例，不修改前三份历史探针：检查 start→验证→可能继续写入→stop 的旧验证信任，以及显式 disabled 的离线 provider 响应。无真实 API、无真实服务，不是 E3。

从仓库根运行：

```bash
PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 .venv/bin/python docs/handoffs/2026-10-11-product-reliability-closure/diagnostics/postclosure_probe.py.txt
```

审计时第一条输出的旧验证接受/同参抑制为 true，stop_invalidates 为 false；第二条抛 `missing_reasoning_continuity`。修复后应以正式回归覆盖对应行为，不保持缺陷输出为“成功条件”。
