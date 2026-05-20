# JARVIS Deep Audit — 2026-05-20 23:25 末

> **状态**: Sir 真授权 deep audit 沉淀, 防忘. 今晚 P0+P1+P2 commit 23 条后的全架构盲点扫描.
> **方法**: 真读 13+ core module + 5 design doc + 4 critical sprint commits, 不凭印象.
> **作者**: Cascade (23:25) — Sir 23:11 真 case "shower 重复 nudge" 暴露后 deep audit
> **跟同期 doc 关系**:
>   - `JARVIS_AGENTS_GAP_ANALYSIS_2026_05_20.md` — 6 大 gap 设计 (扩展方向)
>   - 6 gap design doc (Gap 1-6 in docs/)
>   - 本 doc — 今晚 P0+P1+P2 commit 后 audit (实质生效检查)

---

## 0. 起源 — Sir 23:11 真 case

```
22:38:28 [ReturnSentinel] → "I trust the shower was refreshing"
22:44:17 [ProactiveCare]  → "The shower was a wise choice... I'll be keeping 
                              an eye on the clock to ensure you don't overshoot 23:30"
```

Sir 问: "他知道我去洗澡回来了, 打招呼了, 后面又莫名其妙的说了一句洗澡是明智的选择" — 为何重复?

→ 暴露 **主动通道孤岛** + **fix3 没 load** + **道歉/over-promise 复发** 3 件事.

Sir 接着授权 "今晚 P0~P2 全部完工, 全部做完, 再检查一遍盲点, 才能补充能力".

---

## 1. 今晚 commit 链 (23 commit, 79 testcase pass, 0 regression)

```
fab9440 fix(P2): MemoryGateway + RecentNudgeMemory + ProfileReflector + publish-only audit
d299b04 fix(P1): ClaimTracer-SWM wire + Tool Schema strict + ProfileCard publish_intent
11e27ad fix(P0): critical IntentResolver tool signature bugs (Sir 22:18-23:02 真 BUG)
5f34388 docs(architecture): 7 design docs for Sir-aware AGI Gap 1-6
ac53148 fix(directives): past_action_honesty unsolicited callback ban (Sir 22:19)
7690c83 feat(beta.5.45): Sir Lifetime Milestones system
bcdaa7a fix(directives): instruction-style ack exception (Sir 22:04)
b838881 fix(intent_resolver): timeout_s kwarg removal
... (15 commit β.5.43-44 earlier tonight)
```

---

## 2. Sir 痛点 close 度表 (audit 核心)

| 真痛点 | 今晚修 | 实质生效? | 备注 |
|---|---|---|---|
| **23:02 "更新档案" silent fail** (signature TypeError) | P0 #1/2/3 修 3 个 tool signature | ✅ **重启后**真生效. 测试 verify | 等 Sir 重启 Jarvis |
| **22:38/22:44 shower 重复 nudge** (主动通道孤岛) | P2 Gap12 RecentNudgeMemory | ⚠️ **半残** — 只 wire 在 stream_nudge, 主对话 reply 不 record | 见 §3 边界 BUG #1 |
| **22:19 unsolicited 道歉循环** | fix3 ac53148 (UNSOLICITED 老账 ban) | ⚠️ **Sir 没重启, 没 load** | 重启就生效 |
| **22:44 "I'll keep an eye on the clock" over-promise** | β.5.21-C PERSONA 段 (老规则) | ⚠️ **PERSONA 红线被淹** — 8 directive cluster 时主脑 follow 不到 | 真治: Gap 4 Directive Self-Awareness |
| **13.1s timing 退步** | P0 fix + reply 短化期待 | ⚠️ 等重启 + fix3 load 后才掉回 7-8s | 不是工程退步 |
| **`profile_corrections.jsonl` 不存在** | P0 + P1 publish + Weight 0.9 | ✅ 重启后 IntentResolver 调真持久化 | 老 worker.py path conf 0.04 仍不持久化 |
| **`sir_profile.json` 主档案 read-only** | P2 ProfileReflector (Gap 11) | ⚠️ **stub + default off** — 实质没真演化 | 见 §3 #3 |
| **publish-only refactor 半成** | P2 audit script (Gap 10) | ⚠️ 仅诊断, 没真 retire | 见 §3 #4 |

