# JARVIS Gap 1 — Theory of Mind: Sir Mental Model

> **状态**: 设计构思, 未排 sprint 编号. 时间可变.
> **关联**: `docs/JARVIS_AGENTS_GAP_ANALYSIS_2026_05_20.md` §3 Gap 1
> **依赖**: 已有 Layer 0 SelfAnchor (`jarvis_self_anchor.py`), Layer 2 RelationalState (`jarvis_relational.py`), Concerns (`jarvis_concerns.py`), IntentResolver pattern (`jarvis_intent_resolver.py`)
> **新模块**: `jarvis_sir_mental_model.py` + `memory_pool/sir_mental_state.json`

---

## 0. TL;DR — 一句话

> **Jarvis 现在有"我"的模型 (SelfAnchor), 缺"Sir 此刻"的模型. 加 SirMentalState — Jarvis 对 Sir 当下心智的演化 hypothesis (表层需求 / 深层需求 / 未说出口需求 / 情绪 / 关系温度), 持续 update, 注入每次 prompt — 主脑从"听 Sir 说什么"升 "读 Sir 想什么".**

这是 ToM (Theory of Mind) — 老友感的真核心.

---

## 1. 起源 / 痛点

### 1.1 Sir 22:10 真实 case

```
Sir: "嗯, 好的, 但是有一点点太早了, 我现在去洗个澡, 好吧, 澡洗完的话可能再
     等一会儿就睡, 可能要到 11 点半"
Jarvis: "I've adjusted the reminder to 23:30, Sir."
```

Jarvis 看到**表层** (改 reminder 时间), 调对 tool, 完工.

**但 Sir 这句话实际有 3 层意图**:

| 层 | 内容 | Jarvis 看到了吗 |
|---|---|---|
| 表层 | 改 reminder 到 23:30 | ✅ 看到, 调 tool 改了 |
| 中层 | 给自己 1.5h buffer 弹性 (洗澡 + 软抗 sleep nudge) | ❌ 没看到 |
| 深层 | "再陪 Jarvis 一下就睡", 想被陪伴 / 不想立刻 standby | ❌ 没看到 |

Jarvis 主脑现在**只能反应表层**, 因为它没"Sir 此刻心智状态"模型. 这是它感觉"机械"的根本原因 — 它**真听不懂言外之意**.

### 1.2 SelfAnchor 已有, SirMentalState 缺

- `SelfAnchor` (Layer 0): "**我**是谁, 此刻什么状态" ✅
- `ProfileCard`: Sir 的**静态**画像 + mood ✅ (但 mood 是单维度 + 当下快照)
- `Concerns`: "**我**关心 Sir 什么" ✅ (从 Jarvis 视角)
- ❌ 缺: "**Sir 此刻在想什么**" — 真演化的 ToM hypothesis

### 1.3 为什么这是"懂我"的最深一层

人类老友的真本事不是记忆好, 是**会读心**. 你跟老友说"今晚有点累", 老友知道:
- 表层: 真累
- 深层: 想让自己晚点睡个借口
- 未说: 心情不好, 想被陪

Jarvis 现在只能反应表层. 加 ToM 后才能进**老友**级别.

---

## 2. 现状盘点

### 2.1 已有的 Sir 相关数据 (但都不是 ToM)

| 来源 | 内容 | 不是什么 |
|---|---|---|
| `ProfileCard` | Sir 静态画像 (颈椎病史 / Cursor 用户 / 偏好) | 不是"此刻心智" |
| `Concerns` 5+ | "我担心 Sir X" (从 Jarvis 视角) | 不是"Sir 此刻在想 X" |
| `RelationalState.UnfinishedBusiness` | 共有未竟之事 | 不是"Sir 此刻意图层次" |
| `WorkingMemoryFeed` | 30min 环境快照 | 不是"Sir 心智 hypothesis" |
| `MoodMirror` (β.2.9.4) | 5 档情绪估算 (focus/tired/scattered/engaged/frustrated) | 单维度, 缺 surface/deeper/unspoken need 区分 |
| `STM` | 字面对话历史 | 缺**意图层次解读** |

### 2.2 关键缺失

