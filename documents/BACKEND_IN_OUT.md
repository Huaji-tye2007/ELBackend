# AI Novel Vocabulary Learning System - 系统架构设计文档（V1.5）
## 一、系统目标
用户上传：

+ 小说文本（txt）
+ 词表

系统自动：

1. 分析词表并建立用户词库
2. 分析小说并建立章节数据库
3. 根据用户词汇掌握情况动态生成阅读内容
4. 将阅读内容改写为英语轻小说对话体
5. 实现词汇复现与掌握追踪
6. 定期插入 AI 番外补充难以融入主线的词汇

---

# 二、系统数据流
```latex
用户上传词表
        │
        ▼
Vocabulary Preprocessor
读取词表 → 以用户上传的 (word, meaning) 为主建立学习对象；缺少 meaning 时用 WordSenseDB 补全/拆分 → 初始化 fsrs_card（last_review=null）→ 写入 UserVocabDB
        │
        ▼
UserVocab.json

═══════════════════════

用户上传小说
        │
        ▼
Novel Preprocessor
切分章节 → 提取标题与人物 → LLM 生成 summary 与 world_setting → 写入 ChapterDB
        │
        ▼
ChapterDB.json

═══════════════════════

系统后台生成 Arc
       │
       ▼

Arc Planner
读取：

ReadingProgress
ChapterDB
UserVocabulary

规划未来一个 Arc（默认10集）

确定：

每集对应原文片段
Side Episode 固定位置

输出 ArcPlan

    │
    ▼

Vocabulary Scheduler
计算：

Urgency Score
（复习紧迫度）

完成ArcPlan中的target_words

    │
    ▼

Batch Generator

一次生成未来10集：

Episode N ~ Episode N+9

写入 Episode Cache
        │
        ▼

Story Rewriter
携带 previous_context + source_text_chunk + ScheduledWords 调用 LLM → 改写为英文轻小说对话体 → 输出 messages[]
        │
        ▼

Vocabulary Annotator
遍历 messages[] 识别目标词表层形式 → 按 lemma 查 UserVocabDB → last_review=null 则 is_new=true → 组装 marks[] 与 vocab[]
        │
        ▼

Episode Formatter
合并 meta + messages[] + vocab[] → 打包为 FormatSpec.json → 存入 EpisodeDB
        │
        ▼

FormatSpec.json
        │
        ▼

用户阅读
        │
        ▼

Reading Tracker
接收前端 POST（每词的 clicked 状态）→ 记录本集 EpisodeReadingLog → 触发 Mastery Evaluator
        │
        ▼

Mastery Evaluator
滚动更新 history_window → 计算加权得分 → 映射为 FSRS Rating → 调用 py-fsrs 更新 fsrs_card（stability / difficulty / due）
        │
        ▼

更新 UserVocab.json
```

---

# 三、数据结构设计
---

## 1.  VocabularyItem
词表存储方法，只是一个结构体形式，不是文件

系统核心状态文件

```json
{
  "id": "issue_problem",
  "word": "issue",
  "meaning": "问题",
  "chapter_first_seen": null,
  "history_window": [1, 1, 0, 1, 1],
  "fsrs_card": {
    "card_id": 1717243200000,
    "state": 1,
    "step": null,
    "stability": null,
    "difficulty": null,
    "due": "2026-05-31T21:00:00Z",
    "last_review": null
  }
}
```

---

### 字段说明
| 字段               | 说明                                                                                                                                            |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| id                 | 词汇唯一标识符，带义项后缀（如 issue_problem vs issue_topic），区分多义词                                                                       |
| word               | 英文单词原形（lemma），供 LLM 生成对话和 lemma_index 构建使用                                                                                   |
| meaning            | 当前学习义项                                                                                                                                    |
| chapter_first_seen | 首次出现章节；上传初始化为 `null`，若后续明确首次出现章节则回填为 `>= 1` 的整数                                                                 |
| history_window     | 最近 5 次隐式阅读反馈，1 = 顺畅滑过（未点击释义），0 = 点击查看释义。由 Mastery Evaluator 滚动更新，用于计算喂给 FSRS 的加权评分。新上传词表初始化为 `[1, 1, 1, 1, 1]`；Evaluator 仍兼容历史短窗口，并会在评分前用 `1` 补齐到 5 位。 |


