# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou

"""纯 Python 的 Snappy 解压器（LevelDB 默认块压缩）。

实现 google/snappy 原始（raw）格式的一个子集，足以解压 LevelDB/Chromium
写入的块：
- varint 无符号原始长度
- 元素类型 00=literal、01/10/11=copy（1/2/4 字节 offset）

仅实现解压（工具只读不写）。畸形输入抛 SnappyError。
"""


class SnappyError(Exception):
    pass


def _varint(buf: bytes, pos: int):
    v = 0
    shift = 0
    while True:
        if pos >= len(buf):
            raise SnappyError("varint 越界")
        b = buf[pos]
        pos += 1
        v |= (b & 0x7F) << shift
        if not (b & 0x80):
            return v, pos
        shift += 7
        if shift > 63:
            raise SnappyError("varint 过长")


def decompress(data: bytes) -> bytes:
    """解压 snappy raw 流，返回解压后字节。"""
    if not data:
        return b""
    ulen, pos = _varint(data, 0)
    out = bytearray()
    while len(out) < ulen:
        if pos >= len(data):
            raise SnappyError("数据截断")
        tag = data[pos]
        pos += 1
        etype = tag & 3
        if etype == 0:
            # literal
            n = (tag >> 2) + 1
            if n > 60:
                nbytes = n - 60
                if pos + nbytes > len(data):
                    raise SnappyError("literal 长度越界")
                n = int.from_bytes(data[pos:pos + nbytes], "little") + 1
                pos += nbytes
            if pos + n > len(data):
                raise SnappyError("literal 越界")
            out += data[pos:pos + n]
            pos += n
        else:
            # copy
            if etype == 1:
                n = 4 + ((tag >> 2) & 0x7)
                if pos + 1 > len(data):
                    raise SnappyError("copy offset 越界")
                off = ((tag >> 5) & 0x7) << 8 | data[pos]
                pos += 1
            elif etype == 2:
                n = 1 + (tag >> 2)
                if pos + 2 > len(data):
                    raise SnappyError("copy offset 越界")
                off = data[pos] | (data[pos + 1] << 8)
                pos += 2
            else:
                n = 1 + (tag >> 2)
                if pos + 4 > len(data):
                    raise SnappyError("copy offset 越界")
                off = int.from_bytes(data[pos:pos + 4], "little")
                pos += 4
            if off <= 0 or off > len(out):
                raise SnappyError("copy offset 非法")
            for _ in range(n):
                out.append(out[-off])
    return bytes(out[:ulen])
