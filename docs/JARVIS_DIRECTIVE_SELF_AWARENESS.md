# JARVIS Gap 4 — Directive Cluster Self-Awareness: 主脑看 directive 全貌 + 自己调和冲突

> **状态**: 设计构思, 未排 sprint 编号. 时间可变.
> **关联**: `docs/JARVIS_AGENTS_GAP_ANALYSIS_2026_05_20.md` §3 Gap 4
> **依赖**: 已有 `jarvis_directives.py` (60+ directives), `jarvis_directive_evaluator.py` (post-hoc evaluator)
> **新模块**: 改 `_assemble_prompt` 加 `[DIRECTIVES FIRED THIS TURN]` 元层 block; 改 directive struct 加 `purpose_short` 字段

---

## 0. TL;DR — 一句话

> **现在主脑只见单条 directive text, 看不到 cluster 全貌 + 冲突, 没法 reason "8 条指令冲, 哪些适用此刻". 加 [DIRECTIVES FIRED THIS TURN] 元层 block — 主脑看到 fire 的 directive 列表 + priority + 1 句话 description, 自己调和. 这是治根 directive cluster effect 的元方案.**

---

## 1. 起源 / 痛点

### 1.1 Sir 22:19 真实 case

22:19 turn fired **8 directives** (2350 chars):

```
[L2 inject] tier=SHORT_CHAT fired=[
  'no_hallucinated_tool_use_judge',
  'bilingual_directive',
  'past_action_honesty',
  'capability_boundary_judge',
  'correction_writepath_no_tool',
  'tool_overture_directive',
  'callback_recall_judge',
  'late_night_care_judge'
] (count=8 / chars=2350)
```

主脑被淹没. 它**看到 8 段独立 directive text**, 不知:
- 哪个 priority 最高
- 哪些之间冲突 (e.g. fix3 "不主动道歉" vs fix1/fix4 "言行一致")
- 哪些是 false positive (e.g. past_action_honesty fire 但 Sir 是 instruction "记一下", 不是请求 past action)

→ 主脑只能**全部 follow**, 产生 over-correcting reply (hydration apology).

### 1.2 现状: directive 是黑盒 push

```
turn 开始 → _assemble_prompt:
  for each directive in registry:
    if directive.trigger(ctx):
      prompt += directive.text   # 整段塞 prompt
   ↓
  主脑收 prompt → 反应
```

主脑反应模式: **看到一条指令就 follow**. 没机会"先把 8 条全 list 出来 reason 哪些适用".

### 1.3 治根方向

给主脑**元层视角**:
- "这 turn 你被注入了 8 条 directive"
- "它们 priority 是 [12, 10, 10, 10, 9, 9, 8, 8]"
- "**1 句话 description** 每条管什么"
- "你自己判: 哪些真适用此刻, 哪些是 false positive"

主脑就能 reason: "fix3 priority 10 vs fix1 priority 10, 两者冲突. Sir 当前 turn 是 instruction-style, fix3 适用, fix1/fix4 不应实质改我 reply".

这是**主脑 directive self-awareness** — 不教更多规则, 给主脑**看规则的视角**.

---

## 2. 设计 — directive 加元层 + prompt 注入

### 2.1 改 Directive dataclass 加 `purpose_short` 字段

```python
@dataclass
class Directive:
    id: str
    source_marker: str
    priority: int
    ttl_days: int
    tier_whitelist: list[str]
    text: str                       # 详细 directive text (现有, 主脑看 detail)
    trigger: Callable               # 现有
    
    # 🆕 加这一行:
    purpose_short: str = ''         # < 80 chars, 1 句话描述这条 directive 管什么
                                    # 例: "防主脑 hallucinate tool use claim"
                                    # 例: "Sir 给 instruction-style 时只 ack 不道歉"
                                    # 例: "禁主脑主动从历史翻老 over-claim 道歉"
```

`purpose_short` 不是给主脑看 detail, 是让主脑能**快速 reason cluster 全貌**.

### 2.2 主脑 prompt 注入新 block

在 `_assemble_prompt` 末尾 (现有 directives inject 之后) 加:

```
=== DIRECTIVES FIRED THIS TURN (元层视角) ===
You have {N} directives injected above. Quick overview:

  P12 ⚠️ no_hallucinated_tool_use_judge — 防你 hallucinate tool use claim
  P10 ⚠️ past_action_honesty — 禁你说"已 X"无 tool result. 含禁主动翻老账子条款
  P10 ⚠️ capability_boundary_judge — 教你说能力边界. 含 instruction-style 例外
  P9    correction_writepath_no_tool — Sir 给 reminder write 指令无 tool → 诚实说没工具
  P9    tool_overture_directive — tool fire 前 lead-in 句式
  P8    callback_recall_judge — Sir 用代词 → 先 referent 老话题
  P8    late_night_care_judge — 22:00+ tone gentle
  
[HOW TO USE THIS META-VIEW]
- 不是每条都必 follow 字面. 看 priority + Sir 当前情境调和.
- 多条冲突时 (e.g. P10 vs P10): 自己 reason 哪条更适用此刻.
- 怀疑某条 fire 错 (false positive): 跳过它 (e.g. past_action_honesty 在 instruction-style 时该让位).
- INTEGRITY 系类 (P10+): 永远 honor 底线, 但可以**沉默** (不主动 trigger), 不必 over-correct.
```

### 2.3 关键设计原则

1. **不删 directive text**: 完整 detail 仍注入 (现有路径), 只加**元层摘要**让主脑能"鸟瞰".
2. **priority 显式排序**: 让主脑知道 P12 > P10 > P9, 冲突时优先 P 高.
3. **`HOW TO USE THIS META-VIEW` 子段** 是治根关键 — 教主脑"directive 是 hint 不是 absolute rule".
4. **不教具体调和规则**: Sir 22:47 真理 "工具有现成的, 懂我为主". 不给主脑规则, 给主脑视角.

---

## 3. 实施层级

### Layer A — Directive dataclass 扩展
- 改 `@d:\Jarvis\jarvis_directives.py` 所有 60+ Directive 实例
- 给每条加 `purpose_short=""` field (默认空, 不阻塞 backward compat)
- 重点 ~20 条 (priority ≥ 8) 加真 purpose_short, 余 40 条 lazy 加
- 测试: ~5 testcase 验 dataclass + 不破现有 directive 系统

### Layer B — _assemble_prompt 加元层 block
- 在 directive inject 区末尾加 `[DIRECTIVES FIRED THIS TURN]` block
- 取本 turn fired list (现已有日志 `🧭 [L2 inject] fired=[...]`)
- 渲染: priority sort 降序 + emoji icon (P12+ ⚠️, P8-9 无)
- 含 `[HOW TO USE THIS META-VIEW]` 子段
- block 大小控制 < 1000 chars (fired ≤ 10 条时)

### Layer C — Telemetry
- 记 fire 计数 + 主脑是否 over-correct (用 PreFlight Gap 2 verdict 判)
- 每周 review 看哪些 directive 经常 fire 但 PreFlight 说 over-correct → propose 调整 priority / trigger / scope
- 写 `memory_pool/directive_meta_stats.jsonl`

### Layer D — CLI 工具
- 新文件: `scripts/directive_meta_dump.py`
  - `--list-recent` 看最近 N turn fired directive cluster
  - `--conflicts` LLM 帮 Sir 找哪些 directive 经常一起 fire 且冲突
  - `--purpose-shorts` 列所有 directive purpose_short, 帮 Sir 审

---

## 4. 准则 6 4 问 binding

| # | 问 | 本设计答 |
|---|---|---|
| 1 | 数据 publish 进 SWM? | ✅ directive_fired 已 publish (现有日志, 加结构化 publish) |
| 2 | 决策让 LLM 做? | ✅ 主脑自己 reason 冲突调和, 不写硬规则"P10 总赢 P9" |
| 3 | 配置持久化 + CLI 可改? | ✅ purpose_short 在 directive_registry.json. CLI scripts/directive_meta_dump.py |
| 4 | 和已有 module 正交? | ✅ 跟 directive evaluator (post-hoc) / PreFlight (Gap 2 pre-hoc) 互补. 是 prompt 装配时的元层 |

---

