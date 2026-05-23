# JARVIS 数据流全审 (Phase A.2 of Grand Refactor)

> **目的**: 完整记录 Jarvis 90 模块 + 25 hands 之间的真实数据流. 配合 `JARVIS_AUDIT_CARDS.md` (模块审计) + `JARVIS_ARCHITECTURE_MAP.md` (静态架构) = 完整理解 Jarvis.
>
> 写于 2026-05-23 23:35, Phase A.2 启动. Phase A.1 (140 模块审计) 完成后立即.

---

## 1. 主流程 — Sir 一句话 → reply 完整调用链

```
[Layer 1: 物理感知]
─────────────────────────────────────────────────────────────────
mic 声音 → Whisper/Azure ASR → text
          + AcousticWakeDetector (openWakeWord) 唤醒确认
          + AmbientSensor (笑声/叹气, publish 'ambient_state')
          + PhysicalEnvProbe.tick (键鼠/window, publish 'sensor_change' / 'sir_afk_detected' / etc.)
          + AttentionSlot.capture_now() — 抓拍当下窗口/光标 (utils)
                            ↓
[Layer 2: 派遣]
─────────────────────────────────────────────────────────────────
VoiceListenThread.text_ready signal
                            ↓
JarvisWorkerThread.push_command(cmd) → cmd_queue
                            ↓
JarvisWorkerThread.run() loop:
  ─ TraceContext.new_turn() → turn_<id>
  ─ ScreenVision.async_describe (并发, fire-and-forget Vision LLM)
  ─ Gatekeeper LLM (短 LLM 抽 commitment / cancel / clarify)
        → CommitmentWatcher.add_commitment + publish 'sir_intent_deadline_candidate'
  ─ MemoryCorrectionGuard (Sir 教正语义 + Bayesian)
        → ProfileCard.apply_correction (老路径 audit)
        → MemoryGateway.update_sir_field (新路径 真改 sir_profile.json)
  ─ SleepIntentDetector (Sir 睡眠表态)
  ─ chat_bypass.stream_chat(cmd, context) — 主入口
                            ↓
[Layer 3: prompt 装配]
─────────────────────────────────────────────────────────────────
CentralNerve._assemble_prompt(user_input):
  ─ 30+ render block 顺序 _parts.append (详 §2)
  ─ swm_block = event_bus.to_swm_block(n=12, salience_floor=0.3)
  ─ 总长 ~25K-36K char
                            ↓
[Layer 4: 主脑 LLM stream]
─────────────────────────────────────────────────────────────────
chat_bypass._create_stream(prompt, model, vision_image=screenshot|None)
  ─ KeyRouter.get_key (caller='main_brain', model)
  ─ Gemini-3-Flash / V4-Pro stream
                            ↓
[Layer 5: stream parse + dispatch]
─────────────────────────────────────────────────────────────────
chat_bypass.stream_chat:
  for chunk in stream:
    ─ buffer 追加 chunk_text
    ─ detect <FAST_CALL>...</FAST_CALL>:
        organ='mutation' → MemoryGateway.update_sir_field → 6-layer routing
        organ='memory_hands' → l4_memory_hands.execute (Hippocampus 接口)
        organ='concerns' / 'stand_down' / 'progress' / 'cyclic_task' / etc. → 各 organ
        24 hands organ → l4_*.py.execute(Action)
        + alias resolve (e.g. 'memory' → 'memory_hands')
        + Gatekeeper SWM check (fix82-Z: skip dup add_reminder)
        + soft_timeout 1.5s 异步派
        + tool_result 进 _tool_results
    ─ detect <CONCERN_DAMPEN>... → ConcernsLedger.record_signal (反讽)
    ─ detect <META>... → MetaSelfCheck.parse + audit
    ─ detect ZH split (---ZH---) → translate_queue
    ─ 句子边界 → render_queue (TTS render)
    ─ continuation_prompt 喂回主脑续 stream (主脑看 tool result 自然 ack)
                            ↓
[Layer 6: 后处理 (fire-and-forget)]
─────────────────────────────────────────────────────────────────
chat_bypass.stream_chat 末尾:
  ─ ClaimTracer.extract_claims + verify (调 mutation_receipts / Hippocampus / CW)
  ─ IntegrityWatcher.verify_async (post-stream verify + retry 失败 claim)
  ─ STMSummarizer.summarize_async (reply 长 → 短 LLM 概括)
  ─ ConcernsReflector.reflect_turn (启发式 keyword → severity_delta)
  ─ SoulAlignmentEvaluator.evaluate_async (LLM 评 alignment)
  ─ DirectiveEvaluator.eval_async (评 directive helped/fired)
  ─ Hippocampus.seal_memory_async (LTM 写入 + embed)
  ─ SelfPromiseDetector.detect_and_register (Jarvis 自承诺抽)
  ─ ReplyPreFlight.scan (verdict=ok/edit/scrap, 写 preflight_stats.jsonl)
  ─ CallbackGuard.scan (检测 unsolicited callback)
  ─ ConcernFeedbackJudge.judge_async (Sir 反馈 → severity_delta)
  ─ STM.append_async (_append_stm + persist 30s tick)
                            ↓
[Layer 7: 输出]
─────────────────────────────────────────────────────────────────
TTS pipeline (3 daemon worker):
  _translate_worker: EN → ZH (Gemini-flash-lite)
  _render_worker: ZH text → PCM (Microsoft TTS / SAPI)
  _play_worker: PCM → audio out
                          +
SubtitleOverlay (PyQt5): 双语字幕 + 黑色描边
BreathingLightUI (PyQt5 + OpenGL): Orb 状态机
                            ↓
                          Sir 听到 / 看到
```

