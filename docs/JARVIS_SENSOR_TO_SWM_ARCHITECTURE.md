# JARVIS_SENSOR_TO_SWM_ARCHITECTURE.md

> **β.5.37 / 2026-05-20 / Sir 14:39 校正催生**
>
> Sir 真理: "传感器灵敏度修复, 把不是真正我在操作的行为和我操作的行为区分开告诉主脑, 而不是硬编码 sentinel guard."
>
> 本 doc 是 β.5.37 三层架构改造的 design + 规约. 覆盖 sensor (层 1) / sentinel (层 2) / 主脑 directive (层 3) 全链路.

---

## 一. 现状问题 (Sir 14:33 实测 BUG 链做反例)

### 1.1 BUG 表现
- 13:04:50 SleepDetector score=0.63 灰区 → `request_confirmation` set `_pending_confirmation=True`
- Sir 没回应直接去睡 (1.5h)
- 14:32:50 ReturnSentinel `return_greeting` nudge (afk=85min)
- 14:33:17 Sir 起床说 "嗯,哦,而且睡的也不太好,起来之后心脏很疼哎"
- **handle_confirmation_response** 看 pending=True + "嗯" startswith confirm → **误判 confirmed** → enter sleep mode

### 1.2 当前架构反模式

```
Sensor (PhysicalEnvironmentProbe / ASR)
   ↓
Sentinel (SleepDetector / ProactiveShield / SirStruggleVocab)
   ↓ hard decision (keyword match / threshold / state machine)
nerve.action (enter_sleep_mode / emit nudge / focus_lock)
```

**问题**:
1. **传感器没分层**: 屏幕动 / 键盘鼠标真按 / 麦克风真有声音 全混在 `idle_seconds` 里
2. **Sentinel 硬决策**: SleepDetector / ProactiveShield 自己 keyword match + threshold 决定 action, 主脑看不到 evidence
3. **状态没失效**: `_pending_confirmation` 跨 sleep period 1.5h 仍生效, 没有 SWM evidence 给主脑判断 stale

---

## 二. β.5.37 目标架构 (三维耦合 + 准则 6)

```
┌─────────────────────────────────────────────────────────┐
│ 层 1: Sensor (publish only, raw evidence)               │
│   - PhysicalEnvironmentProbe                            │
│     · last_real_input_ts (键盘/鼠标真按)                  │
│     · idle_seconds_real (基于真 input)                   │
│     · cascade_active_pid (IDE / 自动化 ghost source)     │
│     · window_history (已有, 不变)                         │
│   - SleepDetector → sleep_intent_signal (raw score)     │
│   - VoiceListenThread → asr_real_input (Sir 嘴里说话)   │
└─────────────────────────────────────────────────────────┘
                          ↓ publish
┌─────────────────────────────────────────────────────────┐
│ 数据强耦合: ConversationEventBus = SharedWorldModel     │
│   - publish(type, desc, source, salience, metadata)     │
│   - to_swm_block(n=12) 拼 evidence 段给主脑              │
└─────────────────────────────────────────────────────────┘
                          ↓ 主脑 prompt 看
┌─────────────────────────────────────────────────────────┐
│ 层 3: 主脑 LLM (集中决策, 准则 6 第三维)                  │
│   directive (evidence-only, 不 prescribe):              │
│   - sleep_confirmation_judge                            │
│   - ghost_activity_judge                                │
│   - sir_intent_judge                                    │
│   → emit reaction_space tag:                            │
│     <SLEEP_CONFIRM> / <GHOST_ACK> / <SILENT> / ...      │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ 层 2: Sentinel (publish-only + 接收主脑 tag 才 action)  │
│   - SleepDetector.detect → publish 'sleep_intent_signal'│
│     (不再直接 enter sleep mode)                          │
│   - ProactiveShield → publish 'shield_observation'      │
│     (不再硬 trigger shield_alert)                       │
│   - SirStruggleVocab Conductor path → 继续作 publisher  │
│     但 nudge_context 透传给主脑判断                       │
│   - nerve._trigger_sleep_mode() 只被主脑 <SLEEP_CONFIRM> │
│     tag 解析路径调用                                     │
└─────────────────────────────────────────────────────────┘
```

---

## 三. 层 1 详细 (Sensor 新 publish)

### 3.1 PhysicalEnvironmentProbe 新 sensor 字段

| 字段 | 来源 | 含义 |
|---|---|---|
| `last_real_input_ts` | `win32api.GetLastInputInfo()` | Sir 真物理 input (键鼠) Unix ts |
| `idle_seconds_real` | `time.time() - last_real_input_ts` | 真物理 idle 秒 (跟 `idle_seconds` 一致, alias) |
| `cascade_active_pid` | scan window_history 找 Cursor.exe/Windsurf.exe + Sir mute_until window | Cascade IDE 进程 PID, > 0 表示 IDE 在跑 (ghost source) |
| `ghost_activity_ratio` | window_history 切换数 / Sir 真 input 次数 | > 0.5 表示屏幕动多于 Sir 真操作 |

