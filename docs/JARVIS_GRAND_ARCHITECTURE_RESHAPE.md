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

详细 schema + 实施 见 §6.M1 milestone.

---

## 6. Phase D 实施手册 — 8 个 milestone 详细设计

> 每 milestone 独立, 1 milestone 1-4 周. 顺序执行, 不并行.
>
> **每 milestone 必有**: scope / pre-condition / 实施步骤 / 测试 plan / 回滚 plan / 风险 / 验收准则.

### 6.1 总路线 + 优先级

| M# | 任务 | 周期 | 风险 | 依赖 | 优先 |
|---|---|---|---|---|---|
| **M1** | Lineage Trace 基础设施 — ✅ **主体 5/7 done 2026-05-24 07:20** | 1-2 周 | 低 | 无 | ⭐⭐⭐ 先做, 后面 milestone 都依赖它做反向追溯 debug |
| **M2** | MemoryHub 演化 + central_nerve.memory_gateway 改用 | 1 周 | 中 | M1 | ⭐⭐ |
| **M3** | 死代码 + 同名 class + 3-brain 移到 _legacy | 1 周 | 低 | M2 | ⭐⭐ |
| **M4** | 5 套时间承诺合并 → PromiseLog 单源 | 2 周 | 高 (data migration) | M2 | ⭐ |
| **M5** | 3 决策路径整合 (Conductor + IntentResolver + FAST_CALL) | 1 周 | 中 | M4 | ⭐ |
| **M6** | NERVE_SPLIT god object 拆分 | 4 周 (1 周 1 file) | 高 | M3 | 中 |
| **M7** | PromptBuilder polymorphic + 30 block 全迁 | 2 周 | 中 | M2 + M6 | 中 |
| **M8** | 5 audit log 合并 + state 合并 sir_state.json | 3 天 | 低 | M2 | 低 |

**总周期**: 12-13 周 (~3 个月). 不连续做, 中间穿插 Sir 真测 + bug fix + 新 feature.

---

### 6.2 M1 — Lineage Trace 基础设施 ⭐⭐⭐ (先做)

#### Scope
建立反向追溯基础设施: 任何 reply / decision / mutation 都能回链到 evidence 底层.

#### Pre-condition
- ✅ Phase A+B 完成 (本 doc 已经)
- ✅ Sir 拍板 4 项决议
- 无代码 dependency

#### 实施步骤

**Step 1.1**: 新建 `jarvis_lineage.py` (~300 行)
```python
# 核心 class
class EvidenceID:
    """evt_<ts>_<4hex> 字符串生成器"""
    @staticmethod
    def new() -> str: ...

@dataclass
class Evidence:
    evidence_id: str
    timestamp: float
    source_module: str        # 'PhysicalEnvProbe' / 'ProfileCard' / etc.
    source_method: str        # 'tick' / 'overwrite_field' / etc.
    source_data_id: str       # db_row_id / json_path / file_offset / 'none'
    parent_evidence_ids: List[str]  # DAG 上游
    raw_snapshot: Dict[str, Any]    # 关键 raw 字段 (max 1KB)

class LineageTracer:
    """跨全 layer 收集 evidence, 写 lineage.jsonl daemon"""
    def record_evidence(self, evidence: Evidence) -> str: ...
    def record_decision(
        self, decision_id: str, turn_id: str, reply_text: str,
        prompt_evidence_log: Dict[str, List[str]],  # block_name → evidence_ids
        actions_emitted: List[str],  # FAST_CALL trace_ids
        claims_extracted: List[Dict],
    ) -> None: ...
    def trace_back(self, decision_id: str, depth: int = 5) -> Dict: ...

# 全局单例 + getter
def get_default_tracer() -> LineageTracer: ...
```

**Step 1.2**: 扩 `ConversationEventBus.publish` (`jarvis_utils.py:1276-1380`)
```python
def publish(self, etype, description, source, salience=...,
            evidence_chain: Optional[List[str]] = None,    # 新
            evidence_id: Optional[str] = None,             # 新
            metadata: Optional[Dict] = None) -> str:       # 返回 evidence_id (新)
    ...
    evt_id = evidence_id or EvidenceID.new()
    record = {..., 'evidence_id': evt_id, 'evidence_chain': evidence_chain or []}
    self._deque.append(record)
    # 持久化 critical event
    if salience >= 0.85:
        _persist_to_swm_history_jsonl(record)
    return evt_id
```

