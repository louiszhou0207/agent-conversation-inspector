# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou

# tests/test_codex.py
from conftest import fixture

from src.parsers.codex import parse_codex

CODEX_CWD = "C:\\Users\\user\\Projects\\demo"


def test_codex_session_metadata():
    session = parse_codex(fixture("codex/sample.jsonl"))
    assert session.session_id == "b7d94f2e-1a3c-4e5f-8b9a-0c1d2e3f4a5b"
    assert session.user == CODEX_CWD


def test_codex_has_messages():
    session = parse_codex(fixture("codex/sample.jsonl"))
    assert session.message_count > 0
    assert session.tool == "codex"


def test_codex_tool_calls_with_result():
    session = parse_codex(fixture("codex/sample.jsonl"))
    tool_msgs = [m for m in session.messages if m.tool_call is not None]
    assert tool_msgs
    # function_call_output 应回填到对应 tool_call.result
    assert any(m.tool_call.result for m in tool_msgs)
