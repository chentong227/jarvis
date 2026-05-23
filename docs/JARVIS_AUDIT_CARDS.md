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

