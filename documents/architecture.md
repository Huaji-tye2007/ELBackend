# 架构总览
<!-- SoT: 完整流水线 + 模块分工。写服务层 / 路由 / 编排时引用。 -->

## 完整流水线

```
输入: 小说 txt + 用户词表 (UserVocabulary.json)
  │
  ▼
Module 2 · Novel Preprocessor
  小说 txt → ChapterDB.json
  │
  ▼
Module 3 · Arc Planner (其他人)
  ChapterDB → ArcPlan.json
  │
  ▼
Module 4 · Vocabulary Scheduler (其他人)
  ArcPlan + UserVocabulary → 每集 target_words
  │
  ▼
Module 5 · Story Rewriter (我)
  episode (source_text + previous_context + target_words) → messages[] + draft_marks + rejected_words
  │
  ▼
Module 6 · Vocabulary Annotator (我)
  messages + draft_marks + UserVocabulary → 填充好的 messages[] + vocab[]
  │
  ▼
Module 7 · Episode Formatter (其他人)
  → FormatSpec.json → 前端
```

## 模块分工

| 模块 | 维护人 | 输入 | 输出 |
|------|--------|------|------|
| M2 Novel Preprocessor | **我** | 小说 txt | ChapterDB.json |
| M3 Arc Planner | 其他人 | ChapterDB | ArcPlan.json |
| M4 Vocabulary Scheduler | 其他人 | ArcPlan + UserVocabulary | episode target_words |
| M5 Story Rewriter | **我** | ArcPlan episode | messages + draft_marks |
| M6 Vocabulary Annotator | **我** | messages + UserVocabulary + draft_marks | 完整 messages + vocab |
| M7 Episode Formatter | 其他人 | 完整 messages | FormatSpec.json |
