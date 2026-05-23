# JARVIS Grand Architecture Reshape — 完整架构重塑设计书

> **本 doc 是 JARVIS 大重构的最终设计书**, 取代 `JARVIS_MEMORY_AND_MUTATION_REFACTOR_v1_archive.md`.
>
> 范围: 不只是记忆系统, 是 JARVIS **整个架构** 的重塑.
>
> 写于 2026-05-24 00:30, Sir 拍板进 Phase D 前的最终设计.
>
> **基础**: Phase A 6000 行 audit (7 doc) + Phase B 700 行架构 (1 doc) + 4 项决议.
>
> **目标**: Sir 醒来打开本 doc, 能直接进 Phase D 动工, 不需要再决策.

---

## 0. 阅读路径

| 你是谁 | 怎么读 |
|---|---|
| **Sir 醒来** | §1 决议 → §2 架构骨架 → §11 动工 checklist → 直接动工 M1 |
| **新 agent** | 全 doc 顺序读, 配合 `AGENTS.md` + Phase A 7 doc |
| **Phase D 实施 agent** | §6-§10 是逐 milestone 的实施手册, 一次只做一个 |

---

## 1. 4 项决议 (Sir 委托 Cascade 拍板, 2026-05-24)

> Sir 原话: "是否拆分你来决定, 你对贾维斯的架构和工程纪律以及工程可维护性比我更了解."

### Q1. `jarvis_enhanced.py` (758 行 4 class) 拆分? — **拆 4 file**

**事实**:
- `ProactiveShield` (line 52-346, 295 行) — sentinel
- `ProactiveCompanion` (line 347-468, 122 行) — sentinel
- `SkillTreeTracker` (line 469-736, 268 行) — tracker
- `SoulRouter` (line 737+) — router

**决议**: 拆 4 个独立 file (准则 8 单一职责), `jarvis_enhanced.py` 改为 facade re-export 兼容 30+ 处 `from jarvis_enhanced import` 老 import.

**目标 file**:
- `jarvis_proactive_shield.py`
- `jarvis_proactive_companion.py`
- `jarvis_skill_tree_tracker.py`
- `jarvis_soul_router.py`
- `jarvis_enhanced.py` 改为 ~10 行 facade

**理由**: 4 class 性质不同 (2 sentinel + 1 tracker + 1 router), 单 file 758 行违反 Phase D-M6 god object 拆分原则; 拆后单一职责; facade 保持 backward compat 不破老 import.

---

### Q2. 3-brain (RightBrain / LeftBrain / ReflectionBrain) — **彻底放弃, 移到 `_legacy/3_brain_attempt/`**

**事实** (Phase A 误判, 这次 reshape audit 修正):
- `central_nerve.run(voice_input, max_loops=8, memory_protocol)` 是个**长任务执行循环** (line 4289-5087, ~800 行)
- 调用方: `worker._process_user_input → trigger_routing` (worker.py:5083)
- 工作流: `RightBrain.set_strategic_plan` (战略规划) → `LeftBrain.generate_actions` (战术执行) → `L5Brain.analyze_deadlock` (死锁分析) → `L5Brain.audit_high_risk_action` (高危审核)
- 现实: 主对话 99%+ 走 `chat_bypass.stream_chat`, `jarvis.run()` 长任务流极少触发

**Sir 拍板**: "3-brain 彻底先放弃, 后面等贾维斯地基牢固再装配手脚的时候需要这种长的工作流程再重构."

**决议**: 移到 `_legacy/3_brain_attempt/` 子目录保留作历史参考, 当前不实例化、不调用、不走该路径:
- `l1_right_brain.py` → `_legacy/3_brain_attempt/l1_right_brain.py`
- `l3_left_brain.py` → `_legacy/3_brain_attempt/l3_left_brain.py`
- `l5_reflection_brain.py` → `_legacy/3_brain_attempt/l5_reflection_brain.py`
- `central_nerve.__init__:312-314` 实例化删
- `central_nerve.run()` (~800 行) 移到 `_legacy/3_brain_attempt/central_nerve_run_v1.py`
- `worker.trigger_routing` 删除, 所有命令统一走 `chat_bypass.stream_chat`
- 30+ 处 `from l1_right_brain import RightBrain  # noqa: F401` 兼容 import 全删

**理由**:
- Sir 拍板优先 (准则 7)
- 长任务流没成熟, 现 chat_bypass 单脑路径已能 cover 99%+
- 删除可减少 central_nerve.py ~800 行 god object 体积 (Phase D-M6 双赢)
- 保留 file 不删, 5 年后地基稳了想做 multi-step plan 时可恢复

