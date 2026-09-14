# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou

from src.render.render import render_html


def test_render_creates_html(tmp_path):
    sessions = []
    out = tmp_path / "report.html"
    render_html(sessions, meta={"machine": "HOST", "generated_at": "2026-09-10", "failed": [], "session_count": 0}, out=out)
    html = out.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html
    assert "HOST" in html


def test_render_with_session(tmp_path):
    from src.models import Session, Message, ToolCall
    s = Session(tool="claude-code", source="a.jsonl", session_id="sid-1", user="F:\\work")
    s._title = "测试会话"
    s.messages.append(Message(role="user", time_ms=1783910466091, content="你好"))
    s.messages.append(Message(role="assistant", time_ms=1783910467000, content="你好！"))
    s.messages.append(Message(role="tool", time_ms=1783910468000, content="", tool_call=ToolCall(name="Bash", args="ls -la", result="file1", is_error=False)))
    out = tmp_path / "report.html"
    render_html([s], meta={"machine": "HOST", "generated_at": "", "failed": [], "session_count": 1}, out=out)
    html = out.read_text(encoding="utf-8")
    assert "测试会话" in html and "claude-code" in html and "你好" in html and "ls -la" in html