## 5. 风险 & 缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| **主脑学会 game 元层** (假装 reason 然后还是 over-correct) | 中 | 中 | 跟 Gap 2 PreFlight 联用: PreFlight 是最后 safety net |
| **purpose_short 写不准** 主脑误判 | 中 | 中 | 1) Sir 真机看 + 调 2) 重点 P10+ 写准, P8- lazy 3) L7 reflector L8 (Gap 5) 可学着 propose |
| **prompt 增 1000 chars** TTFT 退步 | 低 | 低 | 现有 prompt 31K, 加 1K = +3%. 主脑 reasoning 提升远 > 这点延迟 |
| **主脑过度怀疑 directive** (跳过 INTEGRITY 红线) | 中 | **致命** | 1) `[HOW TO USE]` 明确"INTEGRITY 系永远 honor 底线" 2) Pre-Flight (Gap 2) Q3 验 factual claim |
| **冲突 directive 调和真的难** (P10 == P10) | 中 | 中 | 不靠主脑全对 — 长期 L8 reflector 学 Sir 拒哪些组合, 慢慢调 priority. 短期容错 |

---

## 6. 完成验收 (Sir 真机判定)

- [ ] Sir 22:19 类 case (fire 8 directives, over-apologize) **不再复现**
- [ ] Sir 看 log fired directive 数仍多 (8+), 但主脑 reply 简洁不 over-correct
- [ ] Sir 觉得 reply 像"butler 自己想清楚后说话", 不像"机器执行 8 条指令"
- [ ] L7 reflector 开始 propose "X directive 跟 Y directive 经常冲突, 建议调 priority" (元学习涌现)
- [ ] TTFT 不退步, prompt 总 chars < 33K (从 31K 涨 < 2K)

---

## 7. 与现有架构的关系

```
turn 开始 → _assemble_prompt:
  ↓
现有: directives.evaluate_trigger → 命中的 inject text
  ↓
[NEW] 加 [DIRECTIVES FIRED THIS TURN] 元层 block
  ↓
主脑收 prompt:
  - directive text (现有, detail)
  - directive meta block (新, 鸟瞰 + 教用法)
  ↓
主脑 reasoning:
  "这 turn 我有 8 条 directive, P12 priority 最高, P10 有 3 条且 fix1/fix3 冲突.
   Sir 当前 turn 是 instruction-style, fix3 ('不主动道歉') 更适用. 我 follow fix3."
  ↓
生成 draft → (Gap 2 PreFlight 二次审) → 输出
  ↓
post-hoc: SoulEvaluator + ClaimTracer + 现有 evaluator
  ↓
Gap 5 L8 Reject Learner 看 fired cluster + verdict, propose directive 系演化
```

---

## 8. 跟 Gap 2 PreFlight 联用

- **Gap 4 (本)**: prompt 装配时给主脑元视角, 让主脑**生成 draft 时就更稳**
- **Gap 2**: draft 生成后, PreFlight 二次 self-check, 兜底纠错

两层防御:
- Gap 4 治根 — 主脑 reasoning 强化
- Gap 2 治症 — 最后 safety net 漏网

理想顺序: **Gap 2 先实施** (治症 ROI 高), **Gap 4 后实施** (治根更深远, 但需要 PreFlight stats 数据辅助调整 purpose_short).

---

## 9. 关键参考

- `@d:\Jarvis\jarvis_directives.py:1-200` Directive dataclass + 60+ instance
- `@d:\Jarvis\jarvis_directive_evaluator.py` Evaluator post-hoc
- `@d:\Jarvis\memory_pool\directive_registry.json` directive 持久化
- `@d:\Jarvis\docs\JARVIS_REPLY_PREFLIGHT.md` Gap 2 (本 Gap 互补)
- `@d:\Jarvis\docs\JARVIS_REJECT_LEARNER_L8.md` Gap 5 (本 Gap 数据源 → L8 学)

---

## 10. 落地后涌现的可能 Gap (Gap 7+)

- **Directive 主脑自propose**: 主脑 fire 错 directive 自己 reason 后, propose "建议这条 directive 改 trigger" → L7 reflector → Sir review
- **Directive 自动 archive**: 30 天 fire 但 PreFlight 总判 false positive → 自动 review queue 候 archive
- **Directive 跨 turn 演化**: 看 fired cluster 跨 100 turn 演化, propose"P10 cluster 减肥, 合并成 P11 一条"

---

*文档作者: Sir 22:47 真授权 + Cascade 23:03 沉淀 / 2026-05-20*
*这是治根 directive cluster effect 的元方案, 跟 Gap 2 PreFlight 互补.*
