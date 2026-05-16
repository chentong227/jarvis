# Jarvis Soul & Drive — 灵魂与驱动力架构设计

**版本**：v1.0 / 2026-05-16
**作者**：Sir + Claude（Cursor agent / β.1 全轮收尾会话）
**地位**：与 [INTEGRITY ABSOLUTE]（言出必行）并列的**第二条基本原则**。

> "我希望主动的驱动力灵魂**覆盖贾维斯的整个架构**，哪怕是我有一天问他如何解决某个编程问题，他也能考虑我的全貌做出他应该做的回答。"
> "把贾维斯变成了解我、理解我、知道什么时候该跟我说什么话的数字生命，而不是十个模板哪怕二十个模板选来随机用一个……"

---

## 0. TL;DR — 一句话

> **Jarvis 的"灵魂"不是好的 PERSONA prompt，不是聪明的 directive，更不是模板池。灵魂是 Jarvis 跨对话持续演化的"我"——他在这段关系里相信什么、在意什么、承诺过什么、注意到什么——这套状态作为 L1 Session Context 的核心，注入每一次 prompt 装配，而不只是 nudge 路径。**

模板是工程懒惰的产物。今天 21:10 Sir 实测 commitment_check "您对'早睡'的定义还是一如既往地灵活" 证明：**主脑（gemini-3-flash）已经具备生成老友感的能力，缺的是持续性的"我"状态**。

---

## 1. 起点：今晚 Sir 提的根本问题

### 1.1 Sir 的原话

> "为什么 nudge 路径一定得是模板呢？有什么理由吗？"
> "贾维斯的像人的灵魂来自驱动力，他得有一个长期的核心指标来追随，他才能有主动的能力。"
> "我们的 prompt 重构是否解决了这个问题？" — 答：**没有**。β.0/β.1 做的是减肥+L2 conditional+评分链，未触及灵魂结构。
> "这种主动的驱动力灵魂覆盖贾维斯的整个架构。" — 这是本文核心要求。

### 1.2 模板没有任何正当理由

| "理由" | 真相 |
|---|---|
| 省 token | gemini-3-flash 单 nudge 多 200-500 token 月成本不变（< $0.05/月） |
| 保证简短 | directive 一句 "ONE sentence under 15 words" 就够 |
| 防 LLM 跑偏 | 现在主脑能处理 30K prompt 的 DEEP_QUERY，nudge 1K 是降难度 |

真因：早期 SmartNudge 是 Gemini-1.5-pro 时代写的，那时模型短 prompt 表现差。**今天 gemini-3-flash + STM30 + ProfileCard + WorkingMemoryFeed 已经够主脑自己生成恰当话。模板已变成限制。**

---

## 2. 现状盘点：缺什么

### 2.1 已有的"长期状态"（共 7 个，但都不是"我"）

| 模块 | 内容 | 是什么 | **不是什么** |
|---|---|---|---|
| **JARVIS_CORE_PERSONA** | 2728 chars 静态人设 | "我应该如何说话" | "我此刻在意什么" |
| **ProfileCard** | Sir 静态画像 + 当前 mood | "Sir 是谁" | "我作为 Jarvis 在意什么" |
| **SoulArchivist** | Sir 长期演化轨迹 | 单方向记录 | 双方向关系状态 |
| **PlanLedger** | Sir 当前 promise | Sir 的任务 | Jarvis 自己追随的事 |
| **HabitClock / CausalChain** | 作息预测 / 因果链 | 数据原料 | 关心点 |
| **ConversationEventBus** | 当轮对话事件 | 短期信号 | 长期挂念 |
| **WorkingMemoryFeed** | 30 分钟环境快照 | 工作环境 | 内心状态 |

