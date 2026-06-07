# AGENTS.md

面向后续 OpenCode 会话的高密度上手手册。仅记录"不写下来就大概率踩坑"的事项。

## 0. 与用户交互

- **统一使用中文回答**。代码注释/标识符照常用英文。

## 1. 仓库定位

- **纯后端仓库**。前端用 Node 单独开发，本仓库只输出标准 FastAPI HTTP API。
- **代码已落地**（截至 2026-06-07）：采用 `app/` 包结构。实际规模：20+ Pydantic 模型、14 个 service 类/包、15 个 API 端点、560 个测试。部分模块仍为骨架（stub），详见 §9 标注。
- **设计真理之源**（动手前必读，按编号优先级）：
  1. `documents/product_analysis.md` — 产品定位、设计原则、核心循环。涉及交互/取舍时按此对齐。
  2. `documents/BACKEND_IN_OUT.md` — 系统架构 V1.5：数据流、9 个模块的输入/输出/职责、JSON 数据结构。**但 §6 FormatSpec 已作废，见下条**。
  3. `documents/format_spec_json.md` — 对话体小说 JSON 格式规范 v3（许家旗版），是前端消费 Episode 输出格式的**唯一 SoT**，完全取代 `documents/BACKEND_IN_OUT.md` §6。
- **设计变更同步约束（强制）**：任何架构/数据结构/模块边界的改动，必须同步更新涉及的 SoT 文档（`documents/BACKEND_IN_OUT.md` / `documents/format_spec_json.md` / `documents/product_analysis.md`）、`AGENTS.md`、以及 `README.md`（若已创建）。文档与代码冲突时以代码为准并立即回写文档。

## 2. 文档中的已知陷阱

- **`documents/BACKEND_IN_OUT.md` §6 `FormatSpec.json` 已作废**。该节红字标注"以许家旗的为准，不要看这个"——许家旗版即根目录的 `documents/format_spec_json.md`。实现 `Episode Formatter` / `Vocabulary Annotator` / 任何前端消费格式相关代码时，**只读 `documents/format_spec_json.md`**，忽略 §6。
- `documents/BACKEND_IN_OUT.md` §4 `Vocabulary Scheduler`：设计已冻结 (2026-06-06)，详见 `documents/BACKEND_IN_OUT.md` §四.4。
- `documents/BACKEND_IN_OUT.md` 与 `documents/format_spec_json.md` 对 lemma / 表层形式描述基本一致，但**以 `documents/format_spec_json.md` §"词形匹配" 为最终口径**（指定了 ECDICT 方案）。

## 3. Python 环境（Windows / PowerShell）

- **Python 3.10**，使用项目内虚拟环境 `.venv`（注意有前导点，用户口述的 `venv` 是笔误）。
- **激活**（每个新 shell 都要做）：

```powershell
.\.venv\Scripts\Activate.ps1
```

- 若 PowerShell 拒绝执行脚本：`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`，再激活。

## 4. 依赖管理规则（强制）

1. 引入任何新 import 之前，**先看 `requirements.txt`**。已存在则直接用。
2. 不在则先 `pip install <pkg>` 到 `.venv`，**完成后立即** `pip freeze > requirements.txt` 并提交。
3. 不要手工编辑 `requirements.txt` 加版本号——总是用 `pip freeze` 生成，避免漂移。
4. 不要切换工具链：本仓库锁定 venv + pip，不用 `conda` / `poetry` / `uv`。

## 5. 锁定的技术栈

| 用途          | 选型                                                      | 现状                                                                |
| ------------- | --------------------------------------------------------- | ------------------------------------------------------------------- |
| Web 框架      | FastAPI + Uvicorn                                         | 已装 (`fastapi 0.136.3`, `uvicorn 0.48.0`)                          |
| 数据模型      | Pydantic v2                                               | 已装 (`pydantic 2.13.4`)                                            |
| FSRS 调度     | **`fsrs`**（PyPI 包名是 `fsrs`，**不是** `pyfsrs`）       | 已装 (`fsrs 6.3.1`)。`import fsrs`，`fsrs.Card(**fsrs_card)`        |
| LLM 编排      | `instructor`                                              | 已装 (`instructor 1.15.1`)，结构化输出绑定 Pydantic                 |
| 异步 Arc 生成 | `asyncio` + JSON checkpoint 状态机                        | 已落地。`ArcGenerationManager`（§14），MVP 阶段不引入外部消息队列   |
| 词形还原      | **`asset/ecdict_mobile.db`**（SQLite，内置）              | **数据库文件目前不在仓库**，需要用户提供；查询路径见 §6             |

不要擅自引入其他 ORM、迁移工具、消息队列。**严禁**引入 `nltk` / `spacy` / `pyinflect` / `lemminflect` 等 lemmatizer——词形还原走 ECDICT。

## 6. 关键命名/概念约定

### 学习对象
- **追踪单位是 `(word, sense)` 对**，不是单词本身。`bank=河岸` 与 `bank=银行` 是两个独立 `VocabularyItem`，各有独立 `item_id`（如 `issue_problem` / `issue_topic`）。多义词通过 `WordSenseDB` 拆分。
- **`is_new` 判定**：`fsrs_card.last_review == null` 且该 `item_id` 在本集尚未出现过。Annotator 需维护集内 `shown_in_this_episode` 集合。
- **FSRS Card**：`fsrs_card` 内嵌对象与 `fsrs` 库的 `Card` 字段一一对应，可 `Card(**fsrs_card)` 还原。

