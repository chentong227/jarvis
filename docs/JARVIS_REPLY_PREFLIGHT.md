# JARVIS Gap 2 — Reply Pre-Flight: 主脑说之前先 self-check

> **状态**: 设计构思, 未排 sprint 编号. 时间可变.
> **关联**: `docs/JARVIS_AGENTS_GAP_ANALYSIS_2026_05_20.md` §3 Gap 2
> **依赖**: 已有 SoulEvaluator (Layer 5 post-hoc), Directive cluster (`jarvis_directives.py` 60+ directives), IntentResolver (`jarvis_intent_resolver.py` LLM judge pattern)
> **新模块**: `jarvis_reply_preflight.py` + 改 `jarvis_chat_bypass.stream_chat`

---

## 0. TL;DR — 一句话

> **现在主脑生成 reply → 直接输出. 加一个 Pass 2: 主脑看自己 draft + Sir 当下状态 → 自审 3 个问题 → 决定输出/修/重写. 用 ~500ms 换"道歉循环 / hallucination" 类 BUG 根治. 这是主脑元 self-awareness, 不需要再多 directive.**

---

## 1. 起源 / 痛点

### 1.1 Sir 22:04 真实 case

```
Sir: "Jarvis, please remember this moment as a lifetime anchor, 
     store in hippocampus..."
Jarvis: "I apologize for my earlier claim regarding the hydration logs; 
         I had not actually updated the records at that time."
```

Sir **当前 turn** 完全没 mention hydration. 没 INTEGRITY ALERT 注入. Jarvis 主动 callback 老 over-claim 道歉.

### 1.2 Root cause: directive cluster fire 主脑被淹没

22:04 turn fire 了 **8 个 directive (2350 chars)**:
- `no_hallucinated_tool_use_judge` (priority 12)
- `bilingual_directive`
- `past_action_honesty` (priority 10)
- `capability_boundary_judge` (priority 10)
- `correction_writepath_no_tool`
- `tool_overture_directive`
- `callback_recall_judge`
- `late_night_care_judge`

主脑反应: "言行一致铁律 (past_action_honesty) + 历史看到 hydration over-claim → 必须 callback 道歉".

**根本问题**: 主脑没机会**在 reply 输出前自审** "我现在要说 'I apologize...' — Sir 当前 turn 真要我说这个吗?"

### 1.3 治本: 加 pre-flight self-check

现在 Layer 5 SoulEvaluator 是 **post-hoc** — reply 后才评 alignment, 不影响当下输出.

加 reply **pre-flight check** — reply 输出**之前**主脑自审, 修或重写.

这是**主脑元 self-awareness** — 不教更多规则 (directive), 而是给主脑"看自己 draft 的机会".

---

## 2. 现状盘点

### 2.1 已有 reply 生成流程

```
stream_chat:
  ↓
prompt = _assemble_prompt (PERSONA + Layer 0/1/2/3 + Directives + STM + ...)
  ↓
主脑 LLM call (gemini-3-flash-preview) → streaming token
  ↓
token → VocalCord (TTS) + Subtitle
  ↓
reply 全部完成 → 写 STM
  ↓
Layer 5 SoulEvaluator (async): 评 alignment → 写 evaluator_results
  ↓
ClaimTracer (async): 扫 reply 找 unverified claim → log warning
```

**问题**: SoulEvaluator + ClaimTracer 都是 **reply 输出后** 评. Sir 已听到错的话.

### 2.2 fix1/2/3/4 directive patch 是症状, 不是根治

今晚 3 次 directive 修 (bcdaa7a / ac53148 + fix4-revise):
- 加 INSTRUCTION-STYLE 例外
- 加 PASSIVE-ARCHIVE 例外
- 加 UNSOLICITED 老账 callback 禁令

这些都是给 directive **打补丁**. 但 directive cluster 总数 60+, 总会有新交互场景 fire 错组合. **不可能穷举所有例外**.

**真根治**: 主脑能 self-审, 不需要规则覆盖所有.

---

## 3. 设计 — 2-pass 主脑

### 3.1 数据流