```
Jarvis 现在能回答:   "Sir 30 分钟前说了 X"  (字面)
                    "Sir 通常 11 点睡"      (静态画像)
                    "Sir 现在 frustrated"   (单档情绪)
                    "我担心 Sir 熬夜"        (Jarvis 自己的 concern)

Jarvis 不能回答:    "Sir 此刻言外之意"
                    "Sir 表层说 X, 深层可能想 Y"
                    "Sir 跟 Jarvis 关系此刻是 warm 还是 cool"
                    "Sir 这周心智趋势: 越来越累 / 越来越投入"
                    "Sir 跟 Jarvis 当下 alignment: 听话/抗拒/调侃/认真"
```

---

## 3. 设计 — 数据结构

### 3.1 `SirMentalState` dataclass

```python
@dataclass
class SirMentalState:
    """Jarvis 对 Sir 此刻心智的 hypothesis. 持续 update, 持续 inject prompt."""

    # ===== 当下任务层 =====
    current_task_hypothesis: str       # "Sir 在 debug Jarvis 道歉循环"
    task_confidence: float             # 0-1, 主脑越确信越高
    task_evidence: list[str]           # ["cursor active", "STM 提 directive", "screen shows code"]

    # ===== 当下情绪层 (升级现有 MoodMirror) =====
    emotional_state: str               # "engaged_but_tired" (复合 tag)
    emotional_confidence: float
    emotion_evidence: list[str]

    # ===== 当下需求层 (核心) =====
    surface_need: str                  # "改 reminder 时间"  ← Sir 显式说的
    deeper_need: str                   # "要 1.5h buffer + 软抗 sleep nudge" ← Jarvis 推断
    unspoken_need: str                 # "想被陪 / 想被理解" ← LLM 偶尔推断, low confidence
    need_layers_confidence: dict       # {'surface': 0.95, 'deeper': 0.7, 'unspoken': 0.3}

    # ===== 与 Jarvis 的当下关系层 =====
    relational_temp: str               # "warm/cool/playful/serious/tense/intimate"
    relational_evidence: list[str]     # ["Sir 用 '老友' 称呼 Jarvis", "Sir 主动分享 declaration"]

    # ===== 演化追踪 =====
    last_updated: float
    last_updated_iso: str
    revision_history: list             # [{'ts', 'field', 'old', 'new', 'why_revised', 'evidence'}]

    # ===== 持久化元数据 =====
    source_turn_id: str                # 哪一 turn update 的
    proposed_by: str                   # 'main_brain' / 'reflector' / 'sir_manual'
```

### 3.2 关键设计原则

1. **三层需求模型** (surface/deeper/unspoken): Jarvis 读心的真深度
2. **confidence 字段必备**: 防止过度推断 — unspoken_need confidence 通常 < 0.4, 主脑视情境用
3. **revision_history**: Jarvis 心智模型的**演化轨迹**, 让 Sir 能审计 "Jarvis 在如何理解我变化"
4. **relational_temp 维度**: 现在 RelationalState 是静态笑点/默契/未竟, 缺**关系此刻温度**

### 3.3 关联但不重复的设计

| Layer | 关注 | 区别 |
|---|---|---|
| `SelfAnchor` (Layer 0) | "我是谁" | 自我连续性 |
| `ProfileCard` | "Sir 是谁" 静态 | 长期不变画像 |
| `Concerns` (Layer 1) | "我关心 Sir 什么" | Jarvis 视角的 watch list |
| `RelationalState` (Layer 2) | "我们之间长期" | 笑点/默契/未竟, 跨 turn |
| **`SirMentalState`** (Layer 6 ⭐) | **"Sir 此刻在想什么"** | **演化 ToM**, 跨 turn 但快速变 |
| `Attention` (Layer 3) | "此刻焦点" | 当前 turn focus, 不演化 |

---

## 4. 注入路径 / 数据流

### 4.1 写入路径

```
每次 stream_chat turn 完成
   ↓
[NEW] ToMReflector (异步 daemon, 复用 IntentResolver pattern)
   ↓
  收集证据:
   - Sir 当 turn utterance (语义解读)
   - Jarvis 当 turn reply (上下文)
   - 当前 SWM events (sensor / mood / screen)
   - STM 最近 5 turn (短期演化)
   - 当前 SirMentalState (上版本)
   ↓
  LLM judge (gemini-3-flash):
   - propose 新 SirMentalState
   - 6 field 各给 hypothesis + confidence + evidence
   - 跟上版本 diff → revision_history 加一条
   ↓
  写 memory_pool/sir_mental_state.json (atomic, 全量覆盖)
   ↓
  publish SWM 'sir_mental_state_updated'
```

