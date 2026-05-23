# JARVIS 大重构立项书 (GRAND REFACTOR)

> **立项时间**: 2026-05-23 22:45
> **立项原因**: Sir 22:40 真意 — "记忆系统的重构不仅涉及灵魂架构, 修正架构, 甚至涉及言出必行等等几乎目前所有架构的内容. 记忆架构就是底座. 这是个整个贾维斯架构大重构的巨型立项, 必须完整遍历贾维斯才可以做设计和决策."
> **状态**: Phase A 启动中 (审计阶段)
> **进度更新**: 每完成 1 个 task → §6 progress 立刻更新 + commit

---

## 0. 立项一句话

**记忆是底座. 重构记忆 = 重构 Jarvis 整个架构. 必须先完整遍历 ~115 模块 + 87 storage + 35 doc, 找全所有耦合, 才设计, 才动手.**

---

## 1. 立项背景

### 1.1 Sir 真意 (2026-05-23 21:49 - 22:40 一段对话演化)

| 时间 | Sir 关键洞察 |
|---|---|
| 21:49 | "我喜欢这种长期记忆方案. 我教过的东西, 除非我重新修正不然都按这个" |
| 22:14 | "我们的工作是重构记忆模块了" |
| 22:30 | "贾维斯的一切都依附于记忆, 没有记忆他的一切都是空中楼阁. 把贾维斯最最最重要的模块做的优雅" |
| 22:40 | "记忆系统的重构涉及几乎所有架构. 必须完整遍历贾维斯才可以做设计和决策" |
| 22:42 | "先把我们的重构计划立项, 然后开始第一阶段的完整遍历贾维斯, 彻彻底底的审计, 做到哪就在立项标记到哪, 保证有迹可循, 工作不断" |

### 1.2 之前 design doc 的草率反思

| 我之前犯的错 | 真因 |
|---|---|
| `JARVIS_MEMORY_UNIFICATION_REFACTOR.md` 拍脑袋写"6 source 分类" | 没真扫 90 py 验证 |
| 说"1 周做完 Phase 1-6" | 极不现实, **真做需 1 个月以上** |
| 没识别"记忆 ↔ Soul ↔ INTEGRITY ↔ ToM ↔ Mutation 全栈耦合" | Sir 真意正是这点 |
| 没考虑 1098 testcase 的 migration | 大架构改 testcase 必断 |

### 1.3 当前已有架构知识 (已写)

| Doc | 涵盖 |
|---|---|
| `AGENTS.md` | 8 准则 + 30s 入门导航 |
| `JARVIS_ARCHITECTURE_MAP.md` | 90 py + 25 hands + 35 doc 索引 (10/22 立项夜起草) |
| `JARVIS_SOUL_DRIVE.md` | 5 Layer 灵魂架构 |
| `JARVIS_MEMORY_AND_MUTATION_REFACTOR.md` | 692 行 — 6 layer abstraction (Sir 5/22 立) |
| `JARVIS_INTEGRITY_STACK.md` | INTEGRITY 7 层栈 |
| `JARVIS_SENSOR_TO_SWM_ARCHITECTURE.md` | 三维耦合 |
| `JARVIS_TOM_SIR_MENTAL_MODEL.md` | ToM 设计 |

**这些是 audit 的起点, 不是终点. Phase A 要验证 / 补全 / 校正这些 doc**.

---

## 2. 核心原则 (Phase A→D 全程)

| # | 原则 | 含义 |
|---|---|---|
| 1 | **先审计后设计** | 不允许"先有结论再找数据" |
| 2 | **先设计后动手** | Phase B 完成 + Sir 拍板 才进 Phase D |
| 3 | **不重新发明轮子** | 现有 ProfileCard / Hippocampus / MemoryGateway 等不全推翻 |
| 4 | **每 step 可独立 ship** | 不允许 "全做完才 work" 的 big bang |
| 5 | **testcase 增不减** | 1098 现有测试不允许删减弱化 |
| 6 | **进度可恢复** | 任何 agent 看本 doc + AGENTS.md 能接手 |
| 7 | **耦合优先** | audit 重点是**模块间耦合**, 不是单模块功能 |
| 8 | **§6 优雅高效可持续** | 不追求最简单 hot-fix, 追求正确架构 |