---

## 2. _assemble_prompt 30+ render block 详

> 装配顺序 (见 `central_nerve.py:1495-2630` _assemble_prompt). 各 block 独立 try/except 容错.

| # | Block | 来源模块 | 数据源 | 触发条件 | 备注 |
|---|---|---|---|---|---|
| 0 | `_base_persona` | `central_nerve.JARVIS_CORE_PERSONA` | hardcoded (~7400 char) | 全 tier | 静态 |
| 1 | `self_anchor_block` | `jarvis_self_anchor.SelfAnchor.build_block()` | turn_count + own_health (KeyRouter / Hippocampus / Concerns 派生) | 全 tier | Soul Layer 0 |
| 2 | `soul_block` | `jarvis_concerns.ConcernsLedger.render_for_prompt()` | concerns.json | 全 tier | Soul Layer 1 |
| 3 | `relational_block` | `jarvis_relational.RelationalState.render_for_prompt()` | relational_state.json | 全 tier | Soul Layer 2 |
| 4 | `attention_block` | `jarvis_attention.build_attention_block()` | concerns + relational + user_input dynamic | 全 tier | Soul Layer 3 |
| 5 | `_fb_block` | `jarvis_reply_feedback.format_for_prompt()` | reply_feedback.jsonl | 仅 STANDARD+ | Sir 上次反馈 |
| 6 | `_corrections_block` | `jarvis_central_nerve._build_corrections_block()` | profile_corrections.jsonl + mutation_receipts.jsonl | STANDARD+ | 修正历史 (fix35 P5-fix35 已合并 2 audit log) |
| 7 | `_ms_block` | `jarvis_milestones.render_prompt_block(max_recent=3)` | sir_milestones.json | STANDARD+ | Sir 终生 milestones |
| 8 | `_rn_text` | `jarvis_recent_nudge_memory.to_prompt_block(within=1800, max=5)` | recent_nudges.jsonl | STANDARD+ | 防 nudge 重复 |
| 9 | `_pc_block` | `ProfileCard.render_for_prompt()` | sir_profile.json | STANDARD+ | Sir 静态画像 |
| 10 | `_tom_text` | `jarvis_sir_mental_model.render_prompt_block(include_unspoken=True)` | sir_mental_state.json | STANDARD+ | ToM 推断 |
| 11 | `_iw_text` | `jarvis_integrity_watcher.render_report_block(within=1800, max=3)` | integrity_audit.jsonl | STANDARD+ | INTEGRITY 报告 |
| 12 | `_cm_text` | `jarvis_cross_session_callback.render_callback_block(last_turn, within=180)` | cross_session_callback.json | STANDARD+ | 跨 session 心结 |
| 13 | `_fail_text` + `_active_text` | `jarvis_watch_task.render_failure_block + render_active_tasks_block` | watch_tasks.json | STANDARD+ | 主动等的事件 |
| 14 | `_sd_text` | `jarvis_stand_down.render_prompt_block()` | stand_down_state.json | 全 tier | Stand Down 模式 |
| 15 | `_sst_text` | `jarvis_sir_status_tracker.render_status_block_for_prompt()` | sir_status.json | 全 tier | Sir 当前状态 |
| 16 | `_sv_text` | `jarvis_screen_vision.render_screen_block(max_age_s=120)` | screen_snapshot.json | STANDARD+ | 屏幕 vision |
| 17 | `_sr_lines` | `central_nerve._build_sleep_routine_block()` | SWM 'sleep_routine_armed' | sleep mode | Sleep routine evidence |
| 18 | `_rce_lines` (fix82-X) | `Hippocampus.list_recent_completed_events(days=7, max=15)` | TaskMemories 'Completed:%' | 全 tier | 近 7 天已完成事件 ⭐ |
| 19 | `_wt_lines` | `central_nerve._build_watch_task_fired_block()` | SWM 'watch_task_fired' | 全 tier | Sir 委托等的事件刚触发 |
| 20 | `_pop_lines` | `central_nerve._build_unsolicited_callback_block()` | SWM 'unsolicited_callback_caught' | STANDARD+ | 防主脑乱 callback |
| 21 | `_err_lines` | `jarvis_error_bus.render_recent_errors_block(within=600)` | system_errors.jsonl | STANDARD+ | 模块错误暴露 |
| 22 | `_ir_lines` | `jarvis_intent_resolver.render_telemetry_block()` | intent_resolver_telemetry.json | STANDARD+ | IR tool result 指引 |
| 23 | `_mood_line` | `central_nerve._build_mood_calibration_line()` | sensor_state aggregated | 全 tier | mood subtle calibration |
| 24 | `_l2_block` | `jarvis_directives.DirectiveRegistry.inject_for(context)` | directive_registry.json | 全 tier | L2 conditional directives ⭐ |
| 25 | `swm_block` | `event_bus.to_swm_block(n=12, salience_floor=0.3, critical=0.85)` | ConversationEventBus (内存) | 全 tier | ⭐⭐⭐ SWM evidence (β.5.0 三维耦合) |
| 26 | `stm_block` | `central_nerve._render_stm()` | short_term_memory list (max 30) | 全 tier | Sir-Jarvis 30 turn |
| 27 | `_sensor_block` | `jarvis_sensor_state_block.build_block()` | PhysicalEnvProbe + JarvisState | STANDARD+ | 实时 sensor (键鼠/window/idle) |
| 28 | `_pf_block` | `jarvis_reply_preflight.render_topic_tracker_block()` | preflight_stats | STANDARD+ | Sir 当前 topic 暗示 |
| 29 | `_wakecb_text` | `jarvis_central_nerve._build_wake_callback_block()` | cross_session_callback wake (跨 session) | wake only | wake greeting context |
| 30 | `_open_threads_text` | `jarvis_utils.render_open_threads_block(stm)` | STM 抽未完话题 | STANDARD+ | 历史未完话题 |
| 31 | `_yesterday_text` | `jarvis_utils.render_yesterday_block()` | LTM yesterday highlights | STANDARD+ | 昨日 highlights |
| 32 | `_active_reminders_text` | `jarvis_utils.render_active_reminders_block()` | CommitmentWatcher + cyclic_task | STANDARD+ | 活跃 reminders |
| 33 | `_project_text` | `jarvis_utils.render_project_block(workspace)` | git root + cwd 推断 | STANDARD+ | 当前 project context |