**Step 1.3**: PromptBuilder block 加 evidence_ids (现 PromptBlock dataclass 不存在, 新建)
```python
# jarvis_central_nerve.py 新增
@dataclass
class PromptBlock:
    name: str
    text: str
    salience: float = 0.5
    source_evidence_ids: List[str] = field(default_factory=list)
    tier_filter: Set[str] = field(default_factory=set)

# _assemble_prompt 改造: 每个 _parts.append 改为 _blocks.append(PromptBlock(...))
# 现 30+ append 改造时记 evidence_ids
```

**Step 1.4**: chat_bypass.stream_chat 末尾 record_decision
```python
# chat_bypass.py 末尾 (post-stream)
brain_decision_id = f"bd_{turn_id}_{int(time.time()*1000)%10000}"
LineageTracer.get_default().record_decision(
    decision_id=brain_decision_id,
    turn_id=turn_id,
    reply_text=accumulated_reply,
    prompt_evidence_log=prompt_evidence_log,
    actions_emitted=[fc.trace_id for fc in fast_calls],
    claims_extracted=claim_tracer_results,
)
```

**Step 1.5**: 新建 `scripts/lineage_dump.py` CLI
```bash
python scripts/lineage_dump.py --reply-id=bd_turn_xxx --depth=full
python scripts/lineage_dump.py --evidence-id=evt_xxx --backtrack
python scripts/lineage_dump.py --turn-id=turn_xxx --decisions
```

**Step 1.6**: 新建 `memory_pool/lineage_config.json` + `lineage.jsonl` (auto rotate via `jsonl_rotator`)

**Step 1.7**: 新建 `LineageReflector` (L7 propose 高频 broken chain) — 后置, 可 M1+1 周再做

#### 测试 plan

| 测试 | Pass 标准 |
|---|---|
| `pytest tests/test_lineage_basic.py` | 单测 EvidenceID 生成唯一 |
| `pytest tests/test_lineage_swm_publish.py` | publish 返回 evidence_id, deque 含 record |
| `pytest tests/test_lineage_record_decision.py` | record_decision 写 lineage.jsonl 1 行 |
| Sir 真测 1 turn | `lineage_dump.py --reply-id=<latest>` 能看到完整 evidence chain |
| Benchmark | publish 增量 < 0.1ms; record_decision 异步, 主流不阻塞 |

#### 回滚 plan
- M1 全部新增, 不改老代码逻辑 → 失败时 `git revert` M1 commits 即可
- `evidence_id` 字段是新 optional, 不破现 publish 调用

#### 风险
| 风险 | 缓解 |
|---|---|
| lineage.jsonl 写盘频繁卡 IO | 异步 daemon + 1s batch flush; benchmark < 1ms 增量 |
| 30+ render block 改造遗漏 | 一次只迁 1 block, 立 unit test |
| evidence_id 满天飞冗余 | 设计上每 evidence 只在 source 处生成 1 次, 后续传递引用 |

#### 验收准则
- ✅ `scripts/lineage_dump.py --reply-id=<latest>` 能看到从 reply → 30+ block evidence → 6 source row 的完整链
- ✅ pytest 全 pass
- ✅ Sir 真测 30min 不卡 (TTFT < 5s 保持)

---

### 6.3 M2 — MemoryHub 演化 + central_nerve.memory_gateway 改用

#### Scope
- `MemoryMutationGateway` 改名 `MemoryHub`
- `central_nerve.memory_gateway` 从 `UnifiedMemoryGateway` (老) 改用 `MemoryHub`
- 老 `UnifiedMemoryGateway` (memory_core) 删
- 加 `Hub.write_*` 6 方法 (按 6 source 分)
- 每 write 自动写 mem_audit.jsonl (M8 准备) + lineage evidence (M1 已有)

#### Pre-condition
- M1 完成 (lineage_id 可用)

#### 实施步骤

**Step 2.1**: `jarvis_memory_gateway.py` 改名
```bash
git mv jarvis_memory_gateway.py jarvis_memory_hub.py
```
class `MemoryMutationGateway` 改名 `MemoryHub`. `MemoryGateway` global getter `get_default_gateway()` → `get_default_hub()`.

