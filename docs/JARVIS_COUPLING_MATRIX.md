# JARVIS 耦合矩阵 (Phase A.4 of Grand Refactor)

> 90 模块间真实调用关系 + 隐藏硬耦合点. 基于 `JARVIS_AUDIT_CARDS.md` (140 模块审计) 抽取.
>
> 写于 2026-05-24 00:00, Phase A.4.

---

## 1. 总览 — 耦合形态分类

| 形态 | 描述 | 数量 | 例 |
|---|---|---|---|
| **A. 持有引用** | `self.X = X(self)` 实例化 + 持有 | ~30 | CentralNerve.profile_card / hippocampus / concerns_ledger / etc. |
| **B. 单例 lazy import** | `get_default_X()` 函数获取 | ~25 | `jarvis_directives.get_default_registry` / `jarvis_concerns.get_default_ledger` |
| **C. SWM publish/read 解耦** | 通过 ConversationEventBus 间接 | ~50 etype | sentinel publish, 主脑 prompt read |
| **D. attr 注入 (后期 wire)** | `nerve.X = Y` (后期外部赋值) | ~10 | `jarvis_worker.jarvis = CentralNerve` / `worker.voice_thread = ...` |
| **E. 共享状态 attr** | 多 module 读写同 nerve.attr | ~20 | `nerve.short_term_memory` / `nerve.event_bus` |
| **F. 硬 import** | 直接 `from X import Y` 调 | ~80% 模块 | utils 是底座, 几乎全部 import |
| **G. 通过 manifest 自动加载** | hands / eyes 通过 SkillScanner 入册 | 25 hands | hand_registry / hand_manifests |

---

## 2. 中心节点的下游辐射 (CentralNerve 持有的 ~30 component)

```
CentralNerve (central_nerve.py:251)
├── 物理感知 (4)
│   ├── self.vocal: VocalCord (vocal_cord)
│   ├── self.blood: JarvisBlood (blood)
│   ├── self.right_brain / left_brain / l5_brain (legacy 3-brain, ⚠️ 待审是否 deprecated)
│   └── self.hippocampus: Hippocampus (hippocampus)
│
├── 状态机 + sensor (8)
│   ├── self.state: JarvisState (utils)
│   ├── self.event_bus: ConversationEventBus (utils) ⭐⭐⭐
│   ├── self.working_feed: WorkingMemoryFeed (utils)
│   ├── self._clipboard_watcher: ClipboardWatcher (utils)
│   ├── self._ps_history_watcher: PSHistoryWatcher (utils)
│   ├── self.habit_clock: HabitClock (sensors)
│   ├── self.causal_chain: CausalChain (sensors)
│   └── self.project_timeline: ProjectTimeline (sensors)
│
├── Soul (4)
│   ├── self.self_anchor: SelfAnchor (β.2.0) ⭐
│   ├── self.concerns_ledger: ConcernsLedger (β.2.1) ⭐
│   ├── self.relational_state: RelationalStateStore (β.2.2) ⭐
│   ├── self.concerns_reflector + weekly_reflector (β.2.5)
│   └── self.soul_evaluator (β.2.6)
│
├── 记忆 (5)
│   ├── self.profile_card: ProfileCard (routing) ⭐
│   ├── self.memory_gateway: UnifiedMemoryGateway (memory_core, ⚠️ 同名重叠)
│   ├── self.plan_ledger: PlanLedger (utils)
│   ├── self.short_term_memory: list (内存, persist 30s tick)
│   └── (sir_mental_model 单例, 不在 nerve attr — 通过 get_default_store 获取)
│
├── 主对话 (3)
│   ├── self.chat_bypass: ChatBypass (后期 wire by Worker)
│   ├── self.context_router: ContextRouter (routing)
│   └── self.content_tracker: ContentPreferenceTracker (routing)
│
├── 指挥 (2)
│   ├── self.conductor: Conductor (后期 wire)
│   └── self.guardian_center / companion_center / prompt_center (3 Center, 历史)
│
├── 承诺 (1)
│   └── self.commitment_watcher: CommitmentWatcher (后期 wire by main)
│
├── 反思 (2)
│   ├── self.reflector: LlmReflector
│   └── self.reflection_scheduler (后期 wire)
│
├── 门 (2)
│   ├── self.nudge_gate: NudgeGate (sentinels)
│   └── self.sleep_detector: SleepIntentDetector (memory_core)
│
├── 状态 (其他)
│   ├── self.eye_registry / hand_registry / eye_manifests / hand_manifests (registry, 热加载)
│   ├── self.prompt_cache: PromptCache (memory_core)
│   ├── self.correction_loop: CorrectionLoop (memory_core)
│   └── self.eyes / hands / env: None (显式 None — 死代码?)
│
└── KeyRouter / TraceContext (全局共享)
```