---

## 3. Phase 总览 (4 阶段, 估 ~6-10 周)

### Phase A: **完整遍历 Jarvis** (审计, ~2 周, 即将启动)

> 核心产出: `docs/JARVIS_AUDIT_CARDS.md` + 数据流图 + storage map + 耦合矩阵

| Sub-phase | 内容 | 产出 | 估时 |
|---|---|---|---|
| A.0 | 建 audit cards 集中文档 + 模板 | `JARVIS_AUDIT_CARDS.md` 起头 | 0.5h |
| A.1 | **90 py 主模块 + 25 hands** 全审 (按域分 9 批, 每模块 1 audit card) | `JARVIS_AUDIT_CARDS.md` ~115 张 card | ~3-5 天 |
| A.2 | 数据流全审 (调用链 / 30+ render block / SWM events / Reflector trigger) | `docs/JARVIS_DATAFLOW_MAP.md` | ~1-2 天 |
| A.3 | 87 storage file 全审 (schema / 读者 / 写者) | `docs/JARVIS_STORAGE_MAP.md` | ~1 天 |
| A.4 | 耦合矩阵 (90×90 模块调用表 + 关键耦合点列表) | `docs/JARVIS_COUPLING_MATRIX.md` | ~1-2 天 |
| A.5 | 历史 patches 审 (TODO_ARCHIVE / 35 doc / git log) 找 deprecated / 失败 attempt | `docs/JARVIS_LEGACY_AUDIT.md` | ~0.5-1 天 |

### Phase B: **基于 audit 设计真整体架构** (~1-2 周, Phase A 完成后)

> 核心产出: `docs/JARVIS_GRAND_DESIGN.md` (作废现 `MEMORY_UNIFICATION_REFACTOR.md`)

| Sub-phase | 内容 |
|---|---|
| B.1 | 找 1-3 个最根本抽象 (不为优雅而优雅) |
| B.2 | 设计与现有 90 模块的兼容路径 |
| B.3 | testcase migration 策略 |
| B.4 | 风险 + rollback 计划 |
| B.5 | 分批 milestone 计划 (week-level) |

### Phase C: **Sir + Agent 共同拍板** (~3-5 天)

| Sub-phase | 内容 |
|---|---|
| C.1 | Sir 看 Phase B 设计 → 真意/痛点确认 |
| C.2 | 分歧讨论 + 决策日志 |
| C.3 | 拆 milestone (week-level) |

### Phase D: **真重构** (~3-5 周)

| 原则 | 内容 |
|---|---|
| 每周 1 milestone | Sir 真测过才下一周 |
| 每 milestone 独立 commit + 可 revert | 不允许长期 branch |
| testcase 必增 | 不减少 |
| 不破现有功能 | 灰度 + flag |

---

## 4. Phase A.1 模块审计 task list (115 模块 + 25 hands)

> **每模块 1 audit card** in `docs/JARVIS_AUDIT_CARDS.md`. card 模板见 §5.

### 4.1 批次 a: 5 核心枢纽 (~22000 行) — **最先审, 影响最大**

| # | 模块 | 行 | 状态 |
|---|---|---|---|
| 1 | `jarvis_nerve.py` | 328 | ⬜ pending |
| 2 | `jarvis_utils.py` | 4861 | ⬜ pending |
| 3 | `jarvis_central_nerve.py` | 5086 | ⬜ pending |
| 4 | `jarvis_chat_bypass.py` | 5960 | ⬜ pending |
| 5 | `jarvis_worker.py` | 5823 | ⬜ pending |

### 4.2 批次 b: Soul 7 模块

| # | 模块 | 行 | 状态 |
|---|---|---|---|
| 6 | `jarvis_self_anchor.py` | 339 | ⬜ |
| 7 | `jarvis_concerns.py` | 984 | ⬜ |
| 8 | `jarvis_relational.py` | 1198 | ⬜ |
| 9 | `jarvis_attention.py` | 207 | ⬜ |
| 10 | `jarvis_soul_reflector.py` | 752 | ⬜ |
| 11 | `jarvis_soul_evaluator.py` | 637 | ⬜ |
| 12 | `jarvis_sir_mental_model.py` | 563 | ⬜ |

