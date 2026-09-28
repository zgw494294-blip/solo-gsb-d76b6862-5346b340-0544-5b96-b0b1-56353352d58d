"""端到端测试：使用 FastAPI TestClient。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def post(body: dict) -> dict:
    resp = client.post("/v1/evaluate", json=body)
    return resp


# ---------- 基本量纲换算 ----------

def test_length_arithmetic_and_convert():
    r = post(
        {
            "expression": "x + y",
            "variables": {"x": {"value": 1, "unit": "km"}, "y": {"value": 500, "unit": "m"}},
            "target_unit": "m",
        }
    )
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["value"] == pytest.approx(1500.0)
    assert b["unit"] == "m"
    assert b["dimensionality"] == {"length": 1}
    assert b["kind"] == "plain"


def test_multiply_divide_composite_dimension():
    r = post(
        {
            "expression": "d / t",
            "variables": {"d": {"value": 100, "unit": "m"}, "t": {"value": 10, "unit": "s"}},
            "target_unit": "km/h",
        }
    )
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["value"] == pytest.approx(36.0)
    assert b["dimensionality"] == {"length": 1, "time": -1}


def test_mass_conversion():
    r = post(
        {
            "expression": "a + b",
            "variables": {"a": {"value": 1, "unit": "kg"}, "b": {"value": 250, "unit": "g"}},
            "target_unit": "g",
        }
    )
    assert r.status_code == 200, r.text
    assert r.json()["value"] == pytest.approx(1250.0)


def test_dimensionless_target_one():
    r = post(
        {
            "expression": "x / y",
            "variables": {"x": {"value": 6, "unit": "m"}, "y": {"value": 3, "unit": "m"}},
            "target_unit": "1",
        }
    )
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["value"] == pytest.approx(2.0)
    assert b["dimensionality"] == {}


def test_unary_signs_and_parentheses_and_pure_numbers():
    r = post(
        {
            "expression": "-(a + b) * 2 + 3*c",
            "variables": {
                "a": {"value": 1, "unit": "m"},
                "b": {"value": 2, "unit": "m"},
                "c": {"value": 1, "unit": "m"},
            },
            "target_unit": "m",
        }
    )
    assert r.status_code == 200, r.text
    assert r.json()["value"] == pytest.approx(-3.0)


def test_time_units():
    r = post(
        {
            "expression": "h - m",
            "variables": {"h": {"value": 1, "unit": "h"}, "m": {"value": 30, "unit": "min"}},
            "target_unit": "s",
        }
    )
    assert r.status_code == 200, r.text
    assert r.json()["value"] == pytest.approx(1800.0)


# ---------- 温度语义 ----------

def test_absolute_plus_delta_celsius():
    r = post(
        {
            "expression": "t + d",
            "variables": {"t": {"value": 20, "unit": "degC"}, "d": {"value": 5, "unit": "delta_degC"}},
            "target_unit": "degF",
        }
    )
    assert r.status_code == 200, r.text
    assert r.json()["value"] == pytest.approx(77.0)
    assert r.json()["kind"] == "absolute"


def test_absolute_minus_delta_fahrenheit():
    r = post(
        {
            "expression": "t - d",
            "variables": {"t": {"value": 32, "unit": "degF"}, "d": {"value": 9, "unit": "delta_degF"}},
            "target_unit": "degC",
        }
    )
    assert r.status_code == 200, r.text
    assert r.json()["value"] == pytest.approx(-5.0)
    assert r.json()["kind"] == "absolute"


def test_delta_plus_absolute():
    r = post(
        {
            "expression": "d + t",
            "variables": {"d": {"value": 10, "unit": "delta_K"}, "t": {"value": 0, "unit": "degC"}},
            "target_unit": "degC",
        }
    )
    assert r.status_code == 200, r.text
    assert r.json()["value"] == pytest.approx(10.0)
    assert r.json()["kind"] == "absolute"


def test_absolute_minus_absolute_is_delta():
    r = post(
        {
            "expression": "hot - cold",
            "variables": {"hot": {"value": 100, "unit": "degC"}, "cold": {"value": 0, "unit": "degC"}},
            "target_unit": "delta_degF",
        }
    )
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["value"] == pytest.approx(180.0)
    assert b["kind"] == "delta"
    assert b["dimensionality"] == {"temperature": 1}


def test_absolute_minus_absolute_mixed_scales():
    r = post(
        {
            "expression": "a - b",
            "variables": {"a": {"value": 212, "unit": "degF"}, "b": {"value": 100, "unit": "degC"}},
            "target_unit": "delta_K",
        }
    )
    assert r.status_code == 200, r.text
    assert r.json()["value"] == pytest.approx(0.0, abs=1e-9)
    assert r.json()["kind"] == "delta"


def test_kelvin_absolute_minus_absolute():
    r = post(
        {
            "expression": "a - b",
            "variables": {"a": {"value": 300, "unit": "K"}, "b": {"value": 273.15, "unit": "K"}},
            "target_unit": "delta_degC",
        }
    )
    assert r.status_code == 200, r.text
    assert r.json()["value"] == pytest.approx(26.85)
    assert r.json()["kind"] == "delta"


def test_absolute_plus_absolute_rejected():
    r = post(
        {
            "expression": "a + b",
            "variables": {"a": {"value": 1, "unit": "K"}, "b": {"value": 1, "unit": "K"}},
            "target_unit": "K",
        }
    )
    assert r.status_code == 422
    b = r.json()["errors"][0]
    assert b["code"] == "temperature_op_not_allowed"
    assert b["position"] == 2  # '+' in "a + b"


def test_negate_absolute_rejected():
    r = post(
        {
            "expression": "-t",
            "variables": {"t": {"value": 10, "unit": "degC"}},
            "target_unit": "degC",
        }
    )
    assert r.status_code == 422
    b = r.json()["errors"][0]
    assert b["code"] == "temperature_op_not_allowed"
    assert b["position"] == 0


def test_absolute_multiply_rejected():
    r = post(
        {
            "expression": "t * 2",
            "variables": {"t": {"value": 10, "unit": "K"}},
            "target_unit": "K",
        }
    )
    assert r.status_code == 422
    b = r.json()["errors"][0]
    assert b["code"] == "temperature_op_not_allowed"
    assert b["position"] == 2


def test_absolute_divide_rejected():
    r = post(
        {
            "expression": "2 / t",
            "variables": {"t": {"value": 10, "unit": "degC"}},
            "target_unit": "1",
        }
    )
    assert r.status_code == 422
    assert r.json()["errors"][0]["code"] == "temperature_op_not_allowed"


def test_delta_minus_absolute_rejected():
    r = post(
        {
            "expression": "d - t",
            "variables": {"d": {"value": 1, "unit": "delta_K"}, "t": {"value": 1, "unit": "K"}},
            "target_unit": "K",
        }
    )
    assert r.status_code == 422
    assert r.json()["errors"][0]["code"] == "temperature_op_not_allowed"


def test_absolute_plus_plain_rejected():
    r = post(
        {
            "expression": "t + n",
            "variables": {"t": {"value": 1, "unit": "K"}, "n": {"value": 1, "unit": "1"}},
            "target_unit": "K",
        }
    )
    assert r.status_code == 422
    assert r.json()["errors"][0]["code"] == "incompatible_dimension"


def test_delta_arithmetic():
    r = post(
        {
            "expression": "a + b",
            "variables": {"a": {"value": 5, "unit": "delta_K"}, "b": {"value": 9, "unit": "delta_degF"}},
            "target_unit": "delta_degC",
        }
    )
    assert r.status_code == 200, r.text
    # 9 delta_degF = 5 K
    assert r.json()["value"] == pytest.approx(10.0)
    assert r.json()["kind"] == "delta"


def test_composite_delta_target():
    # K/s 加热速率
    r = post(
        {
            "expression": "dt / t",
            "variables": {"dt": {"value": 10, "unit": "delta_K"}, "t": {"value": 5, "unit": "s"}},
            "target_unit": "delta_degC/min",
        }
    )
    assert r.status_code == 200, r.text
    assert r.json()["value"] == pytest.approx(120.0)
    assert r.json()["kind"] == "plain"


def test_absolute_target_for_delta_result_rejected():
    r = post(
        {
            "expression": "a - b",
            "variables": {"a": {"value": 2, "unit": "K"}, "b": {"value": 1, "unit": "K"}},
            "target_unit": "degC",
        }
    )
    assert r.status_code == 422
    e = r.json()["errors"][0]
    assert e["code"] == "incompatible_unit"
    assert e["field"] == "/target_unit"


def test_delta_target_for_absolute_result_rejected():
    r = post(
        {
            "expression": "t",
            "variables": {"t": {"value": 0, "unit": "degC"}},
            "target_unit": "delta_K",
        }
    )
    assert r.status_code == 422
    assert r.json()["errors"][0]["field"] == "/target_unit"


# ---------- 零除与量纲不兼容 ----------

def test_division_by_zero_variable():
    r = post(
        {
            "expression": "a / b",
            "variables": {"a": {"value": 1, "unit": "m"}, "b": {"value": 0, "unit": "s"}},
            "target_unit": "m/s",
        }
    )
    assert r.status_code == 422
    e = r.json()["errors"][0]
    assert e["code"] == "division_by_zero"
    assert e["position"] == 2


def test_division_by_zero_literal():
    r = post(
        {
            "expression": "1/0",
            "variables": {},
            "target_unit": "1",
        }
    )
    assert r.status_code == 422
    assert r.json()["errors"][0]["code"] == "division_by_zero"


def test_incompatible_addition():
    r = post(
        {
            "expression": "a + b",
            "variables": {"a": {"value": 1, "unit": "m"}, "b": {"value": 1, "unit": "s"}},
            "target_unit": "m",
        }
    )
    assert r.status_code == 422
    e = r.json()["errors"][0]
    assert e["code"] == "incompatible_dimension"
    assert e["position"] == 2


def test_incompatible_target_unit():
    r = post(
        {
            "expression": "a",
            "variables": {"a": {"value": 1, "unit": "m"}},
            "target_unit": "s",
        }
    )
    assert r.status_code == 422
    e = r.json()["errors"][0]
    assert e["code"] == "incompatible_unit"
    assert e["field"] == "/target_unit"


# ---------- 算式错误（带位置） ----------

def test_function_call_rejected():
    r = post(
        {
            "expression": "sin(x)",
            "variables": {"x": {"value": 1, "unit": "1"}},
            "target_unit": "1",
        }
    )
    assert r.status_code == 422
    e = r.json()["errors"][0]
    assert e["code"] == "invalid_expression"
    assert e["position"] == 3  # '(' after sin


def test_implicit_multiplication_rejected():
    r = post(
        {
            "expression": "2 x",
            "variables": {"x": {"value": 1, "unit": "m"}},
            "target_unit": "m",
        }
    )
    assert r.status_code == 422
    e = r.json()["errors"][0]
    assert e["code"] == "invalid_expression"
    assert "Implicit multiplication" in e["message"]
    assert e["position"] == 2


def test_parenthesized_implicit_multiplication():
    r = post(
        {
            "expression": "x (y)",
            "variables": {
                "x": {"value": 1, "unit": "m"},
                "y": {"value": 1, "unit": "m"},
            },
            "target_unit": "m",
        }
    )
    assert r.status_code == 422
    e = r.json()["errors"][0]
    assert e["code"] == "invalid_expression"
    assert e["position"] == 2


def test_power_operator_rejected():
    r = post({"expression": "x**2", "variables": {"x": {"value": 2, "unit": "m"}}, "target_unit": "m"})
    assert r.status_code == 422
    e = r.json()["errors"][0]
    assert e["code"] == "invalid_expression"
    # "x**2"：第一个 '*' 作为乘号被消费，第二个 '*' 位置即非法处
    assert e["position"] == 2


def test_illegal_character():
    r = post({"expression": "x @ 2", "variables": {"x": {"value": 1, "unit": "1"}}, "target_unit": "1"})
    assert r.status_code == 422
    assert r.json()["errors"][0]["position"] == 2


def test_empty_expression():
    r = post({"expression": "  ", "variables": {}, "target_unit": "1"})
    assert r.status_code == 422
    assert r.json()["errors"][0]["field"] == "/expression"


def test_unbalanced_parentheses():
    r = post({"expression": "(1 + 2", "variables": {}, "target_unit": "1"})
    assert r.status_code == 422
    assert r.json()["errors"][0]["position"] == 6


def test_trailing_operator():
    r = post({"expression": "1 +", "variables": {}, "target_unit": "1"})
    assert r.status_code == 422
    assert r.json()["errors"][0]["field"] == "/expression"


def test_double_operator():
    r = post({"expression": "1 * / 2", "variables": {}, "target_unit": "1"})
    assert r.status_code == 422


# ---------- 变量与单位错误 ----------

def test_unknown_variable_points_to_field_and_position():
    r = post({"expression": "a + b", "variables": {"a": {"value": 1, "unit": "m"}}, "target_unit": "m"})
    assert r.status_code == 422
    e = r.json()["errors"][0]
    assert e["code"] == "unknown_variable"
    assert e["field"] == "/variables/b"
    assert e["position"] == 4  # 'b' in "a + b"


def test_unknown_variable_unit():
    r = post(
        {
            "expression": "x",
            "variables": {"x": {"value": 1, "unit": "ft"}},
            "target_unit": "m",
        }
    )
    assert r.status_code == 422
    e = r.json()["errors"][0]
    assert e["code"] == "invalid_unit"
    assert e["field"] == "/variables/x/unit"


def test_unknown_target_unit():
    r = post(
        {
            "expression": "x",
            "variables": {"x": {"value": 1, "unit": "m"}},
            "target_unit": "mile",
        }
    )
    assert r.status_code == 422
    e = r.json()["errors"][0]
    assert e["code"] == "invalid_unit"
    assert e["field"] == "/target_unit"
    assert e["position"] == 0


def test_offset_unit_in_composite_rejected():
    r = post(
        {
            "expression": "x",
            "variables": {"x": {"value": 1, "unit": "m*degC/s"}},
            "target_unit": "m",
        }
    )
    assert r.status_code == 422
    e = r.json()["errors"][0]
    assert e["code"] == "incompatible_unit"
    assert e["field"] == "/variables/x/unit"


def test_kelvin_composite_unit_allowed():
    # K 偏移为 0，可作为温差参与复合量纲（等价 delta_K）
    r = post(
        {
            "expression": "dt / t",
            "variables": {"dt": {"value": 10, "unit": "delta_K"}, "t": {"value": 1, "unit": "min"}},
            "target_unit": "K/s",
        }
    )
    assert r.status_code == 200, r.text
    assert r.json()["value"] == pytest.approx(10 / 60)
    assert r.json()["dimensionality"] == {"temperature": 1, "time": -1}

    r2 = post(
        {
            "expression": "x",
            "variables": {"x": {"value": 1, "unit": "K*s"}},
            "target_unit": "delta_K*s",
        }
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["value"] == pytest.approx(1.0)


def test_dimensionless_one_combo_rejected():
    r = post(
        {
            "expression": "x",
            "variables": {"x": {"value": 1, "unit": "1*m"}},
            "target_unit": "m",
        }
    )
    assert r.status_code == 422
    assert r.json()["errors"][0]["field"] == "/variables/x/unit"


def test_case_sensitive_unknown_unit():
    # S 不是合法单位（s 才是）
    r = post(
        {
            "expression": "x",
            "variables": {"x": {"value": 1, "unit": "S"}},
            "target_unit": "s",
        }
    )
    assert r.status_code == 422
    assert r.json()["errors"][0]["code"] == "invalid_unit"


# ---------- 请求层校验 ----------

def test_missing_field():
    resp = client.post("/v1/evaluate", json={"expression": "1"})
    assert resp.status_code == 422
    errors = resp.json()["errors"]
    assert any(e["field"] == "/target_unit" and e["code"] == "missing_field" for e in errors)


def test_non_finite_value_rejected():
    r = post(
        {
            "expression": "x",
            "variables": {"x": {"value": "nan", "unit": "m"}},
            "target_unit": "m",
        }
    )
    assert r.status_code == 422


def test_unknown_top_level_field():
    r = post(
        {
            "expression": "1",
            "variables": {},
            "target_unit": "1",
            "extra": 1,
        }
    )
    assert r.status_code == 422


# ---------- 其它 ----------

def test_healthz():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_openapi_available():
    resp = client.get("/openapi.json")
    assert resp.status_code == 200


def test_scientific_notation_numbers():
    r = post(
        {
            "expression": "1e3 + 2.5e2",
            "variables": {},
            "target_unit": "1",
        }
    )
    assert r.status_code == 200, r.text
    assert r.json()["value"] == pytest.approx(1250.0)


def test_leading_dot_number():
    r = post({"expression": ".5 + .25", "variables": {}, "target_unit": "1"})
    assert r.status_code == 200
    assert r.json()["value"] == pytest.approx(0.75)


def test_nested_composite_units_and_fahrenheit_identity():
    # 212 degF 与 100 degC 是同一绝对温度，输出 degF
    r = post(
        {
            "expression": "t",
            "variables": {"t": {"value": 100, "unit": "degC"}},
            "target_unit": "degF",
        }
    )
    assert r.status_code == 200
    assert r.json()["value"] == pytest.approx(212.0)


def test_delta_fahrenheit_identity():
    r = post(
        {
            "expression": "d",
            "variables": {"d": {"value": 180, "unit": "delta_degF"}},
            "target_unit": "delta_degC",
        }
    )
    assert r.status_code == 200
    assert r.json()["value"] == pytest.approx(100.0)


def test_force_unit_expression_newton():
    r = post(
        {
            "expression": "m*a",
            "variables": {
                "m": {"value": 2, "unit": "kg"},
                "a": {"value": 3, "unit": "m/s/s"},
            },
            "target_unit": "kg*m/s/s",
        }
    )
    assert r.status_code == 200, r.text
    assert r.json()["value"] == pytest.approx(6.0)
    assert r.json()["dimensionality"] == {"mass": 1, "length": 1, "time": -2}


def test_whitespace_positions_counted():
    # 位置按原始字符串字符偏移（含空格）
    r = post({"expression": "1   ?", "variables": {}, "target_unit": "1"})
    assert r.status_code == 422
    assert r.json()["errors"][0]["position"] == 4


def test_output_unit_uses_whitelist_symbols():
    r = post(
        {
            "expression": "d / t",
            "variables": {"d": {"value": 100, "unit": "m"}, "t": {"value": 10, "unit": "s"}},
            "target_unit": "km/h",
        }
    )
    assert r.status_code == 200
    assert r.json()["unit"] == "km / h"

    r2 = post(
        {
            "expression": "m*a",
            "variables": {"m": {"value": 2, "unit": "kg"}, "a": {"value": 3, "unit": "m/s/s"}},
            "target_unit": "kg*m/s/s",
        }
    )
    assert r2.status_code == 200
    assert r2.json()["unit"] == "kg * m / s ** 2"

    r3 = post(
        {
            "expression": "x/y",
            "variables": {"x": {"value": 6, "unit": "m"}, "y": {"value": 3, "unit": "m"}},
            "target_unit": "1",
        }
    )
    assert r3.status_code == 200
    assert r3.json()["unit"] == "dimensionless"


def test_no_variables_needed_for_pure_arithmetic():
    r = post({"expression": "(1 + 2) * 3 - 4 / 2", "variables": {}, "target_unit": "1"})
    assert r.status_code == 200, r.text
    assert r.json()["value"] == pytest.approx(7.0)


def test_unit_alias_boundary_mile():
    # mile 不允许被误识别为 min
    r = post(
        {
            "expression": "x",
            "variables": {"x": {"value": 1, "unit": "mile"}},
            "target_unit": "m",
        }
    )
    assert r.status_code == 422
    e = r.json()["errors"][0]
    assert e["code"] == "invalid_unit"
    assert e["field"] == "/variables/x/unit"
    assert e["position"] == 0


def test_abs_abs_subtraction_position():
    r = post(
        {
            "expression": "a   -   b",
            "variables": {"a": {"value": 1, "unit": "K"}, "b": {"value": 1, "unit": "K"}},
            "target_unit": "delta_K",
        }
    )
    assert r.status_code == 200, r.text
    # '-' 在第 4 列（0 基，含空格）
    # 这里只校验成功与值，位置由非法场景测试覆盖
    assert r.json()["value"] == pytest.approx(0.0, abs=1e-12)


def test_fahrenheit_delta_conversion_factor():
    # 9 delta_degF == 5 delta_K == 5 delta_degC
    r = post(
        {
            "expression": "d",
            "variables": {"d": {"value": 9, "unit": "delta_degF"}},
            "target_unit": "delta_K",
        }
    )
    assert r.status_code == 200
    assert r.json()["value"] == pytest.approx(5.0)


def test_addition_with_incompatible_variable_dimensions_points_to_operator():
    r = post(
        {
            "expression": "a + b",
            "variables": {"a": {"value": 1, "unit": "kg"}, "b": {"value": 1, "unit": "m"}},
            "target_unit": "kg",
        }
    )
    assert r.status_code == 422
    e = r.json()["errors"][0]
    assert e["code"] == "incompatible_dimension"
    assert e["position"] == 2
    assert e["field"] == "/expression"


def test_negative_absolute_temperature_input_rejected():
    r = post(
        {
            "expression": "t",
            "variables": {"t": {"value": -100, "unit": "K"}},
            "target_unit": "K",
        }
    )
    assert r.status_code == 422
    e = r.json()["errors"][0]
    assert e["code"] == "temperature_not_negative"
    assert e["field"] == "/variables/t/value"

    r2 = post(
        {
            "expression": "t",
            "variables": {"t": {"value": -300, "unit": "degC"}},
            "target_unit": "K",
        }
    )
    assert r2.status_code == 422
    assert r2.json()["errors"][0]["code"] == "temperature_not_negative"


def test_absolute_temperature_result_below_zero_rejected():
    r = post(
        {
            "expression": "t - d",
            "variables": {"t": {"value": 0, "unit": "K"}, "d": {"value": 10, "unit": "delta_K"}},
            "target_unit": "K",
        }
    )
    assert r.status_code == 422
    assert r.json()["errors"][0]["code"] == "temperature_not_negative"


def test_zero_kelvin_is_valid():
    r = post(
        {
            "expression": "t",
            "variables": {"t": {"value": 0, "unit": "K"}},
            "target_unit": "degC",
        }
    )
    assert r.status_code == 200
    assert r.json()["value"] == pytest.approx(-273.15)