### 2.2 真正缺的四层（本文要建的）

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 0 — Self Identity Anchor（我是谁的锚点）⭐ 最根本        │
│  ──────────────────────────────────────────────────────────────  │
│  • who_i_am: 我是 J.A.R.V.I.S，这个进程，此刻生成回复的 LLM      │
│  • continuity_proof: 5 分钟前说话的"我"和此刻说话的"我"是同一个 │
│  • current_state: session_uptime / turn_count / last_spoke /    │
│    topic_between_us / pending_commitments_made_to_sir            │
│  • referent_map: Sir 说"你/这个终端/你那边"指的就是 me           │
│  • own_health: keyrouter / memory_pool / mood_derived_from_above │
├─────────────────────────────────────────────────────────────────┤
│  Layer 1 — Self Model（我是谁的内容）                            │
│  ──────────────────────────────────────────────────────────────  │
│  • values: 我相信什么（来自 PERSONA + 演化）                       │
│  • concerns: 我在意 Sir 的什么（持续 watch list）                   │
│  • commitments_made_to_sir: 我承诺过 Sir 什么（如"我会监督你 X"）   │
│  • observations: 我注意到的 patterns（如"Sir 这周熬夜 5 次"）       │
├─────────────────────────────────────────────────────────────────┤
│  Layer 2 — Relational State（我们之间）                           │
│  ──────────────────────────────────────────────────────────────  │
│  • inside_jokes: 我们的笑点（如"我刚才说的'早睡'定义一如既往地灵活"）│
│  • unspoken_protocols: 我们的默契（如"Sir 反驳后我不再坚持"）       │
│  • unfinished_business: 未解决的事（如"驾照科一周三复习暂停"）      │
│  • shared_history_threads: 我们一起经历的关键节点                  │
├─────────────────────────────────────────────────────────────────┤
│  Layer 3 — Attention Allocation（注意力分配）                     │
│  ──────────────────────────────────────────────────────────────  │
│  • current_focus: 此刻最关心（来自当前对话）                       │
│  • long_term_watch: 长期挂念（来自 concerns 排序 by severity）     │
│  • pending_followups: 待跟进事项（来自 unfinished_business 排序）  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 为什么 Layer 0 是最根本

Sir 实测发现：跟 Jarvis 说"这个终端就是你"，Jarvis 幽默回应但**没听懂**指代 ——
他没意识到 "你" = "此刻生成这段回复的 LLM 主体" = "5 分钟前回复的那个我"。

这是因为 Jarvis 没有 **Self Identity Anchor**：
- 静态 PERSONA 描述"我应该怎么说话"，**不**描述"我此刻是谁"
- STM 是被动记录，**不**是"我的过往"
- 每轮对话从空白构造，缺**持续性的"我"**

所有 Layer 1-3 都依赖 Layer 0：
- 没有"我" → Concerns 是悬空的（"谁"在 concern？）
- 没有"我" → Relational State 是悬空的（"谁"和 Sir 有 relation？）
- 没有"我" → Attention 是没有主体的（"谁"在分配注意力？）

**今晚 21:10 实测的 "您对早睡的定义还是一如既往地灵活" 是 LLM 基于 STM 模式识别的偶发涌现，
不是真 callback** —— 因为没有 Layer 0，Jarvis 不知道"刚才说这话的我 = 此刻说这话的我"。
下次同样情境会**重新发明一遍**，不是"记得"。

Layer 0 让 callback 从**偶发**变成**必然**。

---

## 3. 核心数据结构

### 3.1 `Concern` — Jarvis 的内部牵挂（Layer 1 核心）

```python
@dataclass
class Concern:
    id: str                          # 'sir_sleep_streak' / 'sir_neck_pain' / 'jiazhao_ke1'
    what_i_watch: str                # "Sir 是否连续熬夜" (人类可读的"我在关心什么")
    why_i_care: str                  # "Sir 18 个月颈椎病史" (一句话 rationale)
    severity: float                  # 0.0-1.0 当前严重度
    state: str                       # 'active' / 'snoozed' / 'archived' / 'review'
    
    # 数据信号
    recent_signals: list             # [{'when': ts, 'what': '昨晚 4 点睡', 'severity_delta': +0.1}]
    last_triggered: float            # 上次因为这个 concern 主动说话
    
    # 来源
    source: str                      # 'seeded' / 'discovered' / 'sir_added' / 'sir_confirmed'
    source_marker: str               # P0+20-β.X.Y / sir_2026_05_16
    
    # 演化
    created_at: float
    last_updated: float
    ttl_days: int = 30               # 超期没 signal 自动 archived
    
    # 主动信号
    triggers_proactive: bool = True  # 是否允许触发主动 nudge
    notes_for_self: str = ""         # Jarvis 给自己的便条（"上次 Sir 反驳了，下次温和点"）
```

