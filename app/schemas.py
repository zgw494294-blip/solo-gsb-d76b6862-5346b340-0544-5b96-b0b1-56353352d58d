"""请求/响应模型。"""

from __future__ import annotations

import math
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Variable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float = Field(..., description="有限数值")
    unit: str = Field(..., description="白名单单位的乘除复合式，或 1")

    @field_validator("value")
    @classmethod
    def _finite(cls, v: float) -> float:
        if isinstance(v, bool) or not math.isfinite(v):
            raise ValueError("value must be a finite number")
        return v


class EvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expression: Annotated[str, Field(..., description="只允许数字、变量、括号、一元正负与 + - * /")]
    variables: Annotated[dict[str, Variable], Field(default_factory=dict)]
    target_unit: Annotated[str, Field(..., alias="target_unit", description="目标单位乘除式，或 1")]

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class EvaluateResponse(BaseModel):
    value: float
    unit: str
    dimensionality: dict[str, int]
    kind: str = Field(..., description="absolute | delta | plain")
