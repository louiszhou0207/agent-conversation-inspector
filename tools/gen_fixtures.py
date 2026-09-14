# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou

"""合成夹具生成器：为公开发布生成无个人信息的测试 / 演示数据。

背景：仓库早期开发时把本地真实会话（Claude/Codex/WorkBuddy JSONL 与豆包
LevelDB）作为测试夹具和 demo 输入入库。发布到 GitHub 前必须整体替换为
**合成数据**——结构真实（各解析器依赖的字段完整），内容完全虚构。

用法：
    python tools/gen_fixtures.py

产出（两份一致）：
    tests/fixtures/claude|codex|workbuddy/sample.jsonl
    tests/fixtures/doubao/leveldb|web/          （合成 LevelDB 目录）
    demo/in/claude|codex|workbuddy/sample.jsonl
    demo/in/doubao/{chrome_doubao-chat_0.indexeddb.leveldb,
                    https_www.doubao.com_0.indexeddb.leveldb}

依赖：v8serialize（合成豆包记录需反向 V8 序列化）。

实现要点：
- 豆包 LevelDB 用最小 SSTable writer 生成单个 .ldb：data block（snappy
  literal-only 压缩，与 src/parsers/leveldb/snappy.py 解压端自洽）+ index
  block + metaindex（空）+ 48 字节 footer；另补 CURRENT / MANIFEST-000001。
- 记录值全部由 v8serialize.dumps() 生成，能被解析器结构化路径正确解码；
  因此合成数据不会触发降级扫描路径（该路径代码保留，仅测试不覆盖）。
- 所有路径 / 用户 / 机器名 / 会话内容均为虚构通用示例。
"""

import json
import shutil
import sys
from pathlib import Path

import v8serialize

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
DEMO_IN = ROOT / "demo" / "in"

# 通用虚构身份（全文统一，绝无真实信息）
USER_CWD = r"C:\Users\user\Projects\demo"
MACHINE = "HOST"
DOUBAO_DESKTOP_DIR = "chrome_doubao-chat_0.indexeddb.leveldb"
DOUBAO_WEB_DIR = "https_www.doubao.com_0.indexeddb.leveldb"

# ---------------------------------------------------------------------------
# Snappy literal-only 压缩（与 src/parsers/leveldb/snappy.py 解压端自洽）
# ---------------------------------------------------------------------------


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _snappy_compress(data: bytes) -> bytes:
    """raw snappy：uncompressed 长度 varint + 60 字节/块的 literal 标签。"""
    out = bytearray(_varint(len(data)))
    pos = 0
    while pos < len(data):
        chunk = data[pos:pos + 60]
        out.append((len(chunk) - 1) << 2)  # 1 字节 literal tag，len<=60
        out += chunk
        pos += len(chunk)
    return bytes(out)


# ---------------------------------------------------------------------------
# 最小 SSTable writer（单 data block）
# ---------------------------------------------------------------------------

_MAGIC = bytes.fromhex("57fb808b247547db")  # leveldb table magic


def _block(records: list) -> bytes:
    """构建一个 leveldb block（snappy 压缩）并返回压缩字节流。

    records: [(key: bytes, value: bytes), ...]（已排序）
    block = 记录区 + restart 偏移数组 + restart 计数；本实现每条记录
    shared=0（无前缀压缩），restart 点取每条记录起点。
    """
    body = bytearray()
    restarts = []
    for key, value in records:
        restarts.append(len(body))
        body += b"\x00"  # shared_len = 0
        body += _varint(len(key))  # non_shared_len
        body += _varint(len(value))  # value_len
        body += key
        body += value
    content = bytes(body) + b"".join(
        r.to_bytes(4, "little") for r in restarts
    ) + len(restarts).to_bytes(4, "little")
    return _snappy_compress(content)