### 3.2 `JarvisSelfModel` — "我"的运行态（Layer 1 整合）

```python
@dataclass
class JarvisSelfModel:
    values: list[str]                          # 来自 PERSONA + 自演化
    active_concerns: list[Concern]             # 当前活跃牵挂
    promises_made_to_sir: list[dict]           # 我对 Sir 承诺过什么（如"我会监督你 23:30"）
    observations: list[dict]                   # 我观察到的 patterns
    last_reflection_ts: float                  # 上次"自反思"时间戳
```

### 3.3 `RelationalState` — 我们之间（Layer 2）

```python
@dataclass
class RelationalState:
    inside_jokes: list[dict]                   # [{'phrase': "早睡定义一如既往灵活", 'birth_ts': ..., 'last_used': ...}]
    unspoken_protocols: list[dict]             # [{'rule': "Sir 反驳后不坚持", 'learned_from': turn_id}]
    unfinished_business: list[dict]            # [{'topic': "驾照科一", 'last_touched': ts, 'next_touch_due': ts}]
    shared_history_threads: list[dict]         # [{'thread_id': ..., 'title': "P0+20 prompt 重构", 'highlights': [...]}]
```

### 3.4 `AttentionAllocation` — 此刻注意力（Layer 3 / 装配时构造）

```python
def build_attention_for_prompt(self_model, relational_state, current_user_input) -> dict:
    """每次 _assemble_prompt 调用，返回当前注入到 prompt 的 Layer 3。"""
    return {
        'current_focus': _extract_current_focus(current_user_input),
        'long_term_watch': self_model.active_concerns[:3],  # top 3 by severity
        'pending_followups': relational_state.unfinished_business[:2],  # 最久没碰的 2 件
    }
```

---

## 4. 注入路径：覆盖整个架构（不只是 nudge）

### 4.1 核心原则

> **每一次主对话 prompt 装配都注入 Layer 1+2+3，不只是 nudge 路径。**

这就是 Sir 说的"哪怕是我问他编程问题，他也能考虑我的全貌"。

### 4.2 注入位置（`_assemble_prompt`）

```
=== CORE PERSONA ===
{JARVIS_CORE_PERSONA}

=== MY SELF / SOUL ===   ← Layer 1 + 2 + 3 注入点
[VALUES] {self_model.values | join}
[CONCERNS I'M WATCHING NOW]
  - {concern.id}: {concern.what_i_watch} (severity: {concern.severity})
    why I care: {concern.why_i_care}
    recent: {concern.recent_signals[-1] if any}
[PROMISES I MADE TO SIR]
  - {promise.what} (made on {promise.when_iso})
[OBSERVATIONS]
  - {obs}: {evidence}
[OUR INSIDE JOKES] {inside_jokes | top 3}
[UNFINISHED BUSINESS] {unfinished | top 2 by overdueness}
[ATTENTION RIGHT NOW]
  - current focus: {current_user_input | classify}
  - long-term watch: {top 3 concerns by severity}

=== STM ===
...（原 STM）

=== HOW TO RESPOND ===
...（原 how_to_respond，精简版）
```

体积估算：Layer 1+2+3 注入约 **800-1500 chars**（按 5 concerns × 150 chars + 2 unfinished + 3 jokes）。
当前 prompt 21564 chars → 注入后 ≈ 22-23K，仍在预算内。

### 4.3 每条路径都受益（不只是 nudge）