**总计 ~30 block** (含 STM SOURCE TAGS + INTEGRITY 红线 footer). PERSONA + 装配后 ~25K-36K char.

---

## 3. SWM event types (~50+, ConversationEventBus etype)

> 详 `utils.py:1276-1380` `DEFAULT_TTL` + `DEFAULT_SALIENCE` dict.

### 3.1 主脑必看 (salience ≥ 0.85)

| etype | salience | TTL | publisher | reader | 用途 |
|---|---|---|---|---|---|
| **`commitment_overdue`** | 0.95 | 900s | CommitmentWatcher | 主脑 prompt + SmartNudge | 承诺超时 必看 |
| **`hallucination_detected`** | 0.92 | 300s | IntegrityWatcher | 主脑 prompt | 主脑 claim 没 evidence (P0-4) |
| **`manual_standby`** | 0.90 | 240s | worker.interrupt_all | 主脑 prompt + 全 sentinel | Sir 急停 |
| **`intent_resolved`** | 0.90 | 600s | IntentResolver | 主脑 prompt 必看 | turn-level mutation 报告 |
| **`tool_called`** | 0.85 | 300s | IntentResolver | 主脑 prompt | 真 mutation 发生 |
| **`sleep_intent_declared`** | 0.85 | 1800s | worker._detect_sleep_intent | SmartNudge / 主脑 | Sir 表态 X 时间内睡 |