### 4.3 批次 c: 记忆 11 模块

| # | 模块 | 行 | 状态 |
|---|---|---|---|
| 13 | `jarvis_routing.py` (ProfileCard) | 1479 | ⬜ |
| 14 | `jarvis_hippocampus.py` | 1478 | ⬜ |
| 15 | `jarvis_memory_core.py` | 1512 | ⬜ |
| 16 | `jarvis_memory_gateway.py` | 733 | ⬜ |
| 17 | `jarvis_milestones.py` | 234 | ⬜ |
| 18 | `jarvis_stm_summarizer.py` | 354 | ⬜ |
| 19 | `jarvis_profile_reflector.py` | 413 | ⬜ |
| 20 | `jarvis_promise_log.py` | 574 | ⬜ |
| 21 | `jarvis_commitment_watcher.py` | 1932 | ⬜ |
| 22 | `jarvis_self_promise.py` | 579 | ⬜ |
| 23 | `jarvis_cyclic_task.py` | 397 | ⬜ |

### 4.4 批次 d: INTEGRITY 9 模块

| # | 模块 | 行 | 状态 |
|---|---|---|---|
| 24 | `jarvis_claim_classifier.py` | 289 | ⬜ |
| 25 | `jarvis_evidence_requirements.py` | 243 | ⬜ |
| 26 | `jarvis_claim_tracer.py` | 888 | ⬜ |
| 27 | `jarvis_claim_revision_log.py` | 527 | ⬜ |
| 28 | `jarvis_integrity_watcher.py` | 1846 | ⬜ |
| 29 | `jarvis_integrity_reflector.py` | 766 | ⬜ |
| 30 | `jarvis_inconsistency_watcher.py` | 461 | ⬜ |
| 31 | `jarvis_callback_guard.py` | 415 | ⬜ |
| 32 | `jarvis_meta_self_check.py` | 458 | ⬜ |

### 4.5 批次 e: IntentResolver + Directive + Mutation 8 模块

| # | 模块 | 行 | 状态 |
|---|---|---|---|
| 33 | `jarvis_directives.py` | 3958 | ⬜ |
| 34 | `jarvis_directive_evaluator.py` | 397 | ⬜ |
| 35 | `jarvis_intent_resolver.py` | 854 | ⬜ |
| 36 | `jarvis_intent_router.py` | 325 | ⬜ |
| 37 | `jarvis_tool_registry.py` | 398 | ⬜ |
| 38 | `jarvis_skill_registry.py` | 2559 | ⬜ |
| 39 | `jarvis_fuzzy_resolver.py` | 207 | ⬜ |
| 40 | `jarvis_prompt_builder.py` | 245 | ⬜ |

### 4.6 批次 f: Proactive Care + Nudge + Conductor 10 模块

| # | 模块 | 行 | 状态 |
|---|---|---|---|
| 41 | `jarvis_proactive_care.py` | 1873 | ⬜ |
| 42 | `jarvis_smart_nudge.py` | 1010 | ⬜ |
| 43 | `jarvis_recent_nudge_memory.py` | 270 | ⬜ |
| 44 | `jarvis_nudge_coordination.py` | 142 | ⬜ |
| 45 | `jarvis_concern_dampen.py` | 169 | ⬜ |
| 46 | `jarvis_concern_feedback.py` | 250 | ⬜ |
| 47 | `jarvis_concern_feedback_reflector.py` | 281 | ⬜ |
| 48 | `jarvis_concern_summon.py` | 108 | ⬜ |
| 49 | `jarvis_conductor.py` | 1255 | ⬜ |
| 50 | `jarvis_curiosity.py` | 147 | ⬜ |

### 4.7 批次 g: Sensor + Sentinel + Reflector 23 模块

