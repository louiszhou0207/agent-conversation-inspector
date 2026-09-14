# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou
# =====================================================================
# discover.ps1 — AI 对话审计：端点发现脚本（Task 11）
#
# 角色：随平台"脚本下发"到客户端点执行，只负责"发现"：
#   扫描 Claude Code / Codex / WorkBuddy / 豆包 四类工具的本地存储，
#   输出 manifest.json 并把整个 JSON 回显到 stdout，供操作员在平台
#   控制台挑选要"获取文件"的会话。本脚本不解析内容、不渲染。
#
# 输出：%ProgramData%\AIAudit\manifest.json（目录不存在则创建）
# 用法：powershell -ExecutionPolicy Bypass -File discover.ps1
# 兼容：Windows PowerShell 5.1
# =====================================================================

# 全程静默：单个条目失败不中断整个扫描
$ErrorActionPreference = 'SilentlyContinue'

# ---------------- 配置 ----------------
# 所有路径一律走环境变量动态解析，不硬编码盘符，保证在任意系统盘 / 用户目录下可运行
$OutputDir     = Join-Path $env:ProgramData 'AIAudit'
$OutputFile    = Join-Path $OutputDir 'manifest.json'
$UsersRoot     = Join-Path $env:SystemDrive 'Users'
# 系统/内置 profile，不参与扫描
$ExcludedUsers = @('Public', 'Default', 'Default User', 'All Users')

# 四类工具在用户 profile 下的相对根目录
$ClaudeRoot = '.claude\projects'
$CodexRoot  = '.codex\sessions'
$WorkRoot   = '.workbuddy\projects'
# 豆包 LevelDB 与附件 Blob：%LOCALAPPDATA%\Doubao\User Data\Default\IndexedDB\<目录名>
$DoubaoRel    = 'AppData\Local\Doubao\User Data\Default\IndexedDB'
# 豆包自带会话备份目录（%USERPROFILE%\Doubao\chats，存在且有内容时是最干净来源）
$DoubaoChats  = 'Doubao\chats'

# ---------------- 工具函数 ----------------

# 将 DateTime 转为 UTC ISO8601 字符串（如 2026-09-10T08:30:00.123Z）
function Get-UtcIso8601([DateTime]$dt) {
    return $dt.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
}

# 可读性探测：文件尝试打开并读 1 字节；目录尝试枚举。
# 返回 @{ readable = bool; error = string }
function Get-ReadableState([string]$path, [bool]$isDir) {
    try {
        if ($isDir) {
            # 目录无法"读 1 字节"，以可枚举作为可读性判定
            $null = Get-ChildItem -LiteralPath $path -Force -ErrorAction Stop
        } else {
            $fs = [System.IO.File]::OpenRead($path)
            try {
                $buf = New-Object byte[] 1
                $null = $fs.Read($buf, 0, 1)
            } finally {
                $fs.Dispose()
            }
        }
        return @{ readable = $true;  error = '' }
    } catch {
        return @{ readable = $false; error = $_.Exception.Message }
    }
}

# 目录递归总大小（字节），无权限/失败时返回 0
function Get-DirSize([string]$path) {
    $total = 0L
    Get-ChildItem -LiteralPath $path -File -Recurse -Force |
        ForEach-Object { $total += $_.Length }
    return $total
}

# 构造一条 manifest 条目（会话级字段可选，缺省为空）
function New-ManifestEntry([string]$tool, [string]$user, [string]$kind,
                           [string]$relPath, [string]$absPath,
                           [long]$sizeBytes, [DateTime]$mtime,
                           [bool]$readable, [string]$readError,
                           [string]$sessionId = '', [string]$title = '',
                           [string]$firstSeen = '', [string]$lastSeen = '',
                           [int]$messageCount = 0, [string]$summary = '',
                           [string]$metaError = '', [string]$hint = '') {
    return [pscustomobject]@{
        tool          = $tool
        user          = $user
        kind          = $kind
        rel_path      = $relPath       # 相对该工具根目录的路径（/ 分隔）
        abs_path      = $absPath
        size_bytes    = $sizeBytes
        mtime         = Get-UtcIso8601 $mtime
        readable      = $readable
        read_error    = $readError
        session_id    = $sessionId
        title         = $title
        first_seen    = $firstSeen
        last_seen     = $lastSeen
        message_count = $messageCount
        summary       = $summary
        session_meta_error = $metaError
        hint          = $hint
    }
}

