"""Session 生命周期管理：启动、恢复、退出、中断。

把原来散在 main.py 里的 session 相关逻辑集中到这里。
"""

from agent.logger import log_event, save_session_snapshot, SESSION_ID
from agent.health_check import run_health_check
from agent.memory import init_memory, cleanup_old_episodes, extract_memories_from_session
from agent.checkpoint import (
    load_checkpoint,
    load_checkpoint_to_state,
    save_checkpoint,
    clear_checkpoint,
)
from config import SYSTEM_PROMPT, MODEL_NAME


# ========== 启动 ==========

def init_session():
    """启动时调用：初始化记忆 + 健康检查 + 记日志"""
    init_memory()
    cleanup_old_episodes()
    
    log_event("session_start", {
        "system_prompt_length": len(SYSTEM_PROMPT),
    })
    
    run_health_check()
    
    print("=== My First Agent (Refactored) ===")
    print(f"Session: {SESSION_ID}")
    print("输入 'quit' 退出，'/reload_skills' 重新加载 skill\n")


def _checkpoint_has_actionable_resume(task_data: dict, conv_data: dict) -> bool:
    """判断 checkpoint 是否值得提示用户「要不要继续」。

    真实 M7-C 痛点：旧实现只要 checkpoint 文件存在就 prompt，
    哪怕 task.status='idle' + 0 条消息 + 无 pending_tool，
    用户会看到「📌 发现未完成的任务：（未命名任务） 已有 0 条对话历史」
    然后被强迫 y/n，体验上既无信息也无意义。

    actionable 条件（任一满足即提示）：
    - status 处于明确等待用户的状态（awaiting_*）
    - 存在 pending_tool 或 pending_user_input_request
    - 有进行中的 plan（current_plan + current_step_index > 0）
    - 有非空对话历史 + 非 idle 状态（说明上一轮没正常收尾）
    """
    status = task_data.get("status") or "idle"
    if status.startswith("awaiting_"):
        return True
    if task_data.get("pending_tool"):
        return True
    if task_data.get("pending_user_input_request"):
        return True
    if task_data.get("current_plan") and (task_data.get("current_step_index") or 0) > 0:
        return True
    msg_count = len(conv_data.get("messages", []))
    if msg_count > 0 and status != "idle":
        return True
    return False


def try_resume_from_checkpoint():
    """检查有没有未完成的任务，有就问用户是否恢复。

    M7-C 修复：不再无条件 prompt；只有 checkpoint 真的处于「等待用户输入」
    或「执行中断」状态时才提示。idle + 空消息的 checkpoint 视作历史残留，
    静默清掉，避免干扰用户开始新对话。
    """
    # 延迟 import，避免循环依赖
    from agent.core import get_state

    checkpoint = load_checkpoint()
    # B2 契约：普通 CLI 下不能裸 print 整段 checkpoint dict（含 conversation messages）。
    # 这里只在 MY_FIRST_AGENT_DEBUG=1 时才打印调试信息，且打印的是 keys 而非 values，
    # 避免把会话历史泄到终端。详见 docs/CLI_OUTPUT_CONTRACT.md "禁止项"。
    from agent.checkpoint import _debug_stdout_enabled
    if checkpoint is not None and _debug_stdout_enabled():
        print(f"[CHECKPOINT] loaded keys={list(checkpoint.keys())}")
    if not checkpoint:
        return

    task_data = checkpoint.get("task", {})
    conv_data = checkpoint.get("conversation", {})

    if not _checkpoint_has_actionable_resume(task_data, conv_data):
        # 静默清理历史残留，避免误导用户「有未完成的任务」。
        clear_checkpoint()
        return

    user_goal = task_data.get("user_goal") or "（未命名任务）"
    step_index = task_data.get("current_step_index", 0)
    msg_count = len(conv_data.get("messages", []))
    status = task_data.get("status") or "unknown"

    print(f"\n📌 发现未完成的任务：{user_goal}")
    print(f"   状态：{status}")
    print(f"   当前步骤索引：{step_index}")
    print(f"   已有 {msg_count} 条对话历史")

    choice = input("要继续这个任务吗？(y/n): ").strip().lower()
    if choice != "y":
        clear_checkpoint()
        print("\n[系统] 已清除断点，回到对话模式，可以直接输入新任务。\n")
        return

    restored = load_checkpoint_to_state(get_state())
    if restored:
        _replay_awaiting_prompt(get_state())
    else:
        print("\n[系统] 恢复断点失败。\n")