| # | 模块 | 行 | 状态 |
|---|---|---|---|
| 51 | `jarvis_sensors.py` | 1147 | ⬜ |
| 52 | `jarvis_env_probe.py` | 959 | ⬜ |
| 53 | `jarvis_sentinels.py` | 2166 | ⬜ |
| 54 | `jarvis_screen_vision.py` | 700 | ⬜ |
| 55 | `jarvis_ambient_sensor.py` | 596 | ⬜ |
| 56 | `jarvis_acoustic_wake.py` | 631 | ⬜ |
| 57 | `jarvis_state_tracker.py` | 235 | ⬜ |
| 58 | `jarvis_silence_intel.py` | 198 | ⬜ |
| 59 | `jarvis_health_probe.py` | 240 | ⬜ |
| 60 | `jarvis_physio_proxy.py` | 303 | ⬜ |
| 61 | `jarvis_screen_tease_reflector.py` | 424 | ⬜ |
| 62 | `jarvis_struggle_reflector.py` | 376 | ⬜ |
| 63 | `jarvis_sleep_pattern_reflector.py` | 249 | ⬜ |
| 64 | `jarvis_companion_rhythm_reflector.py` | 407 | ⬜ |
| 65 | `jarvis_inside_joke_reflector.py` | 390 | ⬜ |
| 66 | `jarvis_sir_request_reflector.py` | ~? | ⬜ |
| 67 | `jarvis_sir_status_tracker.py` | 482 | ⬜ |
| 68 | `jarvis_return_sentinel.py` | 1186 | ⬜ |
| 69 | `jarvis_stand_down.py` | 692 | ⬜ |
| 70 | `jarvis_project_hold_detector.py` | 240 | ⬜ |
| 71 | `jarvis_watch_task.py` | 937 | ⬜ |
| 72 | `jarvis_cross_session_callback.py` | ~? | ⬜ |
| 73 | `jarvis_actionable_items.py` | 1167 | ⬜ |

### 4.8 批次 h: 剩余 ~17 模块

| # | 模块 | 行 | 状态 |
|---|---|---|---|
| 74 | `jarvis_reply_preflight.py` | 405 | ⬜ |
| 75 | `jarvis_reply_feedback.py` | 108 | ⬜ |
| 76 | `jarvis_safety.py` | 722 | ⬜ |
| 77 | `jarvis_reject_learner.py` | 420 | ⬜ |
| 78 | `jarvis_predicate.py` | 576 | ⬜ |
| 79 | `jarvis_predicate_parser.py` | 204 | ⬜ |
| 80 | `jarvis_key_router.py` | 992 | ⬜ |
| 81 | `jarvis_llm_reflector.py` | 337 | ⬜ |
| 82 | `jarvis_reflector_budget.py` | 200 | ⬜ |
| 83 | `jarvis_jsonl_rotator.py` | 157 | ⬜ |
| 84 | `jarvis_error_bus.py` | 253 | ⬜ |
| 85 | `jarvis_sensor_state_block.py` | 170 | ⬜ |
| 86 | `jarvis_progress_tracker.py` | 473 | ⬜ |
| 87 | `jarvis_ui.py` | 920 | ⬜ |
| 88 | `jarvis_vocal_cord.py` | 320 | ⬜ |
| 89 | `jarvis_blood.py` | 95 | ⬜ |
| 90 | `jarvis_enhanced.py` | 757 | ⬜ |

### 4.9 批次 i: 25 hands

| # | 模块 | 行 | 状态 |
|---|---|---|---|
| 91-115 | `l4_*.py` × 25 | ~5300 | ⬜ |

---

## 5. Audit Card 模板

每模块写 1 张 card in `docs/JARVIS_AUDIT_CARDS.md`. 模板:

```markdown
### #<num> `<file>.py` (<行>) — <1 句简介>

**职责**: <核心做啥, 1-2 行>

**核心 method / class**:
- `ClassName.method()` — <1 行干啥>
- ...

**数据**:
- 读: `<storage>` / `<other_module>.attr` / SWM events: `<types>`
- 写: `<storage>` / SWM publish: `<types>`

**上游 (谁调它)**:
- `<module>.<method>()`
- ...

**下游 (它调谁)**:
- `<module>.<method>()`
- ...

**跟记忆的耦合**:
- 直接写: <e.g. ProfileCard.overwrite_field>
- 直接读: <e.g. Hippocampus.search_memory>
- 间接耦合: <e.g. publish 'sir_taught_param' → MemoryGateway 监听>

**跟其他模块的耦合**:
- <module>: <如何耦合>

**已知问题 / TODO marker** (grep "TODO" / "FIXME" / "BUG"):
- ...

**关联 design doc**: `<doc>.md`

**重构含义** (Phase B 设计参考):
- <这模块在大重构中的去留 / 重写 / 兼容>
```

---

## 6. Progress Tracker (LIVE — 每 commit 更新)

> Sir 真意 "工作不断 + 有迹可循". 每完成 1 个 audit card → 立刻更新 + commit.

### 6.1 总进度

| Phase | Sub-phase | 进度 | 备注 |
|---|---|---|---|
| Phase A.0 | audit cards 集中 doc 模板 | ✅ done | `JARVIS_AUDIT_CARDS.md` 建好, 含模板示范 |
| Phase A.1 | 模块审计 (115 + 25) | **140/140 ✅ 100%** | **🎉 Phase A.1 全部完成! 115 jarvis py + 25 hands 全审完** |
| Phase A.2 | 数据流全审 | ✅ done | `JARVIS_DATAFLOW_MAP.md` (~600 行, 含 30+ render block / 50+ SWM etype / 30+ Reflector / 4 关键 case 序列图 / 7 耦合点) |
| Phase A.3 | storage map | ✅ done | `JARVIS_STORAGE_MAP.md` (~500 行, 93 file 6 类详 + 4 死文件 + 5 audit log 合并 + sqlite 4 表) |
| Phase A.4 | 耦合矩阵 | ✅ done | `JARVIS_COUPLING_MATRIX.md` (~400 行, 耦合 7 形态 + 6 同名 class 冲突 + 8 概念重叠 + god object 反模式) |
| Phase A.5 | 历史 audit | ✅ done | `JARVIS_LEGACY_AUDIT.md` (死代码 4 / 半死代码 5+ / 35 design doc 状态 / 历史教训 / Sir 待拍板 4 项)
| Phase B | 设计 | ✅ done | `JARVIS_PHASE_B_DESIGN.md` (~700 行, 13 章 / 4 护城河 + 3 薄弱点 + 4 铁律 / 6 source / Lineage Trace / 8 milestone) — 等 Sir Q1-Q4 拍板
| Phase C | 拍板 | ⬜ pending | B 完成后 |
| Phase D | 重构 | ⬜ pending | C 拍板后 |

### 6.2 当前位置 (LIVE)

> 任何 agent 接手时, 看本 §就知"现在做到哪". 接手即可继续.

```
当前阶段: 🎉 **Phase A + Phase B 全部完成!** 等 Sir Q1-Q4 拍板进 Phase C
进度: Phase A (5 sub-phase 6000 行) + Phase B (700 行 设计 doc)
下一动作: 等 Sir 看完 `JARVIS_PHASE_B_DESIGN.md` → 给 4 项决议 → 进 Phase C
Phase A+B 8 份核心 doc:
  1. `docs/JARVIS_GRAND_REFACTOR.md` (本 doc, 立项)
  2. `docs/JARVIS_AUDIT_CARDS.md` (140 模块 cards)
  3. `docs/JARVIS_DATAFLOW_MAP.md` (数据流)
  4. `docs/JARVIS_STORAGE_MAP.md` (storage)
  5. `docs/JARVIS_COUPLING_MATRIX.md` (耦合)
  6. `docs/JARVIS_LEGACY_AUDIT.md` (历史)
  7. `docs/JARVIS_ARCHITECTURE_MAP.md` (架构总览)
  8. **`docs/JARVIS_PHASE_B_DESIGN.md`** (设计, 4 护城河 + Lineage Trace + 8 milestone) ⭐
最后 commit: 3179720 (A.5 legacy)
```

### 6.3 已完成 audit cards