---

fsrs_card 内嵌对象  
对应 py-fsrs 库的 Card 类，可直接用 Card(**fsrs_card) 实例化。

| 字段        | 说明                                                                                                                            |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------- |
| card_id     | 卡片创建时间戳（毫秒），FSRS 内部唯一标识                                                                                       |
| state       | 记忆周期状态：1 = Learning（新词或短期记忆阶段）；2 = Review（进入长期间隔复习）；3 = Relearning（已掌握但遗忘，重新学习）      |
| step        | 短期记忆步数，本系统中固定为 null，短时记忆由阅读体验本身承担                                                                   |
| stability   | 记忆稳定性 S，控制遗忘曲线衰减速度，越大复习间隔越长；新词为 null                                                               |
| difficulty  | 词汇难度 D，越大说明该词对该用户越难记，会抑制稳定性增长；新词为 null                                                           |
| due         | 下次应复习的绝对时间。Vocabulary Scheduler 的核心调度依据：每次生成新集时，捞取所有 due <= NOW() 的词作为复习候选               |
| last_review | 上次复习的绝对时间。is_new 的判断依据：last_review == null 表示该词从未向用户展示过，Vocabulary Annotator 据此生成 is_new: true |


---

## 2. UserVocabulary.json
用户完整词库

```json
{
  "user_id": "001",

  "vocabulary": [
    {
      "...": "UserVocab Item"
    }
  ]
}
```

---

## 3. WordSenseDB.json
系统词义库

词表导入时使用

```json
{
  "issue": {
    "is_polysemous": true,

    "senses": [
      {
        "id": "issue_problem",
        "meaning": "问题",
      },

      {
        "id": "issue_topic",
        "meaning": "议题",
      },
    ]
  }
  "awkward": {
    "is_polysemous": false,

    "senses": [
      {
        "id": "awkward_1",
        "meaning": "尴尬的",
      }
    ]
  }
}
```

---

## 4. ChapterDB.json
小说章节数据库

```json
{
  "chapter_id": 1,

  "title": "第一章",

  "raw_text": "......",

  "summary": "李华进入学校并认识老师。",

  "characters": [
    "李华",
    "老师"
  ],
  
  "world_setting": "现代校园，略带悬疑色彩",

  "estimated_reading_time": 15
}
```

---

### 字段说明
| 字段                   | 说明                 |
| ---------------------- | -------------------- |
| chapter_id             | 章节编号             |
| title                  | 章节标题             |
| raw_text               | 原始中文文本         |
| summary                | 章节摘要             |
| characters             | 人物列表             |
| scene_tags             | 场景标签             |
| estimated_reading_time | 预计阅读时长（分钟） |


---

## 5. ReadingProgress.json
用户阅读进度

```json
{
  "current_chapter": 3,

  "current_episode": 2,

  "chapter_offset": 0.42,

  "total_episodes_read": 18
}
```

---

### 字段说明
| 字段                | 说明               |
| ------------------- | ------------------ |
| current_chapter     | 当前章节           |
| current_episode     | 当前章节内第几集   |
| chapter_offset      | 当前章节已阅读比例 |
| total_episodes_read | 总阅读集数         |


---

## 6. FormatSpec.json
最终前端消费格式（**<font style="color:#df2a3f;">以许家旗的为准，不要看这个</font>**）