**Step 2.2**: 加 `Hub.write_*` 6 方法 (新接口, 老 `update_sir_field` 保留 backward compat)
```python
class MemoryHub:
    def write_identity(self, field_path, value, source, confidence, reason='') -> MutationReceipt: ...
    def write_event(self, summary, kind, entities=[], embedding=None, source='') -> MutationReceipt: ...
    def write_commitment(self, description, kind, who_promised, deadline=None, **kw) -> MutationReceipt: ...
    def write_concern(self, concern_id, field, new_value, source='') -> MutationReceipt: ...
    def write_state(self, field_path, value, source='') -> MutationReceipt: ...
    def write_relation(self, kind, item_id, field, new_value, source='') -> MutationReceipt: ...

    # 老 backward-compat 方法保留, 内部转调新 write_*
    def update_sir_field(self, field_path, new_value, source, confidence) -> MutationReceipt:
        return self.write_identity(field_path, new_value, source, confidence)
```

**Step 2.3**: `central_nerve.__init__` 改
```python
# 老
self.memory_gateway = UnifiedMemoryGateway(self)
# 新
from jarvis_memory_hub import get_default_hub
self.memory_gateway = get_default_hub()  # attr 名仍 memory_gateway (backward compat)
```

**Step 2.4**: `memory_core.py` 删 `UnifiedMemoryGateway` class (~50 行)

**Step 2.5**: 全文 grep 所有 `MemoryMutationGateway` / `update_sir_field` / `get_default_gateway`, replace 为新名 (允许 alias)

#### 测试 plan
- `pytest tests/test_memory_hub_*.py` 全 pass
- Sir 真测 memory correction → mutation_receipts.jsonl 真有 record + lineage evidence
- benchmark write_identity < 5ms

#### 回滚
- `git revert M2` 即可, 老 update_sir_field API 保留

#### 风险
- 30+ 调用方迁移漏 → grep 严格 + pytest

#### 验收
- ✅ `central_nerve.memory_gateway` 是 MemoryHub 实例
- ✅ Sir 真测 "我距离用 mile" → 走 Hub.write_identity → mutation_receipts.jsonl 真有 + lineage 真有
- ✅ pytest 全 pass

---

### 6.4 M3 — 死代码 + 同名 class + 3-brain 移到 _legacy

#### Scope (合并多个清理动作一次完成)

**3.A. 死代码删** (Phase A.5 list):
- `_archive_promise_log_2026_05_18.json.bak` (0 KB)
- `integrity_audit.jsonl.tainted-184101.bak`
- `central_nerve.py:345-347 self.eyes/hands/env=None`
- `memory_core.TaskWorkerPool` class
- `nerve.py:73-74` 硬编码 HTTP_PROXY → 移 `jarvis_config/network.json`

**3.B. 同名 class 改名** (Phase A.4 list):
- `Claim` (claim_tracer vs integrity_watcher) → `FactClaim` vs `IntegrityClaim`
- `CorrectionEntry` (memory_core vs blood) → `MemCorrectionEntry` vs `BloodCorrectionEntry`
- `MemoryFragment` (memory_core vs blood) → 同上
- `PromptLayer` (memory_core vs blood) → 同上
- `SoulRouter` (routing.py vs enhanced.py) — Q1 拆分时 enhanced.py SoulRouter 移出独立 file 后冲突自动消除

**3.C. 3-brain 移到 `_legacy/3_brain_attempt/`** (Q2 决议):
```bash
mkdir _legacy/3_brain_attempt
git mv l1_right_brain.py _legacy/3_brain_attempt/
git mv l3_left_brain.py _legacy/3_brain_attempt/
git mv l5_reflection_brain.py _legacy/3_brain_attempt/
```

**3.D. central_nerve.run() 长任务流剥离** (Q2):
- `central_nerve.run()` (~800 行 line 4289-5087) 整段移到 `_legacy/3_brain_attempt/central_nerve_run_v1.py`
- `worker.trigger_routing` (worker.py:5073) 删除
- 主对话 100% 走 `chat_bypass.stream_chat` 单脑路径

