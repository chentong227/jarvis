# JARVIS 记忆系统 + 修正能力 重构方案

**起源**: Sir 21:55 真测反馈, 强调"重构而非添加 / 找模块边界重叠 / 合并重构 / 复写能力分层架构".

本 doc 是 **设计阶段**, 分多 part. Part 1 = 完整模块审计 (本文件).

---

# Part 1: 模块审计

## 1.1 进入主脑 prompt 的 30+ 数据 block

依 `_assemble_prompt` 装配顺序 (每轮 try inject):

| # | block | 数据源 | 持久化 |
|---|---|---|---|
| 0 | base_persona | hardcoded | code |
| 1 | self_anchor (L0) | `jarvis_self_anchor` | 内存 |
| 2 | soul/concerns (L1) | `ConcernsLedger` | `concerns.json` |
| 3 | relational (L2) | `relational_state` | `relational_state.json` |
| 4 | attention (L3) | dynamic | (无) |
| 5 | reply_feedback | `reply_feedback.jsonl` | jsonl |
| 6 | profile_corrections | `profile_corrections.jsonl` | **❌ 死代码** |
| 7 | milestones | `sir_milestones.json` | json |
| 8 | recent_nudges | `recent_nudges.jsonl` | jsonl |
| 9 | profile_card | `sir_profile.json` | json |
| 10 | sir_mental_model | dynamic ToM | (内存) |
| 11 | integrity_watcher | `integrity_watcher.json` | json |
| 12 | memory_correction | dynamic | 内存 |
| 13 | watch_tasks | `watch_tasks.json` | json |
| 14 | stand_down | `stand_down_state.json` | json |
| 15 | sir_status | `sir_status.json` | json |
| 16 | screen_vision | `screen_history.jsonl` | jsonl |
| 17 | sir_resting | dynamic | (无) |
| 18 | watch_task_trig | dynamic | (无) |
| 19 | project_hold | sqlite ProjectTimeline | sqlite |
| 20 | error_bus | `system_errors.jsonl` | jsonl |
| 21 | intent_resolver_tools | dynamic SWM | 内存 |
| 22 | mood_line | dynamic | (无) |
| 23 | wake_callback | `cross_session_callback.json` | json |
| 24 | L2 Directives | `directive_registry.json` | json |
| 25-30 (param) | stm / ltm / chat_organs / ledger / landmarks / system_alert | 各自 | jsonl/sqlite/etc. |

**总计 30+ 个**, 每轮装配 ~11000-14000 char.

## 1.2 已有 mutation organ (主脑能修源的接口)

| organ.cmd | 修啥 | 状态 |
|---|---|---|
| `concerns.dismiss/reactivate` | concerns.json state/severity | ✅ fix24 |
| `stand_down.set/clear/status` | stand_down_state.json | ✅ fix25 |
| `promises.fulfill/cancel/list` | jarvis_promise_log.json | ✅ fix27 |
| `ui_control.*` | UI runtime | ✅ |
| `memory_hands.modify_record` | TaskMemories | ✅ 走 hand 路径 |
| `<MEMORY_UPDATE>` tag | 应改 sir_profile.json, **实际写到 profile_corrections.jsonl 死代码** | ❌ **半失效** |

## 1.3 缺的 mutation organ

| 缺口 | Sir 痛点 case |
|---|---|
| `profile.update_field` | "我以后默认晚 11 睡" |
| `concerns.update` (深度: description/what_i_watch/severity) | "睡眠 concern 别这么严肃" |
| `relational.update` | "你这个 joke 太频繁" |
| `attention.adjust` | "windsurf focus 不算工作 (此刻 dynamic 降权)" |
| `screen_vision.annotate` | "windsurf 是 auto-coding" |
| `recent_nudge.suppress` | "这 nudge 别再发" |
| `cross_session_callback.dismiss` | 跨 session 心结 dismiss |
| `mental_model.refine` | Sir 觉得 ToM 推断错 |
| `milestones.update` | 改 lifetime declaration |

## 1.4 持久化但**不进 prompt** 的模块

- **审计**: claim_revisions / claim_stats / mutation_receipts / integrity_audit / main_brain_meta_audit / preflight_stats / jarvis_health_history
- **Vocab** (~25 个 `*_vocab.json`): trigger 词典 (concern_keywords / promise_completion / stand_down_trigger / 等)
- **配置**: directive_inject_config / hippocampus_decay_config / severity_decay_vocab / 等
- **状态储**: jarvis_promise_log (主要给 ProactiveCare 看, 不直接 inject)

## 1.5 死代码 / 半失效 (审计抓出)