```json
{
  "meta": {
    "ep": 18,
    "title": "The Glass",
    "kind": "main"
  },

  "messages": [
    {
      "type": "narration",
      "text": "I set down on the bank and watched the river.",
      "marks": [
        {"word": "bank", "index": 5, "definition": "河岸", "is_new": true}
      ]
    },

    {
      "type": "dialogue",
      "side": "left",
      "name": "Anna",
      "text": "Here is a bank.",
      "marks": [
        {"word": "bank", "index": 3, "definition": "银行", "is_new": true}
      ]
    },

    {
      "type": "dialogue",
      "side": "right",
      "name": "Kazuhiko",
      "text": "...Nukumizu who?",
      "marks": []
    }
  ],

  "vocab": [
    {"word": "bank", "definition": "河岸", "is_new": true},
    {"word": "bank", "definition": "银行", "is_new": true}
  ]
}
```

### 语义
+ 追踪单位是 **（词, 释义）对**，而非词本身。`bank=河岸` 与 `bank=银行` 是两个独立的学习对象，各自拥有独立的 `is_new` 生命周期。
+ `is_new: true` → 释义紧跟词后以内联方式展示，灰色字体：**bank**（银行）
+ `is_new: false` → 仅加粗，不展示释义。用户可点击查询。
+ 一个词可在同一条消息中出现多次——每次出现各有一个 mark，携带正确的 `index`。
+ 若消息中没有目标词，`marks` 为空数组 `[]`。

---

## 7. EpisodeReadingLog.json
本集阅读记录

```json
{
  "episode_id": 18,

  "word_logs": [
    {
      "item_id": "awkward_1",

      "appeared": 3,

      "clicked": 0
    },

    {
      "item_id": "footstep_1",

      "appeared": 2,

      "clicked": 1
    }
  ]
}
```

---

## 8.ArcPlan.json
```json
{
  "arc_id": 3,
  "pending_words": [
    {"item_id": "meticulous_1", "rejected_count": 3},
    {"item_id": "coherent_1", "rejected_count": 1}
  ],
  "episodes": [
    {
      "episode_id": 21,
      "episode_type": "main",
      "source_text": "原文片段",
      "previous_context": [
        {"name": "老师", "text": "等会儿有个转校生要来。"},
        {"name": "李华", "text": "谁啊？这么神秘。"}
      ],
      "target_words": [
        {"item_id": "awkward_1", "word": "awkward", "meaning": "尴尬的", "is_new": true},
        {"item_id": "introduce_1", "word": "introduce", "meaning": "介绍", "is_new": false}
      ]
    },
    {
      "episode_id": 25,
      "episode_type": "side",
      "source_text": null,
      "previous_context": [],
      "target_words": [
        {"item_id": "awkward_1", "word": "awkward", "meaning": "尴尬的", "is_new": true},
        {"item_id": "introduce_1", "word": "introduce", "meaning": "介绍", "is_new": false}
      ]
    }
  ]
}
```

说明：

Arc 为系统规划单位。

默认：

10集

Arc Planner 负责生成。

# 四、模块设计
---

## Module 1 Vocabulary Preprocessor
### 输入
词表

```latex
issue
charge
maintain
```

### 输出
UserVocabulary.json

### 功能
+ 词表读取
+ 用户显式提供 `meaning` 时，保留用户释义并按 `(word, meaning)` 去重生成学习对象
+ 缺少 `meaning` 时，查 WordSenseDB 补全释义并拆分多义词
+ WordSenseDB 只作为辅助词义库；若其某个 sense 合并了多个中文释义，也不能覆盖或合并用户上传的不同释义
+ 建立学习项
+ 初始化学习状态

---

## Module 2 Novel Preprocessor
### 输入
小说 txt

### 输出
ChapterDB.json

### 功能
+ 切章节
+ 提取标题
+ 提取人物
+ 生成摘要

---

## Module 3 Arc Planner  
### 输入
ChapterDB.json

ReadingProgress.json

ArcPlan.json（上一个 Arc，用于读取 pending_words）  

### 输出
 ArcPlan.json（新的 Arc）  

### 功能
规划未来一个 Arc（默认10集）

负责：

+ 按阅读进度从 ChapterDB 切出下一批原文片段，分成10集
+ 确定番外槽位（pending_words 里 rejected_count 超阈值的词集中到番外集）
+ 每集的 target_words 初始化为空数组，留给 Vocabulary Scheduler 填

---

