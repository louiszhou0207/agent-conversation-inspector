# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou

# tests/test_manifest.py
from src.manifest import load_manifest


def test_load_manifest(tmp_path):
    m = tmp_path / "manifest.json"
    m.write_text(
        '{"schema_version":1,"machine":"HOST","scanned_users":["user"],"items":[]}',
        encoding="utf-8",
    )
    meta = load_manifest(tmp_path)
    assert meta is not None and meta["machine"] == "HOST"


def test_missing_manifest(tmp_path):
    assert load_manifest(tmp_path) is None


def test_bad_manifest(tmp_path):
    (tmp_path / "manifest.json").write_text("{bad json", encoding="utf-8")
    assert load_manifest(tmp_path) is None
