# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou

"""audit_ui.py — AI 对话审计 · 本地 Web 交互界面（第二阶段可用性）。

用法：
    python audit_ui.py [--port 8899] [--no-browser]

功能：
  1. 目录选择：路径输入框直接粘贴，或点"选择目录"由后端弹操作系统原生
     目录对话框（Python 标准库 tkinter），返回真实绝对路径
  2. 扫描：界面内直接浏览解析出的全部会话与消息（与报告同一套 IDE 主题）

API：
    GET  /                    UI 页面
    POST /api/pickdir         弹系统原生目录对话框 → {path}
    POST /api/scan            扫描解析 {path} → {sessions, meta, failed}

依赖：Python 标准库（http.server / tkinter），无第三方依赖。
"""

import argparse
import json
import queue
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from src.detect import discover_inputs
from src.manifest import load_manifest
from src.render.render import _session_to_dict
from audit_report import collect_sessions, build_meta

_UI_HTML = (_HERE / "ui.html").read_text(encoding="utf-8")


def _json(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def _pick_dir_thread(q: "queue.Queue"):
    """在独立线程中弹操作系统原生目录对话框（tkinter）。"""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            path = filedialog.askdirectory(parent=root, title="选择会话数据目录")
        finally:
            root.destroy()
        q.put(path or "")
    except Exception:  # noqa: BLE001 —— 无 GUI 环境等场景返回空
        q.put("")


def _api_pickdir() -> dict:
    """弹系统目录对话框，返回选中路径（用户取消时为空字符串）。"""
    q: "queue.Queue" = queue.Queue()
    t = threading.Thread(target=_pick_dir_thread, args=(q,), daemon=True)
    t.start()
    try:
        path = q.get(timeout=600)
    except Exception:  # noqa: BLE001
        path = ""
    if not path:
        return {"error": "未选择目录（或当前环境无桌面对话框可用）", "path": ""}
    return {"path": path}


def _api_scan(path_str: str) -> dict:
    """扫描解析输入目录，返回会话列表（轻量）+ meta + failed。"""
    try:
        discovered = discover_inputs(path_str)
        sessions, failed = collect_sessions(discovered)
        meta = build_meta(load_manifest(path_str), sessions, failed)
        return {
            "sessions": [_session_to_dict(s) for s in sessions],
            "meta": {
                "machine": meta.get("machine", ""),
                "generated_at": meta.get("generated_at", ""),
                "failed": meta.get("failed", []),
                "session_count": meta.get("session_count", 0),
            },
            "scanned": len(discovered),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"扫描失败：{exc}"}


class Handler(BaseHTTPRequestHandler):
    server_version = "AIAuditUI/1.0"

    def _send(self, code: int, body: bytes, ctype: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length) or b"{}")
        except Exception:  # noqa: BLE001
            return {}

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._send(200, _UI_HTML.encode("utf-8"), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/pickdir":
            self._send(200, _json(_api_pickdir()))
        elif path == "/api/scan":
            data = self._read_json()
            self._send(200, _json(_api_scan(str(data.get("path", "")))))
        else:
            self._send(404, b"not found")

    def log_message(self, fmt, *args):  # 静默访问日志
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(prog="audit_ui", description="AI 对话审计 · 本地 Web 交互界面")
    parser.add_argument("--port", type=int, default=8899, help="监听端口（默认 8899）")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    args = parser.parse_args(argv)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"AI 对话审计界面已启动：{url}")
    print("操作：1) 选择拉回的会话数据目录  2) 扫描浏览会话  3) 生成报告")
    print("按 Ctrl+C 停止。")
    if not args.no_browser:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
