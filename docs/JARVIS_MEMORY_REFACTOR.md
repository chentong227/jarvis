# JARVIS 记忆系统重构方案

> 起源: **Sir 21:07 真测反馈** "Windsurf 自动编程不是我在动" + 21:13 提议 "记忆能力能通用到各个模块".
>
> 我最初提议加 L10 `cognitive_calibrations` 账本, **Sir 否定**:
> > "你的方案我觉得有点冗杂, 听起来像我告诉他三件事, 我额外告诉他有一件事不对, 这不是在原来的三件事上改, 而是变成了第四件事, 这会极大地提高 prompt 的字数吧?"
>
> Sir 判断对. 本 doc 探讨**重构而非新增**.

---

## 1. 现状审计 — 已有 9+ 层记忆体

| 层 | 文件 | 内容 | inject prompt 方式 |
|---|---|---|---|
| L0 STM | conversation_history (内存) | 最近 N 条对话 | 每轮全量 |
| L1 SWM | `ConversationEventBus` | sensor publish 的 events | 每轮 top-K relevance |
| L2 Profile | `profile.json` + ProfileCard | Sir 静态属性 | 每轮摘要 |
| L3 Hippocampus (LTM) | `hippocampus.db` (sqlite) | 长期 memory entries | 每轮 vector retrieve |
| L4 Concerns | `concerns.json` | "我关心的事" (sleep/exam/cursor) | SOUL inject |
| L5 Relational | `relational_state.json` | inside jokes / unspoken protocols | SOUL inject |
| L6 Commitments | (in-memory + sqlite) | Sir 让我盯的事 | CommitmentWatcher 用 |
| L7 Promise log | `jarvis_promise_log.json` | Jarvis 自承诺 | (主要不 inject, 后台) |
| L8 Profile corrections | `profile_corrections.jsonl` | Sir 纠正过的字段 | 几乎没人读 (死代码?) |
| L9 STM ratings | `stm_ratings.json` | Sir 对 reply 评分 | 不 inject, archive |
| L9.5 Vocab 多个 | `*_vocab.json` (~10 个) | trigger 词典 | 各 trigger 函数读 |

**Sir 痛点核心**: prompt 已经很臃肿, 加 L10 calibrations 让情况更糟.

## 2. 重叠问题 (削减空间)

| 重叠对 | 原因 | 合并方向 |
|---|---|---|
| Promise log + Commitments | 都是"承诺", 一个 Jarvis 自承诺 + 一个 Sir 让 Jarvis 盯, **schema 几乎一样** | → `accountabilities.jsonl` 一处, `author='sir'/'jarvis'` 区分 |
| Profile + Profile corrections | corrections 应该直接覆写 profile, 不分两份 | → 取消 corrections.jsonl, 直接 mutate profile |
| Concerns + Relational protocols | 都是"长期跟 Sir 之间的事" | → 共享 schema, kind='concern'/'protocol' |
| Hippocampus + STM | LTM = STM 老化下沉, 应该是同一系统两个 view | → 已经是 (但接口 API 分裂) |

**潜在减层 4 个** (L6+L7 → 1 个; L8 → 删; L4+L5 → 共享 schema; L0+L3 → 统一接口).

## 3. Prompt 装配臃肿真因

每轮 prompt 装配 (估算字符):

```
STM (5-10 turns)            : ~2000 char
Profile card                : ~500
Concerns (active)           : ~1000  (3-5 条 active, 每条 ~200)
Relational                  : ~500   (jokes + protocols)
SWM events (recent)         : ~500
Hippocampus retrieved       : ~1500  (top-K vectors)
SOUL multi-layer inject     : ~1500
Directives (5-10 fired)     : ~3000  (每条 ~300-600)
[META] / Stand Down / etc.  : ~500
─────────────────────────────────────
Total                       : ~11000 char
```

**直接问题**:
1. 全量注入而非 relevance retrieval
2. directive 文本过长 (每条 200-600 char × 7-10 条)
3. 重叠记忆双注 (e.g. concern + soul + STM 都说 "Sir 体检" 三遍)

## 4. Sir 教正 → 应该修对应已有记忆

不开新账本, 让主脑听 Sir 教正 → emit FAST_CALL 修**已有**记忆.

