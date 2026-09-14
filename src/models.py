# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou

"""统一会话模型：把四类工具的会话数据归一化为 Session/Message/ToolCall。"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class ToolCall:
    """一次工具调用记录。"""

    name: str
    args: str = ""
    result: str = ""
    is_error: bool = False


@dataclass
class Message:
    """会话中的一条消息。"""

    role: str
    time_ms: int
    content: str
    tool_call: Optional[ToolCall] = None


@dataclass
class Session:
    """一个会话：同一会话文件中的全部消息。"""

    tool: str
    source: str
    session_id: str
    user: str = ""
    messages: List[Message] = field(default_factory=list)

    @property
    def message_count(self) -> int:
        return len(self.messages)

    @property
    def tool_call_count(self) -> int:
        return sum(1 for m in self.messages if m.tool_call is not None)

    @property
    def time_range(self) -> Tuple[Optional[int], Optional[int]]:
        """会话首尾时间；无消息时返回 (None, None)。"""
        if not self.messages:
            return (None, None)
        times = [m.time_ms for m in self.messages if m.time_ms is not None]
        if not times:
            return (None, None)
        return (min(times), max(times))
