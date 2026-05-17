# Jarvis ProactiveCareEngine — 主动关心引擎设计

**版本**: v1.0 / 2026-05-17 (P0+20-β.2.7.9 设计阶段, 实现暂留 P0+20-β.2.8)
**作者**: Sir 提出方向 + Claude 设计
**前置**: `docs/JARVIS_SOUL_DRIVE.md` (L0-L5 灵魂) + `docs/JARVIS_SOUL_UNIVERSALIZATION.md` (灵魂通用化)

> "贾维斯主动关心的事情就该是 nudge，不该写死频率，把算法写优雅效果自然好。
>  这是核心能力不是小项，做大做完善。每次都要等我触发什么才主动，那和被动有什么区别？"
> —— Sir 2026-05-17 19:33

---

## 0. TL;DR

| 维度 | 旧 SmartNudge | 新 ProactiveCareEngine |
|---|---|---|
| 触发依据 | 8 个写死 nudge_type 各自硬阈值 (alt-tab≥12, error_loop≥5min) | 所有 active concerns urgency 综合评分 + L0/L2 修正 |
| 频率限制 | 写死每天 ≤4 次, cooldown=900s | 自适应: 高 urgency 不限, 低 urgency 自衰 |
| 主题选择 | 类型驱动 (offer_help/dormant_project 等) | concern 驱动 + L1 数据 + L2 inside_joke 引用 |
| 学习能力 | 无 (Sir 拒绝下次仍触发) | 拒绝衰减 + 响应加权 + L5 alignment 反馈 |
| 与灵魂层耦合 | 浅 (只在 nudge prompt 里读 SOUL block) | 深 (signal 采集/选材/打分全程读 L0-L5) |
| 文字生成 | nudge_directive 模板 + 主脑 | 同, 但 directive 含"动态 concern 引用素材" |

3 阶段总工时 ~13h。**Phase β-1 必做**, β-2/β-3 看 Sir 反馈决定。

---

## 1. 现状盘点

### 1.1 旧 SmartNudge 真实工作

| 文件 | 类 | 现状 |
|---|---|---|
| `jarvis_smart_nudge.py` | `SmartNudgeSentinel` | daemon, 每 60s tick, 候选 ↓ |
| ↓ 候选 | `hydration / stretch / late_night / atmosphere / dormant_project / offer_help / suggest_break / context_switch_alert` | 8 个固定类型 |
| ↓ 选择 | `_select_best_nudge()` | 按 priority + cooldown 硬阈值 |
| ↓ 发送 | `push_command(__NUDGE__:json)` | 走 `stream_nudge` 路径 |
| `jarvis_enhanced.py` | `ProactiveShield` | β.2.7.3 已加多信号加权 + L0-L5 修正 |
| `jarvis_commitment_watcher.py` | `CommitmentWatcher` | 用户/Jarvis 自承诺定时 nudge (基于 deadline) |
| `jarvis_return_sentinel.py` | `ReturnSentinel` | AFK 归来问候 |
| `jarvis_sentinels.py` | `ChronosTick / SoulArchivist 等` | 各自有特定触发 |

**问题**：5+ daemon 各自独立判断 → 重复触发 / 冷却不联动 / 不读 L1 concerns severity / 没学习。

### 1.2 真实 BUG 复现 (β.2.7.9 修)

| Sir 实测 BUG | 真因 |
|---|---|
| commitment_check nudge "dinner you mentioned at 18:54" 幻觉 | LLM 看 abstract description 脑补 (β.2.7.8 E 修了引用原话) |
| Iron Man homecoming reference 错 fire reminder | Gatekeeper 把闲聊纠正判 future_task (β.2.7.9 P0-A 修) |
| Memory Correction 改 description 但 reminder trigger 留着 | β.2.7.9 P0-B 修 (deactivate trigger) |
| sir_hydration_habit 没机制主动 nudge | **本设计治** (Phase β-1) |
| 8 类硬阈值 / 4次/天上限不灵活 | **本设计治** (Phase β-2) |

---

## 2. 新架构 — 4 模块

```
┌────────────────────────────────────────────────────────────────┐
│                  ProactiveCareEngine (daemon, tick=60s)         │
├────────────────────────────────────────────────────────────────┤
│  CareSignalCollector — 每 tick 计算所有 active concerns urgency │
│        ↓ (concern_id → urgency score 0-1)                      │
│  CareWindowGuard — 判当下能否打扰 (时段/冷却/Sir 拒绝率)        │
│        ↓ (boolean can_speak + adjusted threshold)              │
│  CareSubjectSelector — 选 top urgency concern 当主题 + 找素材   │
│        ↓ ({concern, subject, evidence_snippet})                │
│  CareSpeechSynth — 调 _assemble_prompt(mode='nudge') + 灵魂层  │
│        ↓ (主脑生成自然话, 不走 nudge_directive 8 类模板)        │
│  StreamNudge — 走 chat_bypass.stream_nudge 出声                 │
└────────────────────────────────────────────────────────────────┘
```