| Sir 教正 | 应该修的记忆 | FAST_CALL organ |
|---|---|---|
| "X 别再提" | concerns.json (severity ↓ + triggers_proactive=False) | ✅ `concerns.dismiss` (fix24) |
| "X 做完了" | promise_log.json (state=fulfilled) | ✅ `promises.fulfill` (fix27) |
| "X 不去了" | promise_log.json (state=cancelled) | ✅ `promises.cancel` (fix27) |
| "我要安静" | stand_down_state.json (active) | ✅ `stand_down.set` (fix25) |
| "记错了, 应该 X" | hippocampus modify_record + profile update | ✅ memory_hands.modify_record (旧设计) |
| **"Windsurf 不是我在动"** | hippocampus annotation **新设计** | ❌ **缺**: `hippocampus.annotate` |

**只缺一个 organ**: `hippocampus.annotate` — 给已有 memory 加 tag/置信度/uncertainty marker.

## 5. 推荐重构方向 (3 步骤)

### Step A. 加 `hippocampus.annotate` organ (最小, 解今晚 Windsurf 问题)

不开新账本, 让主脑给已有 memory 加 annotation:

```json
<FAST_CALL>{"organ":"hippocampus","command":"annotate","params":{
  "memory_id_or_keyword":"Windsurf focus",
  "annotation":"focus duration ≠ Sir 在动 — Sir 报告过 auto-coding mode",
  "tags":["uncertainty_marker","auto_process_aware"],
  "confidence_adjust":-0.3
}}</FAST_CALL>
```

**效果**: ProactiveCare/ScreenVision retrieve 这条 memory 时, annotation 自带, 主脑自然看到 reframe.
**优势**: 不加新层, 用已有 hippocampus.

### Step B. 合并重叠记忆 (减层)

- Promise log + Commitments → `accountabilities.jsonl` (1 处, author 区分)
- 删 `profile_corrections.jsonl` 死代码 (改 profile.json 直接覆写)
- Concerns + Relational protocols 共享 schema (kind 字段区分)

**预期减层 3-4 个**, prompt 装配维护简化.

### Step C. Prompt 装配改 relevance retrieval

- 不再每轮全量注入. 用本轮 user_input embedding → top-K relevance retrieve
- 例: Sir 问"今天天气" → 不 inject 体检 promise / windsurf annotation
- Sir 问"你在监控啥" → 才 inject concerns 全量
- 预期 prompt 字数 11000 → 6000 (-45%)

### Step D. directive 文本瘦身 (准则 6 升级)

- 每条 directive 当前 200-600 char (含 examples, anti-pattern, hard rules)
- 重构: 核心 ≤ 80 char + few-shot examples 集中外置 (fast_call_examples.json)
- 主脑只看核心 + 关键词查 examples (类似 RAG)
- 预期单 directive 字数 −60%, 总 prompt −2000 char

## 6. 不推荐做的 (避免叠加)

❌ 加 L10 `cognitive_calibrations.jsonl` — 叠加新账本, prompt 更臃肿
❌ 给每个 sensor 加 "已知教正" 列表 — 分散维护, 不 neat
❌ 主脑每轮多读一个 module — 字数膨胀

## 7. 落地路径建议

| Phase | 范围 | 工作量 | 优先级 |
|---|---|---|---|
| **Step A**: hippocampus.annotate organ + directive | ~200 行, 解 Windsurf 痛点 | 小 | **高** (Sir 真痛点) |
| **Step B**: Promise+Commitment 合并 | ~400 行重构 + 测 | 中 | 中 (不紧, 但减运维) |
| **Step C**: prompt 装配 retrieval | ~600 行 + benchmark | 大 | 高 (Sir 想瘦身) |
| **Step D**: directive 瘦身 | ~500 行 + RAG examples | 中 | 中 |

**建议顺序**: A → C → D → B (A 解痛点, C 直接减字, D 顺势, B 长期重构).

## 8. 当前不动的 (审计完整 后续 Sir 决定)

- `behavior_inference_vocab.json` — 在用 (struggle/sleep/cursor 都用) ✓
- `commitment_conditional_vocab.json` — 在用 ✓
- 所有 `*_vocab.json` — 都是 trigger 词典, 不算记忆体, 不动

## 9. Open questions (Sir 决策项)

1. **L8 `profile_corrections.jsonl` 删不删?** 真没人读, 大概率死代码.
2. **Promise log + Commitments 真合并?** 有几个 testcase 依赖区分.
3. **prompt retrieval 用啥 embedding?** Gemini text-embedding 还是 local?
4. **directive 瘦身后 LLM 真的还能学会复杂指令吗?** 需 few-shot benchmark.

---

## Appendix: 当前 prompt 字数实测 (供参考)

待补充: 跑一次 Sir 重启服务后, dump 一次 prompt 实际装配, 让 Sir 看真字数.
