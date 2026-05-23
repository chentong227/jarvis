# JARVIS Phase B Design — 大重构总体架构设计

> Phase B 产出: 基于 Phase A 6000 行 audit, 设计 Jarvis 下一代统一架构.
>
> 本 doc 严格核对 **Sir 8 项设计准则** + 准则 6 工程方法论 (3 硬规) + 准则 6 4 问 (β.5.44) + 准则 6 递归边界 (β.3.5).
>
> 写于 2026-05-24 00:00, 等 Sir 拍板进 Phase C.

---

## 目录

1. 设计哲学 — 8 准则核对 + 真意
2. 4 个护城河 + 3 个薄弱点 + 4 条铁律
3. 完整架构 6 layer 图
4. Source of Truth — 6 类记忆
5. **Lineage Trace 基础设施** ⭐ (Sir 这次新立)
6. 4 大支柱 module
7. 现有 90 模块的命运 (保留 / 改造 / 拆分 / 删除)
8. Phase D 实施路线 — 8 个 milestone
9. Sir 拍板列表 (4 项决议)

---

## 1. 设计哲学 — 8 准则核对

> 每条新增设计**必须**逐条核对. 任一准则破 = 设计失败.

| # | 准则 | 在本 Phase B 设计的体现 |
|---|---|---|
| **1** | **高效** (TTFT<5s / pipeline<8s) | PromptBuilder 减肥 STANDARD ≤ 25K char, 主脑 LLM 调用单次, lineage trace 异步落盘不阻塞 |
| **2** | **反应迅速** (终端不卡 / 异步链) | SWM publish 全异步, lineage 写 jsonl 异步, 重模块 (Hippocampus / ToM) 全 daemon |
| **3** | **符合人设** (butler / 不奉承) | 删 12 处话术锁残留 / forbidden list (Phase D-M3); evidence-only directive, Soul L0-L3 让主脑自然涌现 |
| **4** | **懂我** (老友感 / profile / hippocampus) | 6 source 统一 MemoryHub, profile 嵌套支持, recent_completed_events 防重复, RelationalState 强化 |
| **5** | **言出必行** (INTEGRITY ABSOLUTE) | **Lineage Trace = 准则 5 法理基础**. 每个 LLM claim 反向链回 evidence; ClaimTracer + IntegrityWatcher + retry_* 链稳定 |
| **6** | **拒绝硬编码 + 三维耦合** | 数据强耦合 SWM 单中介; 行为弱耦合 publish-only sentinel; 决策集中 IntentResolver/主脑; 4 问筛新模块 |
| **7** | **Sir 元否决权** | 本 doc 仅是设计提案, Sir 拍板才执行; Sir 拍板冲突时章程让步 |
| **8** | **优雅 > 简单** | 不允许 hot-fix; 5 套时间承诺合并 / 3 决策路径整合 / god object 拆分都走"正确架构"路径, 不留糖衣 patch |

### 准则 6 — 新模块 4 问筛查 (β.5.44)

本 Phase B 提议**仅 1 个新模块** (LineageTracer), 其余皆**演化**或**合并**已有. LineageTracer 4 问:

| # | 问 | 答 |
|---|---|---|
| 1 | 数据 publish 进 SWM? | ✅ trace event 也是 SWM event 一种, 走同一总线 |
| 2 | 决策让 LLM 做? | ✅ tracer 只采集 + 链接, 不决策 (debug 工具) |
| 3 | 配置持久化 + CLI 可改? | ✅ `lineage_config.json` + `scripts/lineage_dump.py` |
| 4 | 和已有 module 正交? | ✅ 跟 ClaimTracer 互补 (Claim = factual claim verify, Lineage = full DAG); 跟 TraceContext 共用 trace_id |

### 准则 6 工程方法论 (3 硬规) 全 doc 体现

