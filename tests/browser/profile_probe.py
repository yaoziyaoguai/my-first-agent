"""浏览器 profile 测试使用注入的确定性进程身份。"""

from __future__ import annotations

from agent.browser.profile_store import ProcessIdentity


class DeterministicProcessIdentityProbe:
    """避免单元测试依赖宿主是否允许读取进程表。"""

    def probe(self, pid: int) -> ProcessIdentity:
        return ProcessIdentity(exists=True, started_at=f"test-process:{pid}")
