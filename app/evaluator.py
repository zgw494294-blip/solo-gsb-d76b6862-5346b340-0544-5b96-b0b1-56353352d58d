"""AST 求值：在普通 pint 运算之上实现温度语义。

每个中间值用 (Quantity, kind) 表示，kind 取值：
- "plain"：普通量（无量纲字面量、长度、时间、复合量纲，以及含温差的复合量纲）
- "delta"：纯温差量纲（单个 delta_K / delta_degC / delta_degF）
- "abs"  ：绝对温度，内部统一存为 K（kelvin，零偏移），运算安全

语义规则：
- 一元负号不得作用于绝对温度；一元正号保持不变
- abs +/- delta => abs；abs - abs => delta（delta_K）
- 两个绝对温度相加、delta - abs 均非法
- 绝对温度不得参与乘除
- 其余 +、- 走 pint（量纲不兼容由 pint 报 DimensionalityError，转 422）
- 乘除走 pint；结果若恰为纯温度量纲（kelvin 单位），标记为 delta
- 除零转 422，位置指向 / 运算符
"""

from __future__ import annotations

import math
from typing import Any

from pint import UnitRegistry
from pint.errors import DimensionalityError, OffsetUnitCalculusError, PintError

from .errors import APIError

_PLAIN = "plain"
_DELTA = "delta"
_ABS = "abs"


def _q(ureg: UnitRegistry, magnitude: float, units: str = "") -> Any:
    return ureg.Quantity(magnitude, units)


def _reclassify(quantity: Any) -> str:
    """乘除之后的结果分类：纯温度量纲（kelvin 单项）视为温差，其余普通。"""
    units = quantity.units
    if units.dimensionless:
        return _PLAIN
    container = dict(units._units)
    dimensionality = quantity.dimensionality
    if len(container) == 1:
        (canonical, exponent), = container.items()
        if str(dimensionality) == "[temperature]" and exponent == 1:
            return _DELTA
    return _PLAIN


def _delta_to_kelvin(value: Any) -> Any:
    """把纯温差量统一换算到 delta_K。"""
    if dict(value.units._units) == {"diff_kelvin": 1}:
        return value
    return value.to("delta_K")


def _pint_error(exc: Exception, position: int) -> APIError:
    if isinstance(exc, ZeroDivisionError):
        return APIError(
            "division_by_zero",
            "Division by zero at the indicated operator.",
            field="/expression",
            position=position,
        )
    if isinstance(exc, DimensionalityError):
        return APIError(
            "incompatible_dimension",
            f"Incompatible dimensions at operator position {position}: {exc}",
            field="/expression",
            position=position,
        )
    if isinstance(exc, OffsetUnitCalculusError):
        return APIError(
            "temperature_op_not_allowed",
            f"Illegal operation involving an absolute temperature at position {position}: {exc}",
            field="/expression",
            position=position,
        )
    if isinstance(exc, PintError):
        return APIError(
            "evaluation_error",
            f"Unit error at operator position {position}: {exc}",
            field="/expression",
            position=position,
        )
    raise exc


class Evaluator:
    def __init__(self, ureg: UnitRegistry, variables: dict[str, Any]):
        self.ureg = ureg
        # variables: name -> (Quantity, kind)
        self.variables = variables

    def evaluate(self, node: tuple) -> tuple[Any, str]:
        tag = node[0]
        if tag == "num":
            _, magnitude, pos = node
            return _q(self.ureg, magnitude), _PLAIN
        if tag == "var":
            _, name, pos = node
            if name not in self.variables:
                raise APIError(
                    "unknown_variable",
                    f"Unknown variable {name!r}; provide it in 'variables'.",
                    field=f"/variables/{name}",
                    position=pos,
                )
            return self.variables[name]
        if tag == "un":
            _, op, operand, pos = node
            value, kind = self.evaluate(operand)
            if kind == _ABS:
                if op == "-":
                    raise APIError(
                        "temperature_op_not_allowed",
                        "An absolute temperature cannot be negated.",
                        field="/expression",
                        position=pos,
                    )
                return value, _ABS
            if op == "-":
                return -value, kind
            return +value, kind
        # bin
        _, op, left_node, right_node, pos = node
        left, lk = self.evaluate(left_node)
        right, rk = self.evaluate(right_node)

        if op in ("+", "-"):
            return self._add_sub(op, left, lk, right, rk, pos)
        return self._mul_div(op, left, lk, right, rk, pos)

    def _add_sub(
        self,
        op: str,
        left: Any,
        lk: str,
        right: Any,
        rk: str,
        pos: int,
    ) -> tuple[Any, str]:
        # 绝对温度不得出现在乘除中已由 _mul_div 拦截；这里处理 +/-。
        if lk == _ABS or rk == _ABS:
            if lk == _ABS and rk == _ABS:
                if op == "+":
                    raise APIError(
                        "temperature_op_not_allowed",
                        "Two absolute temperatures cannot be added.",
                        field="/expression",
                        position=pos,
                    )
                # 两个绝对温度只许相减，结果为温差（统一 delta_K）
                try:
                    diff = left.to("K").magnitude - right.to("K").magnitude
                except Exception as exc:  # pragma: no cover
                    raise _pint_error(exc, pos)
                if not math.isfinite(diff):
                    raise APIError(
                        "evaluation_error",
                        "Result of temperature subtraction is not finite.",
                        field="/expression",
                        position=pos,
                    )
                return _q(self.ureg, diff, "delta_K"), _DELTA

            # abs 与 delta 组合；delta - abs 没有物理意义
            if op == "-" and lk == _DELTA and rk == _ABS:
                raise APIError(
                    "temperature_op_not_allowed",
                    "Subtracting an absolute temperature from a temperature difference is not allowed.",
                    field="/expression",
                    position=pos,
                )
            if not (lk == _ABS and rk == _DELTA) and not (lk == _DELTA and rk == _ABS):
                # abs +/- 普通量（含无量纲字面量）一律非法
                raise APIError(
                    "incompatible_dimension",
                    "An absolute temperature can only be combined with a temperature difference "
                    "(delta_K / delta_degC / delta_degF) using + or -.",
                    field="/expression",
                    position=pos,
                )
            try:
                if lk == _ABS:
                    result = (left + _delta_to_kelvin(right)) if op == "+" else (left - _delta_to_kelvin(right))
                else:
                    # delta + abs
                    result = _delta_to_kelvin(left) + right
                result = result.to("K")
            except Exception as exc:
                raise _pint_error(exc, pos)
            return result, _ABS

        # 两个普通量：交给 pint 检查量纲兼容性（温差之间的加减也走这里）
        try:
            result = left + right if op == "+" else left - right
        except Exception as exc:
            raise _pint_error(exc, pos)
        return result, _reclassify(result)

    def _mul_div(
        self,
        op: str,
        left: Any,
        lk: str,
        right: Any,
        rk: str,
        pos: int,
    ) -> tuple[Any, str]:
        if lk == _ABS or rk == _ABS:
            raise APIError(
                "temperature_op_not_allowed",
                "An absolute temperature cannot be multiplied or divided.",
                field="/expression",
                position=pos,
            )
        try:
            result = left * right if op == "*" else left / right
        except Exception as exc:
            raise _pint_error(exc, pos)
        kind = _reclassify(result)
        return result, kind