def build_sst(records: list, seq: int = 1000) -> bytes:
    """把 (user_key, value) 记录列表写成一个最小 SSTable 文件字节。

    布局：[data block][index block][metaindex block][footer]
    data block 记录 key 带 8 字节 internal trailer（seq 7B LE + type 1）。
    """
    internal = [
        (k + seq.to_bytes(7, "little") + b"\x01", v) for k, v in records
    ]
    internal.sort(key=lambda kv: kv[0])

    data_blob = _block(internal)
    data_off, data_size = 0, len(data_blob)

    last_key = internal[-1][0]
    index_body = last_key + _varint(data_off) + _varint(data_size)
    index_records = [(last_key, _varint(data_off) + _varint(data_size))]
    index_blob = _block(index_records)
    index_off, index_size = data_off + data_size, len(index_blob)

    meta_blob = _block([])  # 空 metaindex
    meta_off, meta_size = index_off + index_size, len(meta_blob)

    footer_start = meta_off + meta_size
    varints = (
        _varint(meta_off)
        + _varint(meta_size)
        + _varint(index_off)
        + _varint(index_size)
    )
    # footer 固定 56 字节：读取器 _find_footer 按 len-56/len-48/len-40 依次
    # 尝试，48 字节 footer 时 len-56 处可能恰好落在 index/meta 块尾部字节上
    # 被误判为合法 handle；56 字节 footer 保证 len-56 精确命中、其余位置（
    # padding 区）解析为 0 被校验拒绝，唯一命中。
    footer = varints + b"\x00" * (56 - len(varints) - 8) + _MAGIC
    return data_blob + index_blob + meta_blob + footer


def write_doubao_dir(target: Path, records: list, table_name: str) -> None:
    """生成一个可被解析器读取的合成 LevelDB 目录。"""
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    (target / (table_name + ".ldb")).write_bytes(build_sst(records))
    (target / "CURRENT").write_text("MANIFEST-000001\n", encoding="utf-8")
    (target / "MANIFEST-000001").write_bytes(b"\x00\x00\x00\x00")
    (target / "LOG").write_text("Synthetic fixtures. No real data.\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 合成 JSONL 数据
# ---------------------------------------------------------------------------

CLAUDE_SID = "9f2e1a3b-4c5d-4e6f-8a7b-6c5d4e3f2a1b"
CODEX_SID = "b7d94f2e-1a3c-4e5f-8b9a-0c1d2e3f4a5b"
WORKBUDDY_SID = "3c2b1a09-8765-4321-8fed-cba987654321"


def claude_lines() -> list:
    """合成 Claude Code 会话：user / assistant(thinking+text) / tool_use / tool_result 风格。"""
    return [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "你好，我是示例助手。"}]}, "timestamp": "2026-01-05T08:00:00Z", "sessionId": CLAUDE_SID, "cwd": USER_CWD},
        {"type": "user", "message": {"content": "帮我把项目里的 README 整理成中文版。"}, "timestamp": "2026-01-05T08:00:10Z", "sessionId": CLAUDE_SID, "cwd": USER_CWD},
        {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "用户需要 README 中文翻译，先读取现有文件。"}, {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "C:\\Users\\user\\Projects\\demo\\README.md"}}, {"type": "tool_use", "id": "t2", "name": "Grep", "input": {"pattern": "TODO|FIXME", "path": "C:\\Users\\user\\Projects\\demo"}}]}, "timestamp": "2026-01-05T08:00:15Z", "sessionId": CLAUDE_SID, "cwd": USER_CWD},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "# 示例项目\n\n一个示例项目说明。"}]}, "timestamp": "2026-01-05T08:00:20Z", "sessionId": CLAUDE_SID, "cwd": USER_CWD},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "好的，我已读完 README，开始翻译。"}, {"type": "tool_use", "id": "t3", "name": "Write", "input": {"file_path": "C:\\Users\\user\\Projects\\demo\\README.zh.md", "content": "# 示例项目（中文）"}}]}, "timestamp": "2026-01-05T08:00:25Z", "sessionId": CLAUDE_SID, "cwd": USER_CWD},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "翻译完成，文件已写入 README.zh.md。"}]}, "timestamp": "2026-01-05T08:00:30Z", "sessionId": CLAUDE_SID, "cwd": USER_CWD},
    ]


