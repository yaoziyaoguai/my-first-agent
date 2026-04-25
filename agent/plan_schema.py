from __future__ import annotations

from typing import Optional, List
from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    """
    计划中的单个步骤。
    这是 planner 产出的最小执行单元。
    """

    # 步骤唯一标识，例如 step-1
    step_id: str = Field(..., description="步骤唯一标识")

    # 步骤标题，短一点，方便展示
    title: str = Field(..., description="步骤标题")

    # 步骤详细说明，告诉执行层这一步要干什么
    description: str = Field(..., description="详细步骤说明")

    # 步骤类型，用于后续判断这一步是否完成
    # 可选值例如：read / analyze / edit / run_command / report / collect_input / clarify
    step_type: str = Field(..., description="步骤类型")

    # 建议使用的工具名；如果没有明确工具，可为 None
    suggested_tool: Optional[str] = Field(
        None,
        description="建议使用的工具名，没有则为 null",
    )

    # 这一步完成后的预期结果
    expected_outcome: Optional[str] = Field(
        None,
        description="该步骤完成后的预期结果",
    )

    # 该步骤的完成判定标准
    # 用于后续判断“当前 step 是否真的完成”
    completion_criteria: Optional[str] = Field(
        None,
        description="该步骤的完成判定标准",
    )


class Plan(BaseModel):
    """
    planner 生成的完整计划。
    注意：这是“计划内容”，不是运行时 task 状态。
    """

    # 当前任务目标
    goal: str = Field(..., description="当前任务目标")

    # 简短规划思路，可选
    thinking: Optional[str] = Field(
        None,
        description="简短规划思路",
    )

    # 计划步骤列表
    steps: List[PlanStep] = Field(
        default_factory=list,
        description="执行步骤列表",
    )

    # 是否需要用户确认
    needs_confirmation: bool = Field(
        True,
        description="是否需要用户确认",
    )


class PlannerOutput(BaseModel):
    """
    planner 的直接结构化输出。
    用它承接模型原始输出，再决定是否转成 Plan。
    """

    # 任务预估步骤数
    steps_estimate: int = Field(..., description="任务预估步骤数")

    # 当前任务目标；单步任务时可为空
    goal: Optional[str] = Field(
        None,
        description="当前任务目标",
    )

    # 简短规划思路；可为空
    thinking: Optional[str] = Field(
        None,
        description="简短规划思路",
    )

    # 是否需要用户确认
    needs_confirmation: bool = Field(
        True,
        description="是否需要用户确认",
    )

    # 多步任务的步骤列表；单步任务时可为空列表
    steps: List[PlanStep] = Field(
        default_factory=list,
        description="执行步骤列表",
    )