### 3.2 重要 (salience 0.7-0.84)

| etype | salience | publisher | 用途 |
|---|---|---|---|
| `commitment_detected` | 0.80 | Gatekeeper | Sir 自承诺 |
| `tool_chain_circuit_broken` | 0.78 | chat_bypass | 工具链熔断 |
| `reply_interrupted` | 0.75 | worker.interrupt_all | Sir 打断主脑 stream |
| `system_error_visible` | 0.75 | ErrorBus | 模块错误暴露 |
| `soft_focus_active` | 0.70 | focus_lock | offer_help / commitment 焦点 |
| `active_window_hung` | 0.70 | PhysicalEnvProbe | 窗口卡顿 (Sir 可能 frustrated) |
| `sir_watch_request_proposed` | 0.70 | SirRequestReflector | 新 watch concern propose |

### 3.3 一般 (salience 0.4-0.69)

| etype | salience | publisher | 用途 |
|---|---|---|---|
| `concern_active` | 0.65 | ProactiveCare | top concern surface |
| `sir_progress_evidence` | 0.65 | ConcernFeedback | Sir 反馈 progress |
| `help_refused` | 0.62 | worker._detect_help_refusal | Sir 拒绝 offer_help |
| `sir_intent_correction_candidate` | 0.60 | MemoryCorrection | Sir 教正候选 (β.5.44) |
| `sir_intent_deadline_candidate` | 0.60 | CommitmentWatcher (β.5.44) | Sir 时间承诺候选 |
| `reminder_fired` | 0.60 | CommitmentWatcher | 提醒触发 |
| `self_critique` | 0.60 | MetaSelfReflector | 自评 |
| `concern_timing_evidence` | 0.55 | ProactiveCare (β.5.40) | concern timing 信号 |
| `gate_advice` | 0.55 | NudgeGate / OfferGuard | nudge 软建议 |
| `sir_intent_progress_candidate` | 0.55 | ConcernFeedback | progress 候选 |
| `sir_intent_promise_candidate` | 0.55 | SelfPromiseDetector | promise 候选 |
| `sir_intent_commit_candidate` | 0.55 | Gatekeeper | commitment 候选 |
| `afk_return` | 0.55 | ReturnSentinel | Sir 归来 |
| `conversation_event` | 0.55 | gatekeeper / worker | 突破 / 回调 / 释压 |
| `sir_thinking_pause` | 0.55 | SilenceIntel (β.5.43-E) | Sir 短暂思考 |
| `proactive_nudge` | 0.50 | SmartNudge / silent_nudge | 主动 nudge 发声 |
| `tool_executed` | 0.50 | chat_bypass | 工具刚跑完 |
| `sir_intent_profile_update_candidate` | 0.50 | ProfileCard (β.5.44) | profile update 候选 |
| `emotion_shift` | 0.45 | MoodMirror | 情绪检测变化 |
| `ambient_state` | 0.45 | AmbientSensor (β.5.40) | 环境音 (笑/叹/咳) |
| `physio_state` | 0.45 | PhysioProxy (β.5.40-A2) | energy/focus/stress 评分 |
| `persona_note` | 0.40 | CorrectionLoop | 风格调整 |

### 3.4 背景 (salience 0.1-0.39)

| etype | salience | publisher | 用途 |
|---|---|---|---|
| `nudge_window_advice` | 0.35 | CompanionRhythm (β.5.40) | 时段建议 |
| `sensor_change` | 0.30 | PhysicalEnvProbe | window/category/idle 变化 |
| `jarvis_state` | 0.30 | JarvisStateTracker (β.5.43) | HUD 状态变化 |
| `utterance_appended` | 0.20 | central_nerve._append_stm | STM 末尾新对话 (短 TTL trigger) |

### 3.5 fix82 系列 SWM (本次 Phase 0 加)

