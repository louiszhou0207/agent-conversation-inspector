# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou

# tests/test_fixtures.py
from conftest import fixture


def test_fixtures_exist():
    assert fixture("claude/sample.jsonl").exists()
    assert fixture("codex/sample.jsonl").exists()
    assert fixture("workbuddy/sample.jsonl").exists()
    assert fixture("doubao/leveldb/CURRENT").exists()
    assert fixture("doubao/leveldb/MANIFEST-000001").exists()
