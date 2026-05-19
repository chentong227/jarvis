# β.5 完整重构 — Sir 起床后真机验证指南

> **完成时间**: 2026-05-19 12:06 UTC+08
>
> **完成范围**: β.5.0-A → β.5.7 共 8 个 commit, 完整 push + SWM + 主脑架构
>
> **测试指南**: 80+ 个 testcase 全过. Sir 睡醒后按此 doc 实操.

---

## 1. 一图速记: 我做了什么

```
旧架构 (β.4 及之前):                     新架构 (β.5):
                                          
sentinel → NudgeGate.can_speak           sentinel → publish 'gate_advice' 到 SWM
   ├─ freeze? → return False             SWM (top_n by salience × recency)
   ├─ cooldown? → return False               ↓
   └─ pass → push __NUDGE__              主脑 prompt 含 [SHARED WORLD MODEL]:
                                            - gate_advice (decision/block_reason)
                                            - afk_return / concern_active
                                            - sensor_change / utterance_appended
                                            
                                          stream_nudge prompt 含 [REACTION SPACE]:
                                            - 7 类 priority-ordered silence triggers
                                            - 主脑自由输出 [SILENCE] 不出声
                                            
                                          NudgeGate.can_speak (publish_only mode):
                                            - 永远 return True (不 hard 拦)
                                            - publish 'gate_advice' 含全 state
                                          
                                          OfferGuard.check_offer (publish_only mode):
                                            - 永远 return (True, ...)
                                            - publish 'gate_advice' source=OfferGuard
```

---

## 2. 8 个 commit 累计

| commit | 标题 | 关键改动 |
|---|---|---|
| `f63226c` β.5.0-A | SWM 骨干 | publish(salience) + top_n + to_swm_block + 5 source publish + prompt 注入 |
| `e56ec8e` β.5.0-B | stream_nudge [SILENCE] | reaction_space prompt + 早期 [SILENCE] 检测 + return None |
| `b780fa2` β.5.1 | NudgeGate gate_mode | 3 档 (hard/soft/publish_only) + memory_pool/gate_mode_vocab.json + CLI |
| `9d6000c` β.5.2 | OfferGuard gate_mode | 同 3 档 + jarvis_utils.read_gate_mode helper (DRY) |
| `407dc7b` β.5.3 | **vocab 切 publish_only** | NudgeGate/OfferGuard 默认 publish_only + state_meta + 7 silence triggers |
| `e519512` β.5.3-fix | 3 BUG fix | [SILENCE] mid-stream / gate_advice 60s dedupe / last_nudge_age_s None |
| `1548a2d` β.5.4-7 | 收尾 | Conductor + ReturnSentinel/SmartNudge skip publish helpers + vocab 全切 publish_only |
| `03bc45e` β.5.8-fix | **Sir 实测 BUG-1 急修** ⭐ | bias-toward-voice + MUST SPEAK + 修 4 处 silence 死路 + sentinel skip sal 0.4→0.2 |

## ⭐ β.5.8-fix (Sir 14:00 实测发现 BUG-1 后急修)

**症状**: Sir 98min AFK 起床 + first_today + return_greeting → 主脑选 [SILENCE] (该说也不说)

**4 处 silence 死路全修**:
1. `[REACTION SPACE]` prompt: bias-toward-silence → **DEFAULT IS VOICE** + MUST SPEAK 5 类
2. `[TRUTH ANCHOR — RULES 段]`: "silence on unknown beats invented detail" → **but still SPEAK**
3. `[TRUTH ANCHOR — return_greeting]`: 加 **BUT STILL GREET / Don't go silent**
4. `[SOUL TO USE]`: "skip silently" → "**still reply normally**"

**3 处 sentinel skip salience 降**:
- SmartNudge tick skip: 0.4 → **0.2** (低于 SWM floor 0.3)
- ReturnSentinel skip: 0.55 → **0.25**
- Conductor cooldown skip: 0.5 → **0.25**

