# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou

"""豆包（Doubao）会话解析器。

豆包桌面端是 Chromium 应用，会话存于 IndexedDB 的 LevelDB 目录。value 是
V8 v15 structured-clone 序列化。解析采用两级策略：

1. 结构化路径（首选，不降级）：用 v8serialize 完整解码每条记录。记录形态：
   - 桌面库（chrome_doubao-chat）：state.mainTaskDataMap[sessionId]
   - web 库（https_www.doubao.com）：state.chatTaskDataMap[sessionId]
   会话对象含 sentMessages（用户消息，user_type=1）与 receivedMessages
   （助手回复，user_type=2），消息正文在 content_blocks_v2[].content.text_block.text。
   会话列表（名称）在 downlink_body.pull_recent_conv_chain_downlink_body.cells。
2. 降级路径（兜底）：对 v8serialize 解不开的记录（少数自定义 tag），按记录
   做字符串扫描 + 邻近归属，打 _degraded=True。

v8serialize 未安装时自动退化为纯降级路径，不抛异常。
"""

import re
from pathlib import Path
from typing import Dict, List, Optional

from src.models import Message, Session
from src.parsers.leveldb.reader import iter_leveldb_records

# --------------------------------------------------------------------------
# V8 解码（结构化路径）
# --------------------------------------------------------------------------

try:  # pragma: no cover - 环境差异
    import v8serialize as _v8s

    _HAS_V8SERIALIZE = True
except Exception:
    _v8s = None
    _HAS_V8SERIALIZE = False


def _to_py(o, depth: int = 0):
    """把 v8serialize 的 JSObject/JSArray 递归转成 dict/list。"""
    if depth > 60:
        return o
    if hasattr(o, "items"):
        d = {str(k): _to_py(v, depth + 1) for k, v in o.items()}
        # JSArray / 密集整数键映射 → list
        if d and all(k.isdigit() for k in d):
            try:
                keys = sorted(int(k) for k in d)
                if keys == list(range(len(keys))):
                    return [d[str(i)] for i in range(len(keys))]
            except Exception:
                pass
        return d
    if isinstance(o, (list, tuple)):
        return [_to_py(v, depth + 1) for v in o]
    return o


def _varint(data: bytes, pos: int):
    shift = 0
    result = 0
    while True:
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7
        if shift > 63:
            raise ValueError("varint 越界")


def _unwrap_pb_v8(value: bytes) -> bytes:
    """部分记录的值是 protobuf 包装（field1.field2 含 IndexedDB key 与内层 V8）。

    尝试提取内层 V8 value；非 protobuf 包装时原样返回。
    """
    try:
        t, p = _varint(value, 0)
        if t != 0x0A:
            return value
        ln, p = _varint(value, p)
        inner = value[p:p + ln]
        t, p2 = _varint(inner, 0)
        if (t >> 3) != 2:
            return value
        ln2, p2 = _varint(inner, p2)
        return inner[p2:p2 + ln2]
    except Exception:
        return value


def _decode_v8_obj(value: bytes):
    """用 v8serialize 解码 value（自动解 protobuf 包装）；不可用时返回 None。"""
    if not _HAS_V8SERIALIZE:
        return None
    try:
        value = _unwrap_pb_v8(value)
        idx = value.find(b"\xff\x0f")
        if idx < 0:
            idx = value.find(b"\x80\x02")
        if idx < 0:
            return None
        return _to_py(_v8s.loads(value[idx:]))
    except Exception:
        return None


# --------------------------------------------------------------------------
# 结构化提取
# --------------------------------------------------------------------------

def _blocks_text(blocks) -> str:
    """拼接 content_blocks / content_blocks_v2 里的 text_block.text。"""
    if not isinstance(blocks, list):
        return ""
    parts = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        content = b.get("content")
        if isinstance(content, dict):
            tb = content.get("text_block")
            if isinstance(tb, dict):
                text = tb.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
    return "\n".join(parts)