| etype | salience | publisher | 用途 |
|---|---|---|---|
| **`completion_cascaded`** | 0.75 | MemoryGateway.cascade_completion (fix82-X) | Sir 教完成 → 联动 cancel commitment |
| `sir_field_updated` | 0.80 | MemoryGateway._publish_swm | mutation 真改 source |
| `sir_profile_overwritten` | (default) | ProfileCard.overwrite_field | profile.json 真改 |
| `relational_field_updated` | (default) | RelationalState.update_field | relational.json 真改 |

### 3.6 其他 (审计中发现的 etype)

- `intent_call_result` (IntentRouter) — tool 调用结果
- `sleep_intent_due` (worker SleepIntentDueTimer) — 睡眠到点
- `sleep_routine_armed` (worker SleepModeRoutine) — 睡眠 routine 已 armed
- `nudge_no_sound` (worker nudge_dispatch) — nudge 真异常
- `nudge_silenced` (β.5.19-A) — nudge [SILENCE] 预期静默
- `sir_taught_param` (待 fix82 完整化) — Sir 教参数
- `meta_self_check` (MetaSelfCheck) — META 自评

**总计 ~50+ etype**. 全跨进程 in-memory deque (max 60), **不持久化**, 重启丢.

---

## 4. Reflector daemon (~30+, 异步反思)

| Reflector | 周期 | 输入 | 输出 | LLM? |
|---|---|---|---|---|
| **ConcernsReflector** (Soul L4) | 每轮对话末尾 | reply + STM + concerns | concerns.severity_delta | 否 (启发式 keyword) |
| **WeeklyReflector** (Soul L4) | 7d | STM 30 + profile + concerns | concerns_review.json (新 concern propose) | ✅ Gemini-flash |
| **SoulAlignmentEvaluator** (Soul L5) | 每轮对话末尾 | reply + self_model + relational | concerns.aligned 信号 | ✅ Gemini-flash |
| **DirectiveEvaluator** | 每轮对话末尾 | reply + inject 的 directive | directive.helped_count + directive_review.json | ✅ Gemini-flash |
| **ProfileReflector** | 24h (fix81 改 5min) | profile_corrections.jsonl | profile_review.json | ✅ Gemini-flash |
| **IntegrityReflector** | 周期 | integrity_audit.jsonl | claim_stats.json + new evidence rule | ✅ Gemini-flash |
| **ConcernFeedbackJudge** | nudge 后 Sir 反馈时 | user_input + last_nudge | concerns.severity_delta + 'sir_intent_progress_candidate' | ✅ Gemini-flash |
| **ConcernFeedbackReflector** (L7) | 周期 | feedback 历史 | new concern 关联 propose | ✅ Gemini-flash |
| **ToMReflector** (Sir Mental) | 周期 | STM + concerns + sir_status | sir_mental_state.json | ✅ Gemini-flash |
| **ScreenTeaseReflector** (L7) | 周期 | screen_history.jsonl | screen_tease_vocab review | ✅ Gemini-flash |
| **StruggleReflector** (L7) | 周期 | STM | sir_struggle_vocab review | ✅ Gemini-flash |
| **SleepPatternReflector** (L7) | 周期 | sleep history | sir_sleep_pattern_vocab review | ✅ Gemini-flash |
| **CompanionRhythmReflector** (L7) | 周期 | nudge feedback | nudge_window_vocab review | ✅ Gemini-flash |
| **InsideJokeReflector** (L7) | 周期 | STM | RelationalState.inside_jokes review | ✅ Gemini-flash |
| **SirRequestReflector** (L7) | 周期 | STM | concerns_review (新 watch concern) | ✅ Gemini-flash |
| **STMSummarizer** | 每 reply 长时 | reply 文本 | STM 短文 | ✅ Gemini-flash-lite |
| **RejectLearner** (L8) | 周期 (3+ rejects) | reject 历史 | directive review (新 directive 防同类错) | ✅ Gemini-flash |
| **CuriosityDaemon** | 5min tick | sir_status + STM | chat_bypass.stream_nudge (curiosity ping) | ✅ Gemini-flash |
| **PromiseSweepDaemon** | 周期 | promise_log | mark overdue / fulfilled | 否 (heuristic) |
| **HealthProbeDaemon** | 5min tick | psutil + KeyRouter | jarvis_health_history.jsonl | 否 |

