# JARVIS 架构总览 (Architecture Map)

> 2026-05-23 22:40 起草. Sir 真意: "保证以后只要阅读 md 文件就能足够了解贾维斯".
>
> **本文档 = Jarvis 的目录索引 + 1 张图. 90 个 .py 主模块 + 25 个 hands + 35 个 design doc 全在这里关联**.
>
> 读完本 doc + `AGENTS.md` + 6 个核心 design doc (§§§ 标记的) = 完整理解 Jarvis.

---

## 1. TL;DR — 1 张图看 Jarvis

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Sir (人) — 麦克风说话 / 屏幕被看 / 键鼠真按 / 物理 idle                    │
└────────┬──────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Layer 1: 传感器 (Sensors) — 只 publish, 不决策                          │
│  ─────────────────────────────────────────────────────────────────────   │
│  PhysicalEnvProbe / VoiceListenThread / ScreenVisionEngine /             │
│  AmbientSensor / AcousticWake / SleepDetector / 23+ Sentinel             │
└────────┬─────────────────────────────────────────────────────────────────┘
         │ publish()
         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Layer 0: SWM (SharedWorldModel = ConversationEventBus)  ⭐ 数据强耦合枢纽│
│  ─────────────────────────────────────────────────────────────────────   │
│  jarvis_utils.py 内 ConversationEventBus class                           │
│  - publish(etype, desc, source, salience, metadata)                      │
│  - recent_events(within_seconds, types) / to_swm_block()                 │
│  - 所有 sensor/sentinel/reflector/主脑/工具结果 都进这里                  │
└────────┬─────────────────────────────────────────────────────────────────┘
         │ 主脑 prompt 读 to_swm_block()
         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Layer 2: 主脑 (Gemini-3-Pro/Flash via KeyRouter)  ⭐ 决策集中            │
│  ─────────────────────────────────────────────────────────────────────   │
│  • 输入: PERSONA + 6 类记忆 (见 Layer 3) + SWM evidence + STM + Sir 话    │
│  • 输出: 自然语言 reply + N 个 <FAST_CALL>{organ,command,params}         │
│  • directive (130+ 条 conditional inject) 教主脑各种 case 的反应          │
└────────┬─────────────────────────────────────────────────────────────────┘
         │ FAST_CALL 解析后调
         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Layer 3: 6 类记忆 (Source of Truth)  ⭐ 记忆系统                        │
│  ─────────────────────────────────────────────────────────────────────   │
│  A 身份: sir_profile.json + ProfileCard                                  │
│  B 事件: TaskMemories (sqlite) + Hippocampus + STM 30 turn               │
│  C 承诺: Commitments (sqlite) + CommitmentWatcher + PromiseLog           │
│  D 担心: concerns.json + ConcernsLedger + 30+ Reflector                  │
│  E 状态: sir_status / stand_down / sir_acked / state_tracker             │
│  F 关系: relational_state.json + RelationalState (inside_jokes / ...)    │
│                                                                          │
│  统一写入: MemoryGateway.update_sir_field() → cascade → 6 source         │
│  统一审计: mutation_receipts.jsonl (1 处)                                │
└────────┬─────────────────────────────────────────────────────────────────┘
         │ FAST_CALL 也可调
         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Layer 4: 25 个 Hands (执行器)  — 真改世界                               │