**总计 ~30+ component**. CentralNerve 是**中心节点 + 全 Jarvis 数据交换枢纽**.

---

## 3. 重要耦合矩阵 (谁调谁的关键关系)

> 行 = caller, 列 = callee. ⭐ = 关键耦合点.

### 3.1 主对话流耦合

| Caller \ Callee | CentralNerve | ChatBypass | Worker | Hippocampus | ProfileCard | MemoryGateway | EventBus(SWM) |
|---|---|---|---|---|---|---|---|
| **`jarvis_nerve` (main)** | ✅ 实例化 | (间接) | ✅ start | (间接) | (间接) | (间接) | (间接) |
| **CentralNerve** | self | (持有) | (无) | self.hippocampus ✅ | self.profile_card ✅ | (无直接 — 用 get_default) | self.event_bus ✅ |
| **ChatBypass.stream_chat** | self.jarvis ⭐ | self | (无) | (间接 LTM retrieve) | (FAST_CALL) | ⭐ FAST_CALL mutation organ | publish 多 |
| **Worker.run** | self.jarvis ⭐ | self.jarvis.chat_bypass.stream_chat ⭐ | self | (间接) | (间接 corr) | ⭐ memory_correction → update_sir_field | publish |
| **MemoryCorrectionGuard** | (间接) | (无) | (在 worker 内) | (无) | ✅ apply_correction (老) | ✅ update_sir_field (新) | 间接 |
| **Gatekeeper LLM** | (间接) | (无) | (在 worker 内) | ✅ add_commitment_row | (无) | (无) | publish 'sir_intent_*_candidate' |

### 3.2 记忆系统耦合 (核心战场)

| Caller | ProfileCard | Hippocampus | ConcernsLedger | RelationalState | CommitmentWatcher | PromiseLog | Milestones |
|---|---|---|---|---|---|---|---|
| **MemoryGateway.update_sir_field** | ⭐⭐⭐ overwrite_field (新) + apply_correction (老) | (间接 add_completed_event fix82-X) | update_concern_field (P5-fix32-G) | update_field (P5-fix32) | cancel_by_keyword (fix82-X cascade) | mark_fulfilled / mark_cancelled | tool_milestone_register |
| **chat_bypass FAST_CALL** | (mutation organ) | memory_hands organ | concerns organ (dismiss/etc.) | (mutation organ) | (mutation organ) | promises organ | mutation organ |
| **worker.MemoryCorrectionGuard** | ⭐ apply_correction + MemoryGateway | (无) | (无) | (无) | (无) | (无) | (无) |
| **Gatekeeper LLM** | (无) | add_commitment_row | (无) | (无) | ⭐ add_commitment | (无) | (无) |
| **SelfPromiseDetector** | (无) | (无) | (无) | (无) | ⭐ add_commitment (hard) | ⭐ register (soft) | (无) |
| **fix82-X cascade_completion** | (无) | ⭐ add_completed_event | (无) | (无) | ⭐ cancel_by_keyword | (无) | (无) |
| **ProactiveCare** | (无) | (无) | ⭐ list_active (top concern) | list_unfinished | (无) | (无) | (无) |
| **ConcernFeedbackJudge** | (无) | (无) | ⭐ record_signal (Sir 反馈) | (无) | (无) | (无) | (无) |
| **ConcernsReflector** | (无) | (无) | ⭐ record_signal (启发式) | (无) | (无) | (无) | (无) |
| **WeeklyReflector** | (无) | (无) | ⭐ propose 新 concern | (无) | (无) | (无) | (无) |
| **InsideJokeReflector** | (无) | (无) | (无) | ⭐ propose inside_joke | (无) | (无) | (无) |
| **SirRequestReflector** | (无) | (无) | ⭐ propose 新 watch concern | (无) | (无) | (无) | (无) |
| **IntegrityWatcher.retry_*** | (无) | ⭐ retry_reminder / retry_memory | (无) | (无) | retry_commitment | retry_promise | (无) |
| **ClaimTracer.verify** | (无) | search_memory (verify memory claim) | (无) | (无) | list_active (verify commit) | list_pending (verify promise) | (无) |
| **ProfileReflector** | ⭐ overwrite_field (Sir activate 后) | (无) | (无) | (无) | (无) | (无) | (无) |

