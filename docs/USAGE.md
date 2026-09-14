# AI 对话审计小工具 · 运营人员操作手册

> 适用对象：公司运营 / 安全服务人员
> 适用范围：在客户 Windows 终端上离线发现并审计 AI 编程 / 对话工具的本地会话记录，生成可交付的 HTML 审计报告。
> 版本：以本仓库 `discover.ps1`、`audit_report.py` 为准；文档最后更新：2026-09-13。

---

## 1. 工具概述与文件组成

本工具由「A 段发现」+「B 段解析渲染」两部分组成，全程不依赖平台在线接口：

| 组成 | 文件 | 运行位置 | 职责 |
|---|---|---|---|
| A 段：端点发现 | `discover.ps1` | 目标端点（经平台"脚本下发"执行） | 扫描四类工具的本地会话存储，输出 `manifest.json`（清单）并回显整个 JSON |
| B 段：解析 + 报告 | `audit_report.py` | 运营人员电脑 | 读取拉回的会话数据目录，解析并生成单个自包含的 HTML 报告 |
| B 段：Web 交互界面（推荐） | `audit_ui.py` + `ui.html` | 运营人员电脑 | 图形化完成"选目录 → 扫描浏览完整会话"，不必敲命令 |
| 输出产物 | `report.html` | 运营人员电脑 / 交付 | 双击即开的离线报告，无外部依赖 |

一句话流程：**在端点上跑 A 段拿到"有哪些会话"的清单 → 按清单把会话文件拉回运营电脑 → 跑 B 段（Web 界面）浏览完整解析的会话 → 现场展示；需要独立文件时用 CLI 生成 `report.html`**。

### 1.1 覆盖的工具类型

| 工具 | 存储位置 | manifest 粒度 |
|---|---|---|
| Claude Code | `~\.claude\projects\**\*.jsonl` | 每会话一个 `.jsonl`，带会话级元数据（标题/时间/消息数/摘要） |
| Codex | `~\.codex\sessions\**\rollout-*.jsonl` | 每会话一个 `.jsonl`，带会话级元数据 |
| WorkBuddy | `~\.workbuddy\projects\**\*.jsonl` | 每会话一个 `.jsonl`，带会话级元数据（路径含 `\subagents\` 的记为 `kind=subagent`） |
| 豆包（Doubao） | `%LOCALAPPDATA%\Doubao\User Data\Default\IndexedDB\` 下 `chrome_doubao-chat*`（桌面对话）与 `https_www.doubao.com*`（web 对话）的 `.leveldb` 与 `.blob` 目录 | 每个对话库一条目录（`kind=leveldb_dir` / `blob_dir`，带 `hint` 拉取指引），B 段读目录自动解析全部会话 |

> Trae CN / Antigravity 的会话正文为加密存储，本工具**不支持**，详见 FAQ 6.1。

---

## 2. 运行环境

### 2.1 端点侧（跑 A 段 discover.ps1）

- 系统：Windows 10 / 11
- PowerShell **5.1** 或更高（Win10/11 自带，无需额外安装）
- 需要能访问到目标用户的用户目录（通常以管理员 / 目标账号权限执行）

### 2.2 运营侧（跑 B 段 audit_report.py）

- Python **3.8 或更高**（后续可打包成 `exe`，届时无需装 Python，见 3.4）
- 建议在工作目录建虚拟环境并安装开发依赖，用于自检：

```powershell
# 进入工具目录（示例，替换为你实际解压/克隆的目录）
cd <工具目录>

# 创建并激活虚拟环境
python -m venv .venv
.venv\Scripts\activate

# 安装开发依赖（含 pytest，用于自检）
python -m pip install -r requirements-dev.txt

