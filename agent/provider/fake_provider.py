"""不做 NLU 的确定性 Kernel Provider substitute。"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from agent.provider.normalize import latest_user_text, validate_context_pack
from agent.provider.protocol import ProviderProtocolError
from agent.runtime.contracts import ContextPack, ModelResponse, ModelTextBlock
from agent.subagent.contracts import ProviderDeadlineCapability


class FakeProvider:
    """返回显式脚本；未配置脚本时原样 echo 最近一条 user 文本。

    FakeProvider 是同步、立即返回的 provider substitute，因此它结构化声明
    synchronous deadline + terminated receipt，满足 SubAgent v1 的 hard-deadline 合同。
    """

    deadline_contract = ProviderDeadlineCapability(
        hard_deadline_seconds=30.0,
        receipt_type="synchronous",
    )

    def __init__(
        self,
        *,
        scripted_responses: Iterable[ModelResponse | Exception] | None = None,
    ) -> None:
        self._scripted = scripted_responses is not None
        self._responses = deque(scripted_responses or ())

    def generate(self, context: ContextPack) -> ModelResponse:
        validate_context_pack(context)
        if not self._scripted:
            return ModelResponse((ModelTextBlock(latest_user_text(context)),))
        if not self._responses:
            raise ProviderProtocolError("provider_script_exhausted")
        response = self._responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response


__all__ = ["FakeProvider"]
