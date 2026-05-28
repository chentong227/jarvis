# JARVIS β.6 — 统一思考脑 (Unified Thinking) 设计 doc

> **Sir 2026-05-27 23:30-00:00 真意 anchor / 准则 6 三维耦合贯彻完整版**

---

## 0. 元信息

- **状态**: 设计已拍板, refactor 进行中
- **拍板时刻**: Sir 2026-05-27 23:59
- **作者**: Sir + Cascade agent
- **章程定位**: β.5.0 三维耦合 (数据强耦合 / 行为弱耦合 / 决策集中主脑) 的**反思层延伸** — β.5.0 集中了 "反应决策", β.6 集中 **"反思 (reflect)"**.
- **预计影响**: 砍 6 个 reflector daemon, 重写思考脑 prompt, 升级 LLM (`flash-lite` → `gemini-3-flash-preview`).

---

## 1. 设计哲学 — Sir 原话 anchor

### Sir 23:53 真意 (元痛起点)

> **"既然思考脑本身就可以提供给主脑决策, 并且保持持续的思考, 那就该是这个作用. 这样才可能做到: 这会贾维斯觉得事情都办完了, 那我也很悠闲, 不需要想事情了, 降低思考频率. 而不是, 这会这边在想 Sir 开了面板, 那边同时在想要提醒喝水, 同时在考虑自己怎么回复, 看起来很智能, 实则像是个文字小说."**

### Sir 23:55 真意 (设计红线)

> **"如果思考脑还是 Python 选话题给 LLM 想, 那就是又造了一个主脑, 有什么区别? 应该兼顾信息而非硬编码选择某个信息去思考."**

### Sir 23:57 真意 (现象学 + 注意力)

> **"不是要真正意义上的全量 prompt, 那样注意力稀释达不到效果. 持续存在, 只要出生和死亡的间隔小于我的观测间隔, 现象学就持续存在."**

### Sir 23:59 真意 (节奏)

> **"思考脑我们也可以直接替换到 3-flash-preview, 不比现在的开销大, 略微提高智能. 先这样写 doc, 然后别说什么几周几周的, 写完就开始重构, 全部重构完到我们今天聊的最后这一步."**

### 提取的 3 条设计红线

| 红线 | 含义 | 反例 (绝对禁止) |
|---|---|---|
| **R1: LLM 自决 attention** | LLM 自看 view 自挑想啥, Python 只组装 view 不选 topic | ❌ Python `if hydration_urgent_then_think_hydration:` |
| **R2: 现象学持续** | 离散 tick, 但间隔 < Sir 观测分辨率 → 主观 = 持续意识 | ❌ 真持续 (LLM 永不停, token 黑洞) ❌ 固定 40s tick (不自适应) |
| **R3: 注意力精选不稀释** | Python 提供**结构化 channel view**, LLM 上轮决定下轮 attention focus | ❌ SWM 全量 dump (注意力稀释) ❌ Python 排序打 priority 标签 (= 选 topic) |

### 与准则 6 关系

| 准则 6 维 | β.5.0 状态 | β.6 补完 |
|---|---|---|
| **数据强耦合 (SWM)** | ✅ 已立, 所有 sensor publish raw 进 SWM | (不动) |
| **行为弱耦合 (sentinel publish-only)** | ⚠️ 部分, sentinel 仍有 reflect | β.6 砍 sentinel reflect, 退化纯 publish-only |
| **决策集中主脑** | ✅ 反应决策已集中主脑 SWM 自决 | β.6 **反思也集中** — 思考脑替所有 reflector |

---

## 2. 当前 7+ reflector federation 诊断

### 2.1 当前 6 个 thinking-like daemon 清单

