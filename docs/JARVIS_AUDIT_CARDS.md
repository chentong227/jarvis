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

## 批次 c: 记忆 11 模块 (refactor 核心战场)

> 是 Sir 真意"记忆是底座"的具体载体. 11 模块都是 Memory Refactor 的目标.

### #13 `jarvis_routing.py` (1480 行) — **ProfileCard + 3 Center + Router**

**职责**: 4 个 router/center class. 主体是 `ProfileCard` (Sir 静态画像), 3 Center 是 PromptCenter/GuardianCenter/CompanionCenter (历史 wiring 容器).

**核心 class**:

| L | class | 功能 |
|---|---|---|
| 51 | `SoulRouter` | LLM 路由器 (legacy?) |
| 188 | `ContextRouter` | 上下文路由 |
| 281 | `ContentPreferenceTracker` | 内容偏好追踪 |
| 487 | **`ProfileCard`** | ⭐⭐⭐ Sir 静态画像 + apply_correction + overwrite_field (核心记忆类!) |
| 1087 | `PromptCenter` | wiring 容器 (持有 prompt_cache) |
| 1123 | `GuardianCenter` | wiring 容器 (持有 commitment_watcher / return_sentinel) |
| 1173 | `CompanionCenter` | wiring 容器 (持有 smart_nudge / humor_memory) |

**ProfileCard 关键 method** (~600 行):
- `apply_correction(source_module, field, old_value, new_value, confidence)` — 老路径写 `profile_corrections.jsonl` (audit only, 不真改 sir_profile.json)
- `overwrite_field(field, new_value, source, turn_id, reason)` — **新路径** (P5-fix32-B + fix81 嵌套支持) 真覆写 sir_profile.json + audit jsonl + SWM publish
- `_persist_correction_to_disk` — atomic write
- `render_for_prompt` — sir_profile → prompt block
- `_OVERWRITE_ALLOWED_FIELDS` set (white list)

**数据**:
- 读: `jarvis_config/sir_profile.json` (主 profile)
- 写 (audit): `memory_pool/profile_corrections.jsonl`
- 写 (真): `jarvis_config/sir_profile.json` (atomic via tmp+rename, fix81 支持嵌套)
- SWM publish: `sir_profile_overwritten`

**上游**:
- `central_nerve.__init__` 实例化 `self.profile_card = ProfileCard(self)`
- `MemoryGateway.update_sir_field` (layer=ProfileCard) → 调 overwrite_field
- 老路径 `worker.memory_correction` → 调 apply_correction (走 audit only)

**下游**:
- 写 sir_profile.json + corrections.jsonl + SWM bus

**跟记忆的耦合**:
- ⭐⭐⭐ **ProfileCard 是 Layer A 身份的 source of truth** (`JARVIS_MEMORY_AND_MUTATION_REFACTOR.md` §3.1)
- 是 MemoryHub 的 6 source 之首 (Identity)
- 老 `apply_correction` + 新 `overwrite_field` **2 路径** — Phase B 必合

**已知问题**:
- 老路径 `apply_correction` 仅 audit, 不真改 — 半失效死代码 (β.2.9.9 起 P5-fix32-B 转新路径)
- 1480 行单文件, 4 个 router 杂在一起 — 可拆 (ProfileCard 独立成 jarvis_profile_card.py)
- 3 Center (PromptCenter / GuardianCenter / CompanionCenter) 是历史 wiring 容器, **可能 deprecated** (现状只是 attr 容器)

**重构含义**:
- ⭐⭐⭐ ProfileCard 是 MemoryHub.identity source — **必扩展** (apply_correction 路径下线)
- 3 Center 应**清理** — wiring 转到 CentralNerve 直接持有
- 跟 `jarvis_memory_gateway.py` (新路径) 是同一记忆系统 2 半, **必合并**

**审计结论**: ⭐ ProfileCard 是 refactor 核心. 老 vs 新路径必合. 3 Center 评估清理.

---

### #14 `jarvis_hippocampus.py` (1479 行) — **Hippocampus (LTM SQLite + 向量检索)**

**职责**: Jarvis 长期记忆海马体. SQLite (`jarvis_memory.db`) 含 4 表 (TaskMemories / Commitments / ProjectTimeline / CorrectionMemory). Gemini embedding 向量检索 + Backfill daemon.

**核心 class** (1 个超大):

| L | class | 功能 |
|---|---|---|
| 14 | `Hippocampus` | 主类 (~1450 行!) |

**核心 method (40+)**:
- 向量: `_safe_embed_call` / `_embed_with_rotation` / `_fuzzy_fallback_search` / `search_memory` / `search_memory_default` (with time decay)
- TaskMemories: `seal_memory(env, intent, goal, summary, ...)` (主写入) / `update_memory` / `delete_memory` / `restore_memory`
- Commitments: `add_commitment_row` / `mark_commitment_nudged` / `update_commitment_row` / `soft_delete_commitment` / `load_active_commitments`
- 完成事件: `add_completed_event(summary, keywords, source, turn_id)` (fix82-X 加) / `list_recent_completed_events(days_back, max_n)` (fix82-X 加)
- Backfill: `_start_backfill_worker` (15s tick, 补 NULL 向量) / `_run_backfill_batch` / `_is_embed_in_cooldown`
- 熔断: `_mark_embed_failed` (cooldown 60s on quota/auth fail)

**数据**:
- 读/写: `memory_pool/jarvis_memory.db` (sqlite, 4 表)
- 调用: Gemini embedding API (gemini-embedding-2, 768 dim)
- 不 publish SWM (除了 fix82-X completed_event 间接 cascade)

**上游**:
- `central_nerve.__init__` 实例化
- `chat_bypass.stream_chat` 末尾 `seal_memory_async`
- `worker.run` Gatekeeper → `add_commitment_row`
- `MemoryGateway.cascade_completion` (fix82-X) → `add_completed_event`
- `_assemble_prompt` → `search_memory` (LTM retrieve)

**下游**:
- Gemini embedding API (key router via _embed_with_rotation 跨 3 keys)

**跟记忆的耦合**:
- ⭐⭐⭐ **Hippocampus 是 Layer C 长期事实 + Commitments (Layer E) 的 source of truth**
- TaskMemories: 历史 / 完成事件
- Commitments: 时间承诺
- ProjectTimeline + CorrectionMemory: 子表

**已知问题**:
- 1479 行单 class — 极难维护
- 无 module docstring (audit 时已发现)
- TaskMemories schema 含 `is_future_task` / `trigger_time` 字段 — 跟 Commitments 表概念重叠 ("future_task" 跟 "commitment" 模糊)
- 4 表混在 1 个 db — 可拆 (但 sqlite 不一定要拆)
- backfill daemon 跑在主进程 daemon 线程, 启动后立刻试 (β.4.1 起改 5s sleep)

**重构含义**:
- ⭐⭐⭐ Hippocampus 是 MemoryHub 的 B 事件 + C 承诺源
- TaskMemories.is_future_task 字段重叠 Commitments — Phase B 必判
- backfill / 熔断 logic 稳定, 不动
- `add_completed_event` (fix82-X) 是 Phase 0 战术加 — Phase B 应正式集成

**审计结论**: ⭐ 1479 行核心模块. schema 重叠是 refactor 重点. seal_memory + add_completed_event 是 Phase B 关键 API.

---

### #15 `jarvis_memory_core.py` (1513 行) — **12 类老记忆/纠错/睡意类**

**职责**: P0+19-5 拆分时整合的 12 类 — HumorMemory / PromptLayer / PromptCache / CorrectionEntry / CorrectionMemory / MemoryFragment / **UnifiedMemoryGateway** / FeedbackTracker / TaskWorkerPool / Anticipator / CorrectionLoop / SleepIntentDetector.

**核心 class** (12 个):

| L | class | 功能 |
|---|---|---|
| 94 | `HumorMemory` | 笑点 (重叠 RelationalState.inside_jokes!) |
| 300 | `PromptLayer` / 311 `PromptCache` | prompt 缓存 |
| 352 `CorrectionEntry` / 362 `CorrectionMemory` | 老纠错记忆 (重叠 ProfileCard.apply_correction) |
| 506 | `MemoryFragment` | 记忆碎片 |
| **515** | **`UnifiedMemoryGateway`** | ⚠️ **同名不同 class** vs `jarvis_memory_gateway.py:MemoryMutationGateway` |
| 756 | `FeedbackTracker` | 反馈追踪 |
| 819 | `TaskWorkerPool` | 任务 worker 池 (注释 "C1-3 死代码清扫", 实例不再创建) |
| 868 | `Anticipator` | 预期 / 前瞻 |
| 965 | `CorrectionLoop` | 纠正循环 |
| 1048 | `SleepIntentDetector` | 睡眠意图检测 |

**数据**:
- 读: `memory_pool/feedback_vocab.json`
- 各类各自管自己的状态

**上游**:
- `central_nerve.__init__` 实例化 7+ 类 (UnifiedMemoryGateway / CorrectionLoop / SleepIntentDetector / etc.)

**下游**: 内部 + 调 ProfileCard

**跟记忆的耦合**:
- ⚠️ **UnifiedMemoryGateway** vs **MemoryMutationGateway** (P2-Gap7) 同名不同 class!
  - 老 UMG (memory_core.py:515) 是早期路径
  - 新 MMG (memory_gateway.py) 是 P2-Gap7 重写
  - **重叠**, Phase B 必合并
- HumorMemory 重叠 RelationalState.inside_jokes
- CorrectionMemory 重叠 ProfileCard.apply_correction → profile_corrections.jsonl

**已知问题**:
- ⚠️ **本文件混了 12 类不同概念** — Sir 5/16 拆分时为方便整合, 现状概念边界模糊
- TaskWorkerPool 注释 "C1-3 死代码清扫" — 实例不再创建, 但类还在
- HumorMemory 跟 RelationalState.inside_jokes 概念重叠
- CorrectionMemory 跟 ProfileCard.apply_correction 路径重叠
- UnifiedMemoryGateway 跟 MemoryMutationGateway 同名不同物 — **混淆名空间**

**重构含义**:
- ⭐⭐ **本文件是 Memory Refactor 的清理重灾区**
- **必清理**:
  - UnifiedMemoryGateway → 合并到 MemoryMutationGateway (统一名 MemoryHub)
  - HumorMemory → 合并到 RelationalState.inside_jokes
  - CorrectionMemory → 合并到 MemoryGateway 的 audit log
  - TaskWorkerPool → 删 (死代码)
- **保留**: SleepIntentDetector / CorrectionLoop / Anticipator (各自有用)

**审计结论**: ⭐⭐ 1513 行 12 类**最严重的概念重叠区**. 是 Phase B 核心清理目标.

---

### #16 `jarvis_memory_gateway.py` (734 行) — **MemoryMutationGateway (新统一 mutation API)**

