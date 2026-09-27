"""FastAPI 应用入口：POST /v1/evaluate。"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .errors import EvalError
from .evaluator import convert_result, evaluate, value_from_unit
from .expression import parse_expression
from .models import EvalRequest, EvalResponse
from .units import ALLOWED_UNITS, parse_target

app = FastAPI(
    title="量纲公式求值 API",
    version="1.0.0",
    description="离线量纲公式求值：解析算术算式，按单位代数求值并换算到目标单位。",
)


@app.exception_handler(EvalError)
async def eval_error_handler(_: Request, exc: EvalError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": [{"type": exc.type, "loc": exc.loc, "msg": exc.msg}]},
    )


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/v1/evaluate", response_model=EvalResponse)
def evaluate_endpoint(req: EvalRequest) -> EvalResponse:
    ast = parse_expression(req.expression)

    env: dict = {}
    for name, var in req.variables.items():
        if var.unit not in ALLOWED_UNITS:
            raise EvalError.at_variable(
                "unknown_unit",
                name,
                "unit",
                f"变量 {name!r} 的单位 {var.unit!r} 不受支持，"
                f"可用单位：{', '.join(sorted(ALLOWED_UNITS))}",
            )
        env[name] = value_from_unit(var.value, var.unit)

    result = evaluate(ast, env)

    target = parse_target(req.target_unit)
    value, dimension = convert_result(result, target)
    return EvalResponse(value=value, unit=target.canonical, dimension=dimension)
