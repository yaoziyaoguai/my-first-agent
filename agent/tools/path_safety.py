"""FileMutation 工具共享的 project-root safety seam。

这个模块只承载“路径是否仍在项目根内”的判断和拒绝文案，供 write_file /
edit_file 复用。它不执行文件 IO、不做 runtime confirmation、不接 checkpoint，
也不读取敏感文件内容；因此不是新的 path policy 巨石，而是避免多个 mutation
工具复制 project-root 判断的最小共享边界。
"""

from pathlib import Path

from config import PROJECT_DIR


def is_path_inside_project(path: str) -> bool:
    """判断文件 mutation 路径是否仍在项目根目录内。

    这是 FileMutation 工具共享的 path-safety seam：write_file 和 edit_file 都会
    修改本地文件，因此必须复用同一个项目根判断，不能各自复制一份安全逻辑。
    该 helper 只回答路径边界问题，不负责 runtime confirmation、checkpoint、
    linter 或具体工具 IO，从而避免把工具 safety 做成新的巨石。
    """

    try:
        resolved = Path(path).expanduser().resolve(strict=False)
        return resolved.is_relative_to(PROJECT_DIR)
    except Exception:
        return False


def project_boundary_rejection(path: str, *, action: str, manual_action: str) -> str:
    """生成项目外 mutation 的统一拒绝文案。

    拒绝文案集中在 path-safety seam，保证 edit_file 修复 project-root parity 时
    不复制 write_file 的安全判断；同时仍让具体工具传入自己的动作描述，避免把
    tool-specific UX 全部塞进共享 helper。
    """

    return (
        f"拒绝执行：'{path}' 在项目目录之外，v0.2 RC 默认禁止 Agent "
        f"{action}。如需{manual_action}，请由用户手动操作。"
    )