**职责**: P2-Gap7 (2026-05-20) 立的统一 mutation API. 接收主脑 emit `<FAST_CALL>{"organ":"mutation",...}}` → 路由到 6 layer source (ProfileCard / Hippocampus / Concerns / Milestones / CommitmentWatcher / PromiseLog / RelationalState) → 写 audit `mutation_receipts.jsonl` + SWM publish.

**核心 class**:

| L | class | 功能 |
|---|---|---|
| 53 | `WriteReceipt` | dataclass — mutation_id / ts / iso / field_path / new/old_excerpt / source / confidence / layer_targeted / ok / error / turn_id |
| 97 | **`MemoryMutationGateway`** | ⭐⭐⭐ 主类 — `update_sir_field(field_path, new_value, source, confidence, turn_id, nerve)` |

**核心 method**:
- `update_sir_field` (~250 行) — 主入口, 路由 + audit + SWM publish
- `_maybe_cascade_completion(field_path, new_value, source, turn_id, nerve)` — fix82-X 加 (cascade Commitments cancel + add_completed_event + publish)
- `_load_completion_vocab()` — fix82-X 加 (vocab 持久化 `memory_pool/completion_event_vocab.json`)
- `_publish_swm(receipt)` — publish 'sir_field_updated' SWM
- `_write_receipt(receipt)` — append `mutation_receipts.jsonl`
- `recent_receipts(max_n, within_seconds)` — 查询
- top-level `_detect_target_layer(field_path)` — `field_path` 前缀 → layer 路由

**field_path 路由规则** (`_detect_target_layer`):
- `profile.X` / `biographic.X` / `sir.X` → ProfileCard
- `concerns.<cid>` / `concerns.<cid>.<attr>` → ConcernsLedger
- `milestones.X` → Milestones
- `commitment.cancel.<k>` / `commitment.update.<k>` → CommitmentWatcher
- `promise.fulfill.<k>` / `promise.cancel.<k>` → PromiseLog
- `relationships.<op>.<id>` / `protocol.X` / `unfinished.X` / `thread.X` → RelationalState

**数据**:
- 写: `memory_pool/mutation_receipts.jsonl` (统一 audit)
- 写: 通过 layer 路由调各 source
- SWM publish: 'sir_field_updated' (salience 0.80) / 'completion_cascaded' (fix82-X)
- 读: `memory_pool/completion_event_vocab.json` (fix82-X)