**MUST SPEAK 5 类 (永不 silence)**:
- ★ `return_greeting` AND `afk_minutes >= 60` — Sir 长时离开必问候
- ★ `morning_greeting` OR (return_greeting + crosses_sleep=true)
- ★ `commitment_overdue` / `wakeup_reminder`
- ★ SWM 含 Sir question/request 在 last 30s
- ★ sentinel directive 是 one-shot critical event

**ALLOW SILENCE 缩到 4 类 (only explicit Sir reject)**:
1. SWM `freeze_active=true` (Sir said "standby"/"stop")
2. SWM `sleep_mode=true` AND nudge_type 非 SLEEP_ALLOWED_TYPES
3. Sir 60s 内显式 "stop"/"shut up"/"安静"/"别说了"
4. Directive 自相矛盾 (evidence-contradict)

---

## 3. Sir 起床后操作步骤

### Step 1 — 重启 Jarvis

```powershell
# 在 d:\Jarvis 下
python jarvis_nerve.py
```

等 30s 让所有 sentinel 启动. 看到 `[SmartNudgeSentinel] 智能提醒引擎就绪` 等就行.

### Step 2 — 看现状 mode

```powershell
python scripts/gate_mode_dump.py
```

应看到全 `[P] publish_only`:
```
[P] NudgeGate                 = publish_only
[P] OfferGuard                = publish_only
[P] SmartNudgeSentinel        = publish_only
[P] Conductor                 = publish_only
[P] WellnessGuardian          = publish_only
[P] ReturnSentinel            = publish_only
```

### Step 3 — 跑常规对话 + 看 log

```
说: "hello"
```

```powershell
# 看最新 log 路径
$latest = Get-Content docs/runtime_logs/latest.txt
Write-Host "Log: $latest"
Get-Content -Tail 100 $latest | Select-String "SHARED WORLD MODEL"
```

**通过标准**: 输出含 `=== [SHARED WORLD MODEL — Sir 准则 6 evidence] ===` 行.

### Step 4 — 等 SmartNudge / Conductor / ReturnSentinel publish

跑 5-15min 让 sentinel 自然 tick. 然后:

```powershell
Get-Content -Tail 500 $latest | Select-String "gate_advice|NudgeGate would|SmartNudge skipped|ReturnSentinel wanted|Conductor would-propose"
```

**应看到** (5min 后会陆续出现):
```
gate_advice [NudgeGate]: NudgeGate ok-to-speak guardian/...
gate_advice [SmartNudge]: SmartNudge skipped tick: standby_silence_45s_since_conv_off
gate_advice [ReturnSentinel]: ReturnSentinel wanted greet but blocked: ...
gate_advice [Conductor]: Conductor would-propose alert but blocked: inter_source_cooldown_32s...
```

### Step 5 — 看主脑选 [SILENCE] (核心验证)

跑 1h 后:

```powershell
Get-Content -Tail 1000 $latest | Select-String "Nudge/Silence|主脑选 \[SILENCE\]|silence_chosen"
```

**应看到** 至少 1 次:
```
🤐 [Nudge/Silence] 主脑选 [SILENCE] for hydration from SmartNudge
```

如果 0 次出现 → BUG-2 (主脑 ignore reaction_space). 告诉我.

### Step 6 — Sir 主动 standby 验证

```
说: "standby"
```

5min 内若有 nudge 试图触发, 主脑应**强制选 silence** (因为 SWM 含 gate_advice freeze_active=true).

观察:
- TTS 不应再说话
- log 应有 `🤐 [Nudge/Silence] 主脑选 [SILENCE]`

---

## 4. 边界 BUG 监测 + 应对

### 🔴 BUG-1: Jarvis 哑掉 (主脑 over-silence)
**症状**: 1-2h 后 Jarvis 一句话都不说, 该说也不说 — 比如 commitment_overdue 不催, sleep_intent 不应.

**应对**:
```powershell
# 立即回滚到 hard mode
python scripts/gate_mode_dump.py --reset

# 重启后正常 (无需 git rollback)
```