# 把绝对路径转成相对工具根目录的 rel_path（/ 分隔）
function Get-RelPath([string]$fullPath, [string]$root) {
    return $fullPath.Substring($root.Length).TrimStart('\', '/').Replace('\', '/')
}

# ---------------- 会话轻解析（不读全文，只读头部/尾部若干行） ----------------

# 时间归一化：ISO 字符串原样返回；毫秒时间戳（WorkBuddy）转 ISO
function Convert-ToUtcIso($ts) {
    if ($null -eq $ts -or [string]$ts -eq '') { return '' }
    if ($ts -is [string] -and $ts -match '^\d{4}-\d{2}-\d{2}T') { return $ts }
    $num = 0L
    if ([long]::TryParse([string]$ts, [ref]$num) -and $num -gt 100000000000) {
        try { return Get-UtcIso8601 ([DateTimeOffset]::FromUnixTimeMilliseconds($num).UtcDateTime) } catch { return '' }
    }
    return ''
}

# 从消息 content 字段提取文本（string 或 [ {type,text}, ... ]）
function Get-ContentText($content) {
    if ($null -eq $content) { return '' }
    if ($content -is [string]) { return $content }
    if ($content -is [System.Array]) {
        $parts = @()
        foreach ($c in $content) {
            if ($null -ne $c.text) { $parts += [string]$c.text }
        }
        return ($parts -join ' ')
    }
    return ''
}

# 截断到指定字符数（按字符，非字节）
function Truncate-Text([string]$s, [int]$max) {
    if (-not $s) { return '' }
    if ($s.Length -le $max) { return $s }
    return $s.Substring(0, $max)
}

# 是否为工具注入的系统上下文（非真实用户提问），标题/摘要应跳过
function Test-InjectedText([string]$text) {
    if (-not $text) { return $false }
    return $text -like '<environment_context>*' -or $text -like '<system-reminder*' `
        -or $text -like '<system_reminder>*' -or $text -like '<cb_summary*'
}

# 轻解析一个会话文件（读头 40 + 尾 20 行），返回
# @{ session_id; title; first_seen; last_seen; message_count; summary; error }
function Get-SessionMeta([string]$path, [string]$tool) {
    $meta = @{ session_id=''; title=''; first_seen=''; last_seen=''; message_count=0; summary=''; error='' }
    try {
        # 会话 ID：文件名（claude/workbuddy=UUID.jsonl；codex=rollout-{ts}-{UUID}.jsonl）
        $base = [System.IO.Path]::GetFileNameWithoutExtension($path)
        $uuidMatch = [regex]::Match($base, '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')
        if ($uuidMatch.Success) { $meta.session_id = $uuidMatch.Value }
        elseif ($tool -ne 'codex') { $meta.session_id = $base }

        # 头部取 60 行（aiTitle/Codex 首条 user/Claude 首条 user 均在头部）。
        # 仅 Claude 读尾部 20 行（summary 标题事件在会话末尾）；Codex/WorkBuddy
        # 不读尾部——PS 的 -Tail 对超大文件（Codex rollout 可达 10MB+）极慢
        $lines = @(Get-Content -LiteralPath $path -TotalCount 60 -Encoding UTF8 -ErrorAction Stop)
        if ($tool -eq 'claude') {
            $lines += @(Get-Content -LiteralPath $path -Tail 20 -Encoding UTF8 -ErrorAction Stop)
        }

        $seenUser   = $false
        $foundTitle = $null
        foreach ($ln in $lines) {
            if (-not $ln) { continue }
            # 跳过超大行（>8KB）：WorkBuddy 的 system-reminder 注入行常达
            # 2-12KB，ConvertFrom-Json 解析它们极慢；标题/摘要来自小行
            if ($ln.Length -gt 8000) { continue }
            try { $o = $ln | ConvertFrom-Json } catch { continue }
            $t = $o.type
            $ts = Convert-ToUtcIso $o.timestamp
            switch ($tool) {
                'claude' {
                    if ($t -eq 'summary' -and $null -ne $o.summary.title) { $foundTitle = [string]$o.summary.title }
                    elseif ($t -eq 'user') {
                        $txt = Get-ContentText $o.message.content
                        if (-not (Test-InjectedText $txt)) {
                            $meta.message_count++
                            if (-not $seenUser) { $seenUser = $true; $meta.summary = Truncate-Text $txt 120 }
                        }
                    }
                    if ($ts) { if (-not $meta.first_seen) { $meta.first_seen = $ts }; $meta.last_seen = $ts }
                }
                'codex' {
                    if ($t -eq 'response_item' -and $o.payload.type -eq 'message' -and $o.payload.role -eq 'user') {
                        $txt = Get-ContentText $o.payload.content
                        if (-not (Test-InjectedText $txt)) {
                            $meta.message_count++
                            if (-not $seenUser) { $seenUser = $true; $meta.summary = Truncate-Text $txt 120 }
                        }
                    }
                    if ($ts) { if (-not $meta.first_seen) { $meta.first_seen = $ts }; $meta.last_seen = $ts }
                }
                'workbuddy' {
                    if ($t -eq 'ai-title' -and ($null -ne $o.aiTitle -or $null -ne $o.title)) {
                        $foundTitle = if ($null -ne $o.aiTitle) { [string]$o.aiTitle } else { [string]$o.title }
                    }
                    elseif ($t -eq 'message') {
                        # WorkBuddy 的 user 消息基本全是系统注入，消息数按 assistant 回复统计
                        if ($o.role -eq 'assistant') { $meta.message_count++ }
                        elseif ($o.role -eq 'user') {
                            $txt = Get-ContentText $o.content
                            if (-not (Test-InjectedText $txt)) {
                                $meta.message_count++
                                if (-not $seenUser) { $seenUser = $true; $meta.summary = Truncate-Text $txt 120 }
                            }
                        }
                    }
                    if ($ts) { if (-not $meta.first_seen) { $meta.first_seen = $ts }; $meta.last_seen = $ts }
                }
            }
        }
        # 标题：官方标题优先，否则用首条用户消息前 60 字兜底
        if ($foundTitle) { $meta.title = Truncate-Text $foundTitle 80 }
        elseif ($meta.summary) { $meta.title = Truncate-Text $meta.summary 60 }
    } catch {
        $meta.error = $_.Exception.Message
    }
    return $meta
}

# ---------------- 各工具扫描函数 ----------------

# Claude Code：~\.claude\projects\ 递归 *.jsonl → kind=session
function Scan-Claude([string]$profile, [string]$userName) {
    $root = Join-Path $profile $ClaudeRoot
    if (-not (Test-Path -LiteralPath $root)) { return }
    Get-ChildItem -LiteralPath $root -File -Recurse -Filter '*.jsonl' -Force |
        ForEach-Object {
            # 跳过符号链接/重解析点，防止递归死循环
            if ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { return }
            $rs   = Get-ReadableState $_.FullName $false
            $meta = if ($rs.readable) { Get-SessionMeta $_.FullName 'claude' } else { @{} }
            New-ManifestEntry 'claude' $userName 'session' `
                (Get-RelPath $_.FullName $root) $_.FullName `
                $_.Length $_.LastWriteTime $rs.readable $rs.error `
                $meta.session_id $meta.title $meta.first_seen $meta.last_seen `
                $meta.message_count $meta.summary $meta.error
        }
}

# Codex：~\.codex\sessions\ 递归 rollout-*.jsonl → kind=session
function Scan-Codex([string]$profile, [string]$userName) {
    $root = Join-Path $profile $CodexRoot
    if (-not (Test-Path -LiteralPath $root)) { return }
    Get-ChildItem -LiteralPath $root -File -Recurse -Filter 'rollout-*.jsonl' -Force |
        ForEach-Object {
            if ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { return }
            $rs   = Get-ReadableState $_.FullName $false
            $meta = if ($rs.readable) { Get-SessionMeta $_.FullName 'codex' } else { @{} }
            New-ManifestEntry 'codex' $userName 'session' `
                (Get-RelPath $_.FullName $root) $_.FullName `
                $_.Length $_.LastWriteTime $rs.readable $rs.error `
                $meta.session_id $meta.title $meta.first_seen $meta.last_seen `
                $meta.message_count $meta.summary $meta.error
        }
}

# WorkBuddy：~\.workbuddy\projects\ 递归 *.jsonl；
# 路径含 \subagents\ 的 kind=subagent，否则 kind=session
function Scan-WorkBuddy([string]$profile, [string]$userName) {
    $root = Join-Path $profile $WorkRoot
    if (-not (Test-Path -LiteralPath $root)) { return }
    Get-ChildItem -LiteralPath $root -File -Recurse -Filter '*.jsonl' -Force |
        ForEach-Object {
            if ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { return }
            $kind = if ($_.FullName -match '\\subagents\\') { 'subagent' } else { 'session' }
            $rs   = Get-ReadableState $_.FullName $false
            $meta = if ($rs.readable) { Get-SessionMeta $_.FullName 'workbuddy' } else { @{} }
            New-ManifestEntry 'workbuddy' $userName $kind `
                (Get-RelPath $_.FullName $root) $_.FullName `
                $_.Length $_.LastWriteTime $rs.readable $rs.error `
                $meta.session_id $meta.title $meta.first_seen $meta.last_seen `
                $meta.message_count $meta.summary $meta.error
        }
}

# 豆包：只返回真正的对话库（桌面 chrome_doubao-chat 深度研究/任务对话 + web
# https_www.doubao.com 普通对话）及对应附件 Blob 库；audio-recorder / background /
# launcher / launcher2 / text-picker 等应用状态库为噪音，不纳入 manifest。
# 每条带 hint 拉取指引：B 段读目录自动解析全部会话。
function Scan-Doubao([string]$profile, [string]$userName) {
    $base = Join-Path $profile $DoubaoRel
    if (-not (Test-Path -LiteralPath $base)) { return }
    Get-ChildItem -LiteralPath $base -Directory -Force |
        Where-Object { $_.Name -match '^(chrome_doubao-chat|https_www\.doubao\.com)_.*\.(leveldb|blob)$' } |
        ForEach-Object {
            if ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { return }
            $kind = if ($_.Name -like '*.blob') { 'blob_dir' } else { 'leveldb_dir' }
            $hint = if ($kind -eq 'blob_dir') {
                '附件库（图片/语音/文件），与对应会话库一起拉取'
            } else {
                '拉取整个目录，B 段自动解析全部会话'
            }
            $rs   = Get-ReadableState $_.FullName $true
            New-ManifestEntry 'doubao' $userName $kind `
                "$userName/$($_.Name)" $_.FullName `
                (Get-DirSize $_.FullName) $_.LastWriteTime $rs.readable $rs.error `
                '' '' '' '' 0 '' '' $hint
        }
}