**3.E. jarvis_enhanced.py 拆 4 file** (Q1 决议):
- `jarvis_proactive_shield.py` (line 52-346 ProactiveShield → 独立)
- `jarvis_proactive_companion.py` (line 347-468)
- `jarvis_skill_tree_tracker.py` (line 469-736)
- `jarvis_soul_router.py` (line 737+)
- `jarvis_enhanced.py` 改为 ~10 行 facade re-export 兼容老 import:
  ```python
  # facade for backward compat
  from jarvis_proactive_shield import ProactiveShield  # noqa
  from jarvis_proactive_companion import ProactiveCompanion  # noqa
  from jarvis_skill_tree_tracker import SkillTreeTracker  # noqa
  from jarvis_soul_router import SoulRouter  # noqa
  ```

**3.F. 30+ 处 `# noqa: F401` 兼容 import 全删** (3-brain + enhanced):
```bash
# grep -l "from l1_right_brain import" *.py | xargs sed -i '...'
# 但要小心: 真用的 (e.g. central_nerve.py 真实例化) 要先确认已删
```

**3.G. `central_nerve.__init__:312-314` 实例化删**

**3.H. ScreenVisionEngine.HumorMemory 老路径删** — 迁到 RelationalState (但实际数据 migration 在 M4 一并处理)

#### 测试 plan
- `pytest tests/` 全 pass (没 break test)
- Sir 真测主对话 30min 不卡, 不出现 ImportError
- 启动 log 不出现 `[ModuleLoader] 跳过 l1_right_brain: ...` (因为已移走, 不再扫)

#### 回滚
- 失败 `git revert M3` 即可
- `_legacy/3_brain_attempt/` 保留, 想恢复 `git mv` 回根目录即可

#### 风险
| 风险 | 缓解 |
|---|---|
| 极少数 task 走 `jarvis.run()` 长任务流, M3 后这条路死 | 真测 24h, 抓 worker._process_user_input 是否有路由失败 |
| 同名 class 改名波及面广 | grep 严格 + 1 名 1 commit, 易 revert |
| `from jarvis_enhanced import` facade 失败 | 先 facade 测通, 再删 noqa import |

#### 验收
- ✅ `_legacy/3_brain_attempt/` 含 5 file (3 brain + central_nerve_run_v1 + l1_l3_l5)
- ✅ jarvis 启动正常, 主对话 30min 真测无 ImportError
- ✅ 4 死文件删, 6 同名 class 改名, jarvis_enhanced 拆 4 file
- ✅ pytest 全 pass

---

### 6.5 M4 — 5 套时间承诺合并 → PromiseLog 单源

#### Scope
合并: PromiseLog + CommitmentWatcher + cyclic_task + watch_task + concerns.notes_for_self → **PromiseLog 单源** (4 kind: commitment/cyclic/watch/self_promise).

#### Pre-condition
- M2 (MemoryHub 已可用)
- 数据 migration 必须 dry-run + Sir 真测验证

#### 实施步骤

**Step 4.1**: PromiseLog schema 扩 (新加 kind / who_promised / trigger_pattern / bound_to_concern_id 字段, 保留老字段)

**Step 4.2**: 写迁移脚本 `scripts/migrate_commitments_to_promise_log.py`
```python
# 1. 读 jarvis_memory.db Commitments 表 → 写 PromiseLog kind=commitment
# 2. 读 cyclic_task.json (若存在) → 写 PromiseLog kind=cyclic
# 3. 读 watch_tasks.json → 写 PromiseLog kind=watch
# 4. 读 concerns.json 各 concern 的 notes_for_self → bound_to_concern_id
# 5. dry-run 模式: 只输出 diff, 不真写
# 6. apply 模式: 真写 + backup 老数据到 _legacy/data_migration_backup/
```

**Step 4.3**: `Hub.write_commitment` 实现 (4 kind 路由)

**Step 4.4**: `CommitmentWatcher` 退化为 read-only 触发器
```python
# 老: 自己管 commitments + add_commitment + cancel_by_keyword
# 新: 只读 PromiseLog, 检 deadline + emit 'reminder_fired' SWM event
class CommitmentWatcher:
    def run(self):  # daemon
        while True:
            for promise in PromiseLog.list_active():
                if promise.kind in ('commitment', 'self_promise', 'cyclic'):
                    if self._is_due(promise):
                        self.event_bus.publish('reminder_fired', ...)
            time.sleep(30)
```

