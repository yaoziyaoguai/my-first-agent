from agent.logger import log_event, save_session_snapshot, SESSION_ID
from agent.core import chat, messages
from agent.health_check import run_health_check
from config import SYSTEM_PROMPT
from agent.memory import init_memory, cleanup_old_episodes, extract_memories_from_session
# 初始化记忆目录
init_memory()
# 清理过期情景记忆
cleanup_old_episodes()

log_event("session_start", {"system_prompt": SYSTEM_PROMPT})

run_health_check()

print("=== My First Agent (Refactored) ===")
print(f"Session: {SESSION_ID}")
print("输入 'quit' 退出\n")

while True:
    user_input = input("你: ")
    if user_input.strip().lower() == "quit":
        print("\n[系统] 正在提取本次对话的记忆...")
        from agent.core import client
        from config import MODEL_NAME
        extract_memories_from_session(messages, client, MODEL_NAME)
        save_session_snapshot(messages)
        print("会话已保存，再见！")
        break
    chat(user_input)
    print(f"[DEBUG] 当前消息历史: {len(messages)} 条")