# 运行自检（全部通过即可放心使用）
python -m pytest
```

预期输出以 `35 passed` 之类的绿色结果收尾；若某个用例失败，请先停止交付并反馈给工具维护方。

---

## 3. 完整操作流程（重点）

总览（五步）：

1. **脚本下发**：对目标端点执行 `discover.ps1`，得到并查看 `manifest.json` 回显
2. **挑选会话**：根据 manifest 在平台"获取文件"中把需要的会话拉回
3. **整理目录**：把拉回的文件集中放到一个文件夹（如 `audit_主机名_日期\`）
4. **查看会话**：用 **Web 交互界面**（3.0）浏览完整解析的会话；如需独立 HTML 交付物，用 `python audit_report.py <输入目录> -o report.html`
5. **交付**：界面展示 / 把 `report.html` 发给客户，双击即开

### 3.0 Web 交互界面（推荐，B 段图形化操作）

运营人员不需要敲命令，本地启动一个工作台页面，选目录后**直接浏览完整解析的会话**：

```powershell
cd <工具目录>
.venv\Scripts\python audit_ui.py            # 自动打开浏览器；加 --no-browser 不自动打开
# 指定端口：python audit_ui.py --port 9000
```

页面功能：

| 区域 | 操作 |
|---|---|
| ① 选择会话数据目录 | 输入框直接粘贴路径，或点"选择目录"由后端弹**操作系统原生目录对话框**（Python 标准库 tkinter），选完自动填入输入框 |
| ② 扫描结果 | 点"扫描会话"后在页面内直接浏览各工具的会话列表，点击展开看消息（用户/助手气泡、工具调用折叠） |

界面与报告共用同一套 IDE 双主题（默认浅色，右上角按钮切深色，记忆在浏览器本地）。

> 说明：UI 只监听 `127.0.0.1`（本机）。工作台用于运营人员现场查看；如需可交付客户的独立 HTML 文件，请用 CLI：`python audit_report.py <输入目录> -o report.html`。

### 3.1 第一步：对端点"脚本下发"执行 discover.ps1

在终端管理 / EDR 平台的"脚本下发"功能中，把 `discover.ps1` 下发到目标端点执行，脚本会：

- 扫描系统盘 `Users\` 下所有普通用户（`%SystemDrive%\Users`，排除 Public / Default 等系统内置账户）的四类工具存储；
- 把清单写入 `%ProgramData%\AIAudit\manifest.json`（目录不存在会自动创建）；
- 同时把**整个 JSON 回显到 stdout**，运营人员在平台控制台即可直接查看。

手动在端点本地执行时的等价命令（与脚本头注释一致）：

```powershell
powershell -ExecutionPolicy Bypass -File discover.ps1
```

#### 3.1.1 manifest.json 字段含义

顶层字段：

| 字段 | 含义 |
|---|---|
| `schema_version` | 清单结构版本，当前为 `4` |
| `machine` | 机器名（`%COMPUTERNAME%`） |
| `generated_at` | 扫描生成时间（UTC ISO8601，如 `2026-09-10T13:05:21.574Z`） |
| `scanned_users` | 参与扫描的用户名列表 |
| `output_file` | manifest 实际落盘路径（ProgramData 不可写时回退到 `%TEMP%\AIAudit\`） |
| `entries` | 发现条目数组 |

`entries[]` 每条字段：

| 字段 | 含义 |
|---|---|
| `tool` | 工具标识：`claude` / `codex` / `workbuddy` / `doubao` |
| `user` | 所属 Windows 用户名 |
| `kind` | 条目类型：`session`（会话文件）、`subagent`（WorkBuddy 子代理）、`leveldb_dir`（豆包会话库目录）、`blob_dir`（豆包附件库目录）、`chats_json`（豆包备份会话） |
| `rel_path` | 相对该工具根目录的路径（`/` 分隔）；豆包条目带用户名前缀（如 `<user>/chrome_doubao-chat_0...`），多用户拉取不冲突 |
| `abs_path` | 端点上的绝对路径 |
| `size_bytes` | 文件字节数（豆包为整个目录递归总大小） |
| `mtime` | 最后修改时间（UTC ISO8601） |
| `readable` | 是否可读（`true`/`false`，见 4.1） |
| `read_error` | 可读性探测失败时的错误信息；正常为空字符串 |
| `session_id` | 会话 UUID（会话类条目；豆包目录类条目为空） |
| `title` | 会话标题（见 3.2；豆包目录类条目为空） |
| `first_seen` / `last_seen` | 会话时间范围（会话类条目；豆包目录类条目为空） |
| `message_count` | 会话消息数（会话类条目） |
| `summary` | 首条真实用户提问摘要（前 120 字，会话类条目） |
| `session_meta_error` | 轻解析失败时的错误信息；正常为空字符串 |
| `hint` | 拉取指引（豆包目录类条目：`拉取整个目录，B 段自动解析全部会话` / 附件库提示；其余条目为空） |

#### 3.1.2 manifest 样例（节选）

以下为某 Windows 端点（机器名 `HOST`，用户名 `user`）执行 `discover.ps1` 得到的 `manifest.json` 节选（内容为**虚构示例**，仅用于说明字段形态），会话类条目带会话级字段：

```json
{
    "schema_version":  4,
    "machine":  "HOST",
    "generated_at":  "2026-09-13T04:10:21.574Z",
    "scanned_users":  [ "user" ],
    "output_file":  "C:\\ProgramData\\AIAudit\\manifest.json",
    "entries":  [
        {
            "tool":  "claude",
            "user":  "user",
            "kind":  "session",
            "rel_path":  "demo-project/9f2e1a3b-4c5d-4e6f-8a7b-6c5d4e3f2a1b.jsonl",
            "abs_path":  "C:\\Users\\user\\.claude\\projects\\demo-project\\9f2e1a3b-4c5d-4e6f-8a7b-6c5d4e3f2a1b.jsonl",
            "size_bytes":  27307,
            "mtime":  "2026-09-01T01:24:23.838Z",
            "readable":  true,
            "read_error":  "",
            "session_id":  "9f2e1a3b-4c5d-4e6f-8a7b-6c5d4e3f2a1b",
            "title":  "整理项目 README 的中文翻译",
            "first_seen":  "2026-09-01T01:21:12.902Z",
            "last_seen":  "2026-09-01T01:24:15.177Z",
            "message_count":  7,
            "summary":  "帮我把项目里的 README 整理成中文版",
            "session_meta_error":  ""
        },
        {
            "tool":  "codex",
            "user":  "user",
            "kind":  "session",
            "rel_path":  "2026/09/01/rollout-2026-09-01T11-34-07-01a05b08-0408-7a83-aed5-0ffdbfcf3dc3.jsonl",
            "abs_path":  "C:\\Users\\user\\.codex\\sessions\\2026\\09\\01\\rollout-2026-09-01T11-34-07-01a05b08-0408-7a83-aed5-0ffdbfcf3dc3.jsonl",
            "size_bytes":  41544,
            "mtime":  "2026-09-01T03:34:07.852Z",
            "readable":  true,
            "read_error":  "",
            "session_id":  "01a05b08-0408-7a83-aed5-0ffdbfcf3dc3",
            "title":  "实现一个斐波那契数列函数",
            "first_seen":  "2026-03-17T02:48:58.243Z",
            "last_seen":  "2026-03-27T10:38:30.766Z",
            "message_count":  3,
            "summary":  "写一个斐波那契数列函数",
            "session_meta_error":  ""
        },
        {
            "tool":  "workbuddy",
            "user":  "user",
            "kind":  "subagent",
            "rel_path":  "demo-project/22ead6e8-feeb-46b3-ad52-4df2905a505b/subagents/agent-d331163e.jsonl",
            "abs_path":  "C:\\Users\\user\\.workbuddy\\projects\\demo-project\\22ead6e8-feeb-46b3-ad52-4df2905a505b\\subagents\\agent-d331163e.jsonl",
            "size_bytes":  113808,
            "mtime":  "2026-07-12T05:21:54.513Z",
            "readable":  true,
            "read_error":  ""
        },
        {
            "tool":  "doubao",
            "user":  "user",
            "kind":  "leveldb_dir",
            "rel_path":  "chrome_doubao-chat_0.indexeddb.leveldb",
            "abs_path":  "C:\\Users\\user\\AppData\\Local\\Doubao\\User Data\\Default\\IndexedDB\\chrome_doubao-chat_0.indexeddb.leveldb",
            "size_bytes":  11724539,
            "mtime":  "2026-09-03T03:46:11.907Z",
            "readable":  true,
            "read_error":  ""
        }
    ]
}
```

> 实际端点发现的条目数量取决于该机器安装的工具与使用频率（如某台机器可能发现 claude 16 条、codex 33 条、workbuddy 会话 5 条 + subagent 1 条、doubao 4 条（2 个对话库 + 2 个附件库）），可作为"发现结果是否符合预期"的参考量级。

### 3.2 第二步：按 manifest 挑选会话，用平台"获取文件"拉回

manifest（v3）中 **Claude Code / Codex / WorkBuddy 的每条会话条目都带会话级字段**，用于精确定位目标会话：

| 字段 | 含义 |
|---|---|
| `title` | 会话标题：官方标题（WorkBuddy 的 `aiTitle`、Claude 的 summary 标题）优先，否则取首条真实用户提问前 60 字兜底 |
| `first_seen` / `last_seen` | 会话最早 / 最晚消息时间（UTC ISO8601） |
| `message_count` | 消息数（Claude/Codex 为真实用户提问数；WorkBuddy 为助手回复数，因其 user 消息基本全是系统注入） |
| `summary` | 首条真实用户提问前 120 字（已过滤 `<system-reminder>`、`<environment_context>`、`<cb_summary>` 等工具注入内容） |
| `session_id` | 会话 UUID（也是拉回后的文件名 / 定位键） |

操作示例：目标"上周五在豆包 / Claude 里聊**项目计划**的那个会话"→ 在回显或 `manifest.json` 里按 `title` 含关键词、`last_seen` 落在上周五来筛选，直接拿到 `rel_path` 对应的文件去"获取文件"。

- **Claude Code / Codex / WorkBuddy**：**每会话一个 `.jsonl` 文件**，一次拉取一个文件（逐个对应 manifest 中 `kind=session` / `kind=subagent` 的条目）。Codex 的文件名形如 `rollout-2026-09-01T11-34-07-....jsonl`，Claude / WorkBuddy 多为 UUID 形文件名。
- **豆包**：manifest 只返回**真正的对话库**——`chrome_doubao-chat*`（桌面对话）与 `https_www.doubao.com*`（web 对话）各一条目录（`kind=leveldb_dir` 会话库 / `kind=blob_dir` 附件库），audio-recorder / background / launcher 等应用状态库已过滤不入清单；每条带 `hint` 指引，照提示操作即可。建议：
  - 把 `leveldb_dir` 与对应的 `blob_dir` 一起拉（附件库含对话中的图片/语音/文件）；
  - 按目录整体拉取，**保留目录名**（如 `chrome_doubao-chat_0.indexeddb.leveldb`，这是解析器识别豆包的关键标识）；
  - 若平台拆散成多个文件拉回，也没关系——只要目录里包含 `CURRENT` 与 `MANIFEST-000001` 两个标志文件（以及 `*.log` / `*.ldb` 数据文件），解析器仍能识别为豆包数据（见 4.2 / FAQ 6.2）；拉回后 B 段读目录自动解析出**全部会话**。

### 3.3 第三步：拉回文件放一个文件夹

把本台机器拉回的所有文件放进**同一个文件夹**，建议命名 `audit_主机名_日期`，例如：

```
audit_<主机名>_<日期>\
├── manifest.json                      （可选，建议放：界面可显示机器名等元信息）
├── claude\
│   └── 9f2e1a3b-....jsonl
├── codex\
│   └── rollout-2026-09-01....jsonl
├── workbuddy\
│   └── 22ead6e8-....jsonl
└── doubao\
    ├── chrome_doubao-chat_0.indexeddb.leveldb\   （桌面对话库）
    │   ├── CURRENT
    │   ├── MANIFEST-000001
    │   ├── *.log
    │   └── *.ldb
    └── https_www.doubao.com_0.indexeddb.leveldb\ （web 对话库，同结构）
