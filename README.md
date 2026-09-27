# 量纲公式求值 API

离线运行的量纲公式求值服务：接收一个算术算式、一组带单位的变量和一个目标单位，
按单位代数（dimensional algebra）求值并把结果换算到目标单位，返回数值与量纲。

技术栈：Python 3.11+ · FastAPI · Pint · Uvicorn。全程本地计算，不访问任何外部服务。

## 快速开始（一条命令）

```bash
docker compose up --build
```

服务启动后监听本地 **8000** 端口：

- 接口地址：`http://localhost:8000/v1/evaluate`
- 交互式文档（Swagger UI）：`http://localhost:8000/docs`
- 健康检查：`http://localhost:8000/healthz`

不使用 Docker 的本地运行方式：

```bash
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

## API

### `POST /v1/evaluate`

请求体：

```json
{
  "expression": "dist / time",
  "variables": {
    "dist": { "value": 36, "unit": "km" },
    "time": { "value": 2,  "unit": "h" }
  },
  "target_unit": "m/s"
}
```

| 字段 | 说明 |
| --- | --- |
| `expression` | 算式：只允许数字、变量、括号、一元正负号与 `+ - * /` |
| `variables` | 变量名 → `{value, unit}`；`value` 必须是有限数值（拒绝 inf/NaN/布尔） |
| `target_unit` | 目标单位：受支持单位组成的乘除式（可用括号与整数幂 `^`/`**`），或 `1` 表示无量纲 |

成功响应 `200`：

```json
{ "value": 5.0, "unit": "m/s", "dimension": "[length] / [time]" }
```

- `value`：按目标单位换算后的数值
- `unit`：归一化后的目标单位
- `dimension`：结果量纲（无量纲时为 `dimensionless`）

更多示例：

```bash
# 温度：10 °C 加上 18 Δ°F（=10 Δ°C），结果为 20 °C
curl -X POST http://localhost:8000/v1/evaluate \
  -H 'Content-Type: application/json' \
  -d '{"expression": "t + d",
       "variables": {"t": {"value": 10, "unit": "degC"},
                     "d": {"value": 18, "unit": "delta_degF"}},
       "target_unit": "degC"}'
# => {"value": 20.0, "unit": "degC", "dimension": "[temperature]"}
```

## 支持的单位

| 类别 | 单位 |
| --- | --- |
| 长度 | `m`、`cm`、`km` |
| 时间 | `s`、`min`、`h` |
| 质量 | `kg`、`g` |
| 绝对温度 | `K`、`degC`、`degF` |
| 温差 | `delta_K`、`delta_degC`、`delta_degF` |

变量单位必须是上表中的单个单位；目标单位可以是这些单位经 `*`、`/`、括号
和整数幂组合成的式子（如 `kg*m/s^2`、`m^2`、`1/(s)`），或 `1`。

## 运算规则

- **加减**：先把两侧换算到相同量纲再合并；量纲不兼容报 422。
- **乘除**：组合两侧量纲；除数为零报 422。
- **绝对温度**（`K`/`degC`/`degF`）：
  - 可加、减温差，结果仍为绝对温度（如 `10 degC + 5 delta_K`）；
  - 两个绝对温度只允许相减，结果为温差（如 `10 degC - 50 degF → 0 delta_K`）；
  - 不得取负（`-t` 报错），不得参与乘除，两个绝对温度不得相加。
- **温差**：视为普通量纲量，可参与四则运算（如 `delta_K / s`）。
- 目标单位换算：绝对温度结果只能换算到 `K`/`degC`/`degF`；非绝对温度结果
  不能换算到绝对温度单位（防止把温差“洗”成绝对温度）。`K` 是无偏移单位，
  可出现在复合目标中（如 `K/s`）；`degC`/`degF` 只能单独作为目标单位。

## 错误格式

所有领域错误返回 `422`，`detail` 中的 `loc` 指向出错字段或算式位置
（算式位置为 0 起的字符偏移量）：

```json
{
  "detail": [
    {
      "type": "incompatible_units",
      "loc": ["body", "expression", 2],
      "msg": "位置 2：加减两侧量纲不兼容：meter 与 second"
    }
  ]
}
```

| `type` | 含义 | `loc` 示例 |
| --- | --- | --- |
| `syntax_error` | 非法算式（非法字符、隐式乘法、函数调用、括号不配对等） | `["body","expression",1]` |
| `invalid_number` | 算式中的数字不是有限值 | `["body","expression",0]` |
| `unknown_variable` | 算式引用了未定义的变量 | `["body","expression",4]` |
| `unknown_unit` | 变量或目标单位使用了不支持的单位 | `["body","variables","x","unit"]` |
| `incompatible_units` | 加减量纲不兼容、结果与目标单位不兼容 | `["body","expression",2]` 或 `["body","target_unit"]` |
| `absolute_temperature` | 违反绝对温度规则（相加、取负、参与乘除等） | `["body","expression",0]` |
| `division_by_zero` | 除数为零 | `["body","expression",2]` |
| `invalid_target_unit` | 目标单位式非法 | `["body","target_unit",3]` |
| `non_finite_result` | 求值结果溢出为非有限值 | `["body","expression"]` |

请求体本身不合法（缺字段、类型错误、非有限数值等）同样返回 422，
由 FastAPI/Pydantic 给出字段级定位。

## 测试

```bash
pip install -r requirements-dev.txt
pytest
```

## 项目结构

```
app/
  main.py        FastAPI 应用与路由（POST /v1/evaluate、GET /healthz）
  models.py      请求/响应模型（有限数值校验）
  expression.py  算式词法/语法分析（递归下降，带位置的错误）
  evaluator.py   量纲求值语义（温度规则、零除、目标换算）
  units.py       Pint 注册表、受支持单位、温度仿射换算、目标单位解析
  errors.py      可定位的领域错误（统一映射为 422）
tests/
  test_api.py    端到端行为测试
Dockerfile
docker-compose.yml
requirements.txt / requirements-dev.txt
```

实现说明：Pint 负责单位注册、量纲追踪与一般量的换算；绝对温度的仿射换算
（`K`/`degC`/`degF` 互转及与温差的加减）由 `app/units.py` 手工实现，以便对
违反温度规则的运算给出指向算式具体位置的 422 错误。`delta_K` 在 Pint 默认
注册表中不存在，启动时以 `delta_K = kelvin` 补充定义。