### FormatSpec（消费端输出，以 `documents/format_spec_json.md` 为准）
- 顶层结构：`{ meta, messages, vocab }`。
- `meta.kind`：`"main"`（主线）或 `"side"`（番外）。
- `messages[i].type`：`"narration"` 或 `"dialogue"`。`narration` 涵盖所有非对话（动作 / 描写 / 内心）。
- **`dialogue.side` 语义固定**：`"right"` = 主角侧；`"left"` = 其他角色。**不要颠倒**。
- **`marks.index` 是按空格分词的 0-based 词索引**——例如 `"The bank said"` 中 `"bank"` 的 `index = 1`。**不是字符 offset**。Annotator 实现按 `text.split(" ")` 切分定位。
- **`marks.word` 存表层形式**（屈折形态，如 `"consuming"` / `"consumed"`），不是 lemma。
- **学习状态全部按 lemma 维度管理**（is_new、M 计数、FSRS card），不按表层形式。
- **表层→Lemma→item_id 全链路**：
  1. **StoryRewriter** 产出文本（含表层形式，不做 lemma 标注）
  2. **VocabularyAnnotator** 定位目标词 → ECDICT 查 lemma → (lemma, meaning) 查 item_id → 填 marks.word=表层, marks.is_new=按 item_id 判定
  3. **ReadingTracker** 收到点击事件 → 同样 ECDICT + meaning 映射到 item_id → 记录 behavior
  4. **MasteryEvaluator** 按 item_id 更新 FSRS card（隐式反馈→history_window→Rating→review_card→强制跨天）
  全程 lemma 映射唯一途径：ECDICT（`asset/ecdict_mobile.db`），**禁用**任何外部 lemmatizer。
- `vocab` 数组可由 `messages[].marks` 推导，写出来仅为方便前端。

### 词形还原（ECDICT 方案，强制）
- 唯一数据源：`asset/ecdict_mobile.db`（SQLite，**需用户提供**，目前不在仓库）。
- 流程：遇到表层形式（如 `"went"`）→ 查 ECDICT 词条 → 若 `exchange` 字段含 `0:<lemma>`（如 `0:go`）则取该 lemma → 用 lemma 在 `UserVocabulary` 里查 `item_id`。
- 若 `exchange` 为空或词条不存在，表层形式本身即原形。
- **禁止**调用任何外部 lemmatizer 库。
- 在内存建两个索引（加载时一次性构建）：
  - `vocab_index: item_id → VocabularyItem`（O(1) 查项）
  - `lemma_index: (lemma, meaning) → item_id`（O(1) 复合键 → 学习对象）。对于非多义词 meaning 可省略；对于多义词（如 bank=河岸 / bank=银行），meaning 字段用于从同一 lemma 的多个 item_id 中精确定位。具体实现待 ECDICT 存储格式调研后确定。

## 7. 运行 / 开发命令

所有命令需在激活 `.venv` 后执行（见 §3）。以下均为实测可用命令：

```powershell
# 激活虚拟环境（每次新 shell 都要做）
.\.venv\Scripts\Activate.ps1

# 启动开发服务（带热重载）
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 运行全部单元测试（跳过 integration 目录）
pytest tests/ -v --ignore=tests/integration

# 运行单个测试文件
pytest tests/services/test_arc_planner.py -v

# lint 检查（必须在 git add 之前通过）
ruff check app/ tests/

# 自动格式化
ruff format app/ tests/

# lint + format 一键修复
ruff check --fix app/ tests/ && ruff format app/ tests/

# 收集测试用例数（不执行）
pytest --co
```

**注意事项**：
- `ruff` 必须在 `.venv` 内运行（`requirements.txt` 含 `ruff`，但未全局安装）。
- 测试当前收集约 560 个用例；部分模块仍为骨架（stub），对应测试使用 `pytest.skip` / `pytest.raises(NotImplementedError)` 占位。
- 整个测试套不依赖网络，CI 可在离线环境运行。

## 8. 当一个 agent 接手时的优先级

1. 读 `documents/product_analysis.md` 的"设计原则"和"核心循环"，避免做出违背产品哲学的设计（**例：绝不要加打卡 / 红点 / 排行榜 / 缺席提醒**）。
2. 读 `documents/BACKEND_IN_OUT.md` 模块表（§四）找到要动的模块，确认其输入/输出 JSON 形状。
3. 若动到前端消费格式相关代码，**只读 `documents/format_spec_json.md`**，忽略 `documents/BACKEND_IN_OUT.md` §6。
4. 激活 `.venv` 后再动手；新加依赖立即 `pip freeze > requirements.txt`。
5. 改设计 → 同步更新对应 SoT + 本文件。

## 9. 仓库结构（Repository Structure）

> 以下为项目结构。✅ = 已落地，⏳ = 待实现（骨架/stub），❌ = 未创建。