```

子目录怎么摆都可以（解析器递归扫描），关键是**所有文件都在这个输入目录下**，且豆包目录名保持原样（`chrome_doubao-chat_0.indexeddb.leveldb` / `https_www.doubao.com_0.indexeddb.leveldb`，这是解析器识别豆包的关键标识）。

### 3.4 第四步：浏览完整解析的会话（推荐用 Web 界面）

**方式 A：Web 交互界面（推荐，运营人员不用敲命令）**

```powershell
cd <工具目录>
.venv\Scripts\python audit_ui.py            # 自动打开浏览器；加 --no-browser 不自动打开
```

浏览器打开工作台后：

1. 在"① 选择会话数据目录"粘贴路径或点"选择目录"（弹系统原生对话框）选择 3.3 的文件夹；
2. 点"**扫描会话**"——页面内直接展示各工具的会话列表（顶部有各工具会话/消息统计）；
3. 点击会话卡片展开，浏览用户 / 助手消息、工具调用（参数与结果折叠展示）、时间戳。

界面只监听本机 `127.0.0.1`，用于运营人员现场查看。

**方式 B：CLI 生成独立 HTML 报告（需要可交付的文件时）**

```powershell
# 把 <输入目录> 换成 3.3 中的文件夹路径（用引号包裹含空格的路径）
python audit_report.py <输入目录> -o report.html
```

参数说明：

| 参数 | 必填 | 说明 |
|---|---|---|
| `input` | 是 | 输入目录：拉回的会话数据文件夹（含 `manifest.json` 时可选增强报告元信息） |
| `-o, --output` | 否 | 输出 HTML 路径，默认 `report.html` |
| `--package` | 否 | 预留参数：后续用于打包 / 分发场景；当前版本仅打印提示后继续正常出报告 |

实测输出示例（对应 3.3 的目录）：

```
扫描输入：5 项
解析会话：23 个，失败 0 项
报告已生成：C:\...\audit_<主机名>_<日期>\report.html
```

三行输出的含义：

- `扫描输入：N 项` —— 识别出的待解析对象数量（`N` 个 `.jsonl` 文件 + 豆包目录各算一项）；
- `解析会话：M 个，失败 K 项` —— 成功解析出的会话总数，以及**失败并被跳过**的项数；
- `报告已生成：<绝对路径>` —— 输出 HTML 的完整路径。

若存在失败项，会逐条打印跳过明细：

```
  [跳过] <文件路径>: <错误信息>
