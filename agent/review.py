import json

from config import ENABLE_REVIEW, SHOW_REVIEW_DETAILS

CURRENT_TASK_REQUEST = None


def is_control_message(text):
    if not text:
        return False
    normalized = text.strip().lower()
    control_messages = {
        "y", "yes", "n", "no",
        "继续", "继续吧", "继续创建", "继续创建下一个文件",
        "好的", "好", "可以", "行", "开始", "继续做",
    }
    return normalized in control_messages


def get_effective_review_request(user_input):
    global CURRENT_TASK_REQUEST
    if not is_control_message(user_input):
        CURRENT_TASK_REQUEST = user_input
    return CURRENT_TASK_REQUEST or user_input


def truncate_for_review(value, max_len=800):
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except Exception:
            text = str(value)
    if len(text) > max_len:
        return text[:max_len] + "...(已截断)"
    return text


def should_review_turn(tool_traces):
    if not ENABLE_REVIEW:
        return False
    return any(trace.get("tool") == "write_file" for trace in tool_traces)


def print_review_summary(review):
    if not review or review.get("parse_error"):
        print("\n[评测] 本轮评测结果解析失败")
        return

    overall = review.get("overall", "未知")

    if overall == "通过":
        suggestion = "建议继续"
    elif overall == "需要注意":
        suggestion = "建议人工看一下再继续"
    elif overall == "不通过":
        suggestion = "建议本轮重试，或先补验证再继续"
    else:
        suggestion = "请人工判断"

    print(f"\n[评测] {overall}，{suggestion}")

    if SHOW_REVIEW_DETAILS:
        for dim in ["completeness", "accuracy", "safety"]:
            if dim in review:
                print(f"  {dim}: {review[dim]['score']}/5 - {review[dim]['reason']}")

    if overall == "通过":
        print("\n[系统] 评测已通过，如需继续请输入指令。")


def build_retry_feedback(review):
    """根据审查结果构建反馈信息，供自动重试使用"""
    feedback_parts = ["[系统评测反馈] 你的上一次输出未通过质量审查，请根据以下反馈修改："]
    for dim in ["completeness", "accuracy", "safety"]:
        if dim in review:
            feedback_parts.append(f"- {dim}: {review[dim]['score']}/5 - {review[dim]['reason']}")
    feedback_parts.append("\n请重新执行任务，修正上述问题。")
    return "\n".join(feedback_parts)
