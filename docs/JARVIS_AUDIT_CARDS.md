# JARVIS Audit Cards (Phase A.1)

> Phase A 模块审计集中文档. 每模块 1 张 card. 按 `JARVIS_GRAND_REFACTOR.md` §4 批次顺序.
>
> **进度**: 1/140 (0.7%) — 批次 a (5 核心枢纽) 进行中.
>
> **使用**: 任何 agent 写新 card → 追加到本文末尾 + 更新 `JARVIS_GRAND_REFACTOR.md` §6.2.

---

## 批次 a: 5 核心枢纽

### #1 `jarvis_nerve.py` (329 行) — 主入口 __main__ + 转发垫层

**职责**: 启动 Jarvis (PyQt5 main loop + 实例化全部 component + 线程 wiring). 兼容旧 import (`from jarvis_nerve import X`) 通过转发垫层.

**核心 method / class**:
- `__main__` (line 238-329) — 启动序列, 顺序极重要:
  1. `multiprocessing.freeze_support()` (Windows EXE)
  2. `TraceContext.init_session()` → `sess_YYYYMMDD_HHMMSS_<PID>` (后续 bg_log 自动带前缀)
  3. `load_keys()` 从 `.env` 读 API key
  4. 实例化 `KeyRouter(main_brain, google_list, openrouter_list)`
  5. `key_router.probe_google_keys_at_startup(async_mode=True)` (2s 后检测 Google key 健康)
  6. `QApplication(sys.argv)` PyQt5 主 app
  7. `BreathingLightUI()` 实例化 Orb UI
  8. `JarvisWorkerThread(api_key, gemini_key, key_router)` 实例化 worker (内含 `CentralNerve`)
  9. wire `jarvis_worker.state_changed → ui.change_state`
  10. `jarvis_worker.start()`
  11. `SubtitleOverlay(ui)` + 注入到 chat_bypass.subtitle_queue
  12. `ScreenshotSentinel()` + `UserStatusLedgerSentinel(...)` 启动
  13. 连接 `jarvis.conductor / reflection_scheduler / commitment_watcher` 等 attr
  14. 共享 `HumorMemory` 单例 (避免双实例)
  15. `VoiceListenThread()` 启动 + wire 信号 (text_ready/interrupt/awake)
  16. 双向 wire voice_worker.state ↔ jarvis_worker.state ↔ `AttentionSlot` 共享
  17. `voice_worker.start()` + `app.exec_()`

**数据**:
- 读: `.env` (`load_keys` from `jarvis_config/keys.py`) — `OPENROUTER_MAIN` / `GOOGLE_LIST` / `OPENROUTER_LIST` / `GEMINI`
- 写: 进程内全局 — UI / worker / voice_worker / sentinel 实例
- SWM publish: 通过 `TraceContext.init_session()` 间接 (subsequent bg_log)

**上游 (谁调它)**: 无 (本身是 `__main__` 入口) — Sir 运行 `python jarvis_nerve.py`

**下游 (它调谁, 32 个 import)**:
- 转发垫层 import (~25 个老 module, e.g. `KeyRouter` / `PhysicalEnvironmentProbe` / `ChronosTick` / `ChatBypass` / `CentralNerve` / `Worker` / `UI` / ...)
- 启动 wiring 实际调: `KeyRouter` / `BreathingLightUI` / `JarvisWorkerThread` / `SubtitleOverlay` / `ScreenshotSentinel` / `UserStatusLedgerSentinel` / `VoiceListenThread` / `AttentionSlot` / `TraceContext`

**跟记忆的耦合**:
- 直接写: 无
- 直接读: 无
- 间接耦合: 启动时实例化 `CentralNerve` (含 `ProfileCard` / `Hippocampus` / `ConcernsLedger` / `CommitmentWatcher` / ...) — **本模块是所有记忆 component 的 owner / lifecycle 入口**

**跟其他模块的耦合**:
- `jarvis_central_nerve.py`: 实例化 `CentralNerve` (通过 Worker)
- `jarvis_chat_bypass.py`: 通过 `jarvis_worker.jarvis.chat_bypass` 间接 wire `subtitle_queue`
- `jarvis_worker.py`: `JarvisWorkerThread` 是主 Worker
- `jarvis_ui.py`: `BreathingLightUI` + `SubtitleOverlay`
- `jarvis_utils.py`: `TraceContext` + `AttentionSlot` + `safe_gemini_call` 等
- `jarvis_config/keys.py`: `.env` loader
- `l1_right_brain.py` / `l3_left_brain.py` / `l5_reflection_brain.py`: 老 3-brain 架构 import (实际可能未用, **待审**)

**已知问题 / TODO marker**:
- Line 28-49: 重复 import + 历史遗留 (`speech_recognition` / `funasr` / `comtypes` / `PIL.ImageGrab` 等, 可能现状不全用)
- Line 51: `# [C1-7] 删除未使用的 difflib import` — 历史 cleanup 标记
- Line 70-71: 已 deprecated 的重复 import 标 cleanup
- Line 73-74: **硬编码 HTTP_PROXY=127.0.0.1:7890** — Sir 个人代理, EXE 部署时会失效
- Line 58-60: `l1_right_brain` / `l3_left_brain` / `l5_reflection_brain` 老 3-brain 架构, **可能已废弃需 audit**
- Line 62: `ProactiveShield` / `SkillTreeTracker` / `ProactiveCompanion` from `jarvis_enhanced.py` — `enhanced.py` 无 docstring, **可能历史遗留**

**关联 design doc**: 无专 doc (本模块是薄垫层). `JARVIS_ARCHITECTURE_MAP.md` §3.1 提到.

**重构含义 (Phase B 设计参考)**:
- **保留**: __main__ 启动序列 (已稳定)
- **可优化**:
  - 启动 wiring 太多手动 attr 注入 (line 268, 274-300) — 应集中 `CentralNerve.wire_dependencies()` 一处管
  - `l1/l3/l5_brain` import 可能 deprecated — Phase A.5 历史审时确认
  - `jarvis_enhanced.py` 是否真在用 — 同上
- **不动**: TraceContext / KeyRouter / 转发垫层 (老代码兼容)

**审计结论**: 入口模块, 行少, 大部分是 wire. 重构关注点是 wiring 集中化 + 旧 brain 清理. 不在记忆系统主线.

---

### #2 `jarvis_utils.py` (4862 行) — **核心工具 + ⭐ ConversationEventBus (SWM 数据强耦合枢纽)**

**职责**: 全 Jarvis 共享工具库. 含 **SWM 核心** (ConversationEventBus) + Trace ID + LLM 调度装甲 + Attention + WorkingMemory + 状态机 + ANSI / 日志 / TTS Echo 防回灌 等 20+ class 50+ 函数. 是**所有模块的依赖底座**.

**核心 class** (按重要性排序):

| L | class | 1 句话 | 重要性 |
|---|---|---|---|
| 1270 | **`ConversationEventBus`** | **SWM (SharedWorldModel) 数据强耦合枢纽** — publish/recent_events/top_n/to_swm_block | ⭐⭐⭐ |
| 613 | **`TraceContext`** | 进程级 session_id + turn_id 生成 + bg_log 自动注入 | ⭐⭐⭐ |
| 2993 | **`JarvisState`** | 中央状态机 (ready/listening/thinking/speaking/focused) | ⭐⭐ |
| 1812 | **`WorkingMemoryFeed`** | 30min 环境快照 (窗口 / 剪贴板 / 终端命令) | ⭐⭐ |
| 1751 | **`AttentionSlot`** | Layer 3 — Sir 说话当下的注意力快照 (单槽 + 8s TTL) | ⭐⭐ |
| 2084 | **`PlanLedger`** | Sir 计划账本 (跨 session 持久化) | ⭐⭐ |
| 3717 | `QuickClassifier` | 短语快速分类 (cache + LLM fallback) | ⭐ |
| 3167 | `ApiRateLimiter` | API 速率限制器 | ⭐ |
| 3488 | `LocalLLMFallback` | 本地 LLM 兜底 (无网络时) | ⭐ |
| 2548 | `ToneSelector` | 主脑 reply tone 选择 | ⭐ |
| 2671 | `AntiCommonPhraseTracker` | 反陈词滥调追踪 | ⭐ |
| 2800 | `VerbosityPreferenceTracker` | Sir 偏好长短追踪 | ⭐ |
| 4469 | `ProjectContextProbe` | 当前项目识别 (git root / cwd) | ⭐ |
| 4623 | `SessionDigest` | session 结束摘要 | ⭐ |
| 1915 | `ClipboardWatcher` | 剪贴板变化监听 | ⭐ |
| 1990 | `PSHistoryWatcher` | PowerShell 历史命令 watch | ⭐ |
| 1047 | `_TTSEchoRing` | 防 TTS 自言自语回灌 (Sir 听不到 Jarvis 自己) | ⭐ |
| 485 | `_BgLogBuffer` | bg_log 缓冲层 (避免 print 漏到对话框) | ⭐ |
| 231 | `_TeeStream` | Tee print → file + stdout | basic |
| 54 | `_ANSI` | ANSI 颜色常量 | basic |