**风险**: 现有可能极少数 task 路由到 `jarvis.run()`. 真测验证: 删后跑 24h, 看是否有用户 case 落空.

---

### Q3. `central_nerve.memory_gateway` 改用 `MemoryHub` — **改, M2 落实**

**事实**: 现 `central_nerve.memory_gateway = UnifiedMemoryGateway(self)` (老 memory_core 路径), 但实际 mutation 走 `MemoryMutationGateway` (新 P2-Gap7).

**决议**: M2 改 `central_nerve.memory_gateway = MemoryHub.get_default()` (`MemoryMutationGateway` 改名 `MemoryHub`), 老 `UnifiedMemoryGateway` 删.

**理由**: 4 套 mutation 路径合并为单 `MemoryHub.write_*()` 入口 (准则 8); 老路径下线避免双源混乱.

---

### Q4. `cross_session_callback` + `pending_callbacks.jsonl` — **保留, 不动**

**事实** (Phase A 误判, 这次 audit 修正):
- `pending_callbacks.jsonl` 0 KB **不是死**
- 真用途: dashboard 进程 → 主进程 watcher 的**跨进程通道**
- dashboard activate callback → 写 jsonl
- `CommitmentWatcher._consume_pending_callbacks` 启动时 + 每 5min 消费 → `add_commitment` + truncate 清空
- 0 KB = 消费完正常状态, **不是死**

**决议**: 保留 module + json + jsonl 跨进程消费 pattern, 不改.

**理由**: 是合法的跨进程 IPC, 删了反而破 dashboard 联动.

---

## 2. 架构骨架 — 4 护城河 + 3 薄弱点 + 4 铁律 + 8 准则

### 2.1 4 护城河 (5-10 年内不动)

| # | 护城河 | 用途 | 现状 → Reshape 后 |
|---|---|---|---|
| **M1** | **SWM 唯一中介** | 数据强耦合, 解耦 publisher/reader | β.5.0 立 → 加 `evidence_chain` DAG 字段 + 持久化 critical event |
| **M2** | **标准 Action 协议** | `Action(organ, command, parameters, trace_id) → ExecutionResult` | 已立 → 加 `evidence` 字段强制 |
| **M3** | **Lineage Trace** | 反向追溯 reply → 数据底层 | ⭐ 新立 (M1 milestone 落地) |
| **M4** | **vocab 持久化 (准则 6.5)** | 数据驱动行为 + L7 LLM-propose | 38+ vocab 已立 → 剩余 hardcoded 全迁 |

### 2.2 3 薄弱点 (5 年内必有重构, 留扩展点)

| # | 薄弱 | 冲击 (年) | 扩展点 |
|---|---|---|---|
| **W1** | Prompt 是 text | 1-3 年 (多模态原生 LLM) | `PromptBlock(kind=text/image/audio/video, content)` |
| **W2** | 单 LLM 决策中心 | 3-5 年 (多 agent) | `BrainDecision.delegated_to: agent_id` |
| **W3** | 单机 / 单用户 | 3-5 年 (多 device) | Storage interface + Subject 抽象 |

### 2.3 4 铁律 (加新能力的硬约束)

| # | 铁律 | 违反后果 |
|---|---|---|
| **R1** | 新 sensor/effector 只 publish SWM, 不 mutate state, 不 call 其他 module | 破 M1, 5 年内必再重构 |
| **R2** | 新决策必须经 LLM, 不准 python if/else 决策 | 破 LLM 决策集中, 退化回 sentinel |
| **R3** | 新行为模式必须 vocab + CLI + L7 propose, 不准 .py hardcoded | 破 M4, 退化回话术锁 |
| **R4** | 新数据落地必须经 `MemoryHub.write_*()` 单入口, 不准直接写 file/sqlite | 破 M3 lineage, 审计断链 |

### 2.4 8 准则核对 (每条 Phase D milestone 全过)

| # | 准则 | Reshape 落实 |
|---|---|---|
| **1** | 高效 (TTFT<5s) | PromptBuilder 减肥, lineage 异步, single LLM call per turn |
| **2** | 反应迅速 | SWM 全异步, 重模块 daemon |
| **3** | 符合人设 | 删话术锁残留 (M3-子项), evidence-only directive |
| **4** | 懂我 | 6 source 统一 MemoryHub, recent_completed 防重复 |
| **5** | 言出必行 | **Lineage = 法理基础** (M1 ⭐⭐⭐) |
| **6** | 三维耦合 | M1+M2+M4 都是体现 |
| **7** | Sir 元否决 | 本 doc Sir 醒来仍可拍板调整 |
| **8** | 优雅 > 简单 | M4 5 套合 1 / M5 3 决策合 1 / M6 god 拆, 不留 hot-fix |

