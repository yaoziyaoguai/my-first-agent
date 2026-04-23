"""程序入口：输入循环 + 调用 session 模块。"""
import time

from agent.core import chat
from agent.session import (
    init_session,
    try_resume_from_checkpoint,
    finalize_session,
    handle_interrupt_with_checkpoint,
    handle_interrupt_without_checkpoint,
    handle_double_interrupt,
)
from agent.checkpoint import load_checkpoint
from agent.skills.registry import reload_registry


CTRL_C_DOUBLE_PRESS_WINDOW = 1.0  # 秒


def handle_slash_command(user_input: str) -> bool:
    """处理 / 开头的系统命令。返回 True 表示已处理（不再走 chat）。"""
    cmd = user_input.strip()
    
    if cmd == "/reload_skills":
        registry = reload_registry()
        print(f"\n[系统] Skill 已重新加载，当前 {registry.count()} 个可用")
        for w in registry.get_warnings():
            print(f"  {w}")
        return True
    
    return False


def main_loop():
    last_interrupt_time = 0
    
    while True:
        try:
            user_input = input("你: ").strip()

            # 1️⃣ 空输入过滤
            if not user_input:
                continue
            
            if user_input.lower() == "quit":
                finalize_session()
                break
            
            if handle_slash_command(user_input):
                continue
            
            reply = chat(user_input)
            if reply:
                print(reply)
        
        except KeyboardInterrupt:
            now = time.time()
            
            if now - last_interrupt_time < CTRL_C_DOUBLE_PRESS_WINDOW:
                handle_double_interrupt()
                break
            
            last_interrupt_time = now
            
            if load_checkpoint():
                should_exit = handle_interrupt_with_checkpoint()
            else:
                should_exit = handle_interrupt_without_checkpoint()
            
            if should_exit:
                break


if __name__ == "__main__":
    init_session()
    try_resume_from_checkpoint()
    main_loop()