**Step 4.5**: `cyclic_task` / `watch_task` registrar 退化为 `Hub.write_commitment(kind='cyclic'/'watch')` shim

**Step 4.6**: 全文 grep 所有 `add_commitment` / `mark_fulfilled` 调用, 改用 `Hub.write_commitment` / `Hub.cancel_commitment`

**Step 4.7**: dashboard `pending_callbacks.jsonl` 跨进程通道路径不变 (Q4 保留), 但消费时改写 PromiseLog (M4 兼容)

#### 测试 plan
- `pytest tests/test_promise_log_migration.py` (dry-run 验证)
- Sir 真测 1 次 "10:30 叫我去洗澡" → PromiseLog 单源真写 + reminder_fired 真触发
- 真测 24h 看是否漏 fire / 重复 fire

#### 回滚
- migration 真写前必须 backup `_legacy/data_migration_backup/<timestamp>/jarvis_memory.db`
- 失败 → restore backup + revert M4 commits

#### 风险 (高)
| 风险 | 缓解 |
|---|---|
| 数据 migration 错误丢承诺 | dry-run + Sir 真测 1 周 + 自动 backup |
| CommitmentWatcher 退化破触发逻辑 | A/B 测试: 旧 daemon + 新 daemon 并行 1 周, 比 fire 率 |
| concerns.notes_for_self 迁移漏 | 写 verify 脚本: 老 vs 新数据 row count 必须等 |

#### 验收
- ✅ `jarvis_promise_log.json` 含 4 kind 数据
- ✅ Commitments sqlite 表保留作 view (read-only) 或删
- ✅ cyclic_task / watch_task / concerns.notes_for_self 数据迁移完
- ✅ Sir 真测 commitment 触发正常
- ✅ pytest 全 pass

---

### 6.6 M5 — 3 决策路径整合

#### Scope
整合: Conductor + IntentResolver + chat_bypass.FAST_CALL → **主脑 + IntentResolver 单一决策中心**.

#### Pre-condition
- M4 完成

#### 实施步骤

**Step 5.1**: `Conductor.decide_reaction` 评估 — 现真用情况? grep 调用方
- 如果 conductor 真做决策 (β.5.0 前老路径), 退化为 publish-only sentinel
- 如果实际只是 publish 信号给主脑, 直接归类 sensor

**Step 5.2**: `IntentResolver` 升级 — 集中 7 candidate event LLM judge (β.5.44 已立, 这里强化覆盖)
- 所有 mutation candidate 经 IntentResolver 一次 LLM judge → publish 'intent_resolved' SWM event
- chat_bypass.FAST_CALL 路径仍保留 (主脑直接 emit), 但 IntentResolver 是后台 reflector 路径

**Step 5.3**: 文档统一两条路径合法 (主脑直接 FAST_CALL 是同步路径; IntentResolver 是异步 LLM judge 路径), 不冲突. M5 是清理边界, 不是合并.

#### 测试
- pytest 全 pass
- Sir 真测决策延迟 < 5s

#### 验收
- ✅ Conductor 退化为 publish-only or 删除
- ✅ IntentResolver 是唯一 LLM judge 集中点
- ✅ 主脑 FAST_CALL 是唯一 emit 路径

---

### 6.7 M6 — NERVE_SPLIT god object 拆分

#### Scope (4 周, 1 周 1 file)

**Week 1**: `central_nerve.py` (5K+) 拆
- `_assemble_prompt` 30+ block 提到 `jarvis_prompt_builder.py` (与 M7 协作)
- `_set_state` / state machine → `jarvis_state_machine.py`
- 数据 attr 容器保留, 但拆为 mixin

**Week 2**: `chat_bypass.py` (5960 行) 拆
- `_execute_fast_call` + organ dispatch → `jarvis_fast_call_dispatcher.py`
- stream parse + ZH/EN split → `jarvis_stream_parser.py`
- claim trace 后处理 → `jarvis_post_stream_pipeline.py`

