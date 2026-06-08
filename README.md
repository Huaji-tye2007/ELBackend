# ELBackend Frontend Integration Guide

面向前端开发者的后端调用说明。本文只描述前端需要关心的 HTTP API、数据格式、启动方式和一套可复制的验证流程。

## 1. 后端定位

ELBackend 是纯 FastAPI 后端，默认 API 前缀为：

```text
http://127.0.0.1:8000/api/v1
```

前端主要消费两类数据：

- 剧集阅读 JSON：`GET /api/v1/episode/{episode_id}`，格式为 `{ meta, messages, vocab }`
- 阅读行为上报：`POST /api/v1/reading/log` 和 `POST /api/v1/reading/finish`

当前额外回传约定：

- 后端返回的 `messages[].marks[]` 会携带 `item_id`
- 前端渲染仍使用 `word/index/definition/is_new`
- 前端上报阅读行为时必须回传 `item_id`
- 前端可以保留既有 lemma / 词形还原逻辑；`item_id` 只是额外回传给后端的稳定学习对象主键

## 2. 本地启动

### 2.1 环境要求

- Windows PowerShell
- Python 3.10
- 项目内虚拟环境：`.venv`
- ECDICT 数据库：`asset/ecdict_mobile.db`
- LLM 配置：`.env`

`.env` 至少包含：

```env
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=your-key
LLM_MODEL=deepseek-v4-flash
LLM_INSTRUCTOR_MODE=JSON
```

`LLM_INSTRUCTOR_MODE=JSON` 是推荐默认值。部分 thinking 模型不支持 tool calling 的 `tool_choice` 参数，使用 JSON 模式可以避开这个限制。

### 2.2 启动命令

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

健康检查：

```powershell
curl.exe http://127.0.0.1:8000/api/v1/health
```

期望响应：

```json
{ "status": "ok" }
```

## 3. 前端调用顺序

推荐的完整流程：

```text
1. POST /vocabulary/upload      上传用户词表
2. POST /novel/upload           上传小说原文
3. POST /arc/generate           触发生成下一段 Arc
4. GET  /arc/status             轮询生成状态
5. GET  /episode/cache/status   查看已缓存剧集
6. GET  /episode/{episode_id}   获取剧集 JSON 并渲染
7. POST /reading/log            上报本集词汇出现/点击行为
8. POST /reading/finish         完成本集，触发 FSRS 更新
9. GET  /progress               获取阅读进度
```

## 4. Episode JSON 格式

`GET /episode/{episode_id}` 返回：

```json
{
  "meta": {
    "ep": 1,
    "title": "Episode 1",
    "kind": "main"
  },
  "messages": [
    {
      "type": "narration",
      "text": "I consumed the last cookie.",
      "marks": [
        {
          "item_id": "consume_1",
          "word": "consumed",
          "index": 1,
          "definition": "消耗",
          "is_new": true
        }
      ]
    },
    {
      "type": "dialogue",
      "side": "right",
      "name": "Me",
      "text": "I need to be more careful.",
      "marks": []
    }
  ],
  "vocab": [
    {
      "item_id": "consume_1",
      "word": "consumed",
      "definition": "消耗",
      "is_new": true
    }
  ]
}
```

前端渲染规则：

- `messages[].type = "narration"`：叙述/动作/心理描写
- `messages[].type = "dialogue"`：对话
- `dialogue.side = "right"`：主角侧
- `dialogue.side = "left"`：其他角色侧
- `marks[].index`：按 `text.split(" ")` 后的 0-based 词索引，不是字符 offset
- `marks[].item_id`：后端学习对象主键。前端上报阅读行为时请原样回传
- `marks[].word`：文本中的表层形式，例如 `consumed`、`consuming`
- `marks[].is_new = true`：建议内联展示释义，例如 `consumed（消耗）`
- `marks[].is_new = false`：建议只加粗，点击时再查词

注意：后端更新学习状态时优先使用 `item_id`；`marks[].word` 始终是文本中的表层形式。前端可以继续使用既有 lemma 逻辑。