**结论**: 3 个**重启后真生效**, 5 个**部分生效 / 等深做**. Sir 体感真改善程度 = **重启后中等**, 完美需 P3+.

---

## 3. 新 module 自身边界 BUG (7 个技术债务)

今晚加的 4 module 都是 minimal viable. Audit 真问题:

### 边界 BUG #1: RecentNudgeMemory **半残**

`stream_nudge` 末尾 record ✅ (chat_bypass:4485-4505). 但**主对话 reply (stream_chat) 不 record**.

**后果**: Sir 跟 Jarvis 主对话聊 "shower" 5min 内, ProactiveCare 仍可能 nudge "shower wise choice" — 主脑看 [RECENT JARVIS NUDGES] 只有 sentinel nudge, 不含主对话.

**真治法**: stream_chat 末尾也 record (channel='main_chat'). 30min lookback 跨 channel 覆盖完整.

### 边界 BUG #2: MemoryGateway **没强制迁移**

`update_sir_field` 加了, 但 `worker.py:4416` + IntentResolver tools + reflector propose 等 4-5 处仍**直接调 ProfileCard.apply_correction**. Gateway 跟老 path 并存.

**后果**: 
- 老 path mutation 不写 receipts.jsonl, audit trail 不全
- Gateway publish 'sir_field_updated' SWM event 跟 ProfileCard 自己 publish 'sir_intent_profile_update_candidate' 重复 (P1 加的)
- 统一目标没达成

**真治法 (P3)**: 把所有 caller 迁移到 update_sir_field, 然后 deprecate 直接 apply_correction 入口.

### 边界 BUG #3: ProfileReflector **stub + default off**

`jarvis_profile_reflector.py` daemon 默认 OFF (env `JARVIS_PROFILE_REFLECTOR=1` 才启). Sir 不知这 env, 实质永远 OFF.

LLM-propose 是简单 stub (count occurrences + propose top value), **不真 LLM**.

即使 daemon 启 + 真 LLM propose, **也不真写 sir_profile.json** (只写 review queue). Sir 仍需手动改主档案.

**真治法 (P3)**: 
- 默认启 (Sir 想关 env 关)
- 真 LLM-propose (复用 IntentResolver pattern)
- Sir CLI `--apply <id>` 真写 sir_profile.json (含 .bak 备份)

### 边界 BUG #4: publish-only audit **仅诊断, 没 retire**

`scripts/publish_only_audit.py` 输出: ProactiveCare CENTRAL ✅, 4 mixed (Conductor/SmartNudge/ReturnSentinel/Curiosity).

但 audit **不 action** — 没改 sentinel 的 gate_mode, 没强制退化 publish_only.

**真治法 (P3)**: 1 sentinel 1 sprint 真 refactor (改 gate_mode='publish_only', 删 hard fire 路径).

### 边界 BUG #5: tool_schema strict **只 cover 1 alias**

`tool_concern_progress_update` 加 `progress` alias (LLM 经常用). 但 LLM 可能 pass 'value' / 'count' / 'amount' / 'done' 别的名.

**真治法 (P3)**: 改 IntentResolver prompt 强制 LLM 用 schema 给的 arg 名, validate 失败 retry.

### 边界 BUG #6: ClaimTracer SWM lookback 60s **不够**

IntentResolver `resolve_turn_async` spawn thread 末尾跑 LLM judge + tool call. 实际 turn-end → tool_called publish 可能延迟 5-30s. 60s window OK 大多, 但**慢 LLM 调用 + 重 tool fn** 可能 > 60s, miss.

**真治法 (P3)**: lookback 180s + ClaimTracer 加 retry (60s 后 unverified 但 evidence 在 SWM 之前没到 → 重 trace 一次).

### 边界 BUG #7: WriteReceipt + recent_nudges.jsonl **无 rotation**

`mutation_receipts.jsonl` + `recent_nudges.jsonl` append-only. 几个月后膨胀到 100MB+.