**核心 function** (50+, 重要的):

| L | func | 1 句话 |
|---|---|---|
| 908 | `bg_log(msg)` | **关键日志 API** — auto-prefix `[sess_xxx][turn_yyy]` (TraceContext 注入), 不漏到对话框 |
| 1201 | `get_event_bus()` | SWM 全局单例获取 (lazy init) |
| 3147 | `get_default_event_bus()` | 同上 alias |
| 3298 | **`safe_gemini_call(...)`** | **核心 LLM 装甲** — KeyRouter + retry + non-retryable detection + Quota fallback |
| 4220 | `safe_openrouter_call(...)` | OpenRouter 装甲 (类似但走 openrouter) |
| 3713 | `get_local_fallback()` | 本地 LLM fallback singleton |
| 3158 | `create_genai_client()` | google-genai client 创建 (key 轮换内置) |
| 3256 | `network_retry` decorator | 网络重试装甲 |
| 1224 | `read_gate_mode()` | gate_mode_vocab.json 读 (sentinel hard/soft/publish_only) |
| 4394 | `extract_open_threads(stm)` | STM → 未完话题抽取 |
| 4574 | `render_project_block` | prompt block — 当前 project context |
| 4703 | `render_yesterday_block` | prompt block — 昨日 highlights |
| 4721 | `render_open_threads_block` | prompt block — 未完话题 |
| 4764 | `render_active_reminders_block` | prompt block — 活跃 reminders |
| 1163 | `register_jarvis_tts(text)` | TTS echo ring 注册 (防 Jarvis 听到自己) |
| 1168 | `is_recent_jarvis_echo(text)` | 检测 Sir input 是不是 TTS echo |

**ConversationEventBus 详细 (⭐⭐⭐ SWM 核心)**:

```python
# 已注册 etype 数: ~40+ (横跨 sensor/sentinel/reflector/intent_resolver/integrity/...)
# 完整列表见 DEFAULT_TTL dict (L1276-1328) + DEFAULT_SALIENCE dict (L1333-1380)

# 核心 etype 分类:
# ── 主脑必看 (salience ≥ 0.85):
#    intent_resolved (0.90), commitment_overdue (0.95), hallucination_detected (0.92),
#    manual_standby (0.90), tool_called (0.85)
# ── 重要 (salience 0.7-0.84):
#    reply_interrupted (0.75), system_error_visible (0.75), active_window_hung (0.70),
#    sir_watch_request_proposed (0.70), tool_chain_circuit_broken (0.78),
#    soft_focus_active (0.70), sleep_intent_declared (0.85)
# ── 一般 (salience 0.4-0.69):
#    concern_active (0.65), commitment_detected (0.80), gate_advice (0.55),
#    afk_return (0.55), sir_progress_evidence (0.65), sir_intent_*_candidate (0.50-0.60),
#    proactive_nudge (0.50), tool_executed (0.50), conversation_event (0.55)
# ── 背景 (salience 0.1-0.39):
#    sensor_change (0.30), jarvis_state (0.30), nudge_window_advice (0.35),
#    persona_note (0.40), utterance_appended (0.20)

# 核心 method:
.publish(etype, description, ttl=None, source='unknown', metadata=None, salience=None)
   - 8s 去重 (etype + desc[:60] 指纹)
   - max_events=60 (deque maxlen)
.recent_events(within_seconds, types)
.top_n(n=12, types, within_seconds, salience_floor=0.0)
   - score = salience × 0.7 + recency × 0.3
   - recency = e^(-age/180) (3min halflife)
.to_swm_block(n=12, max_chars=800, salience_floor=0.3, critical_salience=0.85)
   - 智能截断: critical (≥0.85) 强制保留, 低 salience 优先扔
.has_type(etype, within_seconds) — 快速判
.register_global(bus_instance) — 单例注册
```

**TraceContext 详细 (⭐⭐⭐ 可追溯性)**:

```python
TraceContext.init_session() → sess_YYYYMMDD_HHMMSS_<PID> (进程级)
TraceContext.new_turn() → turn_YYYYMMDD_HHMMSS_<4hex> (对话级)
TraceContext.current_session() / current_turn() — getter
TraceContext.set_turn(tid) — 接收外部 ID

bg_log(msg) → 自动 prefix `[sess_xxx][turn_yyy] msg` 写到 docs/runtime_logs/jarvis_<sess_id>.log
```

**数据**:
- 读: `memory_pool/gate_mode_vocab.json` (read_gate_mode)
- 写: `docs/runtime_logs/jarvis_<sess>.log` (TeeStream + _BgLogBuffer)
- 维护: 进程内全局 — `_GLOBAL_EVENT_BUS` (SWM 单例) / `_TTSEchoRing` / 各 default tracker
- SWM publish: 不直接 publish, 但提供 publish API 给所有 module 用

**上游 (谁 import 它 — 几乎全 Jarvis)**:
- 真测: `grep "from jarvis_utils import" *.py` → ~85+ 文件 import 它
- 关键 callers: `central_nerve` / `chat_bypass` / `worker` / 全部 sentinel / 全部 reflector / 全部 hand

**下游 (它调谁)**:
- `jarvis_key_router` (safe_gemini_call 内部)
- `google.genai` / `openai` (SDK)
- `win32gui` / `win32process` / `win32api` (capture_attention_snapshot)
- `requests` (LocalLLMFallback)
- 几乎不调其他 jarvis_*.py (是底座, 不是 caller)

**跟记忆的耦合**:
- 直接写: 无 (utils 不持久化记忆)
- 直接读: `memory_pool/gate_mode_vocab.json` (read_gate_mode)
- 间接耦合: **极重** — ConversationEventBus 是**所有记忆 mutation 的 SWM publish 通道**:
  - `MemoryGateway._publish_swm()` 调它
  - `ProfileCard.overwrite_field()` publish 'sir_profile_overwritten'
  - `CommitmentWatcher.add_commitment()` publish 'sir_intent_deadline_candidate'
  - `Hippocampus.add_completed_event()` (fix82-X) publish 'completion_cascaded'
  - 所有 mutation source 都通过 SWM 让主脑下轮看到 evidence

**跟其他模块的耦合**:
- **底座级** — 全 Jarvis 90+ 模块都依赖 utils
- 关键 attr 注入: `voice_worker._attention_slot` / `jarvis_worker._attention_slot` / `jarvis._attention_slot` 都共享 utils.AttentionSlot 实例

**已知问题 / TODO marker** (grep "TODO" / "FIXME" / "BUG"):
- `DEFAULT_TTL` + `DEFAULT_SALIENCE` 字典硬编码 40+ etype (L1276-1380) — **小违 §6 准则 6 持久化原则**, 但实际可能合理 (~40 etype 用 json 反而难维护. 待 Phase B 设计判)
- `_dedupe_window=8.0` 硬编码 (L1387) — 对所有 etype 同 8s 去重, 没分类 (e.g. critical event 应允许更密)
- `max_events=60` deque (L1382) — 超过最早被丢, 跨 session 不持久化 → **重启丢全部 SWM evidence**
- L1467-1482 `type_priority` dict 硬编码 (legacy `to_prompt_block`, 已被 `to_swm_block` 替) — 可清
- 4861 行无 module-level docstring → audit 时已发现, **Phase A 后期补 docstring**

**关联 design doc**:
- `JARVIS_SENSOR_TO_SWM_ARCHITECTURE.md` (β.5.37) — SWM 三维耦合设计, 但**没专细到 EventBus API**
- `AGENTS.md` §3 Trace ID 体系 — 提 TraceContext
- `JARVIS_ARCHITECTURE_MAP.md` §2.5 — 提及但未深入

**重构含义 (Phase B 设计参考)**:

⭐ **utils.py 是 Jarvis 的中枢神经核心**, 重构必须谨慎:

- **保留 + 强化**:
  - ConversationEventBus 是 SWM 唯一 truth — 任何记忆 refactor 必须**经过它**
  - TraceContext 是诚信审计的基石 (每条 audit / mutation 必带 turn_id)
  - safe_gemini_call 是 LLM 装甲, 不可绕

- **应该改进**:
  - SWM 跨 session 不持久化 — Phase D 应加可选 `swm_history.jsonl` (当前重启丢 60 event)
  - DEFAULT_TTL/SALIENCE 硬编码 → 可迁 `memory_pool/swm_etype_config.json` + L7 Reflector LLM-propose 新 etype
  - 4861 行单文件应拆 (e.g. `jarvis_swm.py` / `jarvis_trace.py` / `jarvis_llm_armor.py`)