```
ELBackend/
├── app/                                # ✅ 应用主包
│   ├── __init__.py                     # ✅
│   ├── main.py                         # ✅ FastAPI 实例 + lifespan + 路由挂载
│   ├── core/
│   │   ├── config.py                   # ✅ pydantic-settings：data_dir / ecdict_db_path / openai_*
│   │   ├── dependencies.py             # ✅ FastAPI Depends 工厂（注入 service / storage / llm_client）
│   │   └── exceptions.py               # ✅ 领域异常：NotFoundError/ValidationError/LLMError/GenerationConflictError/ECDictUnavailableError
│   ├── models/                         # ✅ 10 个模型文件，20+ Pydantic v2 数据契约（详见 §12）
│   │   ├── fsrs.py                     # ✅
│   │   ├── vocabulary.py              # ✅
│   │   ├── word_sense.py              # ✅
│   │   ├── chapter.py                 # ✅
│   │   ├── progress.py                # ✅
│   │   ├── episode_log.py             # ✅
│   │   ├── arc_plan.py                # ✅
│   │   ├── episode.py                 # ✅
│   │   └── arc_generation.py          # ✅ ArcGenerationState（§14）
│   ├── api/v1/                         # ✅
│   │   ├── router.py                   # ✅ APIRouter 聚合，前缀 /api/v1
│   │   ├── vocabulary.py              # ✅
│   │   ├── novel.py                   # ✅
│   │   ├── episode.py                 # ✅
│   │   ├── reading.py                 # ✅
│   │   ├── dictionary.py              # ✅
│   │   ├── arc.py                     # ✅
│   │   ├── health.py                  # ✅
│   │   └── schemas.py                  # ✅ 请求 / 响应 schema（与领域模型解耦）
│   ├── services/                       # ✅ 14 个 service 类/包（详见 §11）
│   │   ├── vocabulary_preprocessor.py  # ❌ 未落地（未来任务）
│   │   ├── novel_preprocessor/         # ✅ 子包（T14）：preprocessor.py + chapter_splitter.py
│   │   ├── arc_planner.py              # ✅
│   │   ├── vocabulary_scheduler/       # ✅ 子包：scheduler.py / pools.py / scorer.py / allocator.py
│   │   ├── story_rewriter/             # ✅ 子包（T15）：rewriter.py
│   │   ├── vocabulary_annotator/       # ✅ 子包（T16）：annotator.py
│   │   ├── episode_formatter.py        # ❌ 未落地（未来任务）
│   │   ├── reading_tracker.py          # ⏳ 骨架（stub）
│   │   ├── mastery_evaluator.py        # ✅
│   │   └── arc_generation_manager.py   # ⏳ 骨架（stub），异步编排器（§14）
│   ├── llm/
│   │   ├── client.py                   # ✅ InstructorClient
│   │   └── prompts.py                  # ✅
│   ├── db/
│   │   └── storage.py                  # ✅ JSONStorage[T] 泛型
│   └── utils/
│       ├── lemma.py                    # ✅ lookup_lemma（ECDICT exchange 查询）
│       ├── word_index.py               # ✅ find_word_index（text.split(" ") 0-based）
│       └── atomic_io.py                # ✅ JSON 原子写入：写 .tmp → os.replace
├── tests/                              # ✅ 测试套，目录**严格镜像** app/（~51 个测试文件）
│   ├── conftest.py                     # ✅ 顶层 fixtures（mock_llm / sample_vocab / tmp_data_dir）
│   ├── fixtures/                       # ✅ JSON 测试数据
│   ├── core/ models/ api/v1/ services/ llm/ db/ utils/
│   │   └── test_*.py                   # ✅
│   └── integration/                    # ⏳ 端到端测试目录存在，空
├── scripts/                            # ✅ 开发脚本：build_word_sense_db.py
├── asset/                              # ⏳ 二进制依赖目录存在，ECDICT 数据库待用户提供
│   └── ecdict_mobile.db               # ❌ SQLite，需用户提供，**不入库**
├── documents/                          # ✅ 设计文档（SoT）
│   ├── BACKEND_IN_OUT.md
│   ├── product_analysis.md
│   └── format_spec_json.md
├── data/                               # ✅ 运行时数据（.gitignore，不入库）
│   ├── UserVocabulary.json            # ❌
│   ├── ChapterDB.json                  # ❌
│   ├── EpisodeCache/                   # ❌
│   ├── arc_generation_state.json       # ❌
│   └── WordSenseDB.json               # ✅
├── .venv/                              # ✅ 虚拟环境（不入库）
├── .vscode/
├── AGENTS.md
├── requirements.txt                    # ✅ 依赖列表，强制用 pip freeze 生成
├── pytest.ini                          # ✅ testpaths=tests / pythonpath=. / asyncio_mode=auto
├── pyrightconfig.json                  # ✅ 类型检查配置
├── .env                                # ✅ 本地配置（不入库）
└── .gitignore                          # ✅
```

**目录划分原则**：
- `app/models/` 是**领域模型**，可序列化为 JSON 持久化文件；`app/api/v1/schemas.py` 是 **HTTP 请求/响应 schema**，与领域模型解耦，避免内部字段泄漏到 API。
- `app/services/` 不依赖 HTTP，可被 API 层与 `ArcGenerationManager` 复用。
- `app/services/arc_generation_manager.py` 是**异步编排层**，不在 9 个业务模块之内（详见 §11、§14）。
- `tests/` 目录结构**严格镜像** `app/`：`app/services/episode_formatter.py` → `tests/services/test_episode_formatter.py`。
- `data/` 是运行时数据目录，必须在 `.gitignore`，**不入库**。
- `asset/` 存放二进制依赖（如 ECDICT 数据库），不入库。
- `documents/` 存放设计文档（SoT），是代码真理之源。

## 10. 前后端通信接口（V1.5 草案）

所有端点 prefix `/api/v1`。V1.5 单用户，无鉴权（后续版本再加）。

