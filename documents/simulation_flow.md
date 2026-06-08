# VocabFiction 完整模拟流程

> 本文档从用户视角和后端视角双线追踪系统完整生命周期。
> 覆盖所有 9 个业务模块 + ArcGenerationManager 编排层。
> 时间线：一次完整会话（首次使用 → 上传词表 → 上传小说 → Arc 生成 → 阅读 → 掌握评估 → 下一 Arc 预生成）。

---

## 目录

1. [系统初始化（服务启动）](#1-系统初始化的服务启动)
2. [上传词表（Vocabulary Upload）](#2-上传词表vocabulary-upload)
3. [上传小说（Novel Upload）](#3-上传小说novel-upload)
4. [Arc 生成管线（Arc Generation Pipeline）](#4-arc-生成管线arc-generation-pipeline)
5. [用户阅读一集（Reading Flow）](#5-用户阅读一集reading-flow)
6. [完成一集（Episode Finish）](#6-完成一集episode-finish)
7. [进度推进与下一 Arc 预生成](#7-进度推进与下一-arc-预生成)
8. [番外集（Side Episode）流程](#8-番外集side-episode流程)
9. [异常与恢复场景](#9-异常与恢复场景)

---

## 1. 系统初始化（服务启动）

### 1.1 启动时序

```
FastAPI lifespan 事件触发
  │
  ├── 1. 创建 ArcGenerationManager 单例（注入 5 个依赖服务）
  │     │
  │     ├── ArcPlanner          (纯计算，无外部依赖)
  │     ├── schedule() 函数引用  (VocabularyScheduler, 需 llm_client 参数)
  │     ├── StoryRewriter       (注入 InstructorClient)
  │     ├── VocabularyAnnotator (注入 UserVocabulary + ECDICT connection)
  │     └── EpisodeFormatter    (注入 cache_dir = data/EpisodeCache)
  │
  ├── 2. 调用 resume_on_startup()
  │     │
  │     ├── 检查 data/arc_generation_state.json 是否存在
  │     ├── 若不存在 → 日志 "starting fresh"，直接返回
  │     ├── 若 phase ∈ {IDLE, COMPLETE, FAILED} → 无操作，返回
  │     └── 若 phase 为中间状态 → 记录日志，等待外部注入数据后 resume_pipeline()
  │
  ├── 3. 挂载 API 路由（/api/v1/*）
  │
  └── 4. 健康检查端点 /health → {"status": "ok"}
```

### 1.2 数据目录状态（首次启动）

```
data/
├── WordSenseDB.json          ✅ 已存在（~200 个词条，含多义词拆分）
├── EpisodeCache/             ✅ 空目录（等待 Arc 生成填充）
├── UserVocabulary.json       ❌ 不存在
├── ChapterDB.json            ❌ 不存在
├── ReadingProgress.json      ❌ 不存在
├── EpisodeReadingLogs/       ❌ 不存在
└── arc_generation_state.json ❌ 不存在
```

**依赖注入层**（`app/core/dependencies.py`）在首次调用时按需创建：

| 工厂函数 | 创建时机 | 说明 |
|---|---|---|
| `get_settings()` | 首次调用 | 从环境变量加载，`@lru_cache` |
| `get_llm_client()` | 首次调用 | `InstructorClient(base_url, api_key, model)` |
| `get_ecdict_db()` | 首次调用 | `sqlite3.connect(asset/ecdict_mobile.db)`，不存在则抛 `503` |
| `get_user_vocab_storage()` | 首次调用 | `JSONStorage[UserVocabulary](data/UserVocabulary.json)` |
| 各 Service 工厂 | 首次调用 | 懒加载，`@lru_cache` 缓存单例 |

---

## 2. 上传词表（Vocabulary Upload）

### 2.1 用户操作

用户通过 `POST /api/v1/vocabulary/upload` 上传词表。

**请求**：

```json
{
  "user_id": "default",
  "items": [
    {"word": "issue"},
    {"word": "bank", "meaning": "银行"},
    {"word": "awkward"},
    {"word": "introduce"}
  ]
}
```

### 2.2 后端处理——VocabularyPreprocessor

```
Router: upload_vocabulary()
  │
  ├── 反序列化请求 → VocabularyUploadRequest
  │
  ├── 调用 preprocessor.preprocess(raw_items, user_id="default")
  │     │
  │     ├── 逐词处理:
  │     │   │
  │     │   ├── "issue" (无 meaning)
  │     │   │   → WordSenseDB.lookup("issue")
  │     │   │   → issue 是多义词，创建 2 个 items:
  │     │   │     issue_1 = {id: "issue_1", word: "issue", meaning: "问题, 议题, 发行"}
  │     │   │     issue_2 = {id: "issue_2", word: "issue", meaning: "vi. 发行, 流出"}
  │     │   │
  │     │   ├── "bank" (meaning="银行")
  │     │   │   → WordSenseDB.lookup("bank")
  │     │   │   → 用户指定了 meaning，尝试匹配:
  │     │   │     银行 ∈ bank_1.meaning → 匹配，创建:
  │     │   │     bank_1 = {id: "bank_1", word: "bank", meaning: "银行, 堤, 岸"}
  │     │   │
  │     │   ├── "awkward" (无 meaning)
  │     │   │   → WordSenseDB.lookup("awkward")
  │     │   │   → 非多义词，创建:
  │     │   │     awkward_1 = {id: "awkward_1", word: "awkward", meaning: "尴尬的"}
  │     │   │
  │     │   └── "introduce" (无 meaning)
  │     │       → WordSenseDB 中不存在
  │     │       → 创建占位 item:
  │     │         introduce_1 = {id: "introduce_1", word: "introduce", meaning: ""}
  │     │
  │     └── 每个 VocabularyItem 初始化 fsrs_card:
  │           {
  │             "card_id": 1717243200000,  // 当前毫秒时间戳
  │             "state": 1,               // Learning 状态
  │             "step": null,
  │             "stability": null,
  │             "difficulty": null,
  │             "due": "2026-06-07T12:00:00Z",  // 当前时间
  │             "last_review": null               // ❌ 关键：is_new 判定依据
  │           }
  │
  ├── storage.save(user_vocabulary) → atomic_write_json(data/UserVocabulary.json)
  │
  └── 返回: {"count": 5}
```

### 2.3 持久化结果

**`data/UserVocabulary.json`**（简化）：

```json
{
  "user_id": "default",
  "vocabulary": [
    {
      "id": "awkward_1",
      "word": "awkward",
      "meaning": "尴尬的",
      "chapter_first_seen": 1,
      "history_window": [0],
      "fsrs_card": {
        "card_id": 1717243200000,
        "state": 1,
        "stability": null,
        "difficulty": null,
        "due": "2026-06-07T12:00:00Z",
        "last_review": null
      }
    },
    { "id": "issue_1", "word": "issue", "meaning": "问题, 议题, 发行", ... },
    { "id": "issue_2", "word": "issue", "meaning": "vi. 发行, 流出", ... },
    { "id": "bank_1", "word": "bank", "meaning": "银行, 堤, 岸", ... },
    { "id": "introduce_1", "word": "introduce", "meaning": "", ... }
  ]
}
```

### 2.4 内存索引（加载时构建）

```python
vocab_index = {
    "awkward_1": VocabularyItem(...),
    "issue_1": VocabularyItem(...),
    "issue_2": VocabularyItem(...),
    "bank_1": VocabularyItem(...),
    "introduce_1": VocabularyItem(...),
}

lemma_index = {
    ("awkward", "尴尬的"): "awkward_1",
    ("issue", "问题, 议题, 发行"): "issue_1",
    ("issue", "vi. 发行, 流出"): "issue_2",
    ("bank", "银行, 堤, 岸"): "bank_1",
    ("introduce", ""): "introduce_1",
}
```

### 2.5 用户查询词表

`GET /api/v1/vocabulary` → 返回完整 `UserVocabulary`
`GET /api/v1/vocabulary/awkward_1` → 返回单个 `VocabularyItem`

---

## 3. 上传小说（Novel Upload）

### 3.1 用户操作

`POST /api/v1/novel/upload`

**请求**：

```json
{
  "title": "转生的我被同学们孤立了",
  "raw_text": "第一章 转生\n我睁开眼睛，发现自己在陌生的教室里。\n......\n第二章 新同学\n第二天，老师带来一个转校生。\n......"
}
```

### 3.2 后端处理——NovelPreprocessor

```
Router: upload_novel()
  │
  ├── NovelPreprocessor.preprocess(title, raw_text)
  │     │
  │     ├── chapter_splitter.split(raw_text)
  │     │   → 按 "第X章" 标题切分，返回 list[ChapterSegment]
  │     │   → 示例: [{title: "第一章 转生", text: "我睁开眼睛..."},
  │     │            {title: "第二章 新同学", text: "第二天，老师..."}]
  │     │
  │     └── 对每个章节:
  │           ├── 调用 LLM 生成 summary（中文摘要）
  │           ├── 调用 LLM 提取 characters（人物列表）
  │           ├── 调用 LLM 提取 world_setting（世界观）
  │           └── 计算 estimated_reading_time = len(raw_text.split()) / 200
  │
  ├── storage.save(chapter_db) → data/ChapterDB.json
  │
  └── 返回: {"chapter_count": 2}
```

### 3.3 持久化结果

**`data/ChapterDB.json`**：

```json
{
  "chapters": [
    {
      "chapter_id": 1,
      "title": "第一章 转生",
      "raw_text": "我睁开眼睛，发现自己在陌生的教室里。...",
      "summary": "李华醒来发现自己在陌生的教室，逐渐意识到自己转生了。",
      "characters": ["李华", "老师"],
      "world_setting": "现代校园，略带悬疑色彩",
      "estimated_reading_time": 15
    },
    {
      "chapter_id": 2,
      "title": "第二章 新同学",
      "raw_text": "第二天，老师带来一个转校生。...",
      "summary": "班级来了一个神秘的转校生，引起了李华的注意。",
      "characters": ["李华", "老师", "安娜"],
      "world_setting": "现代校园，略带悬疑色彩",
      "estimated_reading_time": 12
    }
  ]
}
```

> **注意**：当前 NovelPreprocessor 为骨架（stub），以上为设计预期行为。

---

## 4. Arc 生成管线（Arc Generation Pipeline）

这是系统最核心的流程。`ArcGenerationManager` 编排 6 个阶段，以 10 集为一个 Arc 批量生成。

### 4.1 触发方式

| 触发方式 | 条件 | 调用方 |
|---|---|---|
| **自动** | 用户阅读进度达到当前 Arc 的 60% | `ReadingTracker → ArcGenerationManager.start_generation()` |
| **手动** | `POST /api/v1/arc/generate` | 前端/开发者按钮 |
| **启动恢复** | 服务启动，检测到未完成的 checkpoint | `lifespan → resume_on_startup()` |

### 4.2 手动触发示例

`POST /api/v1/arc/generate`

**请求**：`{"arc_id": "arc_001"}`

**响应（立即）**：`{"job_id": "job_a1b2c3d4e5f6", "status": "queued"}`

**若已有任务运行中**：`409 {"detail": "A generation job is already in progress"}`

### 4.3 状态机全流程

```
IDLE (初始状态)
  │
  ├── 加锁 (asyncio.Lock)
  ├── 创建 ArcGenerationState
  ├── asyncio.create_task(_run_pipeline(...))
  └── 立即返回 {"job_id": ..., "status": "queued"}
```

#### 阶段 1：PLANNING

```
PLANNING
  │
  ├── 读取 ReadingProgress
  │     {current_chapter: 1, current_episode: 1, chapter_offset: 0.0, total_episodes_read: 0}
  │
  ├── 读取 ChapterDB（2 个章节）
  │
  ├── ArcPlanner.plan_next_arc(arc_id="arc_001", progress, chapters, prev_arc=None)
  │     │
  │     ├── _validate_inputs()
  │     │   → chapters 不为空 ✅, chapter_offset ∈ [0,1] ✅
  │     │
  │     ├── 计算起始位置:
  │     │   current_chapter=1, chapter_offset=0.0 → word_pos=0
  │     │   start_ep_id = 1（prev_arc=None 首次）
  │     │
  │     ├── _build_episodes():
  │     │   │
  │     │   ├── Episode 1 (main):
  │     │   │   ├── _extract_source_text(start=ch1, word_pos=0, num_words=600)
  │     │   │   │   → 取 ch1 前 600 词
  │     │   │   │   → end_ch=1, end_off=600
  │     │   │   ├── episode_id=1, episode_type="main"
  │     │   │   └── target_words=[]（待 Scheduler 填充）
  │     │   │
  │     │   ├── Episode 2 (main):
  │     │   │   ├── word_pos = 600 - 100 = 500（100 词重叠）
  │     │   │   ├── _extract_source_text(start=ch1, word_pos=500, num_words=600)
  │     │   │   ├── episode_id=2
  │     │   │   └── ...
  │     │   │
  │     │   ├── Episode 3~9 (main):
  │     │   │   └── 依次切片，跨章节时自动跳到 ch2
  │     │   │
  │     │   └── Episode 10 (检查是否插入 side):
  │     │       ├── _should_add_side_episode(prev_arc=None) → False（首次无 pending）
  │     │       → 全部为 main，不插入番外
  │     │
  │     └── 返回 ArcPlan（10 集 EpisodeSlot，target_words 为空）
  │
  ├── 写 checkpoint:
  │   data/arc_generation_state.json → phase=PLANNING, progress={current:0, total:0}
  │   intermediate_data: {arc_plan: {...}}
  │
  └── → 进入下一阶段
```

**`ArcPlan` 输出（简化）**：

```json
{
  "arc_id": "arc_001",
  "pending_words": [],
  "episodes": [
    {
      "episode_id": 1,
      "episode_type": "main",
      "source_text": "我睁开眼睛，发现自己在陌生的教室里。...（前 600 词）",
      "previous_context": [],
      "target_words": []
    },
    { "episode_id": 2, "episode_type": "main", "source_text": "...", ... },
    ... (Episode 3~9)
    { "episode_id": 10, "episode_type": "main", "source_text": "...", ... }
  ]
}
```

#### 阶段 2：SCHEDULING

```
SCHEDULING
  │
  ├── 读取 UserVocabulary（5 个词条，全部 last_review=null → unseen）
  │
  ├── VocabularyScheduler.schedule(arc_plan, user_vocab, now=...)
  │     │
  │     ├── build_pools(vocab, now):
  │     │   ├── unseen_pool = [awkward_1, issue_1, issue_2, bank_1, introduce_1]
  │     │   │   （全部 last_review=null）
  │     │   └── due_review_pool = []（无复习词，冷启动）
  │     │
  │     ├── apply_pending_overlay(pools, []):
  │     │   → pending_words 为空，不调整
  │     │
  │     ├── 逐集处理（以 Episode 1 为例）:
  │     │   │
  │     │   ├── source_text = ch1 前 600 词中文
  │     │   ├── candidate_count = 10 * 3 = 30
  │     │   ├── unseen_batch = unseen_pool[0:30] = 全部 5 个
  │     │   ├── review_batch = []（空）
  │     │   │
  │     │   ├── score_context(source_text, all_candidates, llm_client)
  │     │   │   → LLM 评估每个候选词能否自然嵌入剧情
  │     │   │   → 返回: {"awkward_1": 0.85, "issue_1": 0.72, "issue_2": 0.65,
  │     │   │              "bank_1": 0.91, "introduce_1": 0.78}
  │     │   │
  │     │   ├── final_score (新词):
  │     │   │   score = 0.4 * 0.3 + context_score * 0.7
  │     │   │   → awkward_1: 0.12 + 0.595 = 0.715
  │     │   │   → bank_1:    0.12 + 0.637 = 0.757
  │     │   │   → ...
  │     │   │
  │     │   ├── allocate_main_episode(...):
  │     │   │   → 新词上限 10，共 5 个，全部入选
  │     │   │   → review 词 0 个
  │     │   │   → 返回 TargetWord 列表（全部 is_new=true）
  │     │   │
  │     │   └── episode["target_words"] = [...]
  │     │
  │     ├── Episode 2~10:
  │     │   ├── 同 episode 1 的候选词（冷启动，无新词补充）
  │     │   ├── 但 Arc 内去重：同一 item_id 只能 is_new=true 一次
  │     │   ├── Episode 2 的 target_words 中：全部 marked review（is_new=false）
  │     │   └── ...（候选池用完时会报错吗？不报错，候选不足直接跳过）
  │     │
  │     └── 返回 updated arc_plan（target_words 已填充）
  │
  ├── 写 checkpoint:
  │   phase=SCHEDULING, intermediate_data: {arc_plan, scheduled}
  │
  └── → 进入下一阶段
```

**Episode 1 填充后的 target_words**：

```json
{
  "target_words": [
    {"item_id": "bank_1", "word": "bank", "meaning": "银行, 堤, 岸", "is_new": true},
    {"item_id": "awkward_1", "word": "awkward", "meaning": "尴尬的", "is_new": true},
    {"item_id": "issue_1", "word": "issue", "meaning": "问题, 议题, 发行", "is_new": true},
    {"item_id": "issue_2", "word": "issue", "meaning": "vi. 发行, 流出", "is_new": true},
    {"item_id": "introduce_1", "word": "introduce", "meaning": "", "is_new": true}
  ]
}
```

#### 阶段 3：GENERATING（10 个子阶段）

```
GENERATING(1/10)
  │
  ├── StoryRewriter.rewrite_episode(episode_slot, chapter_text)
  │     │
  │     ├── 构建 LLM prompt（System + User）
  │     │   ├── System: "You are an English light-novel writer..."
  │     │   ├── User: 包含 source_text, target_words, episode_type
  │     │   │
  │     │   └── 关键要求：
  │     │       ├── 输出 narration + dialogue 混合的消息列表
  │     │       ├── 自然嵌入目标词（只嵌合适的，不强行）
  │     │       ├── 表层形式（inflected forms）自由使用
  │     │       ├── dialogue.side: right=主角, left=其他人
  │     │       └── 报告成功嵌入的 target_words_used: [{item_id, surface}]
  │     │
  │     ├── InstructorClient.chat_structured(messages, response_model=_RewriteResponse)
  │     │   → 调用 LLM（300s 超时），返回结构化输出
  │     │
  │     ├── LLM 返回示例（_RewriteResponse）:
  │     │   {
  │     │     "messages": [
  │     │       {"type": "narration", "text": "I opened my eyes..."},
  │     │       {"type": "dialogue", "side": "left", "name": "Teacher",
  │     │        "text": "Class, let's welcome our new student."},
  │     │       {"type": "narration", "text": "An awkward silence filled the room."},
  │     │       {"type": "dialogue", "side": "right", "name": "Kazuhiko",
  │     │        "text": "I'm Kazuhiko. Nice to meet you all."},
  │     │       ...
  │     │     ],
  │     │     "target_words_used": [
  │     │       {"item_id": "awkward_1", "surface": "awkward"},
  │     │       {"item_id": "introduce_1", "surface": "introduced"},
  │     │       {"item_id": "bank_1", "surface": "bank"}
  │     │     ]
  │     │   }
  │     │
  │     ├── 转换为 Domain Messages（marks 留空待 Annotator 填充）:
  │     │   [
  │     │     NarrationMessage(type="narration", text="I opened my eyes...", marks=[]),
  │     │     DialogueMessage(type="dialogue", side="left", name="Teacher",
  │     │                      text="Class, let's...", marks=[]),
  │     │     ...
  │     │   ]
  │     │
  │     └── 返回 RewriteResult(messages=[...], target_words_used=[{"item_id": "awkward_1", "surface": "awkward"}, ...])
  │
  ├── 写 checkpoint:
  │   phase=GENERATING(1/10), progress={current:1, total:10}
  │   intermediate_data 包含 rewrite_results[0]
  │
  └── → GENERATING(2/10) ... GENERATING(10/10)
      ├── 逐集调用 StoryRewriter（共 10 次 LLM 调用）
      └── 每次成功后写 checkpoint，确保断点续跑
```

**`issue_1`, `issue_2` 未被嵌入** → 它们成为 `rejected_words`，标记到 `pending_words`：
```json
{"pending_words": [
  {"item_id": "issue_1", "rejected_count": 1},
  {"item_id": "issue_2", "rejected_count": 1}
]}
```

#### 阶段 4：ANNOTATING（10 个子阶段）

```
ANNOTATING(1/10)
  │
  ├── VocabularyAnnotator.annotate(messages, target_words, shown_set)
  │     │
  │     ├── 对每条消息逐词扫描:
  │     │   │
  │     │   ├── 消息文本: "An awkward silence filled the room."
  │     │   ├── split() → ["An", "awkward", "silence", "filled", "the", "room."]
  │     │   │
  │     │   ├── 清洗标点 → room. → room
  │     │   ├── 查 ECDICT:
  │     │   │   ├── "awkward" → lookup_lemma("awkward", ecdict_db)
  │     │   │   │   → 无 exchange 记录 → lemma = "awkward"
  │     │   │   │   → lemma_index[("awkward", "尴尬的")] → item_id = "awkward_1"
  │     │   │   │   → last_review=null, shown_set 无 → is_new=true ✅
  │     │   │   │   → shown_set.add("awkward_1")
  │     │   │   │   → Mark(word="awkward", index=1, definition="尴尬的", is_new=true)
  │     │   │   │
  │     │   │   └── "bank" → lookup_lemma("bank", ecdict_db)
  │     │   │       → 出现在文本中但不在 target_words（未被 Rewriter 嵌入）
  │     │   │       → 跳过
  │     │   │
  │     │   ↓
  │     │   假设 episode_text = "I sat on the bank of the river..."
  │     │   ├── "bank" → lookup_lemma("bank") → lemma="bank"
  │     │   ├── 来自 target: {"item_id":"bank_1", "word":"bank", "meaning":"银行, 堤, 岸"}
  │     │   ├── last_review=null + shown_set 无 → is_new=true
  │     │   └── Mark(word="bank", index=3, definition="银行, 堤, 岸", is_new=true)
  │     │
  │     └── 返回 annotated messages（marks 已填充）
  │
  ├── 写 checkpoint
  └── → ANNOTATING(2/10) ... ANNOTATING(10/10)
```

**Annotation 前/后对比**：

```json
// 前
{
  "type": "narration",
  "text": "An awkward silence filled the room.",
  "marks": []
}

// 后
{
  "type": "narration",
  "text": "An awkward silence filled the room.",
  "marks": [
    {"word": "awkward", "index": 1, "definition": "尴尬的", "is_new": true}
  ]
}
```

#### 阶段 5：FORMATTING（10 个子阶段）

```
FORMATTING(1/10)
  │
  ├── EpisodeFormatter.format_episode(meta, messages, vocab=None)
  │     │
  │     ├── 构建 Meta:
  │     │   {"ep": 1, "title": "Episode 1", "kind": "main"}
  │     │
  │     ├── 验证 messages（type="narration" 或 "dialogue"）
  │     │
  │     ├── 推导 vocab（从所有 marks 去重）:
  │     │   [
  │     │     {"word": "awkward", "definition": "尴尬的", "is_new": true},
  │     │     {"word": "introduce", "definition": "", "is_new": true}
  │     │   ]
  │     │
  │     └── 返回 Episode（已验证的 FormatSpec v3 格式）
  │
  ├── EpisodeFormatter.write_cache(episode)
  │     └── atomic_write_json(data/EpisodeCache/ep_0001.json, episode)
  │
  ├── → FORMATTING(2/10) ... FORMATTING(10/10)
  │
  └── 全部完成后 → COMPLETE
```

**写入 Episode Cache**：

```
data/EpisodeCache/
├── ep_0001.json   ✅
├── ep_0002.json   ✅
├── ep_0003.json   ✅
├── ep_0004.json   ✅
├── ep_0005.json   ✅
├── ep_0006.json   ✅
├── ep_0007.json   ✅
├── ep_0008.json   ✅
├── ep_0009.json   ✅
└── ep_0010.json   ✅
```

#### 阶段 6：COMPLETE

```
COMPLETE
  │
  ├── phase = "COMPLETE"
  ├── progress = {current: 10, total: 10}
  ├── retry_count = 0
  ├── last_error = null
  ├── 写 checkpoint
  │
  └── 日志: "Arc generation complete — arc_id=arc_001, episodes=10"
```

**最终 checkpoint**：

```json
{
  "arc_id": "arc_001",
  "phase": "COMPLETE",
  "progress": {"current": 10, "total": 10},
  "retry_count": 0,
  "last_error": null,
  "started_at": "2026-06-07T10:00:00Z",
  "updated_at": "2026-06-07T10:03:07Z"
}
```

### 4.4 前端轮询状态

`GET /api/v1/arc/status`（每 5-10 秒拉一次）：

```json
// 生成中
{"arc_id": "arc_001", "phase": "GENERATING",
 "progress": {"current": 4, "total": 10},
 "started_at": "2026-06-07T10:00:00Z",
 "updated_at": "2026-06-07T10:02:15Z",
 "elapsed_seconds": 135,
 "estimated_remaining_seconds": 202,
 "retry_count": 0, "last_error": null}

// 完成
{"arc_id": "arc_001", "phase": "COMPLETE",
 "progress": {"current": 10, "total": 10},
 "started_at": "2026-06-07T10:00:00Z",
 "updated_at": "2026-06-07T10:03:07Z",
 "retry_count": 0, "last_error": null}
```

---

## 5. 用户阅读一集（Reading Flow）

### 5.1 前端获取 Episode

`GET /api/v1/episode/1`

**响应**（FormatSpec v3）：

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
      "text": "I opened my eyes and found myself in a strange classroom.",
      "marks": []
    },
    {
      "type": "dialogue",
      "side": "left",
      "name": "Teacher",
      "text": "Class, let's welcome our new student.",
      "marks": []
    },
    {
      "type": "narration",
      "text": "An awkward silence filled the room.",
      "marks": [
        {"word": "awkward", "index": 1, "definition": "尴尬的", "is_new": true}
      ]
    },
    {
      "type": "dialogue",
      "side": "right",
      "name": "Kazuhiko",
      "text": "I'm Kazuhiko. Nice to meet you all.",
      "marks": []
    },
    {
      "type": "dialogue", 
      "side": "left",
      "name": "Anna",
      "text": "I heard you transferred from the city bank's school.",
      "marks": [
        {"word": "bank", "index": 5, "definition": "银行, 堤, 岸", "is_new": true}
      ]
    }
  ],
  "vocab": [
    {"word": "awkward", "definition": "尴尬的", "is_new": true},
    {"word": "bank", "definition": "银行, 堤, 岸", "is_new": true}
  ]
}
```

### 5.2 阅读中的前端行为

| 前端事件 | 触发条件 | 表现 |
|---|---|---|
| `is_new=true` + 首次 | `marks[].is_new == true` | 灰色内联释义：**awkward**（尴尬的） |
| `is_new=false` 复习 | `marks[].is_new == false` | 仅加粗 **awkward**，无释义，可点击 |
| 点击查询 | 用户点击 `is_new=false` 的词 | 查 `GET /api/v1/dictionary/{word}` 显示释义 |
| 下一页 | 用户点击屏幕 | 加载下一条消息 |

### 5.3 前端上报行为

**阅读中实时上报**（每出现/点击一次都发）：

`POST /api/v1/reading/log`

```json
{
  "episode_id": 1,
  "word_logs": [
    {"item_id": "awkward_1", "appeared": 1, "clicked": 0},
    {"item_id": "bank_1", "appeared": 1, "clicked": 0}
  ]
}
```

`ReadingTracker.track(log)` 处理：
1. `_save_log(log)` → 写入 `data/EpisodeReadingLogs/ep_0001.json`
2. `_advance_progress()` → 更新 `data/ReadingProgress.json`

### 5.4 阅读进度查询

`GET /api/v1/reading/progress`：

```json
{"current_chapter": 1, "current_episode": 2, "chapter_offset": 0.0, "total_episodes_read": 1}
```

---

## 6. 完成一集（Episode Finish）

### 6.1 用户触发

用户读完第 1 集 → 前端调用：

`POST /api/v1/reading/finish`

```json
{"episode_id": 1}
```

### 6.2 后端处理——MasteryEvaluator

```
Router: finish_episode()
  │
  ├── tracker.get_log(1) → 读取 data/EpisodeReadingLogs/ep_0001.json
  │   → {"episode_id": 1, "word_logs": [{"item_id": "awkward_1", "appeared": 1, "clicked": 0}]}
  │
  ├── storage.load() → 读取 data/UserVocabulary.json（当前 5 个词条）
  │
  ├── MasteryEvaluator.evaluate(episode_log, user_vocab, now=...)
  │     │
  │     ├── 逐词处理 word_log（以 awkward_1 为例）:
  │     │   │
  │     │   ├── Step 1: vocab_index["awkward_1"] → 找到 VocabularyItem
  │     │   │
  │     │   ├── Step 2: FIFO push history_window
  │     │   │   clicked=0 → new_value=1（未点击 = 认可）
  │     │   │   new_window = [0, 1, 1, 1, 1]
  │     │   │   （初始[0]，移掉第一个，尾部加1，中间用1填充）
  │     │   │
  │     │   ├── Step 3: 加权评分
  │     │   │   weights = [0.1, 0.1, 0.2, 0.2, 0.4]
  │     │   │   score = (0*0.1 + 1*0.1 + 1*0.2 + 1*0.2 + 1*0.4) / 1.0
  │     │   │         = 0.9
  │     │   │
  │     │   ├── Step 4: Rating 映射
  │     │   │   0.9 >= 0.8 → Rating.Good ✅
  │     │   │
  │     │   ├── Step 5: 创建 fsrs.Card
  │     │   │   Card(card_id=..., state=State(1), stability=None,
  │     │   │        difficulty=None, due=..., last_review=None)
  │     │   │
  │     │   ├── Step 6: FSRS 复习
  │     │   │   scheduler.review_card(card, Rating.Good)
  │     │   │   → updated_card: state=State(2), stability=2.5, difficulty=5.0,
  │     │   │     due=2026-06-08T12:00:00Z, last_review=2026-06-07T12:00:00Z
  │     │   │
  │     │   ├── Step 7: 强制跨天检查
  │     │   │   due = 2026-06-08T12:00:00Z
  │     │   │   已超过 today_end → 不修改 ✅
  │     │   │
  │     │   └── Step 8: 序列化回写
  │     │       fsrs_card.state = 2
  │     │       fsrs_card.stability = 2.5
  │     │       fsrs_card.difficulty = 5.0
  │     │       fsrs_card.due = "2026-06-08T12:00:00Z"
  │     │       fsrs_card.last_review = "2026-06-07T12:00:00Z"
  │     │
  │     └── 返回更新后的 UserVocabulary
  │
  ├── storage.save(updated_vocab) → 持久化
  │
  └── 返回: {"vocab_updated_count": 5}
```

### 6.3 更新后的 fsrs_card

```json
// awkward_1 更新后
{
  "id": "awkward_1",
  "word": "awkward",
  "fsrs_card": {
    "card_id": 1717243200000,
    "state": 1,
    "stability": 2.5,
    "difficulty": 5.0,
    "due": "2026-06-08T12:00:00Z",
    "last_review": "2026-06-07T12:00:00Z"
  },
  "history_window": [1, 1, 1, 1, 1]
}
```

> **注意**：`state` 实际值由 `State(2)` 枚举的 `.value` 决定（=2），此处为简化。

### 6.4 若用户点击了释义

假设 `awkward_1` 的 `clicked = 2`（用户点了两次查释义）：

```python
clicked > 0 → new_value = 0        # 点击 = 未认可
score = (0*0.1 + 0*0.1 + 0*0.2 + 0*0.2 + 0*0.4) / 1.0 = 0.0
0.0 < 0.5 → Rating.Again           # 用户没记住
# FSRS 会降低 stability，缩短下次复习间隔
```

---

## 7. 进度推进与下一 Arc 预生成

### 7.1 阅读进度变化

用户读 5 集后：

```
GET /api/v1/reading/progress
→ {"current_chapter": 1, "current_episode": 6, "chapter_offset": 0.5}
```

### 7.2 60% 自动触发（设计行为，当前骨架）

当 `current_episode / episodes_per_arc >= 0.6`：

```python
# ReadingTracker 内部（或由 ArcGenerationManager 轮询检查）
if progress.total_episodes_read >= DEFAULT_EPISODES_PER_ARC * 0.6:
    # 自动触发生成下一 Arc
    await arc_manager.start_generation(
        arc_id="arc_002",
        progress=progress,
        chapters=chapters,
        user_vocab=user_vocab,
        prev_arc=prev_arc_plan,
    )
```

### 7.3 下一 Arc 的差异

| 项目 | Arc 1（首次） | Arc 2（非首次） |
|---|---|---|
| `prev_arc` | `None` | `ArcPlan(arc_001)` |
| `pending_words` | `[]` | 包含 `issue_1`(rejected=1), `issue_2`(rejected=1) |
| `due_review_pool` | `[]`（冷启动） | 含 `awkward_1`(due=昨天), `bank_1`(due=昨天) |
| `_should_add_side_episode()` | `False` | `True`（pending 词 >= 5 且 rejected >= 3 时） |
| Episode 类型 | 全部 main | 9 main + 1 side（在第 10 位） |

---

## 8. 番外集（Side Episode）流程

### 8.1 触发条件

一个 `PendingWord` 被拒绝 3 次（`rejected_count >= 3`）且同一拒绝阈值的词 >= 5 个时，触发 side episode。

### 8.2 Side Episode 生成

```
Arc 2 的第 10 集（side_episode_position = -1）
  │
  ├── episode_type = "side"
  ├── source_text = null（没有原文切片）
  ├── previous_context = 上一集最后 10 条消息（用于故事连续性）
  │
  ├── VocabularyScheduler 分配 target_words:
  │   ├── 优先塞入 pending_words（issue_1, issue_2）
  │   ├── 新词上限 10，复习词上限 10
  │   └── 剩余槽位从 unseen_pool / due_review_pool 按 final_score 补充
  │
  ├── StoryRewriter 生成:
  │   ├── 无 source_text → LLM 直接创作独立短篇故事
  │   ├── LLM prompt 标记为 "Side Episode (Bonus Story)"
  │   └── 目标：自然嵌入所有 target_words
  │
  ├── VocabularyAnnotator → 正常标注 marks
  │
  └── EpisodeFormatter → 写入 Episode Cache
```

### 8.3 Side Episode 示例

```json
{
  "meta": {"ep": 20, "title": "Episode 20", "kind": "side"},
  "messages": [
    {
      "type": "narration",
      "text": "A strange issue came up at school today.",
      "marks": [
        {"word": "issue", "index": 1, "definition": "问题, 议题, 发行", "is_new": true}
      ]
    }
  ],
  "vocab": [
    {"word": "issue", "definition": "问题, 议题, 发行", "is_new": true}
  ]
}
```

---

## 9. 异常与恢复场景

### 9.1 LLM 调用超时

```
GENERATING(4/10) — LLM 调用超过 300s
  │
  ├── httpx.AsyncClient(timeout=300) 触发 TimeoutException
  │
  ├── _retry_call 捕获异常:
  │   ├── attempt=1 → wait 10s → 重试
  │   ├── attempt=2 → wait 30s → 重试
  │   └── attempt=3 → wait 90s → 重试
  │
  ├── 3 次全部失败:
  │   ├── phase = "FAILED"
  │   ├── last_error = "Phase GENERATING(4/10) failed: LLM timeout"
  │   └── retry_count = 3
  │
  └── 等待手动触发 POST /api/v1/arc/generate
```

### 9.2 服务进程崩溃

```
服务进程在 GENERATING(4/10) 时崩溃
  │
  ├── 最后一次 checkpoint 状态:
  │   phase: "GENERATING"
  │   progress: {current: 3, total: 10}
  │   intermediate_data: 前 3 集的 rewrite_results
  │
  ├── 重启后 lifespan:
  │   ├── 创建 ArcGenerationManager
  │   ├── resume_on_startup() 检测到未完成 checkpoint
  │   └── 等待外部注入数据后 resume_pipeline()
  │
  ├── resume_pipeline(progress, chapters, user_vocab, ...):
  │   ├── 检查 phase="GENERATING", progress.current=3
  │   ├── 从 intermediate_data 恢复前 3 集结果
  │   └── 从 GENERATING(4/10) 继续执行
  │
  └── 用户无感知（前端 GET /api/v1/arc/status 可看到进度继续推进）
```

### 9.3 ECDICT 数据库不存在

```
首次恢复出现时 ECDICT 不可用
  │
  ├── VocabularyAnnotator.__init__() 调用 get_ecdict_db()
  ├── Settings.ecdict_db_path = "asset/ecdict_mobile.db"
  ├── 文件不存在 → raise ECDictUnavailableError
  │
  ├── API 响应:
  │   503 {"detail": "Dictionary service unavailable"}
  │
  └── 所有需要词形还原的端点暂时不可用
```

### 9.4 并发冲突

```
用户连续点击 2 次 "生成下一 Arc"
  │
  ├── 第一次: POST /api/v1/arc/generate → 成功，_state.phase="IDLE"
  ├── 持续到 2 次: POST /api/v1/arc/generate → 此时 phase 已变
  ├── asyncio.Lock 保护:
  │   if phase not in ("COMPLETE", "FAILED"):
  │       raise GenerationConflictError("A generation job is already in progress")
  │
  └── 返回 409 Conflict
```

---

## 附录 A：关键数据流图

```
用户上传词表             用户上传小说
    │                        │
    ▼                        ▼
VocabularyPreprocessor    NovelPreprocessor
    │                        │
    ▼                        ▼
UserVocabulary.json      ChapterDB.json


ArcGenerationManager（异步编排）
    │
    ├── 1. ArcPlanner.plan_next_arc()
    │      → 切 source_text，分配 episode_type
    │
    ├── 2. VocabularyScheduler.schedule()
    │      → 构建候选池，context scoring，分配 target_words
    │
    ├── 3. StoryRewriter.rewrite_episode() × 10
    │      → LLM 改写为英文对话体
    │      → 输出含表层形式，marks 为空
    │
    ├── 4. VocabularyAnnotator.annotate() × 10
    │      → ECDICT 查 lemma → lemma_index 查 item_id
    │      → 填充 marks（表层形式 + index + is_new）
    │
    ├── 5. EpisodeFormatter.format_episode() × 10
    │      → 组装 FormatSpec v3
    │      → atomic_write_json 到 Episode Cache
    │
    └── COMPLETE

    用户阅读
       │
       ├── GET /api/v1/episode/{id} → 读 EpisodeCache
       ├── POST /api/v1/reading/log → ReadingTracker
       └── POST /api/v1/reading/finish → MasteryEvaluator
              │
              ▼
         FSRS Card 更新 → UserVocabulary.json

    阅读进度至 60% → 自动触发下一 Arc 生成（循环）
```

## 附录 B：数据文件生命周期

| 文件 | 创建时机 | 更新时机 | 读取方 |
|---|---|---|---|
| `data/WordSenseDB.json` | 手动构建（`scripts/build_word_sense_db.py`） | 不更新 | VocabularyPreprocessor |
| `data/UserVocabulary.json` | 首次上传词表 | 每次 finish_episode 后 | VocabularyScheduler, MasteryEvaluator, VocabularyAnnotator, API |
| `data/ChapterDB.json` | 上传小说 | 不更新 | ArcPlanner |
| `data/ReadingProgress.json` | 首次阅读 | 每次 track() | ArcPlanner, API |
| `data/EpisodeCache/ep_{n}.json` | Arc 生成 FORMATTING 阶段 | 不更新 | `GET /api/v1/episode/{n}` |
| `data/EpisodeReadingLogs/ep_{n}.json` | 首次上报 log | 无覆盖 | MasteryEvaluator |
| `data/arc_generation_state.json` | Arc 生成 PLANNING 阶段 | 每阶段 transition | ArcGenerationManager, lifespan |

## 附录 C：数值默认值速查

| 参数 | 默认值 | 位置 | 说明 |
|---|---|---|---|
| `DEFAULT_EPISODES_PER_ARC` | 10 | `arc_planner.py` | 每 Arc 集数 |
| `MIN_EPISODE_WORDS` | 400 | `arc_planner.py` | 每集最小词数 |
| `MAX_EPISODE_WORDS` | 600 | `arc_planner.py` | 每集最大词数 |
| `OVERLAP_WORDS` | 100 | `arc_planner.py` | 集间重叠词数 |
| `SIDE_EP_REJECT_THRESHOLD` | 3 | `arc_planner.py` | 触发番外的拒绝次数 |
| `SIDE_EP_TRIGGER_MIN_WORDS` | 5 | `arc_planner.py` | 触发番外的最少 pending 词 |
| `SIDE_EPISODE_POSITION` | -1 (末尾) | `arc_planner.py` | 番外集位置 |
| `episode_limit` | 10 | `vocabulary_scheduler` | 每集新词/复习词上限 |
| `PREVIOUS_CONTEXT_MESSAGE_COUNT` | 10 | `arc_planner.py` | 上下文消息数 |
| `history_window` 长度 | 5 | `mastery_evaluator.py` | 隐式反馈窗口 |
| `weights` | [0.1,0.1,0.2,0.2,0.4] | `mastery_evaluator.py` | 加权评分权重 |
| `Rating.Good` 阈值 | >= 0.8 | `mastery_evaluator.py` | - |
| `Rating.Hard` 阈值 | >= 0.5 | `mastery_evaluator.py` | - |
| `max_retries` | 3 | `arc_generation_manager.py` | 最大重试次数 |
| 重试间隔 | [10s, 30s, 90s] | `arc_generation_manager.py` | 指数退避 |
| LLM 超时 | 300s | `llm/client.py` | httpx 超时 |
