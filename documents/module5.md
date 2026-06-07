# Module 5 · Story Rewriter
<!-- 输入：ArcPlan.json → 输出：每集的 messages[] + draft_marks + rejected_words。实现 M5 时引用。 -->

**输入**：`ArcPlan.json`（包含所有 episode，每集含 source_text + previous_context + candidate_words）  
**输出**：每集一个结构体：`messages[]` + `draft_marks[]` + `rejected_words[]`

## 实现要点

- 遍历 ArcPlan.json 中所有 episode，逐集调用 LLM，每集一次调用
- messages[] 中每条消息**只有 type/text（narration）或 type/side/name/text（dialogue）**，不含 marks——marks 由 Module 6 填充
- draft_marks 只给出 `{surface_form, lemma, item_id, definition}`，**不需要 index**（index 由 Module 6 补算，LLM 给的 index 不可靠）
- rejected_words：LLM 声明哪些 candidate_words 无法自然嵌入剧情，返回其 item_id 列表

## Prompt 设计（参考，可以改为更合理形式）
当前剧情片段：[source_text]
上文语境：[previous_context]
以下是候选词汇池，请：

选出能自然融入本段剧情的词（建议 10-15 个）
用选中的词改写剧情为英文轻小说对话体
输出未选中的词列表（供番外集处理）

候选词：[candidate_words as JSON]

## LLM 返回格式

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

## 注意事项

- LLM 调用加 retry（至少一次），parse 失败要 catch 并记录原始返回
- messages 里 narration 无 side/name 字段，dialogue 必须有 side 和 name