def codex_lines() -> list:
    """合成 Codex 会话：session_meta + response_item(message/function_call/function_call_output)。"""
    return [
        {"timestamp": "2026-01-05T09:00:00Z", "type": "session_meta", "payload": {"id": CODEX_SID, "cwd": USER_CWD}},
        {"timestamp": "2026-01-05T09:00:01Z", "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "写一个斐波那契数列函数。"}]}},
        {"timestamp": "2026-01-05T09:00:02Z", "type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "我来实现一个 Python 版本的斐波那契函数。"}]}},
        {"timestamp": "2026-01-05T09:00:03Z", "type": "response_item", "payload": {"type": "function_call", "call_id": "call_1", "name": "Bash", "arguments": {"command": "python -c 'print(1)'"}}},
        {"timestamp": "2026-01-05T09:00:04Z", "type": "response_item", "payload": {"type": "function_call_output", "call_id": "call_1", "output": "1"}},
        {"timestamp": "2026-01-05T09:00:05Z", "type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "已完成，运行结果正常。"}]}},
    ]


def workbuddy_lines() -> list:
    """合成 WorkBuddy 会话：ai-title + message(user/assistant) + reasoning + function_call。"""
    return [
        {"type": "ai-title", "aiTitle": "示例：翻译 README 文档", "sessionId": WORKBUDDY_SID, "cwd": USER_CWD, "timestamp": 1780000000000},
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "帮我写一份季度总结的提纲。"}], "sessionId": WORKBUDDY_SID, "cwd": USER_CWD, "timestamp": 1780000001000},
        {"type": "reasoning", "rawContent": [{"type": "reasoning_text", "text": "总结提纲应包含成果、问题与计划三部分。"}], "sessionId": WORKBUDDY_SID, "cwd": USER_CWD, "timestamp": 1780000002000},
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "好的，以下是提纲：一、本季度成果；二、遇到的问题；三、下季度计划。"}], "sessionId": WORKBUDDY_SID, "cwd": USER_CWD, "timestamp": 1780000003000},
        {"type": "function_call", "name": "Read", "arguments": {"file_path": "C:\\Users\\user\\Projects\\demo\\notes.md"}, "sessionId": WORKBUDDY_SID, "cwd": USER_CWD, "timestamp": 1780000004000},
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "已参考你的笔记，提纲可以在此基础上补充数据支撑。"}], "sessionId": WORKBUDDY_SID, "cwd": USER_CWD, "timestamp": 1780000005000},
    ]


# ---------------------------------------------------------------------------
# 合成豆包记录
# ---------------------------------------------------------------------------

DOUBAO_DESKTOP_SID = "d4c3b2a1-0000-4000-8000-000000000001"
DOUBAO_WEB_SIDS = [
    "d4c3b2a1-0000-4000-8000-000000000002",
    "d4c3b2a1-0000-4000-8000-000000000003",
]
CONV_1 = "1700000000001"
CONV_2 = "1700000000002"
CONV_3 = "1700000000003"


def _conv_msg(mid: str, conv: str, role: int, text: str, ts: int) -> dict:
    return {
        mid: {
            "conversationId": conv,
            "extra": {
                "content_blocks_v2": [{"content": {"text_block": {"text": text}}}],
                "user_type": role,
                "create_time": ts,
            },
        }
    }


def _doubao_record(state_key: str, task_map: dict, cells: dict = None) -> dict:
    obj = {"state": {state_key: task_map}}
    if cells is not None:
        obj["downlink_body"] = {
            "pull_recent_conv_chain_downlink_body": {"cells": cells}
        }
    return obj