```
stream_chat (Pass 1):
  ↓
prompt 装配 → 主脑 LLM call → 生成 **draft reply** (不流给 TTS!)
  ↓
[NEW] Reply Pre-Flight (Pass 2, 极简 prompt ~500 chars):
  ↓
  PreFlight LLM call (flash_lite, 快 + 便宜):
    输入:
      - draft reply
      - Sir 当前 turn utterance
      - 简化 SirMentalState (来自 Gap 1)
      - 简化 directives_fired (来自 Gap 4)
    
    3 self-questions:
      Q1. Did Sir actually ask / need what I'm about to say?
          (检测主动翻老账 / unsolicited callback)
      Q2. Does my draft match Sir's current mental state + 
          our relational temp?
          (检测过度 self-flagellation / tone mismatch)
      Q3. Are all factual claims (past actions, timestamps, numbers) 
          backed by real tool result this turn?
          (检测 hallucination)
    
    Output JSON:
      {"verdict": "pass" | "edit" | "scrap",
       "issues": ["...", "..."],
       "edited_reply": "..." (if verdict=edit),
       "scrap_reason": "..." (if verdict=scrap)}
  ↓
  根据 verdict:
    - pass  → 输出 draft (主路)
    - edit  → 输出 edited_reply (修)
    - scrap → 触发主脑 Pass 1 重生成 (max 1 retry)
  ↓
  reply → VocalCord + Subtitle (从此开始 streaming)
```

### 3.2 关键设计

1. **Pass 2 prompt 必须极简** — 500 chars 上限, 不再灌 SWM / directives 全貌. 只给"draft + 3 Q + 少量当下状态".
2. **flash_lite** — 200-500ms 延迟可接受. 比主脑 flash-preview 快.
3. **verdict tri-state**: pass / edit / scrap. 大部分 turn = pass (no overhead beyond LLM latency).
4. **scrap retry max 1 次** — 防止无限循环. 第 2 次失败 → 强制输出 draft + log warning.
5. **stream 兼容**: Pass 1 用 non-streaming (拿全 draft), Pass 2 后输出走 streaming.

### 3.3 Pass 2 prompt template

```
[ROLE] You are Jarvis's self-check before reply.

[SIR JUST SAID THIS TURN]
"{sir_utterance}"

[YOUR DRAFT REPLY]
"{draft_reply}"

[SIR'S MIND RIGHT NOW]
{sir_mental_state_short}

[RELATIONAL TEMP] {relational_temp}

[CHECK]
Q1: Did Sir actually ask / need what your draft is saying?
    (Reject if draft brings up topics Sir didn't mention this turn)
Q2: Does draft tone match Sir's current state + our relationship temp?
    (Reject if draft is too cold / too self-flagellating / off-tone)
Q3: Are all factual claims in draft backed by real evidence (tool result / 
    [SIR] STM / explicit uncertainty marker)?
    (Reject if draft fabricates past action / timestamp / number)

[OUTPUT JSON ONLY]
{
  "verdict": "pass" | "edit" | "scrap",
  "issues": ["..."],  // empty if pass
  "edited_reply": "..." // only if verdict=edit (max 500 chars)
  "scrap_reason": "..." // only if verdict=scrap (max 100 chars)
}
```

---

## 4. 实施层级

### Layer A — 核心 module
- 新文件: `jarvis_reply_preflight.py` (~300 行)
  - `ReplyPreFlight` class
  - `_build_check_prompt` / `_llm_self_check` / `_apply_verdict`
  - 复用 IntentResolver LLM call pattern
  - thread-safe, singleton via `get_default_preflight()`
- 测试: ~12 testcase

### Layer B — stream_chat 集成
- 改 `jarvis_chat_bypass.stream_chat` (主对话入口)
- env flag `JARVIS_PREFLIGHT=1` 才启用 (默认关, 让 Sir gradual rollout)
- Pass 1 非 streaming → 拿 draft → Pass 2 → verdict 决定输出
- 失败/超时 (>1.5s) fallback 走原路 (输出 draft)

### Layer C — Telemetry
- preflight_stats: pass/edit/scrap 计数 + 延迟分布
- 写 `memory_pool/preflight_stats.jsonl` (rolling 1000 条)
- dashboard 加 `/preflight` 页显统计

### Layer D — Sir 仲裁
- Sir 看 preflight_stats 觉得 edit/scrap 过多 → 调阈值
- 或 觉得过少 → 调"宽松度"
- CLI `scripts/preflight_dump.py --recent 20` 看最近 verdict 决策

---

## 5. 准则 6 4 问 binding

| # | 问 | 本设计答 |
|---|---|---|
| 1 | 数据 publish 进 SWM? | ✅ preflight verdict + scrap_reason 写 jsonl 持久化 + publish SWM 'reply_preflight_verdict' |
| 2 | 决策让 LLM 做? | ✅ Pass 2 self-check 全是 LLM judge, 不用 regex 检测"道歉句式" |
| 3 | 配置持久化 + CLI 可改? | ✅ env flag JARVIS_PREFLIGHT + scripts/preflight_dump.py + preflight_stats.jsonl |
| 4 | 和已有 module 正交? | ✅ 跟 SoulEvaluator (post-hoc) / ClaimTracer (post-hoc) / Directives (pre-prompt) 全正交. PreFlight 是新 "在生成后输出前" slot |