def _merge_structured(obj: dict, sessions: Dict[str, Session], db: Path) -> None:
    """把一条解码记录合并进会话集合。"""
    st = obj.get("state")
    if not isinstance(st, dict):
        return
    # 桌面库 mainTaskDataMap / web 库 chatTaskDataMap
    task_map = st.get("mainTaskDataMap") or st.get("chatTaskDataMap") or {}
    if not isinstance(task_map, dict):
        return
    for sid, sdata in task_map.items():
        if not isinstance(sdata, dict):
            continue
        session = sessions.get(sid)
        if session is None:
            session = Session(tool="doubao", source=db.name or "doubao", session_id=sid)
            sessions[sid] = session
            session._conv_ids = set()
        # 用户消息 + 助手回复
        for bucket, default_role in (("sentMessages", "user"), ("receivedMessages", "assistant")):
            msgs = sdata.get(bucket)
            if not isinstance(msgs, dict):
                continue
            for _mid, m in msgs.items():
                if not isinstance(m, dict):
                    continue
                cid = m.get("conversationId")
                if cid:
                    session._conv_ids.add(str(cid))
                extra = m.get("extra")
                if not isinstance(extra, dict):
                    extra = {}
                text = _blocks_text(extra.get("content_blocks_v2")) or _blocks_text(m.get("content_blocks_v2"))
                if not text:
                    text = extra.get("tts_content") or ""
                if not text:
                    continue
                ut = extra.get("user_type")
                role = "user" if ut == 1 else ("assistant" if ut == 2 else default_role)
                ts = extra.get("create_time") or m.get("create_time") or 0
                try:
                    ts = int(ts)
                except (TypeError, ValueError):
                    ts = 0
                session.messages.append(Message(role=role, time_ms=ts, content=text[:4000]))
        # requestQuery.syncTask.messages（用户消息，桌面库）
        rq = sdata.get("requestQuery")
        if isinstance(rq, dict):
            st2 = rq.get("syncTask")
            if isinstance(st2, dict):
                for m in st2.get("messages") or []:
                    if not isinstance(m, dict):
                        continue
                    text = _blocks_text(m.get("content_block"))
                    if text:
                        ts = m.get("create_time_ms") or 0
                        try:
                            ts = int(ts)
                        except (TypeError, ValueError):
                            ts = 0
                        session.messages.append(Message(role="user", time_ms=ts, content=text[:4000]))


def _merge_titles(obj: dict, titles: Dict[str, str]) -> None:
    """downlink_body 会话列表：conversation_id → 会话名。"""
    dl = obj.get("downlink_body")
    if not isinstance(dl, dict):
        return
    cells = (dl.get("pull_recent_conv_chain_downlink_body") or {}).get("cells") or {}
    if isinstance(cells, dict):
        cells = list(cells.values())
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        conv = cell.get("conversation")
        if isinstance(conv, dict):
            cid = conv.get("conversation_id")
            name = conv.get("name")
            if cid and name:
                titles[str(cid)] = str(name)


# --------------------------------------------------------------------------
# 降级路径（字符串扫描）
# --------------------------------------------------------------------------

#: 常用汉字（用于过滤 UTF-16LE 误对齐噪声）
_COMMON_HAN = set(
    "的一是在不了有和人这中大为上个国我以要他时来用们生到作地于出就分对成会可主发年动同工"
    "也能下过子说产种面而方后多定行学法所民得经十三之进着等部度家电力里如水化高自二理起小"
    "物现实加量都两体制机当使点从业本去把性好应开它合还因由其些然前外天政四日那社义事平形"
    "相全表间样与关各重新线内数正心反你明看原又么利比或但质气第向道命此变条只没结解问意建"
    "月公无系军很情者最立代想已通并提直题党程展五果料象员革位入常文总次品式活设及管特件长"
    "求老头基资边流路级少图山统接知较将组见计别她手角期根论运农指几九区强放决西被干做必战"
    "先回则任取据处队南给色光门即保治北造百规热领七海口东导器压志世金增争济阶油思术极交受"
    "联什认六共权收证改清己美再采转更单风切打白教速花带安场身车例真务具万每目至达走积示议"
    "声报斗完类八离华名确才科张信马节话米整空元况今集温传土许步群广石记需段研界拉林律叫且"
    "究观越织装影算低持音众书布复容儿须际商非验连断深难近矿千周委素技备半办青省列习响约支"
    "般史感劳便团往酸历市克何除消构府称太准精值号率族维划选标写存候毛亲快效斯院查江型眼王"
    "按格养易置派层片始却专状育厂京识适属圆包火住调满县局照参红细引听该铁价严龙飞"
)


def _is_cjk(code: int) -> bool:
    return (
        0x4E00 <= code <= 0x9FFF
        or code in (0x3002, 0xFF0C, 0xFF1A, 0xFF1B, 0xFF1F, 0xFF01, 0x2026)
    )


def _utf16_runs(data: bytes, start: int, parity: int, maxlen: int = 800) -> List[str]:
    end = min(len(data), start + maxlen)
    i = start
    if i % 2 != parity:
        i += 1
    runs = []
    while i + 1 < end:
        code = data[i] | (data[i + 1] << 8)
        if _is_cjk(code) or (32 <= code < 127):
            j = i
            chars = []
            while j + 1 < end:
                c = data[j] | (data[j + 1] << 8)
                if _is_cjk(c) or (32 <= c < 127):
                    chars.append(chr(c))
                    j += 2
                else:
                    break
            if len(chars) >= 6:
                s = "".join(chars)
                cjk = sum(1 for ch in s if 0x4E00 <= ord(ch) <= 0x9FFF)
                common = sum(1 for ch in s if ch in _COMMON_HAN)
                if cjk / len(s) >= 0.6 and common >= 3:
                    runs.append(s)
            i = j + 2
        else:
            i += 2
    return runs


