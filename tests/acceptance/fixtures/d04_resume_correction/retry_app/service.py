from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class RetryService:
    def run(self, operation: Callable[[], T], *, max_retries: int = 0) -> T:
        return operation()