**LLM-based reflector 总数 ~16+**. 共享 KeyRouter 池. 跟 ReflectorBudget 联动控制 cost.

---

## 5. 关键数据流 — 真实 case 序列图

### 5.1 Case A: "今天血压咨询完成" (Sir 教正完成事件 — fix82-X 路径)

```
Sir: "其实今天血压咨询去过了"
  ↓
worker.run:
  ├─ Gatekeeper LLM (无 commitment 时间 → 不 register)
  └─ MemoryCorrectionGuard (检测教正语义 — Bayesian)
        confidence=0.5 → MemoryGateway.update_sir_field
                          field_path='preferences.user_correction'
                          new_value='血压咨询今天已完成'
                          source='worker.memory_correction'
                          ↓
        MemoryGateway.update_sir_field:
          ├─ layer routing → ProfileCard
          │     confidence=0.5 < 0.8 → fallback apply_correction (audit only)
          │     写 profile_corrections.jsonl + sir_profile.json (其实 audit only 不真改)
          ├─ _maybe_cascade_completion (fix82-X):
          │     load completion_event_vocab.json (已完成 / 完了 / 去过了 ✓)
          │     抽 keywords ('血压', '咨询') ← noun_extract_kws 命中
          │     CommitmentWatcher.cancel_by_keyword('血压', max_age=24h)
          │       → 找到 Commitments.id=20 ('明天去医院咨询...血压') description fuzzy 命中
          │       → soft_delete: is_deleted=1 ✓
          │       → bg_log "🔗 [fix82-X Completion Cascade] cancelled 1"
          │     Hippocampus.add_completed_event(summary='血压咨询今天完成', keywords=['血压'])
          │       → INSERT TaskMemories user_intent='Completed: 血压咨询今天完成' ✓
          │     event_bus.publish('completion_cascaded', sal=0.75)
          ├─ _write_receipt → mutation_receipts.jsonl (audit)
          └─ _publish_swm → 'sir_field_updated' (sal=0.80)
  ↓
chat_bypass.stream_chat:
  ├─ assemble_prompt (调 Hippocampus.list_recent_completed_events 抽 'Completed:%' 7d)
  │     → [RECENT COMPLETED] block 含 '✅ 血压咨询今天完成 (0分钟前)'
  │     → 主脑下轮看到不再误说"明天血压咨询" ✓
  ├─ stream Gemini → reply: "Confirmed today, Sir. Enjoy rest day tomorrow."
  └─ post-process:
      ├─ ClaimTracer: 主脑 claim 'Confirmed' → 配 mutation_receipts.jsonl 验 ✓
      └─ SoulEvaluator: alignment ✓ (跟 ConcernsLedger 健康关心一致)

下次 Sir 问 "明天有啥安排?" → 主脑 prompt 看 [RECENT COMPLETED] 知道血压完了, 不再提.
```

### 5.2 Case B: "10:30 叫我去洗澡" (Sir 设承诺 — fix82-Z Gatekeeper skip 路径)

```
Sir: "10:30 叫我去洗澡"
  ↓
worker.run 并发:
  Path A (Gatekeeper LLM, 后台异步):
    抽 commit ('10:30 去洗澡') → CommitmentWatcher.add_commitment
        → Hippocampus.add_commitment_row: INSERT Commitments DB#28
        → publish 'sir_intent_deadline_candidate' (sal=0.65)
        → bg_log "📝 [CommitmentWatcher] 已注册: 10:30 去洗澡 (DB#28)"
  Path B (chat_bypass.stream_chat 主流):
    主脑 stream → emit <FAST_CALL>{"organ":"memory_hands","command":"add_reminder",...}
        → chat_bypass._execute_fast_call:
            ├─ alias resolve: 'memory' → 'memory_hands' (fix77-Q)
            ├─ fix82-Z: 检 SWM 'sir_intent_deadline_candidate' < 10s 内 ✓
            │   → skip dup add_reminder, fake ExecutionResult(success=True,
            │     msg='Gatekeeper 已并发注册...')
            ├─ tool_result append: "✅ Gatekeeper 已注册 commitment '10:30 去洗澡' DB#28"
            └─ continuation_prompt 喂回主脑
        ↓
    主脑续 stream 看 tool_result → 自然 ack: "Reminder set for 10:30 PM, Sir."
    (不再罐头 "I couldn't" 撒谎 ✓)
  ↓
22:30 到点:
  CommitmentWatcher._check_due_commitments → fire DB#28
    → publish 'reminder_fired' (sal=0.60)
    → chat_bypass.stream_nudge (REMINDER_FIRING tier prompt)
    → TTS: "It's 10:30, Sir. Time for that shower."
```

