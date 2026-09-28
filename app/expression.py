"""算式词法与语法解析。

允许的文法：
    expr   := term (('+' | '-') term)*
    term   := factor (('*' | '/') factor)*
    factor := ('+' | '-') factor | atom
    atom   := NUMBER | NAME | '(' expr ')'

禁止：
- 函数调用（NAME 后紧跟 '('，按“缺少运算符/隐式乘法”报错）
- 隐式乘法（两个 atom 之间没有 * 或 /）
- 幂运算、逗号、百分号等其它任何符号

AST 节点（普通 tuple，首元素为节点类型，末元素为位置）：
    ("num",  float, position)
    ("var",  str,   position)
    ("un",   "+", "num"/"var", position)
    ("bin",  op, left, right, position)
"""

from __future__ import annotations

import math
from typing import Any

from .errors import APIError

_FIELD = "/expression"


def _tokenize(text: str) -> list[tuple[str, str, int]]:
    tokens: list[tuple[str, str, int]] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\n\r":
            i += 1
            continue
        if ch in "+-*/()":
            tokens.append((ch, ch, i))
            i += 1
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and text[i + 1].isdigit()):
            start = i
            seen_dot = False
            seen_e = False
            j = i
            while j < n:
                c = text[j]
                if c.isdigit():
                    j += 1
                elif c == "." and not seen_dot and not seen_e:
                    seen_dot = True
                    j += 1
                elif c in "eE" and not seen_e:
                    seen_e = True
                    j += 1
                    if j < n and text[j] in "+-":
                        j += 1
                else:
                    break
            word = text[start:j]
            try:
                value = float(word)
            except ValueError:
                raise APIError(
                    "invalid_expression",
                    f"Malformed number {word!r} at position {start}.",
                    field=_FIELD,
                    position=start,
                )
            if not math.isfinite(value):
                raise APIError(
                    "invalid_expression",
                    f"Number {word!r} is not finite.",
                    field=_FIELD,
                    position=start,
                )
            tokens.append(("NUM", word, start))
            i = j
            continue
        if ch.isalpha() or ch == "_":
            start = i
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            name = text[start:j]
            tokens.append(("NAME", name, start))
            i = j
            continue
        raise APIError(
            "invalid_expression",
            f"Illegal character {ch!r} at position {i}. "
            "Only digits, variables, parentheses, unary +/- and binary + - * / are allowed.",
            field=_FIELD,
            position=i,
        )
    tokens.append(("EOF", "", n))
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, str, int]], text: str):
        self.tokens = tokens
        self.text = text
        self.idx = 0

    def peek(self) -> tuple[str, str, int]:
        return self.tokens[self.idx]

    def advance(self) -> tuple[str, str, int]:
        tok = self.tokens[self.idx]
        self.idx += 1
        return tok

    def parse(self) -> tuple:
        if self.peek()[0] == "EOF":
            raise APIError(
                "invalid_expression",
                "Expression is empty.",
                field=_FIELD,
                position=0,
            )
        node = self.parse_expr()
        kind, _, pos = self.peek()
        if kind != "EOF":
            tok = self.peek()
            raise APIError(
                "invalid_expression",
                f"Unexpected token {tok[1]!r} at position {tok[2]}.",
                field=_FIELD,
                position=tok[2],
            )
        return node

    def parse_expr(self) -> tuple:
        node = self.parse_term()
        while self.peek()[0] in ("+", "-"):
            op_tok = self.advance()
            right = self.parse_term()
            node = ("bin", op_tok[0], node, right, op_tok[2])
        return node

    def parse_term(self) -> tuple:
        node = self.parse_factor()
        while True:
            kind, _, _ = self.peek()
            if kind in ("*", "/"):
                op_tok = self.advance()
                right = self.parse_factor()
                node = ("bin", op_tok[0], node, right, op_tok[2])
                continue
            if kind in ("NUM", "NAME", "("):
                tok = self.peek()
                raise APIError(
                    "invalid_expression",
                    f"Implicit multiplication is not allowed: expected '*' or '/' "
                    f"before {tok[1]!r} at position {tok[2]}.",
                    field=_FIELD,
                    position=tok[2],
                )
            break
        return node

    def parse_factor(self) -> tuple:
        kind, value, pos = self.peek()
        if kind in ("+", "-"):
            self.advance()
            operand = self.parse_factor()
            return ("un", value, operand, pos)
        return self.parse_atom()

    def parse_atom(self) -> tuple:
        kind, value, pos = self.peek()
        if kind == "NUM":
            self.advance()
            return ("num", float(value), pos)
        if kind == "NAME":
            self.advance()
            if self.peek()[0] == "(":
                lp = self.peek()
                raise APIError(
                    "invalid_expression",
                    f"Function calls are not allowed: {value!r} at position {pos}.",
                    field=_FIELD,
                    position=lp[2],
                )
            return ("var", value, pos)
        if kind == "(":
            self.advance()
            inner = self.parse_expr()
            close = self.peek()
            if close[0] != ")":
                raise APIError(
                    "invalid_expression",
                    f"Missing closing parenthesis (opened at {pos}); "
                    f"got {close[1]!r} at position {close[2]}.",
                    field=_FIELD,
                    position=close[2],
                )
            self.advance()
            return inner
        if kind == ")":
            raise APIError(
                "invalid_expression",
                f"Unmatched closing parenthesis at position {pos}.",
                field=_FIELD,
                position=pos,
            )
        if kind == "EOF":
            raise APIError(
                "invalid_expression",
                "Unexpected end of expression: an operand is missing.",
                field=_FIELD,
                position=pos,
            )
        raise APIError(
            "invalid_expression",
            f"Unexpected token {value!r} at position {pos}.",
            field=_FIELD,
            position=pos,
        )


def parse_expression(text: str) -> tuple:
    if not isinstance(text, str):
        raise APIError(
            "invalid_expression",
            "Expression must be a string.",
            field=_FIELD,
            position=0,
        )
    tokens = _tokenize(text)
    return _Parser(tokens, text).parse()