def doubao_desktop_records() -> list:
    """桌面库：1 个会话（mainTaskDataMap）+ 会话列表 + 大量杂项记录。

    杂项记录是会话无关的存储条目（解析器会忽略），用于让 .ldb 记录数
    满足测试对真实库规模的回归要求（>= 100 条）。
    """
    records = []
    session = _doubao_record(
        "mainTaskDataMap",
        {
            DOUBAO_DESKTOP_SID: {
                "sentMessages": _conv_msg("m1", CONV_1, 1, "帮我写一个批量重命名文件的脚本。", 1780000000000),
                "receivedMessages": _conv_msg("m2", CONV_1, 2, "好的，这是脚本：使用 os.rename 遍历目录即可。", 1780000001000),
                "requestQuery": {"syncTask": {"messages": []}},
            }
        },
        cells={
            "c1": {"conversation": {"conversation_id": CONV_1, "name": "示例会话-文件重命名"}}
        },
    )
    records.append((b"rec-session-0001", v8serialize.dumps(session)))

    for i in range(2, 101):
        misc = {"idx": i, "kind": "synthetic", "ts": 1780000000000 + i}
        records.append((b"rec-misc-%05d" % i, v8serialize.dumps(misc)))
    return records


def doubao_web_records() -> list:
    """web 库：2 个普通对话会话（chatTaskDataMap）+ 会话列表。"""
    task_map = {
        DOUBAO_WEB_SIDS[0]: {
            "sentMessages": _conv_msg("w1", CONV_2, 1, "推荐几个适合新手的 Python 学习项目。", 1780001000000),
            "receivedMessages": _conv_msg("w2", CONV_2, 2, "推荐三个：命令行小工具、网页爬虫、数据可视化仪表盘。", 1780001001000),
        },
        DOUBAO_WEB_SIDS[1]: {
            "sentMessages": _conv_msg("w3", CONV_3, 1, "解释一下 git rebase 和 merge 的区别。", 1780002000000),
            "receivedMessages": _conv_msg("w4", CONV_3, 2, "rebase 会改写提交历史使分支线性，merge 保留分叉并产生合并提交。", 1780002001000),
        },
    }
    cells = {
        "c1": {"conversation": {"conversation_id": CONV_2, "name": "示例对话-Python 学习"}},
        "c2": {"conversation": {"conversation_id": CONV_3, "name": "示例对话-git 概念"}},
    }
    session = _doubao_record("chatTaskDataMap", task_map, cells)
    records = [(b"rec-web-session-0001", v8serialize.dumps(session))]
    for i in range(2, 31):
        misc = {"idx": i, "kind": "synthetic", "ts": 1780001000000 + i}
        records.append((b"rec-web-misc-%05d" % i, v8serialize.dumps(misc)))
    return records


# ---------------------------------------------------------------------------
# 落盘
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, lines: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")


def generate() -> None:
    # JSONL 三件套
    for area in (FIXTURES, DEMO_IN):
        _write_jsonl(area / "claude" / "sample.jsonl", claude_lines())
        _write_jsonl(area / "codex" / "sample.jsonl", codex_lines())
        _write_jsonl(area / "workbuddy" / "sample.jsonl", workbuddy_lines())

    # 豆包 LevelDB
    write_doubao_dir(FIXTURES / "doubao" / "leveldb", doubao_desktop_records(), "000100")
    write_doubao_dir(FIXTURES / "doubao" / "web", doubao_web_records(), "000200")
    write_doubao_dir(DEMO_IN / "doubao" / DOUBAO_DESKTOP_DIR, doubao_desktop_records(), "000100")
    write_doubao_dir(DEMO_IN / "doubao" / DOUBAO_WEB_DIR, doubao_web_records(), "000200")

    print("synthetic fixtures written to:")
    print("  ", FIXTURES)
    print("  ", DEMO_IN)


if __name__ == "__main__":
    generate()