### 3.3 SWM publish/read 解耦 (β.5.0 三维耦合)

> Publish 端 (~30 个) → SWM → Read 端 (~10 个).

**Publishers** (谁 publish):
- **PhysicalEnvProbe** → 'sensor_change' / 'sir_afk_detected' / 'ghost_activity_observed' / 'active_window_hung'
- **JarvisStateTracker** → 'jarvis_state'
- **CommitmentWatcher** → 'sir_intent_deadline_candidate' / 'commitment_overdue' / 'reminder_fired'
- **Gatekeeper (in worker)** → 'sir_intent_commit_candidate' / 'commitment_detected' / 'conversation_event'
- **ConcernFeedbackJudge** → 'sir_intent_progress_candidate'
- **SelfPromiseDetector** → 'sir_intent_promise_candidate'
- **MemoryCorrection (in worker)** → 'sir_intent_correction_candidate'
- **ProfileCard.overwrite_field** → 'sir_profile_overwritten' / 'sir_intent_profile_update_candidate'
- **MemoryGateway** → 'sir_field_updated' / 'completion_cascaded' (fix82-X)
- **IntentResolver** → 'tool_called' / 'intent_resolved'
- **chat_bypass** → 'tool_executed' / 'tool_chain_circuit_broken' / 'soft_focus_active'
- **worker.interrupt_all** → 'manual_standby' / 'reply_interrupted'
- **worker._detect_sleep_intent** → 'sleep_intent_declared'
- **SmartNudge / silent_nudge** → 'proactive_nudge' / 'visual_pulse'
- **ProactiveCare** → 'concern_active' / 'nudge_window_advice' / 'concern_timing_evidence'
- **AmbientSensor** → 'ambient_state'
- **PhysioProxy** → 'physio_state'
- **SilenceIntel** → 'sir_thinking_pause'
- **IntegrityWatcher** → 'hallucination_detected'
- **NudgeGate / OfferGuard** → 'gate_advice'
- **ReturnSentinel** → 'afk_return'
- **ErrorBus** → 'system_error_visible'
- **WatchTaskJudge** → 'watch_task_fired'
- **InconsistencyWatcher** → 'inconsistency_detected'
- **MetaSelfCheck** → 'meta_self_check'
- **CallbackGuard** → 'unsolicited_callback_caught'
- **RelationalState.update_field** → 'relational_field_updated'
- **CrossSessionCallback** → (待审)

**Readers** (谁读):
- **CentralNerve._assemble_prompt** → swm_block (n=12, salience_floor=0.3)
- **ProactiveCare** → top concern + cooldown 决策
- **chat_bypass.stream_chat** → fix82-Z Gatekeeper skip + soft_focus_active 检测
- **SmartNudge** → recent_nudges + nudge_window_advice
- **NudgeGate** → 全 sentinel cooldown 决策
- **IntegrityWatcher** → hallucination_detected → retry
- **IntentResolver** → 7 candidate events 集中 LLM judge
- **ClaimTracer** → tool_called / sir_field_updated 配对 verify
- **CompanionRhythmReflector** → nudge feedback 学习
- **dashboard** → 全 SWM events for monitoring

### 3.4 hands 耦合 (25 个)