│  ─────────────────────────────────────────────────────────────────────   │
│  l4_audio / l4_window / l4_screen / l4_memory / l4_text / l4_process /   │
│  l4_input / l4_media_control / l4_video_upload / l4_watcher / ...        │
└─────────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Layer 5: TTS + UI — 输出给 Sir                                          │
│  ─────────────────────────────────────────────────────────────────────   │
│  jarvis_vocal_cord.py (TTS) + jarvis_ui.py (PyQt5 + OpenGL 字幕/Orb)     │
└─────────────────────────────────────────────────────────────────────────┘
```

**关键耦合方式 (准则 6 三维耦合)**:
- **数据强耦合**: 所有信号 publish 进 SWM, 主脑读统一证据
- **行为弱耦合**: Sentinel 不硬决策, 改 publish-only
- **决策集中**: 主脑 1 处看全 evidence, 自决 reaction (silence / voice / silent_text / visual_pulse / tool_call)

---

## 2. 5 个核心枢纽 (≥ 1500 行的主干)

> 这 5 个 .py 加起来 ~22000 行, 是 Jarvis 的中枢神经. 读 src 才能完全懂, 但看本 §就够导航.

### 2.1 `jarvis_nerve.py` (328 行) — **主入口 / __main__**

启动顺序:
1. 解析 CLI args → 加载 jarvis_config/sir_profile.json
2. `TraceContext.init_session()` 生成 `sess_YYYYMMDD_HHMMSS_<PID>` (trace ID)
3. 实例化 `CentralNerve` (jarvis_central_nerve.py) — 主大脑控制器
4. 实例化 `Worker` (jarvis_worker.py) — PyQt5 工作线程主体
5. 启动 daemons (~30 个 Reflector + Sentinel)
6. 启动 PyQt5 main loop (UI + worker thread)

> 本模块是**入口**, 业务逻辑全在 CentralNerve / Worker. 没专 design doc (薄包装).

### 2.2 `jarvis_central_nerve.py` (5086 行) — **CentralNerve + PERSONA + _assemble_prompt**

**最重要**: `_assemble_prompt()` 拼装每轮主脑 prompt, 含:
- `JARVIS_CORE_PERSONA` (~7400 chars 静态人设)
- 30+ 个 render block (concerns / relational / attention / sir_mental_model / screen_vision / etc.)
- 输出: ~20K-36K char 给主脑

**子模块** (CentralNerve 实例化时持有):
- `self.event_bus` = ConversationEventBus (SWM 入口)
- `self.profile_card` = ProfileCard (jarvis_routing.py)
- `self.hippocampus` = Hippocampus
- `self.commitment_watcher` = CommitmentWatcher
- `self.concerns_ledger` = ConcernsLedger
- `self.intent_resolver` = IntentResolver
- 数十个其他 component

> 拆分计划: `docs/NERVE_SPLIT_PLAN.md` (尚未执行).

### 2.3 `jarvis_chat_bypass.py` (5960 行) — **stream_chat 主对话循环**

**最关键**: `stream_chat()` 是每次 Sir 说话后的主流程:
1. 装配 prompt (调 CentralNerve._assemble_prompt)
2. 调 Gemini stream API
3. parse stream chunks → 检测 `<FAST_CALL>...</FAST_CALL>` 标签
4. 实时 dispatch FAST_CALL (mutation / hands / organs)
5. 拼 continuation_prompt 喂回主脑 (主脑看 tool result 续 stream)
6. 末尾: TTS + UI emit + post-turn reflectors

> 拆分计划: 在 NERVE_SPLIT_PLAN 内. 当前 5960 行单文件, 难维护.

### 2.4 `jarvis_worker.py` (5823 行) — **PyQt5 Worker 主线程 + 工具链**

**职责**:
- 跑 PyQt5 worker thread (避免 main UI thread block)
- 处理 ASR text_ready signal
- 调 chat_bypass.stream_chat
- memory_correction guard (Sir 教正语义检测)
- Gatekeeper LLM (commitment / cancel / 实时 NLU)
- 各种 sentinel 协调

> 没专 design doc. 极复杂 — 有 P0+19-9 marker (2026-05-16 reorg) + 后续 50+ patches.

### 2.5 `jarvis_utils.py` (4861 行) — **核心工具 + ⭐ ConversationEventBus**

**ConversationEventBus** (即 SharedWorldModel SWM) 在这里实现:
- `publish(etype, description, source, salience, metadata)`
- `recent_events(within_seconds, types)` — 主脑 prompt 用
- `to_swm_block(n=12)` — render evidence section

**其他工具**:
- `bg_log()` — 不漏到对话框的 background log + auto trace prefix
- `safe_gemini_call()` — KeyRouter 装甲 + 重试 + Quota 容灾
- `network_retry` decorator — 网络重试装甲
- `TraceContext` — session/turn ID 生成 + 注入
- `WorkingMemoryFeed` — 30min 环境快照

> 巨型文件没专 doc. SWM 设计在 `JARVIS_SENSOR_TO_SWM_ARCHITECTURE.md` 提到但 API 详细设计未单独 doc.

---

## 3. 90 个 `jarvis_*.py` 完整索引

> 按 Layer / Domain 分组. 每行: 文件 | 行 | 1 句简介 | 关联 design doc

### 3.1 启动 + 主流 (5 核心枢纽 — §2 详)

| 模块 | 行 | 简介 | doc |
|---|---:|---|---|
| `jarvis_nerve.py` | 328 | 主入口 __main__ + PyQt5 启动 | (薄, 见 §2.1) |
| `jarvis_central_nerve.py` | 5086 | CentralNerve + PERSONA + _assemble_prompt | NERVE_SPLIT_PLAN |
| `jarvis_chat_bypass.py` | 5960 | stream_chat 主对话循环 + FAST_CALL parse/dispatch | NERVE_SPLIT_PLAN |
| `jarvis_worker.py` | 5823 | PyQt5 Worker + memory_correction + Gatekeeper | (无专 doc) |
| `jarvis_utils.py` | 4861 | ConversationEventBus (SWM) + bg_log + safe_gemini_call + TraceContext | SENSOR_TO_SWM (部分) |

### 3.2 灵魂架构 (Soul Drive 5 Layer)

| 模块 | 行 | 简介 | doc |
|---|---:|---|---|
| `jarvis_self_anchor.py` | 339 | Layer 0 — 我是谁的锚点 | **SOUL_DRIVE §** |
| `jarvis_concerns.py` | 984 | Layer 1 — Jarvis 内部牵挂 (5+ active concerns) | **SOUL_DRIVE §** |
| `jarvis_relational.py` | 1198 | Layer 2 — 我们之间 (inside_jokes / unfinished / threads) | **SOUL_DRIVE §** |
| `jarvis_attention.py` | 207 | Layer 3 — 此刻注意力分配 | **SOUL_DRIVE §** |
| `jarvis_soul_reflector.py` | 752 | Layer 4 — 异步 daemon update concerns | **SOUL_DRIVE §** |
| `jarvis_soul_evaluator.py` | 637 | Layer 5 — 主脑 reply 是否符合 self_model | **SOUL_DRIVE §** |
| `jarvis_sir_mental_model.py` | 563 | Theory of Mind — Sir 此刻心智模型 | **TOM_SIR_MENTAL_MODEL §** |

### 3.3 记忆系统 (Memory Source of Truth)

| 模块 | 行 | 简介 | doc |
|---|---:|---|---|
| `jarvis_routing.py` | 1479 | ProfileCard (Sir 静态画像 + overwrite_field) | MEMORY_AND_MUTATION |
| `jarvis_hippocampus.py` | 1478 | TaskMemories sqlite + Commitments + 长期事实 | MEMORY_AND_MUTATION |
| `jarvis_memory_core.py` | 1512 | Memory Core — 唤醒/失败/睡觉/沉默 12 类 | (薄, 在 SOUL_DRIVE 提到) |
| `jarvis_memory_gateway.py` | 733 | **统一 mutation API** (P2-Gap7, 2026-05-20) | **MEMORY_AND_MUTATION §** |
| `jarvis_milestones.py` | 234 | Sir's Lifetime Milestones | (在 SOUL_DRIVE 提到) |
| `jarvis_stm_summarizer.py` | 354 | STM Reply 概括 (Gap-Z1) | (无专 doc) |
| `jarvis_profile_reflector.py` | 413 | 24h tick 提案 sir_profile.json 演化 | MEMORY_AND_MUTATION |
| `jarvis_promise_log.py` | 574 | Jarvis 自承诺账本 | MEMORY_AND_MUTATION |
| `jarvis_commitment_watcher.py` | 1932 | Sir 承诺 + sqlite Commitments + nudge | MEMORY_AND_MUTATION |
| `jarvis_self_promise.py` | 579 | Jarvis Self-Promise 检测器 (vocab driven) | (无专 doc) |
| `jarvis_cyclic_task.py` | 397 | 通用循环协议 | (无专 doc) |

### 3.4 主脑 prompt + Directive

| 模块 | 行 | 简介 | doc |
|---|---:|---|---|
| `jarvis_directives.py` | 3958 | L2 Conditional Directives Registry (130+ 条) | **DIRECTIVE_SELF_AWARENESS §** |
| `jarvis_directive_evaluator.py` | 397 | Gemini-3-Flash 异步评 directive 是否 helped | DIRECTIVE_SELF_AWARENESS |
| `jarvis_prompt_builder.py` | 245 | Sir 真意 1 prompt builder 体系 (P5-fix54) | PROMPT_REFACTOR_PLAN |

### 3.5 INTEGRITY 栈 (诚信验证)

| 模块 | 行 | 简介 | doc |
|---|---:|---|---|
| `jarvis_claim_classifier.py` | 289 | L1 — 主脑 reply 抽 claim | **INTEGRITY_STACK §** |
| `jarvis_evidence_requirements.py` | 243 | L2 — 各 claim 类型的 evidence 要求 | INTEGRITY_STACK |
| `jarvis_claim_tracer.py` | 888 | L3 — 通用 claim 防说谎 (vocab + LLM) | INTEGRITY_STACK |
| `jarvis_claim_revision_log.py` | 527 | functional revision log (区分 ritual) | INTEGRITY_STACK |
| `jarvis_integrity_watcher.py` | 1846 | reply 后台 verify + retry 老 claim | INTEGRITY_STACK |
| `jarvis_integrity_reflector.py` | 766 | L7 LLM-propose 新 evidence rule | INTEGRITY_STACK |
| `jarvis_inconsistency_watcher.py` | 461 | Commitment Inconsistency (Layer B) | INTEGRITY_STACK |
| `jarvis_callback_guard.py` | 415 | Unsolicited Callback 5+ 防误报 | (无专 doc, 在 INTEGRITY 提到) |
| `jarvis_meta_self_check.py` | 458 | thinking pass meta self-check parser | INTEGRITY_STACK |

### 3.6 IntentResolver + Tool routing

| 模块 | 行 | 简介 | doc |
|---|---:|---|---|
| `jarvis_intent_resolver.py` | 854 | Sir utterance → intent → tool candidates (β.5.44) | **INTENT_RESOLVER_REFACTOR §** |
| `jarvis_intent_router.py` | 325 | intent → tool 路由 | INTENT_RESOLVER_REFACTOR |
| `jarvis_tool_registry.py` | 398 | TOOL_REGISTRY (mutation tools) | INTENT_RESOLVER_REFACTOR |
| `jarvis_skill_registry.py` | 2559 | 自我成长地图 (技能注册 + 持久化) | (无专 doc) |
| `jarvis_fuzzy_resolver.py` | 207 | ASR 实体容错 (fuzzy → exact ID) | (无专 doc) |

### 3.7 主动关怀 + Nudge 体系

| 模块 | 行 | 简介 | doc |
|---|---:|---|---|
| `jarvis_proactive_care.py` | 1873 | ProactiveCareEngine 主动关怀 | **PROACTIVE_CARE_ENGINE §** |
| `jarvis_smart_nudge.py` | 1010 | SmartNudge 哨兵 — 11 类 nudge + type-mute | (无专 doc) |
| `jarvis_recent_nudge_memory.py` | 270 | 记忆通过去 nudge (P2-Gap12) | (无专 doc) |
| `jarvis_nudge_coordination.py` | 142 | β.5.0 三维耦合 sentinel 协调 | (无专 doc) |
| `jarvis_concern_dampen.py` | 169 | CONCERN_DAMPEN tag — 反讽 concern severity | (无专 doc) |
| `jarvis_concern_feedback.py` | 250 | LLM 评判 Sir 反馈 → concern 加减分 | (无专 doc) |
| `jarvis_concern_feedback_reflector.py` | 281 | L7 LLM 内反思 propose | (无专 doc) |
| `jarvis_concern_summon.py` | 108 | concern 召唤检测 (vocab loader) | (无专 doc) |
| `jarvis_conductor.py` | 1255 | 指挥官 — 融合 directive + 关键词/LLM + 决策 | (无专 doc) |
| `jarvis_curiosity.py` | 147 | Curiosity Ping (β.2.9.4) | (无专 doc) |

### 3.8 Sensor + Sentinel 体系

| 模块 | 行 | 简介 | doc |
|---|---:|---|---|
| `jarvis_sensors.py` | 1147 | 传感器 / 感知 / 分类 (主 Thread 类) | **SENSOR_TO_SWM §** |
| `jarvis_env_probe.py` | 959 | PhysicalEnvironmentProbe 环境感知 (键鼠 / window) | SENSOR_TO_SWM |
| `jarvis_sentinels.py` | 2166 | 9 类通用哨兵后台线程 | SENSOR_TO_SWM |
| `jarvis_screen_vision.py` | 700 | 屏幕 vision 结构化 (Gemini Vision) | **VISION_INTEGRATION §** |
| `jarvis_ambient_sensor.py` | 596 | Ambient audio sensor 环境音 publish 进 SWM | (无专 doc) |
| `jarvis_acoustic_wake.py` | 631 | openWakeWord 唤醒装甲 (β.4.8) | (无专 doc) |
| `jarvis_state_tracker.py` | 235 | HUD 状态机 + SWM publish | (无专 doc) |
| `jarvis_silence_intel.py` | 198 | thinking pause detection (β.5.43-E) | (无专 doc) |
| `jarvis_health_probe.py` | 240 | Jarvis 自检 daemon | (无专 doc) |
| `jarvis_physio_proxy.py` | 303 | 生理代理 — energy/focus/stress 推断 | (无专 doc) |
| `jarvis_screen_tease_reflector.py` | 424 | L7 vocab propose daemon | (无专 doc) |
| `jarvis_struggle_reflector.py` | 376 | L7 sir_struggle_vocab propose | (无专 doc) |
| `jarvis_sleep_pattern_reflector.py` | 249 | Sir 睡眠模式 L7 reflector | (无专 doc) |
| `jarvis_companion_rhythm_reflector.py` | 407 | L7 daemon nudge timing 学习 (β.5.40-E1) | (无专 doc) |
| `jarvis_inside_joke_reflector.py` | 390 | L7 propose inside_jokes (β.5.40-B1) | (无专 doc) |
| `jarvis_sir_request_reflector.py` | ~? | (无 doc) | (无专 doc) |
| `jarvis_sir_status_tracker.py` | 482 | Sir 状态跟踪 (P5-SirStatusTracker) | (无专 doc) |
| `jarvis_return_sentinel.py` | 1186 | 归来哨兵 ReturnSentinel + AFK | (无专 doc) |
| `jarvis_stand_down.py` | 692 | Stand Down 模式 — 暂停 nudge | (无专 doc) |
| `jarvis_project_hold_detector.py` | 240 | Project Hold detector (β.5.46-fix18) | (无专 doc) |
| `jarvis_watch_task.py` | 937 | WatchTask 主动等屏幕事件 (β.5.46-fix13) | (无专 doc) |
| `jarvis_cross_session_callback.py` | ~? | 跨 session 心结 surface | (无专 doc) |
| `jarvis_actionable_items.py` | 1167 | ActionableItems 统一 Sir 可操作 (21 类) | (无专 doc) |

### 3.9 Reply Pipeline + Pre/Post 检查

| 模块 | 行 | 简介 | doc |
|---|---:|---|---|
| `jarvis_reply_preflight.py` | 405 | reply 前 self-check (Gap 2 PreFlight) | **REPLY_PREFLIGHT §** |
| `jarvis_reply_feedback.py` | 108 | Sir 对 Jarvis reply 的反馈 (β.5.43-D) | (无专 doc) |
| `jarvis_safety.py` | 722 | 安全 helper / 拒绝 / 中文判式 | (无专 doc) |
| `jarvis_reject_learner.py` | 420 | L8 Reject Learner 退化学习 | **REJECT_LEARNER_L8 §** |

### 3.10 Predicate + Commitment

| 模块 | 行 | 简介 | doc |
|---|---:|---|---|
| `jarvis_predicate.py` | 576 | Predicate-Driven Commitment (β.2.8.6) | **PREDICATE_COMMITMENT §** |
| `jarvis_predicate_parser.py` | 204 | Gatekeeper 内 LLM Parser | PREDICATE_COMMITMENT |

### 3.11 LLM 装甲 + Reflector 调度

| 模块 | 行 | 简介 | doc |
|---|---:|---|---|
| `jarvis_key_router.py` | 992 | API Key 装甲路由 (5+ Google + OpenRouter fallback) | (无专 doc) |
| `jarvis_llm_reflector.py` | 337 | 通用 LLM 反思器 | (无专 doc) |
| `jarvis_reflector_budget.py` | 200 | Reflector Budget 控制 (Gap-Z3) | (无专 doc) |
| `jarvis_jsonl_rotator.py` | 157 | JSONL rotation utility (P3-BUG#7) | (无专 doc) |
| `jarvis_error_bus.py` | 253 | Error Self-Healing Bus (β.5.43-F) | (无专 doc) |

### 3.12 Sensor block 渲染 + UI

| 模块 | 行 | 简介 | doc |
|---|---:|---|---|
| `jarvis_sensor_state_block.py` | 170 | [SENSOR STATE] block builder (P5-fix53) | (无专 doc) |
| `jarvis_progress_tracker.py` | 473 | 通用数值进度 (P5-fix35-D) | (无专 doc) |
| `jarvis_ui.py` | 920 | PyQt5 + OpenGL Orb / 字幕 | (无专 doc) |
| `jarvis_vocal_cord.py` | 320 | TTS (Microsoft TTS / SAPI) | (无专 doc) |

### 3.13 微杂项

| 模块 | 行 | 简介 |
|---|---:|---|
| `jarvis_blood.py` | 95 | Action / ExecutionResult dataclass (协议) |
| `jarvis_enhanced.py` | 757 | (无 docstring, 历史模块?) |

---

## 4. 25 个 `l4_*.py` Hands (执行器)

> **Sir 真意问题**: hands 全无 docstring + 无 md doc. **执行真改世界的部分文档化最差**.

| Hand | 行 | 关键 commands |
|---|---:|---|
| `l4_audio_hands.py` | 216 | volume_set / volume_get / mute / unmute |
| `l4_clipboard_hands.py` | 111 | copy / paste / get_clipboard |
| `l4_desktop_hands.py` | 109 | minimize_all / show_desktop |
| `l4_display_hands.py` | 126 | dim_display / sleep_display / wake_display / get_brightness |
| `l4_everything_search_hands.py` | 45 | search files via Everything |
| `l4_file_operator_hands.py` | 62 | copy / move / delete file |
| `l4_gui_atom.py` | 112 | basic GUI atoms |
| `l4_input_hands.py` | 321 | type_text / send_keys / mouse_click |
| `l4_media_control_hands.py` | 136 | play / pause / next / prev / stop (媒体键) |
| `l4_memory_hands.py` | 180 | search_memory / list_reminders / delete_record / **add_reminder** / list_commitments |
| `l4_network_hands.py` | 122 | ping / dns / network_check |
| `l4_notification_hands.py` | 95 | toast 通知 |
| `l4_process_hands.py` | 318 | find_process / kill_process / list_processes |
| `l4_screenshot_hands.py` | 167 | take_screenshot / region_screenshot |
| `l4_system_hands.py` | 328 | shutdown / restart / sleep / lock |
| `l4_system_info_hands.py` | 167 | cpu_usage / mem / disk / battery |
| `l4_terminal_hands.py` | 103 | run_command in PowerShell / cmd |
| `l4_text_hands.py` | 248 | read_file / write_file / append_file |
| `l4_txt_writer_hands_generated.py` | 39 | (auto-generated) |
| `l4_url_launcher_hands.py` | 76 | open URL in browser |
| `l4_video_upload_hands.py` | 500 | YouTube / Bilibili 视频上传 |
| `l4_watcher_hands.py` | 739 | 文件 watch / 目录 watch / event hook |
| `l4_web_hands.py` | 116 | http_get / http_post |
| `l4_window_hands.py` | 341 | focus_window / minimize / maximize / list_windows |
| `monitor_hands.py` | 57 | monitor 相关 |

**TODO**: 写 `docs/JARVIS_HANDS_REFERENCE.md` 列每个 hand 的 commands + params + return + 例子. (Phase 1 重构后做.)

---

## 5. 持久化 storage map (87+ file)

### 5.1 主 store (Source of Truth)

| 文件 | 类 | 内容 |
|---|---|---|
| `jarvis_config/sir_profile.json` | Identity | Sir 核心画像 (work_rhythms / unit_preferences / health_targets / ...) |
| `memory_pool/jarvis_memory.db` | Events + Commitments | TaskMemories + Commitments + ProjectTimeline + CorrectionMemory (sqlite) |
| `memory_pool/concerns.json` | Concerns | active concerns + signals |
| `memory_pool/relational_state.json` | Relations | inside_jokes + unfinished + threads |
| `memory_pool/sir_status.json` | State | Sir 当前状态 (sleeping / online / etc.) |
| `memory_pool/sir_milestones.json` | Identity | Sir lifetime milestones |
| `memory_pool/jarvis_promise_log.json` | Commitments | Jarvis 自承诺 |

### 5.2 Vocab (40+, 准则 6 持久化范式)

`*_vocab.json`: 主脑/sentinel 用的 keyword/pattern 词表, 配 `scripts/<X>_dump.py` CLI + L7 Reflector LLM-propose:
- `concern_keywords` / `concern_dismiss` / `concern_summon`
- `behavior_inference` / `commitment_conditional` / `correction_dispatcher`
- `sleep_cancel` / `wake_filler` / `proactive_care_cooldown`
- ... (~40)

### 5.3 Reflector queue + audit log

| 类 | 文件 | 用途 |
|---|---|---|
| Review | `concerns_review.json` / `directive_review.json` / `relational_review.json` / `profile_review.json` | Sir 拍板待审 |
| Audit | `mutation_receipts.jsonl` / `profile_corrections.jsonl` / `claim_revisions.json` / `claim_stats.json` / `integrity_audit.jsonl` / `main_brain_meta_audit.jsonl` / `intent_resolver_telemetry.json` / `preflight_stats.jsonl` / `key_router_reset_audit.jsonl` / `system_errors.jsonl` | 审计 |
| Snapshot | `sir_acked_state.json` / `stand_down_state.json` / `screen_snapshot.json` / `key_router_state.json` / `key_router_health.json` | 短期状态 |
| Cooldown | `proactive_care_cooldown_vocab.json` / `recent_nudges.jsonl` / `sir_status_vocab.json` / `gate_mode_vocab.json` | nudge 节流 |
| History | `screen_history.jsonl` / `stm_recent.jsonl` / `progress_logs.json` / `pending_callbacks.jsonl` / `mutation_dump.jsonl` / `stand_down_history.jsonl` / `jarvis_health_history.jsonl` | 历史滚动 |

详 `docs/JARVIS_MEMORY_UNIFICATION_REFACTOR.md` §2 audit.

---

## 6. 35 个 design doc 索引 (按重要性)

### 6.1 ⭐⭐⭐ 必读 (Jarvis 灵魂 + 章程)

| Doc | 内容 |
|---|---|
| `AGENTS.md` | Agent 入口章程 — 8 准则 + 30 秒读什么 |
| `JARVIS_WORKFLOW_PROTOCOL.md` | Workflow 总章程 — Trace ID / 提交 / 测试纪律 |
| `JARVIS_PYTHON_STYLE.md` | py 风格 + import / marker / forbidden |
| `JARVIS_INTEGRITY_STACK.md` | INTEGRITY ABSOLUTE 言出必行栈 |
| `JARVIS_SOUL_DRIVE.md` | SOUL & DRIVE 灵魂与驱动 5 Layer (Layer 0/1/2/3/4/5) |

### 6.2 ⭐⭐ 核心架构 (重构 / sub-system 设计)

| Doc | 内容 |
|---|---|
| `JARVIS_MEMORY_AND_MUTATION_REFACTOR.md` | 692 行 — 6 层抽象 + MemoryGateway + correction_dispatcher (P2-Gap7) |
| `JARVIS_MEMORY_UNIFICATION_REFACTOR.md` | **本次起草** — 6 source 统一 + cascade engine (Phase 0-6) |
| `JARVIS_MUTATION_INTERFACE.md` | mutation organ 接入协议 |
| `JARVIS_SENSOR_TO_SWM_ARCHITECTURE.md` | 三维耦合 sensor → SWM → 主脑 |
| `JARVIS_TOM_SIR_MENTAL_MODEL.md` | Theory of Mind — Sir 此刻心智模型 |
| `JARVIS_INTENT_RESOLVER_REFACTOR.md` | IntentResolver β.5.44 重构 |
| `NERVE_SPLIT_PLAN.md` | central_nerve / chat_bypass 拆分计划 (未执行) |
| `PROMPT_REFACTOR_PLAN.md` | prompt builder + L0/L1/L2 减肥 |

### 6.3 ⭐ 子系统设计

| Doc | 内容 |
|---|---|
| `JARVIS_PROACTIVE_CARE_ENGINE.md` | ProactiveCare 主动关怀 |
| `JARVIS_VISION_INTEGRATION.md` | ScreenVision Engine |
| `JARVIS_REPLY_PREFLIGHT.md` | reply 前 self-check |
| `JARVIS_PREDICATE_COMMITMENT.md` | Predicate-driven commitment |
| `JARVIS_REJECT_LEARNER_L8.md` | L8 Reject Learner |
| `JARVIS_DIRECTIVE_SELF_AWARENESS.md` | Directive 自反 + evaluator |
| `JARVIS_PERSONA_EVOLUTION.md` | PERSONA 演化 |
| `JARVIS_MEMORY_REFACTOR.md` | 老 memory refactor (历史) |
| `JARVIS_SOUL_UNIVERSALIZATION.md` | Soul 泛化 |
| `JARVIS_TEASE_AND_TOOL_CHANNEL_DESIGN.md` | tease + tool channel |
| `JARVIS_VOICE_PIPELINE_LATENCY.md` | 语音管线延迟优化 |
| `JARVIS_PROACTIVITY_NEXT.md` | 主动性下一步 |
| `JARVIS_BASIC_ELECTRONICS_PLAN.md` | (子项目) |

### 6.4 Audit / Gap analysis (历史快照)

| Doc | 内容 |
|---|---|
| `JARVIS_AGENTS_GAP_ANALYSIS_2026_05_20.md` | 5/20 gap audit |
| `JARVIS_DEEP_AUDIT_2026_05_20.md` | 5/20 深度 audit |
| `JARVIS_FOUNDATION_AUDIT_2026_05_17.md` | 5/17 基础 audit |
| `ARCHITECTURE_AUDIT_2026_05_16.md` | 5/16 架构 audit |
| `JARVIS_P5_FINAL_REPORT_2026_05_21.md` | P5 最终报告 |
| `SYSTEM_BLIND_SPOTS_20260523_*.md` | 5/23 系统盲点 |
| `SOUL_FULL_ABLATION_20260517_*.md` | 5/17 Soul ablation |

### 6.5 Agent handoff / kickoff (Sir 给下一 agent)

| Doc | 内容 |
|---|---|
| `AGENT_HANDOFF_PROTOCOL.md` | 跨 agent 交接 |
| `AGENT_HANDOFF_BETA5_REAL_TEST.md` | β.5 真测交接 |
| `AGENT_KICKOFF_INTEGRITY_STACK.md` | INTEGRITY 立项 |
| `AGENT_KICKOFF_PROMPT.md` / `_TEMPLATE.md` | kickoff 模板 |
| `JARVIS_FUTURE_VISION_DESKTOP_COPILOT.md` | 远景 |
| `JARVIS_DASHBOARD_*.md` | dashboard 设计 |

---

## 7. 数据流 — Sir 一句话 → reply 全流程

```
Sir 说话
   │
   ▼