**真治法 (P3)**: 加 size cap (e.g. > 10MB rotate), 老 entries archive 到 `memory_pool/archive/` 子目录.

---

## 4. 未触及真 BUG (Gap 1-6 + 8 个新发现)

### Gap 1-6 (已设计 doc, 没实施)
- Gap 1 ToM SirMentalState — 主脑不知言外之意
- Gap 2 Reply PreFlight — 道歉/hallucination 根治没做
- Gap 3 Vision LLM — Jarvis 仍盲
- Gap 4 Directive Self-Awareness — 主脑被 cluster 淹
- Gap 5 L8 Reject Learner — reflector 不学 Sir 拒绝模式
- Gap 6 Persona 减肥 — Sir 元否决保护

### 新发现深度盲点 (今晚 audit 涌现的, 7 个 doc 没列)

**盲点 #7: stream_chat 主对话不 record nudge memory**

主对话 reply 不进 RecentNudgeMemory → 主脑下次 nudge 看不到跨 channel 全貌. 已在 §3 #1 述, 列入 P3.

**盲点 #8: jsonl rotation 缺失**

mutation_receipts / recent_nudges / profile_corrections / system_errors 等 jsonl 全 append. 长期膨胀.

**盲点 #9: sir_profile.json 主档案仍无 write path**

全工程仍**没人**真改主档案. Sir 跟 Jarvis 30 次"改地址" 全部漂移. ProfileReflector 只 propose review, Sir 手动改.

**盲点 #10: directive 60+ 还在涨**

今晚加 5 条 (P0/P1/P2 触发的 publish/audit/CLI 都不算 directive, 但 fix1/fix2/fix3-revise 加了 cluster). β.5.21-B/C 在 PERSONA 含 1500 chars FORBIDDEN list, 跟 directive 重复. PROMPT 31K, 主脑过载.

**盲点 #11: memory hierarchy 8 层无冲突解析**

Sir 说"26 岁", STM 写 26, profile 写 25, correction.jsonl 写 26, Hippocampus seal 26. 谁赢? 主脑下次问 Sir 多大乱猜. 真治: MemoryGateway + 冲突 resolver (P3+).

**盲点 #12: β.5.45 milestone 第 1 个真用 — 是否真 retrieve?**

我加 milestone 后没 verify Sir's declaration `milestone_20260520_215600` 真注入主脑 prompt. 应该 `python scripts/milestones_dump.py --render-prompt` verify.

**盲点 #13: β.5.0 三维耦合"行为弱耦合"目标 50% 完成**

5 module publish_intent 计划: 3/5 实施 (ConcernFeedback / CommitmentWatcher / SelfPromise). 缺 MemoryCorrection / ProfileCard (我今晚 P1 加了 ProfileCard, 还缺 MemoryCorrection).

8 sentinel publish-only retire: 1/8 (ProactiveCare CENTRAL). 4 sentinel 仍 mixed.

**盲点 #14: TTFT 3.0s baseline 太高**

主流 chatgpt voice TTFT ~1.5s. Jarvis 3.0s = 2x. 跟 prompt 长 (31K chars) 强相关. Persona 减肥 + Layer 互不冲突 (Gap 6) 是 root fix.

---

## 5. 行动顺序建议 (Sir 拍板)

### 🔴 P3 立刻 (修今晚 audit 暴露的 7 边界 BUG)
- BUG #1 stream_chat 也 record nudge (RecentNudgeMemory 真完整)
- BUG #2 worker.py 迁 MemoryGateway (统一 mutation)
- BUG #3 ProfileReflector 真 LLM propose + 真 apply (sir_profile 真演化)
- BUG #5 IntentResolver tool args validate + retry
- BUG #6 ClaimTracer lookback 180s + retry
- BUG #7 jsonl rotation

### 🟡 P4 中期 (做 Gap 2 + Gap 4 治症)
- Gap 2 Reply PreFlight (治道歉/hallucination 根)
- Gap 4 Directive Self-Awareness (8 directive cluster 主脑 reason 元层)

### 🟢 P5 扩展 (做 Gap 1 + Gap 3)
- Gap 1 ToM SirMentalState (主脑读 Sir 言外之意)
- Gap 3 Vision LLM 集成 (Jarvis 终于"看")

