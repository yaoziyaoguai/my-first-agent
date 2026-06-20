"""Skill System 类型化错误——所有 fail-closed 边界返回这些错误。

设计原则（来自 RFC/SDD）：
- 不暴露原始文件内容或路径细节到 error message（防泄露）
- 每个错误携带 code / message / path / recoverable / safe_preview
- recoverable=True 表示可安全重试（如文件缺失），False 表示结构性错误
- SkillLoadError 继承 Exception，确保可以 pytest.raises 捕获
"""
from __future__ import annotations

from pathlib import Path

# Exception 框架需要设置的特殊属性名
_EXCEPTION_FRAMEWORK_ATTRS = frozenset({
    "__traceback__", "__cause__", "__context__", "__suppress_context__",
    "__notes__", "args",
})


class SkillLoadError(Exception):
    """Skill 加载/解析/校验边界的 fail-closed 错误。

    safe_preview 是对用户安全可见的简短描述，不含路径或敏感信息。

    构造后除 Exception 框架属性外不可再修改（模拟 frozen）。
    """

    code: str
    message: str
    path: Path | None
    recoverable: bool
    safe_preview: str
    _locked: bool

    def __init__(
        self,
        code: str,
        message: str,
        path: Path | None = None,
        recoverable: bool = False,
        safe_preview: str = "",
    ):
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "recoverable", recoverable)
        object.__setattr__(self, "safe_preview", safe_preview)
        object.__setattr__(self, "_locked", True)

    def __setattr__(self, name: str, value: object) -> None:
        """构造后不可修改（Exception 框架属性除外）。"""
        if name in _EXCEPTION_FRAMEWORK_ATTRS or not hasattr(self, "_locked") or not self._locked:
            object.__setattr__(self, name, value)
        else:
            raise AttributeError(f"SkillLoadError 不可变，禁止设置 '{name}'")

    def __repr__(self) -> str:
        return (
            f"SkillLoadError(code={self.code!r}, message={self.message!r}, "
            f"recoverable={self.recoverable}, safe_preview={self.safe_preview!r})"
        )


# ---- 错误码常量 ----

# 解析阶段
CODE_PARSE_ERROR = "PARSE_ERROR"
CODE_MISSING_FRONTMATTER = "MISSING_FRONTMATTER"

# 必填字段
CODE_MISSING_NAME = "MISSING_NAME"
CODE_MISSING_DESCRIPTION = "MISSING_DESCRIPTION"
CODE_MISSING_VERSION = "MISSING_VERSION"
CODE_MISSING_STATUS = "MISSING_STATUS"

# 字段校验
CODE_INVALID_NAME = "INVALID_NAME"
CODE_INVALID_STATUS = "INVALID_STATUS"
CODE_INVALID_RISK_LEVEL = "INVALID_RISK_LEVEL"
CODE_INVALID_CONFIRMATION = "INVALID_CONFIRMATION"
CODE_INVALID_MEMORY_SCOPE = "INVALID_MEMORY_SCOPE"
CODE_INVALID_RESOURCE = "INVALID_RESOURCE"

# 重复/冲突
CODE_DUPLICATE_NAME = "DUPLICATE_NAME"

# 安全
CODE_UNSAFE_PATH = "UNSAFE_PATH"
CODE_SECRET_DETECTED = "SECRET_DETECTED"
