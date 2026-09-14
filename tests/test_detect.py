# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou

from src.detect import detect_format, discover_inputs


def test_detect_claude():
    assert detect_format("fbf52826-c913.jsonl", "a.jsonl") == "claude-code"


def test_detect_codex():
    assert detect_format("rollout-2026-04-23T09-14-12-xxx.jsonl", "r.jsonl") == "codex"


def test_detect_workbuddy():
    assert detect_format("4585c6a4-36e0.jsonl", "w.jsonl") == "workbuddy"


def test_detect_doubao_dir():
    assert detect_format("leveldb", "chrome_doubao-chat_0.indexeddb.leveldb") == "doubao"


def test_detect_doubao_web_dir():
    """web 版豆包 LevelDB（普通对话主要存储）也必须识别为 doubao。"""
    assert detect_format("leveldb", "https_www.doubao.com_0.indexeddb.leveldb") == "doubao"


def test_discover_inputs_recursive(tmp_path):
    (tmp_path / "a.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.jsonl").write_text("", encoding="utf-8")
    assert len(discover_inputs(tmp_path)) == 2
