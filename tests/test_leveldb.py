# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou

# tests/test_leveldb.py
from conftest import fixture

from src.parsers.leveldb.reader import iter_leveldb_records
from src.parsers.leveldb.v8 import decode_v8_string
from src.parsers.doubao import parse_doubao_dir


def test_leveldb_records():
    records = list(iter_leveldb_records(fixture("doubao/leveldb")))
    assert len(records) > 0
    # 记录形如 (user_key, value_bytes)
    for key, value in records:
        assert isinstance(key, bytes)
        assert isinstance(value, bytes)


def test_sst_records_readable():
    """回归：.ldb（snappy 整块压缩）必须能读出记录，否则豆包只剩 WAL 切片。"""
    import pathlib
    from src.parsers.leveldb.reader import _iter_sst
    db = pathlib.Path(fixture("doubao/leveldb"))
    sst_total = sum(len(list(_iter_sst(p))) for p in db.glob("*.ldb"))
    assert sst_total >= 100, f".ldb 记录过少（{sst_total}），snappy 解压可能失效"
    # 至少存在有值的记录
    assert any(
        v for p in db.glob("*.ldb") for _k, v in _iter_sst(p) if v
    )


def test_v8_chinese():
    assert decode_v8_string("音乐生成".encode("utf-16le"), enc=1) == "音乐生成"


def test_doubao_sessions():
    sessions = parse_doubao_dir(fixture("doubao/leveldb"))
    assert len(sessions) >= 1
    assert any(s.session_id for s in sessions)
    # 若存在消息，则至少一条消息的 content 非空
    for s in sessions:
        if s.messages:
            assert any(m.content for m in s.messages)


def test_doubao_no_empty_sessions():
    """空会话是幽灵 UUID（消息 ID 被误当会话 ID）导致，必须剔除。"""
    sessions = parse_doubao_dir(fixture("doubao/leveldb"))
    assert all(s.messages for s in sessions), "存在没有消息的会话"


def test_doubao_message_quality():
    """降级消息（time_ms==0 的字符串扫描来源）不得是 UTF-16 错位噪声。

    合成夹具为标准 V8 编码、可完整结构化解码，不触发降级扫描路径；
    若未来夹具引入无法解码的记录（如豆包自研 tag 0x05），此处仍会校验。
    """
    from src.parsers.doubao import _acceptable_text
    sessions = parse_doubao_dir(fixture("doubao/leveldb"))
    assert sessions, "应至少解析出 1 个会话"
    degraded_seen = False
    for s in sessions:
        for m in s.messages:
            if m.time_ms == 0:  # 降级路径消息
                degraded_seen = True
                assert _acceptable_text(m.content), f"降级消息疑似乱码: {m.content!r}"
            else:
                assert m.time_ms > 0, f"结构化消息缺时间戳: {m.content[:30]!r}"


def test_doubao_web_has_readable_chat():
    """web 版豆包库（普通对话）应结构化解析出用户与助手双向消息。"""
    sessions = parse_doubao_dir(fixture("doubao/web"))
    roles = {m.role for s in sessions for m in s.messages}
    msgs = [m.content for s in sessions for m in s.messages if m.content]
    assert len(msgs) >= 2, f"web 库消息过少: {len(msgs)}"
    assert "user" in roles and "assistant" in roles, f"应包含双向消息: {roles}"
    assert any(len(m) >= 10 for m in msgs), "web 库没有可读对话"