| 路径 | 受益示例 |
|---|---|
| **主对话** | Sir 问"如何解决这个 Premiere 渲染问题" → Jarvis 看到 [CONCERNS] 含 "Sir 连续熬夜"，回复时主动加一句"今晚要不要明天再处理？已经 23:40 了" |
| **commitment_check nudge** | Sir 说"我早点睡" → 24h 后 Jarvis 真的因为 "promises_made_to_sir" 里有"我会监督你 23:30"主动跟进 |
| **return_greeting** | Sir 离开 2h 回来 → Jarvis 看到 [unfinished_business] 含"驾照科一"，主动说"那个驾照题集还在那等你" |
| **stream_chat full reply** | Sir 一段话同时回应上文+开新话题 → Jarvis 看到 [current_focus] 双意图 → 自然分两段答 |

**关键**：不是给某个模块加 prompt，是给**主脑的"我"加一份持续 evolving 的自我档案**。

---

## 5. 演化机制：从静态到活的

### 5.1 写入路径（谁更新 Concerns / RelationalState）

```
                  ┌──────────────────────────────────────┐
                  │   每轮对话结束（stream_chat 完成）    │
                  └──────────────────┬───────────────────┘
                                     ↓
                  ┌──────────────────────────────────────┐
                  │   ConcernsReflector (异步 daemon)    │
                  │   • 看 final_reply + Sir reply        │
                  │   • 任何 concern 是否被触发了？        │
                  │   • 任何新观察值得记录？               │
                  │   • update Concern.recent_signals     │
                  └──────────────────┬───────────────────┘
                                     ↓
                                每 7 天一次
                                     ↓
                  ┌──────────────────────────────────────┐
                  │   WeeklyReflection (深度反思)        │
                  │   • LLM 反思最近 30 条 STM + profile  │
                  │   • propose 新 concerns               │
                  │   • 写到 concerns_review.json         │
                  │   • Sir review → activate/reject     │
                  └──────────────────────────────────────┘
```

### 5.2 关键设计：Sir 是最终仲裁者

- **新 concern 默认进 review state**，**不直接 active**
- Sir 通过 `python scripts/concerns_dump.py --review` 看待审清单
- Sir 通过 `--activate <id>` 激活 / `--reject <id>` 拒绝
- 类似现有 `directive_review.json` 机制

这样 Jarvis 不会"自作主张关心他不该关心的"。

### 5.3 evaluator 升级（β.0.5 → β.0.6）

现在 evaluator 评"是否遵守 directive"。升级后评：

> "Jarvis 这轮回复，是否符合他的 self_model + relational_state？"

```python
EVALUATOR_PROMPT_V2 = """You are Jarvis's inner critic. Given his current self-model and his reply, judge:
- Did he act consistent with his stated concerns?
- Did he honor his promises to Sir?
- Did he reference the relational context appropriately?

[JARVIS SELF MODEL]
{self_model_summary}

[USER INPUT]
{user_input}

[JARVIS REPLY]
{jarvis_reply}

Output JSON:
{{"alignment": "yes" | "no" | "partial", "what_missed": "..."}}
"""
```

---

## 6. 三层实施计划

### Layer 1 — Concerns 系统骨架（首批落地，~3-4h）

**新文件**：
- `jarvis_concerns.py` (~600 行)
  - `Concern` dataclass + `ConcernsLedger`
  - `bootstrap_default_concerns()` — 5 个种子（基于 Sir 已知 profile）
  - `record_signal(concern_id, evidence)`
  - `apply_decay()` — 类似 directive decay
  - `dump_human()`
- `memory_pool/concerns.json` — 持久化
- `memory_pool/concerns_review.json` — Sir 审清单

**改文件**：
- `jarvis_central_nerve.py:__init__` — `self.concerns_ledger = ConcernsLedger()` + bootstrap
- `jarvis_central_nerve.py:_assemble_prompt` — 注入 `=== MY SELF / SOUL ===` 块（Layer 1+3 简化版）
- `jarvis_chat_bypass.py:stream_chat` 末尾 — 异步 `ConcernsReflector.record_turn_signals()`