| Hand | 谁调? | 数据写入 |
|---|---|---|
| **memory_hands** ⭐ | chat_bypass FAST_CALL organ='memory_hands'/'memory' (alias fix77-Q) | Hippocampus (sqlite) |
| audio_hands / display_hands / media_control_hands | chat_bypass | Windows API |
| input_hands / window_hands / process_hands / screenshot_hands | chat_bypass | Windows API |
| file_operator_hands / text_hands / clipboard_hands / url_launcher_hands | chat_bypass | 文件 / 剪贴板 |
| network_hands / system_info_hands / system_hands | chat_bypass | 网络 / 系统 |
| terminal_hands.forge_organ | chat_bypass | 动态生成新 hand (meta) |
| watcher_hands | watch_task daemon | 屏幕模式 |
| video_upload_hands | chat_bypass | YouTube / Bilibili API |
| web_hands | chat_bypass | 浏览器自动化 |

---

## 4. 隐藏硬耦合 (Phase B 必处理)

### 4.1 同名不同 class — 命名空间冲突

| 类名 | 出处 | 用途差异 |
|---|---|---|
| **`UnifiedMemoryGateway` vs `MemoryMutationGateway`** | memory_core.py:515 vs memory_gateway.py:97 | 老 (β.4.x) vs 新 (P2-Gap7). **Phase B 必合并** |
| **`Claim`** | claim_tracer.py:104 vs integrity_watcher.py:106 | 不同字段 dataclass — 混淆 |
| **`CorrectionEntry`** | memory_core.py:352 vs blood.py | 同名 dataclass |
| **`MemoryFragment`** | memory_core.py:506 vs blood.py | 同名 dataclass |
| **`PromptLayer`** | memory_core.py:300 vs blood.py | 同名 dataclass |
| **`SoulRouter`** | routing.py:51 vs enhanced.py | 重复定义 |

### 4.2 概念重叠 — 多个 module 做同一事

| 概念 | 多处实现 | 应合并到 |
|---|---|---|
| **时间承诺** | PromiseLog + CommitmentWatcher + cyclic_task + watch_task + concerns.notes_for_self **5 套** | Phase B 决议: PromiseLog 单源 vs 双源 |
| **决策路径** | Conductor + IntentResolver + chat_bypass.FAST_CALL **3 套** | Phase B 决议: 1 入口 |
| **mutation 路径** | ProfileCard.apply_correction (老) + ProfileCard.overwrite_field (新) + MemoryGateway.update_sir_field + execute_memory_updates (safety.py 老) **4 套** | MemoryGateway.update_sir_field 单入口 |
| **claim verify** | ClaimTracer + IntegrityWatcher | tracer = sync 抽 + 验, watcher = async retry — 边界要清 |
| **笑点** | RelationalState.inside_jokes + memory_core.HumorMemory **2 套** | RelationalState 单源 |
| **correction audit** | profile_corrections.jsonl + mutation_receipts.jsonl + claim_revisions.json **3 处** | mem_audit.jsonl 单 audit |
| **state** | sir_status.json + stand_down_state.json + sir_acked_state.json + relational_state.violations | 合并 1 个 sir_state.json (待 Phase B 设计) |
| **add_reminder** | l4_memory_hands + tool_commitment_register + Gatekeeper.add_commitment **3 路径** | 通过 MemoryHub.write 单入口 |

### 4.3 隐藏依赖 — 不显式但实际依赖

| 依赖 | 表现 |
|---|---|
| **CentralNerve._assemble_prompt 读 30+ component** | 任一 component 启动失败 (silent except) → block 缺 → 主脑看不全 |
| **chat_bypass.self.jarvis ref → CentralNerve** | chat_bypass 几乎所有 method 都通过 `self.jarvis.X` 访问全 component (隐式 god object) |
| **Worker.jarvis_worker.jarvis → CentralNerve** | 同上 — Worker 也通过 jarvis ref god access |
| **AttentionSlot 共享实例** | voice_worker._attention_slot / jarvis_worker._attention_slot / jarvis._attention_slot **3 处共享** (main 段 wire) |
| **STM list 共享** | central_nerve.short_term_memory + chat_bypass.short_term_memory + 各 reflector 读 → 多写者风险 |
| **PhysicalEnvProbe 类级 attr 共享** | 多 module 读 `PhysicalEnvironmentProbe.window_history` (类级共享 list) |
| **HumorMemory 单例** | central_nerve 创建 + companion_center.start_all 用同一对象 (jarvis_nerve.__main__ 显式 wire) |

