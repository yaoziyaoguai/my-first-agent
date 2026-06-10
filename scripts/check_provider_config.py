#!/usr/bin/env python3
"""Provider 配置诊断脚本（provider auth/config diagnostics）。

这个脚本做静态 provider 配置诊断——检查环境变量中 provider 的类型、模型、
API key 存在性（只输出 yes/no，不输出值），识别配置问题并给出可执行建议。

设计原则：
- 不读取 .env 文件内容：只检查进程环境变量中已有的 provider 相关变量
- 不打印 secret：API key 只输出 SET/not set，不输出开头或长度
- 不调用真实 API：所有诊断都是静态推断
- 不尝试连接真实 provider：连接性验证留待用户显式 real-provider validation

为什么需要这个脚本：
- 真实 provider validation 曾出现 401 config/auth concern
- local trial 的第一步就是确认 provider 配置状态
- 用户需要比 ProviderConfigurationError 更具体的诊断信息
- 这是 startup readiness 的补充——先确保能启动，再诊断 provider 配置

为什么不读取真实 .env：
- .env 可能包含真实 secret，AutoRun 严格不触碰
- 静态诊断不需要 .env 内容即可识别大部分配置问题
- 用户可以在显式 real-provider validation 阶段自行加载 .env 后运行本脚本验证
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    from agent.provider.diagnostics import diagnose_provider_config, render_diagnostic_report

    diagnostic = diagnose_provider_config()
    print(render_diagnostic_report(diagnostic))

    if diagnostic.status == "error":
        return 2
    if diagnostic.status == "warn":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