- **持久化**: 所有新增 vocab / config 进 `memory_pool/*.json`, 不写死 .py
- **CLI 可改**: 配套 `scripts/<thing>_dump.py`
- **L7 LLM-propose**: 配套 reflector 看 evidence, LLM propose 加新 vocab → review queue

---

## 2. 4 个护城河 + 3 个薄弱点 + 4 条铁律

### 2.1 4 个护城河 — 5-10 年内不动

| # | 护城河 | 现状 | Phase B 强化 |
|---|---|---|---|
| **M1** | **SWM 唯一中介** | β.5.0 已立, 三维耦合 | 加 `evidence_chain` DAG 字段; critical event ≥0.85 持久化 jsonl |
| **M2** | **标准 Action 协议** | `Action(organ, command, parameters)` 已立 | 加 `trace_id` 字段; 所有 24 hands 强制 `ExecutionResult.evidence` 字段 |
| **M3** | **Lineage Trace** | ⭐ 新立 | 见 §5 |
| **M4** | **vocab 持久化 (准则 6.5)** | 38+ vocab 已模范 | 剩余 hardcoded 全迁 (Phase D-M3) |

### 2.2 3 个薄弱点 — 5 年内**必有**重构 (现在留扩展点)

| # | 薄弱 | 冲击源 | 现在留的扩展点 |
|---|---|---|---|
| **W1** | **Prompt 是 text** | 多模态原生 LLM (1-3 年) | `PromptBlock(kind=text|image|audio|video, content)` 预留多 kind |
| **W2** | **单 LLM 决策中心** | 多 agent 协作 (3-5 年) | `BrainDecision.delegated_to: agent_id` 字段预留 |
| **W3** | **单机 / 单用户** | 多 device + 多用户 (3-5 年) | Storage 抽 interface, Identity 抽 `Subject`, 不假设 hardcoded "Sir" |

### 2.3 4 条铁律 — 加新能力的硬约束

> 写进未来所有 KICKOFF doc, 加新 module 的 agent 必须遵守. 违反 = Sir 真测打回.

| # | 铁律 | 违反后果 |
|---|---|---|
| **R1** | 加新 sensor / effector **必须**只 publish 进 SWM, **不**直接 mutate state, **不**直接 call 其他 module | 破 M1 SWM 中介, 5 年内必再重构 |
| **R2** | 加新决策**必须**经主脑 LLM, **不准**在 python 里 if/else 做新决策 | 破"LLM 决策集中", 退化回 sentinel 时代 |
| **R3** | 加新行为模式**必须** vocab JSON + CLI + L7 propose, **不准** hardcoded list 在 .py | 破 M4 vocab 持久化, 退化回话术锁时代 |
| **R4** | 加新数据落地**必须**经 `MemoryHub.write()` 单入口, **不准**直接写 file/sqlite | 破 M3 Lineage trace, 审计断链 |

---

## 3. 完整架构 6 layer 图

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 6: Output (TTS + Subtitle + Visual UI)                │
│   VocalCord / SubtitleOverlay / BreathingLightUI             │
└─────────────────────────▲───────────────────────────────────┘
                          │ reply tokens + metadata
┌─────────────────────────┴───────────────────────────────────┐
│ Layer 5: Decision — LLM 主脑 (单一决策中心)                  │
│   PromptBuilder → Gemini stream → BrainDecision              │
│   (含 reaction_space: silence/voice/silent_text/visual/tool) │
└─────────────────────────▲───────────────────────────────────┘
                          │ read SWM evidence + 6 source
┌─────────────────────────┴───────────────────────────────────┐
│ Layer 4: SWM (Shared World Model) ⭐⭐⭐ M1 护城河            │
│   ConversationEventBus + EventChain DAG (新)                 │
│   in-memory deque(60) + critical events ≥0.85 jsonl 持久化   │
└──────────▲──────────────────────────────────▲───────────────┘
           │ publish events                   │ read evidence
