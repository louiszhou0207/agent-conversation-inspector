# AI 对话审计小工具

浏览 Claude Code / Codex / WorkBuddy / 豆包四类工具的本地会话记录，按需生成可交付的单文件 HTML 报告。本地运行，不发起网络请求。

## 特性

- 四类工具会话自动识别与解析
- Web 工作台浏览完整会话，或 CLI 生成独立 HTML 报告

## 快速上手

环境：Windows（发现脚本）+ Python 3.8+（解析 / 界面）。

1. **发现会话**：在目标机器执行 `discover.ps1`，扫描四类工具的本地存储，输出 `manifest.json` 会话清单：

```powershell
powershell -ExecutionPolicy Bypass -File discover.ps1
```

2. **拉取数据**：按清单把目标会话文件 / 目录拉回本地，集中放到一个文件夹。

3. **浏览或出报告**，二选一：

```bash
# Web 工作台：选目录后直接浏览完整会话（推荐）
python audit_ui.py

# CLI：生成单个自包含 HTML 报告
python audit_report.py <输入目录> -o report.html
```

## 支持的工具

| 工具 | 存储位置 | 解析粒度 |
|---|---|---|
| Claude Code | `~\.claude\projects\*\*.jsonl` | 每会话一文件 |
| Codex | `~\.codex\sessions\*\*\*\rollout-*.jsonl` | 每会话一文件 |
| WorkBuddy | `~\.workbuddy\projects\*\*.jsonl` | 每会话一文件 |
| 豆包 | `%LOCALAPPDATA%\Doubao\...\IndexedDB\`（桌面 + web 两个会话库） | 整目录自动解析全部会话 |

## 测试

`python -m pytest tests/ -v`（35 passed）。测试与 `demo/in/` 示例数据均为合成数据，可用 `python tools/gen_fixtures.py` 重新生成，不含真实会话内容。

## 已知限制

- 豆包桌面库个别记录使用自研序列化标签，无法标准解码，走字符串扫描降级（内容可读、缺角色与顺序保证）；web 库为完整结构化解析
- 报告包含会话原文，属敏感数据，交付时请脱敏并控制访问权限

## 文档与许可

详细使用手册见 `docs/USAGE.md`；背景与使用场景见 `docs/use-cases.md`。MIT License © 2026 LouisZhou，详见 [LICENSE](LICENSE)。