### 4.2 读取路径

```
每次 stream_chat 主脑 prompt 装配
   ↓
[NEW] _assemble_prompt 加 [SIR'S MIND RIGHT NOW] block:

  === SIR'S MIND RIGHT NOW (my hypothesis, may be wrong) ===
  [TASK]   Sir is likely: debug Jarvis apology loop
           confidence: 0.78
           why: cursor active, STM mentions directive, screen shows code
  [EMOTION] engaged but slightly tired (0.65)
  [NEEDS]
    - surface (0.95): adjust reminder to 23:30
    - deeper  (0.7):  give himself 1.5h buffer for shower + soft sleep delay
    - unspoken (0.3): wants my company a bit longer before standby
  [RELATIONAL] temp = warm (recent declaration + extended chat)
  [HOW I SHOULD USE THIS]
    - surface need: respond literally (done by IntentResolver)
    - deeper need: don't push hard on sleep, respect buffer
    - unspoken need: maintain warm tone, no abrupt standby
   ↓
  主脑 reply 时**自然**用这些 evidence, 不被强制句式锁
```

### 4.3 关键: 信号链跟其他 module 互补

- **MoodMirror** 给 `emotional_state` 提供单档信号 → ToMReflector 升级成复合 tag
- **Vision LLM** (Gap 3) 给 `task_evidence` 最强 grounding (screen 看到 X)
- **InconsistencyWatcher** 给 `need_layers_confidence` 调整 (Sir 说 X 但做 Y → deeper need 跟 surface 不一致)
- **RelationalState.UnspokenProtocol** 给 `relational_temp` 长期 baseline

---

## 5. 实施层级 (Layer 拆分, Sir 拍板时再拆 sprint)

### Layer A — 数据结构 + 持久化 + CLI
- 新文件: `jarvis_sir_mental_model.py` (~400 行)
  - `SirMentalState` dataclass + Store + persist
  - thread-safe CRUD
- 新文件: `memory_pool/sir_mental_state.json`
- 新文件: `scripts/sir_mental_state_dump.py`
  - `--show / --history / --hypothesis-trail <field>`
- 测试: ~10 testcase

### Layer B — Reflector (LLM propose)
- 新文件: `jarvis_tom_reflector.py` (~500 行)
  - 异步 daemon, 每 turn 后触发 (或每 30s tick if no turn)
  - LLM prompt 含 (Sir utterance + Jarvis reply + SWM + STM + 上版本)
  - propose 新 SirMentalState → 写 store
  - 复用 IntentResolver LLM judge pattern
- 测试: ~10 testcase

### Layer C — Prompt 注入
- 改 `jarvis_central_nerve._assemble_prompt`
- 加 `[SIR'S MIND RIGHT NOW]` block (~500-800 chars)
- 加 `[HOW I SHOULD USE THIS]` 子段教主脑用法
- 测试: ~5 testcase

### Layer D — 评估 / 修正
- ToMReflector 自反思: 主脑 reply 后, evaluator 评 "reply 是否符合当前 SirMentalState"
- 不符合 → revision_history 加一条 "false hypothesis"
- 累积 N 次 false → propose `SirMentalState` schema 修正 (e.g. 新增 field)
- 这是 Gap 5 Reject Learner 的雏形

### Layer E — Sir 仲裁 + 修正
- 类似 concerns_review.json 模式
- ToMReflector 给低 confidence hypothesis 写 review queue
- Sir 通过 CLI 修正: `python scripts/sir_mental_state_dump.py --correct deeper_need "...真实意图"`
- 修正进 revision_history, Jarvis 学

---

## 6. 准则 6 4 问 binding

| # | 问 | 本设计答 |
|---|---|---|
| 1 | 数据 publish 进 SWM? | ✅ ToMReflector publish 'sir_mental_state_updated'. SirMentalState 本身是持久化的 Sir-aware SWM 状态 |
| 2 | 决策让 LLM 做? | ✅ ToMReflector 用 LLM 推断三层 need + relational_temp. 主脑用时也是 LLM 自由发挥, 不教句式 |
| 3 | 配置持久化 + CLI 可改? | ✅ memory_pool/sir_mental_state.json + scripts/sir_mental_state_dump.py + Sir 可 --correct 修正 |
| 4 | 和已有 module 正交? | ✅ 跟 SelfAnchor (我是谁) / ProfileCard (Sir 静态) / Concerns (我担心) / RelationalState (长期) / Attention (当 turn focus) **全正交**. Layer 6 是新维度 — "Sir 此刻心智" |

