"""目标单位 / 变量单位的词法与语法解析。

单位串只允许：
- 14 个白名单单位符号：m cm km, s min h, kg g,
  K degC degF, delta_K delta_degC delta_degF
- 乘号 *、除号 /、括号
- 字面量 1（无量纲，只允许整体为 1，不能与单位组合）

返回 (unit, meta)，meta 用于分类：
{"kind": "dimensionless"}
{"kind": "absolute"}            # 恰好一个绝对温度符号
{"kind": "delta"}               # 恰好一个温差符号
{"kind": "plain"}               # 其它（含温差与其它量纲的复合）

绝对温度单位的指数必须为 +1 且不能与任何其它单位组合，
因为带偏移单位不允许出现在乘除复合量纲中。
"""

from __future__ import annotations

from typing import Any

from pint import UnitRegistry
from pint.util import UnitsContainer

from .errors import APIError

# 符号 -> pint 内部规范名
_UNIT_CANONICAL: dict[str, str] = {
    "m": "meter",
    "cm": "centimeter",
    "km": "kilometer",
    "s": "second",
    "min": "minute",
    "h": "hour",
    "kg": "kilogram",
    "g": "gram",
    "K": "kelvin",
    "degC": "degree_Celsius",
    "degF": "degree_Fahrenheit",
    "delta_K": "diff_kelvin",
    "delta_degC": "diff_degree_Celsius",
    "delta_degF": "diff_degree_Fahrenheit",
}

ABSOLUTE_UNITS = frozenset({"K", "degC", "degF"})
DELTA_UNITS = frozenset({"delta_K", "delta_degC", "delta_degF"})

_FIELD = "/target_unit"  # 默认；变量单位的解析会覆盖 field


def _tokenize(text: str, field: str) -> list[tuple[str, str, int]]:
    tokens: list[tuple[str, str, int]] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\n":
            i += 1
            continue
        if ch in "*/()":
            tokens.append((ch, ch, i))
            i += 1
            continue
        # 1 作为无量纲整体单位
        if ch == "1":
            tokens.append(("UNIT", "1", i))
            i += 1
            continue
        # 白名单单位：优先匹配 delta_* 长符号
        matched: str | None = None
        for symbol in sorted(_UNIT_CANONICAL, key=len, reverse=True):
            if text.startswith(symbol, i):
                end = i + len(symbol)
                # 边界检查：避免 mile 被当成 min、mins 被当成 min 等
                if end < n and (text[end].isalnum() or text[end] == "_"):
                    continue
                matched = symbol
                break
        if matched is not None:
            tokens.append(("UNIT", matched, i))
            i += len(matched)
            continue
        raise APIError(
            "invalid_unit",
            f"Illegal character or unknown unit at position {i} in unit expression {text!r}.",
            field=field,
            position=i,
        )
    tokens.append(("EOF", "", n))
    return tokens


