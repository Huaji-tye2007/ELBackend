# 对话体小说 JSON 格式规范 (v3)
App 消费的机器可读格式。

## 顶层结构
```json
{
  "meta": { ... },
  "messages": [ ... ],
  "vocab": [ ... ]
}
```

## meta
| 字段    | 类型   | 说明                                |
| ------- | ------ | ----------------------------------- |
| `ep`    | number | 集数                                |
| `title` | string | 本集标题                            |
| `kind`  | string | `"main"`（主线）或 `"side"`（番外） |


示例：

```json
{
  "ep": 3,
  "title": "The Glass",
  "kind": "main"
}
```

## messages
消息对象数组。每条消息通过 `type` 字段区分类型。

### narration（叙述）
涵盖所有非对话内容：动作、描写、内心活动。渲染为居中、灰字、弱化样式。

```json
{
  "type": "narration",
  "text": "Footsteps approach. A shadow falls across my table.",
  "marks": [
    { "word": "footstep", "index": 0, "definition": "脚步", "is_new": true }
  ]
}
```

### dialogue（对话）
口语对话。`"right"` = 主角侧（右气泡，头像 + 角色名）。`"left"` = 其他角色（左气泡，头像 + 角色名）。

```json
{
  "type": "dialogue",
  "side": "left",
  "name": "Anna",
  "text": "Hey.",
  "marks": []
}
```

| 字段    | 类型   | 说明                           |
| ------- | ------ | ------------------------------ |
| `side`  | string | `"left"` 或 `"right"`          |
| `name`  | string | 角色名                         |
| `text`  | string | 对话内容                       |
| `marks` | array  | 本条消息中的词汇标记（可为空） |


## marks
每条消息都有一个 `marks` 数组。每个 mark 将一个目标词锚定到消息文本中的精确位置。

| 字段         | 类型    | 说明                                          |
| ------------ | ------- | --------------------------------------------- |
| `word`       | string  | 词在 `text` 中的原形                          |
| `index`      | number  | 词在 `text` 中的 0-based 字位置（按空格分词） |
| `definition` | string  | 对应该处语境的中文释义                        |
| `is_new`     | boolean | `true` = 该 (词, 释义) 对在全作品中首次出现   |


### 语义
+ 追踪单位是 **（词, 释义）对**，而非词本身。`bank=河岸` 与 `bank=银行` 是两个独立的学习对象，各自拥有独立的 `is_new` 生命周期。
+ `is_new: true` → 释义紧跟词后以内联方式展示，灰色字体：**bank**（银行）
+ `is_new: false` → 仅加粗，不展示释义。用户可点击查询。
+ 一个词可在同一条消息中出现多次——每次出现各有一个 mark，携带正确的 `index`。
+ 若消息中没有目标词，`marks` 为空数组 `[]`。

### 同词异义 —— 同一消息内
当一个词在同一句话中出现两次且含义不同时，各自拥有独立的 mark：

```json
{
  "type": "narration",
  "text": "The bank said the bank of the river was eroding.",
  "marks": [
    { "word": "bank", "index": 1, "definition": "银行", "is_new": true },
    { "word": "bank", "index": 4, "definition": "河岸", "is_new": true }
  ]
}
```

字索引（0-based）：

```plain
The(0) bank(1) said(2) the(3) bank(4) of(5) the(6) river(7) was(8) eroding.(9)
```

渲染效果：两处均为 `is_new: true`，各自展示内联释义：

> The **bank**（银行） said the **bank**（河岸） of the river was eroding.
>

### 同词同义 —— 多次出现
当同一个（词, 释义）对在后续再次出现时：

```json
// Ep.1 — 首次出现
{ "word": "bank", "index": 3, "definition": "河岸", "is_new": true }

// Ep.3 — 复习出现
{ "word": "bank", "index": 7, "definition": "河岸", "is_new": false }
```

首次：**bank**（河岸）。复习：**bank**（仅加粗，可点击）。

## 词形匹配（词形还原 / Lemmatization）
同一个词可能以不同屈折形式出现在不同集数中：`consume`、`consumed`、`consuming`。这些被视为**同一词汇项**，共享一条学习记录。

+ **方案**：Lemmatization — 将屈折形式还原为词典原形（lemma）
+ **时机**：LLM 生成阶段。生成管线对所有目标词做 lemma 归一化，确保 `consumed` 和 `consuming` 都映射到 `consume`
+ `word`** 字段**：记录**表层形式** — 即消息文本中实际出现的词形。用户看到的、被加粗的即此形式
+ **追踪**：客户端维护 lemma → {表层形式集} 的映射。学习状态（is_new、M 计数）按 **lemma** 维度管理，不按表层形式。当客户端在消息中遇到 `consumed` 时，先查其 lemma `consume`，再确定 is_new 和 M 计数
+ **词典查询**：用户点击表层形式（如 `went`）时，客户端在 ECDICT 中查该词。若词条 `exchange` 字段包含 `0:<lemma>`（如 `0:go`），则以该 lemma 获取完整词典条目（音标、释义等）。若 `exchange` 为空或不存在，则表层形式本身就是原形。全部基于内置 `ecdict_mobile.db`，无需引入外部 lemmatizer 库。

示例 — 同一 lemma，不同表层形式：

```json
// Ep.1 — 首次出现，表层形式 "consuming"
{ "word": "consuming", "index": 3, "definition": "消耗", "is_new": true }

// Ep.4 — 复习出现，表层形式 "consumed"
{ "word": "consumed", "index": 5, "definition": "消耗", "is_new": false }
```

两者均映射到 lemma `consume`。Ep.4 中 `is_new: false` 是因为该 lemma 已出现过。

## vocab
顶层数组，汇总本集中所有不重复的（词, 释义）对。供集末词汇面板使用。可从所有消息的 `marks` 中推导得出——此处提供仅为方便。

```json
{ "word": "bank", "definition": "河岸", "is_new": true }
```

| 字段         | 类型    | 说明                             |
| ------------ | ------- | -------------------------------- |
| `word`       | string  | 目标词                           |
| `definition` | string  | 中文释义                         |
| `is_new`     | boolean | 该（词, 释义）对在本集中是否为新 |


## 完整示例
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
        { "word": "footstep", "index": 0, "definition": "脚步", "is_new": false }
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
      "side": "left",
      "name": "Anna",
      "text": "You're Nukumizu, right? Class C?",
      "marks": []
    },
    {
      "type": "narration",
      "text": "This is the moment my quiet invisible life ends.",
      "marks": [
        { "word": "invisible", "index": 6, "definition": "隐形的", "is_new": true }
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
    { "word": "footstep", "definition": "脚步", "is_new": false },
    { "word": "invisible", "definition": "隐形的", "is_new": true }
  ]
}
```

### 同词异义 —— 跨消息
```json
{
  "meta": { "ep": 5, "title": "The River", "kind": "main" },
  "messages": [
    {
      "type": "narration",
      "text": "I sat down on the bank and watched the water.",
      "marks": [
        { "word": "bank", "index": 5, "definition": "河岸", "is_new": true }
      ]
    },
    {
      "type": "dialogue",
      "side": "right",
      "name": "Kazuhiko",
      "text": "The bank called. They want to talk about my loan.",
      "marks": [
        { "word": "bank", "index": 1, "definition": "银行", "is_new": true }
      ]
    }
  ],
  "vocab": [
    { "word": "bank", "definition": "河岸", "is_new": true },
    { "word": "bank", "definition": "银行", "is_new": true }
  ]
}
```

两处均为 `is_new: true`——不同的义项，不同的学习对象。各自渲染为内联释义。