| Method | Path                           | Request                               | Response                              | 说明                                   |
| ------ | ------------------------------ | ------------------------------------- | ------------------------------------- | -------------------------------------- |
| POST   | `/vocabulary/upload`           | `{user_id, items: [{word, meaning}]}` | `{count: int}`                        | 上传词表，Vocabulary Preprocessor 处理 |
| GET    | `/vocabulary`                  | –                                     | `UserVocabulary`                      | 查询全部词条（含 FSRS 卡）             |
| GET    | `/vocabulary/{item_id}`        | –                                     | `VocabularyItem`                      | 单条查询                               |
| POST   | `/novel/upload`                | `{title, raw_text}`                   | `{chapter_count: int}`                | 上传小说，Novel Preprocessor 切章      |
| GET    | `/novel/chapters`              | –                                     | `[Chapter]`                           | 章节列表                               |
| GET    | `/novel/chapters/{chapter_id}` | –                                     | `Chapter`                             | 单章详情                               |
| GET    | `/episode/{episode_id}`        | –                                     | `Episode`（FormatSpec v3）            | 前端消费的剧集 JSON                    |
| GET    | `/episode/cache/status`        | –                                     | `{cached_count, latest_episode_id}`   | Episode Cache 状态                     |
| GET    | `/progress`                    | –                                     | `ReadingProgress`                     | 当前阅读进度                           |
| POST   | `/reading/log`                 | `EpisodeReadingLog`                   | `{updated: bool}`                     | 上报阅读行为（点击/出现）              |
| POST   | `/reading/finish`              | `{episode_id}`                        | `{vocab_updated_count: int}`          | 完成一集，触发 Mastery Evaluator       |
| GET    | `/dictionary/{word}`           | –                                     | `{word, meaning, examples?: []}`      | 查词（用于 marks 点击展开）            |
| POST   | `/arc/generate`                | `{arc_id?: str}`                      | `{job_id, status: "queued"}` 或 `409` | 手动触发 Arc 生成（详见 §14）          |
| GET    | `/arc/status`                  | –                                     | `ArcGenerationState`（见 §14）        | 前端轮询生成进度                       |
| GET    | `/health`                      | –                                     | `{status: "ok"}`                      | 健康检查                               |

**`GET /api/v1/arc/status` 响应示例**：

```json
{
  "arc_id": "arc_003",
  "phase": "GENERATING",
  "progress": {"current": 4, "total": 10},
  "started_at": "2026-06-06T10:00:00Z",
  "updated_at": "2026-06-06T10:03:07Z",
  "elapsed_seconds": 187,
  "estimated_remaining_seconds": 280,
  "retry_count": 0,
  "last_error": null
}
```

## 11. 模块类映射

### 9 个业务模块（与 `documents/BACKEND_IN_OUT.md` §四一一对应）

| #   | 类                       | 文件                                      | 核心方法                                                                                                                              |
| --- | ------------------------ | ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `VocabularyPreprocessor` | `app/services/vocabulary_preprocessor.py` | `preprocess(raw_items: list[dict]) -> UserVocabulary`                                                                                 |
| 2   | `NovelPreprocessor`      | `app/services/novel_preprocessor/`        | `preprocess(title: str, raw_text: str) -> list[Chapter]`                                                                              |
| 3   | `ArcPlanner`             | `app/services/arc_planner.py`             | `plan_next_arc(progress, chapters, prev_arc) -> ArcPlan`                                                                              |
| 4   | `VocabularyScheduler`    | `app/services/vocabulary_scheduler/`      | `schedule(arc_plan: dict, user_vocab: dict, now: datetime                                                                             | None = None) -> dict` |
| 5   | `StoryRewriter`          | `app/services/story_rewriter/`            | `rewrite_episode(target_words, chapter_slice) -> tuple[list[Message], list[str]]`（Message.text 含表层形式，不做 lemma 标注；marks 由 Annotator 后补）|
| 6   | `VocabularyAnnotator`    | `app/services/vocabulary_annotator/`      | `annotate(messages, target_words, shown_set) -> list[Message]`                                                                        |
| 7   | `EpisodeFormatter`       | `app/services/episode_formatter.py`       | `format_episode(meta, messages, vocab) -> Episode`                                                                                    |
| 8   | `ReadingTracker`         | `app/services/reading_tracker.py`         | `track(episode_log) -> ReadingProgress`                                                                                               |
| 9   | `MasteryEvaluator`       | `app/services/mastery_evaluator.py`       | `evaluate(episode_log: EpisodeReadingLog, user_vocab: dict) -> dict`（隐式反馈→history_window 评分→FSRS review_card，含跨日强制机制） |

### VocabularyScheduler 设计（2026-06-06 冻结）

**文件结构**：`app/services/vocabulary_scheduler/`（4 文件包）
- `scheduler.py`：公开入口 `schedule()`
- `pools.py`：候选池构建（unseen_pool / due_review_pool / pending overlay）
- `scorer.py`：`score_context()` 与 `final_score()`
- `allocator.py`：main / side episode 分配逻辑

**公开函数**：`schedule(arc_plan: dict, user_vocab: dict, now: datetime | None = None) -> dict`

**核心流程**：
1. `now` 为空时使用 `datetime.now(timezone.utc)`。
2. 从 `user_vocab["vocabulary"]` 构建：
   - `unseen_pool`: `fsrs_card.last_review is None`
   - `due_review_pool`: `last_review is not None and due <= now`
3. `pending_words` 只作为优先级 overlay：
   - pending unseen 词排在 unseen_pool 前面
   - pending due 词排在 due_review_pool 前面
4. unseen_pool 排序：pending 优先，其次 `chapter_first_seen` 升序
5. due_review_pool 排序：pending 优先，其次 `fsrs_card.due` 升序
6. 每集从两个池各取 `episode_limit * 3` 作为 LLM 初筛候选。
7. `score_context(source_text, candidates)` 返回 `{item_id: float}`：
   - 分值范围 `0.0 <= score <= 1.0`
   - `source_text is None` 时所有候选返回 `0.5`
   - LLM client 必须依赖注入；单元测试必须 mock，不真实联网
8. `final_score()`：
   - 新词：`0.4 * 0.3 + context_score * 0.7`
   - 复习词：`urgency * 0.5 + context_score * 0.5`
   - `urgency = min(1.0, overdue_days / 30)`
9. main episode：新词上限 10，复习词上限 10，pending 词不强塞
10. side episode：新词上限 10，复习词上限 10，pending 词优先填入
11. 冷启动：review 词不足时用新词补充，候选不足时不报错
12. Arc 内去重：同一 item_id 在同一 Arc 内只能有一次 `is_new=true`

