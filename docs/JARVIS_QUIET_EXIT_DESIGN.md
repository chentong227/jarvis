# JARVIS QUIET-EXIT 智能设计 — 主脑主动退出焦点

> Sir 真意 (2026-05-28 18:25 + 18:42): "贾维斯发现我[不]在和他说话以后, [不能]再
> 持续焦点模式了吧？不然不是又把我说的话录进去了吗？完整设计一下这个智能度呢？"

## 1. Sir 真痛 — log 18:23-18:27 时间线

| 时刻 | 事件 | 系统反应 | Sir 真感受 |
|---|---|---|---|
| 18:23:08 | ReturnSentinel "面试准备等您" | focus mode lock 90s | OK |
| 18:23:25 | Sir 唱歌 "也他出钱..." | 当 reply + 注册 commitment "晚一点再开始面试准备 @ 13:00" | 🔴 误判 |
| 18:23:50 | Sir 唱 "关系也封住了..." | 又回话 | 🔴 又被打扰 |
| 18:25:00 | Sir 明说 "**先退下吧，不是在跟你讲话**" | reaction=quiet_exit 但 **focus 没退** | 🔴 主脑懂但没行动 |
| 18:25:10 | Sir "他在你房间还不能说话" | 又回话 (focus 还在) | 🔴 |
| 18:25:35 | Sir "种就是" | 又回话 | 🔴 |
| 18:26:02 | InnerThought sal=0.82 反思 "I provided an unnecessary clarification..." | **主脑反思已知错** | 但行动权没接通 |
| 18:26:30 | Sir 按 Ctrl+Alt+J StandDown 30min | grace 4s 内 "梯" 1 字 → cancel | 🔴 误取消 |
| 18:27 | Sir 喊 "Stand down" hotword | 强停 | Sir 已经累 |

**根因**: 主脑 LLM 已 emit `reaction=quiet_exit` 信号 (META schema), **但 python 没接** — `_VALID_REACTIONS` 只含 `voice/silent_text/silence`. 主脑智能空转.

## 2. 3 层智能架构 (互不重叠, 准则 6 决策集中主脑)

| 层 | 角色 | 判别者 | 时效 | 准则 6 维度 |
|---|---|---|---|---|
| **L1 Reactive** | 当前 turn 主脑 emit quiet_exit → python 接通 | 主脑 LLM | 立刻 (本 turn) | 数据强耦合 (META→SWM) |
| **L2 Proactive** | 下轮 prompt 主脑看上轮 quiet_exit + audio_tone 主动判别 | 主脑 LLM | 下 turn 起 | 决策集中主脑 (directive 引导) |
| **L3 Sensor** | 唤醒词检测 / 唱歌识别 / 远场过滤 / L7 reflector 自学 vocab | python sensor + L7 reflector | 持续 | 行为弱耦合 + vocab 持久化 |

## 3. L1 Reactive — 本次落地

### 3.1 META schema 扩

`@d:/Jarvis/jarvis_meta_self_check.py` `_VALID_REACTIONS`:

```py
_VALID_REACTIONS = {
    'voice',              # 正常 reply (TTS)
    'silent_text',        # 字幕但不 TTS
    'silence',            # 整 skip
    'quiet_exit',         # ★ 新: Sir 不在跟我说话, 退出 focus + 60s ASR 试探期
    'observant_silence',  # ★ 新: 旁观但保持 focus (Sir 短暂停顿)
}
```

加新字段:

```py
intent_target: str = 'jarvis'
# jarvis / self_muttering / other_person / singing / unknown
# 主脑判别这句 ASR "是对谁说的"
```

### 3.2 chat_bypass parse_meta 后 hook

```py
if meta.reaction == 'quiet_exit':
    # 1. release focus mode lock
    if self.return_sentinel:
        self.return_sentinel.soft_focus_active = False
        self.return_sentinel.soft_focus_until = 0.0
    # 2. voice_thread 60s ASR 试探期
    if self.voice_thread:
        self.voice_thread.quiet_exit_until = time.time() + 60.0
        self.voice_thread.in_active_conversation = False
    # 3. publish SWM event (5 sentinel cooldown signal)
    bus.publish(
        etype='main_brain_quiet_exit',
        description=f"intent_target={meta.intent_target}",
        source='chat_bypass.meta_hook',
        salience=0.75, ttl=60.0,
    )
```

### 3.3 voice_thread 看 quiet_exit_until

```py
# 试探期内: ASR 仍跑, 但不送主脑 (除非 wake word / Sir 主动喊)
if now < self.quiet_exit_until:
    if not _has_wake_word(audio_text):
        bg_log(f"🤫 [QuietExit/Skip] '{audio_text[:40]}' — main brain 已退, "
               f"剩 {self.quiet_exit_until - now:.0f}s 试探期")
        return  # 不送主脑
    else:
        # Sir 主动喊 → 立刻 cancel 试探期, 重新激活
        self.quiet_exit_until = 0.0
        bg_log(f"🎤 [QuietExit/Cancel] wake word → re-engage")
```

### 3.4 5 sentinel 顶部加 quiet_exit gate

