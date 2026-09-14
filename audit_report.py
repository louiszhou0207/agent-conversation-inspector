# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou

"""audit_report.py — AI 对话数据审计报告 CLI 主入口。

用法：
    python audit_report.py <input> [-o report.html] [--package]

流程：
    discover_inputs 扫描输入目录 → 按 fmt 路由到对应 parser 解析（doubao
    目录用 parse_doubao_dir 扩展出多个会话，其余用 parse_* 单文件函数）→
    load_manifest 用 manifest.json 增强 meta → render_html 输出自包含 HTML。

容错：任何单个文件/目录解析失败只记入 failed 列表，不中断整个流程。
"""

import argparse
import platform
import sys
from datetime import datetime
from pathlib import Path

from src.detect import discover_inputs
from src.manifest import load_manifest
from src.parsers.claude import parse_claude
from src.parsers.codex import parse_codex
from src.parsers.doubao import parse_doubao_dir
from src.parsers.workbuddy import parse_workbuddy
from src.render.render import render_html

#: 单文件解析器路由（doubao 是目录解析，单独处理）
_SINGLE_FILE_PARSERS = {
    "claude-code": parse_claude,
    "codex": parse_codex,
    "workbuddy": parse_workbuddy,
}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="audit_report",
        description="扫描 AI 对话数据目录并生成自包含 HTML 审计报告",
    )
    parser.add_argument(
        "input",
        help="输入目录：运营人员从目标机器拉回的会话数据（含 manifest.json 时为可选增强）",
    )
    parser.add_argument("-o", "--output", default="report.html", help="输出 HTML 路径（默认 report.html）")
    parser.add_argument(
        "--package",
        action="store_true",
        help="预留参数：后续用于打包/分发场景，当前版本仅打印提示",
    )
    return parser.parse_args(argv)


def collect_sessions(discovered):
    """按 fmt 路由解析全部输入，返回 (sessions, failed)。任何失败都不中断。"""
    sessions = []
    failed = []
    for path, name, fmt in discovered:
        try:
            if fmt == "doubao":
                sessions.extend(parse_doubao_dir(path))
            elif fmt in _SINGLE_FILE_PARSERS:
                sessions.append(_SINGLE_FILE_PARSERS[fmt](path))
            else:
                # fmt 为 None（不可识别文件）静默跳过
                continue
        except Exception as exc:  # noqa: BLE001 —— 单文件失败不中断整批
            failed.append({"path": str(path), "error": str(exc)})
    return sessions, failed


def build_meta(manifest, sessions, failed, generated_at=None):
    """manifest 优先，缺失字段用默认值兜底，保证 render 需要的四个键齐全。"""
    meta = dict(manifest or {})
    meta.setdefault("machine", platform.node() or "unknown")
    meta.setdefault(
        "generated_at",
        generated_at or datetime.now().astimezone().isoformat(timespec="seconds"),
    )
    meta["failed"] = failed
    meta["session_count"] = len(sessions)
    return meta


def main(argv=None):
    args = parse_args(argv)

    if args.package:
        print("提示：--package 为预留参数，当前版本暂不启用打包逻辑。")

    discovered = discover_inputs(args.input)
    sessions, failed = collect_sessions(discovered)

    meta = build_meta(load_manifest(args.input), sessions, failed)
    render_html(sessions, meta=meta, out=args.output)

    print(f"扫描输入：{len(discovered)} 项")
    print(f"解析会话：{len(sessions)} 个，失败 {len(failed)} 项")
    if failed:
        for item in failed:
            print(f"  [跳过] {item['path']}: {item['error']}")
    print(f"报告已生成：{Path(args.output).resolve()}")

    # 解析失败时仍成功出报告（弱一致），失败详情已写入 meta.failed
    return 0


if __name__ == "__main__":
    sys.exit(main())
