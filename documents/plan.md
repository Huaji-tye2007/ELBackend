# 实施计划

## 基础设施（utils/）

- [x] `utils/__init__.py`
- [x] `utils/io.py` — read_json / write_json
- [x] `utils/llm_client.py` — LLMClient（OpenAI SDK + DeepSeek）

## Module 2 · Novel Preprocessor

- [x] `Novel Preprocessor/__init__.py`
- [x] `Novel Preprocessor/chapter_splitter.py` — 正则切章节（"第X章"/"Chapter N"/ALL CAPS），fallback 1500 字硬切
- [x] `novel_preprocessor/preprocessor.py` — LLM 提取 characters + summary + world_setting + 拼装 ChapterDB
- [x] `tests/test_module2.py` — 覆盖 split + metadata + E2E

## Module 5 · Story Rewriter

- [ ] 构建三层 prompt（system → 人物设定 + previous_context → source_text + target_words）
- [ ] LLM 调用 + parse 返回 messages / draft_marks / rejected_words
- [ ] retry + parse fallback 处理

## Module 6 · Vocabulary Annotator

- [ ] 加载时建立 vocab_index + lemma_index
- [ ] 计算 index（自算，不信任 LLM）
- [ ] is_new 判断（严格按 last_review + shown_in_this_episode）
- [ ] 生成 marks[] + vocab[]
- [ ] 注入 marks 到 messages 输出