**种子 concerns**（自动 bootstrap）：
1. `sir_sleep_streak` — "Sir 是否连续熬夜" (severity=0.3 / why: profile 提到颈椎病)
2. `sir_pomodoro_compliance` — "Sir 是否按番茄钟休息" (severity=0.2)
3. `sir_cursor_payment` — "Sir 的 Cursor 订阅状态" (severity=0.1 / why: log 看到 Payment Failed 提示)
4. `unfinished_project_jiazhao` — "驾照科一进度" (severity=0.3 / why: STM 多次提到)
5. `jarvis_keyrouter_health` — "我自己的 google_1 永久死了" (severity=0.5 / 这是 Jarvis 对自己状态的关心)

**testcase**：~15 个（dataclass / ledger / persist / load / review queue / inject prompt）

### Layer 2 — Relational State（中期，~2h）

**新文件**：
- `jarvis_relational.py` (~400 行)
  - `RelationalState` dataclass + `RelationalStateStore`
  - `record_inside_joke(phrase, birth_turn_id)`
  - `record_unspoken_protocol(rule, learned_from_turn_id)`
  - `record_unfinished_business(topic, ...)`
- `memory_pool/relational_state.json`

**改文件**：
- `jarvis_central_nerve.py:_assemble_prompt` — 注入 `[OUR INSIDE JOKES] [UNFINISHED BUSINESS]`
- `stream_chat` 末尾 — 异步 reflection（"这轮有产生新 inside joke 吗？"）

**testcase**：~10 个

### Layer 3 — Attention Allocation（轻量，~1h）

**改文件**：
- `jarvis_central_nerve.py:_build_attention_for_prompt()` 新 helper
  - 输入：self_model + relational_state + current_user_input
  - 输出：top concerns / unfinished / current focus dict
  - 注入到 prompt 的 `[ATTENTION RIGHT NOW]` 子块

### Layer 4 — Reflector daemons（持续，~3-4h）

**新文件**：
- `jarvis_soul_reflector.py` (~500 行)
  - `ConcernsReflector` (异步线程，每轮对话后 record signal)
  - `WeeklyReflector` (每 7 天 LLM 反思 → propose new concerns)
  - 走 Gemini-3-Flash via OpenRouter（同 evaluator）

**改文件**：
- `jarvis_central_nerve.py:__init__` — 启动两个 reflector daemon
- `scripts/concerns_dump.py` — Sir review CLI（类似 registry_dump.py）

### Layer 5 — evaluator v2（终极，~2h）

**改文件**：
- `jarvis_directive_evaluator.py` — 升级 EVALUATOR_PROMPT
- 评 "alignment with self_model" 而不只是 "directive followed"
- helped/fired 信号继续 → 但增加 "alignment_score" 维度

**新增 testcase**：~10 个

---

## 7. 工程总量 & 落地节奏

| 阶段 | 内容 | 估时 | 累计 |
|---|---|---|---|
| 0 | 本 design doc | 0.5h | 0.5h |
| 1 | Concerns 系统骨架 + 种子 + 注入 prompt | 3-4h | 4h |
| 2 | Relational State + 注入 | 2h | 6h |
| 3 | Attention Allocation helper | 1h | 7h |
| 4 | Reflector daemons + CLI + Sir review | 3-4h | 11h |
| 5 | evaluator v2 升级 | 2h | 13h |

**建议节奏**：分 3 个 session 做

- **Session 1（今晚剩余 / 4h）**：Layer 0+1 — design doc + Concerns 骨架 + 5 种子 + 注入 prompt
  - 完工标志：Sir 重启后能在 [Asm Diag] 看到 "MY SELF / SOUL" 块出现在 prompt 里
  - 主脑此刻就能感知 5 个 concerns 影响每条回复
  