**上游**:
- `chat_bypass._execute_fast_call` organ='mutation' → 调 update_sir_field
- `worker.memory_correction` (P3-BUG#2) → 调 update_sir_field (路径 'preferences.user_correction', conf=0.5)
- `IntentResolver tool_*` → 调 update_sir_field (conf=0.9)

**下游**:
- 7 个 layer source: ProfileCard / Hippocampus / Concerns / Milestones / CW / PromiseLog / RelationalState
- SWM bus + receipts.jsonl

**跟记忆的耦合**:
- ⭐⭐⭐ **是 MemoryHub 的核心原型** — 现状已实现 6 layer routing, fix82-X 加 cascade. **应直接演化为 MemoryHub**, 不重写
- 唯一统一 mutation 入口

**已知问题**:
- `field_path` 前缀字符串 hardcoded 在 `_detect_target_layer` (74-95 行) — 可 vocab 化
- cascade 仅 1 类 (completion) — Phase B 应加更多 (param_update / commitment_cancel / etc.)
- 跟 `UnifiedMemoryGateway` (memory_core.py) **同名不同物** → Phase B 改名 MemoryHub

**重构含义**:
- ⭐⭐⭐ **本模块是 MemoryHub 的 80% 实现** — Phase D 应基于此演化, 不另起炉灶
- 改名: MemoryMutationGateway → MemoryHub (避免跟 UnifiedMemoryGateway 混淆)
- 加 cascade rules (现仅 completion, 加 param_update / commitment_cancel / promise_fulfill / etc.)
- 加 `read_context()` API (现状只 write, 无统一 read)

**审计结论**: ⭐⭐⭐ **是 MemoryHub refactor 的起点**. 不重写, 增量演化.

---

### #17 `jarvis_milestones.py` (235 行) — **Sir 终生 milestones (lifetime declaration)**

**职责**: Sir 自己声明的"重要时刻 / 不可对我用"的事 (e.g. "我有颈椎病" / "我和某人 5 年友谊"). 不是普通 profile field, 有特殊 do_not_use_against 规则.

**核心 functions** (无 class, 全函数式):

| L | func | 功能 |
|---|---|---|
| 86 | `load_milestones()` | 读 sir_milestones.json |
| 41 | `_store_path` | 路径 |
| 49 | `_empty_store` | 空 schema |
| 63 | `_load_raw` / 77 `_save_raw` | atomic IO |
| (其他 ~8 个) | add / list / archive / render_prompt_block / `tool_milestone_register` (Hippocampus 路由) |

**数据**:
- 读/写: `memory_pool/sir_milestones.json`

**上游**:
- `_assemble_prompt` render `[MILESTONES]` block
- `MemoryGateway` layer='Milestones' → 调 tool_milestone_register

**下游**: 仅 IO

**跟记忆的耦合**:
- ⭐ Layer A 子集 (静态身份的特殊部分)
- 跟 sir_profile.lifetime 概念上重叠 — `JARVIS_MEMORY_AND_MUTATION_REFACTOR.md` §2.3 模糊 3

**已知问题**:
- 跟 sir_profile.lifetime (如有) 重叠 — Phase B 判保留独立
- 无 class, 全函数式 — 可改 class style 一致

**重构含义**:
- **保留独立** — milestones 有 do_not_use_against 特殊规则, 不应混入 profile
- **跟 Memory Refactor 关系**: 是 MemoryHub.identity 的子 source

**审计结论**: 薄, 235 行函数式, 不大改.

---

### #18 `jarvis_stm_summarizer.py` (355 行) — **STM Reply 概括 (Gap-Z1)**

**职责**: 主脑 reply 太长时, 异步用小 LLM (Gemini-flash-lite) 概括成短文 → 写入 STM. 让 STM 30 turn 内不被长 reply 占满.

**核心 class**:

| L | class | 功能 |
|---|---|---|
| 158 | `STMSummarizer` | 主类 |

**核心 method / function**:
- `summarize_async(text, callback)` — fire-and-forget LLM
- `_call_summarize_llm` — 短 LLM
- `_load_config` (top-level) — 读 `memory_pool/stm_summarize_config.json`
- `is_enabled` — 配置开关
- `_cache_get / _cache_put` — LRU cache (避免重复概括)

**数据**:
- 读: `memory_pool/stm_summarize_config.json`
- 写: 通过 callback 写回 STM (`central_nerve._append_stm`)

**上游**:
- `chat_bypass.stream_chat` 末尾 fire-and-forget (reply 长时)

**下游**:
- LLM (Gemini-flash-lite via OR)
- callback → STM

**跟记忆的耦合**:
- 写 STM (短期), 不写 Hippocampus (长期)

**已知问题**:
- LLM cost (虽 lite 模型, 但每 reply 1 次) — 跟 Reflector Budget 联动
- LRU cache 大小 hardcoded?

**重构含义**:
- **保留** — STM 概括降低 prompt 长度, 有用
- **跟 Memory Refactor 关系**: STM 是 Layer B 事件的短期缓冲, 概括是优化

**审计结论**: 实用工具, 不大改.

---

### #19 `jarvis_profile_reflector.py` (414 行) — **ProfileReflector (sir_profile.json 演化 daemon)**

**职责**: 24h tick (fix81 改 5min) 扫 `profile_corrections.jsonl` 累积 → LLM propose 改动 → 写 `profile_review.json` → Sir CLI activate/reject.

**核心 class**:

| L | class | 功能 |
|---|---|---|
| 51 | `ProfileProposal` | dataclass — proposal_id / field_path / action / new_value / rationale / state |
| 69 | `ProfileReflector` | 主 daemon |

**核心 method**:
- `_scan_corrections` — 读 jsonl tail
- `_propose_changes_llm` — LLM 看 corrections + STM 提议 profile 改动
- `_persist_review_queue` — 写 `profile_review.json`
- `start_daemon(tick_interval_s)` — daemon 启动
- `apply_proposal(proposal_id, decision)` — Sir CLI 调 (activate / reject)

**数据**:
- 读: `memory_pool/profile_corrections.jsonl` (audit)
- 读: STM + ProfileCard (从 nerve 拿)
- 写: `memory_pool/profile_review.json` (review queue)
- 写: `jarvis_config/sir_profile.json` (Sir activate 后, 通过 ProfileCard.overwrite_field)

**上游**:
- `central_nerve.__init__` 启 daemon (env JARVIS_PROFILE_REFLECTOR=1)
- `scripts/profile_reflector_dump.py` Sir CLI

**下游**:
- LLM (Gemini-flash via OR)
- ProfileCard.overwrite_field

**跟记忆的耦合**:
- ⭐ profile.json 演化 — 是 Layer A 的更新机制
- 跟 ProfileCard.apply_correction 配套 (corrections 累积 → reflector propose)

**已知问题**:
- 默认 24h tick, fix81 缩到 5min (但默认未启)
- min_corrections=5 (fix81 改 1) 也太严
- 跟 IntentResolver 直接 emit profile.update_field 路径**冲突** — 主脑直 emit 走 MemoryGateway, Reflector 走 review queue, 但概念重叠

**重构含义**:
- ⭐ **保留** — Reflector 模式是准则 6.5 模范
- **整合**: 跟 MemoryGateway 的高置信跳 review 路径联动

**审计结论**: 414 行 daemon 实用, 但 tick / threshold 需 Sir 真测调.

---

### #20 `jarvis_promise_log.py` (575 行) — **Jarvis 自承诺账本 (PromiseExecutionLog)**

**职责**: Jarvis 嘴上说"我会监督你 X" 类承诺的真追踪. 区分 hard (有时间) / soft (无时间), 跟 ClaimTracer 配合 verify.

**核心 class**:

| L | class | 功能 |
|---|---|---|
| 90 | `Promise` | dataclass — id / kind (hard/soft) / description / created_at / deadline / state (pending/fulfilled/cancelled/overdue) |
| 120 | `PromiseExecutionLog` | 主 store |
| 515 | `PromiseSweepDaemon` | 周期 daemon (清 stale promise) |

**核心 method**:
- `register(description, kind, deadline_ts)` — 添加
- `mark_fulfilled(pid, evidence_kind, evidence_what)` — 兑现
- `mark_cancelled(pid, reason)` — 取消
- `mark_overdue(pid)` — 超时
- `list_pending` / `list_fulfilled` / `list_overdue`
- top-level `try_pair_evidence(evidence_kind, evidence_what)` (β.2.8.5) — tool 成功后自动配对最近 promise → fulfilled

**数据**:
- 读/写: `memory_pool/jarvis_promise_log.json`
- SWM publish: `_publish_promise_event` (top-level helper)

**上游**:
- `SelfPromiseDetector` 抽 promise → register
- `chat_bypass._execute_fast_call` 末尾 → try_pair_evidence
- `MemoryGateway` layer='PromiseLog' → 调 mark_fulfilled / mark_cancelled

**下游**: 内部 + SWM

**跟记忆的耦合**:
- ⭐ **Layer E 承诺的子 source** (Jarvis 自己的承诺 vs Sir 的承诺 = CommitmentWatcher)
- 跟 CommitmentWatcher 概念上重叠 — `JARVIS_MEMORY_AND_MUTATION_REFACTOR.md` §2.2 重叠 1 提出: "Promise Log + Commitment Watcher + concerns.notes_for_self 三套合并"

**已知问题**:
- 跟 CommitmentWatcher 重叠 — design doc 提出 PromiseLog 单源 + CW 退化为 timer engine, **未执行**
- soft promise 跟 concerns.notes_for_self 概念重叠

**重构含义**:
- ⭐⭐ **是 Layer E 的合并候选** — Phase B 必决定: PromiseLog 单源 vs 双源 (Jarvis + Sir 分开)
- `try_pair_evidence` 是 promise 兑现的核心 — Phase D 应保留

**审计结论**: ⭐ 跟 CommitmentWatcher 合并是 refactor 关键决策点.

---

### #21 `jarvis_commitment_watcher.py` (1933 行) — **CommitmentWatcher (Sir 承诺 + sqlite + 定时 nudge)**

**职责**: Sir 嘴上的承诺 (e.g. "10:30 提醒去洗澡"). 含: 抽承诺 + sqlite 持久化 (Commitments 表) + in-memory list + 定时检查 + nudge 触发 + cancel/update by keyword.

**核心 class**:

| L | class | 功能 |
|---|---|---|
| 267 | `CommitmentWatcher` | 主类 (~1700 行!) |

**核心 method (50+)**:
- `add_commitment(description, deadline_str, source='gatekeeper'/'self_promise')` — 主入口 (含 sqlite INSERT + in-memory + SWM publish 'sir_intent_deadline_candidate')
- `cancel_by_keyword(keyword, max_age_seconds=1800)` — fuzzy match 取消 (P0-3, fix82-X 用 24h 窗口)
- `update_by_keyword(keyword, new_description, new_deadline_str)` — 改
- `_check_due_commitments` — tick (1s) 检查到期
- `_fire_nudge(commit)` — 触发 [REMINDER FIRING NOW]
- `_to_24h(h, m, ampm)` — 时间转换
- top-level `_load_behavior_patterns_from_json` (vocab 加载) / `infer_concern_link` / `infer_expected_behavior` (β.5.46-fix13 行为推断)

**数据**:
- 读/写: `memory_pool/jarvis_memory.db` (Commitments 表, 通过 Hippocampus.add_commitment_row)
- 读: `memory_pool/behavior_inference_vocab.json` (准则 6.5)
- 读: `memory_pool/commitment_conditional_vocab.json`
- SWM publish: 'sir_intent_deadline_candidate' (β.5.44-B) / 'commitment_overdue' / 'reminder_fired'

**上游**:
- `worker.run` Gatekeeper LLM 抽 commit → 调 add_commitment
- `SelfPromiseDetector` (jarvis_self_promise.py) → 调 add_commitment
- `MemoryGateway` layer='CommitmentWatcher' → 调 cancel_by_keyword / update_by_keyword
- fix82-X cascade_completion → 调 cancel_by_keyword
- `_check_due_commitments` (tick daemon) 自启

**下游**:
- `Hippocampus.add_commitment_row / soft_delete_commitment`
- `chat_bypass.stream_nudge` (commitment_check fire 时)

**跟记忆的耦合**:
- ⭐⭐⭐ **是 Layer E 承诺的 source of truth** (Sir 承诺), 配套 PromiseLog (Jarvis 自承诺)
- 跟 PromiseLog 重叠 — `JARVIS_MEMORY_AND_MUTATION_REFACTOR.md` §2.2 重叠 1
- 跟 `cyclic_task` (循环承诺) + `watch_task` (等屏幕事件) 概念上 4 套时间承诺 系统

**已知问题**:
- 1933 行单 class — 极大
- 跟 PromiseLog / cyclic_task / watch_task **4 套时间承诺**, design doc 提出合并未执行
- `cancel_by_keyword` fuzzy match 不准 — Sir 22:06 真测痛点 (description "明天去医院咨询医生血压跟降压药" vs Sir 说"明天去血压咨询" 没命中)
- in-memory list 跟 sqlite 双层数据 — 同步不一致风险

**重构含义**:
- ⭐⭐⭐ **是 Layer E 的核心**, 跟 PromiseLog / cyclic_task / watch_task 必合并设计
- fuzzy match 应升级 (LLM-based, 不是字面 LIKE)
- in-memory + sqlite 应统一 (sqlite 唯一 truth)

**审计结论**: ⭐⭐ 1933 行核心模块. 4 套时间承诺合并是 refactor 重点.

---

### #22 `jarvis_self_promise.py` (580 行) — **SelfPromiseDetector (Jarvis 自承诺检测器)**

**职责**: 看 Jarvis reply, 检测"我会 X" 类承诺. 区分 hard (有时间, 进 CommitmentWatcher) vs soft (无时间, 进 concerns.notes_for_self / PromiseLog).

**核心 class**:

| L | class | 功能 |
|---|---|---|
| 225 | `SelfPromiseDetector` | 主类 |

**核心 method / function**:
- `detect(reply)` — 主入口, 返 promises list
- `detect_and_register(reply, commitment_watcher)` — detect + 自动注册到 CW
- top-level `_load_promise_vocab` / `_get_compiled_soft_patterns` (vocab 加载)

**数据**:
- 读: `memory_pool/promise_soft_vocab.json` (准则 6.5)
- 写: 通过 CommitmentWatcher.add_commitment + PromiseLog.register

**上游**: `chat_bypass.stream_chat` 末尾 fire-and-forget

**下游**:
- CommitmentWatcher.add_commitment (hard)
- PromiseLog.register (soft)

**跟记忆的耦合**:
- 间接 — 是 PromiseLog 和 CommitmentWatcher 的写入者

**已知问题**:
- vocab 持久化 ✅ (准则 6 模范)
- 跟 ConcernsLedger.notify_concern_aligned (Jarvis 对齐 concern 时的"我会监督") 概念交叉

**重构含义**:
- **保留** — vocab + L7 范式好
- **跟 Memory Refactor 关系**: 是 Layer E 的写入侧 detector

**审计结论**: 580 行实用 detector, 不大改.

---

### #23 `jarvis_cyclic_task.py` (398 行) — **CyclicTask (通用循环协议)**

**职责**: P5-fix35-C / 2026-05-23 立的"每 N 分钟/小时/天 X" 循环承诺. 主脑 emit `<FAST_CALL>{"organ":"cyclic_task",...}` 后, 系统展开成 N 个 reminder.

**核心 class**:

| L | class | 功能 |
|---|---|---|
| 55 | `CyclicTask` | dataclass — task_id / kind / interval_s / next_fire_ts / max_fires |
| 81 | `CyclicTaskStore` | 主 store + tick daemon |

**核心 method**:
- `register(kind, interval_s, ...)` — 添加, 自动展开 N 次
- `cancel(task_id)` — 取消
- `list_active`
- `_tick_check_due` — daemon 检查到期

**数据**:
- 读/写: `memory_pool/cyclic_task_dispatcher_vocab.json` (准则 6.5)
- 通过 CommitmentWatcher.add_commitment 间接写 sqlite

**上游**:
- `chat_bypass._execute_fast_call` organ='cyclic_task' → register

**下游**:
- CommitmentWatcher.add_commitment (注册每个展开的 reminder)

**跟记忆的耦合**:
- ⭐ Layer E 子 source (循环承诺特殊化, 区别于单次 commitment)
- 跟 CommitmentWatcher 是依赖 (cyclic 展开 = N 个 commitment)

**已知问题**:
- 跟 CommitmentWatcher 是双层 (cyclic 是抽象, commitment 是具体), refactor 时考虑合并

**重构含义**:
- **保留** — 循环承诺是真实需求, 抽象正确
- **跟 Memory Refactor 关系**: Layer E 子 source

**审计结论**: 398 行薄 store + tick, 实现合理.

---

## 批次 d: INTEGRITY 9 模块 (言出必行栈)

> 详 `JARVIS_INTEGRITY_STACK.md` (21KB 完整 design). INTEGRITY ABSOLUTE 是 Sir 立的"和 SOUL 同等地位" 第一原则.

### #24 `jarvis_claim_classifier.py` (290 行) — **INTEGRITY L1: Claim Classifier**

**职责**: 主脑 reply 抽 claim — 用 vocab patterns 分类 (commitment / completion / mutation / promise / refusal / etc.).

**核心 functions** (无 class, 全函数式 — vocab driven):

| L | func | 功能 |
|---|---|---|
| 161 | `get_classify_vocab()` | 加载 `memory_pool/claim_classify_vocab.json` |
| 196 | `_active_patterns` | 获取激活 patterns |
| 212 | `classify(reply)` | 主入口 — 返 list of (kind, span, confidence) |
| 268 | `get_loaded_stats` | 调试 |

**数据**:
- 读: `memory_pool/claim_classify_vocab.json` (准则 6.5 持久化)
- 配 CLI: `scripts/claim_classify_dump.py`

**上游**: `claim_tracer.extract_claims` 调

**下游**: 无 (纯函数式)

**跟记忆的耦合**: 无直接, 是 INTEGRITY 链路的第 1 步

**已知问题**: vocab 持久化 + L7 propose ✅ (准则 6 模范)

**关联 design doc**: `JARVIS_INTEGRITY_STACK.md` L1 完整设计

**重构含义**: ⭐ **保留** — 模式典范, 不大改

---

### #25 `jarvis_evidence_requirements.py` (244 行) — **INTEGRITY L2: Evidence Requirements**

**职责**: 各 claim kind 应该有什么 evidence (e.g. commitment claim 应该有 CommitmentWatcher receipt + deadline). vocab driven.

**核心 functions** (无 class):

| L | func | 功能 |
|---|---|---|
| 141 | `get_evidence_requirements_vocab()` | 加载 vocab |
| 189 | `get_requirements(claim_kind)` | 主入口 |

**数据**:
- 读: `memory_pool/evidence_requirements.json`

**上游**: `claim_tracer.verify` 调

**跟记忆的耦合**: 无 (是规则定义)

**已知问题**: vocab 持久化 ✅

**重构含义**: ⭐ **保留** — L2 evidence 规则中央定义

---

### #26 `jarvis_claim_tracer.py` (889 行) — **INTEGRITY L3: Claim Tracer (通用防说谎)**

**职责**: 主入口 — 抽 claim + 跟实际 mutation_receipts / SWM / commitment / promise / reminder 配对 verify. 主脑说"我已记下" 没真改 → 标 unverified → 下轮 INTEGRITY ALERT.

**核心 class + functions**:

| L | item | 功能 |
|---|---|---|
| 104 | `Claim` (dataclass) | claim 实体 (kind / span / confidence / extracted_meta) |
| 123 | `extract_claims(reply)` (top-level) | 主入口 — 调 classifier + 抽 meta |
| ~30 个 helpers | `_check_time_within_2min` / `_check_evidence_kind` / `verify_against_*` / `retry_*` | 各 claim kind 的 verifier |

**数据**:
- 读: `memory_pool/integrity_claim_vocab.json`
- 读: `mutation_receipts.jsonl` (gateway audit) / SWM events / Hippocampus / CommitmentWatcher / PromiseLog
- 写: `memory_pool/claim_revisions.json` (revision 路径) / `claim_stats.json`

**上游**:
- `chat_bypass.stream_chat` 末尾 + `stream_nudge` 末尾 调
- `IntegrityWatcher` post-stream verify

**下游**:
- `MemoryGateway.recent_receipts` (查 mutation 审计)
- 各 source (Hippocampus / CW / PromiseLog) 的 list / search

**跟记忆的耦合**:
- ⭐⭐ **是 INTEGRITY 跟 Memory 的 bridge** — 验主脑 claim 是否真有 mutation receipt
- 是 mutation_receipts.jsonl 的主消费者

**已知问题**:
- 889 行函数式 + 30+ helper — 可拆 (各 verifier 独立)
- vocab 持久化 ✅

**重构含义**: ⭐⭐ **保留 + 拆** — 核心 verify 逻辑, 应保留. helper 可独立 sub-module

---

### #27 `jarvis_claim_revision_log.py` (528 行) — **Claim Revision Log (区分 ritual vs functional revision)**

**职责**: P5-fixCB-revise — 主脑 reply 主动 functional revision (e.g. 改自己说错的话) 应记录, 区别于纯礼仪修正.

**核心 class**:

| L | item | 功能 |
|---|---|---|
| 63 | `ClaimRevision` (dataclass) | revision 实体 |
| 103 | `ClaimRevisionStore` | 主 store |
| 286 (top) | `capture_revision_from_reply(reply)` | 主入口 — 抽 revision |
| 388 | `detect_sir_querying_capability` | Sir 反讥能力时检测 |

**数据**:
- 读/写: `memory_pool/claim_revisions.json`

**上游**: `chat_bypass.stream_chat` 末尾 调 capture_revision_from_reply

**下游**: 内部 + audit log

**跟记忆的耦合**: ⭐ 跟 mutation_receipts 配套 (revision 跟 mutation 是 2 类记录)

**已知问题**: 跟 `claim_stats.json` 重叠 (3 个 jsonl 都跟 claim 有关)

**重构含义**:
- ⭐ 保留 — functional revision 是 INTEGRITY 真意
- **整合**: 跟 `mutation_receipts.jsonl` + `claim_stats.json` 三 audit 应合并 1 个统一 audit log (`mem_audit.jsonl`)

**审计结论**: 528 行实用. audit 合并是 Phase D 任务.

---

### #28 `jarvis_integrity_watcher.py` (1847 行) — **IntegrityWatcher (post-stream verify + retry)**

**职责**: P5-IntegrityWatcher — Jarvis 自检栈核心. 后台 verify + retry 失败 claim. e.g. 主脑说"set reminder" 失败 → watcher 重新调 hippocampus.add_reminder retry.

**核心 class + helpers**:

| L | item | 功能 |
|---|---|---|
| 106 | `Claim` (dataclass, 这里有自己的版本! 跟 #26 重叠?) | watcher 内部的 claim |
| 514 | `IntegrityWatcherStore` | 持久化 |
| 1043 | **`IntegrityWatcher`** | 主类 (~800 行!) |
| 1572 | `_LlmClaimJudge` | LLM 评估 (Gemini-flash) |
| 30+ top-level | `_load_claim_vocab` / `_get_compiled_detectors` / `_load_suspicious_kw` / various retry helpers | helpers |

**核心 method** (在 IntegrityWatcher class):
- `verify_async(reply, ...)` — 主入口
- `retry_reminder` / `retry_commitment` / `retry_memory` / `retry_promise` — 各 claim 类型 retry
- `_load_*` (vocab loaders)

**数据**:
- 读: `memory_pool/integrity_claim_vocab.json` / `integrity_suspicious_kw.json`
- 写: `memory_pool/integrity_audit.jsonl` (audit) / `integrity_watcher.json` (state)
- SWM publish: `hallucination_detected` (主脑 claim 没 evidence)

**上游**: `chat_bypass.stream_chat` 末尾 fire-and-forget

**下游**:
- Hippocampus / CommitmentWatcher / PromiseLog (retry 时调)
- LLM (LlmClaimJudge)

**跟记忆的耦合**:
- ⭐⭐⭐ **是 INTEGRITY 防主脑撒谎的最后防线**
- retry 失败 claim → 真调 module → 真补救 (β.5.43 立, Sir 准则 5 言出必行)

**已知问题**:
- 1847 行单文件含 4 class + 30+ helpers — 太大
- `Claim` 跟 `claim_tracer.py:Claim` 同名不同 dataclass (不同字段) → **混淆**
- 跟 `claim_tracer` 重叠 — 都做 verify, 但概念分: tracer = 抽 + 验 (sync), watcher = 后台 retry (async)

**关联 design doc**: `JARVIS_INTEGRITY_STACK.md` 完整 21KB

**重构含义**:
- ⭐⭐ **是 INTEGRITY 真治本机制** — Phase B 应保留, 但 1847 行必拆
- `Claim` 跟 tracer 应统一 dataclass
- 跟 tracer 边界要清

**审计结论**: ⭐ 1847 行核心模块. 拆 + Claim 统一是 refactor 重点.

---

### #29 `jarvis_integrity_reflector.py` (767 行) — **INTEGRITY L7: Reflector (LLM-propose 新 evidence rule)**

**职责**: L7 LLM-propose — 看 audit log 抽 patterns, propose 新 evidence rule 进 review queue.

**核心 class**:

| L | item | 功能 |
|---|---|---|
| 66 | `ClaimStatsDumper` | claim 统计 dump 工具 (1d tick) |
| 235 | `IntegrityReflector` | 主 daemon |
| 36 (top) | `dump_claim_stats` | 工具 |

**数据**:
- 读: `memory_pool/integrity_audit.jsonl` (audit) + `claim_stats.json`
- 写: `memory_pool/claim_stats.json` + Reflector propose review queue

**上游**: `central_nerve.__init__` start daemon

**下游**: LLM (Gemini-flash via OR)

**跟记忆的耦合**: 间接 — 是 INTEGRITY audit 的反思层

**已知问题**: 跟 ProfileReflector / SoulReflector / Reflector Budget 共享 LLM pool — Phase B 应统一调度

**重构含义**: ⭐ 保留 — L7 LLM-propose 是准则 6 模范

**审计结论**: 767 行 daemon, 不大改.

---

### #30 `jarvis_inconsistency_watcher.py` (462 行) — **Commitment Inconsistency Watcher (Layer B)**

**职责**: 检测 Sir 真行为 vs Sir 自己承诺的不一致 (e.g. Sir 说"我会 11 点睡" 但 23:30 还在 coding). 写 inconsistency events, 让主脑下轮看到 evidence 自决怎么提醒 (不预设话术).

**核心 class**:

| L | item | 功能 |
|---|---|---|
| 168 | `InconsistencyWatcher` | 主类 |
| 80 (top) | `_load_inconsistency_vocab_from_json` | vocab 加载 |
| 113 | `_get_inconsistency_vocab` | getter |
| 135-145 | `get_sir_sleep_verbs` / `get_sir_break_verbs` / `get_jarvis_wrapper_markers` | helper |

**数据**:
- 读: `memory_pool/inconsistency_vocab.json`
- 读: STM + CommitmentWatcher
- SWM publish: `inconsistency_detected` (主脑下轮看 evidence)

**上游**: daemon (周期 tick) 或 `chat_bypass` 触发

**下游**: SWM bus

**跟记忆的耦合**: 间接 — 读 STM + Commitments

**已知问题**: vocab 持久化 ✅

**重构含义**: ⭐ **保留** — 是 INTEGRITY 行为层的实时检测

**审计结论**: 462 行实用, 不大改.

---

### #31 `jarvis_callback_guard.py` (416 行) — **Unsolicited Callback Guard (5+ 防误报)**

**职责**: P5-fixCB — 检测主脑 reply 含"未邀请的 callback" (e.g. Sir 说"晚安", Jarvis 跟"你昨天的代码 BUG 我修了"是 unsolicited). 抓 5+ 类 forbidden 短语.

**核心 functions** (无 class):

| L | func | 功能 |
|---|---|---|
| 47 | `_load_vocab` | 加载 `forbidden_callback_vocab.json` |
| 93 | `reset_vocab_cache` | reset |
| 104 | **`scan_for_unsolicited_callback(reply, sir_utterance, vocab_path)`** | 主入口 |
| 159 | `_sir_invited_callback` | Sir 主动邀请检测 |
| 174 | `publish_callback_violation` | publish 违规 SWM |

**数据**:
- 读: `memory_pool/forbidden_callback_vocab.json` (准则 6.5)

**上游**: PreFlight / chat_bypass scan reply

**下游**: SWM publish + log audit

**跟记忆的耦合**: 无直接 — 是 reply 后的检测器

**已知问题**: vocab 持久化 ✅

**重构含义**: ⭐ 保留 — 准则 6 模范

**审计结论**: 416 行 detector, 不大改.

---

### #32 `jarvis_meta_self_check.py` (459 行) — **META Self-Check parser (thinking pass 元层自检)**

**职责**: P5-Layer1-fix19 — 主脑 reply 末尾 emit `[META] evidence=... reaction=... skip_alert=...` 格式自评. 本模块 parse + 验真. 检测主脑是否乱说自己 reaction.

**核心 class + helpers**:

| L | item | 功能 |
|---|---|---|
| 56 | `MetaSelfCheck` | 主类 |
| 95 (top) | `parse_meta(reply)` | 抽 META block + parse |
| 186 | `publish_meta` | publish META 信号 |
| 261 | `read_recent_meta` | 查最近 META |
| 291 | `check_commitments_vs_mutations` | 验 META 跟实际 mutation 一致 |

**数据**:
- 读: STM + reply
- 写: `memory_pool/main_brain_meta_audit.jsonl` (META audit)
- SWM publish: 'meta_self_check'

**上游**: `chat_bypass.stream_chat` 末尾

**下游**: 内部 + SWM + audit

**跟记忆的耦合**: ⭐ META 是主脑自评机制, 跟 mutation_receipts 配对验

**已知问题**: META block 格式 hardcoded — 但跟 directive 教学一致, 不是 vocab

**重构含义**: ⭐ 保留 — 是主脑自检环节

**审计结论**: 459 行实用 parser + verifier, 不大改.

---

## 批次 e: IntentResolver + Directive + Mutation 8 模块

### #33 `jarvis_directives.py` (3959 行) — **L2 Conditional Directives Registry (130+ directive 教学)**

**职责**: 中央 conditional directive 注册库. 130+ 条 directive 各自含 `id / trigger_fn / text / priority / ttl / purpose_short`. 装配 prompt 时按 trigger 匹配 inject 适用的 ~10 条.

**核心 class**:

| L | item | 功能 |
|---|---|---|
| 47 | `DirectiveContext` | dataclass — turn context (sir_input / jarvis_last / sir_status / etc.) |
| 101 | `Directive` | dataclass — id / text / priority / ttl_days / trigger / source_marker |
| 136 | **`DirectiveRegistry`** | 主类 — register / get / decay / inject |

**核心 functions** (80+ top-level):
- 80+ `_has_*` / `_user_input_*` / `_jarvis_reply_*` / `_trigger_*` (各 directive 的 trigger_fn 实现)

**数据**:
- 读: `memory_pool/directive_registry.json` (持久化注册 + counter)
- 读: `memory_pool/directives_vocab.json` / `directive_inject_config.json`
- 写: `directive_registry.json` (decay counter + last_fired_ts)

**上游**:
- `central_nerve.__init__` 启 decay daemon (β.0.1)
- `_assemble_prompt` 调 `inject_for(context)` 装配 directive block
- `DirectiveEvaluator` 评 directive 是否 helped

**下游**: 内部 + STM/SWM read

**跟记忆的耦合**:
- ⭐ 130+ directive 是主脑教学的中心
- 部分 trigger 读 mutation_receipts / SWM / Hippocampus

**已知问题**:
- 3959 行单文件 — 是历史累积巨型 (P0+20-β.0.1 起)
- 80+ trigger_fn 散在 top-level — 难维护
- 跟 `directive_evaluator` 是 2 半 (这里定义, evaluator 评)
- vocab + 持久化 + L7 ✅ (准则 6 模范, 但文件本身太大)

**关联 design doc**: `JARVIS_DIRECTIVE_SELF_AWARENESS.md`

**重构含义**: ⭐⭐ 必拆 — 130 directive 按 family 分文件 (commitment/memory_correction/sleep/integrity/...)

**审计结论**: ⭐ 3959 行最大单文件. 拆 + 分类是 Phase D 任务.

---

### #34 `jarvis_directive_evaluator.py` (398 行) — **DirectiveEvaluator (Gemini-flash 异步评 helped/fired)**

**职责**: 每轮对话后异步用 Gemini-flash 评 inject 的 directive 是否真 helped (rated 0-1) → 写 directive 的 helped/fired 计数.

**核心 class**:

| L | item | 功能 |
|---|---|---|
| 86 | `EvalResult` | dataclass |
| 98 | `DirectiveEvaluator` | 主类 |

**数据**:
- 写: `directive_registry.json` 的 helped/fired 计数 + `directive_review.json` (低分 directive 进 review)
- LLM: Gemini-flash via OR

**上游**: `chat_bypass.stream_chat` 末尾 fire-and-forget

**下游**: LLM + DirectiveRegistry

**跟记忆的耦合**: 间接

**已知问题**: 跟 SoulEvaluator + IntegrityReflector 共享 LLM pool — Phase B 应统一调度

**重构含义**: ⭐ 保留, 跟 evaluator pool 一起设计

**审计结论**: 398 行 evaluator, 跟 directives 配套.

---

### #35 `jarvis_intent_resolver.py` (855 行) — **IntentResolver (β.5.44 — Sir 一句话集中 LLM judge)**

**职责**: β.5.44 重构 — Sir 一句话, 7 module publish-only candidate event, IntentResolver 集中 LLM judge 决定调哪个 tool. 替代分散 sentinel 各自硬决策.

**核心 class**:

| L | item | 功能 |
|---|---|---|
| 92 | **`IntentResolver`** | 主类 (~750 行) |

**核心 method**:
- `resolve(user_input, candidates)` — 主入口
- `_call_llm_judge` — Gemini judge
- `_dispatch_tool(tool_name, params)` — 调 TOOL_REGISTRY
- `_publish_intent_resolved` — publish 'intent_resolved' SWM (salience 0.90 必看)

**数据**:
- 读: SWM `sir_intent_*_candidate` events (7 类)
- 读: `memory_pool/intent_to_tool_map.json` (vocab)
- 写: `memory_pool/intent_resolver_telemetry.json` (audit)
- SWM publish: 'tool_called' (0.85) / 'intent_resolved' (0.90)

**上游**:
- `worker.run` 调 (Sir 一句话后, 7 sentinel 各自 publish 完后)

**下游**:
- TOOL_REGISTRY 内 mutation tools
- LLM (Gemini judge)

**跟记忆的耦合**:
- ⭐⭐⭐ **是 Sir 真意"7 module publish + 主脑集中决策" 的核心**
- 调 mutation_correction_apply / profile_field_update / commitment_register / etc.

**已知问题**:
- 跟 chat_bypass `_execute_fast_call` mutation organ 路径 **2 套**:
  - 主脑直 emit FAST_CALL → chat_bypass 派
  - Sentinel publish candidate → IntentResolver judge → tool — Phase B 必整合

**关联 design doc**: `JARVIS_INTENT_RESOLVER_REFACTOR.md`

**重构含义**: ⭐⭐ 跟 chat_bypass FAST_CALL dispatch 联动整合

**审计结论**: 855 行核心模块. 是 Sir 真意 publish-only 模式的代表. Phase B 整合.

---

### #36 `jarvis_intent_router.py` (326 行) — **IntentRouter (β.5.36-G intent → tool 路由)**

**职责**: 把 intent 抽象 → tool 调用. 老路径 (β.5.36-G), 跟 IntentResolver 概念上**重叠**?

**核心 class**:

| L | item | 功能 |
|---|---|---|
| 46 | `IntentCall` | dataclass |
| 53 | `IntentParser` | 抽 intent |
| 105 | `IntentRouter` | 主类 |

**数据**: 读 `intent_to_tool_map.json`

**上游**: 不清楚 (跟 IntentResolver 重叠?), 待 Phase A.4 耦合矩阵确认

**下游**: TOOL_REGISTRY

**跟记忆的耦合**: 间接

**已知问题**:
- ⚠️ 跟 IntentResolver 同一概念 — Phase B 必判: 留 1 个 / 合并

**重构含义**: ⭐ 待 Phase B 决议: 跟 IntentResolver 必合并

**审计结论**: 326 行老路径, 跟 IntentResolver 重叠待清.

---

### #37 `jarvis_tool_registry.py` (399 行) — **TOOL_REGISTRY (mutation tools 中央注册)**

**职责**: β.5.44-D — 注册 IntentResolver 和 chat_bypass 调的 mutation tool. 含 `tool_concern_progress_update / tool_memory_correction_apply / tool_commitment_register / tool_self_promise_register / tool_profile_field_update / tool_milestone_register / ...`.

**核心 functions** (无 class, 全函数式 7+ tools):

| L | func | 功能 |
|---|---|---|
| 36 | `tool_concern_progress_update` | concern 进度更新 (Sir 反馈 progress 时) |
| 98 | `tool_memory_correction_apply` | 记忆纠正 (Sir 教正时) |
| 其他 | `tool_commitment_register` / `tool_self_promise_register` / `tool_profile_field_update` / `tool_milestone_register` / `tool_recall_memory` / `tool_search_memory` / `tool_concern_dismiss` |

**数据**:
- 写: 各 mutation 通过 MemoryGateway.update_sir_field
- 读: 各 source 通过相应 list/search

**上游**: IntentResolver._dispatch_tool / chat_bypass._execute_fast_call

**下游**: MemoryGateway + 各 source

**跟记忆的耦合**: ⭐⭐⭐ **是 mutation 工具中央**, IntentResolver 主脑都通过它

**已知问题**: 跟 chat_bypass 内 organ dispatch 部分重叠 — Phase B 整合

**关联 design doc**: `JARVIS_INTENT_RESOLVER_REFACTOR.md`

**重构含义**: ⭐⭐ 是 MemoryHub.write 的 tool 接口

**审计结论**: 399 行实用 tool 集合, 跟 MemoryGateway 配套.

---

### #38 `jarvis_skill_registry.py` (2560 行) — **SkillRegistry (130 skill 自我成长地图)**

**职责**: 轴 3-L0 — Jarvis 的"我能做什么"地图. 130+ skill 从 l4_hands_pool / l2_eyes_pool 自动入册 + autosave + PromiseParser/Activator/Executor (执行计划).

**核心 class** (9 个):

| L | item | 功能 |
|---|---|---|
| 78 | `SkillManifest` | dataclass |
| 218 | `SkillRegistry` | 主 store |
| 808 | `OfferGuard` | 防主脑乱 offer 没 skill 的能力 |
| 1006 | `PromiseParseError` | exception |
| 1010 | `PromiseDraft` | dataclass |
| 1060 | `PromiseParser` | 主脑 reply parse 成 plan |
| 1256 | `PromiseActivator` | 激活 plan 跑步骤 |
| 1422 | `SkillScanner` | 自动扫 hands_pool 入册 |
| 1871 | `PromiseExecutor` | 真跑步骤 + 反推 + 重试 + dangerous 二次确认 |
| 2392 | `CapabilityClaimValidator` | 验主脑 reply 含 capability claim 是否真有 skill |

**数据**:
- 读/写: `memory_pool/skill_registry.jsonl` (autosave 60s)
- 读: 扫 `l4_hands_pool/*.py` + `l2_eyes_pool/*.py` 抽 manifest

**上游**:
- `central_nerve.__init__` bootstrap (轴 3-L0.3 / P0+18-a.1)
- `OfferGuard` 在 chat_bypass / preflight 调
- `PromiseExecutor` 在 plan 跑步骤时调

**下游**:
- 24 hands (l4_*.py) — 通过 manifest 调
- LLM (PromiseParser 抽 plan)

**跟记忆的耦合**:
- ⭐⭐ **是 capability ground truth** — 主脑 claim "我能做 X" 必查 SkillRegistry 验
- 跟 INTEGRITY 配合 (CapabilityClaimValidator)

**已知问题**:
- 2560 行 9 class — 极大. 应拆 (registry / scanner / executor / validator 各独立)
- PromiseParser/Activator/Executor 跟 chat_bypass FAST_CALL dispatch 概念重叠
- 跟 PlanLedger (utils.py) 关系待清

**重构含义**: ⭐⭐ 必拆. 跟 plan 系统 (PlanLedger / PromiseExecutor) 整合

**审计结论**: 2560 行第 2 大单文件. 拆 + 整合是 Phase D 任务.

---

### #39 `jarvis_fuzzy_resolver.py` (208 行) — **Fuzzy Entity Resolver (ASR 实体容错)**

**职责**: P0+18-b.8 — ASR 转录的实体名 (e.g. "微信" 转成 "Vision") fuzzy 找最接近的真实进程/窗口名.

**核心 functions** (无 class):

| L | func | 功能 |
|---|---|---|
| 46 | `_normalize` | 字符串归一化 |
| 69 | `fuzzy_resolve_entity(target, candidates)` | 主入口 (fuzz + 中英文混) |
| 137 | `get_running_process_names` | 获取当前进程名 list |
| 163 | `format_fuzzy_candidates_for_msg` | 格式化候选给主脑 |

**数据**: 无持久化

**上游**: chat_bypass / IntentResolver 调

**下游**: psutil 进程列表 + win32api

**跟记忆的耦合**: 无

**已知问题**: 实用工具, 不大改

**重构含义**: 保留

**审计结论**: 208 行实用 helper.

---

### #40 `jarvis_prompt_builder.py` (246 行) — **PromptBuilder (P5-fix54 新统一 builder)**

**职责**: P5-fix54 / 2026-05-23 立的 prompt builder 体系. `BlockSpec` (id / content / tiers / salience / hint) + `PromptBuilder` (注册 block + tier 路由 + salience 排序 + audit).

**核心 class**:

| L | item | 功能 |
|---|---|---|
| 47 | `BlockSpec` | dataclass — 描述 1 个 prompt block |
| 82 | **`PromptBuilder`** | 主类 — register + compose + audit |

**核心 method**:
- `register(block_spec)` — 注册 block
- `compose(persona, user_input, footer, include_meta_hint)` — 拼装 prompt
- `_select_blocks_for_tier(tier, max_chars)` — 按 tier 选
- `audit` — 输出 prompt 装配 debug info
- top-level `make_sensor_block_spec` / `make_swm_block_spec` — 标准 helper

**数据**: 无持久化 (每轮临时构造)

**上游**:
- `central_nerve._assemble_prompt` 调 (Phase 3a 起 — REMINDER_FIRING / Wake / SHORT_CHAT 已迁)

**下游**: 无

**跟记忆的耦合**: 无直接 — 但是 _assemble_prompt 重构的方向 (从 30+ render block → builder 统一)

**已知问题**:
- 仅 3 个 tier 已迁 (REMINDER_FIRING / WAKE_ONLY / SHORT_CHAT) — STANDARD/CRITICAL 还在 _assemble_prompt 老路径
- 应 Phase D 全迁

**关联 design doc**: `PROMPT_REFACTOR_PLAN.md`

**重构含义**:
- ⭐⭐ **是 _assemble_prompt 重构的工具** — Phase D 应 STANDARD/CRITICAL tier 也迁过来
- **跟 Memory Refactor 关系**: 是 MemoryHub.read_context() 的实施工具

**审计结论**: 246 行薄但关键. Phase D 应充分用.

---

## 批次 f: Proactive Care + Nudge + Conductor 10 模块

> 详 `JARVIS_PROACTIVE_CARE_ENGINE.md`. 主动关怀引擎是 Sir 真意"懂我" 的体现.

### #41 `jarvis_proactive_care.py` (1874 行) — **ProactiveCareEngine 主动关怀引擎**

**职责**: 周期 tick 看 ConcernsLedger top concern + 时段 + Sir state, 决定要不要主动 nudge. 含 7 个 sub-class.

**核心 class** (8 个):

| L | item | 功能 |
|---|---|---|
| 215 | `CareSignal` / 225 `CareEvidence` | dataclass |
| 248 | `CareConcernSensor` | sensor — 评 concern timing |
| 597 | `CareSignalCollector` | 集合各 evidence |
| 743 | `CareWindowGuard` | 时段 guard (e.g. 不要凌晨 nudge) |
| 861 | `CareSubjectSelector` | 选哪个 concern surface |
| 1038 | `CareSpeechSynth` | nudge 文案 (但已 publish-only, 不再 hard 生成) |
| 1413 | **`ProactiveCareEngine`** | 主类 |

**核心 functions** (top-level helpers):
- `_compute_concern_timing_evidence` / `_load_sir_sleep_pattern` / `_load_cooldown_vocab` / etc. (~10 个)

**数据**:
- 读: `concerns.json` / `proactive_care_cooldown_vocab.json` / `sir_sleep_pattern_vocab.json` / SWM
- SWM publish: `concern_active` / `proactive_nudge` / `nudge_window_advice`

**上游**: `central_nerve.__init__` 启 daemon (β.2.8)

**下游**:
- ConcernsLedger / SWM / `chat_bypass.stream_nudge`

**跟记忆的耦合**: ⭐⭐ 是 ConcernsLedger 的主消费者 (top concern surface)

**已知问题**:
- 1874 行 8 class — 可拆 (各 sub class 独立)
- `CareSpeechSynth` 已 publish-only (β.5.0 三维耦合) 但 1038 行还有 — 待清

**关联 design doc**: `JARVIS_PROACTIVE_CARE_ENGINE.md` (12KB)

**重构含义**:
- ⭐ 必拆 — 8 sub class 各独立
- `CareSpeechSynth` 已退化, 应删

**审计结论**: 1874 行核心 nudge 引擎. 拆 + 清理是任务.

---

### #42 `jarvis_smart_nudge.py` (1011 行) — **SmartNudge 哨兵 (11 类 nudge + type-mute + humor_memory)**

**职责**: P0+19-6.e — 全 Jarvis 唯一允许"主动开口"的 sentinel. 11 类 nudge (commitment_check / sleep_due / morning_greet / return_greet / posture / hydrate / pomodoro / focus_check / break_remind / schedule_check / random_companion).

**核心 class**:

| L | item | 功能 |
|---|---|---|
| 117 | `SmartNudgeSentinel` | 主类 (~900 行) |

**数据**:
- 读: `recent_nudges.jsonl` / SWM / ConcernsLedger / sir_status / habit_clock
- 写: `recent_nudges.jsonl` (anti-repeat 历史)
- SWM publish: `proactive_nudge`

**上游**:
- `central_nerve.__init__` 启 sentinel
- `companion_center.start_all`

**下游**: `chat_bypass.stream_nudge`

**跟记忆的耦合**: ⭐ 跟 RecentNudgeMemory 配套, 跟 ConcernsLedger 同步

**已知问题**:
- 1011 行 1 class — 大
- 11 类 nudge 各分支 hardcoded — 可 vocab 化

**重构含义**: ⭐ 拆 11 类各 sub-method. 跟 ProactiveCare 是 2 种主动机制 (PC = 智能 / SN = 节奏)

**审计结论**: 1011 行核心 nudge 模块.

---

### #43 `jarvis_recent_nudge_memory.py` (271 行) — **RecentNudgeMemory (P2-Gap12 通过去 nudge 记忆)**

**职责**: P2-Gap12 — 防 30min 内同类 nudge 重复. 持久化 jsonl + decay daemon.

**核心 class**:

| L | item | 功能 |
|---|---|---|
| 42 | `NudgeRecord` | dataclass |
| 85 | `RecentNudgeMemoryStore` | 主 store |

**数据**: 读/写 `memory_pool/recent_nudges.jsonl`

**上游**: SmartNudge / ProactiveCare / chat_bypass.stream_nudge

**下游**: 无

**跟记忆的耦合**: 间接

**重构含义**: ⭐ 保留 — 防重复机制

**审计结论**: 271 行实用 store.

---

### #44 `jarvis_nudge_coordination.py` (143 行) — **NudgeCoordination (β.5.0 三维耦合 sentinel 协调)**

**职责**: P5-fixC — sentinel proactive nudge 协调. `should_yield_to_recent_proactive_nudge` 检测 30s 内已 nudge 过 → skip. publish/skip helper.

**核心 functions** (无 class):

| L | func | 功能 |
|---|---|---|
| 26 | `should_yield_to_recent_proactive_nudge` | 检测最近 nudge → skip |
| 80 | `publish_proactive_nudge_fired` | publish 'proactive_nudge_fired' SWM |
| 112 | `publish_proactive_nudge_skipped` | publish 'proactive_nudge_skipped' SWM |

**数据**: SWM read/publish

**上游**: SmartNudge / ProactiveCare 调

**下游**: SWM bus

**跟记忆的耦合**: 无

**重构含义**: ⭐ 保留 — β.5.0 协调 helper

**审计结论**: 143 行薄 helper.

---

### #45 `jarvis_concern_dampen.py` (170 行) — **CONCERN_DAMPEN tag parser**

**职责**: P5-fix45 — 主脑 reply 主动 emit `<CONCERN_DAMPEN>{...}</CONCERN_DAMPEN>` tag 反讽降 concern severity. 比硬 dismiss 软.

**核心 functions**:

| L | func | 功能 |
|---|---|---|
| 61 | `ParsedDampen` (dataclass) | parse 结果 |
| 77 | `parse_dampen_tags(reply)` | 抽 tag |
| 99 | `apply_dampen(parsed, ledger)` | 改 concern severity |
| 160 | `process_reply(reply, ledger)` | 主入口 |

**数据**: 通过 ConcernsLedger.record_signal 写

**上游**: chat_bypass.stream_chat 末尾

**下游**: ConcernsLedger

**跟记忆的耦合**: ⭐ 写 concerns severity

**重构含义**: ⭐ 保留 — 主脑反讽机制

**审计结论**: 170 行实用 parser.

---

### #46 `jarvis_concern_feedback.py` (251 行) — **ConcernFeedbackJudge (LLM 评 Sir 反馈 → severity_delta)**

**职责**: P0+20-β.5.22-C — Sir 反馈 nudge 效果时 (e.g. "好的, 我去喝水了" / "别再提了"), LLM 评 severity_delta + optimal_timing → 写回 ConcernsLedger.

**核心 class**:

| L | item | 功能 |
|---|---|---|
| 38 | `ConcernFeedbackJudge` | 主类 |

**核心 method**:
- `judge_async(user_input, last_nudge_concern, callback)` — fire-and-forget
- `_call_llm_judge` — Gemini-flash via OR
- `record_user_feedback` — 写 ConcernsLedger.record_signal + publish 'sir_intent_progress_candidate'

**数据**: 读 STM, 写 concerns.json, SWM publish

**上游**: `worker.run` 在 nudge 后 Sir 反馈时调

**下游**: ConcernsLedger + LLM + SWM

**跟记忆的耦合**: ⭐ 写 concerns.severity (LLM 决策)

**已知问题**:
- LLM 决 severity_delta — 应 publish 给主脑自决 (但实际 LLM 已是 publish 候选)

**重构含义**: ⭐ 保留 — 反馈学习机制

**审计结论**: 251 行实用 judge.

---

### #47 `jarvis_concern_feedback_reflector.py` (282 行) — **ConcernFeedbackReflector (L7 LLM-propose)**

**职责**: P0+20-β.5.23-B — daemon 看 ConcernFeedback 历史, propose 新 concern 关联 / vocab.

**核心 class**:

| L | item | 功能 |
|---|---|---|
| 45 | `ConcernFeedbackReflector` | 主 daemon |

**数据**: 读 audit, 写 review queue

**上游**: central_nerve daemon

**下游**: LLM

**跟记忆的耦合**: 间接

**重构含义**: 保留 — L7 模式

**审计结论**: 282 行 daemon.

---

### #48 `jarvis_concern_summon.py` (109 行) — **Concern Summon Detector (vocab loader)**

**职责**: P5-Gap4-followup-vocab — 检测 Sir 主动召唤 concern (e.g. "你有没有 X concern" → top up that concern severity).

**核心 functions**:

| L | func | 功能 |
|---|---|---|
| 54 | `_load_from_disk` | vocab 加载 |
| 78 | `load_active_keywords` | 获取激活 keywords |
| 92 | `is_summoned(user_input, concern_id)` | 检测 |

**数据**: 读 `concern_summon_vocab.json`

**上游**: chat_bypass / preflight 调

**下游**: ConcernsLedger (间接 — main caller 看 result top up severity)

**跟记忆的耦合**: 间接

**重构含义**: 保留

**审计结论**: 109 行薄 detector.

---

### #49 `jarvis_conductor.py` (1256 行) — **Conductor (指挥官 — 多源融合 + LLM/规则决策)**

**职责**: P0+19-6.b — Jarvis "指挥官" 大脑层. 融合 directive + 关键词 + LLM 决策, 决定每条 utterance 的 reaction 路径.

**核心 class**:

| L | item | 功能 |
|---|---|---|
| 104 | `Conductor` | 主类 (~1150 行) |

**核心 method** (估计):
- `decide_reaction(user_input, context)` — 主入口
- `_apply_directives` / `_apply_keywords` / `_apply_llm`
- `_dispatch` — 派发到 chat_bypass / SmartNudge / etc.

**数据**: 读 directives + STM + concerns + sir_status, 写 SWM

**上游**: `central_nerve.__init__` 实例化, worker 调

**下游**: chat_bypass / SmartNudge / 各 sentinel

**跟记忆的耦合**: ⭐ 读全 Jarvis 状态决策 reaction

**已知问题**:
- ⚠️ 1256 行 — 大
- ⚠️ **跟 IntentResolver 概念重叠** — Conductor 是早期 (P0+19-6.b), IntentResolver 是新 (β.5.44). Phase B 必决议合并

**重构含义**: ⭐⭐ 跟 IntentResolver 关系待清, 可能整合

**审计结论**: 1256 行老指挥官. 跟 IntentResolver 关系是 refactor 重点.

---

### #50 `jarvis_curiosity.py` (148 行) — **Curiosity Ping (β.2.9.4 daemon D)**

**职责**: β.2.9.4 — daemon 5min tick, 看 Sir 静默时间长 + 没新事件 → 偶尔主动问"忙啥呢" 类好奇心 ping.

**核心 class + helpers**:

| L | item | 功能 |
|---|---|---|
| 35 | `CuriosityDaemon` | 主类 |
| 142 | `ensure_curiosity_daemon_started` | 单例启动 |

**数据**: 读 sir_status + STM

**上游**: central_nerve daemon

**下游**: chat_bypass.stream_nudge

**跟记忆的耦合**: 间接

**重构含义**: ⭐ 保留 — 老友感真实需求

**审计结论**: 148 行薄 daemon.

---

## 批次 g: Sensor + Sentinel + Reflector 23 模块

> 详 `JARVIS_SENSOR_TO_SWM_ARCHITECTURE.md`. 三维耦合 sensor → SWM → 主脑.

### #51 `jarvis_sensors.py` (1148 行) — **6 类感知工具 (FunnelLogger / SensorFilter / HabitClock / CausalChain / ProjectTimeline / SubconsciousMailbox)**

**职责**: P0+19-3 拆分 — 感知/分类工具集合. 6 sub-class 各自管: 日志漏斗 / sensor 过滤 / 习惯时钟 / 因果链 / 项目时间线 / 潜意识邮箱.

**核心 class** (6 个, 各 100-300 行):
- `FunnelLogger` — 日志漏斗 (按 verbosity 级别筛选)
- `SensorFilter` — sensor 信号过滤
- `HabitClock` — 习惯时钟 (按时段建模 sleep/work/idle)
- `CausalChain` — 因果链 (事件因果关系推断)
- `ProjectTimeline` — 项目时间线 (sqlite ProjectTimeline 表 ORM)
- `SubconsciousMailbox` — 潜意识邮箱 (异步 LLM 反思的邮箱模式)

**数据**: 各类各自管 (sqlite ProjectTimeline / 内存 mailbox / vocab)

**上游**: `central_nerve.__init__` 实例化多 ProjectTimeline / HabitClock / CausalChain

**跟记忆的耦合**: ⭐ ProjectTimeline 是 Layer C 的子表 (Hippocampus 4 表之一)

**重构含义**: ⭐ 拆 — 6 sub class 各独立 (e.g. `jarvis_funnel_logger.py` / `jarvis_habit_clock.py`)

**审计结论**: 1148 行 6 杂类, 概念混合.

---

### #52 `jarvis_env_probe.py` (960 行) — **PhysicalEnvironmentProbe (键鼠/window/idle 物理感知)**

**职责**: P0+19-2 — 物理环境感知 daemon. `last_real_input_ts` / `idle_seconds_real` / `cascade_active_pid` / `window_history` / 鼠标轨迹 / 键盘节奏.

**核心 class**: 单 `PhysicalEnvironmentProbe`. 含 `_tick_callbacks` 列表, 各 sub module 注册 tick callback.

**数据**:
- 读: win32api / win32gui / pycaw (audio sessions)
- 写: 类级 attr (mouse_distance_5min / window_history / 等)
- SWM publish: `sensor_change` / `sir_afk_detected` / `ghost_activity_observed` / `active_window_hung`

**上游**: `central_nerve.__init__` 注册 callback. tick 全 Jarvis 调.

**下游**: SWM bus + win32 系统 API

**跟记忆的耦合**: ⭐ 是 sensor 层数据源, 不直接写 memory

**关联 design doc**: `JARVIS_SENSOR_TO_SWM_ARCHITECTURE.md` Layer 1

**重构含义**: ⭐ 保留 — 是 sensor 层底座. 跟 SWM 解耦良好.

**审计结论**: 960 行实用 sensor.

---

### #53 `jarvis_sentinels.py` (2167 行) — **9 个普通 sentinel (Chronos / System / SoulArchivist / NudgeGate / UserStatus / Screenshot / Wellness / ReflectionScheduler)**

**职责**: P0+19-6.a — 9 sub-class sentinel daemon. 各自定时跑 + 各自职责.

**核心 class** (9 个):
- `ChronosTick` — 全局时间 tick (1s)
- `ChronosSentinel` — 时间 sentinel
- `SystemSentinel` — 系统状态 sentinel
- `SoulArchivistSentinel` — 灵魂归档 (跟 SoulArchivist 配套)
- `NudgeGate` — nudge 90s 全局 cooldown
- `UserStatusLedgerSentinel` — Sir 状态台账
- `ScreenshotSentinel` — 截屏 sentinel (周期截屏给 ScreenVision)
- `WellnessGuardian` — 健康守护 (久坐/喝水/睡眠 推断 → 写 concerns)
- `ReflectionScheduler` — 反思调度器 (协调多个 reflector LLM call)

**数据**: 各自管. ScreenshotSentinel 写 `screen_history.jsonl`. WellnessGuardian 调 ConcernsLedger.

**上游**: `jarvis_nerve.__main__` 启动多个

**跟记忆的耦合**: ⭐ WellnessGuardian 写 concerns, ScreenshotSentinel 写 screen_history

**已知问题**:
- 2167 行 9 class — 大. 应拆 (e.g. `jarvis_chronos.py` / `jarvis_screenshot_sentinel.py` / `jarvis_wellness.py`)
- 跟 ProactiveCare / SmartNudge 部分功能重叠 (Wellness 也写 concerns, ProactiveCare 也读 concerns)

**重构含义**: ⭐ 必拆 — 9 类各独立

**审计结论**: 2167 行第 3 大杂文件.

---

### #54 `jarvis_screen_vision.py` (701 行) — **ScreenVisionEngine (Vision LLM 结构化感知)**

**职责**: P5-Gap3 — 截屏 → Gemini Vision 多模态 → 结构化 ScreenSnapshot (active_app / file_or_url / cursor_line / errors_visible / etc.).

**核心 class**:
- `ScreenSnapshot` — dataclass
- `ScreenVisionEngine` — 主类

**核心 method**:
- `async_describe(trigger='wake'/'backfill'/'sir_ref', jpeg_bytes)` — fire-and-forget Vision LLM
- `_capture_screen_jpeg` — 截屏 + JPEG (fix81 加鼠标红圈)
- `_call_vision_llm` — Gemini Vision 调

**数据**:
- 读: ImageGrab + Gemini Vision API
- 写: `memory_pool/screen_snapshot.json` (latest 1 帧) + `screen_history.jsonl`
- SWM publish: `screen_described`

**上游**: `worker.run` 唤醒后并发调 / `chat_bypass` Sir 引用屏幕时 / `ScreenshotSentinel` (周期 backfill)

**下游**: Gemini Vision via KeyRouter

**跟记忆的耦合**: ⭐ `screen_history.jsonl` 是 Layer B 子 source (屏幕历史)

**关联 design doc**: `JARVIS_VISION_INTEGRATION.md` (12KB)

**重构含义**: ⭐ 保留 — Vision 是 Sir 关键 sensor

**审计结论**: 701 行实用. fix81 加鼠标红圈 ✅.

---

### #55 `jarvis_ambient_sensor.py` (597 行) — **AmbientSensor (环境音 sensor publish 进 SWM)**

**职责**: β.5.40 — 麦克风环境音 sensor (笑声 / 叹气 / 咳嗽 / 屏息 / 乐曲 / 噪音). 不调 ASR (避免歧义), 仅 publish 信号给主脑.

**核心 class**:
- `AmbientObservation` — dataclass
- `AmbientSensor` — 主 sensor

**数据**:
- 读: mic (PyAudio + 信号处理)
- 写: `ambient_sensor_config.json`
- SWM publish: `ambient_state` (laughter / sigh / cough / etc.)

**上游**: `jarvis_nerve.__main__` daemon

**跟记忆的耦合**: 间接

**重构含义**: 保留 — sensor 层

**审计结论**: 597 行实用 sensor.

---

### #56 `jarvis_acoustic_wake.py` (632 行) — **AcousticWakeDetector (openWakeWord 唤醒装甲)**

**职责**: P0+20-β.4.8 — openWakeWord 唤醒词检测器. 防 ASR 误唤. 跟 VoiceListenThread 配合.

**核心 class**:
- `WakeDetectionResult` — dataclass
- `AcousticWakeDetector` — 主类

**数据**: 读 mic + openWakeWord 模型

**上游**: VoiceListenThread

**跟记忆的耦合**: 无

**重构含义**: 保留 — 物理唤醒底座

**审计结论**: 632 行实用 wake.

---

### #57 `jarvis_state_tracker.py` (236 行) — **JarvisStateTracker (HUD 状态机 + SWM publish)**

**职责**: β.5.43-A — HUD 状态机 (ready / listening / thinking / speaking / focused). 跟 utils.JarvisState 配合.

**核心 class**: 单 `JarvisStateTracker`

**数据**: SWM publish 'jarvis_state' (salience 0.30)

**上游**: 状态变化时 publish

**跟记忆的耦合**: 无

**重构含义**: 保留

**审计结论**: 236 行薄 tracker.

---

### #58 `jarvis_silence_intel.py` (199 行) — **Silence Intelligence (β.5.43-E thinking pause)**

**职责**: 检测 Sir 短暂停顿 (e.g. 中间嗯/啊/哦) — publish 'sir_thinking_pause' SWM, 让主脑下轮 ack 不抢话.

**核心 functions** (无 class)

**数据**: SWM publish

**重构含义**: 保留 — 物理感知

**审计结论**: 199 行薄 helper.

---

### #59 `jarvis_health_probe.py` (241 行) — **HealthProbeDaemon (Jarvis 自检 daemon)**

**职责**: β.2.8.6 — 周期 5min tick 看 Jarvis 自身健康 (memory / threads / handles / KeyRouter status). 写 `jarvis_health_history.jsonl`.

**核心 class**: 单 `HealthProbeDaemon`

**数据**: 读 psutil + KeyRouter / 写 `jarvis_health_history.jsonl`

**跟记忆的耦合**: 无 — 是 Jarvis 自身健康 audit

**重构含义**: 保留

**审计结论**: 241 行实用 self-monitor.

---

### #60 `jarvis_physio_proxy.py` (304 行) — **PhysioProxy (β.5.40-A2 生理代理)**

**职责**: 从键鼠节奏推断 energy / focus / stress 评分 (heuristic, 不调 LLM).

**核心 class**:
- `PhysioState` — dataclass
- `PhysioProxy` — 主推断

**数据**: 读 PhysicalEnvProbe + 写 SWM `physio_state`

**重构含义**: 保留 — sensor 层

**审计结论**: 304 行薄 proxy.

---

### #61 `jarvis_screen_tease_reflector.py` (425 行) — **ScreenTeaseReflector (β.5.35-B L7 vocab propose)**

**职责**: L7 daemon — 看屏幕 history, propose 新 screen_tease_vocab (Sir 观察到的笑点 / 模式).

**核心 class**: 单 `ScreenTeaseReflector`

**数据**: 读 screen_history.jsonl, 写 vocab review queue

**重构含义**: 保留 — L7 模式

**审计结论**: 425 行 daemon.

---

### #62 `jarvis_struggle_reflector.py` (377 行) — **StruggleReflector (β.5.35-D Sir 困难 vocab propose)**

**职责**: L7 daemon — 看 Sir 历史 utterance, propose 新 sir_struggle_vocab patterns.

**核心 class**: 单 `StruggleReflector`

**数据**: 读 STM, 写 `sir_struggle_vocab.json` review

**重构含义**: 保留

**审计结论**: 377 行 L7 daemon.

---

### #63 `jarvis_sleep_pattern_reflector.py` (250 行) — **SleepPatternReflector (β.5.39 Sir 睡眠 vocab propose)**

**职责**: L7 — 看历史睡眠数据, 推 Sir 睡眠 pattern vocab.

**核心 class**: `SleepPatternReflector`

**数据**: 读 sleep history, 写 `sir_sleep_pattern_vocab.json`

**重构含义**: 保留

**审计结论**: 250 行 L7 daemon.

---

### #64 `jarvis_companion_rhythm_reflector.py` (408 行) — **CompanionRhythmReflector (β.5.40-E1 nudge timing 学习)**

**职责**: L7 — 看 nudge feedback (helped/missed), 学习 timing pattern (哪个时段 nudge 最有效).

**核心 class**: `CompanionRhythmReflector`

**数据**: 读 ConcernFeedback audit, 写 `nudge_window_vocab.json`

**重构含义**: 保留

**审计结论**: 408 行 L7 daemon.

---

### #65 `jarvis_inside_joke_reflector.py` (391 行) — **InsideJokeReflector (β.5.40-B1 笑点 propose)**

**职责**: L7 — 看 STM, propose inside_jokes 进 RelationalState review queue.

**核心 class**: `InsideJokeReflector`

**数据**: 读 STM, 写 RelationalState review

**跟记忆的耦合**: ⭐ 写 RelationalState

**重构含义**: 保留

**审计结论**: 391 行 L7 daemon.

---

### #66 `jarvis_sir_request_reflector.py` (381 行) — **SirRequestReflector (β.5.43-fix3 主动 watch concern propose)**

**职责**: L7 — 看 Sir utterance "你帮我盯下 X" 类显式委托, propose 新 watch concern.

**核心 class**: `SirRequestReflector`

**数据**: 读 STM, 写 concerns_review

**跟记忆的耦合**: ⭐ 写 ConcernsLedger.review

**重构含义**: 保留

**审计结论**: 381 行 L7 daemon.

---

### #67 `jarvis_sir_status_tracker.py` (483 行) — **SirStatusTracker (P5-SirStatusTracker Sir 状态)**

**职责**: P5-SirStatusTracker — Sir 当前状态 (sleeping / online / AFK / focus / etc.) 实时追踪. 写 `sir_status.json`.

**核心 class**:
- `SirStatus` (dataclass)
- `SirStatusStore`

**数据**: 读/写 `sir_status.json` + SWM publish

**跟记忆的耦合**: ⭐⭐ Layer E 状态的核心 source

**重构含义**: ⭐ 保留 — Layer E 主 source. Phase B 应跟 stand_down + sir_acked 整合

**审计结论**: 483 行核心状态 tracker.

---

### #68 `jarvis_return_sentinel.py` (1187 行) — **ReturnSentinel (β.4.x 归来哨兵 + AFK + 验证)**

**职责**: P0+19-6.c — Sir 离开后回归哨兵. afk 检测 + 5min 阈值 + 主动归来问候 (跟 SmartNudge 配合 fire return_greeting).

**核心 class**: `ReturnSentinel` (~1100 行)

**数据**: 读 PhysicalEnvProbe + sir_status, 写 SWM `afk_return`

**已知问题**: 1187 行单 class — 大

**重构含义**: ⭐ 拆 — afk 检测 / 归来 nudge / 验证 应分独立

**审计结论**: 1187 行核心 sentinel.

---

### #69 `jarvis_stand_down.py` (693 行) — **StandDown (P5-fix25 暂停模式)**

**职责**: P5-fix25 — Sir 玩游戏/接电话时按 Ctrl+Alt+J 全局 hotkey 切 stand_down (TTS off + nudge off + 字幕 on).

**核心 class**: `StandDownState`

**数据**: 读/写 `stand_down_state.json` + SWM publish

**跟记忆的耦合**: Layer E 子状态

**重构含义**: ⭐ 保留 — Sir 真测有效. Phase B 跟 sir_status 整合.

**审计结论**: 693 行实用 mode.

---

### #70 `jarvis_project_hold_detector.py` (241 行) — **Project Hold Detector (β.5.46-fix18)**

**职责**: 检测 Sir "不要管 X 项目" 意图 → 写 ProjectTimeline `held_until_ts`.

**核心 functions** (无 class)

**数据**: 写 ProjectTimeline.held_until_ts

**跟记忆的耦合**: 写 ProjectTimeline

**重构含义**: 保留

**审计结论**: 241 行薄 detector.

---

### #71 `jarvis_watch_task.py` (938 行) — **WatchTask (β.5.46-fix13 主动等屏幕事件)**

**职责**: Sir 委托等某事件 (e.g. "等导出完成提醒"). ScreenVision daemon judge 屏幕证据 → publish 'watch_task_fired' SWM.

**核心 class**:
- `WatchTask` (dataclass)
- `WatchTaskRegistrar` — 注册
- `WatchTaskJudge` — Vision LLM 判

**数据**: 读/写 `watch_tasks.json`

**跟记忆的耦合**: ⭐ Layer E 子 source (主动等的事件), 跟 Commitments / cyclic_task / promise 概念上 4 套

**重构含义**: ⭐⭐ 跟 4 套时间承诺合并候选

**审计结论**: 938 行核心 watch.

---

### #72 `jarvis_cross_session_callback.py` (245 行) — **CrossSessionCallback (跨 session 心结)**

**职责**: 上 session 没解决的 emotional 心结, 在新 session wake 时 surface (e.g. "上次你说 X, 还在想吗").

**核心 class**:
- `Callback` (dataclass)
- `CrossSessionCallbackStore`

**数据**: 读/写 `cross_session_callback.json` (但实际持久化未启?)

**已知问题**: `pending_callbacks.jsonl` 0 字节 — 似乎未真用

**重构含义**: 待 Phase A.5 历史 audit 确认是否 deprecated

**审计结论**: 245 行可能未真用.

---

### #73 `jarvis_actionable_items.py` (1168 行) — **ActionableItems (β.5.41 统一 Sir 可操作项)**

**职责**: 统一 Sir 可操作 21 类 (concerns dismiss / promise cancel / commitment update / profile field update / etc.). 给 Dashboard / CLI 用.

**核心 class**: `ActionableItem` (~1100 行)

**数据**: 读全 Jarvis 各 source (concerns / promise / commitment / profile)

**跟记忆的耦合**: ⭐ 是各 mutation source 的 read-side aggregator

**已知问题**:
- 1168 行 1 class — 大
- 21 类 hardcoded — 可 vocab 化

**重构含义**: ⭐ 拆 + vocab 化

**审计结论**: 1168 行 actionable 聚合.

---

