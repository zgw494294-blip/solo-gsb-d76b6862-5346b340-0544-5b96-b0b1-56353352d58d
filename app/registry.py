"""Pint 单位注册表：仅加载本项目自带的白名单定义文件，离线可用。"""

from __future__ import annotations

import os
from functools import lru_cache

from pint import UnitRegistry

_UNITS_FILE = os.path.join(os.path.dirname(__file__), "units.txt")


@lru_cache(maxsize=1)
def get_registry() -> UnitRegistry:
    # case_sensitive=True：避免 s/S、m/M 之类的意外别名
    return UnitRegistry(_UNITS_FILE, case_sensitive=True)