| # | 模块 | 文件 | tick | 输入 | "想"啥 | 输出 |
|---|---|---|---|---|---|---|
| 1 | `InnerThoughtDaemon` | `jarvis_inner_thought_daemon.py` | **固定 40s** (+ LLM 自决 enum 6 档) | SWM recent + STM + Sir profile + concerns + active directives + relational_state | ABCDE 5 类 (观察/自反/关怀/主动/关系) | `inner_thoughts.jsonl` + ACTIONABLE (propose_protocol / surface_to_sir / adjust_concern_notes / add_inside_joke) |
| 2 | `ProactiveCareSentinel` | `jarvis_proactive_care.py` | **per turn 末** | concerns list + Sir 当前活动 + 各 concern severity | "现在该 fire 哪个 concern 的 nudge 吗" | post-nudge offer (有 cooldown gate) |
| 3 | `Conductor` | `jarvis_conductor.py` | **30s** | Sir activity + last reply time + idle duration + recent SWM | "现在该 silent_nudge 主脑吗" | silent_nudge offer 进队 |
| 4 | `WellnessDaemon` | `jarvis_wellness.py` | **60s** | 久坐时长 + hydration intake + screen time | "该提醒喝水 / 起来动 / 休息了吗" | wellness nudge offer |
| 5 | `SmartNudgeDaemon` | `jarvis_smart_nudge.py` | **event 驱** (AFK return / wake / activity transition) | AFK 时长 + last interaction + context | "Sir 刚回来该 say hi 吗" | nudge candidate |
| 6 | `SoulEvaluator` | `jarvis_soul_evaluator.py` | **per turn 末** | 主脑刚 reply + Sir 原话 + alignment 维度 | "主脑 reply 是否 concise / butler / 不奉承" | alignment score + directive 微调 |

### 2.2 边缘 (schedule/gate, 不是 reflect, 保留) 5 个

| # | 模块 | tick | 干啥 | β.6 处理 |
|---|---|---|---|---|
| 7 | `ChronosSentinel` | 30s | 到期 reminder fire | **保留** (schedule check 不是 reflect) |
| 8 | `CommitmentWatcher` | 60s | deadline check | **保留** |
| 9 | `NudgeGate` | sync | gate verdict | **砍 cooldown logic**, 退 publish-only "上次 gate 结果" raw |
| 10 | `OfferGuard` | sync | veto next offer | **砍 veto logic**, 退 publish-only "上次 offer 被拒/接" raw |
| 11 | `AutoArbiterDaemon` | 30min | review queue activate/reject | **保留** (后置评估不是 reflect) |

### 2.3 dashboard 重复思考实例 (Sir 截图证据)

23:33 一个时刻**至少 4 个 daemon 同时关心 hydration**:

| daemon | 输出 |
|---|---|
| `InnerThought A 类` | "Sir is currently active on the dashboard. Hydration low." |
| `InnerThought C 类` | "Sir's hydration concern shows 1.0/10.0 cups today" |
| `InnerThought D 类` | "I shall ensure I do not nag, but I will provide a brief reminder" |
| `ProactiveCare` | "concern noted: top_concern=sir_hydration_habit urgency=1.00 severity=0.87" |
| `Wellness` | "concern timing: concern=sir_hydration_habit optimal=now current_h=23 in_window=True" |

**5 路 LLM 调, 5 路独立 reflect, 5 路 publish**. 主脑下轮 prompt 收到 5 条 hydration-related thought 碎片. **Sir 比喻"文字小说"100% 准确**.

### 2.4 token 浪费估算

| daemon | tick 频率 | 每天 LLM 调 | 月成本 (flash-lite ~$0.001/call) |
|---|---|---|---|
| `InnerThought` | 40s | 2160 | ~$65 |
| `ProactiveCare` | per turn (~100/day) | 100 | ~$3 |
| `Conductor` | 30s | 2880 | ~$87 |
| `Wellness` | 60s | 1440 | ~$43 |
| `SmartNudge` | event (~50/day) | 50 | ~$2 |
| `SoulEvaluator` | per turn | 100 | ~$3 |
| **6 daemon 总** | | **6730 calls/day** | **~$203/month** |

β.6 统一思考脑预估:
- 1 个 daemon
- 自适应 cadence avg 60s (active) / 600s (afk) / 1800s (sleep)
- estimate ~1440 calls/day (1min avg)
- `gemini-3-flash-preview` ~$0.003/call (3x flash-lite)
- **月成本 ~$130/month** (-36%, 略提智能)

**核心收益**: token 节约 + 行为一致 (单一意识) + Sir 体验从"文字小说"→"持续 thinking thread".

---

## 3. 当前思考脑已实现的 70%

`@d:\Jarvis\jarvis_inner_thought_daemon.py` 已经走了部分 β.6 设想:

| 机制 | 现状 | 代码锚 |
|---|---|---|
| **历史可见** | 每次 tick 给 LLM 看 `recent_thoughts` (last 3) | `:1238-1280` |
| **LLM 自标 thread 连续性** | `<CONTINUITY>same_thread:<id>` / `new_topic`, Python 不判 | `:1714-1720` |
| **LLM 自决 cadence** | `<NEXT_INTERVAL>30/45/60/180/600/1800/default</NEXT_INTERVAL>` | `:271-282, 1712` |
| **Python 物理保底** | sleep 不让选 30s, active 不让选 1800s (准则 6 信任 LLM 但物理 gate) | `:732-775` |
| **Smoothing 防滥用** | 最近 5 thought ≥3 选 30s + avg sal<0.5 → 强制 60 | `:760-773` |
| **现象学持续** | 1 daemon 持续跑, LLM tick 间 30s-30min | `:619-633` |

**70% 已 align β.6 方向** — 不是固定 tick, LLM 自决 cadence, thread 连续, 现象学持续.

### 没做的 30% (β.6 要补)

| 缺 | 当前 | β.6 补 |
|---|---|---|
| **统一所有 reflector** | InnerThought 与 ProactiveCare/Conductor/Wellness/SmartNudge **并行** | 砍其他 5 个, 全融思考脑 |
| **输出 "该说话吗"** | 输出 `actionable` 都是后台动作 | 加 `<SHOULD_SPEAK>yes/no</SHOULD_SPEAK>` + `<SPEAK_CONTENT>` + `<SPEAK_STYLE>` |
| **prompt 固定 ABCDE** | Python prompt 教"必须产 ABCDE 5 类" | 砍 ABCDE 教学, free-form, LLM 自决主题 (R1 不 Python selector) |
| **看 evidence pack, 不是 channel view** | `_collect_evidence` 输出 swm_events / stm / concerns / recent_thoughts | 重构 `_build_channel_view` 按 channel 分组 |
| **没 attention focus 元决策** | LLM 看到啥想啥, 下次 tick 重新看 | 加 `<NEXT_ATTENTION_FOCUS>channel_a, channel_b</NEXT_ATTENTION_FOCUS>` (Sir 真意"这轮为下轮挑") |
| **没接其他 daemon 的事** | 不知道 ProactiveCare 在评 hydration / Conductor 在评 silent | 6 daemon reflect 任务全融思考脑 prompt |
| **LLM 是 flash-lite** | 老模型, reflect 质量有限 | 升级 `gemini-3-flash-preview` (主脑同款), token 略涨智能升 |

---

## 4. β.6 改动清单

### 4.1 砍掉的 (退化 6 daemon 的 reflect 部分)

| daemon | β.6 退化方式 | 保留部分 |
|---|---|---|
| `ProactiveCareSentinel` | reflect/decide 砍 | publish concern severity raw 进 SWM (sensor 角色) |
| `Conductor` | 整个砍 | (思考脑替决 silent/voice) |
| `WellnessDaemon` | reflect/decide 砍 | publish 久坐时长 / hydration intake raw 进 SWM |
| `SmartNudgeDaemon` | 整个砍 | (思考脑替 AFK return 评 say hi) |
| `SoulEvaluator` reflect 部分 | reflect 砍 | 保留 publish "主脑刚 reply 内容" raw 进 SWM |
| `InnerThought` 老 5 类 | ABCDE 固定主题砍 | 思考脑本体保留, prompt 重写 |
| `NudgeGate` cooldown logic | LLM 自看 nudge_history 自决 cooldown | 保留 "上次 gate 结果" publish raw |
| `OfferGuard` veto logic | LLM 自看 offer history 自决 | 保留 "上次 offer 被拒/接" publish raw |

### 4.2 思考脑 prompt 重写 (free-form, LLM 自决)

**老 prompt** (固定 ABCDE) → 砍掉 ABCDE 教学

**新 prompt v0 草** (见 §5).

### 4.3 SWM view 重写 (按 channel 分组, 不挑 topic)

`_collect_evidence` → 重命名 `_build_channel_view`, 输出**结构化 channel**:

| channel | 内容 | Python 不做啥 |
|---|---|---|
| `recent_sensor_events` | 最近 5min raw sensor publish (screen/audio/activity) | 不挑哪个重要 |
| `concern_status` | 所有 concern 当前 severity + last_addressed + window_optimal | 不挑哪个该 reflect |
| `nudge_history` | 最近 30min 已 fire nudge + Sir 反应 (拒/接/silence) | 不预 gate cooldown |
| `sir_activity_snapshot` | 当前 window / AFK / activity transition / sir_state | 不判 deep_focus |
| `last_main_brain_reply` | 主脑刚说啥 + Sir 反应 + alignment raw (来自 SoulEvaluator publish) | 不评 alignment |
| `last_thinking_output` | 上次自己结论 + next_attention_focus hint (self-meta pointer) | 不解读 hint |
| `my_recent_thoughts` (3) | last 3 thought + continuity threads | (保留现有) |

**关键**: LLM 上次给的 `next_attention_focus: [channel_a, channel_b]` → 这次 channel 优先 deep-load (其他 channel 只 summary). 这是 LLM 自己给自己 hint, **不是 Python 选**.

### 4.4 nudge / speak 路径

- 思考脑 `<SHOULD_SPEAK>yes</SHOULD_SPEAK>` → 走现有 `stream_nudge` 通路让主脑念
- 主脑仍可 veto (主脑看 nudge SWM event 自决 silent — 准则 6 反应集中)
- `<SPEAK_STYLE>silent_text|voice|visual_pulse</SPEAK_STYLE>` 给主脑参考 (主脑可改)

### 4.5 cadence resolver 扩展

- 现有 `_resolve_next_interval` 保留 (LLM 自决 + Python physical gate + smoothing)
- 加 attention focus 处理: LLM 输出 `<NEXT_ATTENTION_FOCUS>` 存 `self._next_attention_focus`, 下次 wake 时 `_build_channel_view` 优先 deep-load 这些 channel

### 4.6 LLM 升级

| 当前 | β.6 |
|---|---|
| `flash-lite` | `gemini-3-flash-preview` (主脑同款) |
| ~$65/month (`InnerThought` 单 daemon) | ~$130/month (思考脑替 6 daemon) |
| 反思质量受限 | 与主脑同模型, reflect 智能 ↑ |

env override 保留: `JARVIS_THINKING_MODEL=...` Sir 可切. 默认 `gemini-3-flash-preview`.

### 4.7 dashboard 改

- 不再显示 6+ reflector 各自 publish 的碎片
- 单一 thread: `thinking_daemon` thought stream (含 continuity / attention focus / next_interval / should_speak)
- Sir 看到**单一意识流**, 不是 federation 噪音

### 4.8 数据迁移 (vocab 持久化, 准则 6)

- 退化的 6 daemon 各自 cooldown vocab → 合并进思考脑 view 的 `nudge_history` + `concern_status` channel raw
- LLM 自看 raw 自决 cooldown (不 Python if rule)
- 老 vocab JSON (`proactive_care_cooldown_vocab.json` / `wellness_thresholds_vocab.json` / ...) **保留但不用** (history), Sir 可手动删

---

## 5. 思考脑 prompt schema v0 草