**Week 3**: `worker.py` (5823 行) 拆
- Gatekeeper LLM → `jarvis_gatekeeper.py` (现已部分独立, 强化)
- MemoryCorrectionGuard → 已独立 `jarvis_memory_correction.py`
- `_process_user_input` 主流 → 保留 worker.py
- `_detect_sleep_intent` / `_detect_help_refusal` → `jarvis_sir_intent_sensors.py`

**Week 4**: `utils.py` (4861 行) 拆
- ConversationEventBus + EvidenceChain → `jarvis_swm.py`
- TraceContext → `jarvis_trace_context.py`
- safe_gemini_call + KeyRouter wrapper → `jarvis_llm_call.py`
- 各 small util → 保留 `jarvis_utils.py` (但减肥到 ~1000 行)

#### 风险 (高)
- 启动失败 / import 循环 / 主脑 prompt 缺 block
- **缓解**: 每周拆 1 file, pytest + Sir 真测 1 天验证, 失败 revert

#### 验收
- ✅ 4 大 file 都 < 1500 行
- ✅ pytest 全 pass
- ✅ Sir 真测主对话 1 周 stable

---

### 6.8 M7 — PromptBuilder polymorphic + 30 block 全迁

#### Scope
- `PromptBlock(kind=text|image|audio|video, content, ...)` 多 kind
- 现 30+ render block 全迁到 PromptBuilder 集中装配
- PromptBuilder 输出: text concat (now) / multipart (future W1 多模态原生)

#### 实施步骤

**Step 7.1**: `jarvis_prompt_builder.py` 已有? grep
- 部分已迁 3 tier, M7 全 30 block 迁

**Step 7.2**: PromptBlock dataclass 扩 kind 字段 (W1 扩展点)

**Step 7.3**: 30+ block 一次迁 1 个 (~1 天 1 个), 立 unit test

#### 验收
- ✅ `_assemble_prompt` 退化为 `PromptBuilder.assemble(tier).render(format='text')`
- ✅ STANDARD prompt < 25K char (现 25-36K, 减肥目标)
- ✅ pytest 全 pass

---

### 6.9 M8 — 5 audit log 合并 + state 合并 sir_state.json

#### Scope (3 天)

**8.A. 5 audit log 合并** → `mem_audit.jsonl` (单源):
- `mutation_receipts.jsonl`
- `profile_corrections.jsonl`
- `claim_revisions.json`
- `claim_stats.json`
- `integrity_audit.jsonl`

**8.B. State 合并** → `sir_state.json`:
- `sir_status.json`
- `stand_down_state.json`
- `sir_acked_state.json`

#### 实施步骤
- 写 schema + migration 脚本
- 调用方迁
- 老 file 移到 `_legacy/data_migration_backup/`

#### 风险 (低)
- audit log 历史读取脚本可能遗漏

#### 验收
- ✅ `mem_audit.jsonl` 单源, dashboard 真用
- ✅ `sir_state.json` 单源, _assemble_prompt 真读

---

## 7. 验证矩阵 — 8 准则 + 4 问 + 3 硬规

| 检查项 | M1 | M2 | M3 | M4 | M5 | M6 | M7 | M8 |
|---|---|---|---|---|---|---|---|---|
| 准则 1 高效 | ✅ 异步 | ✅ < 5ms write | ✅ 减肥 | ✅ 单源 read 快 | ✅ | ✅ | ✅ 减肥 STANDARD | ✅ |
| 准则 2 反应迅速 | ✅ | ✅ | ✅ | ✅ daemon | ✅ | ✅ | ✅ | ✅ |
| 准则 3 人设 | ✅ | ✅ | ✅ 删话术锁残留 | ✅ | ✅ | ✅ | ✅ evidence-only | ✅ |
| 准则 4 懂我 | ✅ | ✅ Hub 6 source | ✅ | ✅ commitments 单源 | ✅ | ✅ | ✅ | ✅ |
| 准则 5 言出必行 | ✅⭐ 法理基础 | ✅ Hub audit | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 准则 6 三维耦合 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 准则 6 4 问 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 准则 6.5 持久化+CLI+L7 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 准则 7 Sir 元否决 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 准则 8 优雅 > 简单 | ✅ | ✅ | ✅ | ✅ 真合并 | ✅ | ✅ | ✅ | ✅ |

---

## 8. 风险总览 + 总体回滚策略

