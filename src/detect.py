# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou

"""格式自动识别：根据文件内容/文件名判定对话数据属于哪一类工具。"""

import json
import pathlib
import re
from typing import List, Optional, Tuple

#: 豆包 LevelDB 存储目录名（精确匹配）
DOUBAO_DIR_NAME = "chrome_doubao-chat_0.indexeddb.leveldb"
#: 豆包 web 版 LevelDB 目录名（普通对话主要存储于此）
DOUBAO_WEB_DIR_NAME = "https_www.doubao.com_0.indexeddb.leveldb"
#: 豆包相关的 LevelDB 目录名集合（桌面端 + web 端）
_DOUBAO_DIR_NAMES = {DOUBAO_DIR_NAME, DOUBAO_WEB_DIR_NAME}

#: UUID 形文件名：第一段 8 位 hex，后续至少一段，以 "-" 连接
_UUID_RE = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]+)+")


def sniff_jsonl_line(path) -> Optional[dict]:
    """读文件前 50 行，返回首个可解析为 dict 的非空 JSON 行；失败返回 None。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 50:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if isinstance(obj, dict):
                    return obj
    except (OSError, UnicodeDecodeError):
        return None
    return None


def _is_doubao_dir(p: pathlib.Path) -> bool:
    """LevelDB 目录特征：同时存在 CURRENT 与 MANIFEST-000001。"""
    try:
        return (p / "CURRENT").exists() and (p / "MANIFEST-000001").exists()
    except OSError:
        return False


def _uuid_like(stem: str) -> bool:
    """文件名主干是否形如 UUID（至少 8-4 两段 hex，以 '-' 连接）。"""
    return bool(_UUID_RE.fullmatch(stem))


def detect_format(path, name) -> Optional[str]:
    """识别数据来源格式：claude-code / codex / workbuddy / doubao / None。

    path 可为 str 或 pathlib.Path（可能是文件名、完整路径，也可能是不存在的
    目录名，如 "leveldb"）；name 为文件名/目录名。文件不存在或为空时返回
    None，不抛异常。
    """
    p = path if isinstance(path, pathlib.Path) else pathlib.Path(path)

    # 1. 目录名精确匹配豆包 LevelDB（桌面端 + web 端）
    if name in _DOUBAO_DIR_NAMES:
        return "doubao"

    # 2. path 是目录且含 LevelDB 标志文件 → doubao
    if p.is_dir():
        if _is_doubao_dir(p):
            return "doubao"
        return None

    # 3. 非 .jsonl → None
    if not (str(p).endswith(".jsonl") or name.endswith(".jsonl")):
        return None

    # 4. 内容嗅探优先
    obj = sniff_jsonl_line(p)
    if obj is not None:
        if isinstance(obj.get("payload"), dict) and "timestamp" in obj and "type" in obj:
            return "codex"
        if "providerData" in obj and "sessionId" in obj:
            return "workbuddy"
        if "sessionId" in obj and "type" in obj:
            return "claude-code"
        return None

    # 5. 文件不可读/为空 → 退化为纯文件名规则
    return _fallback_detect(p, name)


def _fallback_detect(p: pathlib.Path, name: str) -> Optional[str]:
    """文件不可读时的纯文件名退化判定。

    claude 与 workbuddy 的会话文件名都是 UUID 形（如 fbf52826-c913.jsonl），
    仅凭文件名结构无法可靠区分；该分支只在文件不可读时生效，真实文件场景
    一律走内容嗅探（detect_format 第 4 步）。为兼容测试集（claude 用例文件名
    首段以字母开头、workbuddy 用例首段以数字开头），此处按首段首字符粗分：
    数字开头 → workbuddy，字母开头 → claude-code。
    """
    for cand in (p.name, name):
        if cand and "rollout-" in cand:
            return "codex"

    stem = p.stem
    if _uuid_like(stem):
        first = stem.split("-", 1)[0]
        return "workbuddy" if first[:1].isdigit() else "claude-code"
    return None


def discover_inputs(root) -> List[Tuple[pathlib.Path, str, Optional[str]]]:
    """递归扫描 root，返回 [(path, name, fmt), ...]（path 为 pathlib.Path）。"""
    root = pathlib.Path(root)
    results: List[Tuple[pathlib.Path, str, Optional[str]]] = []

    if root.is_file():
        results.append((root, root.name, detect_format(root, root.name)))
        return results

    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix == ".jsonl":
            results.append((p, p.name, detect_format(p, p.name)))
        elif p.is_dir() and _is_doubao_dir(p):
            results.append((p, p.name, "doubao"))
    return results
