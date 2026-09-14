# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou

"""最小 V8 structured-clone 解码器（兼容豆包 IndexedDB 存储）。

豆包桌面端（Chromium）把会话对象以 V8 structured-clone 序列化存进
LevelDB 的 value。本模块实现 Chromium 实际使用的 v15 格式（版本标记
0xFF 0x0F）与旧 v2 格式（0x80 0x02）的常用子集，并对未知/歧义 tag
做"部分解码"容错：对象/数组解码中途失败时，保留已解析部分。

v15 关键格式（与旧版不同，务必注意）：
- kBeginJSObject(0x6F) 之后**没有属性计数**，直接是交替的 key/value，
  以 kEndJSObject(0x7B) 结束
- kBeginDenseJSArray(0x41) 之后是 varint 长度，再是元素
- 字符串（0x22 一字节 / 0x23 双字节）会写入引用表，后续可用
  kReference(0x5E) 复用
"""

import struct
from typing import Any, List, Optional, Tuple


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


def decode_v8_string(value_bytes: bytes, enc: int = 0) -> str:
    """按编码前缀解码字符串正文：enc=0 → UTF-8；enc=1 → UTF-16LE。"""
    try:
        if enc == 1:
            return value_bytes.decode("utf-16le", errors="replace")
        return value_bytes.decode("utf-8", errors="replace")
    except Exception:
        return ""


class V8Decoder:
    """迭代式 V8 解码器。部分解码：对象/数组解析中途失败时返回已解析部分。"""

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.refs: List[Any] = []

    # ---- 基础读取 ----

    def _varint(self) -> int:
        v, self.pos = _varint(self.data, self.pos)
        return v

    def _raw(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise ValueError("读取 %d 字节越界" % n)
        b = self.data[self.pos:self.pos + n]
        self.pos += n
        return b

    def _one_byte_str(self) -> str:
        n = self._varint()
        return self._raw(n).decode("utf-8", "replace")

    def _two_byte_str(self) -> str:
        n = self._varint()
        return self._raw(n * 2).decode("utf-16le", "replace")

    def find_version(self) -> Optional[bytes]:
        """在前 256 字节内找版本标记（0xFF 0x0F 或 0x80 0x02），
        定位后返回标记；找不到返回 None（不移动 pos 之外的状态）。"""
        head = self.data[:256]
        for marker in (b"\xff\x0f", b"\x80\x02"):
            i = head.find(marker)
            if i >= 0:
                self.pos = i + 2
                return marker
        return None

    # ---- 解码 ----

    def decode(self, depth: int = 0) -> Any:
        """解码一个值；遇到未知 tag 抛 ValueError（由上层决定保留部分）。"""
        if depth > 50 or self.pos >= len(self.data):
            raise ValueError("depth/end")

        tag = self.data[self.pos]
        self.pos += 1

        # 简单值
        if tag == 0x30 or tag == 0x5F:  # null / undefined
            return None
        if tag == 0x54:
            return True
        if tag == 0x46:
            return False
        if tag == 0x02:
            return True
        if tag == 0x03:
            return False
        if tag == 0x4E:  # double
            return struct.unpack("<d", self._raw(8))[0]
        if tag == 0x49:  # int32
            return struct.unpack("<i", self._raw(4))[0]
        if tag == 0x55:  # uint32
            return struct.unpack("<I", self._raw(4))[0]

        # 字符串（写入引用表）
        if tag == 0x22:
            s = self._one_byte_str()
            self.refs.append(s)
            return s
        if tag == 0x23:
            s = self._two_byte_str()
            self.refs.append(s)
            return s

        # 引用
        if tag == 0x5E:
            idx = self._varint()
            return self.refs[idx] if idx < len(self.refs) else None

        # JSObject（v15：无属性计数，key/value 直到 0x7B）
        if tag == 0x6F:
            obj: dict = {}
            try:
                while True:
                    if self.pos >= len(self.data):
                        break
                    t = self.data[self.pos]
                    if t == 0x7B:
                        self.pos += 1
                        break
                    k = self.decode(depth + 1)
                    if not isinstance(k, str):
                        break  # key 不是字符串 = 解析错位，保留部分
                    v = self.decode(depth + 1)
                    obj[k] = v
            except Exception:
                pass  # 保留已解析部分
            self.refs.append(obj)
            return obj

        # 稠密数组（0x41：varint 长度 + 元素；结束 tag 0x24 可选）
        if tag == 0x41:
            arr: list = []
            try:
                n = self._varint()
                if n > 200000:
                    n = 0
                for _ in range(n):
                    if self.pos >= len(self.data):
                        break
                    t = self.data[self.pos]
                    if t == 0x24:
                        self.pos += 1
                        break
                    arr.append(self.decode(depth + 1))
            except Exception:
                pass  # 保留已解析部分
            self.refs.append(arr)
            return arr

        # 对象/数组结束 tag 单独出现时视为 None
        if tag in (0x7B, 0x24, 0xE1):
            return None

        raise ValueError("未知 tag 0x%02x @%d" % (tag, self.pos - 1))


def decode_v8(data: bytes, start: int = 0) -> Any:
    """从 data 解码一个 V8 值（自动定位版本标记）；失败返回 None。

    start 用于跳过外层包装头（如豆包 value 前有一段前缀字节）。
    部分解码：返回尽可能多的顶层对象。
    """
    d = V8Decoder(data)
    d.pos = start
    if not d.find_version():
        return None
    try:
        return d.decode()
    except Exception:
        # 顶层对象若已部分解析出键，返回部分结果
        if d.refs:
            last = d.refs[-1]
            if isinstance(last, dict) and last:
                return last
        return None