## Module 4 Vocabulary Scheduler
### 输入
 ArcPlan.json（读当前集的 episode_type 和 pending_words）、UserVocabulary.json  

### 输出
 ArcPlan.json（补全 target_words 字段）

### 功能（设计冻结 2026-06-06）
分三步为 ArcPlan 的每个 episode 填满 target_words：

**第一步：构建候选池**
从 UserVocabulary 读取所有词，按 fsrs_card.last_review 分类：
- `unseen_pool`：`last_review is null`
- `due_review_pool`：`last_review is not null` 且 `due <= now`
- 没有 MASTERED 状态——词汇生命周期完全由 FSRS due 字段管理，due 未到的词本轮跳过。
- `pending_words` 作为优先级 overlay：pending 词排在各自池的最前面。
- unseen_pool 排序：pending 优先 → `chapter_first_seen` 升序；`null` 排在已知章节之后。
- due_review_pool 排序：pending 优先 → `fsrs_card.due` 升序。

**第二步：场景适配评分**
每集从两个池各取 `episode_word_limit * 3` 作为 LLM 初筛候选。
调用 `score_context(source_text, candidates) -> {item_id: float}` 获取 0~1 的适配分。
- `source_text is null`（side episode）时，所有候选统一返回 0.5。
- LLM client 以依赖注入方式传入 Scheduler，不在模块内硬编码。
综合评分公式：
- 新词（`last_review is null`）：`0.4 * 0.3 + context_score * 0.7`
- 复习词：`urgency * 0.5 + context_score * 0.5`
- `urgency = min(1.0, overdue_days / 30)`

**第三步：填入 target_words**
配额规则：
- main episode：新词上限 10，复习词上限 10。pending 词不强塞，按 final_score 自然竞争。
- side episode：新词上限 10，复习词上限 10。pending 词优先填满，剩余槽位再按 final_score 补充。
- 冷启动降级：review 词不够时全用新词填满，候选不足时不报错。
- Arc 内复现：同一 item_id 在整个 Arc 内只能 `is_new=true` 一次；被引入过的新词会进入本 Arc 复现池，后续 episode 可继续以 `is_new=false` 进入 `target_words`，避免小词表只在第一集出现。
- 池消费规则：每集只从 unseen/review 池移除实际选中的 item_id；同一批候选里未被选中的词必须保留给后续 episode，不能按“选中数量”推进数组指针导致靠前未选词被跳过。

**职责边界**
- 不调用 ECDICT
- 不生成 story 文本
- 不直接修改 fsrs_card（FSRS 更新由 MasteryEvaluator 在用户读完一集后处理）
- 不决定 episode_type（由 ArcPlanner 决定）
- 不维护任何 MASTERED 状态

---

## Module 5 Story Rewriter
### 输入
ArcPlan.json  

### 输出
messages[]、 rejected_words[]  

### 功能
LLM 从候选池里选能自然嵌入剧情的词，改写为英文轻小说对话体，落选词作为 rejected_words 返回  

### 说明
Story Rewriter 不再只考虑当前集。

需要遵守 Arc Planner 的长期规划：

+ target_words
+ episode_type
+ **输出文本中的词汇均为表层形式**（屈折形态，如 `"consuming"` / `"went"` / `"ran"`）。Rewriter 不做 lemma 归一化，但必须在结构化输出中报告成功嵌入词的 `{item_id, surface, message_index, word_index}`。Annotator 优先用 `message_index/word_index` 精确定位，只有缺精确位置时才退回 surface/ECDICT 兜底。

---

## Module 6 Vocabulary Annotator
### 输入
messages[]

UserVocabulary.json

### 输出
vocab[]

### 功能
判断：

+ 是否首次出现
+ 是否显示释义
+ 标记词汇位置

### 用 Scheduler 的显式 is_new 与 last_review 判断 is_new
Vocabulary Annotator 在处理一集的 messages 时，维护一个集内临时已见集合：