### 5.3 Case C: "Cursor 别再提" (Sir 反讽 concern — concerns.dismiss 路径)

```
Sir: "Cursor 别再提了"
  ↓
worker.run:
  ├─ ConcernFeedbackJudge.judge_async (LLM 评 Sir 反馈):
  │     output: { concern_id: 'sir_cursor_payment', severity_delta: -0.7,
  │              optimal_timing: 'never', dismiss=True }
  │     → ConcernsLedger.record_signal(concern_id='sir_cursor_payment', delta=-0.7)
  │     → publish 'sir_intent_progress_candidate' (sal=0.55)
  └─ chat_bypass.stream_chat:
      主脑可能 emit <CONCERN_DAMPEN>{"concern_id":"sir_cursor_payment","reason":"Sir 反讽"}
        → jarvis_concern_dampen.process_reply:
            ConcernsLedger.record_signal(delta=-0.5) — 再降 (不重置 0)
        OR 主脑 emit <FAST_CALL>{"organ":"concerns","command":"dismiss",...}
          → ConcernsLedger.dismiss(concern_id='sir_cursor_payment')
            → state='archived' + triggers_proactive=False
            → 持久化 concerns.json
  ↓
下轮 _assemble_prompt: soul_block 不再含 sir_cursor_payment (state=archived)
  → ProactiveCare 不再 surface 该 concern
  → 主脑下次自然不再提 Cursor.
```

### 5.4 Case D: 主脑撒谎 → IntegrityWatcher retry (β.5.43)

```
主脑 reply: "I've set a reminder for 10:30 PM."
但 emit <FAST_CALL> 失败 (e.g. 缺 intent 参数 → "❌ 缺少 intent 参数")
  ↓
chat_bypass post-stream:
  ├─ ClaimTracer.extract_claims:
  │     抽 claim {kind: 'reminder', target: '10:30', evidence_kind: 'add_reminder'}
  │     verify: 找 mutation_receipts within 60s + intent='10:30'
  │     → 找不到 (FAST_CALL 失败) → unverified
  │     → publish 'hallucination_detected' (sal=0.92)
  └─ IntegrityWatcher.verify_async:
      读 SWM 'hallucination_detected'
      → retry_reminder(claim, nerve):
          调 hippocampus.add_reminder(intent='10:30 reminder', trigger_time=...)
          → 真补救成功 → mark recovered
          → publish 'recovered' SWM
  ↓
下轮 _assemble_prompt: integrity_watcher block 含 '✅ recovered: reminder 10:30'
  → directive `claim_recovery_aware` 触发
  → 主脑 prompt 教: "你之前 claim X, watcher 重新调 module 自动补上, 现状态真 OK.
                      你必须 inline acknowledge. Sir 准则 5 言出必行可观察."
  → 主脑下次 reply 自然 ack: "Sir, 顺便那 reminder 我刚补好了, 现在 OK."
```

---

## 6. 数据流的 7 大耦合点 (Phase B 必处理)

| # | 耦合 | 现状 | 问题 |
|---|---|---|---|
| 1 | **ProfileCard.apply_correction (老) vs overwrite_field (新)** | 双路径并存 | 主脑教正部分走老路径 audit only 不真改 |
| 2 | **5 套时间承诺**: PromiseLog + CommitmentWatcher + cyclic_task + watch_task + concerns.notes_for_self | 各自管自己 | 不联动, Sir 教 1 次同步不到全 5 套 |
| 3 | **mutation_receipts.jsonl + profile_corrections.jsonl + claim_revisions.json + claim_stats.json + integrity_audit.jsonl** | 5 个 audit log | 应合并 1 个 mem_audit.jsonl |
| 4 | **Conductor + IntentResolver + chat_bypass.FAST_CALL** | 3 套决策路径 | 主脑 emit 走 3 处, 不一致 |
| 5 | **Hippocampus.TaskMemories.is_future_task vs Commitments 表** | 同 db 2 表概念重叠 | "future_task" 跟 "commitment" 模糊 |
| 6 | **HumorMemory + RelationalState.inside_jokes** | 2 处管笑点 | 重叠 |
| 7 | **L1 Right/Left/Reflection brain (legacy?) + 现 chat_bypass + worker** | 历史架构残留 | Phase A.5 必查 deprecated |

