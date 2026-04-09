from agent.logger import log_event, save_session_snapshot, SESSION_ID
from agent.core import chat, messages
from config import SYSTEM_PROMPT

log_event("session_start", {"system_prompt": SYSTEM_PROMPT})

print(f"=== My First Agent (Refactored) ===")
print(f"Session: {SESSION_ID}")
print("输入 'quit' 退出\n")

while True:
    user_input = input("你: ")
    if user_input.strip().lower() == "quit":
        save_session_snapshot(messages)
        print("会话已保存，再见！")
        break
    chat(user_input)
    print(f"[DEBUG] 当前消息历史: {len(messages)} 条")