**职责边界**：
- 不调用 ECDICT
- 不生成 story 文本
- 不直接修改 fsrs_card
- 不决定 episode_type（由 ArcPlanner 决定）
- 不维护 MASTERED 状态（词汇生命周期完全由 FSRS due 字段管理）

### 编排层（不在 9 个业务模块内）

| 类                     | 文件                                     | 核心方法                                                                                           | 说明                                        |
| ---------------------- | ---------------------------------------- | -------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| `ArcGenerationManager` | `app/services/arc_generation_manager.py` | `start_generation(arc_id, user_id)` / `get_status() -> ArcGenerationState` / `resume_on_startup()` | 异步状态机，协调 1→7 模块串行执行。详见 §14 |
| `JSONStorage[T]`       | `app/db/storage.py`                      | `load() -> T` / `save(obj: T)` / `append(item)`                                                    | V1.5 JSON 文件持久化                        |
| `InstructorClient`     | `app/llm/client.py`                      | `chat_structured(messages, response_model)`                                                        | instructor + OpenAI 兼容客户端              |

**注入原则**：所有 service 类**不直接** new 依赖。LLM 客户端、storage、settings 通过 `__init__` 注入，方便测试 mock。

## 12. 数据契约（Pydantic 模型规划）

20+ Pydantic v2 模型分布在 10 个文件。命名以 `documents/BACKEND_IN_OUT.md` §三 与 `documents/format_spec_json.md` 为准。

| 文件                           | 模型                                                                           | 关键约束                                                                                                                                                                                                                                                                                |
| ------------------------------ | ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `app/models/fsrs.py`           | `FsrsCard`                                                                     | `card_id: int`（毫秒时间戳）、`state: int` ∈ {1,2,3}、`stability/difficulty: float \| None`、`due: datetime`、`last_review: datetime \| None`                                                                                                                                           |
| `app/models/vocabulary.py`     | `VocabularyItem`、`UserVocabulary`                                             | `id`、`word`（lemma）、`meaning`、`chapter_first_seen: int = Field(ge=1)`、`history_window: list[int]`、`fsrs_card: FsrsCard`                                                                                                                                                           |
| `app/models/word_sense.py`     | `WordSense`、`WordSenseDB`                                                     | `dict[word, {is_polysemous: bool, senses: list[{id, meaning}]}]`                                                                                                                                                                                                                        |
| `app/models/chapter.py`        | `Chapter`、`ChapterDB`                                                         | `chapter_id`、`title`、`raw_text`、`summary`、`characters: list[str]`、`world_setting`、`estimated_reading_time: int`                                                                                                                                                                   |
| `app/models/progress.py`       | `ReadingProgress`                                                              | `current_chapter`、`current_episode`、`chapter_offset: float = Field(ge=0, le=1)`、`total_episodes_read: int = Field(ge=0)`                                                                                                                                                             |
| `app/models/episode_log.py`    | `WordLog`、`EpisodeReadingLog`                                                 | `word_logs: list[{item_id, appeared: int, clicked: int}]`                                                                                                                                                                                                                               |
| `app/models/arc_plan.py`       | `PendingWord`、`EpisodeSlot`、`ArcPlan`                                        | `arc_id`、`pending_words`、`episodes: list[EpisodeSlot]`，`EpisodeSlot.episode_type: Literal["main","side"]`                                                                                                                                                                            |
| `app/models/episode.py`        | `Meta`、`NarrationMessage`、`DialogueMessage`、`Mark`、`VocabEntry`、`Episode` | `Meta.kind: Literal["main","side"]`、`Mark.index: int = Field(ge=0)`（**按空格分词的词索引**）、`Mark.word: str`（**表层形式**）、`DialogueMessage.side: Literal["left","right"]`（**right=主角**）                                                                                     |
| `app/models/arc_generation.py` | `ArcGenerationState`                                                           | `arc_id: str`、`phase: Literal["IDLE","PLANNING","SCHEDULING","GENERATING","ANNOTATING","FORMATTING","COMPLETE","FAILED"]`、`progress: {current: int, total: int}`、`retry_count: int = Field(ge=0)`、`last_error: str \| None`、`started_at: datetime \| None`、`updated_at: datetime` |

**约束强制点**：
- `Mark.index` 必须有 `ge=0` 约束（不能负）
- `DialogueMessage.side` 必须是 `Literal["left","right"]`，禁止字符串 free-form
- `chapter_offset` 必须 `ge=0, le=1`

## 13. 关键工具与编排

### `app/utils/lemma.py` — 词形还原（ECDICT）

```python
def lookup_lemma(surface: str, db: sqlite3.Connection) -> str: ...
```

- 查 `asset/ecdict_mobile.db` 的 `exchange` 字段，找到 `0:<lemma>` 则返回 lemma
- 若 db 不存在 → 抛 `ECDictUnavailableError`，由路由层翻译为 HTTP 503
- 若 word 不在词典或无 `0:` 标记 → 返回 surface 本身
- **禁止**调用任何外部 lemmatizer（NLTK / spaCy / pyinflect / lemminflect）

### `app/utils/word_index.py` — 词索引定位

```python
def find_word_index(text: str, surface: str, occurrence: int = 0) -> int: ...
```

- 按 `text.split(" ")` 切分（**不是字符 offset**）
- 0-based 返回词索引
- `occurrence` 处理同 surface 多次出现（默认第 0 次）

### `app/db/storage.py` — JSON 泛型存储

```python
class JSONStorage(Generic[T]):
    def __init__(self, path: Path, model: type[T]): ...
    async def load(self) -> T: ...
    async def save(self, obj: T) -> None: ...
```

- 加载：读 JSON → `model.model_validate(...)`
- 保存：`model.model_dump_json()` → 走 `atomic_write_json`