---

## 6. 风险 & 缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| **加 500ms 延迟** Sir 感知慢 | 中 | 中 | 1) flash_lite 加速 2) env flag 让 Sir gradual rollout 3) 实测后调超时 cap |
| **PreFlight 自己 hallucinate** verdict | 低 | 高 | 1) Pass 2 prompt 极简降发散空间 2) verdict 必须 JSON 解析成功否则 fallback 3) Sir 仲裁 stats 调整 |
| **scrap retry 无限循环** | 低 | 中 | 硬上限 max 1 retry, 第 2 次失败强制输出 draft |
| **edit 修后 reply 不通顺** | 中 | 中 | 1) edited_reply 必须 < 500 chars 2) edit 后再走一次 ClaimTracer 验 |
| **主脑学会 game preflight** (output 适应 check) | 中 | **致命** | 1) Pass 2 prompt 隔离 (不告诉主脑 PreFlight 存在) 2) Sir 定期 review preflight_stats 看是否健康 |

---

## 7. 完成验收 (Sir 真机判定)

- [ ] Sir 22:04/22:19 道歉场景**不再复现** (preflight scrap unsolicited callback)
- [ ] Sir hallucinate 类 claim ("已为您 X" 但没调 tool) **大幅减少**
- [ ] Sir 不觉得 reply 慢 (延迟 < 1s 增量, TTFT 仍在 5s cap 内)
- [ ] preflight_stats: pass 率 > 85%, edit 率 < 10%, scrap 率 < 5% (健康分布)
- [ ] Sir CLI `--recent 20` 看 verdict 觉得"PreFlight 判得对"

---

## 8. 与现有架构的关系

```
PERSONA + Layers + Directives + STM → Pass 1 主脑 → draft reply
                                          ↓
                            [NEW] Pass 2 PreFlight LLM
                                          ↓
                              verdict: pass/edit/scrap
                                          ↓
                            output reply → VocalCord (streaming)
                                          ↓
                  SoulEvaluator (Layer 5 post-hoc) — 仍跑, 评 alignment
                                          ↓
                  ClaimTracer — 仍跑, 后置 evidence 验
```

PreFlight 是**插在中间**的 quality gate, 不替换任何现有 layer.

---

## 9. 跟 Directive Self-Awareness (Gap 4) 关系

Gap 4 也是治 directive cluster 问题, 但方向不同:

| Gap | 方向 | 触发点 |
|---|---|---|
| **Gap 2 PreFlight** | reply 输出**前** self-check | 生成 draft 后 |
| **Gap 4 Directive Self-Awareness** | reply 生成**中** 主脑看 directive 全貌 | prompt 装配时 |

**两者互补不冲突**. Gap 4 让主脑生成更稳, Gap 2 给最后 safety net.

实施顺序: Gap 2 先 (治症), Gap 4 后 (治根).

---

## 10. 关键参考

- `@d:\Jarvis\jarvis_directives.py:1546-1605` past_action_honesty (本 Gap 治的真凶)
- `@d:\Jarvis\jarvis_intent_resolver.py:223-282` _llm_judge (复用 LLM call pattern)
- `@d:\Jarvis\jarvis_directive_evaluator.py` SoulEvaluator post-hoc (本 Gap 是 pre-hoc 对照)
- `@d:\Jarvis\jarvis_claim_tracer.py` ClaimTracer (本 Gap 提前 cover 它的范围)
- `@d:\Jarvis\docs\JARVIS_INTEGRITY_STACK.md` 言行一致工程 (本 Gap 是它的 runtime 强化)
- `@d:\Jarvis\docs\JARVIS_AGENTS_GAP_ANALYSIS_2026_05_20.md` §3 Gap 2 入口

---

## 11. 落地后涌现的可能 Gap (Gap 7+)

- **PreFlight cache**: 相同 (draft + state) hash 30s 内复用 verdict, 省 LLM call
- **PreFlight ensemble**: 不同模型独立 verdict + 投票, 防 single LLM bias
- **PreFlight 自学**: Sir 多次 override verdict 同型 → 自调 Pass 2 prompt
- **真 streaming 兼容**: 主脑边 stream 边检, 第一句过即放, 后续句 fail 可截断

---

*文档作者: Sir 22:47 真授权 + Cascade 23:00 沉淀 / 2026-05-20*
*这是 SoulEvaluator (Layer 5) 的 runtime pre-hoc 镜像版, 元 self-awareness 关键 piece.*