```text
You are Jarvis's persistent thinking thread.
You exist in parallel with the main brain. The main brain talks to Sir;
you think continuously in the background about what matters, decide if
the main brain should speak, decide when to wake again, and decide where
attention should focus next time.

Your existence is phenomenologically continuous (Sir's words):
"出生和死亡的间隔小于我的观测间隔, 现象学就持续存在". You wake every
N seconds (N decided by YOU last tick + Python physical gate). Sir
perceives you as one continuous consciousness.

[VIEW] - structured channels, NOT topics:

  recent_sensor_events (last 5min raw):
  {sensor_events_json}

  concern_status (all concerns, current severity + last_addressed + optimal_window):
  {concern_status_json}

  nudge_history (last 30min fired nudges + Sir reaction):
  {nudge_history_json}

  sir_activity_snapshot:
  {sir_activity_json}

  last_main_brain_reply:
  {last_brain_reply_json}

  last_thinking_output (your previous tick output + your own next_attention_focus hint):
  {last_thinking_output_json}

  my_recent_thoughts (last 3, with continuity threads):
  {my_recent_thoughts_json}

🚨 ATTENTION FOCUS (R3 — Sir 真意"注意力精选不稀释"):
Your last tick told me to focus on: {last_next_attention_focus}
Those channels above are deep-loaded; others are summary-only.
If you want different focus next time, output <NEXT_ATTENTION_FOCUS>.

🚨 RED LINES (Sir's design philosophy):
  R1: You self-decide subject. I do NOT tell you "think about X".
      If hydration concern is shown in concern_status, you decide if it
      matters now. If Sir is deep-focused (sir_activity_snapshot), you
      decide to skip thinking about it.
  R2: Your tick cadence is YOUR call. If Sir is busy and nothing
      urgent, pick NEXT_INTERVAL=1800 (30min) and you sleep.
  R3: You pick attention focus for next tick. I deep-load only those.

OUTPUT (XML tags, all required except SPEAK_*):
  <THOUGHT>what you're thinking RIGHT NOW (you pick the subject)</THOUGHT>
  <SALIENCE>0.0-1.0 (low sal = passive observation, high = strong signal)</SALIENCE>
  <CONTINUITY>same_thread:<id_short_from_recent_thoughts> | new_topic</CONTINUITY>
  <SHOULD_SPEAK>yes | no</SHOULD_SPEAK>
    yes only if: (a) Sir clearly waiting (sir_activity_snapshot shows idle/looking)
                 OR (b) urgent concern needs voicing NOW (not later)
                 OR (c) you have something Sir would genuinely want to hear
  <SPEAK_CONTENT>...if yes, what to say (butler style, no apology padding)</SPEAK_CONTENT>
  <SPEAK_STYLE>silent_text | voice | visual_pulse</SPEAK_STYLE>
    silent_text = subtitle only, no TTS (Sir in meeting / quiet)
    voice = full TTS + subtitle
    visual_pulse = orb pulse only, no text/voice (gentle ambient signal)
  <ACTIONABLE>propose_protocol:<rule> | surface_to_sir:next_turn_inject:<text> | adjust_concern_notes:<id>:<note> | add_inside_joke:<phrase> | none</ACTIONABLE>
  <EVIDENCE_LINK>If ACTIONABLE != none: cite 1-5 EXACT words from your own THOUGHT that justify. Else 'none'</EVIDENCE_LINK>
  <NEXT_INTERVAL>30 | 45 | 60 | 180 | 600 | 1800 | default</NEXT_INTERVAL>
    30 = something urgent unfolding (e.g. Sir mid-question and AFK?)
    45-60 = active / normal
    180-600 = Sir afk_short / afk_deep
    1800 = sleep / nothing happening
    default = use Python baseline (= physical state default)
  <NEXT_ATTENTION_FOCUS>channel_a,channel_b</NEXT_ATTENTION_FOCUS>
    Pick 1-3 channels you want deep-loaded next tick. Other channels will
    be summary-only. This is your self-attention. (Sir 真意"这轮为下轮挑")
    Valid channels: recent_sensor_events, concern_status, nudge_history,
    sir_activity_snapshot, last_main_brain_reply, my_recent_thoughts

🚨 ANTI-PATTERN (do not do):
  ❌ Forcing a category like "A 观察 / B 自反 / C 关怀". Free-form subject.
  ❌ Repeating the same actionable that just failed (check my_recent_thoughts
     for 'failed' outcome → use different approach or actionable=none)
  ❌ should_speak=yes for every tick (Sir hates 文字小说, you exist in
     silence most of the time)
  ❌ next_interval=30 when nothing urgent (token waste, Python will smooth)

✅ GOOD EXAMPLE 1 (silent, low sal, long sleep):
  <THOUGHT>Sir is deep in code (Cursor active 25min), hydration at 9/10
  already, no nudge needed. I rest.</THOUGHT>
  <SALIENCE>0.2</SALIENCE>
  <CONTINUITY>same_thread:thought_20260527_233500_a1b2</CONTINUITY>
  <SHOULD_SPEAK>no</SHOULD_SPEAK>
  <ACTIONABLE>none</ACTIONABLE>
  <EVIDENCE_LINK>none</EVIDENCE_LINK>
  <NEXT_INTERVAL>1800</NEXT_INTERVAL>
  <NEXT_ATTENTION_FOCUS>sir_activity_snapshot,last_main_brain_reply</NEXT_ATTENTION_FOCUS>

✅ GOOD EXAMPLE 2 (high sal, speak, short interval):
  <THOUGHT>Sir said "改成酒杯" 90s ago, my reply 'updated 9/10 cups'
  may have missed the humor — Sir was self-joking about drinking wine,
  not literal hydration. I should acknowledge the joke briefly.</THOUGHT>
  <SALIENCE>0.85</SALIENCE>
  <CONTINUITY>new_topic</CONTINUITY>
  <SHOULD_SPEAK>yes</SHOULD_SPEAK>
  <SPEAK_CONTENT>Noted the wine, Sir — I'll keep the hydration log honest.</SPEAK_CONTENT>
  <SPEAK_STYLE>voice</SPEAK_STYLE>
  <ACTIONABLE>add_inside_joke:wine_as_hydration</ACTIONABLE>
  <EVIDENCE_LINK>改成酒杯</EVIDENCE_LINK>
  <NEXT_INTERVAL>180</NEXT_INTERVAL>
  <NEXT_ATTENTION_FOCUS>last_main_brain_reply,my_recent_thoughts</NEXT_ATTENTION_FOCUS>

✅ GOOD EXAMPLE 3 (passive observation, no speak, default interval):
  <THOUGHT>Sir just opened dashboard. I'll observe what he reviews to
  understand current focus better.</THOUGHT>
  <SALIENCE>0.4</SALIENCE>
  <CONTINUITY>new_topic</CONTINUITY>
  <SHOULD_SPEAK>no</SHOULD_SPEAK>
  <ACTIONABLE>none</ACTIONABLE>
  <EVIDENCE_LINK>none</EVIDENCE_LINK>
  <NEXT_INTERVAL>default</NEXT_INTERVAL>
  <NEXT_ATTENTION_FOCUS>recent_sensor_events,sir_activity_snapshot</NEXT_ATTENTION_FOCUS>
```