### 2.1 CareSignalCollector — urgency 算法

```python
def compute_urgency(concern, now_ts, recent_signals, last_triggered_ts,
                     nudge_fatigue, l0_state) -> float:
    """
    所有因子 0-1, 综合 urgency 0-1
    """
    base = concern.severity                                # L1 0-1
    
    # 1. 信号新鲜度 衰减 (越久没收到信号越冷)
    age_hours = (now_ts - last_signal_ts) / 3600
    recency = math.exp(-age_hours / 24)                    # 24h 半衰
    
    # 2. 信号密度 (最近活跃信号多 → 更紧)
    signal_density = min(1.0, len(recent_signals_24h) / 5) # 5 信号 = 满
    
    # 3. 沉默压力 (越久没主动提 → 该提)
    silence_hours = (now_ts - last_triggered_ts) / 3600
    silence_pressure = min(1.0, silence_hours / 12)        # 12h 满
    
    # 4. 疲劳惩罚 (Sir 最近拒过 → 降权)
    fatigue_penalty = max(0.2, 1.0 - nudge_fatigue * 0.15) # 拒 1 次 -15%
    
    # 5. L0 状态修正 (Sir 主动对话 → 降, Jarvis 不健康 → 降)
    l0_modifier = 1.0
    if l0_state.get('turn_count_recent', 0) >= 10:
        l0_modifier *= 0.85  # Sir 高活跃, 少主动
    if l0_state.get('keyrouter_unhealthy'):
        l0_modifier *= 0.75  # Jarvis 自身有问题, 少干扰
    
    urgency = base * recency * (0.5 + 0.5 * signal_density) \
            * (0.5 + 0.5 * silence_pressure) * fatigue_penalty * l0_modifier
    return min(1.0, urgency)
```

### 2.2 CareWindowGuard — 能否打扰

```python
def can_speak_now(concern, now_ts, l2_state, recent_nudge_history) -> bool:
    # 1. L2 deep_work_silence 协议生效中 → 拒
    if l2_state.deep_work_active(within_minutes=30):
        return False
    # 2. Sir 最近 5 分钟有显式 "勿扰" → 拒
    if recent_nudge_history.last_rejected_within(seconds=300):
        return False
    # 3. 同 concern 最近 30min 已 nudge → 拒
    if concern.last_triggered > now_ts - 1800:
        return False
    # 4. 任何 nudge 最近 5 分钟内 → 拒 (合并节奏)
    if recent_nudge_history.last_any_within(seconds=300):
        return False
    # 5. 时段判断
    hour = time.localtime(now_ts).tm_hour
    if 2 <= hour <= 5:  # 凌晨深睡时段
        # 仅 critical urgency > 0.85 才打扰
        return False  # 默认拒, 上游决定 critical override
    return True
```

### 2.3 CareSubjectSelector — 选主题 + 找素材

```python
def select_top_concern_and_evidence(concerns, l1_ledger, l2_store, stm):
    """
    1. 按 urgency 排序 active concerns
    2. 取 top 1 (or top 2 如果分数接近)
    3. 找 L2 inside_joke 含此 concern keyword → 拿来当幽默引用素材
    4. 找 STM 最近 2h 内 Sir 自己提过此主题的话 → 当原话引用
    """
    scored = [(c, compute_urgency(c, ...)) for c in concerns if c.state == 'active']
    scored.sort(key=lambda x: -x[1])
    top = scored[0]
    
    evidence = {
        'concern': top[0],
        'urgency_score': top[1],
        'inside_joke_ref': l2_store.find_joke_for_topic(top[0].id),  # 可空
        'sir_recent_quote': stm.find_recent_user_quote(top[0].id, max_age_hours=2),
        'last_signal_what': top[0].recent_signals[-1] if top[0].recent_signals else None,
    }
    return evidence
```

### 2.4 CareSpeechSynth — 走灵魂层主脑

