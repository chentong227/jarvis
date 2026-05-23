# JARVIS Legacy Audit (Phase A.5)

> 查 deprecated / 失败 attempt / 历史脱节. 完成 Phase A 最后阶段.

## 1. 真死代码 — 应删

| # | 项 | 处理 |
|---|---|---|
| 1 | `_archive_promise_log_2026_05_18.json.bak` (0 KB) | 删 |
| 2 | `pending_callbacks.jsonl` (0 KB) | 删 |
| 3 | `plans.json` (0 KB) — PlanLedger 未真持久化 | 删 / 启用 |
| 4 | `integrity_audit.jsonl.tainted-184101.bak` | 删 |
| 5 | `central_nerve.py:345-347` `self.eyes / hands / env = None` | 删 |
| 6 | `memory_core.TaskWorkerPool` (注释 "C1-3 死代码清扫", 实例不再创建) | 删 class |
| 7 | `safety.execute_memory_updates` (老 MEMORY_UPDATE) — β.2.9.9 起转新路径 | 标 deprecated |
| 8 | `nerve.py:73-74` 硬编码 HTTP_PROXY=127.0.0.1:7890 | 移到 config |

## 2. 半死代码 — 老 vs 新并存

| 老 | 新 | Phase B 决议 |
|---|---|---|
| `ProfileCard.apply_correction` (audit only) | `ProfileCard.overwrite_field` (真改 + audit) | 老路径下线 |
| `UnifiedMemoryGateway` (memory_core:515) | `MemoryMutationGateway` (memory_gateway:97) | 合并为 `MemoryHub`, 老删 |
| `Conductor` + `IntentResolver` + `chat_bypass FAST_CALL` | (3 套决策路径) | 留 1 套 |
| `add_reminder` 3 路径 (l4_memory_hands / tool_commitment_register / Gatekeeper) | (3 套) | 合并到 `MemoryHub.write_commitment` |
| `HumorMemory` (memory_core) | `RelationalState.inside_jokes` (β.2.2) | 迁到 RelationalState |
| `CorrectionMemory` (sqlite) | `mutation_receipts.jsonl` (新) | 老删 |

## 3. 待 Sir 确认 (不是 deprecated, 但需决定)

| 项 | 现状 | Sir 决议 |
|---|---|---|
| `jarvis_enhanced.py` (758 行 4 class) | `ProactiveShield` 真用 (`routing.py:1166` CompanionCenter), `SkillTreeTracker` 真用 (`central_nerve:1201`), `ProactiveCompanion` 真用 — **保留** | 拆 4 class 各独立 file |
| 3-brain (`RightBrain/LeftBrain/ReflectionBrain`) | 实例化 `central_nerve:312-314`, 但实际用途不明 — 需 grep usage | Sir 决定: 真用 / 占位 |
| `central_nerve.memory_gateway = UnifiedMemoryGateway` | 老路径 attr 仍持有 — 但 mutation 实际走新 MemoryMutationGateway | 改用新 |
| `cross_session_callback` | `pending_callbacks.jsonl` 0 KB 似乎未真用 | 启用 / 删 |

## 4. Design doc 状态分类 (35 个)

### 4.1 章程 + 已实现稳定 (15)
`AGENTS.md` / `WORKFLOW_PROTOCOL` / `PYTHON_STYLE` / `INTEGRITY_STACK` / `SOUL_DRIVE` / `SENSOR_TO_SWM` / `TOM_SIR_MENTAL` / `VISION_INTEGRATION` / `REJECT_LEARNER_L8` / `REPLY_PREFLIGHT` / `PREDICATE_COMMITMENT` / `DIRECTIVE_SELF_AWARENESS` / `PROACTIVE_CARE_ENGINE` / `INTENT_RESOLVER_REFACTOR` / `MUTATION_INTERFACE`

### 4.2 部分实现, 待 Phase D 完成 (5)
`NERVE_SPLIT_PLAN` (~10%) / `PROMPT_REFACTOR_PLAN` (~30%) / `MEMORY_AND_MUTATION_REFACTOR` (~80%) / `MEMORY_UNIFICATION_REFACTOR` (今晚草率, **作废**, 被 Phase A 替代) / `PROACTIVITY_NEXT`

### 4.3 历史快照保留 (10)
`AGENTS_GAP_ANALYSIS_2026_05_20` / `DEEP_AUDIT_2026_05_20` / `FOUNDATION_AUDIT_2026_05_17` / `ARCHITECTURE_AUDIT_2026_05_16` / `P5_FINAL_REPORT_2026_05_21` / `SYSTEM_BLIND_SPOTS_*` / `SOUL_FULL_ABLATION_*` / `SOUL_QUICK_VALIDATION_*` / `MEMORY_REFACTOR.md` (老 7KB 版, 已被 692 行版替代 — 标 `_legacy/`)