- **跟 Memory Refactor 关系**:
  - **utils.ConversationEventBus 是 MemoryHub 的下游 publish 通道** — refactor 不重写, 只增加 publish 类型
  - **utils.TraceContext 是 MemoryRecord.turn_id 的来源** — 不动
  - **utils.WorkingMemoryFeed + AttentionSlot** 应纳入"State source" (E 类) 的 component, 不重写

**审计结论**: utils.py 是 Jarvis **数据耦合的中枢**. 真重构记忆系统 = 重写 utils 大半 (尤其 ConversationEventBus). 但**应增强不应推翻** — 已有 SWM 设计经历 β.5.0-A 真正经验积累. Phase B 应聚焦"扩 + 拆", 不是"重写".

---

### #3 `jarvis_central_nerve.py` (5086 行) — **CentralNerve + PERSONA + _assemble_prompt (主脑大脑)**

**职责**: Jarvis 主大脑控制器. 持有所有 sub-component 实例 (30+) + 装配每轮主脑 prompt + STM 管理 + Sleep 模式 + 主循环. **CentralNerve 实例是 Jarvis 系统的中心节点**, 90% 主模块都通过它访问其他.

**核心 class** (仅 1 个):

| L | class | 1 句话 |
|---|---|---|
| 251 | **`CentralNerve`** | 主大脑控制器 (持有 30+ component + 装配 prompt + STM + Sleep) |

**核心 method** (按重要性排序):

| L | method | 功能 | 行数 | 重要性 |
|---|---|---|---|---|
| 259 | **`__init__`** | 实例化 30+ component (Hippocampus / ProfileCard / Concerns / Relational / SelfAnchor / EventBus / SoulEval / SoulReflector / SkillRegistry / Directives / StandDown / PlanLedger / WorkingMemoryFeed / ...) | ~950 行 | ⭐⭐⭐ |
| 1495 | **`_assemble_prompt`** | 装配每轮主脑 prompt (PERSONA + 30+ render block, ~25K-36K chars) | ~2500 行 | ⭐⭐⭐ |
| 4289 | `run` | 主循环 — process_command + 调 chat_bypass.stream_chat | ~400 行 | ⭐⭐ |
| 4018 | `_build_nudge_prompt` | nudge 专用 prompt 装配 | ~50 行 | ⭐⭐ |
| 4008 | `_build_time_persona` | 动态时间 PERSONA (含 day-of-week / 当前小时) | ~10 行 | ⭐ |

**STM 管理 method**:

| L | method | 功能 |
|---|---|---|
| 1287 | `push_command` | 接收 Sir 命令进 STM |
| 1317 | `_calc_importance` | STM 单条 importance 评分 |
| 1336 | `_compress_stm_if_needed` | STM 超 30 条压缩 |
| 1355 | `_append_stm` | append + dirty flag + publish 'utterance_appended' SWM |
| 1392 | `_restore_stm_from_disk` | 启动时 restore (β.4.10) |
| 1437 | `_persist_stm_to_disk` | atomic dump 整 STM 到 `memory_pool/stm_recent.jsonl` |
| 1472 | `_start_stm_persist_daemon` | 30s tick daemon 持续 dump |
| 1223 | `_restore_short_term_memory` | 老路径 (可能 deprecated) |
| 1262 | `_restore_task_snapshot` | 启动 restore active task |

**Sleep + Wake 模式**:

| L | method | 功能 |
|---|---|---|
| 4672 | `_detect_sleep_intent` | Sir 表态睡眠语义检测 |
| 4703 | `_detect_deep_sleep_request` | 深睡 (TTS off + nudge off) |
| 4709 | `_trigger_sleep_mode` | 进入睡眠模式 |
| 4738 | `_detect_wake_up` | Sir 唤醒语义 (e.g. 早安) |
| 4750 | `_on_activity_wake` | 物理 input 激活 (键鼠 / 屏幕动) |
| 4766 | `_check_short_sleep` | 短睡确认 (< 30min 不算真睡) |
| 4823 | `_trigger_end_of_day_archive` | 每日结束归档 |

**热重载 + 其他**:

| L | method | 功能 |
|---|---|---|
| 4068 | `_init_soul_router` | SoulRouter 实例化 |
| 4079 | `preload_session_context` | 预热 session (启动后异步预查) |
| 4146 | `_process_concurrent_interruption` | Sir 打断主脑 stream 时 |
| 4263 | `_set_state` | 状态设 (调 JarvisState) |
| 4267 | `_hot_reload_organs` | 热重载 hands + eyes manifest |
| 4904 | `_duck_task` | task ducking (后台任务 mute browser) |

**`__init__` 实例化的 30+ component** (这是耦合枢纽 — 任何 audit 必查):

