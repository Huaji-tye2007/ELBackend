# Module 6 · Vocabulary Annotator
<!-- 输入：messages[] + UserVocabulary + draft_marks → 输出：填充 marks[] 的 messages + vocab[]。实现 M6 时引用。 -->

**输入**：`messages[]` + `UserVocabulary.json` + `draft_marks`（来自 Story Rewriter）  
**输出**：填充好 `marks[]` 的 messages + `vocab[]`

## 实现要点

### is_new 判断逻辑（严格按此实现）

```python
shown_in_this_episode = set()  # 存 item_id

for each word occurrence:
    if fsrs_card.last_review == null and item_id not in shown_in_this_episode:
        is_new = True
        shown_in_this_episode.add(item_id)
    else:
        is_new = False
```

### index 计算（Module 6 自己算，不信任 LLM）

```python
def find_word_indices(text: str, surface_form: str) -> list[int]:
    tokens = text.split()
    return [
        i for i, tok in enumerate(tokens)
        if tok.strip(".,!?;:\"'").lower() == surface_form.lower()
    ]
```

同一词在同一条 message 中出现多次 → 生成多条 mark，is_new 仅首次为 true。

### 加载时建立两个索引（模块启动时做一次）

```python
vocab_index = {item["id"]: item for item in user_vocab["vocabulary"]}  # item_id → VocabularyItem
lemma_index = defaultdict(list)                                          # lemma → [item_id, ...]
for item in user_vocab["vocabulary"]:
    lemma_index[item["word"]].append(item["id"])
```

注意：`lemma_index` 用 `defaultdict(list)`，因为同一 lemma 可能对应多个义项（多义词）。

### marks 字段语义（严格对齐前端规范）

- `word`：表层形式（如 "consumed"，不是 lemma）
- `index`：0-based，按空格分词的词位置
- `definition`：来自 VocabularyItem.meaning
- `is_new`：见上方判断逻辑
