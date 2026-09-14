# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou

# tests/test_e2e.py
"""端到端验收：用真实夹具组装输入目录，跑 CLI 生成报告并断言四类工具齐全。"""

import shutil
import subprocess
import sys
from pathlib import Path

from conftest import fixture

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOUBAO_DIR = "chrome_doubao-chat_0.indexeddb.leveldb"
DOUBAO_WEB_DIR = "https_www.doubao.com_0.indexeddb.leveldb"


def _assemble_inputs(tmp_path: Path) -> Path:
    """把四类夹具组装成 CLI 的输入目录（豆包含桌面端 + web 端两个库）。"""
    inputs = tmp_path / "inputs"
    inputs.mkdir()

    for name in ("claude", "codex", "workbuddy"):
        d = inputs / name
        d.mkdir()
        shutil.copy(fixture(f"{name}/sample.jsonl"), d / "sample.jsonl")

    doubao_root = inputs / "doubao"
    shutil.copytree(fixture("doubao/leveldb"), doubao_root / DOUBAO_DIR)
    shutil.copytree(fixture("doubao/web"), doubao_root / DOUBAO_WEB_DIR)
    return inputs


def _run_cli(inputs: Path, out: Path):
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "audit_report.py"), str(inputs), "-o", str(out)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_e2e_report_contains_all_tools(tmp_path):
    inputs = _assemble_inputs(tmp_path)
    out = tmp_path / "report.html"
    proc = _run_cli(inputs, out)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert out.exists()

    html = out.read_text(encoding="utf-8")
    for kw in ("claude-code", "codex", "workbuddy", "doubao"):
        assert kw in html, f"报告缺少工具标记: {kw}"