## 5. API 详情

### 5.0 接口总览与状态码

所有响应体为 JSON。错误响应统一为：

```json
{ "detail": "error message" }
```

| Method | Path | Body | 200/成功响应 | 常见错误 |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/health` | 无 | `{ "status": "ok" }` | - |
| POST | `/api/v1/vocabulary/upload` | `{user_id, items:[{word, meaning}]}` | `{ "count": number }` | `400` 词表非法；`500` 保存/预处理失败 |
| GET | `/api/v1/vocabulary` | 无 | `UserVocabulary` | `500` 读取失败 |
| GET | `/api/v1/vocabulary/{item_id}` | 无 | `VocabularyItem` | `404` item 不存在；`500` 读取失败 |
| POST | `/api/v1/novel/upload` | `{title, raw_text}` | `{ "chapter_count": number }` | `422` 请求体校验失败 |
| GET | `/api/v1/novel/chapters` | 无 | `Chapter[]` 摘要列表 | - |
| GET | `/api/v1/novel/chapters/{chapter_id}` | 无 | `Chapter` | `404` 未上传小说或章节不存在 |
| POST | `/api/v1/arc/generate` | `{ "arc_id"?: string }` | `{ "job_id": string, "status": "queued" }` | `400` 无章节；`404` 未上传小说；`409` 已有任务运行 |
| GET | `/api/v1/arc/status` | 无 | `ArcGenerationState` | - |
| GET | `/api/v1/episode/cache/status` | 无 | `{cached_count, latest_episode_id}` | - |
| GET | `/api/v1/episode/{episode_id}` | 无 | `Episode` | `404` Episode 尚未生成 |
| GET | `/api/v1/dictionary/{word}` | 无 | `{word, meaning, examples?}` | `404` 查不到词；`503` ECDICT 不可用 |
| POST | `/api/v1/reading/log` | `{episode_id, word_logs:[{item_id, appeared, clicked}]}` | `{ "updated": true }` | `400` 点击数非法；`422` 缺少/空 `item_id` 或请求体校验失败 |
| POST | `/api/v1/reading/finish` | `{ "episode_id": number }` | `{ "vocab_updated_count": number }` | `404` 无阅读日志或无词表 |
| GET | `/api/v1/progress` | 无 | `ReadingProgress` | - |
| GET | `/api/v1/reading/progress` | 无 | `ReadingProgress` | - |

### 5.1 上传词表

```http
POST /api/v1/vocabulary/upload
```

请求：

```json
{
  "user_id": "demo_user",
  "items": [
    { "word": "consume", "meaning": "消耗" },
    { "word": "invisible", "meaning": "隐形的" },
    { "word": "awkward", "meaning": "尴尬的" },
    { "word": "bank", "meaning": "河岸" },
    { "word": "bank", "meaning": "银行" }
  ]
}
```

响应：

```json
{ "count": 5 }
```

### 5.2 查询词表

```http
GET /api/v1/vocabulary
GET /api/v1/vocabulary/{item_id}
```

返回的是后端内部词汇状态，包含 FSRS card。普通阅读界面通常不需要直接消费这个接口。

### 5.3 上传小说

```http
POST /api/v1/novel/upload
```

请求：

```json
{
  "title": "Demo Novel",
  "raw_text": "Chapter 1\nThe invisible boy sat by the river bank. He consumed the last cookie and felt awkward when Anna noticed him.\n\nChapter 2\nThe next morning, the bank called about a loan. He tried to remain calm, but the conversation became awkward again."
}
```

响应：

```json
{ "chapter_count": 2 }
```

### 5.4 查询章节

```http
GET /api/v1/novel/chapters
GET /api/v1/novel/chapters/{chapter_id}
```

`/chapters` 返回章节摘要列表，不包含 `raw_text`。

`/chapters/{chapter_id}` 返回单章详情，包含 `raw_text`。

### 5.5 触发 Arc 生成

```http
POST /api/v1/arc/generate
```

请求：

```json
{ "arc_id": "demo_arc_001" }
```

`arc_id` 可省略。响应：

```json
{
  "job_id": "job_xxx",
  "status": "queued"
}
```

如果已有生成任务运行中，会返回 `409`。

### 5.6 轮询生成状态

```http
GET /api/v1/arc/status
```

响应示例：

```json
{
  "arc_id": "demo_arc_001",
  "phase": "GENERATING",
  "progress": { "current": 4, "total": 10 },
  "retry_count": 0,
  "intermediate_data": null,
  "last_error": null,
  "started_at": "2026-06-07T10:00:00+00:00",
  "updated_at": "2026-06-07T10:03:07+00:00",
  "elapsed_seconds": 187,
  "estimated_remaining_seconds": 280
}
```

阶段含义：

```text
IDLE -> PLANNING -> SCHEDULING -> GENERATING -> ANNOTATING -> FORMATTING -> COMPLETE
```

前端建议每 5-10 秒轮询一次。`phase = "COMPLETE"` 后再读取 episode。

### 5.7 查询 Episode Cache

```http
GET /api/v1/episode/cache/status
```

响应：

```json
{
  "cached_count": 10,
  "latest_episode_id": 10
}
```

### 5.8 获取剧集

```http
GET /api/v1/episode/1
```

返回 FormatSpec v3 Episode JSON，见第 4 节。

### 5.9 查词

```http
GET /api/v1/dictionary/{word}
```

示例：

```powershell
curl.exe http://127.0.0.1:8000/api/v1/dictionary/consumed
```

响应：

```json
{
  "word": "consume",
  "meaning": "消耗;消费;吃完"
}
```

实际释义取决于 ECDICT 数据库。

### 5.10 上报阅读行为

```http
POST /api/v1/reading/log
```

推荐前端在用户完成一集时上报本集所有 marks 的出现次数与点击次数。**主逻辑可以沿用现有 lemma 方案，但 reading log 必须把对应 mark 的 `item_id` 带回后端。**

请求：

```json
{
  "episode_id": 1,
  "word_logs": [
    {
      "item_id": "consume_1",
      "appeared": 1,
      "clicked": 0
    },
    {
      "item_id": "awkward_1",
      "appeared": 2,
      "clicked": 1
    }
  ]
}
```

字段说明：

- `item_id`：必填。学习对象主键，来自 `marks[].item_id`
- `appeared`：该学习对象本集出现次数
- `clicked`：用户点击查看释义次数
- `clicked <= appeared`

响应：

```json
{ "updated": true }
```

如果缺少 `item_id` 或传入空字符串，会由 Pydantic/FastAPI 返回 `422`，避免后端用表层词和释义二次猜测学习对象。

### 5.11 完成本集并更新 FSRS

```http
POST /api/v1/reading/finish
```

请求：

```json
{ "episode_id": 1 }
```

响应：

```json
{ "vocab_updated_count": 2 }
```

`vocab_updated_count` 表示本集实际更新 FSRS 的唯一词条数量。

### 5.12 查询阅读进度

兼容路径：

```http
GET /api/v1/progress
GET /api/v1/reading/progress
```

响应：

```json
{
  "current_chapter": 1,
  "current_episode": 2,
  "chapter_offset": 0.0,
  "total_episodes_read": 1
}
```

## 6. 完整验证流程

以下命令假设后端已运行在 `127.0.0.1:8000`。

如果你使用 macOS、Linux、WSL 或 Git Bash，可以直接看 **6B. Bash/curl 版本**。Windows PowerShell 用户看 **6A. PowerShell 版本**。

## 6A. PowerShell 版本

### 6.1 可选：清理运行时数据

如果想从干净状态开始，可以删除运行时数据。保留 `data/WordSenseDB.json`。

```powershell
Remove-Item data\UserVocabulary.json -ErrorAction SilentlyContinue
Remove-Item data\ChapterDB.json -ErrorAction SilentlyContinue
Remove-Item data\ReadingProgress.json -ErrorAction SilentlyContinue
Remove-Item data\arc_generation_state.json -ErrorAction SilentlyContinue
Remove-Item data\EpisodeReadingLogs -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item data\EpisodeCache\*.json -ErrorAction SilentlyContinue
```

### 6.2 上传词表

```powershell
$body = @{
  user_id = "demo_user"
  items = @(
    @{ word = "consume"; meaning = "消耗" }
    @{ word = "invisible"; meaning = "隐形的" }
    @{ word = "awkward"; meaning = "尴尬的" }
    @{ word = "bank"; meaning = "河岸" }
    @{ word = "bank"; meaning = "银行" }
  )
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/vocabulary/upload" `
  -ContentType "application/json" `
  -Body $body
```

### 6.3 上传小说

```powershell
$novel = @{
  title = "Demo Novel"
  raw_text = @"
Chapter 1
The invisible boy sat by the river bank. He consumed the last cookie and felt awkward when Anna noticed him. He wanted to hide, but the quiet room made every movement obvious.

Chapter 2
The next morning, the bank called about a loan. He tried to remain calm, but the conversation became awkward again. Anna smiled as if she could see through his invisible excuses.
"@
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/novel/upload" `
  -ContentType "application/json" `
  -Body $novel
```

### 6.4 触发生成

```powershell
$arc = @{ arc_id = "demo_arc_001" } | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/arc/generate" `
  -ContentType "application/json" `
  -Body $arc
```

### 6.5 轮询状态

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/arc/status"
```

重复执行，直到：

```json
{ "phase": "COMPLETE" }
```

如果看到：

```json
{ "phase": "FAILED", "last_error": "..." }
```

请先检查：

- `.env` 中 LLM 配置是否可用
- thinking 模型是否使用了 `LLM_INSTRUCTOR_MODE=JSON`
- `asset/ecdict_mobile.db` 是否存在
- `data/UserVocabulary.json` 是否存在
- `data/ChapterDB.json` 是否存在

### 6.6 获取剧集

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/episode/cache/status"
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/episode/1"
```

前端拿到 Episode 后，按 `messages` 渲染聊天流，并按 `marks` 加粗/展示释义。

### 6.7 上报阅读日志

如果第 1 集里出现了 `consumed` 和 `awkward`，可以模拟：

```powershell
$log = @{
  episode_id = 1
  word_logs = @(
    @{
      item_id = "awkward_1"
      appeared = 1
      clicked = 1
    }
  )
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/reading/log" `
  -ContentType "application/json" `
  -Body $log
```

### 6.8 完成本集

```powershell
$finish = @{ episode_id = 1 } | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/reading/finish" `
  -ContentType "application/json" `
  -Body $finish
```

期望：

```json
{ "vocab_updated_count": 1 }
```

### 6.9 查询进度

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/progress"
```

期望 `total_episodes_read` 增加。

## 6B. Bash/curl 版本

以下命令适用于 macOS、Linux、WSL、Git Bash。Windows Git Bash 下如果 `python` 指向错误，请改用 `py -3.10` 或直接在 PowerShell 中启动后端。

### 6B.1 启动后端

```bash
source .venv/Scripts/activate 2>/dev/null || source .venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

健康检查：

```bash
curl -s http://127.0.0.1:8000/api/v1/health | python -m json.tool
```

期望：

```json
{
  "status": "ok"
}
```

### 6B.2 可选：清理运行时数据

保留 `data/WordSenseDB.json`，只清理运行时状态。

```bash
rm -f data/UserVocabulary.json
rm -f data/ChapterDB.json
rm -f data/ReadingProgress.json
rm -f data/arc_generation_state.json
rm -rf data/EpisodeReadingLogs
rm -f data/EpisodeCache/*.json
```

### 6B.3 上传词表

```bash
curl -s -X POST "http://127.0.0.1:8000/api/v1/vocabulary/upload" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "demo_user",
    "items": [
      { "word": "consume", "meaning": "消耗" },
      { "word": "invisible", "meaning": "隐形的" },
      { "word": "awkward", "meaning": "尴尬的" },
      { "word": "bank", "meaning": "河岸" },
      { "word": "bank", "meaning": "银行" }
    ]
  }' | python -m json.tool
```

期望：

```json
{
  "count": 5
}
```

### 6B.4 上传小说

```bash
curl -s -X POST "http://127.0.0.1:8000/api/v1/novel/upload" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Demo Novel",
    "raw_text": "Chapter 1\nThe invisible boy sat by the river bank. He consumed the last cookie and felt awkward when Anna noticed him. He wanted to hide, but the quiet room made every movement obvious.\n\nChapter 2\nThe next morning, the bank called about a loan. He tried to remain calm, but the conversation became awkward again. Anna smiled as if she could see through his invisible excuses."
  }' | python -m json.tool
```

期望：

```json
{
  "chapter_count": 2
}
```

### 6B.5 触发生成

```bash
curl -s -X POST "http://127.0.0.1:8000/api/v1/arc/generate" \
  -H "Content-Type: application/json" \
  -d '{ "arc_id": "demo_arc_bash_001" }' | python -m json.tool
```

期望：

```json
{
  "job_id": "job_xxx",
  "status": "queued"
}
```

### 6B.6 轮询生成状态

单次查看：

```bash
curl -s "http://127.0.0.1:8000/api/v1/arc/status" | python -m json.tool
```

每 5 秒轮询一次：

```bash
while true; do
  curl -s "http://127.0.0.1:8000/api/v1/arc/status" | python -m json.tool
  sleep 5
done
```

看到 `"phase": "COMPLETE"` 后按 `Ctrl+C` 停止轮询。

如果看到 `"phase": "FAILED"`，检查：

- `.env` 是否配置 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`
- thinking 模型是否配置 `LLM_INSTRUCTOR_MODE=JSON`
- `asset/ecdict_mobile.db` 是否存在
- `data/UserVocabulary.json` 和 `data/ChapterDB.json` 是否存在

### 6B.7 查询 Episode Cache

```bash
curl -s "http://127.0.0.1:8000/api/v1/episode/cache/status" | python -m json.tool
```

### 6B.8 获取第 1 集完整 JSON

```bash
curl -s "http://127.0.0.1:8000/api/v1/episode/1" | python -m json.tool
```

保存到文件：

```bash
curl -s "http://127.0.0.1:8000/api/v1/episode/1" > episode_1.json
python -m json.tool episode_1.json
```

如果安装了 `jq`，也可以：

```bash
jq '.meta, (.messages | length), (.vocab | length)' episode_1.json
jq '.messages[0]' episode_1.json
```

### 6B.9 查词

```bash
curl -s "http://127.0.0.1:8000/api/v1/dictionary/consumed" | python -m json.tool
```

### 6B.10 上报阅读日志

```bash
curl -s -X POST "http://127.0.0.1:8000/api/v1/reading/log" \
  -H "Content-Type: application/json" \
  -d '{
    "episode_id": 1,
    "word_logs": [
      {
        "item_id": "consume_1",
        "appeared": 1,
        "clicked": 0
      },
      {
        "item_id": "awkward_1",
        "appeared": 1,
        "clicked": 1
      }
    ]
  }' | python -m json.tool