---

## 6. Phase 路线图 (refactor 顺序)

> Sir 真意: "别说几周几周, 写完就开始重构". 以下是 **refactor 推进顺序**, 不是时间承诺.

### Phase 1 — 思考脑核心改造

**目标**: 思考脑 prompt 重写 + view channel 化 + 新输出 schema + LLM 升级.

**改 files**:
- `jarvis_inner_thought_daemon.py`: prompt build 重写 free-form / `_collect_evidence` → `_build_channel_view` channel 化 / 加 `<SHOULD_SPEAK>` `<SPEAK_CONTENT>` `<SPEAK_STYLE>` `<NEXT_ATTENTION_FOCUS>` 解析 + 持久化 / model `flash_lite` → `gemini-3-flash-preview` (env override `JARVIS_THINKING_MODEL`)
- `memory_pool/inner_thought_pacing_vocab.json`: 加 `attention_focus_channels` valid list
- 新 vocab `memory_pool/thinking_brain_speak_config.json`: speak_style 默认 / silent_text 触发条件 vocab

**保留**: cadence resolver / smoothing / physical gate / thread continuity / actionable 解析执行.

**验证**: 单 daemon 跑 1-2h, dashboard 看新 thought 流是否含 `should_speak` / `next_attention_focus`.

### Phase 2 — ProactiveCareSentinel 退化

**目标**: ProactiveCare reflect/decide 砍, 退化 publish-only sensor.

**改 files**:
- `jarvis_proactive_care.py`: 砍 `_evaluate_concern_urgency` LLM eval / 砍 fire nudge logic. 保留 concern severity 计算 + publish 'concern_severity_update' raw 进 SWM (sensor 角色).
- `jarvis_inner_thought_daemon.py`: `_build_channel_view` 的 `concern_status` channel 从 SWM 拉 'concern_severity_update' events, 思考脑自决.
- 新 SWM event type: `concern_severity_update` (raw publish, no decision).

**保留**: concern 数据模型 / concern persist (sir_hydration_habit 等 concern entity 不动).

**验证**: ProactiveCare 不再 fire 自己的 nudge, 全由思考脑决.