[Layer 1 ASR]  jarvis_sensors.VoiceListenThread
   │ 语音 → 文本 (Whisper / Azure)
   ▼
[Trace]  jarvis_utils.TraceContext.new_turn() → turn_<id>
   │
   ▼
[Layer 2 Worker]  jarvis_worker.handle_text_ready
   │
   ├─→ ScreenVision.async_describe (并发, 截图 + Gemini Vision)
   ├─→ Gatekeeper LLM (commitment / cancel 检测)
   ├─→ MemoryCorrectionGuard (教正语义)
   └─→ chat_bypass.stream_chat
        │
        ▼
   [Layer 3 prompt 装配]  jarvis_central_nerve._assemble_prompt
        │
        ├─→ PERSONA (~7400 char)
        ├─→ MY SELF / SOUL block (concerns / relational / attention)
        ├─→ SirMentalState (ToM)
        ├─→ ProfileCard render
        ├─→ Hippocampus search_memory (LTM)
        ├─→ STM (last 30 turn)
        ├─→ ScreenVision snapshot
        ├─→ Sensor State block (键鼠 / window / idle)
        ├─→ SWM evidence (to_swm_block)
        ├─→ [WATCH TASK FIRED] / [INTEGRITY WATCHER] / [RECENT COMPLETED] (fix82-X) / ...
        ├─→ 30+ render block 的其他 (sir_status / stand_down / project_hold / ...)
        ├─→ L2 directives 条件 inject (130+ 条筛 ~10 注入)
        └─→ STM SOURCE TAGS + INTEGRITY 红线
        │
        ▼ ~25K-36K char
   [Layer 4 主脑]  Gemini-3-Pro/Flash via KeyRouter (key_router.get_key)
        │ stream
        ▼
   [Layer 5 stream parse]  chat_bypass 实时检测
        │
        ├─→ <FAST_CALL>...</FAST_CALL>
        │   ├─→ organ='mutation' → MemoryGateway.update_sir_field → 6-layer routing
        │   ├─→ organ='memory_hands' / 'profile' / etc. → l4_*.py hands
        │   └─→ organ='concerns' / 'stand_down' / 'progress' / ... → 各 organ
        │
        ├─→ ZH/EN bilingual split (---ZH---)
        ├─→ continuation_prompt (主脑看 tool result 续 stream)
        │
        ▼
   [Layer 6 后处理]
        │
        ├─→ ClaimTracer 抓 claims + verify
        ├─→ IntegrityWatcher 后台 retry
        ├─→ SoulReflector 异步 update concerns signals
        ├─→ STM persist + Hippocampus seal_memory_async
        ├─→ Reply Feedback collect
        │
        ▼
   [Layer 7 输出]
        │
        ├─→ TTS (jarvis_vocal_cord)
        └─→ UI (jarvis_ui PyQt5 — Orb 动画 / 字幕)
        │
        ▼
   Sir 听到 / 看到