### `app/llm/client.py` — Instructor 客户端

```python
class InstructorClient:
    def __init__(self, base_url: str, api_key: str, model: str): ...
    async def chat_structured(self, messages: list[dict], response_model: type[T]) -> T: ...
```

- 用 `instructor` 包结构化输出绑定 Pydantic
- 超时：`httpx.AsyncClient(timeout=300)`
- 不做重试（重试在 `ArcGenerationManager` 层做）

### `app/utils/atomic_io.py` — JSON 原子写入

```python
async def atomic_write_json(path: Path, model: BaseModel) -> None: ...
```

- 写临时文件 `path.with_suffix(".tmp")` → `aiofiles.write` → `os.replace(tmp, path)`
- 保证并发安全：避免半写文件（进程崩溃在 fsync 之前）
- **所有 JSON 持久化**（UserVocabulary、ArcGenerationState、Episode Cache）必须走此函数，**禁止**直接 `f.write(json.dumps(...))`

## 14. 异步任务架构（ArcGenerationManager）

> 状态机骨架已落地（`app/services/arc_generation_manager.py`），阶段逻辑待补充。

### 14.1 设计原则
- **MVP 阶段不引入外部消息队列**（不装 Celery / arq / RQ / Taskiq / Redis）
- 进程内 `asyncio` + JSON checkpoint 状态机
- 当 Redis 成为基础设施后再迁移到 **Taskiq**，**接口边界不变**

### 14.2 触发方式

| 方式     | 触发点                              | 调用                                                                                                                   |
| -------- | ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| 自动     | 用户阅读进度达到当前 Arc 的 **60%** | `ReadingTracker` 调用 `ArcGenerationManager.start_generation(next_arc_id)`                                             |
| 手动     | `POST /api/v1/arc/generate`         | API 路由调用 `start_generation(arc_id)`                                                                                |
| 启动恢复 | 服务启动 lifespan 钩子              | `ArcGenerationManager.resume_on_startup()` 读 `data/arc_generation_state.json`；若 phase ∉ {`IDLE`, `COMPLETE`} 则续跑 |

### 14.3 状态机

```
IDLE
  → PLANNING            # 调用 ArcPlanner.plan_next_arc
  → SCHEDULING          # 调用 VocabularyScheduler.schedule
  → GENERATING(1/10)    # 调用 StoryRewriter.rewrite_episode
  → GENERATING(2/10)
  → ...
  → GENERATING(10/10)
  → ANNOTATING          # 调用 VocabularyAnnotator.annotate（对全部 10 集）
  → FORMATTING          # 调用 EpisodeFormatter.format_episode（对全部 10 集）
  → COMPLETE

任意步骤异常 → FAILED → 重试（指数退避，最多 3 次：10s → 30s → 90s）→ 仍失败则停留 FAILED 等待手动 generate
```

每步成功后立即写 checkpoint 到 `data/arc_generation_state.json`（走 `atomic_write_json`）。

### 14.4 API 端点

| Method | Path                   | Request          | Response                     | 说明                                                              |
| ------ | ---------------------- | ---------------- | ---------------------------- | ----------------------------------------------------------------- |
| POST   | `/api/v1/arc/generate` | `{arc_id?: str}` | `{job_id, status: "queued"}` | 手动触发；若已有任务运行中 → `GenerationConflictError` → HTTP 409 |
| GET    | `/api/v1/arc/status`   | –                | `ArcGenerationState`         | 前端轮询；POST 后通常每 5–10 秒拉一次                             |

### 14.5 并发约束
- 同一时刻只允许一个 Arc 在生成中（V1.5 单用户假设）
- `ArcGenerationManager` 是**进程内单例**，通过 FastAPI `Depends` 注入
- 内部用 `asyncio.Lock` 保护状态转换，确保 `start_generation` 不会被并发触发

### 14.6 失败处理

| 失败类型                             | 处理                                                                         |
| ------------------------------------ | ---------------------------------------------------------------------------- |
| LLM API 单次超时（>300s）            | `httpx.AsyncClient(timeout=300)` 触发异常 → 进入重试                         |
| LLM 调用业务失败（5xx / rate limit） | 捕获后进入重试                                                               |
| 重试策略                             | `max_retries=3`，指数退避：10s → 30s → 90s                                   |
| 3 次全部失败                         | phase 停留 `FAILED`，`last_error` 写入异常 message，等待人工或下一次自动触发 |
| 服务进程崩溃                         | 下次启动 `resume_on_startup()` 从最后一个 checkpoint 续跑                    |

### 14.7 监控
- 监控接口即 `GET /api/v1/arc/status`
- 前端可在阅读界面底部显示一条细线："下一段故事生成中…"（符合 `documents/product_analysis.md` 设计原则 #1，不打扰用户）
- 不引入 Prometheus / 监控 dashboard（V1.5 单机不需要）

### 14.8 迁移到 Taskiq 的接口边界

未来引入 Taskiq + Redis 时，**只替换 `ArcGenerationManager` 内部实现**：

| 当前实现（MVP）                                   | 迁移后（Taskiq）                                 |
| ------------------------------------------------- | ------------------------------------------------ |
| `asyncio.create_task(self._run_pipeline(arc_id))` | `await pipeline_task.kiq(arc_id=arc_id)`         |
| 读写 `data/arc_generation_state.json`             | 读写 Redis-backed `TaskiqResult`                 |
| `asyncio.Lock`                                    | 用 Redis 分布式锁 / Taskiq idempotent middleware |
| 单进程内执行                                      | 独立 Worker 进程消费                             |

**公共接口保持不变**：
- `ArcGenerationManager.start_generation(arc_id)` 签名不变
- `ArcGenerationManager.get_status()` 签名不变
- HTTP 端点不变
- 外部调用方（`ReadingTracker`、API 路由）零修改

