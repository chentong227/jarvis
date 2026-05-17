# Jarvis 主动性扩展规划 v1.0

**版本**: 2026-05-18 (β.2.9 规划阶段)
**Sir 起源问题** (00:55):
> "我和他说过去睡觉了, 这会我又启动他了, 他会不会在某个时刻主动说话打趣我一句?
>  '你不是说去睡了吗?' 这种能力也是'人工智能'的好体现."

---

## 0. 已有主动性盘点

| 模块 | 触发方式 | 主动维度 |
|---|---|---|
| `ProactiveCareEngine` (β.2.8) | concern urgency 动态评分 + sensor 派生 signal | concern-driven, 长期关心 |
| `SmartNudgeSentinel` (旧, 8 类硬触发) | 写死 hydration/stretch/late_night 类时段 | 时段-driven, 老路径 |
| `CommitmentWatcher` (含 β.2.8.6 Predicate) | deadline_ts / predicate.evaluate(ctx) | 承诺-driven (Sir + Jarvis 自承诺) |
| `ReturnSentinel` | AFK > 5min 回归 | AFK-driven |
| `Conductor` | 漏斗事件 + scheduling | 调度-driven |
| `ChronosTick` (in `jarvis_sentinels`) | 定时 (邮件 / 日程) | 时钟-driven |
| `ProactiveShield` (frustration) | 多 sensor 加权 (alt-tab / error_visible) | 情绪-driven |
| `WeeklyReflector` (daily β.2.8.13) | 反思推 concern propose | 元-driven |

→ **当前覆盖**: 关心 / 承诺 / AFK / 时段 / 情绪 / 反思

→ **未覆盖**: **承诺一致性反差 / wake 时机 / 跨 session callback / Sir 历史决策追问**

---

## 1. Sir 例子拆解 (00:55 → 01:04 启动)

```
T=00:55  Sir: "我去睡觉了, 拜拜晚安"
         → SleepIntent 检出 → Gatekeeper 注册 commitment "睡觉"
         → 触发 sleep_mode_routine (β.2.9.1 新接通: mute WeChat + dim display)
         → Jarvis: "好的, 晚安" → standby

T=01:04  Sir 重新唤醒 (说 "Jarvis")
         → wake_word_detected → active_conversation=True
         → ... Sir 等 Jarvis 说话, 或自己先说 ...
         
[Sir 期望] Jarvis 自动说: "您不是去睡了吗, Sir? 9 分钟就反悔了?"
[当前]    Jarvis 只回 "Yes, Sir?" 等 Sir 开口
```

→ **缺**: wake 时机 + commitment inconsistency detect + 主动 callback

---

## 2. 主动性扩展 6 大方向

| # | 名称 | 触发 | 设计要点 | 工时 |
|---|---|---|---|---|
| **A** | **Wake-time Callback** (Sir 例子) | Sir wake-word 命中 + 上一轮对话 < 30min + 有 active commitment | 在 wake 入口暴露给主脑: prompt 注入 "Sir 上次 N min 前说 X, 现在重新唤醒了". 主脑自己判断要不要 callback. (不硬编码句式 — 准则 6) | 30min |
| **B** | **Commitment Inconsistency Watcher** | promise 注册后 X min 内行为反差 (e.g. 说 sleep 但 wake / 说 break 但 alt-tab 频繁) | 新 `inconsistency_detector` daemon, fire-and-forget signal 给 ProactiveCare. urgency 高时主动 nudge | 1h |
| **C** | **Mood Mirror** | 多 sensor 综合 (键盘节奏 / 切换频率 / sleep streak / 时段) → 推断 Sir 当下情绪 | 主脑 prompt 加 `[CURRENT MOOD ESTIMATE]`, 主脑自己用 (准则 6) | 45min |
| **D** | **Curiosity Ping** | Sir 长时间一种活动 (1h+ cursor coding) → Jarvis 主动问开放问题 | 不强 — 1-2 天 1 次, 让 Sir 短暂跳出工作模式. e.g. "I notice you've been deep in that file for an hour — what are you trying to crack?" | 45min |
| **E** | **Cross-session Memory Callback** | 跨 session (今天 / 昨天 / 上周) Sir 决策反差 | 比如 Sir 周一说 "周三去刷题", 周三 wake 时 ProactiveCare check 未完成 → 主动提醒 (现有 commitment_check 已部分做, 但跨 session 弱) | 1h |
| **F** | **Self-aware Comeback** (元-主动) | Jarvis 自己 fail 后下次 wake 时主动 acknowledge | e.g. Jarvis 上次 hallucinate (ClaimTracer 标 unverified) → 这次 wake 时 prompt 加 "上次 reply 未被 verify, 留意" | 1h |

