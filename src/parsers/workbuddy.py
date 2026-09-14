# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou

"""WorkBuddy JSONL 会话解析器。

输入为 WorkBuddy（飞书 CLI 等）导出的 .jsonl 会话文件，输出统一的 Session
模型。解析规则（容错：单行 JSON 损坏则跳过，不中断整个文件）：
- session_id = 首个 sessionId；user = 首个 cwd；时间戳为 epoch 毫秒整数直接使用
- type == ai-title → 记录 Session._title = aiTitle
- type == message → 按 role（user/assistant）生成消息，content 取 content 列表
  中文本块的 text 连接（块类型为 input_text/output_text，兼容 "text"）
- type == reasoning → assistant 消息，content 前缀 "[推理] " + rawContent 中
  文本块的 text（块类型 reasoning_text，兼容 "text"）
- type == function_call → Message(role="tool",
  tool_call=ToolCall(name=name, args=字符串截断2000 / json.dumps[:2000]))
- 其余类型（file-history-snapshot / function_call_result 等）一律跳过
"""

import json
from pathlib import Path
from typing import List

from src.models import Message, Session, ToolCall


def _is_text_block(block: dict) -> bool:
    """块是否为文本块：type == "text" 或以 "text" 结尾（input_text 等）。"""
    btype = block.get("type")
    return isinstance(btype, str) and (btype == "text" or btype.endswith("text"))


def _join_text(blocks) -> str:
    """从块列表中提取文本块的 text，用换行连接。"""
    if not isinstance(blocks, list):
        return ""
    parts = [
        b.get("text", "")
        for b in blocks
        if isinstance(b, dict) and _is_text_block(b) and b.get("text")
    ]
    return "\n".join(parts)


def parse_workbuddy(path) -> Session:
    """解析 WorkBuddy 会话文件为 Session；文件不可读/损坏时返回空会话。"""
    p = Path(path)
    session = Session(
        tool="workbuddy",
        source=p.name,
        session_id="",
        user="",
    )
    try:
        lines = p.open("r", encoding="utf-8")
    except OSError:
        return session
    with lines:
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(obj, dict):
                continue

            if not session.session_id and obj.get("sessionId"):
                session.session_id = str(obj["sessionId"])
            if not session.user and obj.get("cwd"):
                session.user = str(obj["cwd"])

            ts = obj.get("timestamp")
            if not isinstance(ts, int):
                ts = 0

            etype = obj.get("type")
            if etype == "ai-title":
                if obj.get("aiTitle"):
                    session._title = obj["aiTitle"]
            elif etype == "message":
                role = obj.get("role")
                if role not in ("user", "assistant"):
                    continue
                content = _join_text(obj.get("content"))
                if not content:
                    continue
                session.messages.append(
                    Message(role=role, time_ms=ts, content=content)
                )
            elif etype == "reasoning":
                text = _join_text(obj.get("rawContent"))
                if text:
                    session.messages.append(
                        Message(
                            role="assistant",
                            time_ms=ts,
                            content="[推理] " + text,
                        )
                    )
            elif etype == "function_call":
                name = obj.get("name", "")
                arguments = obj.get("arguments")
                if isinstance(arguments, str):
                    args = arguments[:2000]
                else:
                    args = json.dumps(arguments, ensure_ascii=False)[:2000]
                session.messages.append(
                    Message(
                        role="tool",
                        time_ms=ts,
                        content="",
                        tool_call=ToolCall(name=name, args=args),
                    )
                )
            # 其余类型（file-history-snapshot / function_call_result 等）跳过
    return session