**预估迁移工作量**：2–4 小时。

## 15. 编码规范（Coding Standards）

> 所有规则强制执行。违反 = 必须修复才能 commit。

### 15.1 Python 风格

- **写完任意 .py 文件后立即跑**：
  ```powershell
  ruff format <file>
  ruff check --fix <file>
  ```
  在 `git add` 之前必须保证 `ruff check` 退出码为 0。
- **生产代码禁用 `assert`**：会被 `python -O` 移除，且不应作为业务校验。需校验时抛专门异常。
- **测时长用 `time.monotonic()`，不用 `time.time()`**（避免系统时间漂移导致负数）。
- **import 放文件顶部**。允许的例外：
  - 解决循环 import 的延迟 import（必须加注释说明）
  - `if TYPE_CHECKING:` 块内的类型 import（重依赖如 `sqlite3` 之外的库）
  - 仅在某函数内用的可选重依赖（必须在函数 docstring 注明）
- **类型注解强制**：所有函数签名必须有 type hints。Python 3.10+ 语法：
  - `X | None` 而非 `Optional[X]`
  - `list[int]` / `dict[str, int]` 而非 `List[int]` / `Dict[str, int]`
- **行长度 120**（ruff `line-length = 120`）。

### 15.2 异常处理

- **不要直接 `raise Exception` / `RuntimeError`**。每种错误用专门异常类：
  - 在 `app/core/exceptions.py` 定义：`NotFoundError`、`ValidationError`、`LLMError`、`GenerationConflictError`、`ECDictUnavailableError`
  - 简单 invalid input / not found 可直接用 stdlib `ValueError` / `KeyError`
- **领域异常 → HTTPException 在路由边界翻译**：
  - Service 层抛 `NotFoundError` / `ValidationError` 等领域异常
  - `app/api/v1/*.py` 路由处理器捕获并翻译：

    | 领域异常                         | HTTP 状态码 |
    | -------------------------------- | ----------- |
    | `NotFoundError` / `KeyError`     | 404         |
    | `ValidationError` / `ValueError` | 400         |
    | `GenerationConflictError`        | 409         |
    | `LLMError`                       | 502         |
    | `ECDictUnavailableError`         | 503         |

  - 不翻译会变成 500 Internal Server Error，**泄漏内部细节并误导前端**。

### 15.3 FastAPI / 异步约束

- **service 类不直接调 LLM / 文件 IO**：通过 `__init__` 注入依赖（`llm_client`、`storage`、`settings`），方便 mock。
- **service body 在骨架阶段抛 `NotImplementedError("TODO: 见 documents/BACKEND_IN_OUT.md §四.<N>")`**，方便测试用 `pytest.raises` 包裹占位。
- **FastAPI 路由的依赖通过 `Depends` 注入**（依赖工厂在 `app/core/dependencies.py`）。
- **JSON 持久化必须用 `app/utils/atomic_io.atomic_write_json`**，禁止直接 `f.write(json.dumps(...))`。

### 15.4 命名

- **函数 / 方法名用动词开头**：`get_`、`extract_`、`find_`、`compute_`、`build_`、`load_`、`save_`、`annotate_`、`evaluate_`、`schedule_`、`plan_`、`rewrite_`、`format_`、`track_`。
- **避免名词形式**：`_serialize_keys` 不用 → 用 `serialize_keys` — 名词形式读起来像属性，不像可调用。
- **谓词例外**：`is_*` / `has_*` / `should_*` / `can_*` 允许（返回 bool）。
- **类名用名词**：`ArcGenerationManager`、`InstructorClient`、`JSONStorage`。

### 15.5 禁用清单（违反 = 拒收）

- **不引入 ORM**（SQLAlchemy / SQLModel / Tortoise）—— V1.5 用 JSON 文件持久化
- **不引入消息队列依赖**（Celery / arq / RQ / Taskiq / Redis）—— MVP 阶段（详见 §14）
- **不引入 lemmatizer 库**（NLTK / spaCy / pyinflect / lemminflect）—— 词形还原走 ECDICT（详见 §6）
- **不引入 `requests`**—— 用 `httpx`（async 一致）
- **不引入 `conda` / `poetry` / `uv`**—— 锁定 venv + pip（详见 §4）
- **不手工编辑 `requirements.txt` 加版本号**—— 总是 `pip freeze`（详见 §4）

### 15.6 文件约束

- 每个 Python 文件顶部一行 module docstring，简述用途
- 公共 API（类的 public method、模块的 public function）必须有 docstring，含 Args / Returns / Raises
- 私有方法 `_` 开头不强制 docstring，但复杂逻辑需要内联注释
- 中文注释允许；docstring 优先英文（与 type hints / 库习惯一致）

## 16. 测试规范（Testing Standards）

### 16.1 测试框架

- **使用 pytest**，不要用 `unittest.TestCase`
- **测试文件位置严格镜像 source**：`app/services/episode_formatter.py` → `tests/services/test_episode_formatter.py`
- **fixtures 分层**：`tests/conftest.py` 提供顶层组合 fixture（如 `mock_llm`、`sample_vocab`、`tmp_data_dir`），`tests/<module>/conftest.py` 提供局部 fixture

### 16.2 覆盖度

- **每个新行为加测试**，至少覆盖 success / failure / edge 三种场景
- 骨架阶段（service body 仅抛 `NotImplementedError`）：每个公开方法至少 1 个 `pytest.raises(NotImplementedError)` 占位测试
- 实现完成后：补充 happy path / 边界 / 异常分支
- 不写 `assert True` 占位（用 `pytest.skip("reason")` 或 `pytest.xfail("reason")`）

### 16.3 Mock