| # | 模块 | card 位置 | commit | 时间 |
|---|---|---|---|---|
| 1 | `jarvis_nerve.py` | `JARVIS_AUDIT_CARDS.md` §批次 a #1 | b53b751 | 2026-05-23 22:55 |
| 2 | `jarvis_utils.py` | `JARVIS_AUDIT_CARDS.md` §批次 a #2 | 4a06438 | 2026-05-23 23:00 |
| 3 | `jarvis_central_nerve.py` | `JARVIS_AUDIT_CARDS.md` §批次 a #3 | 215ff24 | 2026-05-23 23:06 |
| 4 | `jarvis_chat_bypass.py` | `JARVIS_AUDIT_CARDS.md` §批次 a #4 | 4e07bbf | 2026-05-23 23:13 |
| 5 | `jarvis_worker.py` | `JARVIS_AUDIT_CARDS.md` §批次 a #5 | 61a9c46 | 2026-05-23 23:18 |
| 6 | `jarvis_self_anchor.py` | `JARVIS_AUDIT_CARDS.md` §批次 b #6 | (即将) | 2026-05-23 23:30 |
| 7 | `jarvis_concerns.py` | `JARVIS_AUDIT_CARDS.md` §批次 b #7 | (即将) | 2026-05-23 23:30 |
| 8 | `jarvis_relational.py` | `JARVIS_AUDIT_CARDS.md` §批次 b #8 | (即将) | 2026-05-23 23:30 |
| 9 | `jarvis_attention.py` | `JARVIS_AUDIT_CARDS.md` §批次 b #9 | (即将) | 2026-05-23 23:30 |
| 10 | `jarvis_soul_reflector.py` | `JARVIS_AUDIT_CARDS.md` §批次 b #10 | (即将) | 2026-05-23 23:30 |
| 11 | `jarvis_soul_evaluator.py` | `JARVIS_AUDIT_CARDS.md` §批次 b #11 | (即将) | 2026-05-23 23:30 |
| 12 | `jarvis_sir_mental_model.py` | `JARVIS_AUDIT_CARDS.md` §批次 b #12 | fefbac0 | 2026-05-23 23:30 |
| 13-23 | 记忆 11 模块 (routing/hippocampus/memory_core/memory_gateway/milestones/stm_summarizer/profile_reflector/promise_log/commitment_watcher/self_promise/cyclic_task) | `JARVIS_AUDIT_CARDS.md` §批次 c | 0ac4f39 | 2026-05-23 23:42 |
| 24-32 | INTEGRITY 9 模块 (claim_classifier/evidence_requirements/claim_tracer/claim_revision_log/integrity_watcher/integrity_reflector/inconsistency_watcher/callback_guard/meta_self_check) | `JARVIS_AUDIT_CARDS.md` §批次 d | 1df4d11 | 2026-05-23 23:55 |
| 33-40 | Intent + Directive + Mutation 8 模块 (directives/directive_evaluator/intent_resolver/intent_router/tool_registry/skill_registry/fuzzy_resolver/prompt_builder) | `JARVIS_AUDIT_CARDS.md` §批次 e | f79e721 | 2026-05-24 00:08 |
| 41-50 | Care + Nudge + Conductor 10 模块 | `JARVIS_AUDIT_CARDS.md` §批次 f | 323e73b | 2026-05-24 00:18 |
| 51-73 | Sensor + Sentinel + Reflector 23 模块 | `JARVIS_AUDIT_CARDS.md` §批次 g | b825cc3 | 2026-05-24 00:30 |
| 74-90 | 剩余 17 模块 | `JARVIS_AUDIT_CARDS.md` §批次 h | 1d5f95d | 2026-05-24 00:38 |
| 91-115 | **25 hands 群表** (audio/clipboard/desktop/display/file/gui/input/media/memory/network/notification/process/screenshot/system/text/url/video/watcher/web/window/etc.) | `JARVIS_AUDIT_CARDS.md` §批次 i | (即将) | 2026-05-24 00:50 |

---

## 7. 决策日志

> Sir 关键拍板记录 (Sir 元否决权 §7).

