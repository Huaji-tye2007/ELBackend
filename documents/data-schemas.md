# 数据结构定义
<!-- 所有 JSON 数据结构速查。需要确认字段名 / 类型时引用。 -->

## VocabularyItem（UserVocab 的基本单元）

```json
{
  "id": "issue_problem",
  "word": "issue",
  "meaning": "问题",
  "chapter_first_seen": 3,
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

`last_review == null` → 该词从未展示过 → `is_new: true`（首次出现时）

## ChapterDB 条目

```json
{
  "chapter_id": 1,
  "title": "第一章",
  "raw_text": "...",
  "summary": "李华进入学校并认识老师。",
  "characters": ["李华", "老师"],
  "world_setting": "现代校园，略带悬疑色彩",
  "estimated_reading_time": 15
}
```

## FormatSpec messages 条目（最终前端格式）

```json
{
  "meta": {
    "ep": 3,
    "title": "The Glass",
    "kind": "main"
  },
  "messages": [
    {
      "type": "narration",
      "text": "Footsteps approach. A shadow falls across my table.",
      "marks": [
        {"word": "footstep", "index": 0, "definition": "脚步", "is_new": true}
      ]
    },
    {
      "type": "dialogue",
      "side": "left",
      "name": "Anna",
      "text": "Hey.",
      "marks": []
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
    {"word": "footstep", "definition": "脚步", "is_new": true}
  ]
}
```

## M5 输入 ArcPlan.json

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

## M5 输出（LLM 返回的草稿 marks）

```json
{
  "messages": [
    {
      "type": "narration",
      "text": "Footsteps approach. A shadow falls across my table."
    },
    {
      "type": "dialogue",
      "side": "left",
      "name": "Anna",
      "text": "Hey. I want to introduce my friend."
    },
    {
      "type": "narration",
      "text": "She smiles awkwardly."
    }
  ],
  "draft_marks": [
    {"surface_form": "awkwardly", "lemma": "awkward", "item_id": "awkward_1", "definition": "尴尬地"}
  ],
  "rejected_words": ["introduce_1"]
}
```