```py
# 通用 helper
def _recent_quiet_exit(bus, window_s=60.0):
    events = bus.recent(etype='main_brain_quiet_exit', window_s=window_s)
    return bool(events)

# CommitmentWatcher.add_commitment 顶部 (防唱歌注册 commit):
if _recent_quiet_exit(bus, window_s=10.0):
    bg_log(f"📝 [CW] 🛡️ main_brain quiet_exit ≤ 10s → skip register")
    return

# ProactiveCare.push 顶部:
if _recent_quiet_exit(bus, window_s=30.0):
    return False

# 同理 Conductor / SmartNudge / Wellness
```

## 4. L2 Proactive — 主脑主动判别 directive

`@d:/Jarvis/memory_pool/directive_registry.json` 加 entry:

```json
{
  "id": "audio_target_judgement",
  "purpose": "教主脑看 audio_tone + STM 自决 intent_target, 不被动等 Sir 明说退下",
  "content": "判定当前 ASR 'intent_target' (jarvis/self_muttering/other_person/singing):\n- Sir 直接称呼 'Jarvis/Charles' OR 含明确请求 → jarvis\n- audio_tone='singing' OR ASR 是断续歌词 / 重复短语 / 押韵 → singing\n- Sir 上轮明说 '退下/不是跟你说/别说话' → 后续 N turn 默认 self_muttering 直到 Sir 重 wake\n- 句子短/无完整动词/全语气词 (e.g. '种就是' / '梯') + 无 cue → 倾向 self_muttering\n判 jarvis 才回 voice; 否则 reaction=quiet_exit, intent_target=<...>",
  "tier": "STANDARD"
}
```

## 5. L3 Sensor — 后续 (本次不做)

### 5.1 vocab 持久化 `memory_pool/quiet_exit_signals_vocab.json`

```json
{
  "wake_words": ["jarvis", "charles", "贾维斯", "travis", "jervis"],
  "explicit_dismiss_phrases": [
    "退下", "stand down", "不是跟你说", "别说话", "shh", "嘘"
  ],
  "singing_indicators": ["lyric_repeat_3plus", "断续", "韵脚"],
  "muttering_indicators": ["very_short", "no_finite_verb", "filler_only"]
}
```

### 5.2 L7 Reflector daemon

看 SWM `main_brain_quiet_exit` events + Sir 真按 StandDown / 唤醒词频率, LLM-propose
新 vocab signal "近 24h Sir 自言自语场景, 主脑哪几次没主动 quiet_exit", Sir 拍板入 vocab.

### 5.3 audio classifier (激进, 评估后再做)

audio 流分类器判 "对话 vs 唱歌 vs 远场环境音". 唱歌识别后整 ASR turn 跳过.

## 6. 准则合规 check

| 准则 | 落地 |
|---|---|
| 6 数据持久化 | `main_brain_quiet_exit` SWM event / L3 vocab JSON |
| 6 CLI 可改 | 现 `scripts/directive_meta_dump.py` + L3 `scripts/quiet_exit_vocab_dump.py` |
| 6 LLM 决策 | quiet_exit / intent_target 全主脑 LLM 自决 |
| 6 4 问 | 不加新 module, 改 META schema + 4 处 hook + vocab |
| 7 Sir 元否决 | 任何阶段 Sir 不满意 → env var disable quiet_exit hook |
| 8 优雅 | 5 commit root-cause 治本, 不糖衣 patch |

## 7. testcase 守门 (fix38)

- L1.1: META parser 接受 quiet_exit / observant_silence + intent_target 字段
- L1.2: chat_bypass parse_meta(reaction=quiet_exit) → focus_lock release + SWM publish
- L1.3: voice_thread quiet_exit_until 期内 skip 非 wake word
- L1.4: voice_thread quiet_exit_until 期内 wake word 重激活 + cancel 试探期
- L1.5: CW.add_commitment quiet_exit 10s 内 → skip register
- L1.6: ProactiveCare.push quiet_exit 30s 内 → skip nudge
- L2.1: directive_registry.json 含 audio_target_judgement entry
- Leak.1: ProfileCard apply_correction 不再 print 到 stdout (用 bg_log)

## 8. 防回退 anchor

- fix38 守 quiet_exit 接通 + leak fix
- 如 _VALID_REACTIONS 删 quiet_exit → testcase 红
- 如 chat_bypass 不再 hook → testcase 红
- 如 sentinel gate 被绕 → testcase 红

## 9. Sir 可控开关

- `JARVIS_QUIET_EXIT_DISABLED=1` env var → chat_bypass hook 跳过 (回滚保险)
- `scripts/gate_mode_dump.py` 不影响 quiet_exit (这是 META 路径不是 gate 路径)
- `quiet_exit_until` 60s 默认, 可改 `JARVIS_QUIET_EXIT_WINDOW_S=N`

## 10. 后续路线 (Phase B / C)

- **Phase B**: L2 directive 真测 1 周, 收集主脑判 quiet_exit 准确率
- **Phase C**: L3 audio classifier 评估 (复杂度 vs Sir ROI)
- **Phase D**: L7 reflector daemon 自学 vocab
