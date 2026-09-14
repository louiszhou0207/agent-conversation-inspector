# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou

"""Codex JSONL 会话解析器。

输入为 Codex Desktop 导出的 .jsonl 会话文件（行结构 {timestamp,type,payload}），
输出统一的 Session 模型。解析规则（容错：单行 JSON 损坏则跳过）：
- session_id = session_meta.payload.id；user = session_meta.payload.cwd
- response_item：
  - payload.type == message（role 为 assistant/user）→ 将 content 各 dict 的
    text 拼接为消息
  - payload.type == function_call → Message(role="tool",
    tool_call=ToolCall(name=payload.name, args=json.dumps(arguments)[:2000]))
  - payload.type == function_call_output → 回填 result 到对应 tool_call
    （优先按 call_id 精确配对，缺省回退到最近一个尚无 result 的 tool_call）
- 其余 payload 类型 / 行类型（event_msg、turn_context 等）一律跳过
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


def _message_content(payload: dict) -> str:
    """把 message 的 content 列表里各 dict 的 text 拼接起来。"""
    content = payload.get("content")
    if not isinstance(content, list):
        return ""
    parts = [
        b.get("text", "")
        for b in content
        if isinstance(b, dict) and b.get("text")
    ]
    return "\n".join(parts)


def _recent_unfilled_tool(session: Session) -> Optional[ToolCall]:
    """从消息尾部往前找第一个尚无 result 的 tool_call。"""
    for m in reversed(session.messages):
        if m.tool_call is not None and not m.tool_call.result:
            return m.tool_call
    return None


def parse_codex(path) -> Session:
    """解析 Codex 会话文件为 Session；文件不可读/损坏时返回空会话。"""
    p = Path(path)
    session = Session(
        tool="codex",
        source=p.name,
        session_id="",
        user="",
    )
    # call_id -> ToolCall，用于 function_call_output 精确回填
    pending: dict = {}
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

            ts = _ts_ms(obj.get("timestamp"))
            ptype = obj.get("type")
            payload = obj.get("payload")

            if ptype == "session_meta" and isinstance(payload, dict):
                if not session.session_id and payload.get("id"):
                    session.session_id = str(payload["id"])
                if not session.user and payload.get("cwd"):
                    session.user = str(payload["cwd"])
                continue

            if ptype != "response_item" or not isinstance(payload, dict):
                continue

            ptype = payload.get("type")
            if ptype == "message":
                role = payload.get("role")
                if role not in ("assistant", "user"):
                    continue
                content = _message_content(payload)
                if not content:
                    continue
                session.messages.append(
                    Message(role=role, time_ms=ts, content=content)
                )
            elif ptype == "function_call":
                name = payload.get("name", "")
                args = json.dumps(payload.get("arguments"), ensure_ascii=False)[:2000]
                tool_call = ToolCall(name=name, args=args)
                call_id = payload.get("call_id")
                if call_id:
                    pending[str(call_id)] = tool_call
                session.messages.append(
                    Message(role="tool", time_ms=ts, content="", tool_call=tool_call)
                )
            elif ptype == "function_call_output":
                output = payload.get("output")
                if output is None:
                    continue
                result = str(output)[:2000]
                tool_call = None
                call_id = payload.get("call_id")
                if call_id:
                    tool_call = pending.get(str(call_id))
                if tool_call is None:
                    tool_call = _recent_unfilled_tool(session)
                if tool_call is not None:
                    tool_call.result = result
            # 其余 payload 类型（reasoning / token_count 等）跳过
    return session