| 类别 | attr | 类型 | 持久化 |
|---|---|---|---|
| **Soul Layer 0** | `self.self_anchor` | `SelfAnchor` | (内存) |
| **Soul Layer 1** | `self.concerns_ledger` | `ConcernsLedger` | `concerns.json` |
| **Soul Layer 2** | `self.relational_state` | `RelationalState` | `relational_state.json` |
| **Soul Layer 3** | (no attr) | `build_attention_block` helper | (动态) |
| **Soul Layer 4** | `self.concerns_reflector` / `self.weekly_reflector` | Reflector daemons | (内存) |
| **Soul Layer 5** | `self.soul_evaluator` | `SoulAlignmentEvaluator` | (内存) |
| **ToM** | (待审 `self.sir_mental_model` 待 #11) | `SirMentalModel` | `sir_mental_state.json` |
| **记忆** | `self.hippocampus` | `Hippocampus` | sqlite + jsonl |
| **记忆** | `self.profile_card` | `ProfileCard` | `sir_profile.json` |
| **记忆** | `self.memory_gateway` | `UnifiedMemoryGateway` (注意 — **跟 MemoryMutationGateway 同名但不同 class**, 见 audit gap §) | (代理) |
| **记忆** | `self.short_term_memory` | list (max 30) | `stm_recent.jsonl` |
| **记忆** | `self.plan_ledger` | `PlanLedger` | `memory_pool/plans.json` |
| **记忆** | `self.working_feed` | `WorkingMemoryFeed` | (30min 内存 TTL) |
| **SWM** | `self.event_bus` | `ConversationEventBus` | (内存) |
| **状态** | `self.state` | `JarvisState` | (内存) |
| **承诺** | `self.commitment_watcher` | 后续 wire by `jarvis_nerve.__main__` |  |
| **承诺** | `self.guardian_center.commitment_watcher` | 同上 (alias?) |  |
| **指挥** | `self.conductor` | `Conductor` (后续 wire) |  |
| **指挥** | `self.guardian_center` / `self.companion_center` / `self.prompt_center` | 3 Center (PromptCenter / GuardianCenter / CompanionCenter) |  |
| **物理** | `self.vocal` | `VocalCord` (TTS) |  |
| **物理** | `self.blood` | `JarvisBlood` (Action protocol) |  |
| **观察** | `self.context_router` | `ContextRouter` |  |
| **观察** | `self.content_tracker` | `ContentPreferenceTracker` |  |
| **观察** | `self.causal_chain` | `CausalChain` |  |
| **观察** | `self.habit_clock` | `HabitClock` |  |
| **观察** | `self.project_timeline` | `ProjectTimeline` (sqlite) |  |
| **反思** | `self.reflector` | `LlmReflector` (共享 LLM 调度) |  |
| **反思** | `self.reflection_scheduler` | (后续 wire) |  |
| **门** | `self.nudge_gate` | `NudgeGate` (90s cooldown) |  |
| **门** | `self.sleep_detector` | `SleepIntentDetector` |  |
| **3-brain (legacy?)** | `self.right_brain` / `self.left_brain` / `self.l5_brain` | RightBrain / LeftBrain / ReflectionBrain | **待审是否 deprecated** |
| **registry** | `self.eye_registry` / `self.hand_registry` / `self.eye_manifests` / `self.hand_manifests` | dict (热加载) | |
| **prompt cache** | `self.prompt_cache` | `PromptCache` | (内存) |
| **correction** | `self.correction_loop` | `CorrectionLoop` | |
| **clipboard / ps** | `self._clipboard_watcher` / `self._ps_history_watcher` | watcher thread | feed |

**`_assemble_prompt` 装配的 30+ render block** (按顺序, 详 `JARVIS_ARCHITECTURE_MAP.md` §7 数据流):

> 这是**主脑 prompt 装配的核心**, 决定主脑每轮看什么 evidence. 详细顺序见 `_assemble_prompt` 内 `_parts.append(...)` 调用链:
> 1. `_base_persona` (PERSONA 7400 chars)
> 2. `self_anchor_block` (Layer 0)
> 3. `soul_block` (Layer 1 concerns)
> 4. `relational_block` (Layer 2)
> 5. `attention_block` (Layer 3)
> 6. `reply_feedback` + `profile_corrections` + `milestones` + `recent_nudges` + `profile_card` + `sir_mental_model` + `integrity_watcher` + `memory_correction` + `watch_tasks` + `stand_down` + `sir_status` + `screen_vision` + `sir_resting` + `watch_task_trig` + `project_hold` + `error_bus` + `intent_resolver_tools` + `wake_callback` + `L2 Directives` + `[RECENT COMPLETED]` (fix82-X) + `[SENSOR STATE]` + ... + `STM SOURCE TAGS` + `INTEGRITY 红线`
> 7. `swm_block = event_bus.to_swm_block(n=12, salience_floor=0.3)` ⭐ SWM evidence

**数据**:
- 读: `sir_profile.json` (ProfileCard) / `concerns.json` (Ledger) / `relational_state.json` / `stm_recent.jsonl` / `jarvis_memory.db` (Hippocampus) / `plans.json` / `gate_mode_vocab.json` / ... (几乎所有 storage)
- 写: `stm_recent.jsonl` (STM persist) / 任务 snapshot
- SWM publish: 'utterance_appended' (STM append) / state 变化 / 其他 component 通过 self.event_bus

**上游 (谁调它)**:
- `jarvis_worker.py` 通过 `self.jarvis = CentralNerve(...)` 持有 + 调
- `jarvis_chat_bypass.py` 通过 `self.jarvis = central_nerve` 持有 (CN 实例化 ChatBypass 时传 self)
- `jarvis_nerve.py:__main__` 通过 `JarvisWorkerThread` 间接

**下游 (它调谁 — 极多)**:
- **所有 30+ component** (持有 + 调用)
- LLM (通过 `safe_gemini_call` + KeyRouter)

**跟记忆的耦合**:
- **CentralNerve 是 Jarvis 记忆 component 的 owner** — `self.hippocampus / profile_card / concerns_ledger / relational_state / memory_gateway / plan_ledger / working_feed` 全在它手里
- `_assemble_prompt` 是**主脑读所有记忆 source 的统一入口** (但分散在 30+ render block, 不是 1 个 facade)
- STM 管理 (`_append_stm` / `_persist_stm_to_disk`) — 短期记忆持久化

**跟其他模块的耦合**:
- **极重** — 是中心 owner, 全 Jarvis 依赖
- 不直接 import 90 模块, 通过 `__init__` lazy import 各 sub-component
- 暴露所有 attr 给 worker / chat_bypass / sentinel / reflector 用

**已知问题 / TODO marker**:
- `__init__` 950+ 行 — **极难维护**, NERVE_SPLIT_PLAN.md 提出拆分但未执行
- `_assemble_prompt` 2500+ 行 — **同上**
- 启动音量恢复 (L265-296) — **跟主功能无关**, 应迁到独立 utility
- L312-314 `RightBrain / LeftBrain / ReflectionBrain` 老 3-brain 架构 — **可能 deprecated** (与 `jarvis_nerve.py` 重复 import). 待 Phase A.5 确认
- L385 `UnifiedMemoryGateway` vs `MemoryMutationGateway` (jarvis_memory_gateway.py) — **同名不同 class!**:
  - `UnifiedMemoryGateway` (utils → memory_core) 是老路径
  - `MemoryMutationGateway` (P2-Gap7) 是新路径
  - **重叠**, Phase B 应合并
- 30+ component try/except 都 `(非致命)` — 启动 silent fail 会被掩盖 (audit 时已发现)
- `self.eyes / self.hands / self.env = None` (L345-347) — 显式 None, 似乎死代码
- 多处 `bg_log` + traceback 嵌套深, 可统一 helper

**关联 design doc**:
- `JARVIS_SOUL_DRIVE.md` — 灵魂 Layer 0/1/2/3/4/5 在 __init__ wire
- `NERVE_SPLIT_PLAN.md` — 拆分计划 (未执行)
- `PROMPT_REFACTOR_PLAN.md` — prompt 减肥 (部分执行)
- `JARVIS_MEMORY_AND_MUTATION_REFACTOR.md` — memory_gateway wire

**重构含义 (Phase B 设计参考)**:

⭐⭐⭐ **CentralNerve 是记忆 refactor 的核心 caller**, 几乎所有改动都涉及它:

- **必拆**:
  - `__init__` 950 行 → 拆 `__init__` 50 行 + N 个 `_init_<subsystem>()` method (NERVE_SPLIT_PLAN 已设计)
  - `_assemble_prompt` 2500 行 → 30+ render block 各自模块化, **应统一通过 `MemoryHub.read_context()`** (设想中) 入口

- **必整合**:
  - `UnifiedMemoryGateway` vs `MemoryMutationGateway` — **必须合并**
  - 30+ component 启动 wiring 应集中到 `_wire_components()` 方法

- **不动**:
  - STM persist (β.4.10 已稳定)
  - Sleep 模式逻辑 (Sir 真测稳定)
  - JarvisState integration

- **跟 Memory Refactor 关系**:
  - `_assemble_prompt` 现状 30+ render block 应**统一收敛** — 这是 Memory Unification 设计的 `read_context()` 落地点
  - `__init__` 30+ component 实例化应**整合到 MemoryHub** (统一 source of truth 实例化)
  - **CentralNerve 应变薄** — 从"30+ component owner" 变 "MemoryHub + IntentRouter + PromptBuilder 的轻协调器"

**审计结论**: central_nerve 是 Jarvis **最大单文件**, 是记忆 refactor 的**直接战场**. NERVE_SPLIT_PLAN.md 已提出但未执行 — Phase D 必落地. _assemble_prompt 30+ render block 是 Phase B 核心设计点. 必跟 utils + memory_gateway 一起重构, 不能孤立.

---

### #4 `jarvis_chat_bypass.py` (5960 行) — **stream_chat 主对话循环 + FAST_CALL 派发**

**职责**: 实际跑每轮对话的循环 — 装配 prompt → 调 LLM stream → 实时 parse `<FAST_CALL>` 标签 → dispatch organ → 拼 continuation prompt → TTS + UI emit. **是 Sir 说话后的主流程实际跑工**.

**核心 class** (仅 1 个):

| L | class | 1 句话 |
|---|---|---|
| 238 | **`ChatBypass`** | 主对话循环 + TTS pipeline + FAST_CALL dispatch (24 method) |

**核心 method** (按重要性排序):

| L | method | 功能 | 重要性 |
|---|---|---|---|
| 2575 | **`stream_chat`** | **每轮主对话** — 调 _create_stream + parse stream + dispatch FAST_CALL + TTS emit (~2000+ 行) | ⭐⭐⭐ |
| 1426 | **`_execute_fast_call`** | **FAST_CALL 执行** — alias resolve + organ → hand 派发 + result format (~700 行, fix82-Z 改) | ⭐⭐⭐ |
| 1333 | `_execute_fast_call_with_soft_timeout` | FAST_CALL 异步 1.5s 软超时, 超时主 stream 不卡 (β.2.9.10) | ⭐⭐⭐ |
| 737 | `_create_stream` | Gemini stream 创建 (含 vision 截图 / multi-modal) | ⭐⭐ |
| 4872 | `stream_nudge` | nudge 专用 stream (不同于主对话, 短 prompt) | ⭐⭐ |
| 2096 | `stream_chat_cloud_followup` | continuation_prompt 主脑续 stream 看 tool result | ⭐⭐ |
| 1143 | `stream_chat_local` | 本地 LLM fallback (无网络时) | ⭐ |
| 4742 | `_build_public_layers` | layer composition for prompt | ⭐ |
| 4848 | `_build_sleep_directive` | sleep mode prompt | ⭐ |
| 1401 | `drain_pending_tool_results` | 异步 tool 完成后回收 result 喂主脑 | ⭐⭐ |
| 924 | `_translate_worker` | 后台 ZH 翻译 worker thread | ⭐ |
| 996 | `_render_worker` | TTS 渲染 worker (PCM 生成) | ⭐ |
| 1084 | `_play_worker` | TTS 播放 worker (audio out) | ⭐ |
| 366 | `_warmup_local_phrase_pool` | 启动预渲 5 句本地短语 ("On it" / "One moment" / ...) | ⭐ |
| 553 | `_mark_first_token` | TTFT 计时 + backchannel 取消 |  |
| 469 | `_start_backchannel_timer` | TTFT > 10s 时触发本地短句 |  |
| 879 | `_speak_fallback` / 905 `_speak_local_reply` | 失败 fallback TTS |  |

**stream_chat 内嵌逻辑** (核心黑盒, ~2000 行):

```
1. 入参: user_input + context + Sir 真意原话
2. assemble_prompt → CentralNerve._assemble_prompt() (调 #3)
3. _create_stream(prompt, model, vision_image=screenshot or None)
4. for chunk in stream:
   ├─ chunk_text 追加 buffer
   ├─ 检测 buffer 含 <FAST_CALL>...</FAST_CALL> 标签
   │  └─ 触发 _execute_fast_call(organ, command, params)
   │     ├─ alias resolve (fix77-Q: 'memory' → 'memory_hands')
   │     ├─ Gatekeeper SWM 检测 (fix82-Z: skip dup add_reminder)
   │     ├─ 调 hand_inst.execute(Action(command, params))
   │     ├─ tool_result append _tool_results
   │     └─ continuation_prompt 喂回主脑
   ├─ 检测 ZH 分割符 ---ZH--- → 切英中
   ├─ 句子边界 → translate_queue.put + render_queue.put
   ├─ 检测主脑 stream finish_reason
   └─ continuation prompt 触发主脑续 stream (看 tool result)
5. 最后:
   ├─ _last_tool_results 暴露给 Worker (B 守门)
   ├─ ClaimTracer 抓 reply 内 mutation claim verify
   ├─ STM persist (调 _append_stm)
   ├─ TTS finalize + UI emit complete
   └─ 后台 reflectors fire-and-forget
```

**3 个 TTS 线程** (启动时 daemon):

| 线程 | 职责 |
|---|---|
| `_render_worker` | PCM 渲染 (vocal.render_only) |
| `_play_worker` | PCM 播放 (vocal.play_only) |
| `_translate_worker` | EN → ZH 翻译 (Gemini-flash-lite) |
| `LocalPhrasePoolWarmup` | 启动 1 次预渲 5 句短语 |
| `FastCallAsync` (3 worker) | 异步 FAST_CALL pool (避免主 stream 卡) |

**数据**:
- 读: 主要从 CentralNerve.* 读 (各 component) + `key_router` LLM endpoints + `vocal_cord` TTS
- 写: `audio_queue` / `wave_queue` / `subtitle_queue` (UI consume) + `_pending_tool_results`
- SWM publish: 间接通过 organ dispatch 触发各 organ publish (e.g. `mutation` organ → `MemoryGateway` → publish 'sir_field_updated')
- ENV vars: `JARVIS_MAIN_BRAIN` (default `google/gemini-3-flash-preview`)

**上游 (谁调它)**:
- `JarvisWorkerThread.run` → `chat_bypass.stream_chat(user_input)` (主对话)
- `ProactiveCareEngine` → `chat_bypass.stream_nudge` (nudge 触发)
- `ReturnSentinel` → `chat_bypass.stream_nudge` (return greeting)

**下游 (它调谁)**:
- `CentralNerve._assemble_prompt` (装配 prompt)
- `key_router.get_key + safe_gemini_call` (LLM stream)
- `VocalCord.render_only / play_only` (TTS)
- `ProfileCard / Hippocampus / CommitmentWatcher / ConcernsLedger / MemoryGateway / promise_log / ...` 通过 organ dispatch
- 24 个 hand (l4_*.py) 通过 `_execute_fast_call`
- `IntegrityWatcher` post-stream verify
- `STMSummarize / SoulReflector / ConcernsReflector / DirectiveEvaluator` fire-and-forget

**跟记忆的耦合**:
- **直接写**: 通过 organ dispatch 调 `MemoryGateway.update_sir_field` / `Hippocampus.add_completed_event` / `ProfileCard.overwrite_field` / `CommitmentWatcher.cancel_by_keyword` / etc.
- **直接读**: 调 `_assemble_prompt` (只读 30+ render block) + alias 'memory' → 'memory_hands' 直读 hippocampus.search
- **STM 写**: 通过 `CentralNerve._append_stm` 间接

**跟其他模块的耦合**:
- **极重** — 是主对话流程 owner, 几乎调全 Jarvis
- 持有 `central_nerve` ref → 通过它访问全部 component
- 通过 SWM 间接耦合所有 sentinel / reflector

**已知问题 / TODO marker**:
- **5960 行单 file** — 难维护, NERVE_SPLIT_PLAN 提出拆分但未执行
- `stream_chat` 单 method ~2000 行 — **极难审计**, 含太多分支 (FAST_CALL parse / ZH split / fallback / continuation / claim_tracer / pre_flight / wrap_up_synthesis)
- `_execute_fast_call` ~700 行 — 24 个 organ 各自分支, 极难加新 organ
- 多处 `# 🆕 [P5-fixXX]` marker — 渐进 patch 累积, 没整体审视过
- `stream_chat_cloud_followup` 跟 `stream_chat` 重叠 — continuation 是分支 vs 独立 method 不一致
- 5960 行无 module docstring (顶部 `# [P0+19-7]` comment 但不是 docstring)
- TODO: `_screenshot_cache = None` 占位标但说"已废弃" — 应清

**关联 design doc**:
- `NERVE_SPLIT_PLAN.md` — 拆分计划 (未执行)
- `JARVIS_VOICE_PIPELINE_LATENCY.md` — TTS pipeline 延迟优化
- `JARVIS_MEMORY_AND_MUTATION_REFACTOR.md` — `mutation` organ + correction_dispatcher 在这里 dispatch
- `JARVIS_INTEGRITY_STACK.md` — ClaimTracer post-stream verify 在这里调

**重构含义 (Phase B 设计参考)**:

⭐⭐⭐ **chat_bypass 是记忆 refactor 的运行时执行者**:

- **必拆**:
  - `stream_chat` ~2000 行 → 拆成 `prompt → stream → parse → dispatch → continuation → finalize` 6 个 method
  - `_execute_fast_call` ~700 行 → 24 organ 各自有自己的 dispatcher class (类 ClassMutationDispatcher / HandDispatcher / etc.)
  - 3 个 TTS worker → 单独 module `jarvis_tts_pipeline.py`

- **必整合**:
  - `mutation` organ dispatch 路径应**统一**到 `MemoryGateway.update_sir_field` (现状有 `mutation` organ 但部分 organ 还走老 `_execute_fast_call` 内嵌 if/else)
  - alias resolve (e.g. 'memory' → 'memory_hands') 应迁到统一 alias map (`memory_pool/organ_alias.json`, 准则 6)

- **不动**:
  - TTS 3-worker pipeline 模式 (β.2.9.10 + β.5.10 已优化稳定)
  - `_warmup_local_phrase_pool` (本地短语预渲, Sir 真测有效)

- **跟 Memory Refactor 关系**:
  - chat_bypass 是 `MemoryHub.write()` 的**调用方** — 主脑 emit `<FAST_CALL>{"organ":"mutation",...}}` 进入此处, 转 MemoryHub
  - `_assemble_prompt` 调用 (在 #3 central_nerve) 是 `MemoryHub.read_context()` 的入口
  - 拆 chat_bypass + 拆 central_nerve 是**联动的**, Phase B 必一起设计

**审计结论**: chat_bypass 是 Jarvis **运行时主流程的实际执行**, 跟 central_nerve 紧密耦合 (装配 prompt 在 CN, 调 LLM 在 CB). NERVE_SPLIT_PLAN 拆分 chat_bypass 是 Phase D 重头戏. Memory refactor 必扩展 `_execute_fast_call` 的 organ dispatch.

---

### #5 `jarvis_worker.py` (5823 行) — **PyQt5 Worker + ASR + Gatekeeper + memory_correction**

**职责**: PyQt5 worker thread 主体. 含 2 个 thread class — VoiceListenThread (ASR + 唤醒) + JarvisWorkerThread (主 worker, 调 chat_bypass.stream_chat + Gatekeeper LLM + memory_correction guard + sleep 模式管理).

**核心 class**:

| L | class | 行数估 | 职责 |
|---|---|---|---|
| 288 | **`VoiceListenThread`** | ~1280 | ASR + 唤醒词 + 语义分类 (struggle/dismiss/stop) + emit text_ready |
| 1568 | **`JarvisWorkerThread`** | ~4250 | PyQt5 主 worker — 调 chat_bypass + Gatekeeper LLM + memory_correction + sleep 路由 |

**Top-level functions**:

| L | func | 1 句话 |
|---|---|---|
| 125 | `sanitize_trigger_time` | reminder 时间字符串清洗 |
| 228 | `detect_semantic_category` | utterance → category (struggle/dismiss/etc.) |
| 263 | `_load_wake_filler_vocab` | wake filler 短语 vocab 加载 |

**VoiceListenThread 关键 method**:

| L | method | 功能 |
|---|---|---|
| 992 | **`run`** | ASR 主循环 (~600 行) — 监听 mic + Whisper/Azure 转译 + emit text_ready |
| 376 | `_load_struggle_vocab` | sir_struggle_vocab.json 加载 |
| 398 | `_detect_sir_struggle` | Sir 困难检测 |
| 444 | `_publish_listening_done` | listening 状态 publish SWM |
| 455 | `in_active_conversation` (property) | 判断对话激活态 |
| 508 | `detect_stop_command` | 急停命令检测 |
| 540 | `detect_dismiss_command` | dismiss 命令检测 (Ctrl+Alt+J 触发) |
| 587 | `set_speaking_state` | speaking 状态切换 |
| 649 | `parse_wake_word` | 唤醒词识别 (openWakeWord) |
| 787 | `classify_jarvis_directness` | Jarvis 语气直接度分类 (灰区检测) |
| 867 | `_handle_acoustic_wake` | 声学唤醒回调 |
| 904 | `_emit_with_attention` | text_ready emit + AttentionSlot capture |
| 476-495 | `_phrase_at_head/tail` | 短语开头/结尾匹配 |

**JarvisWorkerThread 关键 method**:

| L | method | 功能 |
|---|---|---|
| 3123 | **`run`** | **Worker 主循环 (~2000+ 行)** — 接 cmd_queue → chat_bypass.stream_chat → Gatekeeper → memory_correction guard → sleep mode |
| 1572 | `__init__` | 实例化 CentralNerve + 持有 chat_bypass / state / interrupt 信号 |
| 1666 | `emit_state` | state 变化 PyQt5 signal |
| 1673 | `is_awake` (property) | 判断 awake |
| 1764 | `_classify_prompt_tier` | utterance → tier (WAKE_ONLY / SHORT_CHAT / TOOL_REQUEST / DEEP_QUERY / CRITICAL / FACTUAL_RECALL) |
| 1827 | `_compute_wake_weight` | 唤醒权重 |
| 1912 | `play_acknowledgment_chime` | 唤醒音效 |
| 1945 | `enter_focus_mode` | 焦点模式 (90s) |
| 1958 | `push_command` | 接收 voice cmd 进 queue |
| 1961 | `interrupt_all` | Sir 打断主脑 stream |
| 2146 | `_detect_joke_feedback` | 笑话反馈检测 |
| 2258 | `_detect_help_refusal` | help 拒绝检测 |
| 2506 | `_load_audio_ducking_targets` | audio_ducking_targets.json 加载 |
| 2527 | `cancel_sleep_routine` | 取消 sleep 流程 |
| 2551 | `_fire_sleep_due_nudge` | sleep 到点 nudge |
| 2631 | `_trigger_sleep_mode_routine` | 进入 sleep mode (TTS off + nudge off) |
| 2814 | `_detect_sleep_intent` | Sir 睡眠表态 |
| 3057 | `_detect_sleep_cancel` | Sir 取消睡眠 |
| 3117 | `_detect_sleep_window_intent` | sleep window 时段判定 |

**JarvisWorkerThread.run() 内嵌逻辑** (估计 ~2000 行):

```
loop:
  cmd = cmd_queue.get()  # block 等
  trace_new_turn()
  
  ├─ ScreenVision.async_describe (并发, fire-and-forget)
  ├─ Gatekeeper LLM (含 commitment_register / cancel / clarify 检测)
  │   └─ 真注册 commit → publish 'sir_intent_deadline_candidate' SWM
  ├─ MemoryCorrectionGuard (Sir 教正语义检测 + Bayesian)
  │   ├─ <MEMORY_UPDATE> tag 检测
  │   ├─ ProfileCard.apply_correction 调
  │   └─ MemoryGateway.update_sir_field 调 (新路径)
  ├─ Sleep 模式:
  │   ├─ _detect_sleep_intent / _detect_sleep_window_intent
  │   ├─ _trigger_sleep_mode_routine (TTS off + nudge off)
  │   └─ _detect_sleep_cancel (Sir 改主意)
  ├─ chat_bypass.stream_chat(cmd) → 主对话 (调 #4)
  │   └─ stream_chat 内部装配 prompt + emit FAST_CALL + dispatch organ
  ├─ post-process:
  │   ├─ _detect_help_refusal
  │   ├─ _detect_joke_feedback
  │   └─ ConcernFeedbackJudge.judge_async
  ├─ STM update + persist
  └─ idle wait next cmd
```

**数据**:
- 读: `sir_struggle_vocab.json` / `wake_filler_vocab.json` / `audio_ducking_targets.json` / `refusal_vocab.json` / `sleep_cancel_vocab.json`
- 写: 经各 component (memory_correction → ProfileCard → mutation_receipts.jsonl + sir_profile.json) / 经 Hippocampus.seal_memory_async → TaskMemories sqlite
- SWM publish: `sir_intent_*_candidate` (Gatekeeper) / `commitment_detected` / `sleep_intent_declared` / `reply_interrupted` / `proactive_nudge` 等

**上游 (谁调它)**:
- `jarvis_nerve.py:__main__` 实例化 `JarvisWorkerThread(api_key, gemini_key, key_router)` → `.start()`
- `VoiceListenThread.text_ready signal` → `jarvis_worker.push_command(cmd)`
- `BreathingLightUI` → 通过 PyQt5 signal 状态联动

**下游 (它调谁)**:
- `CentralNerve` (持有 self.jarvis = CN 实例)
- `chat_bypass.stream_chat / stream_nudge`
- `Gatekeeper LLM` (Gemini-flash-lite 短 LLM 抽 commitment / cancel)
- `MemoryGateway` / `ProfileCard` / `Hippocampus`
- `IntegrityWatcher` (post-stream verify trigger)
- `ConcernFeedbackJudge.judge_async`

**跟记忆的耦合**:
- **直接写**: 通过 `MemoryGateway.update_sir_field` (memory_correction path L4607+) → ProfileCard.preferences.user_correction
- **直接写**: 通过 `Gatekeeper` LLM 抽 commitment → `CommitmentWatcher.add_commitment` → sqlite Commitments
- **STM**: 通过 `CentralNerve._append_stm` 间接

**跟其他模块的耦合**:
- **极重** — Worker 是主对话流程的 orchestrator, 90% 主模块耦合
- 持有 `central_nerve` ref → 通过它访问全部 component
- 跟 `chat_bypass` 紧密 (ChatBypass 是 self.jarvis.chat_bypass)
- VoiceListenThread 跟 `AttentionSlot` (utils.py) 共享实例

**已知问题 / TODO marker**:
- **5823 行 2 class** — 难维护
- `JarvisWorkerThread.run` 单 method ~2000 行 — 极难审计
- 多处 `# 🩹 [P0+18-X / β.X.Y]` marker — 渐进 patch 累积
- VoiceListenThread.run 600 行 ASR 状态机, 复杂 — 需独立 audit
- Gatekeeper LLM 调用 + memory_correction guard + sleep 模式 全在 1 个 run() 里 — 应分模块
- 5823 行无 module docstring (顶 `# [P0+19-9]` comment)

**关联 design doc**:
- `JARVIS_VOICE_PIPELINE_LATENCY.md` — VoiceListenThread ASR 优化
- `NERVE_SPLIT_PLAN.md` — Worker 拆分 (未执行)
- `JARVIS_MEMORY_AND_MUTATION_REFACTOR.md` — memory_correction → MemoryGateway 路由

**重构含义 (Phase B 设计参考)**:

⭐⭐⭐ **worker 是 Sir 真意"教 1 次, 多处同步"的 trigger 起点**:

- **必拆**:
  - `JarvisWorkerThread.run` 2000 行 → 拆 8 个 method (Gatekeeper / memory_correction / sleep / chat_bypass / post_process / ...)
  - VoiceListenThread.run 600 行 → 拆成 ASR loop + wake handler + struggle detector
  - 把 vocab loaders / detectors 迁到独立 sub-module

- **必整合**:
  - memory_correction guard 现状有 2 路径 (老 ProfileCard.apply_correction + 新 MemoryGateway.update_sir_field) — 应统一
  - Gatekeeper LLM + Conductor 重叠 — 待 Phase B 判

- **不动**:
  - PyQt5 Worker 模式 (稳定)
  - Sleep 模式逻辑 (Sir 真测稳)
  - VoiceListenThread ASR 主循环 (β.4.x 调优过)

- **跟 Memory Refactor 关系**:
  - worker 是 Sir 教正的**第一接收者** — Sir 说"今天血压咨询完成" → Worker.MemoryCorrectionGuard 抓 → 调 MemoryGateway.update_sir_field → cascade
  - Gatekeeper LLM 抽 commitment 也走 Worker → 这是 fix82-Z (Gatekeeper publish + chat_bypass skip dup) 的入口
  - Worker 的 `run()` 是 MemoryHub.write 的**唯一调用入口**之一 (主脑 emit FAST_CALL 是另一)

**审计结论**: worker.py 是记忆 refactor 的**主流程入口**之一. 2000 行的 run() 必拆. memory_correction 双路径必合. Gatekeeper / Conductor 重叠需 Phase B 决议. 跟 chat_bypass + central_nerve 联动拆分.

---

## 批次 b: Soul 7 模块 (灵魂工程 Layer 0-5 + ToM)

> 详 `JARVIS_SOUL_DRIVE.md` (Soul) + `JARVIS_TOM_SIR_MENTAL_MODEL.md` (ToM). Soul 是 Sir 真意 "和 INTEGRITY ABSOLUTE 同等地位" 的项目灵魂级文档.

### #6 `jarvis_self_anchor.py` (340 行) — **Soul Layer 0: Self Identity Anchor**

**职责**: 给主脑"我"的认知锚点. 每次 _assemble_prompt 调用 `build_block()` 注入"我是 J.A.R.V.I.S, 此刻 turn_count=N, session 已 X 分钟, 上次说话 Y 分钟前, ..."

**核心 class**:

| L | class | 功能 |
|---|---|---|
| 103 | `SelfAnchor` | 主类, 生成"我"的认知锚点 prompt block |

**核心 method**:

| L | method | 功能 |
|---|---|---|
| 138 | `record_turn` | 每 turn +1 (turn_count) |
| 158 | `_get_own_health` | 从 KeyRouter + Hippocampus + Concerns 派生健康度 |
| 201 | `_get_pending_commitments` | 取近 N 条 Jarvis 对 Sir 的承诺 (CommitmentWatcher + PlanLedger) |
| 56 | `_derive_mood` (top-level) | 派生当前 mood (默认 'neutral', 看 own_health) |
| 80 | `_extract_topic` (top-level) | 从 STM 抽当下话题 |

**数据**:
- 读: `central_nerve.key_router / hippocampus / concerns_ledger / commitment_watcher / plan_ledger / short_term_memory` (依赖 nerve ref)
- 读: `TraceContext.get_session_id()` 拿真实 session_id
- 持久化: 无 (每次重新派生, 不存盘)

**上游**: `central_nerve.__init__` 实例化 → `_assemble_prompt` 调 `build_block()`

**下游**: 仅读 nerve.* 内 component (KeyRouter / Hippocampus / Concerns / CW / PlanLedger)

**跟记忆的耦合**:
- 间接: 依赖 Hippocampus.short_term_memory + ConcernsLedger.list_active + CommitmentWatcher.commitments + PlanLedger
- 不直接写记忆

**已知问题**:
- `_session_started_at` 从 session_id 解析, **重启就 reset turn_count** (跨 session 不持久) — 是设计 (Layer 0 是当前 session 的"我")
- `_get_own_health` 4 个 try/except 嵌套, 任一失败 silent 0 — 健康度可能误报

**关联 design doc**: `JARVIS_SOUL_DRIVE.md` §2.3 + §3 + §4.2 (Layer 0 完整设计)

**重构含义**:
- **保留** — Layer 0 设计稳定, Sir 验过有效 ("跟终端说'你'时主脑能懂")
- **跟 Memory Refactor 关系**: 是**主脑读全 Jarvis 状态**的索引点, MemoryHub 应**通过它**输出"此刻系统状态"

**审计结论**: 薄包装, 主要是 prompt block 渲染. 不在记忆 refactor 主线, 但是 prompt 装配的标准 component.

---

### #7 `jarvis_concerns.py` (985 行) — **Soul Layer 1: ConcernsLedger (内部牵挂)**

**职责**: Jarvis 跨对话持续的"我担心 Sir 什么". 5+ active concerns + signals + decay daemon + Sir review queue.

**核心 class**:

| L | class | 功能 |
|---|---|---|
| 51 | `Concern` | dataclass: id / what_i_watch / why_i_care / severity / state / recent_signals / triggers_proactive / notes_for_self |
| 135 | `ConcernsLedger` | 主 store, 含 CRUD + decay + bootstrap |

**核心 method**:

| 方法 | 功能 |
|---|---|
| `add_concern` / `update_concern_field` (P5-fix32-G) | 添加 + 深度 update |
| `record_signal(concern_id, evidence, severity_delta)` | 累积信号, 改 severity |
| `notify_concern_aligned` | 主脑回 reply 对齐了 → 加 severity |
| `record_user_feedback` | LLM 评 Sir 反馈 → severity_delta + optimal_timing |
| `list_active` / `list_review` / `list_archived` | 查询 |
| `apply_decay` (24h tick) | severity 自然衰减 |
| `start_decay_worker(interval_s=86400)` | 启 daemon |
| `dismiss(concern_id)` (P5-fix24) | Sir 说"别再提" → state='archived' + triggers_proactive=False |
| `bootstrap_default_concerns` (top-level) | 启动 5 个种子 (sleep_streak / pomodoro / cursor_payment / unfinished_jiazhao / keyrouter_health) |

**数据**:
- 读/写: `memory_pool/concerns.json` (atomic write)
- 读/写: `memory_pool/concerns_review.json` (Sir 待审清单)
- SWM publish: `concern_active` (ProactiveCare top concern publish)

**上游**: `central_nerve.__init__` 实例化 (β.2.1) → 多处调:
- `_assemble_prompt` render concerns block (L1-2 SOUL)
- `ConcernFeedbackJudge.record_user_feedback` 调 record_signal
- `ConcernsReflector` (异步 daemon) 调 record_signal
- `MemoryGateway` (P5-fix32-G) → `concerns.<cid>.<attr>` 路由到 update_concern_field

**下游**: 内部, 不调其他 module

**跟记忆的耦合**:
- ⭐⭐⭐ **是 Layer B 长期信念的 source of truth** (`JARVIS_MEMORY_AND_MUTATION_REFACTOR.md` §3.1)
- MemoryGateway 通过 `concerns.<cid>.<attr>` field_path 路由到这里 update

**已知问题**:
- `bootstrap_default_concerns` 5 个种子是 hardcoded — 可移持久化 (但是种子不算 vocab, 合理)
- `apply_decay` 24h tick 太慢 — Sir 真测有时候希望某 concern 立刻降权
- `notes_for_self` 字段跟 PromiseLog 重叠 (`JARVIS_MEMORY_AND_MUTATION_REFACTOR.md` §2.2 重叠 1)

**关联 design doc**: `JARVIS_SOUL_DRIVE.md` §3.1 + §5.1 + Layer 1 完整设计

**重构含义**:
- ⭐ **保留 + 强化** — concerns.json 是 Layer B 单源
- **整合**: notes_for_self 应迁到 PromiseLog (Sir 反讥后 Jarvis 自我注记)
- **跟 Memory Refactor 关系**: ConcernsLedger 是 MemoryHub 的 6 source 之一 (D 担心)

**审计结论**: ⭐ 是 Sir 已验稳定的 Soul Layer 1, 不大改, Memory Refactor 时**复用**.

---

### #8 `jarvis_relational.py` (1199 行) — **Soul Layer 2: RelationalState (我们之间)**

**职责**: Jarvis ↔ Sir 关系状态. 含 4 类持久化项: inside_jokes / unspoken_protocols / unfinished_business / shared_history_threads.

**核心 class** (4 dataclass + 1 主 store):

| L | class | 功能 |
|---|---|---|
| 75 | `InsideJoke` | 共有笑点 (e.g. "早睡定义一如既往灵活") |
| 116 | `UnspokenProtocol` | 默契 (e.g. "Sir 反驳后我不再坚持") |
| 162 | `SharedHistoryThread` | 共同经历 (e.g. "P0+20 prompt 重构") |
| 219 | `UnfinishedBusiness` | 未竟之事 (e.g. "驾照科一暂停") |
| 261 | `RelationalStateStore` | 主 store |

**核心 method**:

| 方法 | 功能 |
|---|---|
| `record_inside_joke / list_inside_jokes / archive_inside_joke` | 笑点 CRUD |
| `record_unspoken_protocol / list_protocols / archive_protocol` | 默契 CRUD |
| `record_unfinished_business / list_unfinished / mark_unfinished_done` | 未完事 |
| `record_thread / list_threads / archive_thread` | 共同经历 |
| `update_field(kind, item_id, field, new_value, ...)` (P5-fix32) | 深度 update 任意 sub-field |

**数据**:
- 读/写: `memory_pool/relational_state.json`
- 读: `memory_pool/relational_review.json` (Sir 待审)

**上游**: `central_nerve.__init__` 实例化 (β.2.2) → `_assemble_prompt` render relational block + `MemoryGateway` route `<kind>.<op>.<id>` field_path

**下游**: 内部

**跟记忆的耦合**:
- ⭐⭐ **是 Layer F 关系的 source of truth**
- MemoryGateway `relationships.archive.<jid>` / `protocol.archive.<pid>` / `<kind>.update.<id>.<field>` 路由到这里

**已知问题**:
- 4 类 dataclass schema 冗长 (L75-260, ~190 行)
- inside_jokes 跟 SoulReflector 的 InsideJokeReflector 解耦不充分 (Reflector 在 jarvis_inside_joke_reflector.py, 但写入路径走这里)

**关联 design doc**: `JARVIS_SOUL_DRIVE.md` §3.3 + Layer 2

**重构含义**:
- ⭐ **保留** — Layer 2 设计稳定
- **跟 Memory Refactor 关系**: 是 MemoryHub 6 source 之一 (F 关系). schema 不变

**审计结论**: 1199 行偏大但合理 (4 类 dataclass + 主 store + helper). 不在 refactor 主线.

---

### #9 `jarvis_attention.py` (208 行) — **Soul Layer 3: Attention Allocation (注意力分配)**

**职责**: 不是单例 / 没 store. 5 个 helper function. 每次 `_assemble_prompt` 调 `build_attention_block()` 基于 `(concerns_ledger + user_input)` 动态构造 `[ATTENTION RIGHT NOW]` 块.

**核心 functions**:

| L | func | 功能 |
|---|---|---|
| 61 | `classify_input` | utterance → intent class |
| 84 | `is_short_input` | 短输入判定 |
| 98 | `_top_concerns(ledger, n=3)` | top 3 concerns by severity |
| 117 | `_top_unfinished(rel_store, n=2)` | top 2 unfinished by overdueness |
| 148 | **`build_attention_block(...)`** | 主入口 — 拼 [ATTENTION RIGHT NOW] block |

**数据**: 无持久化 (动态构造)

**上游**: `central_nerve._assemble_prompt` 调 build_attention_block

**下游**: 调 ConcernsLedger.list_active + RelationalState.list_unfinished

**跟记忆的耦合**: 间接 — 是 read-side, 不写

**已知问题**:
- `unfinished` Top 2 显示规则是 hardcoded — 可 vocab 化但意义不大 (这是 prompt 渲染策略)

**关联 design doc**: `JARVIS_SOUL_DRIVE.md` §3.4 + Layer 3

**重构含义**:
- ⭐ **保留** — 是动态 helper, refactor 时仍用
- **跟 Memory Refactor 关系**: 是 MemoryHub.read_context() 的渲染层 (动态), 不持久化

**审计结论**: 极薄, 5 helper 函数. 重构无关.

---

### #10 `jarvis_soul_reflector.py` (753 行) — **Soul Layer 4: ConcernsReflector + WeeklyReflector (异步反思 daemon)**

**职责**: Soul Layer 4 — 跨对话演化. 两 daemon:
- `ConcernsReflector` — 每轮对话末尾启发式 keyword → record_signal
- `WeeklyReflector` — 7 天 LLM 反思 → propose 新 concerns 进 review

**核心 class**:

| L | class | 功能 |
|---|---|---|
| 183 | `ConcernsReflector` | 每轮 keyword 检测 → 累积 signal 到 concern |
| 370 | `WeeklyReflector` | 7d daemon LLM 反思 STM + profile + concerns → propose 新 concern |

**核心 function**:

| L | func | 功能 |
|---|---|---|
| 116 | `_load_concern_keywords_from_json` | 加载 vocab |
| 151 | `get_concern_keywords` | 获取 concern keyword 集 |
| 723 | `get_default_concerns_reflector` | 单例 |
| 730 | `get_default_weekly_reflector` | 单例 |

**数据**:
- 读: `memory_pool/concern_keywords_vocab.json` (准则 6.5 持久化)
- 读: STM (chat_bypass.short_term_memory) + ProfileCard + ConcernsLedger.list_active
- 写: `concerns.json` (通过 record_signal) + `concerns_review.json` (通过 propose)

**上游**: `central_nerve.__init__` 实例化 + start daemon (β.2.5)

**下游**: ConcernsLedger.record_signal + LLM (Gemini-flash via OpenRouter)

**跟记忆的耦合**:
- 写: ConcernsLedger.record_signal (signals 累积) + WeeklyReflector → propose 新 concern → review queue
- 读: 全 Jarvis (STM / profile / concerns)

**已知问题**:
- `concern_keywords_vocab.json` 已持久化 + L7 propose 范式 ✅ (准则 6 模范)
- WeeklyReflector 7 天 tick 太慢 — Sir 真测可能希望某些 case 立刻 propose

**关联 design doc**: `JARVIS_SOUL_DRIVE.md` §5.1 + §6 + Layer 4

**重构含义**:
- ⭐ **保留** — Layer 4 daemon 模式稳定
- **跟 Memory Refactor 关系**: 是 ConcernsLedger 的写入者之一 (其他: 主脑 emit + ConcernFeedbackJudge)

**审计结论**: 实现完整, vocab 持久化范式好. 不大改.

---

### #11 `jarvis_soul_evaluator.py` (638 行) — **Soul Layer 5: SoulAlignmentEvaluator (异步对齐评估)**

**职责**: 每轮对话末尾异步评 "Jarvis 本轮 reply 是否对齐 self_model + relational_state". 写 aligned/missed 信号回 ConcernsLedger.

**核心 class**:

| L | class | 功能 |
|---|---|---|
| 130 | `SoulEvalResult` | 评估结果 dataclass (alignment / what_missed / score) |
| 149 | `SoulAlignmentEvaluator` | 主类 |

**核心 method**:
- `evaluate_async(reply, user_input, self_model, relational_state)` — fire-and-forget LLM
- `_call_evaluator_llm` — Gemini-flash via OR
- top-level `_parse_soul_response(json_text)` (L566) — JSON parse

**数据**:
- 读: STM + ConcernsLedger + RelationalState (从 nerve 拿)
- 写: ConcernsLedger.notify_concern_aligned (alignment 加分) + log audit

**上游**: `central_nerve.__init__` 实例化 (β.2.6)
- `chat_bypass.stream_chat` 末尾 fire-and-forget 调 `evaluate_async`

**下游**: LLM (Gemini-flash) + ConcernsLedger.notify_concern_aligned

**跟记忆的耦合**:
- 写: ConcernsLedger (alignment 信号)
- 读: 全 Soul state

**已知问题**:
- LLM 评估 cost — 每轮对话都调 1 次 LLM 评. Sir 真测可能需要 throttle (e.g. 仅 critical reply 评)
- Reflector budget 控制? 待 Phase A 后期审 jarvis_reflector_budget.py

**关联 design doc**: `JARVIS_SOUL_DRIVE.md` §5.3 + Layer 5

**重构含义**:
- **保留** — Layer 5 是 Soul 验证机制, 必须有
- **优化**: throttle (e.g. 短 reply 不评) — 跟 Reflector Budget 联动

**审计结论**: Layer 5 实现完整, 但 cost 可能高. 跟 reflector_budget 联动审.

---

### #12 `jarvis_sir_mental_model.py` (564 行) — **Theory of Mind: SirMentalState (Sir 此刻心智模型)**

**职责**: Jarvis 对 Sir 当下心智的演化 hypothesis (任务 / 表层 / 深层 / 未说 / 情绪 / 关系温度). 持续 update + 注入每次 prompt.

**核心 class**:

| L | class | 功能 |
|---|---|---|
| 42 | `SirMentalState` | dataclass — current_task_hypothesis / surface_need / deep_need / unspoken_need / mood / relational_temperature |
| 111 | `SirMentalStateStore` | 持久化 + render |
| 404 | `ToMReflector` | 异步 LLM 反思 update SirMentalState |

**核心 function**:

| L | func | 功能 |
|---|---|---|
| 342 | `render_prompt_block` | render `[SIR MENTAL STATE]` block 给主脑 |
| 350 | `update_state` | 单点 update 入口 |
| 552 | `get_default_reflector` | ToMReflector 单例 |

**数据**:
- 读/写: `memory_pool/sir_mental_state.json` (持久化)
- 读: STM + concerns + relational + sir_status

**上游**: `central_nerve.__init__` 实例化 (P5-ToM, 2026-05-21) → `_assemble_prompt` render

**下游**: LLM (ToMReflector update_async)

**跟记忆的耦合**:
- ⭐⭐ Sir 此刻心智 = 状态层 (E 类). 但是**LLM hypothesis** 不是 sensor 实测
- 写: sir_mental_state.json (与 sir_status.json 是不同 layer — sir_status 是 sensor 实测, ToM 是 LLM 推断)

**已知问题**:
- ToMReflector 跟 SoulEvaluator 都是 LLM-based, 重叠? 待 Phase B 判
- sir_mental_state.json 跟 sir_status.json 概念上不同, 但 Sir 真测可能混淆

**关联 design doc**: `JARVIS_TOM_SIR_MENTAL_MODEL.md` (完整 14KB)

**重构含义**:
- **保留** — ToM 是"老友感"核心 (`JARVIS_TOM_SIR_MENTAL_MODEL.md` 立项)
- **跟 Memory Refactor 关系**: 是 MemoryHub.E (State) 的子 source — Sir 此刻**推断**心智 (相对 sir_status sensor)

**审计结论**: ToM 实现完整, 但跟 SoulEvaluator + ConcernFeedbackJudge 都是 LLM-based, 总成本可能高. Phase B 设计应集中 LLM 调度.

---