```

---

## 8. 文档化 gap (本 audit 发现的 todo)

| Gap | 影响 | 建议 doc |
|---|---|---|
| 90+ py 主模块约 60 个无专 doc | 复杂模块设计藏在代码里 | 不必每个模块 1 doc, 用本 map + 模块 docstring 即可 |
| 25 hands **全无 docstring + 无 md** | 执行层最不文档化 | **`docs/JARVIS_HANDS_REFERENCE.md`** (TODO Phase 1 后) |
| `jarvis_utils.py` 4861 行无 docstring 但含 SWM 核心 | 数据耦合枢纽未文档化 | **`docs/JARVIS_SWM_AND_UTILS.md`** (高优先) |
| `jarvis_chat_bypass.py` 5960 行无专 doc | stream_chat 流程藏在代码 | 含在 `NERVE_SPLIT_PLAN.md` 内, 待拆分时写 |
| `jarvis_worker.py` 5823 行无专 doc | 工作流复杂 | 同上 |
| 30+ Reflector 各自 1 个无专 doc | 自反 daemon 散落 | 1 个 `docs/JARVIS_REFLECTOR_INDEX.md` 总索引 |
| 87 storage file 无统一 schema doc | 持久化不可控 | 在 memory unification refactor 内合并 |

**建议明日补**:
1. `docs/JARVIS_SWM_AND_UTILS.md` — 详 ConversationEventBus + utils 核心 API
2. `docs/JARVIS_HANDS_REFERENCE.md` — 25 hands 完整 commands/params 手册
3. `docs/JARVIS_REFLECTOR_INDEX.md` — 30+ reflector daemon 索引

这 3 篇加上本 map = **完整 Jarvis 架构知识库**.

---

## 9. 给 Agent 的导航指南

> 进窗口前 30 秒: 读 `AGENTS.md` + 本 doc 的 §1 (TL;DR 图) + §2 (5 枢纽) = ~3 min 全景导航.

**不同任务读什么**:

| 任务 | 必读 |
|---|---|
| 改记忆系统 | 本 doc §3.3 + `MEMORY_AND_MUTATION_REFACTOR.md` + `MEMORY_UNIFICATION_REFACTOR.md` |
| 改主脑 prompt | 本 doc §2.2 + `PROMPT_REFACTOR_PLAN.md` + `JARVIS_DIRECTIVE_SELF_AWARENESS.md` |
| 改 Soul 系统 | `SOUL_DRIVE.md` (5 Layer 详) |
| 改 sensor / sentinel | `SENSOR_TO_SWM_ARCHITECTURE.md` + 本 doc §3.8 |
| 加 hand | (todo) `JARVIS_HANDS_REFERENCE.md` + l4_<existing>_hands.py 模仿 |
| INTEGRITY 相关 | `JARVIS_INTEGRITY_STACK.md` + 本 doc §3.5 |
| Vision | `JARVIS_VISION_INTEGRATION.md` + `jarvis_screen_vision.py` |
| 看 Sir 痛点历史 | `TODO.md` + `docs/TODO_ARCHIVE.md` (200KB) Grep |

---

## 10. 准则 6 三维耦合在本 map 的体现

- **数据强耦合**: 6 source → SWM → 主脑 — 1 处看全 evidence
- **行为弱耦合**: 30+ Reflector / 23 Sentinel publish-only, 不硬决策
- **决策集中**: 主脑 1 处看, 自决 reaction. python regex 覆盖不到 → L7 Reflector LLM-propose vocab + Sir 拍板.

---

*本 doc 由 Sir + Cascade 2026-05-23 22:45 起草.*
*目标: 1 篇 md 让 Sir / 任何 agent 看全 Jarvis 90 模块.*
*与 `AGENTS.md` (章程) + 6 个 ⭐⭐⭐ doc (灵魂) + `MEMORY_UNIFICATION_REFACTOR.md` (重构计划) 配合, 构成完整知识库.*