### 8.1 高风险 milestone

| M# | 风险 | 真测验证窗口 |
|---|---|---|
| **M4** | data migration 错误丢承诺 | dry-run + 1 周 A/B (旧+新 daemon 并行) |
| **M6** | god object 拆破启动 | 1 周 1 file + 真测 1 天验证 |

### 8.2 总体回滚策略

每 milestone 独立 commit, 不允许跨 milestone 大 commit:
- `git revert <M_X_first_commit>..<M_X_last_commit>` 整 M 退
- 数据 migration 自动 backup `_legacy/data_migration_backup/<ts>/`
- pytest 必须前置 (fail 不 commit)

### 8.3 真测纪律

| 时点 | 谁 | 测什么 |
|---|---|---|
| 每 milestone 完成 | Cascade | pytest 全 pass |
| 每 milestone 完成 | Sir | 真机 1 天 (主对话 + nudge + correction) |
| 每 phase 完成 | Sir | 真机 3 天 + 24h 不重启 |
| 全 reshape 完成 | Sir | 真机 1 周 + 多 nudge / commitment / correction case |

---

## 9. 5-10 年演化路线 (Sir 关心 — 持续运转能力)

| 期 | 时点 | 演化 |
|---|---|---|
| **现在 (Reshape 启动前)** | 2026-05-24 | Phase A+B 设计完成, 等动工 |
| **Phase D 完成** | 2026-Q3 | M1-M8 全完成, 主体稳定; Sir 加新能力 = 加数据模块 (R1-R4) |
| **1-3 年** | 2027-2029 | W1 (多模态原生) 来时, PromptBlock kind 扩 image/audio. 不动其他护城河 |
| **3-5 年** | 2029-2031 | W2 (多 agent) 来时, BrainDecision.delegated_to 启用; 长任务流恢复时把 `_legacy/3_brain_attempt/` 拿回, 但**走 SWM + Hub 协议**, 不是老 god 路径 |
| **5+ 年** | 2031+ | W3 (多 device/多用户) 来时, Storage interface 切分布式; Subject 多用户 |
| **理论极限** | 10+ 年 | LLM paradigm 完全不同, 必有下一次 grand refactor — 是工程正常迭代 |

**Sir 真意核对**: "**只要这个架构有持续运转的能力即可, 调整不可避免**". ✅ Reshape 完全符合.

---

## 10. 加新能力 SOP (Phase D 后, 5-10 年内通用)

> 任何 agent 加新 sensor / effector / sentinel / reflector 时, **必须**走以下 SOP. 违反 = Sir 真测打回.

### Step 1: 准则 6 — 4 问筛查 (β.5.44)

| # | 问 | 通过? |
|---|---|---|
| 1 | 数据 publish 进 SWM (M1)? | □ Yes / □ No |
| 2 | 决策让 LLM 做 (R2)? | □ Yes / □ No |
| 3 | 配置持久化 vocab + CLI (R3, 准则 6.5)? | □ Yes / □ No |
| 4 | 和已有 module 正交 (不重复)? | □ Yes / □ No |

任一 No → 不加, 或先解决 No 再加.

### Step 2: 走铁律 R1-R4

- 新 sensor: 只 publish, 不 mutate state, 不 call 其他 module (R1)
- 新决策: 经 LLM 不写 if/else (R2)
- 新行为: vocab JSON + CLI + L7 propose (R3)
- 新数据落地: 经 `Hub.write_*()` 单入口 (R4)

### Step 3: 加 Lineage trace 钩子

- 你 publish event 时, `evidence_chain` 字段填上游 evidence_ids
- 你 write Hub 时, evidence_id 自动生成 (M1 已实现)
- 你的 module 行为可被 `lineage_dump.py` 反向追溯

### Step 4: 准则 6 工程方法论 (3 硬规)

- vocab 写 `memory_pool/<name>_vocab.json` (不 hardcoded .py)
- CLI 写 `scripts/<name>_dump.py` (Sir 可看/加/激活/拒绝)
- Reflector 写 `jarvis_<name>_reflector.py` (L7 LLM-propose 新 vocab)

### Step 5: 测试

- `pytest tests/test_<name>_basic.py` 单测
- Sir 真测 1 天

---