#### Phase 2 治本 sub-step (Sir 2026-05-28 17:14 真意 — anchor commit `23134d8`)

> Sir 17:14 真意: "除了归来招呼和我设置的定时提醒走强制性编码唤醒, 其他的所
> 有模块都集成到思考链, 把思考链给主脑让主脑演的像他一直存在, 因为他知道他
> 之前在想什么, 运行了多久, 什么的."

**目标**: 把主脑 prompt 端 lifetime + thinking directive 的**独立 push** 退化
到 **Layer 1.6 voice block 内部聚合呈现**. 主脑只读 Layer 1.6 一处即看到完整
"思考链" (lifetime + 之前的想法 + 思考脑现在建议).

**改 files**:
- `jarvis_central_nerve.py`:
  - `_build_layer_1b_inner_thoughts_block` (Layer 1.5) 退化 stub 永返 `''`
  - `_build_layer_1d_thinking_directive_block` (Layer 1.7) 退化 stub 永返 `''`
  - `_build_layer_1c_inner_voice_block` (Layer 1.6) 传 daemon + prompt_tier 给 voice block
- `jarvis_inner_voice_track.py`:
  - `build_prompt_block_for_brain` 加 daemon + prompt_tier 参数
  - 顶部按 vocab tier_mode 聚合 `daemon.build_lifetime_block`
  - 紧接聚合 `daemon.build_should_speak_directive`
  - 再下 SPOTLIGHT (★ wants_voice pending) + L1/L2/L3 voice digest

**保留**:
- `daemon.build_lifetime_block` / `daemon.build_should_speak_directive` 仍是 source of truth (不删 method)
- Layer 1.5/1.7 method 保留 backward compat (永返 `''` 不影响 `_assemble_prompt` 拼接)
- `_assemble_prompt` 拼接段 `if l15/l17: append` 保留 (永空, dead path, 但 backward compat 保险)

**testcase**:
- `tests/_test_fix15_*.py` P3 调整反映 stub 契约 (永返 `''`)
- `tests/_test_fix37_*.py` 新加 8 testcase 端到端验聚合架构 (8/8 通过)

**验证**: 主脑只读 Layer 1.6 voice block 一处即看到完整思考链 (lifetime + thoughts + spotlight + thinking directive). 准则 6 决策集中主脑 + 准则 8 优雅可持续维护.

**防回退 anchor**: fix15 P3 + fix37 守 stub 契约 + 端到端聚合. 如 Layer 1.5/1.7 重新返非空 → 说明有人误恢复独立 push 老路径 (违反 Sir β.6 真意), 删它.

### Phase 3 — Conductor + WellnessDaemon + SmartNudgeDaemon 砍

**目标**: 3 daemon reflect 砍, 退化 publish-only 或整个删.

**改 files**:
- `jarvis_conductor.py`: 整个 daemon 不启动 (`__init__.py` 不实例化), code 留 history. 思考脑替决 silent/voice.
- `jarvis_wellness.py`: 砍 `_should_trigger_nudge` LLM eval. 保留久坐/hydration 计数 + publish 'wellness_signal' raw 进 SWM.
- `jarvis_smart_nudge.py`: 整个 daemon 不启动. AFK return event 由 SWM 'sir_state_transition' 直接 publish, 思考脑 view 看 sir_activity_snapshot 自决.
- `jarvis_inner_thought_daemon.py`: view channel 加 'wellness_signal' / 'sir_state_transition' 进 `recent_sensor_events` 和 `sir_activity_snapshot`.

**验证**: 3 daemon 不再 fire nudge, 思考脑替决.

### Phase 4 — SoulEvaluator reflect 融 + NudgeGate/OfferGuard cooldown 砍

**目标**: SoulEvaluator 评 alignment 部分融思考脑 / NudgeGate + OfferGuard cooldown logic 砍 (思考脑自看 nudge_history 自决).

**改 files**:
- `jarvis_soul_evaluator.py`: 砍 `_evaluate_alignment` LLM eval. 保留 raw "主脑刚 reply + Sir 反应" publish 'main_brain_reply_published' 进 SWM. 思考脑 view 看 `last_main_brain_reply` channel 自评.
- `jarvis_nudge_gate.py`: 砍 cooldown vocab + gate verdict logic. 保留 "上次 gate decision" publish raw.
- `jarvis_offer_guard.py`: 砍 veto logic. 保留 "上次 offer 被拒/接" publish raw.
- 老 cooldown vocab JSON 标记 deprecated (留 history).