### 4.4 启动顺序硬耦合

`jarvis_nerve.__main__` 启动顺序 (线性):
1. TraceContext.init_session
2. KeyRouter
3. probe_google_keys (2s 后异步)
4. QApplication
5. BreathingLightUI
6. JarvisWorkerThread (实例化 → 内部实例化 CentralNerve → 30+ component init)
7. SubtitleOverlay + chat_bypass.subtitle_queue
8. ScreenshotSentinel
9. UserStatusLedgerSentinel
10. wire jarvis.conductor / reflection_scheduler / commitment_watcher / 等
11. HumorMemory 共享单例
12. VoiceListenThread + 信号 wire (text_ready / interrupt / awake)
13. AttentionSlot 共享
14. voice_worker._subtitle_queue
15. voice_worker.start
16. app.exec_()

**问题**: 顺序错 = 启动失败. 但 step 10-13 是手动 attr 注入, 应集中 `CentralNerve.wire_dependencies()`.

---

## 5. 模块依赖反向图 (谁依赖 X)

> 找最被依赖的中心节点.

| 模块 | 被依赖次数 (估) | 角色 |
|---|---|---|
| **`jarvis_utils`** | ~85+ (几乎全 Jarvis import) | 底座 — SWM + TraceContext + safe_gemini_call + bg_log + ... |
| **`jarvis_central_nerve.CentralNerve`** | ~50 (持有所有 component) | 中心 — 通过 self.X access |
| **`jarvis_blood`** | ~30 (Action / ExecutionResult dataclass) | 协议 |
| **`jarvis_key_router`** | ~30 (LLM 调用全用) | 装甲 |
| **`jarvis_directives`** | ~10 (DirectiveContext / Registry) | 教学 |
| **`jarvis_memory_gateway`** | ~10 (mutation 入口) | 记忆中介 |
| **`jarvis_concerns`** | ~10 (Reflector / Feedback / dashboard) | Soul L1 |
| **`jarvis_hippocampus`** | ~10 (LTM + Commitments + Vision) | 记忆 |

**核心节点 = utils + central_nerve + blood + key_router** (4 大底座).

---

## 6. 依赖图 (mermaid 概念图)

```mermaid
graph TB
    NERVE[jarvis_nerve __main__] --> WORKER[Worker]
    WORKER --> CN[CentralNerve]
    WORKER --> CHAT[chat_bypass]
    CN --> CHAT
    CHAT --> CN
    
    CN --> PROFILE[ProfileCard]
    CN --> HIPPO[Hippocampus]
    CN --> CONCERNS[ConcernsLedger]
    CN --> REL[RelationalState]
    CN --> EVENTBUS[ConversationEventBus SWM]
    CN --> ANCHOR[SelfAnchor]
    CN --> WORKING[WorkingMemoryFeed]
    CN --> PLAN[PlanLedger]
    
    CHAT -->|FAST_CALL mutation| GATEWAY[MemoryGateway]
    GATEWAY --> PROFILE
    GATEWAY --> HIPPO
    GATEWAY --> CONCERNS
    GATEWAY --> REL
    GATEWAY -->|cascade| CW[CommitmentWatcher]
    GATEWAY -->|cascade| HIPPO
    
    CHAT -->|FAST_CALL hand| HANDS[24 l4 hands]
    HANDS -->|memory_hands| HIPPO
    
    WORKER -->|Gatekeeper LLM| CW
    WORKER -->|MemoryCorrection| GATEWAY
    
    SENTINELS[Sensor + 23 Reflector] -->|publish| EVENTBUS
    EVENTBUS -->|to_swm_block| CN
    EVENTBUS -->|recent_events| CHAT
    EVENTBUS -->|recent_events| INTEGRITY[IntegrityWatcher]
    
    INTEGRITY -->|retry| HIPPO
    INTEGRITY -->|retry| CW
    INTEGRITY -->|retry| PROMISE[PromiseLog]
    
    CN -->|render| ASSEMBLE[_assemble_prompt 30+ block]
    ASSEMBLE -->|read| PROFILE
    ASSEMBLE -->|read| CONCERNS
    ASSEMBLE -->|read| REL
    ASSEMBLE -->|read| HIPPO
    ASSEMBLE -->|read| EVENTBUS
    ASSEMBLE -->|read| WATCH[WatchTask]
    ASSEMBLE -->|read| MILESTONES[Milestones]
    ASSEMBLE -->|read| TOM[SirMentalState]
    ASSEMBLE -->|read| STATUS[SirStatusTracker]
    ASSEMBLE -->|read| DIRECTIVES[DirectiveRegistry]
    ASSEMBLE -->|read| 25+ 其他 source
```