- **mock 用 `spec` / `autospec`**：
  ```python
  mock_client = mock.create_autospec(InstructorClient)
  ```
  防止 mock 接口与真实接口漂移。
- **优先 `@mock.patch` 装饰器**，参数化里值变化时再用 `with mock.patch(...)` 上下文管理器
- **LLM 调用必须 mock**（用 `mock_llm` fixture），**严禁**测试中真实联网
- 文件 IO 用 `tmp_path` 或 `tmp_data_dir` fixture，**严禁**写到真实 `data/` 目录

### 16.4 时间相关

- **时间依赖测试用 `time_machine`**（推荐）或 `freezegun`，不用 `datetime.now()` 硬编码
- 涉及 `time.monotonic` 的测试通过依赖注入传入 `clock` 函数，便于替换

### 16.5 参数化

- **多输入相似测试用 `@pytest.mark.parametrize`**，不要复制粘贴
- 关键约束（`marks.index` / `marks.word` / `dialogue.side`）必须用 parametrize 覆盖多场景

### 16.6 关键约束的显式断言（强制）

- **`marks.index` 测试**：必须断言 `text.split(" ")[mark.index] == mark.word` —— 验证按空格分词的词索引语义
- **`marks.word` 测试**：必须至少一个表层形式案例（如 `"consuming"` 而非 lemma `"consume"`）
- **`dialogue.side` 测试**：必须断言 `side="right"` 对应主角，`side="left"` 对应其他角色

### 16.7 Pydantic 模型测试

- 20+ 个模型每个至少 3 个测试：`valid_minimal`、`valid_full`、`invalid` (`pytest.raises(ValidationError)`)
- 用 `documents/format_spec_json.md` 的完整 Episode 示例做一次 `Episode.model_validate(...)` 必须通过
- 用真实 `fsrs.Card(**fsrs_card_dict)` 还原一次，验证字段一一对应

### 16.8 异步与 API 测试

- async 测试不需要 `@pytest.mark.asyncio` 装饰器（`pytest.ini` 已设 `asyncio_mode = auto`）
- FastAPI 路由测试用 `httpx.AsyncClient(app=app)` 直接 ASGI 调用，不起 `uvicorn`
- 整个测试套**不依赖网络**，CI 可在离线环境运行

### 16.9 ArcGenerationManager 测试

- 状态机的**每个 transition 都要测试**（IDLE→PLANNING, PLANNING→SCHEDULING, ..., 各种 →FAILED 路径）
- mock 全部 9 个 service 类，单独验证编排逻辑
- 重启恢复：构造 phase 在 `GENERATING(4/10)` 的 checkpoint 文件，验证 `resume_on_startup()` 从第 5 集继续
- 重试退避：用 `time_machine` 验证 10s/30s/90s 间隔

### 16.10 不要这样做

- **不用 `caplog`** 验证日志输出（耦合实现，应验证行为）
- 不在测试里真实发起 LLM / HTTP 网络调用
- 不写依赖随机种子但不固定的测试（`random.seed(0)` / `np.random.seed(0)`）
- 不在测试间共享可变状态（每个 fixture 应能独立运行）

## 17. Git 工作流（Git Workflow）

> 仓库**已是 git repo**（含 `.git` 目录）。以下为统一规范。

### 17.1 仓库初始化（待办）

首次启动 git 时按以下顺序：

1. `git init`
2. 创建 `.gitignore`，至少包含：
   ```
   .venv/
   __pycache__/
   *.pyc
   .pytest_cache/
   .ruff_cache/
   data/
   .env
   asset/ecdict_mobile.db
   ```
3. 首次 commit：`chore: initial commit (docs + AGENTS.md + requirements.txt)`

### 17.2 Commit 规范（Conventional Commits）

**每个 task 完成且通过验证后，必须做一次原子 commit**。

格式：

```
<type>(<scope>): <subject in English>

[optional body in 中文]

[optional footer: refs / breaking change]
```

- **type**（强制）：`feat` / `fix` / `docs` / `test` / `refactor` / `chore` / `perf` / `style`
- **scope**（推荐）：`models` / `services` / `api` / `arc` / `llm` / `utils` / `db` / `tests` / `docs` / `deps`
- **subject**：祈使句，英文，首字母小写，**不加句号**，**≤ 72 字符**

**示例**：

```text
feat(arc): add ArcGenerationManager state machine

实现 IDLE→PLANNING→...→COMPLETE 状态机，含 JSON checkpoint
和 max_retries=3 指数退避。public API 与未来 Taskiq 迁移兼容。
```

```text
fix(annotator): correct marks.index off-by-one in find_word_index
test(models): cover Pydantic validation for 20+ models
docs(agents): add §14 async architecture
chore(deps): add pytest + instructor to requirements.txt
```

### 17.3 Atom 粒度

- 一个 task 完成后**立即** commit，不要攒一坨
- 单一目的：一个 commit 只做一件事
- 通过验证（`ruff check` 退出 0 + `pytest` 通过 + `lsp_diagnostics` 无 error）才能 commit
- 大 task 可拆多次 commit，每个 logical chunk 一次

### 17.4 禁用

- 不强制推送（`git push -f`）到共享分支
- 不在 commit message 加 emoji
- 不用 `git commit --amend` 覆盖已发布 commit
- 不跳过 pre-commit hook（一旦加了 hook）
- 不写 "WIP" / "fix typo" / "asdf" 这类无意义 message
- 不在一个 commit 里混杂代码改动和无关的格式化

### 17.5 当前状态备忘

- 仓库已初始化为 git repo，含 `.git` 目录和 `.gitignore`
- 已有 AGENTS.md / requirements.txt / 三份设计文档作为初始 commit
- 每个 Sisyphus task 完成时按 §17.2 格式提交一次
