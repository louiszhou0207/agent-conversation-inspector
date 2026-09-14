# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou

# tests/test_workbuddy.py
from conftest import fixture

from src.parsers.workbuddy import parse_workbuddy


def test_workbuddy_session_metadata():
    session = parse_workbuddy(fixture("workbuddy/sample.jsonl"))
    assert session.session_id == "3c2b1a09-8765-4321-8fed-cba987654321"
    assert session.user  # 首个 cwd 非空


def test_workbuddy_messages_and_roles():
    session = parse_workbuddy(fixture("workbuddy/sample.jsonl"))
    assert session.message_count > 2
    roles = {m.role for m in session.messages}
    assert "user" in roles
    assert "assistant" in roles


def test_workbuddy_tool_calls():
    session = parse_workbuddy(fixture("workbuddy/sample.jsonl"))
    tool_msgs = [m for m in session.messages if m.tool_call is not None]
    assert tool_msgs
    assert all(m.tool_call.name and m.tool_call.args for m in tool_msgs)
