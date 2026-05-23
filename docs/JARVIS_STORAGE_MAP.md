# JARVIS Storage Map (Phase A.3 of Grand Refactor)

> 87+ storage file 完整 schema + reader/writer 索引. 配合 `JARVIS_AUDIT_CARDS.md` + `JARVIS_DATAFLOW_MAP.md`.
>
> 写于 2026-05-23 23:50, Phase A.3.

---

## 1. 总览 — storage 6 大类

| 类别 | 数量 | 示例 | 持久化策略 |
|---|---|---|---|
| **核心 Source of Truth** | ~10 | `sir_profile.json` / `concerns.json` / `relational_state.json` / `jarvis_memory.db` | atomic write, 单源 |
| **Vocab (准则 6 持久化)** | ~40 | `concern_keywords_vocab.json` / `behavior_inference_vocab.json` / etc. | atomic + L7 propose |
| **Audit log (jsonl append-only)** | ~10 | `mutation_receipts.jsonl` / `profile_corrections.jsonl` / `integrity_audit.jsonl` | append-only |
| **State snapshot** | ~10 | `sir_status.json` / `stand_down_state.json` / `key_router_state.json` | atomic write |
| **Cooldown / config** | ~10 | `reflector_budget_config.json` / `proactive_care_cooldown_vocab.json` | atomic write |
| **History rolling jsonl** | ~10 | `screen_history.jsonl` / `stm_recent.jsonl` / `recent_nudges.jsonl` | append + rotate / tail keep |
| **Static asset** | ~5 | `jarvis_v1.onnx` / `jarvis_v1.tflite` / `jarvis_prompt.wav` / `README.md` | 静态 |
| **Database** | 2 | `jarvis_memory.db` (4 表) / `skill_tree.db` | sqlite |

---

## 2. 核心 Source of Truth 详 (10 个)

