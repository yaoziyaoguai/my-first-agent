import subprocess
from config import PROJECT_DIR
from agent.logger import log_event


def check_workspace_lint():
    """检查 workspace 下所有 Python 文件的 lint 状态"""
    workspace = PROJECT_DIR / "workspace"
    if not workspace.exists():
        return {"status": "skip", "reason": "workspace 目录不存在"}
    
    py_files = list(workspace.glob("**/*.py"))
    if not py_files:
        return {"status": "skip", "reason": "无 Python 文件"}
    
    try:
        result = subprocess.run(
            ["ruff", "check"] + [str(f) for f in py_files],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return {"status": "pass", "file_count": len(py_files)}
        else:
            return {"status": "warn", "file_count": len(py_files), "issues": result.stdout.strip()}
    except Exception as e:
        return {"status": "error", "reason": str(e)}


def check_backup_accumulation():
    """检查 .bak 备份文件是否堆积过多"""
    bak_files = list(PROJECT_DIR.rglob("*.bak"))
    if len(bak_files) > 10:
        return {
            "status": "warn",
            "count": len(bak_files),
            "message": f"发现 {len(bak_files)} 个备份文件，建议清理",
            "files": [str(f) for f in bak_files[:20]],
        }
    return {"status": "pass", "count": len(bak_files)}


def check_log_size():
    """检查日志文件大小"""
    log_file = PROJECT_DIR / "agent_log.jsonl"
    if not log_file.exists():
        return {"status": "pass", "size": 0}
    
    size_mb = log_file.stat().st_size / (1024 * 1024)
    if size_mb > 10:
        return {
            "status": "warn",
            "size_mb": round(size_mb, 2),
            "message": f"日志文件已达 {round(size_mb, 2)} MB，建议归档或清理",
        }
    return {"status": "pass", "size_mb": round(size_mb, 2)}


def check_session_accumulation():
    """检查 session 快照是否堆积"""
    session_dir = PROJECT_DIR / "sessions"
    if not session_dir.exists():
        return {"status": "pass", "count": 0}
    
    sessions = list(session_dir.glob("*.json"))
    if len(sessions) > 50:
        return {
            "status": "warn",
            "count": len(sessions),
            "message": f"发现 {len(sessions)} 个 session 快照，建议归档",
        }
    return {"status": "pass", "count": len(sessions)}


def run_health_check():
    """运行所有健康检查"""
    checks = {
        "workspace_lint": check_workspace_lint,
        "backup_accumulation": check_backup_accumulation,
        "log_size": check_log_size,
        "session_accumulation": check_session_accumulation,
    }
    
    results = {}
    warnings = []
    
    for name, check_fn in checks.items():
        result = check_fn()
        results[name] = result
        if result["status"] == "warn":
            warnings.append(f"  ⚠️  {name}: {result.get('message', '有告警')}")
    
    log_event("health_check", results)
    
    print("\n" + "=" * 50)
    print("🏥 项目健康检查报告")
    print("=" * 50)
    
    for name, result in results.items():
        status = result["status"]
        icon = {"pass": "✅", "warn": "⚠️", "skip": "⏭️", "error": "❌"}[status]
        print(f"  {icon} {name}: {status}")
    
    if warnings:
        print("\n需要关注：")
        for w in warnings:
            print(w)
    else:
        print("\n所有检查通过，项目状态健康。")
    
    print("=" * 50 + "\n")
    
    return results