---

## 7. Phase B 设计输入 — 关键耦合洞察

### 7.1 god object 反模式

- **CentralNerve**: ~30+ attr, 是事实上的 god object. 几乎所有 caller 通过 `self.jarvis.X` access.
- **chat_bypass**: 5960 行单 file, 通过 `self.jarvis` 间接 god access.
- **worker**: 5823 行单 file, 同上.

**Phase B 应**: 拆 god object — CentralNerve 退化为 `MemoryHub + IntentRouter + PromptBuilder + StateTracker + EventBus + 4 sentinel orchestrator` 的薄协调器.

### 7.2 同名 class 命名空间污染

- 6+ 处同名不同 class (UnifiedMemoryGateway vs MemoryMutationGateway / Claim / CorrectionEntry / ...)
- Phase B 必清理 — 改名 + 同名 dataclass 集中 `jarvis_blood.py` 共享.

### 7.3 SWM 是真正的解耦层 (β.5.0 三维耦合)

- 30+ publishers + ~10 readers, 通过 SWM 间接耦合
- **是 Jarvis 最优秀的解耦设计** — Phase B 应**强化** (不弱化)
- 但 SWM 跨 session 不持久化 — Phase D 加可选 jsonl

### 7.4 启动 wiring 散乱

- `jarvis_nerve.__main__` 16 步线性 wiring + step 10-13 手动 attr 注入
- 应集中 `CentralNerve.wire_dependencies(worker, voice_thread, ui)` 一处管.

### 7.5 hands 耦合简单

- 24 hands schema 一致 (Action → ExecutionResult) — Phase D 易扩展
- memory_hands 是唯一跟记忆耦合, 其他物理执行
- 应补 docstring + manifest doc

---

## 8. 总结 — Phase A 完成

Phase A 全部完成 (A.1 模块审计 140/140 + A.2 dataflow + A.3 storage + A.4 coupling):

**4 大产出**:
1. `JARVIS_AUDIT_CARDS.md` (~3000 行) — 140 模块详细 card
2. `JARVIS_DATAFLOW_MAP.md` (~600 行) — 数据流 + render block + SWM + Reflector
3. `JARVIS_STORAGE_MAP.md` (~500 行) — 93 file storage map
4. `JARVIS_COUPLING_MATRIX.md` (本 doc, ~400 行) — 耦合矩阵 + 隐藏耦合

**核心发现**:
- 6+ 同名 class 命名空间冲突
- 5 套时间承诺系统重叠
- 3 套决策路径 + 4 套 mutation 路径
- 5 audit log 应合并
- 4 死文件
- god object 反模式 (CentralNerve / chat_bypass / worker)
- SWM 是优秀解耦, 但跨 session 不持久化
- MemoryMutationGateway 已是 MemoryHub 80% 实现 — 演化非重写

**A.5 历史 audit (待做)**: 需查 deprecated:
- `jarvis_enhanced.py` (758 行 4 class)
- 3-brain (RightBrain / LeftBrain / ReflectionBrain)
- TaskWorkerPool ("C1-3 死代码清扫")
- pending_callbacks.jsonl (0 KB)
- plans.json (0 KB)
- safety.py:execute_memory_updates (老 MEMORY_UPDATE)
- 35 design doc 中已 deprecated 的设计

完成 Phase A.5 后即可进 Phase B 设计.

---

*Phase A.4 coupling matrix 完成于 2026-05-24 00:05.*
