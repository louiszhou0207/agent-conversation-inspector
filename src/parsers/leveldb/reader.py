# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou

"""最小 LevelDB 读取器：解析 WAL（.log）与 SSTable（.ldb）。

只实现读记录所需的最小集；任一文件解析失败时静默跳过，不抛异常。

WAL（.log）：
- 文件按 32KB 分块，每块内是 7 字节记录头：
    checksum(4) + length(2) + type(1)
  type：1=FULL 2=FIRST 3=MIDDLE 4=LAST；FULL/FIRST 开始新记录，LAST 结束，
  MIDDLE 续接，需要跨块拼接。
- 拼接后的完整记录是 LevelDB WriteBatch 序列化：
    seq(8 字节小端) + count(4 字节小端)
    然后 count 条：type(1 字节，1=Put 0=Delete) + key_len(varint) + key
                  [+ value_len(varint) + value（Put 时）]
  WriteBatch 里的 key 是 user_key（不带 8 字节 internal trailer）。

SSTable（.ldb）：
- 文件尾 magic = 0x57fb808b247547db。footer 里依次是 metaindex handle 与
  index block handle（每个 handle 是 offset/size 两个 varint）。
- index block 每条记录的 value 是 data block 的 handle（offset/size 两个 varint）。
- data block 内记录：shared_len(varint) + non_shared_len(varint) +
  value_len(varint) + key_delta + value；块尾 type(1) + crc(4) 忽略。
- SSTable 里的 key 带 8 字节 internal trailer（seq 7 + type 1），读取时去掉，
  以便与 WAL 的 user_key 对齐做去重。
"""

import struct
from pathlib import Path
from typing import Iterator, Tuple

from src.parsers.leveldb import snappy

#: 块大小：WAL 按 32KB 切块
BLOCK_SIZE = 32 * 1024
#: SSTable footer magic
_TABLE_MAGIC = bytes.fromhex("57fb808b247547db")
#: internal key trailer 长度（seq 7 字节 + type 1 字节）
_TRAILER_LEN = 8
#: 块尾 trailer 长度（1 字节压缩类型 + 4 字节 crc）
_BLOCK_TRAILER = 5
#: 压缩类型
_COMPRESSION_NONE = 0
_COMPRESSION_SNAPPY = 1

# WAL 记录类型
_FULL = 1
_FIRST = 2
_MIDDLE = 3
_LAST = 4


def _varint(buf: bytes, pos: int) -> Tuple[int, int]:
    """读 varint（LEB128），返回 (值, 新pos)。越界抛 ValueError。"""
    shift = 0
    result = 0
    while True:
        if pos >= len(buf):
            raise ValueError("varint 越界")
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7
        if shift > 63:
            raise ValueError("varint 过长")


def _iter_log(path) -> Iterator[Tuple[bytes, bytes]]:
    """解析 WAL 文件，yield (user_key, value)。"""
    with open(path, "rb") as f:
        data = f.read()

    # 1. 按 32KB 块切分，收集 (type, payload)
    pieces = []  # list[(type, bytes)]
    pos = 0
    while pos + 12 <= len(data):
        block = data[pos:pos + BLOCK_SIZE]
        bp = 0
        while bp + 7 <= len(block):
            _checksum, length, rtype = struct.unpack_from("<IHB", block, bp)
            if length == 0 and rtype == 0:
                break  # 块尾 padding
            bp += 7
            if bp + length > len(block):
                break  # 记录被截断，忽略
            pieces.append((rtype, block[bp:bp + length]))
            bp += length
        pos += BLOCK_SIZE

    # 2. 拼接出完整记录
    records = []  # list[bytes]
    cur = b""
    for rtype, payload in pieces:
        if rtype == _FULL:
            records.append(payload)
            cur = b""
        elif rtype == _FIRST:
            cur = payload
        elif rtype == _MIDDLE:
            cur += payload
        elif rtype == _LAST:
            cur += payload
            records.append(cur)
            cur = b""

    # 3. 解析 WriteBatch
    for rec in records:
        if len(rec) < 12:
            continue
        count = struct.unpack_from("<I", rec, 8)[0]
        if count > 1_000_000:
            continue
        p = 12
        try:
            for _ in range(count):
                etype = rec[p]
                p += 1
                klen, p = _varint(rec, p)
                key = rec[p:p + klen]
                p += klen
                if etype == 1:  # Put
                    vlen, p = _varint(rec, p)
                    value = rec[p:p + vlen]
                    p += vlen
                    yield key, value
                # Delete（etype==0）无 value，跳过
        except (ValueError, IndexError):
            continue


def _parse_handles(data: bytes, footer_start: int):
    """从 footer 解析 (metaindex_handle, index_handle)；
    失败返回 (None, None)。"""
    p = footer_start
    try:
        mi_off, p = _varint(data, p)
        mi_size, p = _varint(data, p)
        ix_off, p = _varint(data, p)
        ix_size, p = _varint(data, p)
    except (ValueError, IndexError):
        return None, None
    return (mi_off, mi_size), (ix_off, ix_size)


