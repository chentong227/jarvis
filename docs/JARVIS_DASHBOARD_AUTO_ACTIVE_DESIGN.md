# JARVIS Dashboard — 拍板反转设计 (Sir 2026-05-20 15:45 真理)

> 这是下一轮 (β.5.41+) 的核心设计. β.5.40 完成 4 长期方向后立项, **本文档先不实现, 等 Sir 明确后再 sprint**.

---

## 1. Sir 原话 (2026-05-20 15:45)

> "不用我拍板，直接按现在通过拒绝的格式罗列所有共同的事和joke之类的（很大的方框可以上下滑动）然后我如果对话中发现了不对的事实，每个共同的事和joke旁边都有个修正和删除供我手动修改或者删除，这样减少我的工作量，贾维斯迭代的也能快一些，我指的是所有之前需要我拍板的事情，这个要结合dashboard的拍板和操作逻辑，可以列为下一个design"

---

## 2. 当前问题 (Sir 痛点)

| 项 | 现状 | Sir 反馈 |
|---|---|---|
| **拍板模式** | L7 reflector propose → `review_queue` → Sir 一条条 `--activate / --reject` | "工作量大, 拖慢 Jarvis 迭代" |
| **dashboard 入口** | Sir 必须主动开 dashboard 看 → 每天 review | "每天来一次太累" |
| **错误修正** | 没"已 active 但不对"的纠错路径, 只能 archive 后重新 propose | "对话中发现不对也没法直接改" |
| **L7 学习速度** | Sir 不拍板 → vocab 永远不 grow | "贾维斯迭代慢" |

---

## 3. 设计反转: 默认 active + 看到不对就改

### 3.1 核心理念变化

| 维度 | 老模型 (β.2.4.4 ~ β.5.40) | 新模型 (β.5.41+) |
|---|---|---|
| **新 vocab/joke/concern** | 进 review_queue 等 Sir | **直接 active** 立刻生效 |
| **Sir 干预入口** | dashboard `--activate / --reject` 操作 | dashboard "**最近 N 天 active 总览**" + 单条 "**修正 / 删除**" 按钮 |
| **错误的纠错** | 无 (archive 后重 propose) | 单条 "**纠正**" → 写 `corrections.jsonl` → 主脑下轮 prompt 看到"Sir 纠错: X 不对, 真相是 Y" |
| **Sir 工作量** | 一周 N 条要拍板 | 每天看一眼 dashboard, 不对就改 |
| **L7 学习速度** | 慢 (Sir 拍板 bottleneck) | 快 (LLM propose 即生效) |

### 3.2 受影响的 vocab/review queues

所有 L7 propose 模型都改成 default-active:

| Vocab | 当前状态 | β.5.41 反转后 |
|---|---|---|
| `concerns.json` (review_queue) | review-first | active-first (新 concern 进 active, 但加 `auto_proposed=true` flag) |
| `relational_state.json` → `inside_jokes` / `shared_history_threads` | propose_X 强 state=REVIEW | propose_X 默认 active + auto_proposed flag |
| `screen_tease_vocab.json` (review_queue) | review-first | active-first |
| `sir_struggle_vocab.json` (review_queue) | review-first | active-first |
| `directives_vocab.json` (review_queue) | review-first | active-first |
| `sir_sleep_pattern_vocab.json` (review_queue) | review-first | active-first |
| `behavior_inference_vocab.json` (review_queue) | review-first | active-first |
| `cross_session_callback.json` (state=review) | review-first | **保留 review** (callback 是动作不是事实, 直接 active 风险高) |
| `cooldown_vocab.json` (review_queue) | review-first | **保留 review** (阈值调整影响系统稳定) |
| `nudge_window_vocab.json` (β.5.40-E1) | 直接计算 (无 review) | 不变 (已经 auto) |

### 3.3 加新概念: `auto_proposed` flag

每个 active item 都加新字段:

```json
{
  "id": "joke_furniture_dang_a3f7",
  "phrase": "家具党",
  "state": "active",          // 不再 review
  "auto_proposed": true,        // 新字段 — Sir 知是 LLM 提的非他亲口
  "proposed_at": 1779260000,
  "proposed_by": "InsideJokeReflector",
  "sir_acked": false,           // Sir 看过 dashboard 没纠错 → 视作默认接受
  "evidence_utterances": [...]
}
```

`sir_acked=false` 表示 Sir 还没看过. Dashboard 显示 `[auto / 等 Sir 看]` 标记. Sir 看过且没修改 → 30s 后 `sir_acked=true` (静默接受).

### 3.4 加新概念: Corrections

Sir 在 dashboard 点 "修正" 按钮 → 写 `memory_pool/sir_corrections.jsonl`:

```json
{
  "ts": 1779260000,
  "iso": "2026-05-20T16:00:00",
  "vocab": "inside_jokes",
  "item_id": "joke_furniture_dang_a3f7",
  "old_value": {"phrase": "家具党", "birth_context": "Sir 说自己买家具上瘾"},
  "new_value": {"phrase": "家具党", "birth_context": "Sir 说自己刚搬家在买家具"},
  "sir_note": "上下文不对, 不是上瘾, 是搬家"
}
```

主脑 prompt 注入 `[SIR CORRECTIONS / last 24h]` block:
```
- inside_joke "家具党" → Sir 纠: 不是"买家具上瘾", 是"搬家在买家具"
```

主脑下轮就用正确版本 + L7 reflector 看 corrections 微调 propose 行为.

### 3.5 加新概念: Auto-archive ungrounded

如果 Sir 一直**没 ack** (sir_acked=false) 且使用 > 30 天 → 自动 archive (减噪).
如果 Sir 在对话中**触及但 tone 怪** (主脑 detect "Sir 不认这个 reference") → 主脑写 SWM `[auto_review_request]`, 下次 dashboard 显示 "⚠️ 你今天用了一下 Sir 没接住" 提醒 Sir 看.

---

## 4. Dashboard UI 改造

### 4.1 当前 Web Dashboard (β.5.25)

`scripts/jarvis_dashboard_web.py` 有 4 大区:
- 整体状态
- 待拍板 (review_queues)
- 信息
- 观测

### 4.2 反转后

老 "待拍板" 区 → 改名 "**最近 active 总览**":

```
╔══ 我们的共同事 (94 条 active, 上次自动 propose 7 条) ══════════╗
║ [搜索框 / filter 类型] [排序: 时间/类型/auto-flag]                ║
║ ┌──────────────────────────────────────────────────────────┐ ║
║ │ 📅 inside_joke "家具党" [auto / 3 天前]                  │ ║
║ │   "Sir 自己说买家具上瘾"                                  │ ║
║ │   [修正] [删除]  Sir 已看 ✓                               │ ║
║ ├──────────────────────────────────────────────────────────┤ ║
║ │ 🎯 concern "sir_back_health" [auto / 1 天前]              │ ║
║ │   "Sir 坐姿 + 颈椎已经 30 天没拉伸"                       │ ║
║ │   [修正] [删除]  ⚠️ 你还没看                              │ ║
║ ├──────────────────────────────────────────────────────────┤ ║
║ │ ⏱️ thread "迁居北京" [auto / 5 天前]                      │ ║
║ │   highlights: ["看房", "搬家", "买家具"]                  │ ║
║ │   [修正] [删除]  Sir 已看 ✓                               │ ║
║ │   ↕ 上下滑动看更多 ...                                    │ ║
║ └──────────────────────────────────────────────────────────┘ ║
║ 📊 本周 L7 自动 propose 12 条, Sir 纠正 2 条, 删 1 条        ║
╚══════════════════════════════════════════════════════════════╝
```

