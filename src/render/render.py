# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou

"""HTML 报告渲染：把解析出的会话渲染成单个自包含 HTML 文件。

输出文件不依赖任何 CDN 或外部资源，双击即可在浏览器打开。
"""

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

_HERE = Path(__file__).resolve().parent
_DEFAULT_TEMPLATE = _HERE / "template.html"

#: 会话按工具分组的展示顺序
_TOOL_ORDER = ["claude-code", "codex", "workbuddy", "doubao"]


def _session_to_dict(s: Any) -> Dict[str, Any]:
    """把 Session 归一化为前端可直接消费的 dict。

    序列化字段：{tool,user,source,id,title(first 时间倒序时兜底 session_id[:8]),
    first,last,messages:[{role,t,c,tc}]}。时间戳为毫秒。
    """
    first, last = s.time_range
    title = getattr(s, "_title", None) or s.session_id[:8]
    messages: List[Dict[str, Any]] = []
    for m in s.messages:
        tc = None
        if m.tool_call is not None:
            tc = {
                "name": m.tool_call.name,
                "args": m.tool_call.args,
                "result": m.tool_call.result,
                "err": bool(m.tool_call.is_error),
            }
        # text/thinking/tool 等各类角色统一把内容放进 c
        messages.append({"role": m.role, "t": m.time_ms, "c": m.content, "tc": tc})
    return {
        "tool": s.tool,
        "user": s.user,
        "source": s.source,
        "id": s.session_id,
        "title": title,
        "first": first,
        "last": last,
        "messages": messages,
    }


def render_html(
    sessions: Iterable[Any],
    meta: Dict[str, Any],
    out: Union[str, Path],
    template: Optional[Union[str, Path]] = None,
) -> Path:
    """把 sessions 序列化为 JSON 塞进模板 __DATA__ 占位符，输出单文件。

    sessions: Session 可迭代对象；meta: 报告元信息（machine/generated_at/
    failed/session_count 等）；out: 输出 HTML 路径；template: 模板路径，缺省用
    包内 template.html。
    """
    if template is None:
        template = _DEFAULT_TEMPLATE
    template = Path(template)
    html = template.read_text(encoding="utf-8")

    payload = {
        "sessions": [_session_to_dict(s) for s in sessions],
        "meta": meta,
    }
    data = json.dumps(payload, ensure_ascii=False, indent=1)
    # 防止消息内容里的 </script> 提前截断内嵌脚本（\/ 是合法 JSON 转义）
    data = data.replace("</", "<\\/")

    # 模板形如 <script>window.__DATA__=__DATA__;</script>：只替换值位置的
    # __DATA__ 占位符，保留左侧 window.__DATA__ 属性名。
    html = html.replace("=__DATA__;", "=" + data + ";")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out