def _find_footer(data: bytes):
    """尝试多种 footer 起始位置，返回首个解析合理的 index handle；
    找不到返回 None。"""
    if len(data) < 64 or data[-8:] != _TABLE_MAGIC:
        return None
    # 尝试 48 字节（标准）与 40/56 字节变体
    for footer_start in (len(data) - 56, len(data) - 48, len(data) - 40):
        if footer_start < 0:
            continue
        mi, ix = _parse_handles(data, footer_start)
        if ix is None:
            continue
        ix_off, ix_size = ix
        # 合理性校验：index 必须在文件内，且不为 0
        if (
            ix_off > 0
            and 0 < ix_size <= len(data)
            and ix_off + ix_size <= footer_start
            and ix_off + ix_size <= len(data)
        ):
            return footer_start, ix
    return None


def _read_block(data: bytes, offset: int, size: int) -> bytes:
    """读取一个 SSTable 块并解压，返回块正文（记录字节流）。

    本存储的块是"整块 snappy 流"（无标准 5 字节 trailer）：优先尝试
    snappy 解压，失败则视为未压缩原文。
    """
    if offset < 0 or offset + size > len(data) or size < 4:
        return b""
    block = data[offset:offset + size]
    try:
        return snappy.decompress(block)
    except Exception:
        return block


def _parse_block_records(content: bytes):
    """解析块记录字节流（不含 restart 区），yield (key, value)。

    记录格式：shared_len(varint) + non_shared_len(varint) + value_len(varint)
              + key_delta + value；前缀压缩需维护 prev_key。
    块尾部是 restart 偏移数组 + restart 计数（末 4 字节），解析到其起始处停止。
    """
    if len(content) < 4:
        return
    restart_count = int.from_bytes(content[-4:], "little")
    if restart_count > 100000 or len(content) < 4 + 4 * restart_count:
        restart_count = 0
    end = len(content) - 4 - 4 * restart_count
    if end < 5:
        return
    pos = 0
    prev_key = b""
    while pos + 5 <= end:
        try:
            shared, pos = _varint(content, pos)
            non_shared, pos = _varint(content, pos)
            vlen, pos = _varint(content, pos)
        except (ValueError, IndexError):
            break
        if pos + non_shared + vlen > end:
            break
        key = prev_key[:shared] + content[pos:pos + non_shared]
        pos += non_shared
        value = content[pos:pos + vlen]
        pos += vlen
        yield key, value
        prev_key = key


def _parse_block(data: bytes, offset: int, size: int) -> Iterator[Tuple[bytes, bytes]]:
    """解析一个 leveldb 块（自动解压），yield (key, value)。"""
    content = _read_block(data, offset, size)
    if not content:
        return
    yield from _parse_block_records(content)


def _iter_sst(path) -> Iterator[Tuple[bytes, bytes]]:
    """解析 SSTable 文件，yield (user_key, value)。"""
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 64 or data[-8:] != _TABLE_MAGIC:
        return

    found = _find_footer(data)
    if found is None:
        return
    footer_start, (ix_off, ix_size) = found

    # 读 index block，每条 value 是 data block handle
    data_handles = []
    for key, value in _parse_block(data, ix_off, ix_size):
        try:
            hoff, p = _varint(value, 0)
            hsize, p = _varint(value, p)
        except (ValueError, IndexError):
            continue
        # 第一个数据块可能位于 offset 0，故只校验 size>0 与边界
        if hsize > 0 and hoff + hsize <= footer_start:
            data_handles.append((hoff, hsize))

    # 逐个 data block 解析
    for hoff, hsize in data_handles:
        for key, value in _parse_block(data, hoff, hsize):
            # 去掉 8 字节 internal trailer
            if len(key) >= _TRAILER_LEN:
                yield key[:-_TRAILER_LEN], value


def iter_leveldb_records(db_dir) -> Iterator[Tuple[bytes, bytes]]:
    """合并目录内 .log 与 .ldb 的全部记录，按 user_key 去重（后写覆盖先写）。

    yield (user_key, value_bytes)。任一文件解析失败静默跳过。
    """
    db = Path(db_dir)
    latest: dict = {}
    order: list = []

    # 先 .log（新写入），后 .ldb（已落盘）；重复 key 以最后一次为准
    for pattern in ("*.log", "*.ldb"):
        for p in sorted(db.glob(pattern)):
            if not p.is_file():
                continue
            try:
                if pattern == "*.log":
                    records = _iter_log(p)
                else:
                    records = _iter_sst(p)
                for key, value in records:
                    if not key:
                        continue
                    if key not in latest:
                        order.append(key)
                    latest[key] = value
            except Exception:
                # 单个文件解析失败：静默跳过，不中断整个目录
                continue

    for key in order:
        yield key, latest[key]