### 3.2 PhysicalEnvironmentProbe publish point

```python
# get_sensor_snapshot() 调用时 (每 30s tick):
if last_real_input_ts != prev and idle_seconds_real > 60:
    bus.publish('sir_afk_detected', 
                f"idle_real={idle_seconds_real}s, last_input @{last_real_input_ts}",
                source='PhysicalEnvProbe',
                salience=0.65,
                metadata={
                    'idle_seconds_real': idle_seconds_real,
                    'last_real_input_ts': last_real_input_ts,
                })

if cascade_active_pid > 0:
    bus.publish('ghost_activity_observed',
                f"Cascade IDE pid={cascade_active_pid}, window 在变但 Sir 真 idle",
                source='PhysicalEnvProbe',
                salience=0.55,
                metadata={'cascade_pid': cascade_active_pid})
```

---

## 四. 层 2 详细 (Sentinel publish-only 改造)

### 4.1 SleepDetector → publish-only

**改造前** (`jarvis_memory_core.py:1057-1300`):
```python
def detect(user_input):
    score = ...
    if score >= 0.70: 
        self.confirm_sleep()  # ← 硬决策
        nerve._trigger_sleep_mode()
    elif score >= 0.50:
        self.request_confirmation()  # ← 设 pending 状态
        # 然后 handle_confirmation_response 硬 keyword match
```

**改造后**:
```python
def detect(user_input):
    score = ...
    # 只 publish, 不 set state
    bus.publish('sleep_intent_signal',
                f"score={score:.2f} kw={breakdown.kw} sem={breakdown.sem}",
                source='SleepDetector',
                salience=min(0.30 + score * 0.65, 0.95),
                metadata={
                    'score': score,
                    'breakdown': breakdown,
                    'user_input': user_input,
                    'detected_at': time.time(),
                })
    # 不再 confirm_sleep / request_confirmation. 主脑看 SWM evidence 自决.
```

**handle_confirmation_response** → **删** (主脑 directive 取代)

**nerve._trigger_sleep_mode**: 保留, 但只被主脑 LLM emit `<SLEEP_CONFIRM>yes</SLEEP_CONFIRM>` tag 解析路径调用.

### 4.2 ProactiveShield → 接收 SWM signal, frustration_score 加权

**改造前**:
```python
def _scan():
    history = window_history
    switches = count(...)
    score = ...
    if score >= TRIGGER: 
        trigger shield_alert
```

**改造后**:
```python
def _scan():
    history = window_history
    switches = count(...)
    
    # 准则 6 evidence: 看真 input vs ghost
    snap = PhysicalEnvProbe.get_sensor_snapshot()
    idle_real = snap.get('idle_seconds_real', 0)
    ghost_pid = snap.get('cascade_active_pid', 0)
    
    # frustration_score breakdown 加新维度
    raw_score = _compute_frustration_score(switches, error_min, snap)
    if idle_real > 30 and ghost_pid > 0:
        # Sir 真离场 + 有 IDE ghost source → switches 不算 frustration
        raw_score *= 0.1  # 平滑降权, 不是 hard skip
    
    # 触不触 alert 仍由 score 决定, 但加 ghost_activity_observed publish
    if raw_score >= TRIGGER_SCORE:
        bus.publish('shield_observation', ...)
        trigger shield_alert (与之前同, 但 score 已合理)
```

注: 此处 `* 0.1` 是 publish 后主脑无法纠正 score, 所以仍 partial 用 sensor evidence 调权. 比 hard skip 灵活. 后续可彻底改 publish-only 但本 commit 先到这.

### 4.3 SirStruggleVocab Conductor path

**改造前** (`jarvis_conductor.py:238-269`):
```python
if voice_thread.last_struggle_at fresh:
    return {'source': 'SirStruggleVocab', 'action': 'Offer Help', ...}
    # ← Conductor 自决发 offer_help nudge
```

**改造后** (本轮架构改造做):
```python
if voice_thread.last_struggle_at fresh:
    # publish struggle signal 让主脑看
    bus.publish('sir_struggle_observed',
                f"phrase={phrase_id} sev={severity} text='{struggle_text[:80]}'",
                source='SirStruggleVocab',
                salience=0.6 + (sev_rank/5),
                metadata={
                    'phrase_id': phrase_id,
                    'severity': severity,
                    'struggle_text': struggle_text,
                    'detected_at': time.time(),
                })
    # 仍 return offer_help nudge_alert (不动 trigger, 因为 Sir 明确说 struggle 必须响应)
    # 但 nudge_context 透传 struggle 全文给主脑 judge "这是真 struggle 还是 dismiss"
    return {...nudge_alert...}
```