---

## 3. 完整架构 — 6 层 + 数据流

### 3.1 6 层架构图

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 6: Output                                                   │
│   VocalCord (TTS) / SubtitleOverlay (PyQt5) / BreathingLightUI   │
└──────────────────────────▲───────────────────────────────────────┘
                           │ reply tokens + metadata + evidence_id
┌──────────────────────────┴───────────────────────────────────────┐
│ Layer 5: Decision — LLM 主脑 (单一决策中心) ⭐⭐⭐                  │
│   PromptBuilder → Gemini stream → BrainDecision                  │
│   reaction_space: silence / voice / silent_text / visual / tool  │
│   FAST_CALL emit Action(organ, command, params, trace_id)        │
│                                                                   │
│   ☆ 输出经 LineageTracer 反向 mapping 到 prompt evidence         │
└──────────────────────────▲───────────────────────────────────────┘
                           │ read SWM evidence + 6 source data
┌──────────────────────────┴───────────────────────────────────────┐
│ Layer 4: SWM (Shared World Model) ⭐⭐⭐ M1 护城河                  │
│   ConversationEventBus + EvidenceChain DAG (新)                  │
│   in-memory deque(60) + critical (≥0.85) jsonl 持久化 (新)        │
└──────────▲────────────────────────────────────▲──────────────────┘
           │ publish events                     │ read evidence
┌──────────┴───────────────┐         ┌──────────┴───────────────┐
│ Layer 3: Sensor          │         │ Layer 3': Effector        │
│   (publish-only)         │         │   (read-only via Hub)     │
│                          │         │                           │
│   Physical:              │         │   24 hands (l4_*.py)      │
│     PhysicalEnvProbe     │         │     audio / display /     │
│     AmbientSensor        │         │     window / file_op /    │
│     ScreenVision         │         │     network / system /    │
│                          │         │     memory_hands / ...    │
│   Conversational:        │         │                           │
│     SilenceIntel         │         │   通过 Action protocol M2 │
│     ReturnSentinel       │         │   每个 Action 带 trace_id │
│     Gatekeeper (LLM)     │         │   ExecutionResult.evidence│
│     ConcernFeedbackJudge │         │                           │
│     SelfPromiseDetect    │         └──────────▲────────────────┘
│     MemoryCorrection     │                    │ FAST_CALL emit
│     IntegrityWatcher     │                    │
│     ...                  │         ┌──────────┴────────────────┐
└──────────────────────────┘         │ Layer 2: IntentResolver   │
                                     │   (LLM judge 集中)        │
                                     │   收 7 candidate event    │
                                     │   publish-only verdict    │
                                     └──────────▲────────────────┘
                                                │
┌───────────────────────────────────────────────┴─────────────────┐
│ Layer 1: MemoryHub (P2-Gap7 演化, 单 mutation 入口) ⭐            │
│                                                                  │
│   Hub.write_identity   — sir_profile.json + milestones          │
│   Hub.write_event       — Hippocampus sqlite                     │
│   Hub.write_commitment  — PromiseLog (合并 5 套)                 │
│   Hub.write_concern     — concerns.json                          │
│   Hub.write_state       — sir_state.json (合并 status/standdown) │
│   Hub.write_relation    — relational_state.json                  │
│                                                                  │
│   每 write 自动:                                                 │
│     - 写对应 source                                              │
│     - 生成 evidence_id (M3 lineage)                             │
│     - 写 mem_audit.jsonl (合并 5 audit log)                     │
│     - publish SWM '*_field_updated' (含 evidence_chain)         │
│     - 触发 cascade (e.g. fix82-X completion → cancel commit)    │
│                                                                  │
│ Layer 0: Source of Truth (6 类, 严格)                            │
│   A. Identity   → sir_profile.json + sir_milestones.json         │
│   B. Events     → jarvis_memory.db (TaskMemories + ProjTimeline) │
│   C. Commitments → jarvis_promise_log.json (单源, 合 5 套)        │
│   D. Concerns   → concerns.json                                  │
│   E. State      → sir_state.json (合 sir_status+standdown+acked) │
│   F. Relations  → relational_state.json                          │
└──────────────────────────────────────────────────────────────────┘

         ┌─── LineageTracer (M3 护城河) ────────────────┐
         │  跨全 layer 收集 EvidenceID DAG              │
         │  反向追溯: reply token → prompt block →      │
         │            evidence_id → source row          │
         │  CLI: scripts/lineage_dump.py --reply-id=X   │
         └──────────────────────────────────────────────┘