┌──────────┴───────────┐         ┌────────────┴───────────────┐
│ Layer 3: Sensor      │         │ Layer 3': Effector          │
│ (publish-only)       │         │ (read-only via MemoryHub)   │
│  PhysicalEnvProbe    │         │  24 hands (l4_*.py)         │
│  AmbientSensor       │         │  via Action protocol M2     │
│  ScreenVision        │         │                             │
│  SilenceIntel        │         └────────────▲────────────────┘
│  ReturnSentinel      │                      │ FAST_CALL emit
│  Gatekeeper          │                      │
│  ConcernFeedback     │         ┌────────────┴────────────────┐
│  SelfPromiseDetect   │         │ Layer 2: IntentResolver     │
│  MemoryCorrection    │         │  (LLM judge, Sir 反馈集中)  │
│  ...                 │         │  publish-only candidate     │
└──────────────────────┘         └────────────▲────────────────┘
                                              │
┌─────────────────────────────────────────────┴───────────────┐
│ Layer 1: MemoryHub ⭐ (P2-Gap7 演化, 单 mutation 入口)        │
│   write_identity / write_event / write_commitment /          │
│   write_concern / write_state / write_relation               │
│   ↓ 6-layer routing + audit + SWM publish + lineage          │
│   ↓ 写入对应 source                                           │
│                                                               │
│ Layer 0: Source of Truth (6 类) — §4                          │
│   A. Identity   → sir_profile.json + milestones              │
│   B. Events     → jarvis_memory.db (Hippocampus)              │
│   C. Commitments → jarvis_promise_log.json (单源, 合并 5 套)  │
│   D. Concerns   → concerns.json                              │
│   E. State      → sir_status.json + stand_down + 合并        │
│   F. Relations  → relational_state.json                      │
└──────────────────────────────────────────────────────────────┘

         ┌─── LineageTracer (M3 护城河, §5) ────┐
         │  跨全 layer 收集 evidence DAG       │
         │  反向追溯: reply token → 数据底层    │
         └─────────────────────────────────────┘