def _replay_awaiting_prompt(state):
    """按恢复后的 task.status 重新打印对应的询问提示。

    目的：checkpoint 存的是一个「等待用户某种输入」的断点，恢复后用户
    如果不知道当前处于哪个 awaiting 状态，就不知道该输入 y/n。
    """
    from agent.planner import Plan, format_plan_for_display

    status = state.task.status
    plan_dict = state.task.current_plan

    if status == "awaiting_plan_confirmation" and plan_dict:
        try:
            plan = Plan.model_validate(plan_dict)
            print(format_plan_for_display(plan))
        except Exception:
            pass
        print("按此计划执行吗？(y/n/输入修改意见): ", end="", flush=True)
        return

    if status == "awaiting_step_confirmation":
        print("\n上一步已完成。回复 y 继续下一步，回复 n 停止任务。")
        return

    if status == "awaiting_user_input":
        # 区分两种来源：
        # - 执行期求助（pending_user_input_request 非 None）：回放当时的问题/原因/选项
        # - collect_input/clarify 收尾：保留旧文案
        pending = getattr(state.task, "pending_user_input_request", None)
        if pending:
            print("\n上一轮需要你补充信息后才能继续：")
            if pending.get("question"):
                print(f"  问题：{pending['question']}")
            if pending.get("why_needed"):
                print(f"  原因：{pending['why_needed']}")
            options = pending.get("options") or []
            if options:
                print("  可选项：")
                for o in options:
                    print(f"    - {o}")
            print("  请直接回复你的答复。")
        else:
            print("\n上一步需要补充信息，请直接回复。")
        return

    if status == "awaiting_tool_confirmation" and state.task.pending_tool:
        pending = state.task.pending_tool
        print(
            f"\n⚠️ 有待确认的工具：{pending.get('tool')}({pending.get('input')})"
        )
        print("是否执行？(y/n/输入反馈意见): ", end="", flush=True)
        return

    print(f"\n[系统] 已恢复断点（状态：{status}）。\n")


# ========== 退出 ==========

def finalize_session():
    """正常退出（quit 或双 Ctrl+C）：提取记忆 + 保存快照 + 保存 state 断点"""
    from agent.core import client, get_state

    state = get_state()
    messages = state.conversation.messages

    print("\n[系统] 正在提取本次对话的记忆...")
    extract_memories_from_session(messages, client, MODEL_NAME)
    save_session_snapshot(messages)

    if state.task.current_plan:
        save_checkpoint(state)
        print("[系统] 未完成的任务断点已保存，下次启动可继续。")

    print("会话已保存，再见！")


# ========== 中断处理 ==========

def handle_interrupt_with_checkpoint() -> bool:
    """单次 Ctrl+C + 有 checkpoint：弹菜单。返回 True 表示要退出程序。"""
    from agent.core import get_state

    state = get_state()
    messages = state.conversation.messages
    save_checkpoint(state)

    print("\n\n[系统] 当前任务已暂停，断点已保存。")
    print("  1. 继续当前任务")
    print("  2. 放弃任务，回到对话模式")
    print("  3. 退出程序")

    choice = input("请选择 (1/2/3): ").strip()

    if choice == "1":
        print("[系统] 已保留当前任务状态，继续对话。\n")
        return False

    if choice == "2":
        clear_checkpoint()
        state.reset_task()
        print("[系统] 任务已放弃，回到对话模式。\n")
        return False

    if choice == "3":
        save_session_snapshot(messages)
        print("[系统] 再见！")
        return True

    print("[系统] 回到对话模式。\n")
    return False


def handle_interrupt_without_checkpoint() -> bool:
    """单次 Ctrl+C + 无 checkpoint：提示再按一次退出。返回 False（不退出）"""
    from agent.core import get_state

    messages = get_state().conversation.messages

    print("\n\n[系统] 再按一次 Ctrl+C 退出程序，或继续输入。")
    save_session_snapshot(messages)
    return False


def handle_double_interrupt():
    """连续两次 Ctrl+C：保存并退出"""
    from agent.core import get_state

    print("\n\n[系统] 检测到连续中断，正在保存...")

    state = get_state()
    messages = state.conversation.messages
    save_session_snapshot(messages)

    if state.task.current_plan:
        save_checkpoint(state)
        print("[系统] 任务断点已更新。")

    print("[系统] 下次启动可继续未完成的任务。再见！")