## 11. Sir 醒来 — 动工前 checklist ⭐

Sir 醒来后, 打开本 doc, 跟着以下步骤即可进入 Phase D 动工:

### 11.1 阅读顺序 (~30 min)

1. **本 doc §1** (4 项决议) — 看 Cascade 拍的 Q1-Q4 是否同意
2. **本 doc §2** (4 护城河 + 4 铁律) — 心智模型对齐
3. **本 doc §6.2** (M1 详细) — 知道第一步要做什么
4. **`AGENTS.md`** — 章程 refresh
5. **`docs/JARVIS_PHASE_B_DESIGN.md`** §5 (Lineage Trace 详细) — Reshape doc 的简化版可以 skip

### 11.2 拍板 (5 min)

| 决议 | Cascade 提案 | Sir |
|---|---|---|
| Q1 | jarvis_enhanced.py 拆 4 file | □ accept / □ override |
| Q2 | 3-brain 移 _legacy + central_nerve.run() 删 | □ accept / □ override |
| Q3 | central_nerve.memory_gateway → MemoryHub | □ accept / □ override |
| Q4 | cross_session_callback 保留 (跨进程 IPC 真用) | □ accept / □ override |

### 11.3 进 Phase D — M1 启动

```powershell
# 1. 看 §6.2 M1 详细步骤
# 2. 跟 Cascade 说 "动工 M1"
# 3. Cascade 按 §6.2 Step 1.1-1.7 顺序执行
# 4. 每 Step 独立 commit, pytest 前置
# 5. 完成后 Sir 真测 lineage_dump.py 验证
```

### 11.4 Sir 不需要做的事

- ❌ 不需要再设计 (本 doc 全有)
- ❌ 不需要担心 backward compat (4 铁律保证)
- ❌ 不需要 review 每个 commit (pytest + 真测验证为主)

### 11.5 Sir 需要做的事

- ✅ Q1-Q4 拍板 (5 min)
- ✅ 每 milestone 完成后 1 天真测
- ✅ Phase D 完成后 1 周真测
- ✅ Sir 元否决权 (准则 7) — 任何冲突 Sir 拍板

---

## 12. Phase A+B+Reshape 完整 doc 索引

| Doc | 行 | 用途 |
|---|---|---|
| `AGENTS.md` | < 400 | 入口章程 |
| `docs/JARVIS_GRAND_REFACTOR.md` | ~370 | 立项书 + LIVE 进度 |
| `docs/JARVIS_AUDIT_CARDS.md` | ~3300 | 140 模块审计 |
| `docs/JARVIS_DATAFLOW_MAP.md` | ~600 | 数据流 |
| `docs/JARVIS_STORAGE_MAP.md` | ~500 | 93 storage file |
| `docs/JARVIS_COUPLING_MATRIX.md` | ~400 | 耦合矩阵 |
| `docs/JARVIS_LEGACY_AUDIT.md` | ~150 | 历史 audit |
| `docs/JARVIS_ARCHITECTURE_MAP.md` | ~580 | 静态架构 |
| `docs/JARVIS_PHASE_B_DESIGN.md` | ~700 | Phase B 设计 |
| **`docs/JARVIS_GRAND_ARCHITECTURE_RESHAPE.md`** | ~1300 | **本 doc, 最终设计书** ⭐ |
| `docs/JARVIS_MEMORY_AND_MUTATION_REFACTOR_v1_archive.md` | 647 | 老记忆重构 (archive, ref only) |
| `docs/AGENT_KICKOFF_GRAND_RESHAPE.md` | (待写) | Sir 醒来 kickoff |

---

## 13. 完成状态

**本 doc 完成**: 2026-05-24 00:50.

**Phase A+B+Reshape**: ✅ 全部完成. 等 Sir 醒来 Q1-Q4 accept → 进 Phase D-M1 动工.

**下一步**: Sir 醒来 → 看 §11 checklist → 拍板 → 跟 Cascade 说 "动工 M1".

---

*Sir 一觉醒来, 打开 IDE, 看本 doc §11, 5 min 拍板 4 项决议, 即可进入 Phase D-M1 动工.*
*Cascade 已把所有思考 / 设计 / 风险 / 测试 plan 全部写完, 等 Sir 拍板.*

