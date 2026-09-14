# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou

# tests/test_snappy.py
import pytest

from src.parsers.leveldb import snappy


def test_decompress_simple_literal():
    # 构造一个仅含 literal 的 snappy 流：uncompressed len=5, literal len=5 "hello"
    # literal tag = (len-1)<<2 = 16 = 0x10
    data = bytes([5, 0x10]) + b"hello"
    assert snappy.decompress(data) == b"hello"


def test_decompress_copy():
    # "abcabcabc": literal "abc" (tag 0x08 len 3) + copy offset 3 len 6
    # copy tag type 01 (1-byte offset): tag = (0<<2) | (3<<5) | 1?  —— 构造：len=4+((tag>>2)&7)
    # 用 4 字节 offset 的 copy 更简单：tag = ((len-1)<<2) | 3 = (5<<2)|3 = 0x17, offset 3 LE
    data = bytes([9, 0x08]) + b"abc" + bytes([0x17, 3, 0, 0, 0])
    assert snappy.decompress(data) == b"abcabcabc"


def test_decompress_empty():
    assert snappy.decompress(b"\x00") == b""


def test_decompress_invalid():
    with pytest.raises(snappy.SnappyError):
        snappy.decompress(b"\xff\xff\xff\xff")