注: SirStruggle 路径 **仍触发 nudge**, 但 nudge prompt 把 struggle 全文 + 时间 + sensor 上下文给主脑, 主脑判 "是 struggle 还是 dismiss". 比 sentinel 硬 keyword guard 灵活.

---

## 五. 层 3 详细 (主脑 directive)

### 5.1 sleep_confirmation_judge directive

加到 `central_nerve.py` directive_pool, vocab JSON 持久化 + L7 propose.

**写法 (evidence-only, 不 prescribe)**:
```
[SLEEP CONFIRMATION CONTEXT - β.5.37]
- SWM may show: sleep_intent_signal (score, time)
- SWM may show: sir_afk_detected (idle_real_seconds)
- Sir's current input: <user_text>

If you observe a fresh sleep_intent_signal (< 5 min ago) AND Sir's current input 
clearly confirms (e.g. "yes" / "好" / "对" standalone), you may emit:
  <SLEEP_CONFIRM>yes</SLEEP_CONFIRM>

If Sir's input is ambiguous or unrelated, do NOT emit confirm.

If sleep_intent_signal is stale (> 30 min) OR Sir just returned from afk (sir_afk_detected 
shows long afk), the signal is stale — treat current input as new conversation, not confirmation.
```

### 5.2 ghost_activity_judge directive

```
[GHOST ACTIVITY CONTEXT - β.5.37]
- SWM may show: ghost_activity_observed (cascade_pid, window 切换数)
- SWM may show: sir_afk_detected (idle_real_seconds > 60)

If both are present, screen activity is NOT Sir — do NOT mention Windsurf terminal /
Cursor IDE / coding work in your reply as Sir's activity. Treat as background ghost.

Reference Sir's real_input_ts instead: only events at/after that time are Sir.
```

### 5.3 sir_intent_judge (struggle 判)

```
[STRUGGLE INTENT CONTEXT - β.5.37]
- SWM may show: sir_struggle_observed (phrase, severity, full text)

When responding to offer_help nudge, judge from Sir's struggle_text whether:
(1) Sir actually expressing struggle ("我搞不定", "卡住了") → offer help
(2) Sir using struggle-sounding words but in dismiss / casual context 
    ("我去休息" → not struggle, just leaving)
    ("看不懂这电视剧" → casual comment, not technical struggle)

If (2), respond minimally / acknowledge without offering help.
```

---

## 六. 落地路线 (4 commits)

### β.5.37-A: Sensor 层
- PhysicalEnvironmentProbe 加 `last_real_input_ts` / `idle_seconds_real` / `cascade_active_pid` 字段
- get_sensor_snapshot 返回新字段
- publish `sir_afk_detected` / `ghost_activity_observed` 到 SWM

### β.5.37-B: Sentinel publish-only (SleepDetector)
- SleepDetector.detect publish `sleep_intent_signal`
- handle_confirmation_response 删 (主脑 directive 取代)
- _trigger_sleep_mode 改为只被主脑 `<SLEEP_CONFIRM>` tag 调用

### β.5.37-C: Sentinel publish + 加权 (ProactiveShield + SirStruggle)
- ProactiveShield 用 sensor 加权 frustration_score, publish `shield_observation`
- SirStruggleVocab Conductor path publish `sir_struggle_observed`

### β.5.37-D: 主脑 directive + nerve `<SLEEP_CONFIRM>` 解析
- 3 个 directive 加 directive_pool
- nerve.handle_user_speech 加 `<SLEEP_CONFIRM>` tag 解析
- vocab JSON 持久化

### β.5.37-E: regression test + Sir 真机实测

---

## 七. 反例: 什么是硬编码 (Sir 校正后的红线)

| 反例 | 替代 |
|---|---|
| `_sleep_dismiss_kw = ('休息', '睡觉', ...)` 在 `.py` | vocab JSON + CLI + L7 reflector |
| `if struggle_age <= 15.0: defer` | sentinel publish + 主脑 directive |
| `if idle_seconds > 60: skip` | sensor publish `sir_afk_detected` + ProactiveShield 用 evidence 加权 |
| `confirm_words = ['yes', '嗯', '好', ...]` | 主脑 LLM judge "Sir 这句是 yes/no/neither" |
| `_pending_confirmation = True` 跨进程 state | publish `sleep_intent_signal` + 主脑看 SWM 自决 stale or not |

---

## 八. 验收标准 (Sir 真机)

1. Sir 14:33 起床说 "嗯,哦,而且睡的也不太好..." — 不会被误判 confirm
2. Sir 13:03 说 "我要去休息" — 不会被 expletive vocab "我去" 误命中 → 不触 offer_help
3. Sir 离桌期间 Cascade 跑代码 — ProactiveShield 不触 shield_alert
4. return_greeting nudge 内容 — 主脑看到 SWM ghost_activity_observed → 不说 "Windsurf terminal active"
5. 所有判断逻辑可通过 `Grep -rn "_keyword" *.py` 查不出新硬编码 list