```python
shown_in_this_episode = set()  # 存 item_id

for each word occurrence:
    if target_word.is_new is False:
        is_new = False
    elif fsrs_card.last_review == null and item_id not in shown_in_this_episode:
        is_new = True
        shown_in_this_episode.add(item_id)
    else:
        is_new = False
```

### 表层形式 vs Lemma 的处理

第一步：Story Rewriter 生成文本时
LLM 自然地写出屈折形式（consuming、consumed、went）。
Rewriter 的输出是纯叙事文本，**不包含 lemma 标注**（marks 留空），但必须在结构化响应中报告成功嵌入的目标词：

```json
{
  "target_words_used": [
    {
      "item_id": "consume_1",
      "surface": "consumed",
      "message_index": 0,
      "word_index": 5
    }
  ]
}
```

第二步：Vocabulary Annotator 接收 Rewriter 输出的 messages 后
优先使用 `target_words_used[].message_index/word_index` 在文本中精确定位表层词，再用 `item_id → VocabularyItem` 取得释义与 FSRS 状态。`surface` 用于校验该位置 token 是否与 Rewriter 声明一致，并作为 `marks.word` 的表层形式来源。仅当 rewriter 没有返回精确位置时，才退回 surface 直接匹配或通过 ECDICT 对文本 token 做 lemma 兜底定位。

若多个 `target_words_used` 共享同一 surface（如 `bank` 的多个义项），Annotator 仍以各自的 `message_index/word_index` 定位，不再依赖返回顺序猜测位置。学习对象身份始终由 `item_id` 决定。

```python
item_id = "consume_1"          # Rewriter 返回
surface_form = "consumed"      # Rewriter 返回的表层形式，填入 marks.word
message_index = 0              # Rewriter 返回，指向 messages[0]
word_index = 5                 # Rewriter 返回，指向 messages[0].text.split(" ")[5]
item = vocab_index["consume_1"]

# Scheduler 显式传入 is_new=false 时优先作为复现词处理；否则再用
# item.fsrs_card.last_review + 集内 shown_set 判断首次展示
is_new = target_word["is_new"] and item["fsrs_card"]["last_review"] is None and (
    "consume_1" not in shown_in_this_episode
)

# 写入 marks
mark = {
    "item_id": item_id,
    "word": surface_form,   # "consumed"，表层形式
    "index": word_index,
    "definition": item["meaning"],
    "is_new": is_new
}
```

关键点：UserVocabulary 里的 VocabularyItem 存的 word 字段是 lemma（consume），不是屈折形式。

### 一词多义处理
同一 lemma 可能对应多个 item_id（如 `bank` → `bank_river` 河岸 / `bank_finance` 银行）。
主链路中不再由 Annotator/ReadingTracker 根据 `(lemma, meaning)` 二次猜 item_id；Scheduler 选出的目标词、Rewriter 返回的 `target_words_used`、Episode `marks`、Reading Log 都必须携带同一个 `item_id`。
当两个 item_id 使用相同 surface 时，Rewriter 必须返回各自准确的 `message_index/word_index`；Annotator 用位置字段分配不同 token，避免同一 `marks.index` 同时出现两个释义。

```python
vocab_index = {item["id"]: item for item in user_vocab["vocabulary"]}
item = vocab_index[item_id]
```

`lemma_index` 仍可作为词表预处理、查词或 Annotator 缺少精确位置时的辅助索引，但不得作为学习状态主键。

```python
vocab_index   # item_id → VocabularyItem，主链路使用
lemma_index   # (lemma, meaning) → item_id，仅辅助/兜底
```

---

## Module 7 Episode Formatter
### 输入
ArcPlan.json（取当前集的 episode_id、episode_type 等 meta）  

meta

messages

vocab

### 输出
FormatSpec.json

 Episode Cache  

 更新 ArcPlan.json 的 pending_words  

### 功能
生成前端展示格式

### 说明
生成结果不立即消费。

统一写入缓存。

供前端直接读取。

---

## Module 8 Reading Tracker
### 输入
用户阅读行为

### 输出
EpisodeReadingLog.json

ReadingProgress.json  

### 功能
记录：