```

**关键设计**:
1. **数据流单向**: Sensor publish → SWM → 主脑读 → 决策 emit Action → MemoryHub.write → Source. 不允许跨层短路 (R1)
2. **mutation 单入口**: 任何 source 修改必须经 MemoryHub.write (R4), 自动 lineage + audit + SWM publish
3. **决策单中心**: Layer 5 主脑 LLM 是唯一决策, IntentResolver 是 LLM judge 集中点 (R2)

---

## 4. Source of Truth — 6 类记忆

> 严格 6 类, **不准**第 7 类出现. 加新数据 = 归到 6 类之一, 或者**非数据** (是配置/vocab/audit, 不是记忆).

### 4.1 6 类详

| 类 | 中文 | 文件 | Schema | 写者 (经 Hub) | 读者 |
|---|---|---|---|---|---|
| **A. Identity** | 身份/画像 | `sir_profile.json` + `sir_milestones.json` | `{biographic, preferences, work_rhythms, health_targets, lifetime_milestones, ...}` | `Hub.write_identity(field_path, value, source, confidence)` | 主脑 prompt block #9 #7; SelfAnchor; WeeklyReflector |
| **B. Events** | 事件/记忆 | `jarvis_memory.db` (TaskMemories, ProjectTimeline) | sqlite row + embedding | `Hub.write_event(summary, kind, entities)` | Hippocampus.search_memory; recent_completed; LTM retrieve |
| **C. Commitments** | 承诺 (合并 5 套) | `jarvis_promise_log.json` (主) + Commitments sqlite (副) | `{id, kind, who_promised, description, deadline, state, evidence}` | `Hub.write_commitment(...)` | CommitmentWatcher daemon; ClaimTracer; reminder_fired |
| **D. Concerns** | 关心/牵挂 | `concerns.json` | `{id, what_i_watch, severity, state, recent_signals, ...}` | `Hub.write_concern(...)` | 主脑 soul block; ProactiveCare; reflector |
| **E. State** | 当前状态 (合并 sir_status / stand_down / sir_acked) | `sir_state.json` (新合并) | `{sleeping, online, AFK, focus, mood, stand_down, acked_state}` | `Hub.write_state(...)` | 主脑 prompt block; ProactiveCare; ReturnSentinel |
| **F. Relations** | 关系 | `relational_state.json` | `{inside_jokes, unspoken_protocols, unfinished_business, shared_history_threads}` | `Hub.write_relation(...)` | 主脑 relational block; InsideJokeReflector |

### 4.2 5 套时间承诺合并 → C 单源

| 老 (5 套) | 新 (1 套) |
|---|---|
| `PromiseLog` (Jarvis 自承诺 + Sir 承诺) | ⭐ 主源 `jarvis_promise_log.json` |
| `CommitmentWatcher` (Sir 时间承诺) | 视图 (read-only daemon, 看 promise_log 触发 reminder_fired) |
| `cyclic_task` (循环任务) | promise.kind = 'cyclic' |
| `watch_task` (主动等的事件) | promise.kind = 'watch' |
| `concerns.notes_for_self` (concern 内提醒) | 移到 promise.bound_to_concern_id |

合并后**所有时间承诺**都在 PromiseLog 单源, 4 类 kind: `commitment / cyclic / watch / self_promise`. CommitmentWatcher daemon 退化为 read-only 触发器.

### 4.3 不属于 6 类的数据 — 各归各处

| 数据 | 归属 | 不属于 6 source |
|---|---|---|
| Vocab (40 个 json) | 配置 / 行为驱动, **不是记忆** | 单独 `memory_pool/*_vocab.json` |
| Audit log (5+ jsonl) | 准则 5 言出必行的证据链 | 合并 `mem_audit.jsonl` |
| SWM event 持久化 (新) | 跨 session evidence 保留 | `swm_history.jsonl` (critical events ≥0.85) |
| Lineage DAG (新) | 反向追溯 | `lineage.jsonl` (§5) |
| Skill registry | 24 hands 自动加载 | `skill_registry.jsonl` (现有) |

---

## 5. Lineage Trace 基础设施 ⭐ (Sir 这次新立, M3 护城河)

> Sir 原话: "**通过主脑的判决反向追踪, 直到审到模块最底层的数据获取端**".
>
> **这是准则 5 言出必行的法理基础**. 主脑 claim X → 必须能 trace 到 evidence raw row.

### 5.1 设计

```
LLM reply token
    │ trace_id (turn_id 已有)
    ▼
brain_decision_id (新)
    │ links: List[evidence_id]
    ▼
prompt_evidence_log (新)  — 每 prompt 装配的 block 都记录 source evidence
    │ block_id → source_evidence_ids
    ▼
[ Evidence ID schema ]
    evidence_id: 'evt_<timestamp>_<4hex>'
    source_module: 'PhysicalEnvProbe' / 'ProfileCard' / 'Hippocampus' / ...
    source_method: 'tick' / 'overwrite_field' / 'add_completed_event' / ...
    source_data_id: db_row_id / json_path / file_offset
    parent_evidence_ids: List[evidence_id]  — DAG 上游
    raw_snapshot: {...}  — 关键 raw 字段 (有限大小)
    ▼
sensor raw / source data
    e.g. window_title='Chrome' from PhysicalEnvProbe at 23:50:12.345
```

### 5.2 SWM event 增字段

`ConversationEventBus.publish` 加 2 字段:

```python
def publish(self, etype, description, source, salience=...,
            evidence_chain: List[str] = None,   # 新 — 上游 evidence_id 列表
            evidence_id: str = None) -> str:    # 新 — 自动生成或传入
    """返回 evidence_id (新)"""
```

### 5.3 PromptBuilder 装配时记录

每个 render block 装配时:
```python
block = PromptBlock(
    name='soul_block',
    text=concerns.render_for_prompt(),
    source_evidence_ids=[concerns.evidence_id_top_3]  # 新
)
```

PromptBuilder 输出时把所有 `source_evidence_ids` 合并到 `prompt_evidence_log` 写 jsonl.

### 5.4 LLM 决策落定后反向 mapping

`chat_bypass.stream_chat` 末尾:
```python
brain_decision_id = f"bd_{turn_id}_{int(time.time()*1000)%10000}"
LineageTracer.record_decision(
    decision_id=brain_decision_id,
    turn_id=turn_id,
    reply_text=accumulated_reply,
    prompt_evidence_log=prompt_evidence_log,  # 整 prompt 的 evidence
    actions_emitted=[fc.trace_id for fc in fast_calls],
    claims_extracted=claim_tracer_results,
)
```

写入 `memory_pool/lineage.jsonl`.

### 5.5 反向追溯工具 (CLI)

```powershell
python scripts/lineage_dump.py --reply-id=bd_turn_xxxx --depth=full
```

输出:
```
[bd_turn_20260524_001234_5678] reply: "Confirmed today, Sir. Enjoy rest day tomorrow."
├── prompt evidence:
│   ├── soul_block (concern_top_3) ← evt_20260524_001230_a1b2
│   │   └── source: ConcernsLedger.list_active_top_n() ← row#sir_health_check
│   ├── recent_completed (rce_lines) ← evt_20260524_001231_c3d4
│   │   └── source: Hippocampus.list_recent_completed_events() ← TaskMemories.id=1779
│   │       └── written by: MemoryGateway.cascade_completion (fix82-X)
│   │           └── trigger: worker.MemoryCorrectionGuard ← turn_xxx user_input '今天血压咨询完成'
│   └── ... (其他 28 block 各自 evidence)
├── actions emitted:
│   └── (none, 主脑只是 ack)
└── claims extracted:
    └── 'Confirmed today' → verified by recent_completed evidence ✓
```

**Sir 一键看见**: 主脑说"今天确认", 是因为 prompt 含 recent_completed_events block, 这个 block 来自 Hippocampus.list_recent_completed_events 的 row#1779, 这个 row 是 fix82-X cascade 写的, 这个 cascade 是因为 turn_xxx Sir 教了"血压咨询完成". 完整因果链.

### 5.6 性能预算

- evidence_id 生成: < 0.1ms (uuid4 hex)
- 写 lineage.jsonl: 异步 daemon, 批量 1s flush, 不阻塞主流
- prompt_evidence_log 装配: 每 block 加 1 个 list append, < 1ms
- 总开销: prompt 装配 < 5ms 增量, 主流不感

### 5.7 持久化 + CLI + Reflector (准则 6.5)

| | |
|---|---|
| 持久化 | `memory_pool/lineage.jsonl` (rotate by jsonl_rotator) + `lineage_config.json` |
| CLI | `scripts/lineage_dump.py` (5.5) + `scripts/lineage_query.py --evidence-id=evt_xxx` |
| Reflector | `LineageReflector` 看 lineage 跨日数据, LLM propose "高频 broken chain" 补强 (e.g. block X 经常没 evidence_ids, 该补) |

---

## 6. 4 大支柱 module

### 6.1 MemoryHub (P2-Gap7 演化, 不重写)

**演化路径**:
1. `MemoryMutationGateway` 改名 `MemoryHub` (单数主语, 不是 Gateway)
2. `UnifiedMemoryGateway` (memory_core 老) 删
3. `central_nerve.memory_gateway` attr 改用新
4. API 增 `write_*` 6 方法 (按 6 source 分):
   ```
   Hub.write_identity(field_path, value, source, confidence) → MutationReceipt
   Hub.write_event(summary, kind, entities, ...) → MutationReceipt
   Hub.write_commitment(description, kind, deadline, ...) → MutationReceipt
   Hub.write_concern(...) → MutationReceipt
   Hub.write_state(field, value, ...) → MutationReceipt
   Hub.write_relation(...) → MutationReceipt
   ```
5. 每个 write 自动:
   - 写对应 source
   - 生成 `evidence_id`
   - 写 `mem_audit.jsonl` (合并 5 audit log)
   - publish SWM `*_field_updated` 事件
   - 触发 cascade (如 fix82-X completion → cancel commitment)

### 6.2 EventBus / SWM (β.5.0 已立, 加 lineage)

**新增**:
- `evidence_id` 自动生成
- `evidence_chain: List[str]` DAG 上游
- `salience >= 0.85` 自动写 `swm_history.jsonl` (跨 session 持久化)

### 6.3 PromptBuilder (PromptBlock polymorphic)

**新设计**:
```python
@dataclass
class PromptBlock:
    name: str                          # e.g. 'soul_block'
    kind: Literal['text', 'image', 'audio', 'video']  # W1 扩展点
    content: Any                       # text str / PIL Image / bytes / ...
    salience: float                    # block 级权重
    source_evidence_ids: List[str]     # M3 lineage
    tier_filter: Set[str] | None       # e.g. {STANDARD, CRITICAL}
```

PromptBuilder.assemble(tier) → ordered List[PromptBlock] → renderer (now: text concat; future: multipart).

**渐进迁移**: Phase D-M7 把现 30+ render block 一次迁完.

### 6.4 IntentResolver / Brain Decision (β.5.44 已立)

**新增**:
- `BrainDecision.delegated_to: agent_id | None` (W2 扩展点, 现 None)
- `BrainDecision.reaction_space` 已有 (silence/voice/silent_text/visual/tool)
- `BrainDecision.lineage_evidence_ids` (M3 反向 mapping)

---

## 7. 现有 90 模块的命运

| 命运 | 数量 | 例 |
|---|---|---|
| **保留稳定** | ~50 | Hippocampus / ConcernsLedger / RelationalState / DirectiveRegistry / SelfAnchor / ProfileCard / SWM / KeyRouter / 24 hands / Soul L0-L5 reflectors / etc. |
| **改造合并** | ~12 | CommitmentWatcher 退化为 PromiseLog 视图; HumorMemory 迁 RelationalState; UnifiedMemoryGateway 删; sir_status/stand_down/acked 合 sir_state |
| **拆分 god object** | 3 | central_nerve.py (5K+) / chat_bypass.py (5960) / worker.py (5823) — Phase D-M6, 4 周 |
| **删除死代码** | ~10 | TaskWorkerPool / safety.execute_memory_updates / 4 死文件 / nerve.py:73-74 hardcoded proxy / `central_nerve:345-347 self.eyes/hands/env=None` |
| **新建** | 1 | LineageTracer + LineageReflector (M3) |
| **待 Sir 决议** | 4 | jarvis_enhanced.py (拆 4 class) / 3-brain (RightBrain/LeftBrain/ReflectionBrain 真用?) / pending_callbacks.jsonl 启用 vs 删 / safety 老 MEMORY_UPDATE 何时下线 |

---

## 8. Phase D 实施路线 — 8 个 milestone

> 准则 8 优雅 > 简单. 每 milestone 独立 commit + 真测验证. 不允许跳过架构走 hot-fix.

| M# | 任务 | 周期 | 风险 | 交付物 |
|---|---|---|---|---|
| **M1** | **Lineage Trace 基础设施** ⭐ | 1-2 周 | 低 (只加, 不改) | `jarvis_lineage.py` + SWM 字段 + lineage.jsonl + CLI |
| **M2** | **MemoryHub 演化** (P2-Gap7 改名 + 6 write 方法) | 1 周 | 中 (调用方迁) | `jarvis_memory_hub.py` + 调用方迁 (MemoryGateway → Hub) |
| **M3** | **死代码清理 + 同名 class 改名** | 1 周 | 低 | 6 个同名 class 改名 + 4 死文件删 + TaskWorkerPool 删 |
| **M4** | **5 套时间承诺合并 → PromiseLog 单源** | 2 周 | 高 (data migration) | PromiseLog schema 扩 + CW/cyclic/watch 退化 + 迁移脚本 |
| **M5** | **3 套决策路径整合 → 主脑 + IntentResolver** | 1 周 | 中 | Conductor 退化为 publish-only sentinel; IntentResolver 集中决策 |
| **M6** | **NERVE_SPLIT god object 拆分** | 4 周 (1 周 1 file) | 高 | central_nerve / chat_bypass / worker / utils 各拆为 5-10 个独立 file |
| **M7** | **PromptBuilder polymorphic 重构** | 2 周 | 中 | PromptBlock 多 kind + 30+ block 全迁 |
| **M8** | **5 audit log 合并 mem_audit.jsonl + state 合并 sir_state.json** | 3 天 | 低 | 合并 schema + 调用方迁 |

**总周期估**: 12-13 周 (~3 个月). 但**不连续做**, 中间 Sir 真测 + bug fix + 新 feature 穿插.

**优先级建议**: M1 先做 (lineage 是 debug 神器, 后面所有 milestone 都依赖它做反向追溯), 然后 M3/M2 (清理 + 演化), 再 M4-M5 (合并大重构), 最后 M6-M8 (god object + prompt + audit).

---

## 9. Sir 拍板列表 (4 项决议)

> Sir 拍板这 4 项, Phase B 设计才算锁定, 进 Phase C/D.

### Q1. `jarvis_enhanced.py` 4 class 命运

**现状**: `ProactiveShield` (真用 routing.py), `SkillTreeTracker` (真用 central_nerve), `ProactiveCompanion` (真用 companion_center), 第 4 个待查.

**选项**:
- A. 保留 jarvis_enhanced.py 单 file (758 行)
- B. 拆 4 class 各自独立 file (`jarvis_proactive_shield.py` / `jarvis_skill_tree_tracker.py` / etc.)
- C. ProactiveShield + ProactiveCompanion 合并到 sentinels.py, SkillTreeTracker 独立

### Q2. 3-brain (`RightBrain` / `LeftBrain` / `ReflectionBrain`) 命运

**现状**: 实例化在 `central_nerve:312-314`, 但实际 usage 不明 (待 grep `.right_brain.X` / `.left_brain.X` / `.l5_brain.X`).

**选项**:
- A. 真用, 保留
- B. 占位/legacy, 删
- C. 部分用, 留一个 (e.g. ReflectionBrain) 删其他

### Q3. `central_nerve.memory_gateway` attr 改用 MemoryHub (新)

**现状**: 是 `UnifiedMemoryGateway` (老 memory_core 路径), 但实际 mutation 走 MemoryMutationGateway (新).

**Phase D-M2 必做**: `central_nerve.memory_gateway = MemoryHub.get_default()`. Sir 拍板 ok 即执行.

### Q4. `cross_session_callback` + `pending_callbacks.jsonl` 命运

**现状**: `pending_callbacks.jsonl` 0 KB 似乎未真用. `CrossSessionCallback` module 还在.

**选项**:
- A. 启用 jsonl 持久化路径 (跨 session 心结跨重启保留)
- B. 删 jsonl + module 简化为内存 only
- C. 重新设计跨 session 心结机制

---

## 10. 风险评估

| 风险 | 影响 | 缓解 |
|---|---|---|
| **M4 PromiseLog 合并 data migration 失败** | Sir 历史承诺数据丢 | 迁移脚本必须 dry-run + Sir 真测验证 + backup |
| **M6 god object 拆分破坏功能** | 启动失败 / 主脑 prompt 缺 block | 1 周 1 file 渐进; 每拆一个 pytest + 真机 1 天验证 |
| **M5 Conductor 退化** | 决策延迟 / 重复 | A/B 测试 (新老路径并行 1 周) |
| **lineage.jsonl 写盘开销** | 主流卡顿 | 异步 daemon + 批量 1s flush, benchmark 验证 < 1ms 增量 |
| **Sir 真测打回某 milestone** | 部分 revert | 每 milestone 独立 commit, 易 revert; 不允许跨 milestone 大 commit |

---

## 11. 5-10 年演化路线 (Sir 关心 — 持续运转能力)

| 期 | 时点 | 演化 |
|---|---|---|
| **现在 (Phase B 锁定后)** | 2026-Q2 | 4 护城河立稳 + 4 铁律明文 + 8 milestone 路线 |
| **1 年内** | 2027-Q2 | M1-M8 全完成, jarvis 主体稳定. Sir 加新能力 = 加数据模块, 不动核心 |
| **1-3 年** | 2027-2029 | W1 (多模态原生) 来时, PromptBlock kind 扩 image/audio. 不动其他护城河 |
| **3-5 年** | 2029-2031 | W2 (多 agent) 来时, BrainDecision.delegated_to 启用 + sub-agent 接 SWM. 不动 M1/M3/M4 |
| **5+ 年** | 2031+ | W3 (多 device/多用户) 来时, Storage interface 切分布式实现 + Subject 多用户. 仍不动 M1 SWM 模型 |
| **理论极限** | 10+ 年 | 主脑 LLM paradigm 完全不同 (e.g. 真 world model agent), **必须**重构 — 但**那也只是 Phase B 之后的下一次 grand refactor, 是工程正常迭代** |

**Sir 真意核对**: "**只要这个架构有持续运转的能力即可, 调整不可避免**". ✅ 本设计完全符合 — 5-10 年内不**整体**重构, 但局部演化必有 (不是设计失败).

---

## 12. 验证矩阵 — 准则 1-8 + 4 问 + 3 硬规

| 检查项 | 通过? |
|---|---|
| 准则 1 高效 (TTFT<5s) | ✅ lineage 异步; PromptBuilder 减肥; 单次 LLM 调用 |
| 准则 2 反应迅速 | ✅ SWM publish 全异步; 重模块 daemon |
| 准则 3 符合人设 | ✅ 删话术锁; evidence-only directive |
| 准则 4 懂我 | ✅ MemoryHub 6 source 统一 |
| 准则 5 言出必行 | ✅✅✅ Lineage = 法理基础, claim 必能反向追溯 |
| 准则 6 三维耦合 | ✅ 数据进 SWM (M1); 行为弱耦合 (publish-only sentinel); 决策集中 (主脑 + IntentResolver) |
| 准则 6 4 问 (新模块 LineageTracer) | ✅ 全 Yes (§1.准则 6 4 问) |
| 准则 6.5 (持久化 + CLI + Reflector) | ✅ lineage_config.json + lineage_dump.py + LineageReflector |
| 准则 7 Sir 元否决 | ✅ 本 doc 是提案, Sir 拍板才执行 |
| 准则 8 优雅 > 简单 | ✅ 5 套合 1 / 3 决策合 1 / god object 拆, 不留 hot-fix |

---

## 13. Phase B 完成 — 下一步

**Sir 拍板路径**:

1. **Sir 看完本 doc** → 给 Q1-Q4 决议
2. **Sir 真测验证** Phase A 6 doc + 本 Phase B 设计 是否匹配 Sir 心智模型
3. **Sir 拍板调整** (or accept) → 进 Phase C (Sir + Agent 共同细化)
4. **Phase C 完** → 进 Phase D-M1 (lineage trace 基础设施先做)

**等 Sir 拍板**.

---

*Phase B design 完成于 2026-05-24 00:30. 严格核对 Sir 8 准则, 等 Sir Q1-Q4 决议进 Phase C.*
