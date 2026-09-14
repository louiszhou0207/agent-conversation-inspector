# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou

"""manifest 可选增强：读取输入目录下的 manifest.json 元信息。

运营人员从目标机器拉回数据时，若同时提供了 manifest.json（机器名、扫描
用户、生成时间等），CLI 用它增强报告 meta。该文件是可选的：不存在或内容
非法时返回 None，调用方自行兜底，绝不抛异常。
"""

import json
from pathlib import Path
from typing import Optional


def load_manifest(input_dir) -> Optional[dict]:
    """读取 input_dir/manifest.json。

    返回解析出的 dict（机器名、用户、生成时间等字段原样保留）；文件不存在、
    内容不是合法 JSON、或顶层不是 object 时返回 None，不抛异常。
    """
    p = Path(input_dir) / "manifest.json"
    try:
        # utf-8-sig 兼容带 BOM 与不带 BOM 的 UTF-8（Windows 工具常写 BOM）
        with open(p, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