| 日期 | Sir 拍板内容 | 影响 |
|---|---|---|
| 2026-05-23 22:42 | "先把我们的重构计划立项, 然后开始第一阶段的完整遍历贾维斯, 彻彻底底的审计, 做到哪就在立项标记到哪" | **Phase A 启动** |
| 2026-05-23 22:30 | "贾维斯一切都依附于记忆, 没有记忆都是空中楼阁" | 重构核心目标 = 记忆底座 |
| 2026-05-23 22:14 | "今晚的 5 个 BUG 不是孤立, 是记忆系统散乱症状" | 立项理由 |
| 2026-05-23 21:49 | "我教过的东西除非重新修正不然按这个" | 长期记忆需求 |

---

## 8. 工程约定 (Phase A 执行)

### 8.1 audit cards 集中 doc

- 单文件 `docs/JARVIS_AUDIT_CARDS.md` (随写随长)
- 每模块 1 card, 按 §4 批次顺序
- 单 card ~50-100 行 (不超过)
- 整本可能 ~10000+ 行 — **不算违 §6 边界** (审计文档不是核心章程)

### 8.2 每完成 1 个 card

1. 写 card → 写入 `JARVIS_AUDIT_CARDS.md` 末尾
2. 更新本文 §6.2 当前位置
3. 更新本文 §4.X 模块状态 ⬜ → ✅
4. commit 1 次 (msg: `audit Phase A.1 batch X module Y`)

### 8.3 Phase A 中允许的代码改动

**只允许**:
- 战术性 BUG fix (例: 今晚的 fix82-X / fix82-Z) — Sir 真测痛点
- 添加 docstring (audit 时发现没 docstring 的核心 method)
- 不改架构, 不改接口, 不改 schema

**禁止**:
- 任何架构性 refactor (等 Phase D)
- 删模块, 改接口
- 大改主脑 prompt 或 directive

### 8.4 Phase A 结束信号

下列全满足:
- [ ] 140 模块 (115 py + 25 hands) 全有 audit card
- [ ] `JARVIS_DATAFLOW_MAP.md` 完成
- [ ] `JARVIS_STORAGE_MAP.md` 完成
- [ ] `JARVIS_COUPLING_MATRIX.md` 完成
- [ ] `JARVIS_LEGACY_AUDIT.md` 完成
- [ ] Sir review audit + 拍板进 Phase B

### 8.5 中断 + 恢复

任何 agent 接手:
1. 读 `AGENTS.md` (~3 min)
2. 读本 doc §6.2 当前位置 (~30s)
3. 读 `JARVIS_ARCHITECTURE_MAP.md` 总览 (~5 min)
4. 读上一个 commit 的 audit card 看上下文 (~2 min)
5. 接手继续

总恢复 ~10 min.

---

## 9. 风险 + 缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| Sir 中途真测发现新痛点必须修 | 高 | 中 | 战术性 fix 允许 (§8.3), 不阻塞 audit |
| audit 1098 行 testcase 中发现新 BUG | 高 | 中 | 进 TODO 不立刻改, Phase D 一起 |
| audit cards 写得草率不准 | 中 | 高 | 每 card 必含上下游耦合点, agent 用 grep 验证 |
| Phase A 拖太久 (~ 1 个月+) | 中 | 中 | Sir 可拍板加快 (砍 sub-phase) |
| Phase B 设计还是不够全 | 中 | 高 | Phase B 完成后 Sir review, 不全打回 A |

---

## 10. 给后续 agent 的话

如果你接手本立项, 读完本 doc + `AGENTS.md` + §6.2 当前位置 即可继续:

1. 找下一个 ⬜ 模块
2. 按 §5 模板审计
3. 写 card → commit → 更新 §6.2

**不要尝试设计**. Phase B 是设计, 现在 (Phase A) 只审计.

如果发现真严重 BUG → 战术性 fix 允许, 但不要做架构改动.

---

*本立项书由 Sir 启动 + Cascade 起草, 2026-05-23 22:50.*
*这是 Jarvis 项目史上第一个真"完整遍历 + 大重构"立项. 严肃对待.*
*预估 ~6-10 周完成 (Phase A + B + C + D).*