+ 出现次数
+ 点击次数
+ **出现/点击均以 item_id 记录**：前端可继续使用自己的 lemma/词形逻辑，但提交给后端的 `EpisodeReadingLog.word_logs` 必须包含 `item_id`。ReadingTracker 不再通过 ECDICT + lemma_index 反推学习对象。

---

## Module 9 Mastery Evaluator

> **设计变更 (2026-06-06)**：本模块已从显式 `MASTERED` 判定改为**隐式反馈 → FSRS 复习循环**。不再维护 `appear_count`、`click_count`、`appear_state`、`mastery_score` 等字段，词汇生命周期完全由 FSRS Card 的 `due` / `state` / `stability` / `difficulty` 管理。

### 输入
- `EpisodeReadingLog.json`（含 `word_logs`: `[{item_id, appeared: int, clicked: int}]`）。**注意**：item_id 由前端从 `marks[].item_id` 原样回传，MasteryEvaluator 直接使用。
- `UserVocabulary.json`

### 输出
- 更新后的 `UserVocabulary.json`（仅修改各词汇的 `fsrs_card` 内嵌对象）

### 算法

对 `EpisodeReadingLog` 中每个 `word_log` 执行以下步骤：

#### 1. 隐式消抖窗口 (`history_window`)
- 每个 `VocabularyItem` 维护长度为 5 的 FIFO 队列 `history_window`
- 新值 = `1`（认可）或 `0`（点击查询），依据：`appeared > 0 且 clicked == 0` → `1`，否则 → `0`
- 先将旧窗口追加新值并截取最近 5 位；若窗口仍未满 5 位，则在左侧用 `1` 填充。例：`[0] + 顺畅阅读(1)` → `[1, 1, 1, 0, 1]`

#### 2. 加权评分
```python
weights = [0.1, 0.1, 0.2, 0.2, 0.4]  # 越近权重越高
score = sum(h * w for h, w in zip(history_window, weights))
# 结果: 0.0 <= score <= 1.0
```

#### 3. Rating 映射
```python
from fsrs import Rating

if score >= 0.8:
    rating = Rating.Good
elif score >= 0.5:
    rating = Rating.Hard
else:
    rating = Rating.Again
```

#### 4. FSRS 反序列化

> **⚠️ 修正 (2026-06-07)**：原伪代码使用了不存在的 Card 字段 (`elapsed_days`, `scheduled_days`, `reps`, `lapses`)。
> `fsrs.Card` 构造函数仅有 7 个字段：`card_id`, `state`, `step`, `stability`, `difficulty`, `due`, `last_review`。
> `state` 必须用 `State(int)` 枚举，不能用裸 int。

```python
from fsrs import Scheduler, Card, State

card = Card(
    card_id=fsrs_card["card_id"],                       # 毫秒时间戳
    state=State(fsrs_card["state"]),                    # int → State Enum (必须)
    step=fsrs_card.get("step"),                         # int | None
    stability=fsrs_card["stability"],                   # float | None
    difficulty=fsrs_card["difficulty"],                 # float | None
    due=datetime.fromisoformat(fsrs_card["due"]),       # ISO string → datetime
    last_review=datetime.fromisoformat(fsrs_card["last_review"])
                  if fsrs_card.get("last_review") else None,
)
```

#### 5. FSRS 复习
```python
scheduler = Scheduler()
updated_card, review_log = scheduler.review_card(card, rating)
```

#### 6. 强制跨天
```python
from datetime import datetime, timezone

now = datetime.now(timezone.utc)
today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
if updated_card.due <= today_end:
    # push to tomorrow 00:00 UTC
    updated_card.due = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
```

> **理由**：FSRS 短期复习可能会把 `due` 设得极近（几分钟后），但本应用场景用户每天只读一集，没必要在一天内反复弹出同一词。强制跨天可避免"刚看完立即又出"的体验问题。

#### 7. 序列化回写

> **⚠️ 修正 (2026-06-07)**：原伪代码引用了不存在的 Card 字段。`fsrs.Card` 仅有 7 个字段，回写时只更新实际存在的字段。