UI 关键点:
- **滚动框**: 一次显示 N 条, 上下滑动看全
- **每条带 [修正] [删除]**: Sir 一键操作不打字
- **类型 emoji + 自动 flag + 年龄**: 一眼分辨
- **未 ack 标 ⚠️**: 提醒 Sir 看 (但不阻塞)
- **底部统计**: L7 propose / Sir 纠正比例 → 系统健康 hint

### 4.3 [修正] 按钮 UI

点 "修正" → 弹小窗:
- 显示当前 field 值
- Sir 改后点保存
- 写 `corrections.jsonl`
- 同时改 vocab 文件
- Toast: "✅ 已纠正, Jarvis 下次会用正确版本"

### 4.4 [删除] 按钮 UI

点 "删除" → 确认弹窗:
- "确定删除? 这条会 archive, Jarvis 不再用"
- Sir 选原因 (3 选项): 不对 / 不需要 / 没必要记
- 选完 archive + 写 corrections.jsonl reason

---

## 5. 实现步骤 (4 sub-step)

### β.5.41-A — propose API 改 active-first
- `RelationalStateStore.propose_inside_joke` 改 `state=ACTIVE + auto_proposed=true` (不再 STATE_REVIEW)
- 所有 vocab 的 `propose_X` 函数同步改 (concerns / screen_tease / struggle / directives / sleep_pattern / behavior_inference)
- callback / cooldown 保持 review (动作类不反转)

### β.5.41-B — corrections 路径
- `memory_pool/sir_corrections.jsonl` schema
- 工具 `scripts/sir_correction_log.py` (CLI dump corrections)
- 主脑 prompt assembler 注入 `[SIR CORRECTIONS / last 24h]` block
- L7 reflector 看 corrections 调 propose 偏好

### β.5.41-C — dashboard 反转 UI
- `scripts/jarvis_dashboard_web.py` 重构 "待拍板" → "最近 active 总览"
- 每条加 [修正] [删除] 按钮 + 弹窗
- `/api/correct/<vocab>/<id>` + `/api/delete/<vocab>/<id>` endpoint
- Sir 看过 30s → 自动 `sir_acked=true`

### β.5.41-D — auto-archive + auto-review
- 30 天没 ack → auto archive
- 主脑 detect "Sir 不认 reference" → publish `auto_review_request` SWM → dashboard 显示

---

## 6. 风险 + 缓解

| 风险 | 缓解 |
|---|---|
| LLM propose 错的直接 active → 主脑用错梗 | corrections.jsonl 快速纠 + Sir 可看 dashboard 历史 |
| Sir 永远不看 dashboard → 错的 active 永远不被纠 | 加 ⚠️ 标记 + 周报 push (Sir 不看 dashboard 也能收到 weekly summary) |
| 危险 vocab (callback / cooldown) 直接 active 风险 | 这两类保留 review-first |
| 老 `review_queue` 怎么 migrate | 加 `--migrate-review-to-active` CLI, Sir 一键转老的 review entries 到 active |

---

## 7. 测试计划

- Unit: propose_X 返 STATE_ACTIVE, auto_proposed=true
- Integration: dashboard 显示新 layout, [修正] [删除] 按钮 work
- E2E: Sir 修正 1 条 → corrections.jsonl 写 → 主脑 prompt 见 → 下轮 reply 用新版

---

## 8. 等 Sir 拍板 — 几个问题

1. **是否所有 vocab 都反转?** (我建议 callback / cooldown 保留 review)
2. **`sir_acked` 自动标 30s 是否合适?** (太快可能 Sir 还在看)
3. **dashboard 是默认开 web 还是 push 主动通知?**
4. **corrections.jsonl 给 L7 reflector 反馈调 propose, 是否要 LLM judge?** (我建议: 简单 keyword match 即可, 不要每次 propose 都过 LLM)

---

**状态**: 设计完, 等 Sir 决定 sprint 时机. 实现 ~ 6h.