### 4.4 子项目 + 远景 + Agent handoff (8)
`BASIC_ELECTRONICS_PLAN` / `FUTURE_VISION_DESKTOP_COPILOT` / `DASHBOARD_*` / `PERSONA_EVOLUTION` / `SOUL_UNIVERSALIZATION` / `TEASE_AND_TOOL_CHANNEL` / `VOICE_PIPELINE_LATENCY` / `AGENT_*`

### 4.5 Phase A 新建 (今晚 7 个 ⭐)
`GRAND_REFACTOR` / `AUDIT_CARDS` / `DATAFLOW_MAP` / `STORAGE_MAP` / `COUPLING_MATRIX` / `LEGACY_AUDIT` (本 doc) / `ARCHITECTURE_MAP`

## 5. 历史 patches 主要教训

### 5.1 已成功落地 (大版本)
- **β.2.x Soul** Layer 0-5 ⭐
- **β.4.x** Acoustic Wake + STM 持久化
- **β.5.0-A** SWM 三维耦合 ⭐⭐⭐
- **β.5.0-B** reaction_space (silence/voice/silent_text/visual_pulse/tool_call)
- **β.5.36-44** publish-only sentinel + IntentResolver
- **β.5.46** watch_task / project_hold / behavior_inference
- **P0+18-19** nerve.py 拆 16 file (但 5 大单 file 仍 5K+ 行)
- **P2-Gap7** MemoryMutationGateway ⭐⭐ (Phase D 演化 MemoryHub)
- **P5-fix32-78** 各种 bug fix + vocab 持久化
- **P5-fix81-82** 今晚 fix (overwrite_field 嵌套 / cursor 红圈 / cascade completion / Gatekeeper skip)

### 5.2 已尝试但跳过
- `[SIR NOW]` 复合 block 替 6 sensor block — 大重构易破回归, Sir 真测保稳定
- Promise + CW + notes_for_self 三合一 — 需 data migration
- `attention.adjust` / `screen_vision.annotate` mutation organ — 优先级低
- NERVE_SPLIT (拆 chat_bypass + central_nerve + worker) — Phase D 待做
- PROMPT_REFACTOR (PromptBuilder 全迁) — 部分迁
- ProfileReflector 24h tick (fix81 改 5min, 默认未启)

### 5.3 失败 attempt (Sir 真测打回)
- **β.2.7.x 硬决策 sentinel** — Sir "硬决策不行" → β.5.0 改 publish-only
- **β.2.9.x 话术锁** — Sir "感觉是模板" → P5-fix79-80 删 12 处话术锁 (今晚)
- **早期 vocab patterns** — 反复 propose 调整 (预期, vocab 持续演化)

## 6. 历史教训 — Phase B 应避免

1. **演化 vs 重写** — P2-Gap7 演化为 MemoryHub, 别另起炉灶
2. **分批 vs 一次性** — NERVE_SPLIT 1 次拆 5 个 5K+ file 没做, Phase D 1 周 1 file
3. **vocab 持久化** — 部分 hardcoded (DEFAULT_TTL / _local_phrase_pool / 11 类 nudge) 待迁
4. **silent except** — 30+ `except Exception: pass` 掩盖启动失败, 应统一 health check
5. **god object** — CentralNerve / chat_bypass / worker 历史已知, 没解决
6. **同名 class** — 6+ 处必清
7. **0 docstring 大文件** — utils 4861 / hippocampus 1479 / 25 hands 全无 docstring — Phase D 必补

## 7. Phase A 完成总结

**Phase A 全部 ✅** (~6000 行 audit 文档):

| Sub-phase | 产出 | 行 |
|---|---|---|
| A.0 | `AUDIT_CARDS.md` 模板 | (集中) |
| A.1 | 140 模块审计 | ~3300 |
| A.2 | `DATAFLOW_MAP.md` | ~600 |
| A.3 | `STORAGE_MAP.md` | ~500 |
| A.4 | `COUPLING_MATRIX.md` | ~400 |
| A.5 | `LEGACY_AUDIT.md` (本) | ~150 |

**关键发现 → Phase B 设计输入**:
1. 6+ 同名 class 命名空间冲突 → 必清
2. 5 套时间承诺系统 → 必合并
3. 3 套决策路径 → 必整合
4. 4 套 mutation 路径 → 单 MemoryHub.write 入口
5. 5 audit log → 1 mem_audit.jsonl
6. 4 死文件 → 删
7. god object → 必拆
8. SWM 优秀解耦但跨 session 不持久化
9. **MemoryMutationGateway 已 80% MemoryHub** → 演化非重写
10. 30+ Reflector → ReflectorBudget 集中调度

**Phase B 启动条件**: Sir 看完 Phase A 7 doc → 拍板设计方向.

---

*Phase A.5 完成于 2026-05-24 00:15. Phase A 全部完成 ✅.*