```

> 只要 K=0，基本可以直接交付；K>0 时建议先按 4.4 / 第 5 章排查，确认失败项不影响审计目标范围。

### 3.5 第五步：交付 / 展示

- **现场查看**：Web 工作台页面直接在运营人员电脑上展示（只监听本机）；
- **独立交付文件**：如需把内容发给客户 / 归档，用 CLI 生成 `report.html`——它是**单个自包含文件**（数据内嵌，无任何 CDN / 外部资源依赖），拷贝后双击即可在浏览器打开；
- 交付前请按 4.6 做脱敏与权限控制。

---

## 4. 注意事项 / 常见问题

### 4.1 readable=false 说明权限不足

manifest 中某条目 `readable=false` 表示运行 discover.ps1 的进程无法读取该文件 / 目录（如受控文件夹、其他用户权限、加密文件系统等）。此时即使拉回文件也无法解析。处理：

- 用**管理员权限**或**具备目标用户目录读取权限的账号**重新下发执行；
- 若 `read_error` 有具体错误信息，可据此判断（如拒绝访问 / 找不到路径）。

### 4.2 豆包的解析能力说明

豆包桌面端是 Chromium 应用，会话存放在 IndexedDB 的 LevelDB 二进制存储中。解析为**两级**：

- **web 对话库**（`https_www.doubao.com_0.indexeddb.leveldb`，普通对话）：**完整结构化解析**——用户 / 助手双向消息、毫秒级真实时间戳、会话名，可信度高；
- **桌面库**（`chrome_doubao-chat_0.indexeddb.leveldb`，深度研究 / 任务对话）：会话状态记录可结构化解析；**个别记录使用豆包自研的 V8 扩展标签，无法标准解码**，走字符串扫描降级恢复——该部分消息**内容可读、但缺角色 / 顺序 / 时间戳保证**。

可放心使用的部分：

- **会话是否存在、会话数量、时间范围** —— 可信；
- web 库消息正文 —— 可信（结构化）；
- 桌面库降级消息正文 —— 尽量以整体语义为准，个别噪声不影响审计结论。

### 4.3 豆包目录被占用（LOCK）

豆包正在运行时，其 LevelDB 目录可能被进程锁定。若拉取 / 解析时出现类似 `LOCK`、`Permission denied` 报错：

- 让**脚本 / 人工先把目录复制一份副本**再拉取副本（`copy /robocopy` 均可）；
- 或先关闭豆包进程（在端点上退出豆包客户端）再拉取；
- 解析时同样优先指向"副本目录"而非正在被写入的原目录。

### 4.4 报告打开是空白 / 报错

- 检查 `-o` 指定的输出路径是否合法、当前目录是否有写权限；
- 检查**输入目录路径是否正确**：若目录为空 / 路径不存在，CLI 会打印 `扫描输入：0 项 / 解析会话：0 个` 并照常生成报告，此时报告自然无内容；
- 确认输入目录下确有 `.jsonl` 文件（Claude / Codex / WorkBuddy）或豆包 `chrome_doubao-chat_0.indexeddb.leveldb` 目录；
- 若个别 `.jsonl` 损坏导致解析失败，会显示在 `[跳过]` 明细里，不影响其余会话（详见第 5 章）。

### 4.5 大 JSONL（>50MB）

- 工具**逐行流式读取** `.jsonl`，超大文件不会一次载入内存，可正常解析；
- 但拉取时要注意体积：单文件几十 MB 甚至上百 MB 的 JSONL 在"获取文件"传输、整理目录、交付时都更耗时占空间，建议优先筛选目标时段的会话再拉取。

### 4.6 隐私合规

- 本工具**只读取本机会话文件，不发送任何外部网络请求**（报告为纯本地生成、单文件内嵌数据）；
- 报告包含**对话原文**，属于敏感数据。交付时请注意：
  - 对报告中可能出现的密钥、口令、内网地址、个人信息做脱敏；
  - 通过受控渠道交付，并控制查看权限；
  - 报告 / 输入目录使用后按公司数据保留与销毁策略处理。

---

## 5. 故障排查表

| 症状 | 原因 | 处理 |
|---|---|---|
| manifest 中某条目 `readable=false` | 运行 discover.ps1 的账号无该文件 / 目录读取权限 | 以管理员或目标用户账号重跑脚本；查看 `read_error` 定位 |
| manifest 里缺某一类工具 | 该端点未安装该工具，或用户目录下没有对应数据 | 属正常情况；确认扫描用户是否覆盖到位 |
| 豆包条目不存在 | 端点未安装豆包，或 IndexedDB 目录路径不同 | 检查 `%LOCALAPPDATA%\Doubao\...\IndexedDB\` 下目录名 |
| 报告打开空白 / 无会话 | 输入目录为空、路径错误，或没有可识别的数据文件 | 核对 3.3 目录结构；界面/CLI 输出中的 `扫描输入` / `解析会话` 计数 |
| 个别会话缺失或 `[跳过]` | 对应 `.jsonl` 损坏 / 编码异常，单文件解析失败 | 查看 `[跳过]` 明细；确认该文件是否在审计目标内，必要时重新拉取 |
| 豆包桌面库消息无时间戳 / 无角色 | 桌面库个别记录为豆包自研 V8 扩展标签，走降级扫描恢复 | 属预期行为，以整体语义为准；web 对话库为结构化解析、不受影响（见 4.2） |
| 豆包拉取 / 解析报 LOCK 或拒绝访问 | 豆包进程占用 LevelDB 目录 | 复制目录副本再拉 / 解析；或先退出豆包进程（见 4.3） |
| 运行 `python -m pytest` 报错 | 环境 / 依赖问题 | 确认 Python 3.8+，在 `.venv` 中 `pip install -r requirements-dev.txt` 后重试 |
| 运行 audit_report.py 提示找不到模块 `src.*` | 当前目录不在项目根（`audit_report.py` 所在目录） | `cd` 到项目根目录再执行，或使用绝对路径调用 |

---

## 6. 常见 FAQ

### 6.1 为什么没有 Trae / Antigravity？

Trae CN 与 Antigravity（及其它部分厂商）的会话正文在本地为**加密存储**，无法以明文读取，因此本工具不支持。本工具仅覆盖**明文落盘**的四类工具：Claude Code、Codex、WorkBuddy、豆包。若客户环境以加密工具为主，请先与安全 / 合规确认审计范围是否可覆盖。

### 6.2 豆包消息顺序可能不完全？

豆包数据来自二进制 LevelDB 存储。**web 对话库**为完整结构化解析，顺序与时间戳可信；**桌面库**中走降级扫描恢复的消息**缺失可信时间戳**（记为 0），只能按扫描到的先后排序，同一时间戳下的顺序可能与真实对话不完全一致。结论建议依赖会话整体内容，而非逐条顺序。

### 6.3 报告里的来源行是什么意思？

每个会话卡片的标题下方有一行来源，格式为：

```
工具名 · 项目目录 · 源文件名
```

- **工具名**：claude-code / codex / workbuddy / doubao；
- **项目目录**：会话记录的 `cwd`（工作目录）。Claude Code / Codex / WorkBuddy 均有；豆包无此信息，显示为"未知项目"；
- **源文件名**：该会话对应的源文件（如 `rollout-2026-09-01....jsonl` 或 UUID 形文件名），用于在输入目录 / manifest 中**回溯定位原始文件**。

### 6.4 为什么有些会话显示"无消息"或没出现在报告里？

- 空的 / 全损坏的会话文件会显示为"无消息"或从报告中排除；
- 解析失败的文件会被记入 `[跳过]` 明细（见 3.4）；
- 不可识别的文件（既非四类工具格式、又非豆包目录）会被静默跳过。如需确认，可对照 CLI 输出的 `扫描输入` 计数。

### 6.5 `--package` 参数是做什么的？

预留参数，为后续"打包成可执行文件（exe）分发"场景占位。当前版本运行时会打印一行提示（"`--package 为预留参数`"），随后照常生成报告，不影响使用。

---

## 附：自检清单（交付前逐项确认）

- [ ] manifest 字段能逐项读懂（tool / user / kind / rel_path / abs_path / size_bytes / mtime / readable / read_error / session_id / title / first_seen / last_seen / message_count / summary / hint）
- [ ] 已按 manifest 挑选会话，Claude / Codex / WorkBuddy 一次拉一个 `.jsonl`，豆包拉对话库整个 leveldb 目录（含对应 blob 附件库）
- [ ] 拉回文件已集中到 `audit_主机名_日期\`，豆包目录名保持原样
- [ ] `python audit_ui.py` 启动后扫描目录，解析出会话、无失败项
- [ ] （如需独立交付文件）`python audit_report.py <输入目录> -o report.html` 成功，`失败 0 项`，`report.html` 双击可打开
- [ ] 交付前已按 4.6 完成脱敏与权限控制
