# 离线量纲公式求值 API

基于 **Python + FastAPI + [Pint](https://pint.readthedocs.io/)** 的单机离线服务：
接收算术表达式、带单位的变量与目标单位，完成量纲检查、温度特殊语义处理和单位换算，
返回数值、单位与量纲。无需任何外部网络服务，单位定义随镜像内置。

## 一键启动

需要本机装有 Docker（含 Compose 插件）。

```bash
docker compose up --build
```

服务启动后监听在本机 **8000 端口**：

- 接口地址：`http://localhost:8000/v1/evaluate`
- 健康检查：`http://localhost:8000/healthz`
- 交互式文档（Swagger UI）：`http://localhost:8000/docs`

后台运行可用 `docker compose up --build -d`，查看日志 `docker compose logs -f`，停止 `docker compose down`。

## 请求

`POST /v1/evaluate`，`Content-Type: application/json`：

```json
{
  "expression": "d / t",
  "variables": {
    "d": {"value": 100, "unit": "m"},
    "t": {"value": 10, "unit": "s"}
  },
  "target_unit": "km/h"
}
```

| 字段 | 说明 |
| --- | --- |
| `expression` | 算式字符串，只允许数字、变量名、括号、一元正负号与二元 `+ - * /` |
| `variables` | 变量名到 `{ "value": 有限数值, "unit": 单位串 }` 的映射；可省略 |
| `target_unit` | 目标单位，白名单单位组成的乘除式（支持括号、重复乘除），或 `1`（无量纲） |

### 表达式规则

- 允许：整数/小数/科学计数法（`1e3`、`.5`）、变量（字母/下划线开头）、`( )`、一元 `+`/`-`、`+ - * /`
- **禁止函数调用**：`sin(x)` 返回 422
- **禁止隐式乘法**：`2 x`、`x (y)` 必须写成 `2 * x`、`x * (y)`
- 没有幂运算符（`**`、`^` 均非法）；需要平方请写成 `x * x`
- 错误信息中的 `position` 是从 0 开始、按原始字符串（含空格）计算的字符偏移

### 支持的单位

| 类别 | 单位 |
| --- | --- |
| 长度 | `m` `cm` `km` |
| 时间 | `s` `min` `h` |
| 质量 | `kg` `g` |
| 绝对温度 | `K` `degC` `degF` |
| 温差 | `delta_K` `delta_degC` `delta_degF` |

单位大小写敏感。变量单位与目标单位都可以是乘除复合式，例如 `kg*m/s/s`、`m/s`、`delta_K/min`，
或单独的 `1`（表示无量纲，不能与其它单位组合）。
`degC`、`degF` 带固定偏移，只能作为单位独使用；`K` 偏移为 0，允许出现在复合式中（与 `delta_K` 等价互换）。

## 温度语义

实现遵循以下规则（普通单位只做常规量纲检查）：

1. **加减法必须量纲相同**（先各自换算到基准量纲）；量纲不兼容报 422。
2. **乘除法组合量纲**，零除报 422，位置指向 `/` 运算符。
3. **绝对温度 ± 温差 → 绝对温度**。温差可分别用 `delta_K` / `delta_degC` / `delta_degF` 给出，自动按 1 K = 1 °C = 9/5 °F 的温差比例换算。
4. **两个绝对温度只能相减**，结果为**温差**；相加非法。
5. **绝对温度不得取负**（一元 `-`），也**不得参与乘除**。
6. 温差可以自由取负、加减与乘除（如温升速率 `delta_K/s`）。
7. 结果按目标单位换算：绝对温度结果只接受 `K`/`degC`/`degF` 目标；温差结果不能用绝对温度目标（反之亦然）。

## 响应

成功返回 `200`：

```json
{
  "value": 36.0,
  "unit": "km / h",
  "dimensionality": {"length": 1, "time": -1},
  "kind": "plain"
}
```

- `value`：换算到目标单位后的浮点数值
- `unit`：结果单位（使用请求中的白名单符号，如 `delta_degC`）
- `dimensionality`：基本量纲指数（键为 `length` / `time` / `mass` / `temperature`，无量纲时为 `{}`）
- `kind`：`absolute`（绝对温度）、`delta`（纯温差）或 `plain`（其它）

## 错误（全部返回 422）

响应体形如：

```json
{
  "errors": [
    {
      "code": "invalid_expression",
      "message": "Function calls are not allowed: 'sin' at position 4.",
      "field": "/expression",
      "position": 4
    }
  ]
}
```

- `field`：出错字段的 JSON Pointer（如 `/expression`、`/variables/x/unit`、`/target_unit`）
- `position`：当错误指向算式或单位串时，给出从 0 开始的字符偏移
- 主要错误码：
  - `invalid_expression`：非法字符、函数调用、隐式乘法、括号不匹配、空算式等
  - `unknown_variable`：算式引用了未在 `variables` 中提供的变量
  - `invalid_unit`：单位串中出现非白名单单位或非法结构
  - `incompatible_unit`：带偏移温度单位被复合、结果类别与目标单位不匹配、目标单位量纲不兼容
  - `incompatible_dimension`：加减两侧量纲不同
  - `temperature_op_not_allowed`：绝对温度相加/取负/乘除等非法温度运算
  - `temperature_not_negative`：绝对温度输入或运算结果为负（低于 0 K）
  - `division_by_zero`：除数为零
  - `missing_field` / `invalid_number` / `invalid_request`：请求体结构与数值校验错误

## 示例

绝对温度加减温差（20 °C 升高 5 °C，输出华氏度）：

```bash
curl -s http://localhost:8000/v1/evaluate \
  -H 'Content-Type: application/json' \
  -d '{
    "expression": "t + d",
    "variables": {
      "t": {"value": 20, "unit": "degC"},
      "d": {"value": 5, "unit": "delta_degC"}
    },
    "target_unit": "degF"
  }'
# {"value":77.0,"unit":"degF","dimensionality":{"temperature":1},"kind":"absolute"}
```

两绝对温度之差是温差（212 °F − 100 °C = 180 delta_degF = 100 delta_degC）：

```bash
curl -s http://localhost:8000/v1/evaluate \
  -H 'Content-Type: application/json' \
  -d '{
    "expression": "hot - cold",
    "variables": {
      "hot": {"value": 212, "unit": "degF"},
      "cold": {"value": 100, "unit": "degC"}
    },
    "target_unit": "delta_degC"
  }'
# {"value":100.0,...,"kind":"delta"}
```

非法算式（函数调用）返回带位置的 422：

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/v1/evaluate \
  -H 'Content-Type: application/json' \
  -d '{"expression":"sin(x)","variables":{"x":{"value":1,"unit":"1"}},"target_unit":"1"}'
# 422
```

## 本地开发与测试（不用 Docker）

需要 Python 3.11+：

```bash
python -m pip install -r requirements.txt
python -m pip install pytest httpx
PYTHONPATH=. python -m pytest -q
uvicorn app.main:app --reload --port 8000
```

## 项目结构

```
app/
  main.py        # FastAPI 路由、请求校验、结果换算与错误处理
  expression.py  # 算式词法/语法分析（递归下降，记录错误位置）
  unit_expr.py   # 单位串词法/语法分析（白名单 + 乘除复合）
  evaluator.py   # AST 求值与温度语义（abs / delta / plain 三分法）
  registry.py    # Pint UnitRegistry（加载内置白名单定义）
  units.txt      # 离线白名单单位定义
  errors.py      # 统一 422 异常
  schemas.py     # 请求/响应模型
tests/test_api.py
Dockerfile
docker-compose.yml
requirements.txt
```
