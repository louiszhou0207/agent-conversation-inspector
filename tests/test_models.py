# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou

from src.models import Session, Message


def test_message_roundtrip():
    m = Message(role="user", time_ms=1783910466091, content="你好")
    assert m.role == "user"


def test_session_has_stats():
    s = Session(tool="claude-code", user="user", source="x.jsonl", session_id="abc")
    s.messages.append(Message(role="user", time_ms=1, content="u"))
    s.messages.append(Message(role="assistant", time_ms=2, content="a"))
    assert s.message_count == 2
    assert s.tool_call_count == 0
    assert s.time_range == (1, 2)
