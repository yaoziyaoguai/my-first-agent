"""017 native backend qualification（macOS Seatbelt，只读 fail closed）。

一次 bounded functional probe：``sandbox-exec -p <minimal profile>
/usr/bin/true``。不执行用户命令、不安装/启动/登录任何服务、不降级。closed
reasons 冻结于 ``agent.sandbox.contracts.SANDBOX_QUALIFICATION_REASONS``。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

# minimal probe profile 与真实 profile 同方言（version/allow-default/deny
# network）：既验证 backend 存活，也验证 compiler 依赖的最小子句可编译。
MINIMAL_PROBE_PROFILE = "(version 1)\n(allow default)\n(deny network*)\n"
PROBE_TIMEOUT_SECONDS = 5.0
PROBE_OUTPUT_CAP_BYTES = 16_384
PROBE_TARGET = "/usr/bin/true"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """bounded probe 结果：returncode（None=timeout）、截断前输出。"""

    returncode: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool


class SeatbeltCommandRunner:
    """production probe runner：argument-vector、bounded 输出、timeout kill。"""

    def run(
        self,
        argv,
        *,
        cwd=None,
        env=None,
        timeout: float = PROBE_TIMEOUT_SECONDS,
    ) -> ProbeResult:  # noqa: ANN001, ANN202
        try:
            process = subprocess.Popen(  # noqa: S603 - argv 是内部构造的 exact vector
                [str(item) for item in argv],
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError:
            return ProbeResult(None, b"", b"", timed_out=False)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            return ProbeResult(None, b"", b"", timed_out=True)
        return ProbeResult(process.returncode, stdout, stderr, False)