class _Parser:
    """unit_expr := '1' | product ; product := factor (('*'|'/') factor)*"""

    def __init__(self, tokens: list[tuple[str, str, int]], text: str, field: str):
        self.tokens = tokens
        self.text = text
        self.field = field
        self.pos = 0

    def peek(self) -> tuple[str, str, int]:
        return self.tokens[self.pos]

    def advance(self) -> tuple[str, str, int]:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, kind: str) -> tuple[str, str, int]:
        tok = self.peek()
        if tok[0] != kind:
            raise APIError(
                "invalid_unit",
                f"Unexpected token {tok[1]!r} at position {tok[2]} in unit expression {self.text!r}.",
                field=self.field,
                position=tok[2],
            )
        return self.advance()

    def parse(self) -> UnitsContainer:
        kind, value, start = self.peek()
        if kind == "UNIT" and value == "1":
            self.advance()
            k2, v2, p2 = self.peek()
            if k2 != "EOF":
                raise APIError(
                    "invalid_unit",
                    "Dimensionless '1' cannot be combined with other units.",
                    field=self.field,
                    position=p2,
                )
            return UnitsContainer()
        container = self.parse_product()
        if self.peek()[0] != "EOF":
            tok = self.peek()
            raise APIError(
                "invalid_unit",
                f"Unexpected token {tok[1]!r} at position {tok[2]} in unit expression {self.text!r}.",
                field=self.field,
                position=tok[2],
            )
        return container

    def parse_product(self) -> UnitsContainer:
        try:
            container = self.parse_factor()
        except APIError:
            raise
        while self.peek()[0] in ("*", "/"):
            op = self.advance()
            right = self.parse_factor()
            if op[0] == "*":
                container = container * right
            else:
                container = container / right
        return container

    def parse_factor(self) -> UnitsContainer:
        kind, value, position = self.peek()
        if kind == "(":
            self.advance()
            inner = self.parse_product()
            close = self.peek()
            if close[0] != ")":
                raise APIError(
                    "invalid_unit",
                    f"Missing closing parenthesis at position {position}.",
                    field=self.field,
                    position=close[2],
                )
            self.advance()
            return inner
        if kind == "UNIT" and value != "1":
            self.advance()
            return UnitsContainer({_UNIT_CANONICAL[value]: 1})
        raise APIError(
            "invalid_unit",
            f"Expected a unit at position {position}, got {value!r}.",
            field=self.field,
            position=position,
        )


def parse_unit(text: str, ureg: UnitRegistry, field: str = _FIELD) -> tuple[Any, dict[str, Any]]:
    """解析单位串，返回 (pint unit, 分类信息)。"""
    if not isinstance(text, str) or text.strip() == "":
        raise APIError(
            "invalid_unit",
            "Unit must be a non-empty expression of whitelisted units, or '1'.",
            field=field,
            position=0,
        )

    tokens = _tokenize(text, field)
    container = _Parser(tokens, text, field).parse()

    # 把规范名映射回白名单符号，便于分类
    canonical_to_symbol = {v: k for k, v in _UNIT_CANONICAL.items()}
    leaves: list[tuple[str, int]] = []
    for canonical, exponent in container.items():
        symbol = canonical_to_symbol.get(canonical)
        if symbol is None:  # 理论上不可达：词法只接受白名单符号
            raise APIError(
                "invalid_unit",
                f"Unit {canonical!r} is not on the whitelist.",
                field=field,
            )
        leaves.append((symbol, int(exponent)))

    if not leaves:
        unit = ureg.parse_units("")
        return unit, {"kind": "dimensionless"}

    absolute = [(s, e) for s, e in leaves if s in ABSOLUTE_UNITS]
    delta = [(s, e) for s, e in leaves if s in DELTA_UNITS]

    # 带偏移单位 degC/degF：只允许单独出现且指数为 +1。
    # K 本身偏移为 0（SI 中同时充当温差单位），允许出现在复合式中（等价于 delta_K）。
    offset_units = [(s, e) for s, e in absolute if s in ("degC", "degF")]
    if offset_units and (len(leaves) != 1 or offset_units[0][1] != 1):
        raise APIError(
            "incompatible_unit",
            "Offset temperature unit degC/degF cannot be raised to a power or combined "
            "with other units; use K, delta_K, delta_degC or delta_degF instead.",
            field=field,
        )

    if len(leaves) == 1 and absolute and leaves[0][1] == 1:
        meta = {"kind": "absolute", "symbol": leaves[0][0]}
    elif len(leaves) == 1 and delta and leaves[0][1] == 1:
        meta = {"kind": "delta", "symbol": leaves[0][0]}
    else:
        meta = {"kind": "plain"}

    try:
        unit = ureg.Unit(container)
    except Exception as exc:  # pragma: no cover - 容器已手工构造，基本不会失败
        raise APIError("invalid_unit", f"Failed to build unit: {exc}", field=field)
    return unit, meta