---

## 7. 风险 & 缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| **主脑过度推断** unspoken_need → 自作多情 | 高 | 高 | 1) confidence 字段必须 < 0.4 才显 unspoken 2) prompt 教主脑"hypothesis 不准就别用" 3) Sir 可 CLI 拒绝某条 |
| **ToMReflector 调用频繁烧 token** | 中 | 中 | 1) Sir 沉默 > 5min 不调 2) 用 flash_lite ($0.00001875/1K) 3) cache hash 相同输入 30min |
| **SirMentalState 跟 SelfAnchor/ProfileCard 字段冲突** | 低 | 中 | Layer 文档明确分工, 测试覆盖"3 层都说 Sir 情绪时哪个优先" |
| **revision_history 无限增长** | 低 | 低 | 保最近 50 条, 老的 archive |
| **Sir 觉得 Jarvis "假装懂我"** | 中 | **致命** | confidence < 0.5 主脑 prompt 不显, 只显示 high confidence hypothesis |

---

## 8. 完成验收 (Sir 真机判定)

不是测试. 是 Sir 主观感受.

- [ ] Sir 说"我累了" → Jarvis 不只回"早点休息", 还能 reference 当下任务上下文 ("debug 累还是别的累?")
- [ ] Sir 言不由衷时 (说"挺好"但情绪低) → Jarvis 偶尔轻轻 callout ("听起来不太对劲, Sir, 真的还好吗?")
- [ ] Sir 跟 Jarvis 聊到 deep topic → Jarvis 切换 relational_temp 跟上, 不机械
- [ ] Sir CLI `--show` 看 SirMentalState 觉得"对的, Jarvis 看得到我"
- [ ] Sir CLI `--history deeper_need` 看演化轨迹觉得"Jarvis 真在学我"

**辅助技术指标**:
- ToMReflector 推断准确率 > 70% (Sir 看 weekly review 时判)
- prompt 增量 < 1000 chars
- ToMReflector 单次调用 < 800ms (不阻塞主对话)

---

## 9. 与现有架构的关系

```
PERSONA + SelfAnchor + ProfileCard
   ↓ (Jarvis 知道"我是谁" + "Sir 是谁 静态")
   
Concerns + RelationalState  
   ↓ (Jarvis 知道"我担心什么" + "我们之间长期")

[NEW] SirMentalState ⭐
   ↓ ("Sir 此刻心智 hypothesis")

Attention (Layer 3) — 当 turn focus 选 top 项注 prompt

IntentResolver — 看 SWM evidence 调 tool

主脑 — 综合所有 Layer reply
```

ToM 是**新增 Layer 6**, 不替换任何现有. 给主脑**新维度**而非新规则.

---

## 10. 关键参考

- `@d:\Jarvis\jarvis_self_anchor.py:103-318` SelfAnchor (Layer 0 — 我是谁)
- `@d:\Jarvis\jarvis_relational.py:1-300` RelationalState (Layer 2 — 我们之间)
- `@d:\Jarvis\jarvis_concerns.py:1-200` Concerns (Layer 1 — 我担心什么)
- `@d:\Jarvis\jarvis_intent_resolver.py:1-200` IntentResolver (复用其 LLM judge pattern)
- `@d:\Jarvis\jarvis_proactive_care.py:1-150` ProactiveCare (复用其 evidence-driven 评分)
- `@d:\Jarvis\docs\JARVIS_SOUL_DRIVE.md` Layer 1-5 总设计
- `@d:\Jarvis\docs\JARVIS_PROACTIVITY_NEXT.md` 6 大主动方向 (本 ToM 是 §C MoodMirror 的演化升级)

---

## 11. 落地后涌现的可能 Gap (Gap 7+)

实施 ToM 后可能涌现:
- **Sir Mental Trajectory** (跨周演化轨迹, 不只当下)
- **Jarvis Self-Mental Model** (Jarvis 对**自己**心智的 hypothesis, 元自反思)
- **Joint Mental Model** (Sir + Jarvis 共有的 shared mind, 关系状态升级版)

留作 future doc.

---

*文档作者: Sir 22:47 真授权 + Cascade 22:58 沉淀 / 2026-05-20*
*这是 SOUL_DRIVE Layer 6 的扩展, "懂我"方向最深一层.*