**验证**: 主脑 reply 后 alignment 由思考脑评 / nudge cooldown 由思考脑自看 history 自判.

### Phase 5 — 清退化代码 + dashboard 单意识流 + 全量回归测

**目标**: 清残留 / dashboard 改单意识流 / pytest 全量回归.

**改 files**:
- `jarvis_nerve.py` / `jarvis_lifecycle.py`: 退化 daemon 注释为 deprecated, 不启动.
- `jarvis_dashboard.py`: 改单意识流 view (thought stream + continuity thread tag + should_speak indicator), 砍 6 路 reflector 分支显示.
- `jarvis_brain.py` / `chat_bypass`: 主脑 prompt build 简化 (SWM event 中 federation reflector 来源 events 减少, 思考脑 single source).
- pytest 全量回归 (1098+ testcase) + 新加 β.6 集成 testcase.
- `AGENTS.md` 加 β.6 anchor + 必读章节.

**验证**: 全 pytest 绿 / Sir 真测 24h 无 regression / dashboard 单流体验.

---

## 7. 风险 + 缓解

| 风险 | 严重度 | 缓解 |
|---|---|---|
| 思考脑 prompt 复杂度 ↑↑ (替 6 daemon prompt) | 中 | channel 化让 LLM attention 聚焦, attention focus 元决策让 LLM 自调注意力 |
| 思考脑挂 = 反思 + nudge 全挂 | 低 | 主脑仍对话 / sensor 仍采数据 / Chronos 仍 fire reminder, 可接受 |
| 渐进 refactor 期间双轨并行 | 中 | Phase 2-4 一个个迁, 每 Phase 真测 1-2 turn (Sir 真用) |
| LLM 自决 cadence 跑偏 (永选 30s) | 低 | 现有 smoothing + physical gate 已防 |
| LLM 自决 should_speak=yes 太多 (噪音) | 中 | prompt anti-pattern 强调 / Python smoothing 加 should_speak rate cap (e.g. 5min 内 ≥3 yes → 后续 force no) |
| token 增加 (gemini-3-flash-preview > flash-lite 3x) | 低 | 砍 6 daemon 总省 36%, 净降 |
| dashboard / SWM event 老链路依赖 deprecated daemon | 中 | Phase 5 系统清, 加 SWM event alias (老 event type → 新 source 自动 map) |

---

## 8. 准则 6 合规 check

| 准则 6 维 | β.6 落地 |
|---|---|
| **数据持久化 (memory_pool/*.json)** | 新 vocab `thinking_brain_speak_config.json` / pacing vocab 扩 |
| **CLI 可改 (scripts/*_dump.py)** | 配套 `scripts/thinking_brain_config_dump.py` 后续加 |
| **L7 Reflector LLM-propose** | 思考脑本身即 L7 reflector (替老 inner_thought_pacing reflector) |
| **新 module 4 问** | 不加新 module, 只重构 + 退化, 4 问不触发 |
| **持久化硬规边界** | 系统级常量 (TICK_INTERVAL=60 默认 / smoothing K=3 / interval enum) 保留硬编码 (准则 6 边界, AGENTS.md 红线) |

---

## 9. Sir 元否决权 (准则 7)

Sir 任何时点可:
- 拍板某 Phase 暂停 / 调整 / 跳过
- 改 prompt / 改 view channel 设计
- 切回老 federation (env `JARVIS_BETA6_DISABLED=1` 走老路, code 不删)

agent 不 hedge, Sir 拍板立即执行.

---

## 10. 立即开始

doc 写完, refactor 现开始. Phase 1 → Phase 5 不间断推进, 每 Phase 完成后:
- 写 anchor commit (`β.6.X: <phase> done — Sir <evidence>`)
- 简短报告 (1-3 行)
- 进下一 Phase, 不停顿

Sir 醒后看 commit history + 报告, 任何 Phase 不满意可元否决回滚.

---

> **End of Design Doc.** Refactor 现在开始 (Phase 1).