```

### 3.2 数据流单向铁律

```
Sensor publish event (R1) →
  SWM (M1, in-memory + persist critical) →
    PromptBuilder assembles blocks (with evidence_ids) →
      LLM 主脑 read SWM + 6 source via Hub →
        BrainDecision (含 reaction_space + FAST_CALL emit) →
          IntentResolver / chat_bypass dispatch (R2) →
            MemoryHub.write_*() (R4 单入口) →
              Source of Truth (6 类) +
              mem_audit.jsonl +
              SWM publish 'field_updated' (闭环)
```

**禁止跨层短路**:
- ❌ Sensor 直接写 source (违反 R1+R4)
- ❌ Python 决策 (违反 R2)
- ❌ 写死 vocab in .py (违反 R3)
- ❌ 直接写 file/sqlite 绕过 Hub (违反 R4)

---

## 4. 6 类 Source of Truth — 详细 schema

### 4.1 A. Identity (身份/画像)

**File**: `jarvis_config/sir_profile.json` + `memory_pool/sir_milestones.json`

**Schema**:
```python
SirProfile = {
    'biographic': {
        'name': str, 'age': int, 'location': str, 'occupation': str, ...
    },
    'preferences': {
        'communication_style': str, 'work_rhythm': str,
        'unit_preferences': {'distance_unit': 'mi', 'temperature_unit': 'F', ...},
        'health_targets': {...},
    },
    'work_rhythms': [...],
    'active_projects': [{'name': str, 'status': str, 'last_active': iso, ...}],
    'lifetime': {'created_at': iso, 'first_wake': iso, ...},
    # Sir 独立 milestones 在 sir_milestones.json
}
```

**Hub API**:
```python
Hub.write_identity(
    field_path: str,        # e.g. 'preferences.unit_preferences.distance_unit'
    new_value: Any,
    source: str,            # 'worker.memory_correction' / 'profile_reflector' / etc.
    confidence: float,      # ≥0.85 真改, 0.5-0.85 audit only, <0.5 reject
    reason: str,
) -> MutationReceipt
```

**写者** (经 Hub):
- `worker.MemoryCorrectionGuard` (Sir 教正)
- `IntentResolver.tool_memory_correction_apply`
- `ProfileReflector.activate_review` (5min tick, Sir CLI 拍板后)

**读者**: `_assemble_prompt` block #9; `SelfAnchor`; `WeeklyReflector`

---

### 4.2 B. Events (事件/记忆)

**File**: `memory_pool/jarvis_memory.db` — sqlite, 4 表:
- `TaskMemories` (~1778 行, 核心)
- `ProjectTimeline` (~21 行)
- `Commitments` (~26 行) — Reshape 后退化为 PromiseLog 视图 (M4)
- `CorrectionMemory` — Reshape 后删 (老路径, 已被 mutation_receipts 替代)

**TaskMemories Schema**:
```sql
CREATE TABLE TaskMemories (
    id INTEGER PRIMARY KEY,
    timestamp REAL,
    environment TEXT,
    user_intent TEXT,         -- e.g. 'Completed: 血压咨询今天完成'
    macro_goal TEXT,
    execution_summary TEXT,
    raw_actions TEXT,         -- JSON
    semantic_embedding BLOB,  -- Gemini embed (768 dim)
    is_deleted INTEGER,
    memory_type TEXT,
    entities_json TEXT,       -- JSON
    is_future_task INTEGER,   -- M4 后退化, future task 全走 PromiseLog
    trigger_time TEXT
);
```

**Hub API**:
```python
Hub.write_event(
    summary: str,             # 事件描述
    kind: str,                # 'completed' / 'discussion' / 'work_session' / ...
    entities: List[str] = [],
    user_intent: str = '',
    embedding: bytes = None,  # 可选预算 embedding
    source: str = '',
) -> MutationReceipt
```

**特殊**:
- `Hub.write_event(kind='completed', ...)` 自动 → `INSERT TaskMemories user_intent='Completed: ...'` (fix82-X 已实现)
- 自动触发 cascade `Hub.cancel_commitment(keywords=...)` 联动

**读者**: `Hippocampus.search_memory` (LTM retrieve), `list_recent_completed_events`, etc.

---

### 4.3 C. Commitments (承诺) ⭐⭐ 大合并

**File**: `memory_pool/jarvis_promise_log.json` (单源)

**Schema**:
```python
Promise = {
    'id': str,                # 'prom_<timestamp>_<4hex>'
    'kind': Literal['commitment', 'cyclic', 'watch', 'self_promise'],
    'who_promised': Literal['sir', 'jarvis'],
    'description': str,
    'deadline': iso | None,   # commitment/self_promise 有, cyclic/watch 用 trigger_pattern
    'trigger_pattern': str | None,  # cyclic: 'every_morning' / watch: 'window=Bilibili'
    'state': Literal['active', 'fulfilled', 'cancelled', 'overdue'],
    'evidence': List[str],    # evidence_ids 链接
    'bound_to_concern_id': str | None,  # 旧 concerns.notes_for_self 整合
    'created_at': iso,
    'fulfilled_at': iso | None,
    'cascade_completed_by': str | None,  # 哪个 mutation 联动 cancelled
}
```

**5 套合并**:
| 老 | 新 |
|---|---|
| `PromiseLog.register/mark_fulfilled` (Jarvis 自承诺) | `kind='self_promise'` + `who_promised='jarvis'` |
| `CommitmentWatcher.add_commitment` (Sir 时间承诺) | `kind='commitment'` + `who_promised='sir'` |
| `cyclic_task` (循环任务) | `kind='cyclic'` + `trigger_pattern='every_morning'` |
| `watch_task` (主动等的事件) | `kind='watch'` + `trigger_pattern='window=...'` |
| `concerns.notes_for_self` (concern 内提醒) | `bound_to_concern_id` 字段 |

**Hub API**:
```python
Hub.write_commitment(
    description: str,
    kind: str,                # commitment/cyclic/watch/self_promise
    who_promised: str,        # sir/jarvis
    deadline: str = None,
    trigger_pattern: str = None,
    bound_to_concern_id: str = None,
    source: str = '',
) -> MutationReceipt
```

**读者**:
- `CommitmentWatcher` daemon (退化为 read-only 触发器, 检 deadline + emit `reminder_fired`)
- `ClaimTracer` (verify Jarvis claim)
- `_assemble_prompt` (active_reminders block)

---

### 4.4 D. Concerns (关心/牵挂)

**File**: `memory_pool/concerns.json`

**Schema** (现有, 已稳):
```python
Concern = {
    'id': str,
    'what_i_watch': str,
    'severity': float,                # 0.0-1.0
    'state': Literal['active', 'archived', 'dismissed'],
    'recent_signals': List[Signal],
    'aligned_count': int,
    'last_active_at': iso,
    'triggers_proactive': bool,
    'concern_kind': str,
}
```

**Hub API**:
```python
Hub.write_concern(
    concern_id: str,
    field: str,               # 'severity' / 'state' / 'recent_signals' / ...
    new_value: Any,
    source: str = '',
) -> MutationReceipt
```

---

### 4.5 E. State (当前状态) ⭐ 合并

**File** (合并 3 → 1): `memory_pool/sir_state.json`

合并源:
- `sir_status.json` (sleep/online/AFK/focus/mood)
- `stand_down_state.json` (Stand Down 模式)
- `sir_acked_state.json` (Sir ack 状态)

**Schema**:
```python
SirState = {
    'physical': {'sleeping': bool, 'AFK': bool, 'idle_seconds': int, ...},
    'attention': {'focus_window': str, 'category': str, ...},
    'mood': {'last_known': str, 'updated_at': iso, ...},
    'stand_down': {'mode': bool, 'reason': str, 'until': iso, ...},
    'acked': {'last_ack_turn': str, 'last_ack_at': iso, ...},
}
```

---

### 4.6 F. Relations (关系)

**File**: `memory_pool/relational_state.json` (现有, 已稳)

**Schema**:
```python
RelationalState = {
    'inside_jokes': List[Joke],
    'unspoken_protocols': List[Protocol],  # Sir 不喜欢被反复 confirm 等
    'unfinished_business': List[Thread],
    'shared_history_threads': List[Thread],
}
```

**特殊**: `HumorMemory` (memory_core) 旧分散数据 M3 迁入 `inside_jokes`.

---

## 5. Lineage Trace 基础设施 (M3 护城河) ⭐

详见 §6 (M1 milestone 实施手册).

---
