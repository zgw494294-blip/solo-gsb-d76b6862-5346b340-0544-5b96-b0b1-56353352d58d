"""请求/响应模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class Variable(BaseModel):
    value: float = Field(allow_inf_nan=False, description="有限数值（不接受 inf/NaN/布尔）")
    unit: str = Field(min_length=1, description="受支持的单位符号，见 README 单位表")

    @field_validator("value", mode="before")
    @classmethod
    def _reject_bool(cls, v):
        if isinstance(v, bool):
            raise ValueError("value 必须是有限数值，不能是布尔值")
        return v


class EvalRequest(BaseModel):
    expression: str = Field(
        min_length=1,
        description="算式：数字、变量、括号、一元正负与 + - * /",
        examples=["dist / time"],
    )
    variables: dict[str, Variable] = Field(
        default_factory=dict, description="变量名 -> {value, unit}"
    )
    target_unit: str = Field(
        min_length=1,
        description="目标单位：受支持单位组成的乘除式（可带整数幂）或 1",
        examples=["m/s"],
    )


class EvalResponse(BaseModel):
    value: float = Field(description="按目标单位换算后的数值")
    unit: str = Field(description="归一化后的目标单位")
    dimension: str = Field(description="结果量纲，如 [length] / [time]；无量纲为 dimensionless")