```python
def synth_care_speech(evidence, central_nerve):
    """
    替代旧 nudge_directives 8 类硬模板。
    构造一个动态 directive 让主脑用 L0-L5 注入 + evidence 自由生成。
    """
    concern = evidence['concern']
    directive = f"""You are about to make a brief proactive remark to Sir.
This is NOT a scheduled reminder. This is YOU noticing something based on what
you watch over for Sir (his long-term concerns).

[CONCERN YOU'RE TOUCHING ON]
  id: {concern.id}
  what you watch: {concern.what_i_watch}
  why you care: {concern.why_i_care}
  current severity: {concern.severity:.2f}
  
[EVIDENCE FROM RECENT MEMORY]
  - Sir's recent words on this topic: "{evidence['sir_recent_quote'] or '(none)'}"
  - Last signal you logged: "{evidence['last_signal_what'] or '(none)'}"
  - Inside joke you may reference (sparingly): "{evidence['inside_joke_ref'] or '(none)'}"

[ANTI-HALLUCINATION]
- Quote Sir's exact recent words above if relevant. Don't invent specifics.
- If no recent quote, speak in general "I notice you've been..." form.

[STYLE]
- One sentence, ≤ 25 words English + ZH translation.
- Dry, butler, no chatter. Not a notification.
- If irony arises naturally, mild wit. Else direct.
- Reference YOUR watching, not Sir's behavior judgment.
"""
    # 走 stream_nudge mode='nudge' (Phase 1 已接通 Layer 0-3)
    nudge_ctx = {
        'type': 'proactive_care',
        'nudge_directive': directive,
        'concern_id': concern.id,
        'urgency_score': evidence['urgency_score'],
    }
    central_nerve.worker.push_command(f"__NUDGE__:{json.dumps(nudge_ctx)}")
```

---

## 3. 学习反馈循环

```
Sir 响应 → 写 concern.aligned_count++ + nudge_fatigue 衰减
Sir 忽略 (60s 无反应) → 写 missed_count++ + nudge_fatigue +1
Sir 显式拒 ("别催了" / "knock it off") → fatigue +2 + 加入 reject_history
Sir 主动延续话题 → severity +0.05 + reset fatigue

每 7d L4 WeeklyReflector 看 fatigue / aligned 比例 → 提议调整 severity 上下限
```

---

## 4. 实施 5 阶段

| 阶段 | 工时 | 内容 | 必做 |
|---|---|---|---|
| **β-0 修 reminder 误存** | 1h | β.2.7.9 已做 (P0-A, P0-B) | ✅ |
| **β-1 CareSignalCollector + ProactiveCareEngine 框架** | 3h | 新 daemon + urgency 算法 + 集成现有 SmartNudge 并行跑 | ⭐ |
| **β-2 CareWindowGuard + CareSubjectSelector** | 4h | 打扰判断 + 主题素材选 | ⭐ |
| **β-3 CareSpeechSynth 切换** | 2h | 替代 nudge_directives 8 类模板 + 关掉旧 SmartNudge daemon | ⭐ |
| **β-4 学习反馈循环** | 2h | aligned/missed/fatigue + L5 reflection 接入 | 推荐 |
| **β-5 真机 1 周观察** | 1w | Sir 实测 + 数据驱动调参 | 必 |

---

## 5. 与现有架构关系

| 现有组件 | 处置 |
|---|---|
| `SmartNudgeSentinel` | β-3 起 deprecated, β-4 起删 |
| `ProactiveShield` (alt-tab/error) | 改成 CareSignalCollector 的一个 signal source |
| `CommitmentWatcher` | **保留** (deadline 类 reminder 仍走它) |
| `ReturnSentinel` | **保留** (AFK 归来问候是事件触发非 concern) |
| `ChronosTick` | **保留** (定时邮件类不是 concern) |
| `ConcernsReflector` (L4 keyword) | 保留, 给 CareSignalCollector 提供 signal 来源 |
| `WeeklyReflector` (L4 LLM) | 保留, 周反思 fatigue/aligned 数据 |

---

## 6. 真机验证场景

| 场景 | 期望行为 |
|---|---|
| Sir 工作 1h 没喝水 | sir_hydration_habit urgency 升 → 自然 nudge "Sir, the cup has been silent for a while" |
| Sir 连续 30 alt-tab + 凌晨 | sir_pomodoro + sir_sleep_streak 都触发 → 选 sleep_streak 更高 → "Sir, late night battling code again" |
| Sir 明显在 deep work | CareWindowGuard 拒, 即便 urgency 高 |
| Sir 拒 3 次 hydration nudge | fatigue 升, 接下来 24h 几乎不再触发 |
| Sir 主动提到水 | severity +0.05, fatigue 衰减 |
| Sir 凌晨 2:00 还在 | 仅 critical (urgency > 0.85) 才说话 |

---

## 7. 完成验收 (Sir 真机)

- [ ] Sir 工作长时段被自然提醒喝水, 不感冗余
- [ ] Sir 拒绝某 concern 后 24h 内基本不再听到该 concern
- [ ] Sir 长时间无对话也能听到 Jarvis 主动关心 (不像被动机器人)
- [ ] 主动话术不再是模板感, 每次不同 (主脑灵魂注入产话)
- [ ] 不再出现 "Iron Man homecoming reference" 类幻觉式 reminder

---

*文档作者: Sir 提需求 + Claude 综合设计 / 2026-05-17 19:35*
*与 `JARVIS_SOUL_DRIVE.md` / `JARVIS_SOUL_UNIVERSALIZATION.md` 同等地位.*
*下个 Agent 接手按 Phase β-1 起步, 渐进迁移, 不一次性替换避免回归.*
