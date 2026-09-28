"""统一的 422 业务异常。

每个错误都带：
- code: 机器可读错误码
- field: 出错的请求字段（JSON Pointer，如 "/expression"、"/variables/x/unit"）
- position: 当错误指向算式或单位串中的某个位置时，给出从 0 开始的字符偏移
- message: 人类可读说明（英文，便于稳定断言；README 给出中文说明）
"""

from __future__ import annotations

from typing import Any


class APIError(Exception):
    status_code: int = 422

    def __init__(self, code: str, message: str, field: str = "", position: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field
        self.position = position

    def to_detail(self) -> dict[str, Any]:
        detail: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "field": self.field,
        }
        if self.position is not None:
            detail["position"] = self.position
        return detail