```python
# 将更新后的 fsrs.Card 序列化回 Pydantic FsrsCard
fsrs_card["card_id"] = updated_card.card_id
fsrs_card["state"] = updated_card.state.value          # State Enum → int
fsrs_card["step"] = updated_card.step
fsrs_card["stability"] = updated_card.stability
fsrs_card["difficulty"] = updated_card.difficulty
fsrs_card["due"] = updated_card.due.isoformat()        # datetime → ISO string
fsrs_card["last_review"] = datetime.now(timezone.utc).isoformat()
```

### 与旧版的区别

| 旧版 (已作废) | 新版 |
|---|---|
| `appear_count` / `click_count` 手动计数 | `history_window` FIFO 队列 (长度=5) |
| `appear_state` 枚举 | 取消，由 `history_window` + 评分隐式表达 |
| `mastery_score` 自定义公式 | 取消，由 `fsrs.Card.stability` / `difficulty` 替代 |
| `state: MASTERED` 显式阈值 | 取消，词汇生命周期由 FSRS `due` 字段完全管理 |
| 每词独立状态机 | 统一走 `Scheduler().review_card()` |

### 注意事项
- **不调用 LLM**：本模块纯计算，不依赖外部 API
- **不删除词汇**：即使稳定度极高，词汇**永久保留**在 UserVocabulary 中，前端可选择性展示
- **`history_window` 初始值**：新上传词表初始化为 `[1, 1, 1, 1, 1]`。Evaluator 仍兼容旧数据中的短窗口，并会在首次评分前把未满 5 位的窗口用 `1` 填充（视为"认可"），后续逐步被真实数据替换
- **`elapsed_days` 计算**：FSRS 库需要知道距离上一次复习过了几天；`review_card()` 内部会自动根据 `last_review` 和当前时间推算，调用方通常无需手动计算
- **`VocabularyScheduler` 互斥**：Scheduler 只负责"选词出题"，MasteryEvaluator 只负责"收到反馈后更新卡片"——两个模块**只读/只写 fsrs_card 的不同字段**，避免冲突

### item_id 映射回 VocabularyItem
建议在内存中构建一个字典（后端加载时做一次，不用改 JSON 结构）：

```python
# 加载时构建
vocab_index = {item["id"]: item for item in user_vocab["vocabulary"]}

# 使用时直接查
item = vocab_index["awkward_1"]  # O(1)
```

JSON 文件格式不用动，只是后端读取后立刻建立这个索引，之后所有模块（Vocabulary Annotator、Mastery Evaluator）都用字典查，不用遍历数组。  
如果后续词表很大、或者要持久化到数据库，直接把 id 设为主键就行，逻辑完全一样。

---

# 五、最终系统架构图
```latex
                    用户上传词表
                           │
                           ▼
                Vocabulary Preprocessor
                           │
                           ▼
                 UserVocabularyDB

══════════════════════════════════════

                    用户上传小说
                           │
                           ▼
                   Novel Preprocessor
                           │
                           ▼
                       ChapterDB

══════════════════════════════════════

                  用户点击下一集
                       │
                       ▼

                 Episode Cache

                  （直接读取）

                 ══════════════

                      后台

                   Arc Planner
                       │
                       ▼

              Vocabulary Scheduler
                       │
                       ▼

                 Batch Generator
                       │
                       ▼

                Story Rewriter
                       │
                       ▼ 

              Vocabulary Annotator
                       │
                       ▼

               Episode Formatter
                       │
                       ▼

                 Episode Cache
```

# 未来优化方向
异步 Arc 预生成

策略：

当用户阅读到当前 Arc 的 60% 时

自动开始生成下一 Arc

例如：

当前：

Episode 1~10

用户阅读到：

Episode 6

后台自动生成：

Episode 11~20

确保用户永远不会等待生成过程。

# 推荐技术栈

1. FastAPI + Uvicorn
2. pyfsrs
3. instructor
4. 异步任务队列（如 Celery 或 RQ）用于 Arc 预生成