| 文件 | 现状 | 问题 |
|---|---|---|
| `profile_corrections.jsonl` | `<MEMORY_UPDATE>` tag 仍在写, **但 profile_card block 不读它** (block #9 直读 sir_profile.json) | Sir 教正 profile 永远不回流 → 主脑下次看的还是老 profile. **半失效** |
| `pending_callbacks.jsonl` | 0 字节 | 似乎不再用 |
| `key_router_reset_audit.jsonl` | 极少写 | 边缘 |

---

**Part 1 审计完毕**.

---

# Part 2: 重叠 / 重复 / 死代码 分析

## 2.1 同一信息从多源 inject — Sir 教正应**改哪几处**?

### Case A: "Sir 体检完了" (今天 21:01 真测)

| Source | 当时 | 教正后应改吗? | 接口 |
|---|---|---|---|
| LTM (block #26) | memory ID 1482: "明天有体检, 早睡" | ✅ 改 (改文字, "今天体检完了") | memory_hands.modify_record |
| Promise (#?) | p_cdc96ad5: "我会关注体检" | ✅ fulfilled | promises.fulfill |
| Concerns (block #2) | sir_sleep_streak (severity=0.96) | ❌ 不改 (sleep ≠ 体检, 是 LLM weave 自己绑的) | (无需) |
| STM (block #25) | 历史提到体检 N 次 | ❌ 不改 (历史快照) | (历史不可改) |
| ScreenVision (block #16) | 实时 process_focus (无关) | ❌ 不改 | (无需) |

**主脑应判**: 改 2 处源 (LTM + Promise). 不要改 Concerns. STM/ScreenVision 历史不可改.

### Case B: "Windsurf 不是我在动" (今天 21:07 真测)

| Source | 当时 | 教正后应改吗? | 接口 |
|---|---|---|---|
| LTM (block #26) | memory: "Sir 在 Windsurf coding" | ✅ refine ("auto-coding habit, focus ≠ active") | memory_hands.modify_record |
| Profile (block #9) | active_projects 含 windsurf | ✅ 加 note (但目前**死代码**, MEMORY_UPDATE 写到 corrections jsonl 不回 sir_profile.json) | **❌ 缺真实修源接口** |
| ScreenVision (block #16) | process_focus=Windsurf 35min | ⭕ 不改源 (实时观察事实), 但**解释方式应变** | (改 LTM 后, ScreenVision context 自然变软) |
| Attention (block #4) | current_focus dynamic | ⭕ 不改 (下次重算) | (依赖 LTM/Profile) |
| Concerns (block #2) | sir_pomodoro_compliance (久坐) | ⭕ 不直接绑 windsurf, 但 LLM 关联 | (依赖 LTM/Profile) |

**主脑应判**: 改 2 处源 (LTM + Profile). Profile 要真覆写, 不能写 corrections.

### Case C: "Cursor 别再提" (Sir 18:42 真痛点)

| Source | 当时 | 教正后应改吗? |
|---|---|---|
| Concerns (block #2) | sir_cursor_payment severity=1.0 | ✅ dismiss (severity=0.3, triggers_proactive=False) |
| LTM | "Sir 抱怨 Cursor 付费" | ❌ 不改 (历史事实) |
| recent_nudges | 多条 cursor nudge | ⭕ 自动衰 |

**主脑应判**: 改 1 处源 (concerns.dismiss). ✅ fix24 已治本.

### 重叠 Pattern 总结

| 重叠类型 | 改源策略 |
|---|---|
| **历史事实 vs 当下解读** (LTM + ScreenVision) | 改"事实解读层" (LTM/Profile), 让"传感器层" 推断**自然变软** |
| **承诺 vs 关心** (Promise + Concern) | 各管各的, 不要因为 LLM weave 在一起就联动改 |
| **静态画像 vs 动态行为** (Profile + Attention/ScreenVision) | 改 Profile 影响 Attention/Vision 推断 |
| **同一概念多处存** (corrections + sir_profile) | **必须合并** — 这是死代码 BUG |

## 2.2 严重重叠 / 重复模块 (合并候选)

### 重叠 1: Promise Log + Commitment Watcher + concerns.notes_for_self

**真实拓扑** (审计后):

```
                Sir 说 "1点睡"  →  Gatekeeper LLM  →  ┐
Jarvis 说 "我会监督" (hard, 有时间) →  SelfPromiseDetector ─┤
Jarvis 说 "I'll keep watching" (soft, 无时间) →  SelfPromiseDetector  ─→  ┘
                                                       ↓
        ┌───── Commitment Watcher (sqlite Commitments + in-memory)  ─→ 定时 nudge ──┐
hard ───┤                                                                                ↓
        └───── Promise Log (jarvis_promise_log.json) ──────────────→ 主脑 audit + Promise reflection
                                                                                          ↑
soft ─── concerns.notes_for_self  ────────────────────────────────────────────────────────┘
```

**重叠点**:
- Hard promise 存 **3 份**: CW.commitments[] (内存) + sqlite Commitments 表 + Promise log json
- Soft promise 存 **2 份**: concerns.notes_for_self + Promise log json
- 主脑 prompt 看的是 **Promise log** (block #?), 不是 CW

**合并方向 (建议)**:
- **Promise Log = single source of truth** (统一账本)
- CW 退化为 **Promise Log 的 timer engine** (订阅 hard promise → schedule nudge), 自身不存数据
- concerns.notes_for_self **删除**, 改用 Promise Log 的 soft kind
- sqlite Commitments 表 **下线** (Promise log 已持久化)

### 重叠 2: profile_corrections.jsonl + sir_profile.json (**确认死代码**)

- `<MEMORY_UPDATE>` tag → 写 profile_corrections.jsonl
- profile_card block (#9) → 直读 sir_profile.json
- **永远不回流**

**合并方向 (建议)**:
- 加 `profile.update_field` mutation organ → **真覆写 sir_profile.json**
- profile_corrections.jsonl 转纯 audit (留 30 天审计, 不进 prompt)
- 主脑 directive 教 "教正 profile 时 emit profile.update_field, 不依赖 MEMORY_UPDATE tag"

### 重叠 3: ScreenVision + sir_status + Attention 都说"Sir 现在在干啥"

| 源 | 角度 | 数据 |
|---|---|---|
| ScreenVision (block #16) | 屏幕 process_focus | "Windsurf 35min" |
| sir_status (block #15) | sleep/return/AFK 状态 | "Sir return after 2h sleep" |
| Attention (block #4) | dynamic 推断 | "current_focus = Windsurf coding" |
| sir_resting (block #17) | dynamic | "Sir might be resting" |
| sir_mental_model (block #10) | ToM 推断 | "Sir 在调 cascade, 可能 frustrated" |
| mood_line (block #22) | 情绪推断 | "mid-evening, possibly tired" |

**6 个 block 都说"Sir 现在状态"**, 但角度不同:
- ScreenVision = sensor (机器看到的)
- sir_status = 时序状态 (sleep/return/AFK 转换)
- Attention = 焦点
- sir_resting = 推断 "可能在休息"
- sir_mental_model = ToM
- mood_line = 情绪推断

**重叠分析**: 这 6 个**不重复**, 是 6 个不同 sensor / inference layer. 但 prompt 看起来累赘. **合并方向**:
- 抽 1 个**[SIR NOW]** 复合 block, 内分 "Sensors" / "State" / "Inference":
  ```
  [SIR NOW]
  Sensors: process_focus=Windsurf (35min), screen_motion=low, idle=12min
  State: returned from sleep 2h ago, AFK risk medium
  Inference: probably auto-coding (windsurf), mid-evening fatigue, mental: cascade debug session
  ```
- 字数从 6 个 block 的 ~800 char → 1 个 block ~250 char

### 重叠 4: recent_nudges + concerns.last_proactive_nudge + watch_tasks

| 源 | 用途 |
|---|---|
| recent_nudges (#8) | 防 Jarvis 30min 内重复 nudge | jsonl |
| concerns.last_proactive_nudge | 防同 concern 1h 内重复 surface | concerns.json 内字段 |
| watch_tasks (#13) | Sir 让我盯的 task | watch_tasks.json |

**3 个不同, 不合并**, 但应在 Part 3 layered architecture 中归同一"NudgeMemory"层.

### 重叠 5: integrity_watcher + claim_revisions + claim_stats

3 个文件都跟"主脑 claim 真实性"有关:
- `integrity_watcher.json` — recent claims report (block #11 inject)
- `claim_revisions.json` — claim 历史修订
- `claim_stats.json` — 统计

**合并方向**: 1 个 IntegrityStore module 内含 3 个 view (current / history / stats). 进 prompt 只 current view. 持久化可保留 3 file 也可合并 1 sqlite.

## 2.3 边界模糊 (需 Sir 决策)

### 模糊 1: "Sir 让我盯的事" 究竟是 Promise 还是 Watch?

- "你帮我盯下次代码 deploy 完了告诉我" → 注册 watch_task
- "你帮我记着我下周要开会" → 注册 commitment? watch? promise?

现状: 各注册路径独立, 主脑随机走. **建议**: 建立"**Sir 委托** vs **Jarvis 自承诺**" 两层概念, 不再混用.

### 模糊 2: cross_session_callback vs concerns

- cross_session_callback = wake 时 surfacing 的"上 session 心结"
- concerns = 长期关心

它们是 **lifecycle 不同**:
- callback = 一次性 (说完就 dismissed)
- concern = 长期 (severity 衰减)

**建议**: 保留 2 个 module, 但**统一 mutation 接口**.

### 模糊 3: sir_milestones vs sir_profile.lifetime

- milestones = lifetime declaration / insight (do_not_use_against_sir)
- sir_profile = 长期画像

**建议**: milestones 是 sir_profile 的子集? 还是独立? 我倾向**独立** (milestones 有特殊 do_not_use_against 规则, 不是普通 profile field).

## 2.4 Part 2 总结表

| 合并 / 重构动作 | 优先级 | 预估行 |
|---|---|---|
| Promise Log = single SoT, CW 退化 timer, soft promise 删 notes_for_self | High | -300 / +200 |
| `profile.update_field` mutation organ + corrections.jsonl 转 audit | High | +150 |
| `[SIR NOW]` 复合 block 替 6 个零散 sensor block | High | -400 / +250 |
| IntegrityStore 整合 3 文件 | Medium | -100 / +100 |
| `cross_session_callback` 加 dismiss mutation organ | Medium | +60 |
| `attention.adjust` mutation organ | Medium | +80 |
| `screen_vision.annotate` mutation organ | Low (Sir 真痛点是 LTM 改) | +60 |

---

**Part 2 完毕**.

---

# Part 3: 分层架构设计

## 3.1 6 层抽象 (按"事实层级 + 修改频率")

灵感来自 Sir 自己的话: "改动短期的关注意图? 改动 LLM vision 的视觉意图? 改动长期的关心意图?". Sir 已经把层级勾出来了, 我系统化:

| 层 | 名 | 修啥 | 修改频率 | 影响什么 | 现有源 (block #) | 现有 mutation organ |
|---|---|---|---|---|---|---|
| **A** | 静态身份 (Identity) | Sir 是谁 | 周/月级 | 所有下层推断 | profile_card (#9), milestones (#7) | ❌ 缺 (corrections 死代码) |
| **B** | 长期信念 (Belief) | Jarvis 对 Sir 长期关心 / 我们关系 | 天级 | 主动 nudge / 性格 | concerns (#2), relational (#3) | ✅ concerns.dismiss; ❌ 缺 update / relational |
| **C** | 长期事实 (Memory) | 历史发生的事 | append-only + 偶修 | retrieve 时影响 | LTM (#26), cross_session_callback (#23) | ✅ memory_hands.modify; ❌ 缺 callback dismiss |
| **D** | 当前状态 (State) | Sir 此刻在干啥 | 分钟级 | 当下回应 | sir_status (#15), screen_vision (#16), stand_down (#14), attention (#4), project_hold (#19), sir_resting (#17), ToM (#10), mood (#22) | ✅ stand_down.set; ❌ 缺 attention.adjust / screen.annotate / sir_status.set |
| **E** | 承诺 / 委托 (Commitment) | Sir / Jarvis 的责任 | 高生命周期 | 定时 nudge | promise (block 多), watch_tasks (#13), CW commitments | ✅ promises.fulfill, watch_tasks.cancel; ❌ 缺 sir_commitment.complete |
| **F** | 教学 / 规则 (Meta) | Jarvis 行为规则 | 月级 | 主脑行为 | directives (#24), vocab files | ✅ scripts/registry_dump CLI; ❌ 缺主脑 emit 接口 |

## 3.2 6 层的"修改触发"特点

```
┌────────────────────────────────────────────────────┐
│  Layer A (Identity): "Sir 全职做 Jarvis"           │  低频
│           ↓ 影响下层推断                            │
│  Layer B (Belief):  "我关心 Sir 久坐"               │  中频
│           ↓ 触发 nudge                              │
│  Layer C (Memory):  "5/20 memory ID 1482 体检"     │  低频改字
│           ↓ retrieve 进 prompt                       │
│  Layer D (State):   "windsurf 35min focus"         │  高频 (sensor)
│           ↓ 当下解读                                │
│  Layer E (Commit):  "p_xxx 我会监督体检"            │  事件型
│           ↓ 定时 nudge                              │
│  Layer F (Meta):    "directive: 不要重复 nudge"    │  最低频
│           ↓ 影响主脑行为                            │
└────────────────────────────────────────────────────┘
                       ↑
           Sir 教正 = 修对应层 (1 或多层)
```

## 3.3 layered mutation interface 统一 schema

所有 mutation organ 遵守同 schema, 主脑 emit 时认知统一:

```json
<FAST_CALL>{
  "organ": "<layer_organ>",   // profile / concerns / relational / memory / promises / etc.
  "command": "<update|dismiss|fulfill|set|clear|complete|cancel>",
  "params": {
    "subject_id": "...",       // ID (memory_id / concern_id / promise_id)
    "subject_keyword": "...",  // 模糊 keyword (system 自动 resolve 到 subject_id)
    "field": "...",            // 改哪个字段 (适用 update)
    "new_value": "...",        // 新值
    "intent": "reinforce|refine|revise|dismiss|complete",  // 性质
    "reason": "...",           // Sir 原话 / 主脑解读
    "turn_id": "..."           // audit 链路
  }
}</FAST_CALL>
```

**返回** (FAST_CALL response, 主脑下轮看):
```
✅ profile.update_field: active_projects.windsurf.note += "auto-coding". Sir 下轮 prompt 自动看新版.
✅ memory_hands.modify_record: ID=1482 改 "明天体检 → 今天体检完了". 下轮 retrieve 看新版.
✅ promises.fulfill: p_cdc96ad5 状态 fulfilled.
```

---

# Part 4: Dispatch 机制 — 主脑听 Sir 教正后怎么做?

## 4.1 主脑 3 步推理 (新 directive `correction_dispatcher`)

```
Sir 教正你时, 3 步推理:

Step 1. 判性质 (intent):
   - reinforce  (加强): Sir 再次确认已知 → 无需修源, evidence_count 自动++
   - refine     (修正): 文字 / 时态 / 数字 调整 (e.g. "明天→今天")
   - revise     (改动): 本质语义改变 (e.g. "X 不是 Y, 是 Z")
   - dismiss    (撤): "别再提" / "别再 nudge"
   - complete   (完结): "X 做完了"

Step 2. 判层级 (which layer):
   A 静态身份 → profile / milestones
   B 长期信念 → concerns / relational
   C 长期事实 → memory_hands / cross_session_callback
   D 当前状态 → sir_status / stand_down / screen_vision / project / attention
   E 承诺/委托 → promises / watch_tasks / sir_commitments
   F 教学/规则 → directive_registry

Step 3. 选 1-3 层影响, emit 1-N 个 FAST_CALL:
   - 同 1 turn 可 emit 多 FAST_CALL (parallel-safe)
   - 修源后, 下轮 prompt 看到的就是已修正版

EXAMPLES:

Sir: "Windsurf 自动编程不是我在动"
  → intent=revise, layers=A+C
  <FAST_CALL>{"organ":"memory_hands","command":"modify_record",
    "params":{"id":1482,"new_intent":"...含 auto-coding 模式"}}</FAST_CALL>
  <FAST_CALL>{"organ":"profile","command":"update_field",
    "params":{"field":"active_projects.windsurf.note",
              "new_value":"focus ≠ in action"}}</FAST_CALL>

Sir: "今天体检完了"
  → intent=complete, layers=C+E
  <FAST_CALL>{"organ":"memory_hands","command":"modify_record",
    "params":{"id":1482,"new_intent":"5/22 体检完成"}}</FAST_CALL>
  <FAST_CALL>{"organ":"promises","command":"fulfill",
    "params":{"keyword":"体检"}}</FAST_CALL>

Sir: "Cursor 别再提"
  → intent=dismiss, layer=B
  <FAST_CALL>{"organ":"concerns","command":"dismiss",
    "params":{"concern_id":"sir_cursor_payment"}}</FAST_CALL>

Sir: "我以后默认晚 11 睡"
  → intent=revise, layer=A
  <FAST_CALL>{"organ":"profile","command":"update_field",
    "params":{"field":"sleep_target_hour","new_value":"23:00"}}</FAST_CALL>

Sir: "windsurf 你别盯它了"
  → intent=dismiss, layer=D
  <FAST_CALL>{"organ":"screen_vision","command":"annotate",
    "params":{"target":"windsurf","note":"uncertainty: auto vs in-action"}}</FAST_CALL>
  + (如有) <FAST_CALL>{"organ":"project","command":"hold",
    "params":{"name":"windsurf","reason":"auto-coding mode"}}</FAST_CALL>
```

## 4.2 Mutation pipeline 流程

```
1. Sir 说话
        ↓
2. 主脑 prompt (装配 30+ block)
        ↓
3. 主脑 LLM 推理 → 判 (intent, layers)
        ↓
4. 主脑 emit N 个 <FAST_CALL>...</FAST_CALL>
        ↓
5. ChatBypass parse / dispatch / 各 organ 执行
        ↓
6. 各 organ 真覆写源 + SWM publish event + 写 mutation_receipts.jsonl
        ↓
7. 各 organ 返回人话 result
        ↓
8. 主脑下轮 prompt: 各 source 已是修正版 + result 注入 (无矛盾)
        ↓
9. ClaimTracer audit: 主脑说 "我已记下" 必须有真 mutation_receipt 否则标 unverified
```

## 4.3 ClaimTracer 防说谎绑定

Mutation 跟 ClaimTracer 协同:
- 主脑 reply 含 "I've updated / 已记下 / 已修正" 等 mutation verb
- ClaimTracer 抓 turn 内是否有真 mutation_receipt
- 没有 → 标 unverified → 下轮 INTEGRITY ALERT prepend
- 有 → 标 verified, audit 链路完整

这是 fix27 已经做的 P5-Gap2-Acceptance, 已上线. 重构后所有 6 层共用此 audit.

---

# Part 5: 未来 Plug-and-Play (Sir 真核心要求)

## 5.1 加新 source 时怎么对接?

Sir 提: "以后加上更多的记忆和知识和现状 (如 vision, 26 项本地数据等) 的模块时, 可以通用使用这个修正架构来修正".

**新 source 接入协议** (4 步):

1. **实现 prompt render** (如要 inject):
   ```python
   def render_prompt_block(self, max_chars: int = 300) -> str:
       """返回 [SOURCE_NAME] block 文本, 否则 ''"""
   ```

2. **实现 mutation interface** (跟统一 schema 对齐):
   ```python
   def update_field(self, subject_id_or_keyword: str, field: str,
                       new_value: Any, intent: str, reason: str,
                       turn_id: str) -> Tuple[bool, str]:
       """返回 (ok, human_message)"""
   ```

3. **实现 subject resolver** (主脑模糊 keyword 找精确 ID):
   ```python
   def find_by_keyword(self, keyword: str) -> Optional[str]:
       """模糊找 top-1 subject ID, e.g. 'Windsurf' → memory_id 1482"""
   ```

4. **注册到 LAYER_REGISTRY**:
   ```python
   # jarvis_mutation_dispatcher.py
   LAYER_REGISTRY = {
       'A_identity':   ['profile', 'milestones'],
       'B_belief':     ['concerns', 'relational'],
       'C_memory':     ['memory_hands', 'cross_session_callback'],
       'D_state':      ['sir_status', 'stand_down', 'screen_vision',
                          'project', 'attention'],
       'E_commitment': ['promises', 'watch_tasks', 'sir_commitments'],
       'F_meta':       ['directive', 'vocab'],
   }
   ```

5. **SWM publish + mutation_receipts.jsonl 写**: 复用现有基建.

**主脑 directive 不需新加** — `correction_dispatcher` 已 cover 6 层. 新 source 自动适用.

## 5.2 例: 加 vision_local_db 新 source (Sir 提的 26 项本地数据)

假设有 sqlite `local_knowledge.db` 含 Sir 本地资料:

1. `jarvis_local_db.py` 实现 4 接口
2. 注册 `LAYER_REGISTRY['C_memory'].append('local_db')`
3. 主脑 prompt 装配时, `local_db.render_prompt_block()` 进 #C
4. Sir 教正时: `<FAST_CALL>{"organ":"local_db","command":"update_field",...}</FAST_CALL>`
5. 主脑 directive **不变** (correction_dispatcher 已通用)

---

# Part 6: 实施 Phase 计划

## Phase 1: Foundation (建基础)

| 任务 | 行 | 优先级 |
|---|---|---|
| 写 `jarvis_mutation_dispatcher.py` (LAYER_REGISTRY + dispatch helper) | ~150 | High |
| 写 `correction_dispatcher` directive (教主脑 3 步推理) | ~120 | High |
| 写 `docs/JARVIS_MUTATION_INTERFACE.md` (新 source 接入协议) | ~150 | High |

## Phase 2: 修死代码 + 加缺口 (按优先级)

| 任务 | 层 | 行 | 优先级 |
|---|---|---|---|
| `profile.update_field` organ + corrections.jsonl 转 audit + sir_profile.json 真覆写 | A | ~250 | **High (死代码)** |
| `concerns.update` (深度 update, 不只 dismiss) | B | ~150 | High |
| `relational.update` organ | B | ~150 | High |
| `cross_session_callback.dismiss` organ | C | ~80 | Medium |
| `attention.adjust` organ | D | ~100 | Medium |
| `screen_vision.annotate` organ | D | ~100 | Medium |
| `sir_commitments.complete` organ (CW 那边) | E | ~100 | Medium |
| `directive.add_or_strengthen` organ | F | ~150 | Low |

## Phase 3: 合并重构 (减熵)

| 任务 | 行 | 优先级 |
|---|---|---|
| Promise/Commitment/notes_for_self 合并 (Promise log 单源) | -100 (净) | Medium |
| `[SIR NOW]` 复合 block 替 6 个零散 sensor block | -150 (净) | Medium |
| IntegrityStore 整合 3 文件 | 0 (净) | Low |

## Phase 4: 主脑 directive 教学 + audit

| 任务 | 行 | 优先级 |
|---|---|---|
| `correction_dispatcher` directive 上线 (Phase 1 写, 此时启用) | (同上) | High |
| ClaimTracer 接 mutation_receipts 全量 audit | ~80 | High |
| Testcase ~30 个 (各层 mutation + dispatch + audit) | ~600 | High |

## Phase 5: CLI + dashboard

| 任务 | 行 | 优先级 |
|---|---|---|
| `scripts/mutation_dump.py` (查最近 N 条 mutation) | ~150 | Medium |
| Dashboard 展示 6 层 mutation 健康 | ~200 | Low |

## 总工作量预估

- 新增: ~2400 行
- 删除/合并: ~600 行
- 净增: ~1800 行
- Testcase: ~600 行
- Doc: ~500 行 (含本 doc + JARVIS_MUTATION_INTERFACE.md)

**预估 5-7 个工作 session** 完成全部 Phase. 每个 Phase 独立可上线, 不必全部完成才能体验.

---

# Part 7: 立即建议下一步

1. **Sir 拍板** Part 3-6 设计是否合理 / 哪些 Phase 优先做
2. **如果 Sir 同意大方向**, 我先做:
   - Phase 1 (foundation, mutation_dispatcher.py + directive 框架, ~270 行 1 commit)
   - Phase 2 第 1 项 (`profile.update_field` 治死代码, ~250 行 1 commit)
3. **每 Phase 完成 Sir 真测验证再下一 Phase**

---

**doc 总长** ~600 行. Sir 审定 ~30 分钟读完. 改动量大 (~2400 行新增), 但大部分是机械应用同一架构, 不复杂.

**等 Sir 反馈**.

---

# Part 8: 🚨 修订 — 已有 Foundation 发现 (Phase 1 动手时抓到)

我在动手 Phase 1 前 grep 现状, 发现 **2 天前 Sir 已经做过类似 refactor** —
`@d:\Jarvis\jarvis_memory_gateway.py` ([P2-Gap7 / 2026-05-20 23:55]). 此发现**减半 Phase 1 工作量**.

## 8.1 已有 jarvis_memory_gateway.py 现状

| 我 doc Part 1-4 设计的 | gateway 现状 |
|---|---|
| LAYER_REGISTRY 6 层 | ✅ `_detect_target_layer()` ProfileCard / ConcernsLedger / RelationalStateStore / Milestones / CommitmentWatcher / PromiseLog (**跟我 Part 3 设计完全 match**) |
| 统一 mutation schema | ✅ `update_sir_field(field_path, new_value, source, confidence, turn_id, nerve)` |
| mutation_receipts.jsonl | ✅ `_RECEIPT_PATH = memory_pool/mutation_receipts.jsonl` 已在写 |
| SWM publish | ✅ `_publish_swm()` `sir_field_updated` event |
| 单例 + 顶层函数 | ✅ `get_default_gateway()` / `update_sir_field()` |
| recent_receipts / stats 查询 | ✅ |
| `WriteReceipt` dataclass | ✅ |
| `_GLOBAL_NERVE` fallback | ✅ |

## 8.2 未完成 / 半实现 (Phase 1+2 真实缺口)

| 缺口 | 影响 | 行数估 |
|---|---|---|
| **ProfileCard path 走 `apply_correction` → 写 profile_corrections.jsonl 死代码** (line 196-204) | Sir 教正 profile 仍永远不回流 | ~100 |
| **RelationalStateStore / CommitmentWatcher / PromiseLog routing 没实现** (line 241 `else: 'no router for layer'`) | gateway 路由这 3 layer 直接 fail | ~150 |
| **ConcernsLedger 只走 `record_signal` (改 severity)** , 不能改 description/what_i_watch/triggers_proactive | depth update 不可用 | ~80 |
| **没 FAST_CALL `mutation` organ** in chat_bypass.py | **主脑不能 emit FAST_CALL 调 gateway** — 这是 P2-Gap7 留下的最大缺口 | ~180 |
| **没 correction_dispatcher directive** | 主脑不知道何时该 emit mutation | ~120 |
| **没 subject resolver / keyword → ID** | 主脑只能 emit 精确 ID, 不能用 keyword | ~100 |
| **没 docs/JARVIS_MUTATION_INTERFACE.md** 接入协议 | 未来新 source 没标准 | ~150 |

## 8.3 调整后的 Phase 1 范围 (本 commit)

| Sub-step | 内容 | 行 | 状态 |
|---|---|---|---|
| 1.2 | `jarvis_memory_gateway.py` 加 3 layer routing (Relational / CW / PromiseLog) | ~150 | pending |
| 1.3 | ProfileCard path 改: 真覆写 `sir_profile.json` (治死代码) + corrections.jsonl 转 audit | ~100 | pending |
| 1.4 | `chat_bypass.py` 加 FAST_CALL `mutation` organ + subject resolver | ~280 | pending |
| 1.5 | `jarvis_directives.py` 加 `correction_dispatcher` directive | ~120 | pending |
| 1.6 | `docs/JARVIS_MUTATION_INTERFACE.md` 接入协议 | ~150 | pending |

**总: ~800 行 1 commit** (含已有 gateway 修改).

## 8.4 Phase 2 后续 (本 commit 不做)

- `concerns.update` 深度 update (改 what_i_watch / triggers_proactive)
- `attention.adjust` / `screen_vision.annotate` 新 organ
- `[SIR NOW]` 复合 block (Part 2.2 重叠 3 的合并)
- Promise/CW/notes_for_self 三合一 (Part 2.2 重叠 1 的合并)
- ~30 个 testcase
- CLI `scripts/mutation_dump.py` (gateway 已有 recent_receipts API, CLI 可后做)

---

# Part 9: Phase 1 + Phase 2.1/2.6 实施完成进度 (2026-05-22 22:55)

## 9.1 已完成 commit (按时序)

| Commit | Phase | 内容 |
|---|---|---|
| `1cfb021` | 1.1 | docs: 设计 doc (615 行 7 part) |
| `f2bca3b` | 1.2+1.3 | gateway 6-layer routing + ProfileCard.overwrite_field 真覆写 sir_profile.json |
| `5bc67bb` | 1.4+1.5+1.6 | FAST_CALL `mutation` organ + correction_dispatcher directive (priority=10) + JARVIS_MUTATION_INTERFACE.md |
| `d9a02d4` | 1.7 | 19 testcase, 19/19 pass |
| `3e8398d` | 2.1 | ConcernsLedger.update_concern_field 深度 update + gateway 路由 + 7 testcase (26/26 pass) |
| `972d694` | 2.6 | scripts/mutation_dump.py CLI (list/stats/show/count) |

## 9.2 mutation_dump.py CLI 已可用

Sir 真测后立即可:
```powershell
# 看最近 20 条 mutation
python scripts/mutation_dump.py --list

# 看最近 1h
python scripts/mutation_dump.py --list --within 3600

# 按 layer filter
python scripts/mutation_dump.py --list --layer ProfileCard

# 看 stats (by layer / source / fail rate)
python scripts/mutation_dump.py --stats

# 看一条详情
python scripts/mutation_dump.py --show mut_xxxxxxxx
```

## 9.3 Phase 2 待 Sir 拍板项

| 项 | 优先 | 范围 |
|---|---|---|
| `[SIR NOW]` 复合 block (合 6 sensor block) | Medium | -150 净, 大重构 |
| Promise/CW/notes_for_self 三合一 | Low | 重构, 需 Sir 拍板 (改影响多 module) |
| `attention.adjust` / `screen_vision.annotate` | Low | Sir 没说必要, 后做 |

## 9.4 Sir 真测验证清单

Phase 1 + 2.1 + 2.6 上线后, Sir 真测应能体感:

1. **profile 真生效**:
   - Sir 说"我以后默认晚 11 睡" → 主脑 emit `<FAST_CALL>{"organ":"mutation",...}}`
   - `python scripts/mutation_dump.py --list --within 60` 应看 1 条 ProfileCard receipt
   - `cat jarvis_config/sir_profile.json | grep work_rhythms` 应看新值
   - 下轮 Sir 问"我什么时候睡", 主脑 prompt 看的是新版

2. **concerns 深度修正**:
   - Sir 说"睡眠 concern 别这么严肃, 我半夜画图也算工作" → 主脑 emit
     `<FAST_CALL>{"organ":"mutation","command":"update","params":{
       "field_path":"concerns.sir_sleep_streak.what_i_watch",
       "new_value":"...",
       "intent":"refine"
     }}</FAST_CALL>`
   - `python scripts/concerns_dump.py | grep sir_sleep_streak` 应看新 what_i_watch

3. **不打架**:
   - Sir 教正后, 下一轮主脑 retrieve 看的是已修正版, 不会同时显示老 vs 新 (annotation 设计已撤)