def _clean_text(s: str) -> str:
    while s and len(s) > 1 and s[0] not in _COMMON_HAN and not s[0].isascii():
        s = s[1:]
    while s and len(s) > 1 and s[-1] not in _COMMON_HAN and not s[-1].isascii():
        s = s[:-1]
    return s


def _acceptable_text(s: str) -> bool:
    if not s:
        return False
    cjk = sum(1 for ch in s if 0x4E00 <= ord(ch) <= 0x9FFF)
    ratio = cjk / len(s)
    if len(s) >= 6:
        return ratio >= 0.6
    return len(s) >= 4 and ratio >= 0.8 and cjk == len(s)


def _scan_messages(data: bytes) -> List[str]:
    texts = []
    seen = set()
    for marker in (b"text_block", b"content_blocks", b"\x07content", b"messages"):
        pos = 0
        while True:
            j = data.find(marker, pos)
            if j < 0:
                break
            for parity in (0, 1):
                for run in _utf16_runs(data, j + 6, parity):
                    cleaned = _clean_text(run)
                    if _acceptable_text(cleaned) and cleaned not in seen:
                        seen.add(cleaned)
                        texts.append(cleaned)
            pos = j + len(marker)
    return texts


_UUID_RAW = re.compile(
    rb"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _session_ids(data: bytes) -> List[str]:
    out, seen = [], set()
    for m in _UUID_RAW.finditer(data):
        sid = m.group(0).decode("ascii")
        if sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


def _merge_degraded_record(value: bytes, sessions: Dict[str, Session], db: Path) -> None:
    """降级：对单条无法结构化解码的记录做字符串提取并归属到记录内首个会话。"""
    value = _unwrap_pb_v8(value)
    if not value or len(value) < 64:
        return
    sids = _session_ids(value)
    texts = _scan_messages(value)
    if not sids and not texts:
        return
    sid = sids[0] if sids else "doubao-unattributed"
    session = sessions.get(sid)
    if session is None:
        session = Session(tool="doubao", source=db.name or "doubao", session_id=sid)
        sessions[sid] = session
    session._degraded = True
    for t in texts:
        session.messages.append(Message(role="user", time_ms=0, content=t[:4000]))


# --------------------------------------------------------------------------
# 主入口
# --------------------------------------------------------------------------

_CATCHALL_SID = "doubao-unattributed"


def parse_doubao_dir(path) -> List[Session]:
    """解析豆包 LevelDB 目录为 Session 列表；不抛异常。

    结构化优先（v8serialize），无法解码的记录走降级扫描；会话按消息数
    降序，catch-all 会话排最后。
    """
    db = Path(path)
    sessions: Dict[str, Session] = {}
    titles: Dict[str, str] = {}

    # ---- Pass 1：逐记录解码（逐条容错，单条失败不影响其它） ----
    undecoded = []
    try:
        for _key, value in iter_leveldb_records(db):
            if not value:
                continue
            try:
                obj = _decode_v8_obj(value)
            except Exception:
                obj = None
            if isinstance(obj, dict) and obj:
                try:
                    _merge_structured(obj, sessions, db)
                    _merge_titles(obj, titles)
                except Exception:
                    undecoded.append(value)
            else:
                undecoded.append(value)
    except Exception:
        undecoded = []

    # ---- Pass 2：降级路径（解码失败的记录） ----
    for value in undecoded:
        try:
            _merge_degraded_record(value, sessions, db)
        except Exception:
            continue

    # ---- 会话标题：数字 conversation_id → 会话名（downlink 会话列表） ----
    if titles:
        for session in sessions.values():
            if getattr(session, "_title", None):
                continue
            conv_ids = getattr(session, "_conv_ids", None)
            if conv_ids:
                for cid in conv_ids:
                    if cid in titles:
                        session._title = titles[cid]
                        break

    # ---- 收尾：去重、排序、剔除空会话 ----
    result = []
    global_seen: set = set()
    ordered = sorted(sessions.values(), key=lambda s: 1 if s.session_id == _CATCHALL_SID else 0)
    for session in ordered:
        seen = set()
        unique = []
        for m in session.messages:
            key = (m.role, m.time_ms, m.content)
            if key in seen or m.content in global_seen:
                continue
            seen.add(key)
            global_seen.add(m.content)
            unique.append(m)
        unique.sort(key=lambda m: (m.time_ms, id(m)))
        session.messages = unique
        if session.messages:
            result.append(session)

    result.sort(key=lambda s: (-len(s.messages), s.session_id))
    result.sort(key=lambda s: 0 if s.session_id == _CATCHALL_SID else 1)
    return result