```

期望：

```json
{
  "updated": true
}
```

### 6B.11 完成本集

```bash
curl -s -X POST "http://127.0.0.1:8000/api/v1/reading/finish" \
  -H "Content-Type: application/json" \
  -d '{ "episode_id": 1 }' | python -m json.tool
```

期望：

```json
{
  "vocab_updated_count": 2
}
```

### 6B.12 查询阅读进度

```bash
curl -s "http://127.0.0.1:8000/api/v1/progress" | python -m json.tool
```

也可以使用兼容路径：

```bash
curl -s "http://127.0.0.1:8000/api/v1/reading/progress" | python -m json.tool
```

### 6B.13 Bash 一键烟测脚本

下面脚本会按顺序上传词表、上传小说、触发生成，并轮询状态。它不会自动上报阅读日志，因为需要先确认 episode 中实际出现了哪些 marks。

```bash
#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000/api/v1}"

echo "1. health"
curl -s "$BASE_URL/health" | python -m json.tool

echo "2. upload vocabulary"
curl -s -X POST "$BASE_URL/vocabulary/upload" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "demo_user",
    "items": [
      { "word": "consume", "meaning": "消耗" },
      { "word": "invisible", "meaning": "隐形的" },
      { "word": "awkward", "meaning": "尴尬的" },
      { "word": "bank", "meaning": "河岸" },
      { "word": "bank", "meaning": "银行" }
    ]
  }' | python -m json.tool