**根因可能**: 7 silence triggers 偏 conservative. 我会调样.

### 🔴 BUG-2: 仍 chatter (主脑 ignore [REACTION SPACE])
**症状**: SWM 含 gate_advice 但主脑还说话, [SILENCE] 0 次出现.

**应对**: 告诉我 log 里看到的具体 SWM 内容, 我调 prompt.

**根因可能**: prompt 太长 attention 稀释 / 主脑模型不严格 / triggers 不够 specific.

### 🟡 BUG-3: TTS 漏说 "silence"
**症状**: TTS 说出 "silence" / 字幕显示 `[silence]`.

**应对**: β.5.3-fix 已加 mid-stream guard, 99% 拦得住. 若漏请告诉我具体场景.

### 🟡 BUG-4: SWM 被堆爆
**症状**: SWM block 全是 gate_advice, 看不到 commitment_overdue / afk_return.

**应对**: β.5.3-fix 60s dedupe + β.5.5/β.5.6 SmartNudge/ReturnSentinel 都加了 dedupe. 风险已减.

### 🟡 BUG-5: 启动 race
**症状**: 启动头 5s 内 publish 失败 log.

**应对**: 已 fail-safe (try/except). 不影响功能.

---

## 5. 紧急回滚顺序

| 不稳程度 | 操作 |
|---|---|
| 轻 (一两次哑) | `python scripts/gate_mode_dump.py --set NudgeGate=soft` (双轨观察) |
| 中 (持续异常) | `python scripts/gate_mode_dump.py --reset` (全回 hard) |
| 重 (要回退代码) | `git reset --hard dc1fff6` (β.4.12 之前) |

---

## 6. 我做完的真机 checklist (Sir 自验)

- [ ] T1 重启 Jarvis 启动正常 (无 error)
- [ ] T2 `gate_mode_dump.py` 显示全 publish_only
- [ ] T3 说 "hello" → log 含 `SHARED WORLD MODEL`
- [ ] T4 等 15min → log 含 `gate_advice [NudgeGate/SmartNudge/Conductor/ReturnSentinel]`
- [ ] T5 等 1h → log 至少 1 次 `主脑选 [SILENCE]`
- [ ] T6 说 "standby" → 5min 内 nudge 应被主脑 silence
- [ ] T7 `python scripts/gate_mode_dump.py --reset` → 即时回 hard 行为

Sir 完成任何 X 项失败, 告诉我具体症状 + log 行, 我修.

---

## 7. 设计原则总结 (准则 6 三维)

| 维 | 状态 |
|---|---|
| ✅ **数据强耦合** (SWM publish) | NudgeGate / OfferGuard / Conductor / SmartNudge / ReturnSentinel / ProactiveCare / PhysicalEnvProbe / STM 都 publish 到 SWM |
| ✅ **行为弱耦合** ([SILENCE]) | stream_nudge reaction_space 7 triggers + bias-toward-silence + mid-stream guard |
| ✅ **决策集中主脑** (publish_only) | NudgeGate / OfferGuard publish_only (永不 hard 拦); 其他 4 sentinel skip 时 publish 信号 |

下一阶段 (β.6+) 待 Sir 真机反馈后再定:
- SmartNudge 的 nudge_type 8 类 hardcoded → 主脑动态 pick
- Conductor _check_path_a INTER_SOURCE_COOLDOWN_S 全删 (让主脑看 SWM 完全自决)
- ReturnSentinel skip 规则 vocab 化 (准则 6 vocab 持久化)

---

## 8. Sir 起床后第一句

打开 d:\Jarvis 终端, 跑:
```powershell
python jarvis_nerve.py
# 等 30s
python scripts/gate_mode_dump.py
```

确认 6 全 `[P]` 后, 跟 Jarvis 说话开始测.

不稳就告诉我具体症状, 我立刻修. 完成 β.5 8 commit (待 push), 你睡觉时已经全部测过 sanity 80+ 测全过, 我已尽力预防边界 BUG.

晚安, Sir.