---

## 7. SWM 跨 session 持久化 gap

> ConversationEventBus deque maxlen=60 + in-memory only. **重启全丢**.

**现状**: SWM 是当前 session 的实时 evidence, 跨 session 不保留.

**问题**:
- Sir 22:00 真测的 SWM event (e.g. 'reply_interrupted' / 'tool_called'), 22:30 重启后全消
- 主脑下次启动看不到上次 session 的关键 evidence (commitment_overdue / hallucination_detected 等)
- ClaimTracer 跨 session verify 失败 (老 claim 没了)

**Phase B 必判**: 加可选 `swm_history.jsonl` 持久化 critical event (salience ≥ 0.85)?

---

## 8. 主脑 prompt 总长 vs tier 路径

| Tier | 装配 block | 长度估 | 用途 |
|---|---|---|---|
| **WAKE_ONLY** | persona + self_anchor + state + STM-3 | ~9K char | 仅 "Jarvis" 唤醒 |
| **SHORT_CHAT** | + soul + relational + sir_status + screen_vision | ~14K char | 短聊 |
| **STANDARD** | + 30+ block 全装配 + L2 directives 10 条 | **~25K-36K char** | 默认主对话 |
| **DEEP_QUERY** | STANDARD + LTM retrieve (Hippocampus search_memory) | ~32K-40K char | 深问答 |
| **CRITICAL** | STANDARD + INTEGRITY 强化 + claim_tracer | ~30K char | 排期/纠正/记忆操作 |
| **FACTUAL_RECALL** | STANDARD + LTM 强 retrieve | ~32K char | 事实回忆 |
| **TOOL_REQUEST** | STANDARD + 24 hands manifest | ~28K char | 工具调用 |
| **REMINDER_FIRING** | persona + reminder context + STM-2 | ~6K char | reminder 触发 (短 prompt 主脑专注 nudge) |

**Phase D 应**: prompt 减肥 — STANDARD 35K → 25K (跟 PromptBuilder 配合).

---

## 9. 数据流统计

| 维度 | 数量 |
|---|---|
| 主脑 prompt render block | 30+ |
| SWM event type | ~50+ |
| Reflector daemon (LLM-based) | ~16 |
| Reflector daemon (heuristic) | ~5 |
| 持久化 vocab json | ~40 |
| audit jsonl | ~10 |
| state snapshot json | ~10 |
| sqlite db | 1 (4 表 + 1 skill_tree.db) |
| FAST_CALL organ | ~24 (mutation + 9 manual organ + 14 hands organ) |
| Sentinel daemon | ~9 (sentinels.py) + ~5 (单独) = 14 |

---

## 10. 总结 — Phase B 设计输入

本 dataflow map 揭示了 7 大耦合点 + 5 套时间承诺 + 3 套 mutation 路径 + ~30 render block 散落 + SWM 不持久化等问题. Phase B 应基于此设计:

1. **统一记忆 source 6 类** (Identity / Events / Commitments / Concerns / State / Relations) — `JARVIS_MEMORY_AND_MUTATION_REFACTOR.md` 已定 6 layer abstraction
2. **MemoryHub** 演化自现 `MemoryMutationGateway` (P2-Gap7) — 不另起炉灶
3. **read_context()** 替 30+ 散 render block — 通过 PromptBuilder 实施
4. **5 套时间承诺合并** — Phase B 必决议: PromiseLog 单源 / 双源
5. **3 套决策路径整合** — Conductor + IntentResolver + FAST_CALL → 1 入口
6. **5 audit jsonl 合并** → `mem_audit.jsonl`
7. **SWM 跨 session 持久化** — critical event ≥ 0.85 写 jsonl

---

*Phase A.2 dataflow map 完成于 2026-05-23 23:40.*
*配合 `JARVIS_AUDIT_CARDS.md` (140 模块审计) + `JARVIS_GRAND_REFACTOR.md` (立项) + `JARVIS_ARCHITECTURE_MAP.md` (静态架构) = Jarvis 完整知识库.*