# 豆包自带会话备份：%USERPROFILE%\Doubao\chats\*.json（存在且有内容时）→ kind=chats_json
function Scan-DoubaoChats([string]$profile, [string]$userName) {
    $root = Join-Path $profile $DoubaoChats
    if (-not (Test-Path -LiteralPath $root)) { return }
    Get-ChildItem -LiteralPath $root -File -Recurse -Filter '*.json' -Force |
        ForEach-Object {
            if ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { return }
            $rs  = Get-ReadableState $_.FullName $false
            New-ManifestEntry 'doubao' $userName 'chats_json' `
                (Get-RelPath $_.FullName $root) $_.FullName `
                $_.Length $_.LastWriteTime $rs.readable $rs.error
        }
}

# ---------------- 主流程 ----------------

# 1. 枚举所有用户 profile，排除系统/内置目录
$users = Get-ChildItem -LiteralPath $UsersRoot -Directory -Force |
    Where-Object { $ExcludedUsers -notcontains $_.Name }
$userNames = @($users | ForEach-Object { $_.Name })

# 2. 逐个用户扫描四类工具，收集条目
$entries = New-Object System.Collections.Generic.List[object]
foreach ($u in $users) {
    $profile  = $u.FullName
    $userName = $u.Name
    Scan-Claude       $profile $userName | ForEach-Object { $entries.Add($_) }
    Scan-Codex        $profile $userName | ForEach-Object { $entries.Add($_) }
    Scan-WorkBuddy    $profile $userName | ForEach-Object { $entries.Add($_) }
    Scan-Doubao       $profile $userName | ForEach-Object { $entries.Add($_) }
    Scan-DoubaoChats  $profile $userName | ForEach-Object { $entries.Add($_) }
}

# 3. 解析输出目录：ProgramData 不可写（非管理员/SYSTEM）时回退到用户临时目录，
#    保证 manifest 必然落盘
if (-not (Test-Path -LiteralPath $OutputDir)) {
    try {
        New-Item -ItemType Directory -Path $OutputDir -Force -ErrorAction Stop | Out-Null
    } catch {
        $OutputDir  = Join-Path $env:TEMP 'AIAudit'
        $OutputFile = Join-Path $OutputDir 'manifest.json'
        New-Item -ItemType Directory -Path $OutputDir -Force -ErrorAction Stop | Out-Null
    }
}

# 4. 组装 manifest：顶层元信息 + 条目
$manifest = [ordered]@{
    schema_version = 4
    machine        = $env:COMPUTERNAME
    generated_at   = Get-UtcIso8601 (Get-Date)
    scanned_users  = $userNames
    output_file    = $OutputFile
    entries        = $entries.ToArray()
}
$json = $manifest | ConvertTo-Json -Depth 5

# 5. 写入输出文件；极端情况（如 TEMP 也被锁）仅回显 JSON，不中断
try {
    $json | Set-Content -LiteralPath $OutputFile -Encoding UTF8
} catch {
    # 仅回显 JSON，不中断
}

Write-Output $json
