# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou

# tests/test_claude.py
from conftest import fixture

from src.parsers.claude import parse_claude


def test_claude_session_metadata():
    session = parse_claude(fixture("claude/sample.jsonl"))
    assert session.tool == "claude-code"
    assert session.session_id == "9f2e1a3b-4c5d-4e6f-8a7b-6c5d4e3f2a1b"
    assert session.user  # 首个 cwd 非空


def test_claude_messages_and_roles():
    session = parse_claude(fixture("claude/sample.jsonl"))
    assert session.message_count > 2
    roles = {m.role for m in session.messages}
    assert "user" in roles
    assert "assistant" in roles


def test_claude_tool_calls():
    session = parse_claude(fixture("claude/sample.jsonl"))
    names = {
        m.tool_call.name
        for m in session.messages
        if m.tool_call is not None
    }
    assert names & {"Bash", "Read", "WebSearch", "Write", "Edit", "Grep", "Glob"}
    # tool_call 必须有 name 与 args
    tool_msgs = [m for m in session.messages if m.tool_call is not None]
    assert tool_msgs
    assert all(t.name and t.args for t in (m.tool_call for m in tool_msgs))