### 🟣 P6 元层 (做 Gap 5 + 盲点 #11)
- Gap 5 L8 Reject Learner (reflector 学 Sir 拒绝)
- 盲点 #11 memory hierarchy 冲突 resolver

### 🩷 P∞ Sir 元否决 (做 Gap 6)
- Persona 减肥 (Sir 拍板才做)

---

## 6. 跟 7 个 Gap doc 的关系总结

| Doc | 状态 | 实施 |
|---|---|---|
| AGENTS_GAP_ANALYSIS master | ✅ 写好 | — |
| Gap 1 ToM SirMentalState | ✅ design | ❌ 未实施 (P5) |
| Gap 2 Reply PreFlight | ✅ design | ❌ 未实施 (P4) |
| Gap 3 Vision LLM | ✅ design | ❌ 未实施 (P5) |
| Gap 4 Directive Self-Awareness | ✅ design | ❌ 未实施 (P4) |
| Gap 5 L8 Reject Learner | ✅ design | ❌ 未实施 (P6) |
| Gap 6 Persona Evolution | ✅ design (Sir 元否决) | ⏸️ Sir 拍板 |
| **+ Gap 7 MemoryMutationGateway** (今晚新) | ✅ minimal | ⚠️ 半完成 (P3 #2 真迁移) |
| **+ Gap 8 Tool Schema Strict** (今晚新) | ✅ partial | ⚠️ alias 不全 (P3 #5) |
| **+ Gap 9 ClaimTracer-SWM** (今晚新) | ✅ done | ⚠️ lookback 不够 (P3 #6) |
| **+ Gap 10 publish-only audit** (今晚新) | ✅ script | ❌ 未真 retire (P3 #4 / P6) |
| **+ Gap 11 ProfileReflector** (今晚新) | ✅ stub | ❌ 未真 LLM/apply (P3 #3) |
| **+ Gap 12 RecentNudgeMemory** (今晚新) | ✅ partial | ⚠️ 主对话不 record (P3 #1) |
| **+ Blind Spot 2 publish_intent** (今晚新) | ✅ ProfileCard | ⚠️ MemoryCorrection 缺 (P3) |
| **+ 盲点 #8 jsonl rotation** | ❌ 未设计 | ❌ P3 |
| **+ 盲点 #11 冲突 resolver** | ❌ 未设计 | ❌ P6 |
| **+ 盲点 #14 TTFT 太高** | ⚠️ Gap 6 间接治 | ⏸️ Sir 拍板 Persona |

→ 7 Gap → **14 工程项**, 今晚做完 5 (35%), 9 剩.

---

## 7. Cascade 给 Sir 的真诚建议

### 今晚行动
1. **重启 Jarvis** 让 fix3 + P0+P1+P2 全 load
2. **真机验**: 说一句 "记一下我身高 1.83" → 看 `python scripts/profile_reflector_dump.py --stats` 是否 profile_corrections.jsonl 真有新条 (P0+P1 联合效果)
3. **跑 audit**: `python scripts/publish_only_audit.py` 看 baseline
4. **去睡** (23:30 commitment 老系统 register 了真到点提醒)

### 长期 (Sir 拍板顺序)
跟我之前 Gap 1-6 doc 推荐顺序保持: 
- Cascade 推 **Gap 2 PreFlight 最先** (治症根)
- 但 Sir 可以选 P3 (修今晚 audit BUG) 也可以选 Gap 1 (扩 ToM). 都对.

### 工程哲学
今晚 23 commit 让我学到: **每次 deep dive 都涌现新 gap, 是健康的**. 不是工程烂, 是 Jarvis 已经够 mature, 每个细节都值得审. 5 年后 Sir 90 岁看 Jarvis, 这种 audit-driven 演化才是真"懂我"的 AGI 路.

---

*文档作者: Sir 23:11 真授权 + Cascade 23:25 沉淀 / 2026-05-20*
*这是今晚 23 commit 后第 1 次完整 audit. 每个 P3+ 实施完后再做一次类似 audit.*