| # | 文件 | 大小 | Schema | Writer | Reader | 跟 Memory 6 layer |
|---|---|---:|---|---|---|---|
| 1 | `jarvis_config/sir_profile.json` | (config) | dict — biographic / preferences / unit_preferences / work_rhythms / health_targets / active_projects / lifetime / etc. | ProfileCard.overwrite_field (新) + 老 apply_correction (audit only) | _assemble_prompt (block #9) + SelfAnchor + WeeklyReflector | **A Identity** ⭐ 核心 |
| 2 | `memory_pool/jarvis_memory.db` | 7756 KB | sqlite 4 表: TaskMemories / Commitments / ProjectTimeline / CorrectionMemory | Hippocampus.seal_memory + add_commitment_row + add_completed_event | Hippocampus.search_memory + list_recent_completed_events | **B Events + C 长期事实 + Layer E Commitments** ⭐⭐⭐ |
| 3 | `memory_pool/concerns.json` | 33.2 KB | `{concerns: [Concern{id, what_i_watch, severity, state, recent_signals, ...}]}` | ConcernsLedger.record_signal + dismiss + update_concern_field | _assemble_prompt (soul block) + ProactiveCare + Reflector | **D Belief / Concerns** ⭐⭐ |
| 4 | `memory_pool/relational_state.json` | 27.6 KB | `{inside_jokes / unspoken_protocols / unfinished_business / shared_history_threads}` | RelationalState.record_* + update_field + archive_* | _assemble_prompt (relational block) + InsideJokeReflector | **F Relations** ⭐⭐ |
| 5 | `memory_pool/sir_status.json` | 3 KB | dict — sleeping / online / AFK / focus / mood | SirStatusStore.update | _assemble_prompt + ProactiveCare + ReturnSentinel | **E State** ⭐ |
| 6 | `memory_pool/sir_milestones.json` | 2.4 KB | dict — Sir 终生重要事件 | jarvis_milestones.add | _assemble_prompt (milestones block) | **A Identity** 子 source ⭐ |
| 7 | `memory_pool/jarvis_promise_log.json` | 45.5 KB | `{promises: [Promise{id, kind, description, deadline, state, ...}]}` | PromiseLog.register + mark_fulfilled + mark_cancelled | ClaimTracer + try_pair_evidence | **E Commitments** (Jarvis 自承诺) ⭐⭐ |
| 8 | `memory_pool/sir_mental_state.json` | (待查) | SirMentalState dataclass — current_task / surface_need / deep_need / unspoken_need / mood / relational_temperature | SirMentalStateStore.update_state + ToMReflector | _assemble_prompt (ToM block) | **E State** (LLM 推断 — 区别 sir_status sensor) |
| 9 | `memory_pool/plans.json` | 0 KB | (空, 未启用?) PlanLedger 5 态状态机 | PlanLedger.persist | PlanLedger.load + PromiseExecutor | **E** (待审是否真用) |
| 10 | `memory_pool/watch_tasks.json` | 6.1 KB | watch task list | WatchTaskRegistrar | watch_task daemon + WatchTaskJudge | **E** (主动等的事件) ⭐ |

---

## 3. Vocab (~40, 准则 6 持久化范式)

> 每 vocab 配 `scripts/<name>_dump.py` CLI + L7 Reflector LLM-propose. 是 Sir 准则 6.5 持久化模范.

### 3.1 主脑认知 vocab

| 文件 | 大小 | 用途 | 反思器 |
|---|---:|---|---|
| `directives_vocab.json` | 26.3 KB | 130+ directive 词条 (text + trigger 字符串) | DirectiveEvaluator |
| `directive_registry.json` | 13.7 KB | directive 持久化 (id / counter / last_fired) | DirectiveRegistry.start_decay_worker |
| `directive_inject_config.json` | 1.1 KB | inject 上限 / family 优先级 | (config) |
| `directive_review.json` | 2.3 KB | 低分 directive 待 Sir review | DirectiveEvaluator |
| `claim_classify_vocab.json` | 5.1 KB | claim 分类 patterns | (vocab loader) |
| `evidence_requirements.json` | 4.6 KB | 各 claim kind 应有什么 evidence | (vocab loader) |
| `integrity_claim_vocab.json` | 4.3 KB | INTEGRITY claim verb / pattern | IntegrityWatcher |
| `integrity_suspicious_kw.json` | 0.8 KB | 可疑 claim 关键词 | IntegrityWatcher |
| `forbidden_callback_vocab.json` | 3.2 KB | unsolicited callback forbidden 短语 | CallbackGuard |
| `inconsistency_vocab.json` | 3.7 KB | Sir 真行为 vs 承诺 不一致 patterns | InconsistencyWatcher |
| `predicate_keywords.json` | 1.7 KB | predicate 关键词 (谓词驱动 commitment) | PredicateParser |

### 3.2 Concern + Memory + Mutation vocab

| 文件 | 大小 | 用途 | 反思器 |
|---|---:|---|---|
| `concern_keywords_vocab.json` | 10 KB | concern 触发关键词 | ConcernsReflector |
| `concern_dismiss_vocab.json` | 0.8 KB | Sir "别再提" 关键词 | (vocab loader) |
| `concern_summon_vocab.json` | 2.5 KB | Sir 主动召唤 concern 关键词 | (vocab loader) |
| `_base_correction_vocab.json` | 1.1 KB | 基础 correction 短语 | (vocab loader) |
| `_base_dismiss_vocab.json` | 0.8 KB | 基础 dismiss 短语 | (vocab loader) |
| `memory_correction_vocab.json` | 1.3 KB | 记忆纠正 patterns | MemoryCorrectionGuard |
| `memory_deletion_vocab.json` | 2.4 KB | 记忆删除 patterns | safety._is_*_delete_intent |
| `correction_dispatcher_vocab.json` | 1 KB | correction → mutation organ 路由 | (vocab loader) |
| `commitment_conditional_vocab.json` | 1.5 KB | commitment 条件触发 | CommitmentWatcher |
| **`completion_event_vocab.json`** | 1 KB | **fix82-X**: 完成语义 keywords + noun_extract | MemoryGateway.cascade_completion |
| `cyclic_task_dispatcher_vocab.json` | 1 KB | cyclic_task organ 调度 | (vocab loader) |
| `progress_tracker_dispatcher_vocab.json` | 1.1 KB | progress organ 调度 | (vocab loader) |
| `behavior_inference_vocab.json` | 1.9 KB | commitment 行为推断 (β.5.46-fix13) | CommitmentWatcher |
| `feedback_vocab.json` | 4 KB | feedback patterns | FeedbackTracker |
| `mic_safety_vocab.json` | 1.8 KB | mic safety patterns | (vocab loader) |
| `mutation_receipts.jsonl` | 12.4 KB | mutation audit (jsonl) | MemoryGateway._write_receipt |

### 3.3 Sir 行为 + Sleep + Nudge vocab

| 文件 | 大小 | 用途 | 反思器 |
|---|---:|---|---|
| `sir_struggle_vocab.json` | 3.2 KB | Sir 困难关键词 | StruggleReflector |
| `sir_sleep_pattern_vocab.json` | 1.4 KB | Sir 睡眠 pattern | SleepPatternReflector |
| `sir_status_vocab.json` | 4 KB | sir_status 标志词 | (vocab loader) |
| `sleep_cancel_vocab.json` | 1.2 KB | Sir 取消 sleep 关键词 | (vocab loader) |
| `wake_filler_vocab.json` | 0.9 KB | wake filler 短语 | (vocab loader) |
| `proactive_care_cooldown_vocab.json` | 1.3 KB | nudge cooldown 配置 | ProactiveCare |
| `nudge_window_vocab.json` | 1.5 KB | nudge timing 时段 | CompanionRhythmReflector |
| `severity_decay_vocab.json` | 1.5 KB | severity decay 配置 | (vocab loader) |
| `screen_tease_vocab.json` | 2.9 KB | 屏幕笑点 | ScreenTeaseReflector |
| `sensor_state_inject_vocab.json` | 5.6 KB | SENSOR STATE block patterns | (vocab loader) |
| `thinking_pause_vocab.json` | 2.1 KB | Sir 思考停顿模式 | SilenceIntel |
| `project_hold_phrases_vocab.json` | 4.4 KB | "不要管 X 项目" patterns | ProjectHoldDetector |
| `refusal_vocab.json` | 3 KB | Sir 拒绝模式 | (vocab loader) |
| `promise_soft_vocab.json` | 2.8 KB | soft promise patterns | SelfPromiseDetector |
| `gate_mode_vocab.json` | 2.8 KB | sentinel hard/soft/publish_only mode | (vocab loader) |
| `audio_ducking_targets.json` | 2 KB | audio ducking 目标 app | (config) |
| `intent_fast_path_vocab.json` | 4.2 KB | intent fast path | IntentResolver |
| `intent_to_tool_map.json` | 5.7 KB | intent → tool 路由 | IntentResolver / IntentRouter |
| `tool_intent_vocab.json` | 2.6 KB | tool intent patterns | (vocab loader) |
| `dashboard_intent_vocab.json` | 2 KB | dashboard intent patterns | (dashboard) |
| `response_classify_vocab.json` | 2.7 KB | reply classify patterns | (vocab loader) |
| `ambient_sensor_config.json` | 1.5 KB | ambient sensor 配置 | AmbientSensor |

### 3.4 Reflector + Config

| 文件 | 大小 | 用途 |
|---|---:|---|
| `reflector_budget_config.json` | 1.1 KB | LLM cost 控制 |
| `hippocampus_decay_config.json` | 1.1 KB | Hippocampus decay 配置 |
| `stm_summarize_config.json` | 1.4 KB | STM 概括开关 + cache 大小 |
| `reject_learner_config.json` | 1.2 KB | RejectLearner 配置 |
| `watch_task_config.json` | 2.3 KB | WatchTask 配置 |

---

## 4. Audit log (jsonl, 10 个)

> 大部分是 append-only. **重叠**: 5 个 jsonl 都跟 mutation/claim 有关 — Phase B 应合并.

| 文件 | 大小 | Writer | Reader | 用途 | 重叠? |
|---|---:|---|---|---|---|
| **`mutation_receipts.jsonl`** | 12.4 KB | MemoryGateway._write_receipt | ClaimTracer + dashboard | mutation 真改 audit | ⭐ 主 audit |
| **`profile_corrections.jsonl`** | 48.4 KB | ProfileCard._persist_correction_to_disk + execute_memory_updates (老路) | ProfileReflector + dashboard | profile correction 历史 | ⚠️ 重叠 mutation_receipts |
| `claim_revisions.json` | 24.6 KB | ClaimRevisionStore.append | dashboard | functional revision (区别 ritual) | ⚠️ 重叠 mutation_receipts |
| `claim_stats.json` | 0.2 KB | ClaimStatsDumper (1d tick) | IntegrityReflector | claim 统计 | ⚠️ 重叠 |
| `integrity_audit.jsonl` | 7.2 KB | IntegrityWatcher | IntegrityReflector + dashboard | INTEGRITY verify 历史 | ⚠️ 重叠 |
| `main_brain_meta_audit.jsonl` | 38.2 KB | MetaSelfCheck.publish_meta | dashboard | META block 自评 audit | 独立 |
| `intent_resolver_telemetry.json` | 0.7 KB | IntentResolver.log | dashboard + _assemble_prompt | IR tool 调用 audit | 独立 |
| `preflight_stats.jsonl` | 126.9 KB | PreFlight.log | dashboard | reply preflight stats | 独立 |
| `key_router_reset_audit.jsonl` | 0.4 KB | KeyRouter.reset_audit | dashboard | key reset 历史 | 独立 |
| `system_errors.jsonl` | 30.5 KB | ErrorBus.publish_to_jsonl | _assemble_prompt (block) | 模块错误暴露 | 独立 |
| `stand_down_history.jsonl` | 1.1 KB | StandDownState.log | dashboard | StandDown 历史 | 独立 |
| `jarvis_health_history.jsonl` | 281.9 KB | HealthProbeDaemon | dashboard | Jarvis 自检历史 | 独立 |
| `mutation_dump.jsonl` | (无) | mutation_dump.py CLI | (CLI 输出) | dump 工具临时 | (CLI gen) |
| `item_feedback.jsonl` | 1.9 KB | ContentPreferenceTracker | (tracker) | 内容偏好反馈 | 独立 |

**Phase B 必合并**: `mutation_receipts.jsonl` + `profile_corrections.jsonl` + `claim_revisions.json` + `claim_stats.json` + `integrity_audit.jsonl` → 1 个统一 `mem_audit.jsonl`.

---

## 5. State snapshot (10+, 重启恢复用)

| 文件 | 大小 | Writer | Reader | 用途 |
|---|---:|---|---|---|
| `stand_down_state.json` | 0.4 KB | StandDownState.persist | _assemble_prompt + hotkey | Stand Down 当前状态 |
| `sir_acked_state.json` | 0.1 KB | (sir acked tracker) | (待审是否用) | Sir ack 状态 |
| `screen_snapshot.json` | 0.8 KB | ScreenVisionEngine.persist | _assemble_prompt | latest 1 帧 vision |
| `key_router_state.json` | 0 KB | KeyRouter.persist (state — 0 KB 似乎未真持久化) | KeyRouter | API key 状态 |
| `key_router_health.json` | 3.8 KB | KeyRouter.health_persist | KeyRouter + dashboard | key 健康监控 |
| `key_router_reset_request.json` | 0.4 KB | KeyRouter.reset_request | (manual) | 手动 reset 请求 |
| `intent_resolver_telemetry.json` | (audit 类, 见 §4) | | | |
| `integrity_watcher.json` | 163.5 KB | IntegrityWatcherStore | _assemble_prompt | INTEGRITY 状态 (大) |
| `cross_session_callback.json` | 0.9 KB | CrossSessionCallbackStore | _assemble_prompt | 跨 session 心结 |
| `concerns_review.json` | 0 KB | ConcernsReflector.propose | (Sir CLI activate) | concerns 待审 (空) |
| `relational_review.json` | 1.4 KB | InsideJokeReflector.propose | (Sir CLI) | relational 待审 |
| `directive_review.json` | 2.3 KB | DirectiveEvaluator.propose | (Sir CLI) | directive 待审 |
| `profile_review.json` | (待查) | ProfileReflector.propose | (Sir CLI) | profile 待审 |

---

## 6. History rolling jsonl (~10)

> Append-only + tail keep / rotate.

| 文件 | 大小 | Writer | Reader | 用途 | rotate? |
|---|---:|---|---|---|---|
| `screen_history.jsonl` | 305.4 KB | ScreenshotSentinel + ScreenVisionEngine | dashboard + ScreenTeaseReflector | 屏幕历史 | ✅ jsonl_rotator |
| `stm_recent.jsonl` | 4.3 KB | central_nerve._persist_stm_to_disk (30s tick) | central_nerve._restore_stm_from_disk | STM 30 turn 持久化 | tail-keep 50 |
| `recent_nudges.jsonl` | 18.7 KB | RecentNudgeMemoryStore | SmartNudge / ProactiveCare | 防 nudge 重复 | tail-keep |
| `progress_logs.json` | 2.5 KB | ProgressTrackerStore | _assemble_prompt + dashboard | 数值进度 | (json) |
| `pending_callbacks.jsonl` | 0 KB | (cross_session_callback?) | (待审) | 跨 session 心结 (空) | (未真用) |
| `skill_registry.jsonl` | 78.9 KB | SkillRegistry.autosave (60s) | SkillRegistry.load | skill 130+ | append + load all |
| `_archive_promise_log_2026_05_18.json.bak` | 0 KB | 历史归档 (空) | (无) | β.4.x 归档 | 死文件 |

**Phase B 应**: `pending_callbacks.jsonl` + `_archive_promise_log_*.bak` 是死文件, 清理.

---

## 7. Static asset (5+)

| 文件 | 大小 | 用途 |
|---|---:|---|
| `jarvis_v1.onnx` | 201.4 KB | openWakeWord 模型 (ONNX) |
| `jarvis_v1.tflite` | 202.1 KB | openWakeWord 模型 (TFLite) |
| `jarvis_prompt.wav` | 382 KB | wake prompt 音频 (录音示例) |
| `README.md` | 0.2 KB | memory_pool readme |
| `integrity_audit.jsonl.tainted-184101.bak` | 5.2 KB | 误写 backup (待清) |

---

## 8. Database (sqlite, 2)

### 8.1 `jarvis_memory.db` (7756 KB) — Hippocampus 主 db

| 表 | 行数估 | Schema | Writer | Reader |
|---|---|---|---|---|
| **TaskMemories** | ~1778 | id / timestamp / environment / user_intent / macro_goal / execution_summary / raw_actions / **semantic_embedding** / is_deleted / memory_type / entities_json / is_future_task / trigger_time | seal_memory + add_completed_event | search_memory + list_recent_completed_events |
| **Commitments** | ~26 | id / description / deadline_ts / grace_minutes / source_text / created_at / nudged / is_deleted | add_commitment_row + soft_delete_commitment | load_active_commitments + cancel_by_keyword |
| **ProjectTimeline** | ~21 | id / project_name / last_active_time / total_hours / status / first_seen_time / session_count / held_until_ts | ProjectTimeline (jarvis_sensors) | _assemble_prompt + ContextRouter |
| **CorrectionMemory** | ~141 | id / timestamp / trigger_context / wrong_response / correction / context_embedding / source_module / confidence / times_recalled | CorrectionMemory.append (老路径?) | (老路径, 待审是否用) |

**问题**:
- TaskMemories.is_future_task 字段跟 Commitments 表概念**重叠** (Phase B 必判)
- CorrectionMemory 跟 ProfileCard.apply_correction 老路径**重叠**

### 8.2 `skill_tree.db` (24 KB)

| 表 | 用途 |
|---|---|
| (待查) | SkillRegistry 持久化 (内部使用) |

---

## 9. 完整文件清单 (93 个)

> 按字母顺序. (✓) = 准则 6 vocab + L7 propose 模范

```
_archive_promise_log_2026_05_18.json.bak  (死)
_base_correction_vocab.json (✓)
_base_dismiss_vocab.json (✓)
ambient_sensor_config.json
audio_ducking_targets.json
behavior_inference_vocab.json (✓)
claim_classify_vocab.json (✓)
claim_revisions.json
claim_stats.json
commitment_conditional_vocab.json (✓)
completion_event_vocab.json (✓ fix82-X)
concern_dismiss_vocab.json (✓)
concern_keywords_vocab.json (✓)
concern_summon_vocab.json (✓)
concerns.json ⭐
concerns_review.json
correction_dispatcher_vocab.json (✓)
cross_session_callback.json
cyclic_task_dispatcher_vocab.json (✓)
dashboard_intent_vocab.json (✓)
directive_inject_config.json
directive_registry.json ⭐
directive_review.json
directives_vocab.json ⭐
evidence_requirements.json (✓)
feedback_vocab.json (✓)
forbidden_callback_vocab.json (✓)
gate_mode_vocab.json (✓)
hippocampus_decay_config.json
inconsistency_vocab.json (✓)
integrity_audit.jsonl (audit)
integrity_audit.jsonl.tainted-184101.bak  (死)
integrity_claim_vocab.json (✓)
integrity_suspicious_kw.json
integrity_watcher.json (state, 163KB)
intent_fast_path_vocab.json (✓)
intent_resolver_telemetry.json (audit)
intent_to_tool_map.json
item_feedback.jsonl
jarvis_health_history.jsonl (282KB)
jarvis_memory.db ⭐⭐⭐ (7756 KB sqlite 4 表)
jarvis_promise_log.json ⭐ (45KB)
jarvis_prompt.wav (static)
jarvis_v1.onnx (static, openWakeWord)
jarvis_v1.tflite (static, openWakeWord)
key_router_health.json
key_router_reset_audit.jsonl
key_router_reset_request.json
key_router_state.json (0 KB, 似乎未持久化)
main_brain_meta_audit.jsonl (38KB)
memory_correction_vocab.json (✓)
memory_deletion_vocab.json (✓)
mic_safety_vocab.json (✓)
mutation_receipts.jsonl ⭐⭐⭐ (12KB, MemoryHub 主 audit)
nudge_window_vocab.json (✓)
pending_callbacks.jsonl (0 KB 死)
plans.json (0 KB 未启用)
predicate_keywords.json
preflight_stats.jsonl (127KB)
proactive_care_cooldown_vocab.json (✓)
profile_corrections.jsonl ⭐ (48KB, 老路径 audit)
profile_review.json
progress_logs.json
progress_tracker_dispatcher_vocab.json (✓)
project_hold_phrases_vocab.json (✓)
promise_soft_vocab.json (✓)
README.md (static)
recent_nudges.jsonl (18KB)
reflector_budget_config.json
refusal_vocab.json (✓)
reject_learner_config.json
relational_review.json
relational_state.json ⭐ (27KB)
response_classify_vocab.json (✓)
screen_history.jsonl (305KB)
screen_snapshot.json
screen_tease_vocab.json (✓)
sensor_state_inject_vocab.json (✓)
severity_decay_vocab.json
sir_acked_state.json
sir_milestones.json ⭐
sir_sleep_pattern_vocab.json (✓)
sir_status.json ⭐
sir_status_vocab.json (✓)
sir_struggle_vocab.json (✓)
skill_registry.jsonl (79KB, autosave 60s)
skill_tree.db (24KB sqlite)
sleep_cancel_vocab.json (✓)
stand_down_history.jsonl
stand_down_state.json
stm_recent.jsonl (β.4.10 STM 持久化)
stm_summarize_config.json
system_errors.jsonl (30KB)
thinking_pause_vocab.json (✓)
tool_intent_vocab.json (✓)
wake_filler_vocab.json (✓)
watch_task_config.json
watch_tasks.json (6KB)
```

**总计 93 个**:
- ⭐⭐⭐ 核心: 3 (sir_profile.json + jarvis_memory.db + mutation_receipts.jsonl)
- ⭐ 重要 source: 7 (concerns / relational / status / milestones / promise_log / corrections / directives)
- ✓ 准则 6 vocab: ~38
- 死文件: 4 (_archive*.bak / pending_callbacks.jsonl 0KB / plans.json 0KB / integrity_audit.jsonl.tainted)
- audit log: 10
- state snapshot: 10
- history rolling: 10
- config: 10
- static asset: 5

---

## 10. Storage 设计问题 (Phase B 必决)

| 问题 | 详 |
|---|---|
| **5 audit log 重叠** | mutation_receipts + profile_corrections + claim_revisions + claim_stats + integrity_audit → 应合 `mem_audit.jsonl` |
| **TaskMemories.is_future_task vs Commitments 表 重叠** | 同 sqlite db 2 表概念混 |
| **CorrectionMemory (sqlite) vs ProfileCard.apply_correction (jsonl)** | 老路径 2 处都写 |
| **HumorMemory (memory_core) vs RelationalState.inside_jokes** | 概念重叠, 不同存储 |
| **`pending_callbacks.jsonl` + `plans.json` 0 KB** | 似乎死代码, 待 Phase A.5 历史 audit |
| **SWM ConversationEventBus 不持久化** | 重启全丢 60 event (deque maxlen=60) — Phase B 应加可选 jsonl |
| **`integrity_watcher.json` 163.5 KB** | 单 file 太大, 应分 |
| **`screen_history.jsonl` 305 KB / `jarvis_health_history.jsonl` 282 KB / `preflight_stats.jsonl` 127 KB** | 大 jsonl 应 rotate (jsonl_rotator 已有) |

---

## 11. 持久化策略一致性

| 策略 | 现状 |
|---|---|
| Atomic write (tmp + rename) | ✅ ProfileCard / ConcernsLedger / RelationalState / etc. |
| jsonl append-only | ✅ mutation_receipts / profile_corrections / etc. |
| sqlite 4 表 | ✅ jarvis_memory.db |
| in-memory + 30s tick persist | ✅ STM / ConcernsLedger.start_decay_worker |
| autosave 60s | ✅ SkillRegistry |
| atomic + jsonl rotate | ✅ screen_history (jsonl_rotator) |

**Phase B 应**: 统一 storage helper module (`jarvis_storage_helpers.py`) — 减少各 source 重复实现 atomic write + load + persist. 现状每个 source 自己写 _persist_to_disk + _restore_from_disk.

---

*Phase A.3 storage map 完成于 2026-05-23 23:55. 配合 audit cards + dataflow map = Jarvis 完整知识图.*
