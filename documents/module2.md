# Module 2 · Novel Preprocessor
<!-- 输入：小说 txt → 输出：ChapterDB.json。实现 M2 时引用。 -->

**输入**：小说 txt  
**输出**：`ChapterDB.json`

## 实现要点

- 切章节优先用正则（匹配"第X章"/"Chapter N"/全大写标题），匹配失败：
  1. 调 LLM 按 `start_char_index` 定位章节边界
  2. LLM 调用失败 → 按 1500 字硬切（defensive fallback）
- 第二阶段（对已切好的每章）调 LLM 提取元数据：characters + summary（100字内）+ world_setting（30字内），返回 JSON
- `estimated_reading_time` = len(raw_text) // 300（粗估，无需 LLM）

### LLM 章节切分协议

```
system: 给定全文，识别每章起始位置，返回 [{title, start_char_index}, ...]
        第一条 start_char_index = 0，覆盖全文。无章节标记时返回 [{"title": "Chapter 1", "start_char_index": 0}]
user:   Identify chapter boundaries in this novel text:\n\n{truncated_text}
```
- `truncated_text` 上限 80k 字符
- LLM 返回空 `[]` 视为单章
- `response_format=list`

## ChapterDB 条目结构

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