echo "3. upload novel"
curl -s -X POST "$BASE_URL/novel/upload" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Demo Novel",
    "raw_text": "Chapter 1\nThe invisible boy sat by the river bank. He consumed the last cookie and felt awkward when Anna noticed him.\n\nChapter 2\nThe next morning, the bank called about a loan. He tried to remain calm, but the conversation became awkward again."
  }' | python -m json.tool

echo "4. generate arc"
curl -s -X POST "$BASE_URL/arc/generate" \
  -H "Content-Type: application/json" \
  -d '{ "arc_id": "demo_arc_bash_smoke" }' | python -m json.tool

echo "5. polling status"
for i in $(seq 1 60); do
  status_json="$(curl -s "$BASE_URL/arc/status")"
  echo "$status_json" | python -m json.tool
  phase="$(python -c 'import json,sys; print(json.load(sys.stdin)["phase"])' <<< "$status_json")"
  if [ "$phase" = "COMPLETE" ] || [ "$phase" = "FAILED" ]; then
    break
  fi
  sleep 5
done

echo "6. cache status"
curl -s "$BASE_URL/episode/cache/status" | python -m json.tool
```

## 7. 前端实现建议

### 7.1 渲染 marks

伪代码：

```ts
const words = message.text.split(" ");
for (const mark of message.marks) {
  const surface = words[mark.index];
  // surface should equal mark.word, ignoring punctuation edge cases if needed.
}
```

渲染：

- `is_new=true`：`word（definition）`
- `is_new=false`：只加粗 `word`，点击后调用 `/dictionary/{word}`

### 7.2 生成阅读日志

前端可以从 Episode 中聚合：

```ts
type WordLogDraft = {
  item_id: string;
  appeared: number;
  clicked: number;
};
```

聚合 key 建议使用：

```ts
mark.item_id
```

如果同一学习对象在文本里以不同表层形式出现，例如 `consume/consumed/consuming`，这些 mark 会共享同一个 `item_id`。前端只要按 `item_id` 聚合即可。

### 7.3 错误处理

常见错误：

| HTTP | 场景                        | 前端建议                            |
| ---- | --------------------------- | ----------------------------------- |
| 400  | 阅读日志计数非法，例如 `clicked > appeared` | 检查出现/点击统计 |
| 422  | 阅读日志缺少或传入空 `item_id` | 检查是否回传了 `marks[].item_id` |
| 404  | 词表、章节或 episode 不存在 | 引导重新上传或等待生成完成          |
| 409  | Arc 正在生成                | 继续轮询 `/arc/status`              |
| 503  | ECDICT 不可用               | 提示词典资源缺失                    |

## 8. 开发者快速检查清单

- 后端启动后 `/api/v1/health` 返回 `ok`
- 上传词表后 `/api/v1/vocabulary` 能看到词条
- 上传小说后 `/api/v1/novel/chapters` 能看到章节
- 触发生成后 `/api/v1/arc/status` 最终进入 `COMPLETE`
- `/api/v1/episode/1` 返回 `{ meta, messages, vocab }`
- 阅读日志上报返回 `{ "updated": true }`
- 完成本集返回合理的 `vocab_updated_count`
- `/api/v1/progress` 中 `total_episodes_read` 增加
