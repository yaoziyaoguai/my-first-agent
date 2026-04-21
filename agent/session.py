"""Session 生命周期管理：启动、恢复、退出、中断。

把原来散在 main.py 里的 session 相关逻辑集中到这里。
"""

from agent.logger import log_event, save_session_snapshot, SESSION_ID
from agent.health_check import run_health_check
from agent.memory import init_memory, cleanup_old_episodes, extract_memories_from_session
from agent.checkpoint import (
    load_checkpoint, save_checkpoint, clear_checkpoint, format_resume_context,
)
from agent.prompt_builder import build_system_prompt
from config import SYSTEM_PROMPT, MODEL_NAME


# ========== 启动 ==========

def init_session():
    """启动时调用：初始化记忆 + 健康检查 + 记日志"""
    init_memory()
    cleanup_old_episodes()
    
    full_system_prompt = build_system_prompt()
    log_event("session_start", {
        "system_prompt_length": len(SYSTEM_PROMPT),
        "full_prompt_length": len(full_system_prompt),
    })
    
    run_health_check()
    
    print("=== My First Agent (Refactored) ===")
    print(f"Session: {SESSION_ID}")
    print("输入 'quit' 退出，'/reload_skills' 重新加载 skill\n")


def try_resume_from_checkpoint():
    """检查有没有未完成的任务，有就问用户是否恢复。"""
    # 延迟 import，避免循环依赖
    from agent.core import chat
    
    checkpoint = load_checkpoint()
    if not checkpoint:
        return
    
    plan = checkpoint["plan"]
    msg_count = len(checkpoint.get("messages", []))
    print(f"\n📌 发现未完成的任务：{plan['goal']}")
    print(f"   已有 {msg_count} 条对话历史")
    
    choice = input("要继续这个任务吗？(y/n): ").strip().lower()
    if choice != "y":
        clear_checkpoint()
        print("已清除断点。\n")
        return
    
    # 恢复消息历史到 core 模块的 messages
    import agent.core as core
    core.messages = checkpoint.get("messages", [])
    resume_context = format_resume_context(checkpoint)
    print("\n[系统] 正在恢复任务...\n")
    chat(resume_context)


# ========== 退出 ==========

def finalize_session(messages):
    """正常退出（quit 或双 Ctrl+C）：提取记忆 + 保存快照 + 保存断点"""
    from agent.core import client
    
    print("\n[系统] 正在提取本次对话的记忆...")
    extract_memories_from_session(messages, client, MODEL_NAME)
    save_session_snapshot(messages)
    
    existing = load_checkpoint()
    if existing:
        save_checkpoint(existing["original_input"], existing["plan"], messages)
        print("[系统] 未完成的任务断点已保存，下次启动可继续。")
    
    print("会话已保存，再见！")


# ========== 中断处理 ==========

def handle_interrupt_with_checkpoint(messages) -> bool:
    """单次 Ctrl+C + 有 checkpoint：弹菜单。返回 True 表示要退出程序。"""
    from agent.core import chat
    
    existing = load_checkpoint()
    save_checkpoint(existing["original_input"], existing["plan"], messages)
    
    print("\n\n[系统] 当前任务已暂停，断点已保存。")
    print("  1. 继续当前任务")
    print("  2. 放弃任务，回到对话模式")
    print("  3. 退出程序")
    
    choice = input("请选择 (1/2/3): ").strip()
    
    if choice == "1":
        resume_context = format_resume_context(existing)
        chat(resume_context)
        return False
    
    if choice == "2":
        clear_checkpoint()
        print("[系统] 任务已放弃，回到对话模式。\n")
        return False
    
    if choice == "3":
        save_session_snapshot(messages)
        print("[系统] 再见！")
        return True
    
    print("[系统] 回到对话模式。\n")
    return False


def handle_interrupt_without_checkpoint(messages) -> bool:
    """单次 Ctrl+C + 无 checkpoint：提示再按一次退出。返回 False（不退出）"""
    print("\n\n[系统] 再按一次 Ctrl+C 退出程序，或继续输入。")
    save_session_snapshot(messages)
    return False


def handle_double_interrupt(messages):
    """连续两次 Ctrl+C：保存并退出"""
    print("\n\n[系统] 检测到连续中断，正在保存...")
    save_session_snapshot(messages)
    
    existing = load_checkpoint()
    if existing:
        save_checkpoint(existing["original_input"], existing["plan"], messages)
        print("[系统] 任务断点已更新。")
    
    print("[系统] 下次启动可继续未完成的任务。再见！")