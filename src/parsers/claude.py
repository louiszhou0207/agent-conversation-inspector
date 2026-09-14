# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou

"""Claude Code JSONL 会话解析器。

输入为 Claude Code 导出的 .jsonl 会话文件，输出统一的 Session 模型。
解析规则（容错：单行 JSON 损坏则跳过，不中断整个文件）：
- session_id = 首个 sessionId；user = 首个 cwd
- user 事件：message.content 为字符串时直接使用；为块数组时取 type==text 块的
  text（多块用换行连接）
- assistant 事件：遍历 content 块，text → assistant 消息；thinking →
  "[思考] "+thinking 的 assistant 消息；tool_use → Message(role="tool",
  tool_call=ToolCall(name, args=json.dumps(input)[:2000]))；其余块类型跳过
- 其余事件类型（mode / attachment / file-history-snapshot 等）一律跳过
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from src.models import Message, Session, ToolCall


def _ts_ms(timestamp) -> int:
    """ISO8601 字符串 → epoch 毫秒；解析失败返回 0。"""
    if not isinstance(timestamp, str):
        return 0
    try:
        return int(
            datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp() * 1000
        )
    except (ValueError, TypeError):
        return 0


def _text_from_content(content) -> str:
    """从 message.content 提取文本：字符串直接返回，块数组取 type==text 的 text。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return "\n".join(parts)
    return ""


def _user_message(obj: dict, ts: int) -> Optional[Message]:
    msg = obj.get("message")
    if not isinstance(msg, dict):
        return None
    content = _text_from_content(msg.get("content"))
    if not content:
        return None
    return Message(role="user", time_ms=ts, content=content)


def _assistant_messages(obj: dict, ts: int) -> List[Message]:
    msg = obj.get("message")
    if not isinstance(msg, dict):
        return []
    content = msg.get("content")
    if not isinstance(content, list):
        return []
    messages: List[Message] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            text = block.get("text", "")
            if text:
                messages.append(Message(role="assistant", time_ms=ts, content=text))
        elif btype == "thinking":
            thinking = block.get("thinking", "")
            if thinking:
                messages.append(
                    Message(
                        role="assistant",
                        time_ms=ts,
                        content="[思考] " + thinking,
                    )
                )
        elif btype == "tool_use":
            name = block.get("name", "")
            tool_input = block.get("input")
            args = json.dumps(tool_input, ensure_ascii=False)[:2000]
            messages.append(
                Message(
                    role="tool",
                    time_ms=ts,
                    content="",
                    tool_call=ToolCall(name=name, args=args),
                )
            )
    return messages


def parse_claude(path) -> Session:
    """解析 Claude Code 会话文件为 Session；文件不可读/损坏时返回空会话。"""
    p = Path(path)
    session = Session(
        tool="claude-code",
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

            etype = obj.get("type")
            ts = _ts_ms(obj.get("timestamp"))
            if etype == "user":
                m = _user_message(obj, ts)
                if m is not None:
                    session.messages.append(m)
            elif etype == "assistant":
                session.messages.extend(_assistant_messages(obj, ts))
            # 其余事件类型（mode / attachment / ai-title 等）跳过
    return session
