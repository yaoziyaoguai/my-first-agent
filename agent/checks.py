import subprocess
from pathlib import Path
from config import PROJECT_DIR
from agent.logger import log_event


def run_linter(file_path):
    """对写入的 .py 文件自动运行 ruff 检查"""
    path = Path(file_path)
    
    if path.suffix.lower() != ".py":
        return None  # 非 Python 文件不检查
    
    try:
        result = subprocess.run(
            ["ruff", "check", str(path)],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(PROJECT_DIR),
        )
        
        if result.returncode == 0:
            log_event("linter_passed", {"file": str(path)})
            return "[Linter] ruff 检查通过，未发现问题。"
        else:
            output = result.stdout.strip()
            if len(output) > 2000:
                output = output[:2000] + "\n...(已截断)"
            log_event("linter_issues", {"file": str(path), "output": output})
            return f"[Linter] ruff 发现以下问题，请修复：\n{output}"
            
    except FileNotFoundError:
        return "[Linter] ruff 未安装，跳过检查。"
    except subprocess.TimeoutExpired:
        return "[Linter] ruff 检查超时，跳过。"
    except Exception as e:
        return f"[Linter] 检查失败：{e}"
