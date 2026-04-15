from agent.logger import log_event, save_session_snapshot, SESSION_ID
from agent.core import chat, messages
from agent.health_check import run_health_check
from agent.memory import init_memory, build_memory_prompt, cleanup_old_episodes, extract_memories_from_session
from agent.checkpoint import load_checkpoint, clear_checkpoint, format_resume_context
from config import SYSTEM_PROMPT
import time

# 初始化
init_memory()
cleanup_old_episodes()

memory_prompt = build_memory_prompt()
full_system_prompt = SYSTEM_PROMPT + "\n\n" + memory_prompt

log_event("session_start", {
    "system_prompt": SYSTEM_PROMPT,
    "memory_prompt_length": len(memory_prompt),
    "full_prompt_length": len(full_system_prompt),
})

run_health_check()

# 检查是否有未完成的任务
checkpoint = load_checkpoint()
if checkpoint:
    plan = checkpoint["plan"]
    total = len(plan["steps"])
    msg_count = len(checkpoint.get("messages", []))
    print(f"\n📌 发现未完成的任务：{plan['goal']}")
    print(f"   已有 {msg_count} 条对话历史")

    choice = input("要继续这个任务吗？(y/n): ").strip().lower()
    if choice == "y":
        # 恢复消息历史
        import agent.core as core
        core.messages = checkpoint.get("messages", [])
        resume_context = format_resume_context(checkpoint)
        print("\n[系统] 正在恢复任务...\n")
        chat(resume_context)
    else:
        clear_checkpoint()
        print("已清除断点。\n")

print("=== My First Agent (Refactored) ===")
print(f"Session: {SESSION_ID}")
print("输入 'quit' 退出\n")



last_interrupt_time = 0

while True:
    try:
        user_input = input("你: ")
        if user_input.strip().lower() == "quit":
            # Session 级退出
            print("\n[系统] 正在提取本次对话的记忆...")
            from agent.core import client
            from config import MODEL_NAME
            extract_memories_from_session(messages, client, MODEL_NAME)
            save_session_snapshot(messages)

            from agent.checkpoint import load_checkpoint, save_checkpoint
            existing = load_checkpoint()
            if existing:
                save_checkpoint(existing["original_input"], existing["plan"], messages)
                print("[系统] 未完成的任务断点已保存，下次启动可继续。")

            print("会话已保存，再见！")
            break

        chat(user_input)
        print(f"[DEBUG] 当前消息历史: {len(messages)} 条")

    except KeyboardInterrupt:
        now = time.time()
        if now - last_interrupt_time < 1.0:
            # 连续两次 Ctrl+C → 退出 Session
            print("\n\n[系统] 检测到连续中断，正在保存...")
            save_session_snapshot(messages)

            from agent.checkpoint import load_checkpoint, save_checkpoint
            existing = load_checkpoint()
            if existing:
                save_checkpoint(existing["original_input"], existing["plan"], messages)
                print("[系统] 任务断点已更新。")

            print("[系统] 下次启动可继续未完成的任务。再见！")
            break
        else:
            last_interrupt_time = now

            # 单次 Ctrl+C → 看有没有编排任务在执行
            from agent.checkpoint import load_checkpoint, save_checkpoint, clear_checkpoint
            existing = load_checkpoint()

            if existing:
                # 有编排任务：暂停并给用户选择
                save_checkpoint(existing["original_input"], existing["plan"], messages)
                print("\n\n[系统] 当前任务已暂停，断点已保存。")
                print("  1. 继续当前任务")
                print("  2. 放弃任务，回到对话模式")
                print("  3. 退出程序")

                choice = input("请选择 (1/2/3): ").strip()
                if choice == "1":
                    from agent.checkpoint import format_resume_context
                    resume_context = format_resume_context(existing)
                    chat(resume_context)
                elif choice == "2":
                    clear_checkpoint()
                    print("[系统] 任务已放弃，回到对话模式。\n")
                elif choice == "3":
                    save_session_snapshot(messages)
                    print("[系统] 再见！")
                    break
                else:
                    print("[系统] 回到对话模式。\n")
            else:
                # 没有编排任务：提示再按一次退出
                print("\n\n[系统] 再按一次 Ctrl+C 退出程序，或继续输入。")
                save_session_snapshot(messages)