---

## 3. **A** 最重要 — 优先实施

Sir 例子直接对应。详细设计:

### 数据流
```
wake_word_detected
  ↓
VoiceListenThread._emit_with_attention
  ↓
[NEW] _build_wake_context_snapshot:
  - last_conversation_end_ts (How long since last chat)
  - last_active_commitments (PromiseLog + CommitmentWatcher 交集)
  - last_sir_utterance (上次 Sir 说的话)
  ↓
text_ready.emit(cmd) → CentralNerve
  ↓
[NEW] _assemble_prompt 加 [WAKE CONTEXT] 段:
  "Sir wake-worded you {N} min ago. He last said: '...'.
   Active commitments at that time: [...]"
  ↓
主脑自由决定要不要 callback (准则 6 不写句式)
```

### 触发条件 (不固定每次都触发, 让主脑选)
- 必要: wake_word 命中且 last_conv_end < 30min
- 加分: 上次有 sleep_intent / commitment / "I shall X" 类承诺
- 弱: 主脑自己看 prompt 决定要不要主动

### 与已有的 return_greeting 区别
- `return_greeting`: AFK > 5min 后回归, ReturnSentinel 主动发 nudge
- **wake-time callback**: 短间隔 wake (< 30min), Sir 主动唤醒 (用 wake_word), Jarvis 在 reply 第一句加 callback

---

## 4. **B - F** 概要 (留 Sir 选优先级)

### B. Commitment Inconsistency Watcher
- 监控: `PromiseLog.pending` 注册后 X min 内 `sensor_snap` 出现反差
- 例: Sir 说 "去睡觉" → 注册 promise → 5min 内 Sir 又活跃 → fire `inconsistency:sir_said_sleep_but_active`
- 给 ProactiveCare 作为 signal, urgency 加成 → 自动主动 nudge

### C. Mood Mirror
- 已有 `ProactiveShield._compute_frustration_score` 是雏形
- 扩到全维度: focus / tired / scattered / engaged / frustrated 五档
- 主脑 prompt 加 `[CURRENT MOOD]: focused (0.78)`, 主脑用调 tone

### D. Curiosity Ping
- 每天 1-2 次 (低频, 不烦)
- 触发: 同一 process > 60min + 无对话
- 主脑生成开放问题 (准则 6: 不固定句式)

### E. Cross-session Callback
- ConcernsLedger 已有持久化, 跨 session 自然延续
- 加 `crossing_event_detector` — 比较今天 STM vs 上周 STM 是否有同主题再现

### F. Self-aware Comeback
- ClaimTracer 已记录 unverified claims
- wake 时检查上次 turn 是否有 unverified → prompt 注入 "你上次 reply 有 N 个未 verify 声明, 留意"
- 主脑可选择性 acknowledge / 自纠错

---

## 5. 实施 Roadmap (β.2.9)

| 阶段 | 内容 | 工时 | 必做 |
|---|---|---|---|
| β.2.9.1 (本) | TODO 3 简单功能 (mute_app + dim_display + sleep_mode_routine) | 40min ✅ done | ✅ |
| **β.2.9.2** | **A. Wake-time Callback** (Sir 例子) | 30min | ⭐ 必 |
| β.2.9.3 | B. Inconsistency Watcher | 1h | 推荐 |
| β.2.9.4 | C. Mood Mirror | 45min | 推荐 |
| β.2.9.5 | D-F. Curiosity / Cross-session / Self-aware | 2-3h | Sir 选 |

---

## 6. 准则一致性 audit (本规划)

| 准则 | 本规划是否合规 |
|---|---|
| 1. 高效 | wake-time callback 在 prompt 注入即可, 不加新 daemon, TTFT 不退步 ✅ |
| 2. 反应迅速 | 数据快照都是已有的, 不阻塞 ✅ |
| 3. 符合人设 | 不教句式, 让主脑自己 callback ✅ |
| 4. 懂我 | 这是"懂我"的核心扩展 ⭐ |
| 5. 言出必行 | inconsistency watcher (B) + 自纠错 (F) 都强化准则 5 ⭐ |
| 6. 拒绝硬编码 | 全部走 "给 context + 主脑判断", 不写句式锁 ⭐ |

→ 6 准则全过 ✅

---

*Sir 看完确认优先级, 我下次开 β.2.9.2 (Wake-time Callback) 起.*