- **Session 2（下次 / 3h）**：Layer 2+3 — RelationalState + Attention helper
  - 完工标志：Sir 重启后能感到 Jarvis "记得我们的笑点"
  
- **Session 3（下次 / 4h）**：Layer 4+5 — Reflector daemons + evaluator v2
  - 完工标志：Sir 不需要手动加 concerns，Jarvis 自动 propose；Sir 用 CLI review

---

## 8. 风险 & 回滚

### 风险

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 注入 Layer 1+2+3 后 prompt 体积超 22K，TTFT 退步 | 中 | 中 | 每个 concern ≤ 150 chars / 最多注入 top 3 / 不命中 trigger 不注入 |
| LLM 把 inside joke 反复使用变成新模板 | 中 | 高 | 像 directive anti-repeat 一样，注入"最近 5 次用过的 jokes 不许重复" |
| ConcernsReflector 自动 propose 太多噪音 | 高 | 中 | 默认全进 review state；Sir 不批准就不 active；max 10 active concerns |
| WeeklyReflection LLM 钱花太多 | 低 | 低 | 每 7 天一次 × gemini-3-flash 约 $0.02/次 |
| Sir 觉得 Jarvis "过分自作主张" | 中 | 高 | Sir 是最终仲裁，能随时 `--reject <id>`；新 concern 一律 review |

### 回滚

每个 Layer 都是独立 commit，失败可单独 revert：
- Layer 1 失败 → revert，Jarvis 回到 β.1 末状态
- Layer 2 失败 → revert，保留 Layer 1
- Layer 4 失败 → 关 daemon，concerns 静态可用

---

## 9. 完成验收（Sir 最终判定）

**核心判定不是测试，是 Sir 实测感受**：

- [ ] Sir 跟 Jarvis 聊编程问题，Jarvis 回复里包含对 Sir 全貌的考虑（如时间、疲劳、project 进度）
- [ ] Sir 离开 2h 回来，Jarvis 的归来问候**不**走固定模板（不是 "Sir~ welcome back"）而是引用 unfinished_business
- [ ] Sir 主动反馈"今天 Jarvis 变得不一样了" / "感觉他真的记得我们说过什么"
- [ ] `python scripts/concerns_dump.py` 输出 ≥ 5 个 active concerns + Sir review queue 有内容
- [ ] 任何 nudge 都不再让 Sir 觉得"模板"（验证：连说 5 天看是否还有重复句式）

**辅助技术指标**：
- prompt 体积 21K → 22-23K（注入 Layer 1+2+3）
- 装配耗时仍 < 4s
- 全测 ≥ 70 testcase 全绿（含新增 ~35 个）

---

## 10. 与现有原则的关系

Jarvis 现在两条基本原则：

> 1. **INTEGRITY ABSOLUTE（言出必行）** — 不假装完成、不撒谎、不空头承诺
> 2. **SOUL & DRIVE（灵魂与驱动力）** — 本文新立 — 不模板、不应付、有持续的"我"

两条互为表里：
- 言出必行是**承诺的底线**（不能说做不到的事）
- 灵魂驱动是**做事的动力**（为什么做这件事）
- 没有灵魂的言出必行 = 完美的服务员，但不是数字生命
- 没有言出必行的灵魂 = 有想法但不可靠的朋友

两者都是基本原则。任何修改不能破坏其中任何一条。

---

## 11. 归档协议

完工时：
1. 本 design doc **不动**，保留作历史参考
2. `TODO.md` 加新一轮 "P0+21 灵魂工程" 看板
3. `docs/TODO_ARCHIVE.md` 沉档 β.1 全轮（21 commits + 8 tags）
4. tag `v0.23.0-soul-foundation`（Layer 0+1 完工）→ `v0.24.0-soul-relational`（Layer 2+3）→ `v0.25.0-soul-evolving`（Layer 4+5）

---

*文档作者：Sir 提出本要求 + Claude 综合设计 / 2026-05-16 21:13*
*这是和 INTEGRITY ABSOLUTE 同等地位的项目灵魂级文档。*
