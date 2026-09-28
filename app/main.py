"""FastAPI 应用：POST /v1/evaluate 离线量纲公式求值。"""

from __future__ import annotations

import math
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .errors import APIError
from .evaluator import Evaluator
from .expression import parse_expression
from .registry import get_registry
from .schemas import EvaluateRequest, EvaluateResponse
from .unit_expr import _UNIT_CANONICAL, parse_unit

app = FastAPI(
    title="Offline Dimensional Formula Evaluator",
    version="1.0.0",
    description="基于 Python + FastAPI + Pint 的离线量纲公式求值 API。",
)


@app.exception_handler(APIError)
async def api_error_handler(_: Request, exc: APIError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"errors": [exc.to_detail()]})


def _loc_to_field(loc: tuple[Any, ...]) -> str:
    """把 pydantic 的 loc（如 ('body','variables','x','unit')）转成 JSON Pointer。"""
    parts = [p for p in loc if p != "body"]
    if not parts:
        return ""
    return "/" + "/".join(str(p) for p in parts)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = []
    for err in exc.errors():
        field = _loc_to_field(tuple(err.get("loc", ())))
        code = "invalid_request"
        pydantic_type = err.get("type", "")
        if pydantic_type == "missing":
            code = "missing_field"
        elif pydantic_type in ("finite_number", "float_parsing", "int_parsing"):
            code = "invalid_number"
        errors.append(
            {
                "code": code,
                "message": err.get("msg", "Invalid request."),
                "field": field,
            }
        )
    return JSONResponse(status_code=422, content={"errors": errors})


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


def _build_variables(ureg: Any, variables: dict[str, Any]) -> dict[str, tuple[Any, str]]:
    built: dict[str, tuple[Any, str]] = {}
    for name, var in variables.items():
        field = f"/variables/{name}/unit"
        unit, meta = parse_unit(var.unit, ureg, field=field)
        quantity = ureg.Quantity(var.value, unit)
        if meta["kind"] == "absolute":
            kelvin = quantity.to("kelvin")
            if float(kelvin.magnitude) < 0:
                raise APIError(
                    "temperature_not_negative",
                    f"Absolute temperature variable {name!r} must not be negative "
                    f"(got {var.value} {var.unit}, below 0 K).",
                    field=f"/variables/{name}/value",
                )
            built[name] = (kelvin, "abs")
        elif meta["kind"] == "delta":
            built[name] = (quantity, "delta")
        else:
            built[name] = (quantity, "plain")
    return built


def _dimensionality(quantity: Any) -> dict[str, int]:
    return {name.strip("[]"): int(exp) for name, exp in quantity.dimensionality.items()}


def _display_unit(quantity: Any) -> str:
    """用白名单符号渲染结果单位，避免内部规范名（如 diff_degC、kilometer）泄漏。

    直接遍历 UnitsContainer（规范名 -> 指数），逐项映射后按 pint 默认风格拼回。
    """
    canonical_to_symbol = {v: k for k, v in _UNIT_CANONICAL.items()}
    container = dict(quantity.units._units)
    if not container:
        return "dimensionless"
    positives = [f"{canonical_to_symbol[name]}{_render_exp(exp)}" for name, exp in container.items() if exp > 0]
    negatives = [f"{canonical_to_symbol[name]}{_render_exp(-exp)}" for name, exp in container.items() if exp < 0]
    numerator = " * ".join(positives) if positives else "1"
    if not negatives:
        return numerator
    denominator = " / ".join(negatives)
    if len(negatives) == 1:
        return f"{numerator} / {denominator}"
    return f"{numerator} / ({denominator})"


def _render_exp(exp: int) -> str:
    return f" ** {exp}" if exp != 1 else ""


@app.post("/v1/evaluate", response_model=EvaluateResponse)
async def evaluate(req: EvaluateRequest) -> EvaluateResponse:
    ureg = get_registry()

    # 1. 算式（语法错误带算式位置）
    ast = parse_expression(req.expression)

    # 2. 变量单位与变量构造
    bound = _build_variables(ureg, req.variables)

    # 3. 求值
    result, kind = Evaluator(ureg, bound).evaluate(ast)

    # 绝对温度结果不得为负（低于 0 K）
    if kind == "abs" and float(result.to("kelvin").magnitude) < 0:
        raise APIError(
            "temperature_not_negative",
            "Resulting absolute temperature is negative (below 0 K).",
            field="/expression",
        )

    # 4. 目标单位
    target_unit, target_meta = parse_unit(req.target_unit, ureg, field="/target_unit")

    # 5. 结果类别与目标单位兼容性
    if kind == "abs" and target_meta["kind"] != "absolute":
        raise APIError(
            "incompatible_unit",
            "Result is an absolute temperature; target_unit must be K, degC or degF.",
            field="/target_unit",
        )
    if kind != "abs" and target_meta["kind"] == "absolute":
        raise APIError(
            "incompatible_unit",
            "Result is not an absolute temperature; target_unit K/degC/degF is not applicable. "
            "Use delta_K/delta_degC/delta_degF for a temperature difference.",
            field="/target_unit",
        )

    try:
        converted = result.to(target_unit)
    except Exception as exc:
        raise APIError(
            "incompatible_unit",
            f"Result cannot be converted to target unit {req.target_unit!r}: {exc}",
            field="/target_unit",
        )

    magnitude = float(converted.magnitude)
    if not math.isfinite(magnitude):
        raise APIError(
            "evaluation_error",
            "Converted result is not finite.",
            field="/expression",
        )

    return EvaluateResponse(
        value=magnitude,
        unit=_display_unit(converted),
        dimensionality=_dimensionality(converted),
        kind={"abs": "absolute", "delta": "delta", "plain": "plain"}[kind],
    )
