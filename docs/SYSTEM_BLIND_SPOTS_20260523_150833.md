# Jarvis 系统盲点审计 — 2026-05-23 15:08:33

Sir 准则 8: 优雅高效可持续 > 最简单
Sir 真意 4 类: 存在但不生效 / 能力分配错 / LLM 性价比 / 纯 BUG

## 1. QuickClassifier (qwen2.5:1.5b) 调用点审计

| 文件 | 调用方式 | 任务复杂度 | 评级 | 建议 |
|---|---|---|---|---|
| `jarvis_concern_feedback.py` | prompt_raw 调 1.5B 判 N concern × 4 字段 JSON | **超复杂** | 🔴 错配 | 拆 binary 单字段 OR 升 3B |
| `jarvis_concern_feedback_reflector.py` | L7 reflector 周期回看历史 | **复杂** | 🟡 边界 | 监控 JSON 失败率, 必要时升 3B |

**总结**:
- 🔴 ConcernFeedback judge_async — 14:51 Sir 实测 0 [RECORD] log, 主因 1.5B 容量不足
- 🟡 fix45 已治本 (主脑自决 CONCERN_DAMPEN), ConcernFeedback 可降级为 fallback
- ✅ classify(simple/code/reasoning/search) — 4-way enum, 1.5B 完全胜任

## 2. SWM publish but no consumer — dead data publish

| etype | publisher | 有 specific reader? | 进 prompt (to_swm_block default sal≥0.3)? | 评级 |
|---|---|---|---|---|
| `active_window_hung` | jarvis_proactive_care.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `afk_return` | jarvis_return_sentinel.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `ambient_state` | jarvis_ambient_sensor.py | ✅ | ✅ default in prompt | ✅ 强耦合 |
| `capability_overreach_detected` | jarvis_worker.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `care_signal_derived` | jarvis_proactive_care.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `claim_revision_captured` | jarvis_callback_guard.py, jarvis_claim_r | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `commitment_detected` | jarvis_worker.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `concern_active` | jarvis_proactive_care.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `concern_dampen_applied` | jarvis_concern_dampen.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `concern_dismissed` | jarvis_concerns.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `concern_field_updated` | jarvis_concerns.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `concern_reactivated` | jarvis_concerns.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `concern_timing_evidence` | jarvis_proactive_care.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `conversation_event` | jarvis_worker.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `cyclic_task_cancelled` | jarvis_cyclic_task.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `cyclic_task_registered` | jarvis_cyclic_task.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `deprecated_syntax_used` | jarvis_chat_bypass.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `gate_advice` | jarvis_sentinels.py, jarvis_conductor.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `ghost_activity_observed` | jarvis_env_probe.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `hallucination_detected` | jarvis_worker.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `help_refused` | jarvis_worker.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `intent_call_result` | jarvis_intent_router.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `intent_resolved` | jarvis_intent_resolver.py | ✅ | ✅ default in prompt | ✅ 强耦合 |
| `jarvis_state` | jarvis_state_tracker.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `main_brain_meta` | jarvis_meta_self_check.py | ✅ | ✅ default in prompt | ✅ 强耦合 |
| `manual_standby` | jarvis_worker.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `memory_deletion_preview` | jarvis_worker.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `memory_deletion_refused` | jarvis_worker.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `nudge_no_sound` | jarvis_worker.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `nudge_silenced` | jarvis_worker.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `nudge_window_advice` | jarvis_proactive_care.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `offer_blocked` | jarvis_skill_registry.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `physio_state` | jarvis_physio_proxy.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `preflight_verdict` | jarvis_chat_bypass.py | ✅ | ✅ default in prompt | ✅ 强耦合 |
| `proactive_nudge` | jarvis_smart_nudge.py, jarvis_worker.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `proactive_nudge_fired` | jarvis_nudge_coordination.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `proactive_nudge_skipped_due_to_recent` | jarvis_nudge_coordination.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `progress_cancelled` | jarvis_progress_tracker.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `progress_completed` | jarvis_progress_tracker.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `progress_registered` | jarvis_progress_tracker.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `progress_updated` | jarvis_progress_tracker.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `promise_cancelled` | jarvis_promise_log.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `promise_fulfilled` | jarvis_promise_log.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `relational_field_updated` | jarvis_relational.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `reminder_fired` | jarvis_sentinels.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `reply_interrupted` | jarvis_worker.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `screen_described` | jarvis_screen_vision.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `self_critique` | jarvis_chat_bypass.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `self_promise_overdue` | jarvis_promise_log.py | ✅ | ✅ default in prompt | ✅ 强耦合 |
| `sensor_change` | jarvis_env_probe.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `shield_observation` | jarvis_enhanced.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `sir_afk_detected` | jarvis_env_probe.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `sir_declared_status` | jarvis_sir_status_tracker.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `sir_field_updated` | jarvis_memory_gateway.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `sir_intent_commit_candidate` | jarvis_worker.py | ✅ | ✅ default in prompt | ✅ 强耦合 |
| `sir_intent_correction_candidate` | jarvis_worker.py | ✅ | ✅ default in prompt | ✅ 强耦合 |
| `sir_intent_deadline_candidate` | jarvis_commitment_watcher.py | ✅ | ✅ default in prompt | ✅ 强耦合 |
| `sir_intent_profile_update_candidate` | jarvis_routing.py | ✅ | ✅ default in prompt | ✅ 强耦合 |
| `sir_intent_progress_candidate` | jarvis_concern_feedback.py | ✅ | ✅ default in prompt | ✅ 强耦合 |
| `sir_intent_project_hold_candidate` | jarvis_project_hold_detector.py | ✅ | ✅ default in prompt | ✅ 强耦合 |
| `sir_intent_promise_candidate` | jarvis_self_promise.py | ✅ | ✅ default in prompt | ✅ 强耦合 |
| `sir_intent_return_greeting_candidate` | jarvis_return_sentinel.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `sir_profile_overwritten` | jarvis_routing.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `sir_progress_evidence` | jarvis_concerns.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `sir_sleep_pattern` | jarvis_proactive_care.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `sir_struggle_observed` | jarvis_conductor.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `sir_thinking_pause` | jarvis_silence_intel.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `sir_watch_request_proposed` | jarvis_sir_request_reflector.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `sleep_intent_declared` | jarvis_worker.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `sleep_intent_due` | jarvis_worker.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `sleep_intent_signal` | jarvis_memory_core.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `sleep_routine_armed` | jarvis_worker.py | ✅ | ✅ default in prompt | ✅ 强耦合 |
| `soft_focus_active` | jarvis_worker.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `stm_summarized` | jarvis_stm_summarizer.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `system_error_visible` | jarvis_error_bus.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `tool_called` | jarvis_intent_resolver.py | ✅ | ✅ default in prompt | ✅ 强耦合 |
| `tool_chain_circuit_broken` | jarvis_chat_bypass.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `utterance_appended` | jarvis_central_nerve.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |
| `watch_task_fired` | jarvis_watch_task.py | ✅ | ✅ default in prompt | ✅ 强耦合 |
| `watch_task_register_fail` | jarvis_watch_task.py | ✅ | ✅ default in prompt | ✅ 强耦合 |
| `watch_task_registered` | jarvis_watch_task.py | ⚠️ 仅 to_swm_block default | ✅ default in prompt | 🟢 OK (prompt 通用) |

**总 publish etype: 81, 有 specific reader: 16**

## 3. directive 注册但是否 fire 不明 (dead directive 嫌疑)

| directive id | trigger fn | 状态 |
|---|---|---|
| `nudge_agenda_honesty` | `_trigger_nudge_agenda_honesty` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `continuity_two_parts` | `_trigger_continuity_two_parts` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `tool_honesty_directive` | `_trigger_tool_honesty` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `fuzzy_candidates_policy` | `_trigger_fuzzy_candidates` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `promise_protocol_directive` | `_trigger_promise_protocol` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `bilingual_directive` | `_trigger_bilingual_always` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `meta_self_check_directive` | `_trigger_meta_self_check` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `search_directive` | `_trigger_search_directive` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `memory_callback` | `_trigger_memory_callback` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `image_context` | `_trigger_image_context` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `system_environment` | `_trigger_system_environment` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `smart_routing_working_feed` | `_trigger_smart_routing_working_feed` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `correction_writepath_no_tool` | `_trigger_correction_writepath` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `reminder_read_truth_source` | `_trigger_reminder_read` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `future_tense_capability_check` | `_trigger_future_tense_capability_check` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `memory_update_honesty` | `_trigger_memory_update_honesty` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `tool_overture_directive` | `_trigger_tool_overture` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `dashboard_intent_directive` | `_trigger_dashboard_intent` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `concern_dismissal_judge` | `_trigger_concern_dismissal` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `stand_down_judge` | `_trigger_stand_down` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `promise_completion_judge` | `_trigger_promise_completion` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `correction_dispatcher` | `_trigger_correction_dispatcher` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `cyclic_task_dispatcher` | `_trigger_cyclic_task_dispatcher` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `progress_tracker_dispatcher` | `_trigger_progress_tracker_dispatcher` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `concern_dampen_self_decide` | `None` | 🟢 常驻 always-on |
| `past_action_honesty` | `_trigger_past_action_honesty` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `sleep_confirmation_judge` | `_trigger_sleep_confirmation_judge` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `ghost_activity_judge` | `_trigger_ghost_activity_judge` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `sir_intent_judge` | `_trigger_sir_intent_judge` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `morning_mood_judge` | `_trigger_morning_mood_judge` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `morning_warmth_priority` | `_trigger_morning_mood_judge` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `late_night_care_judge` | `_trigger_late_night_care_judge` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `silent_company_judge` | `_trigger_silent_company_judge` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `callback_recall_judge` | `_trigger_callback_recall_judge` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `mood_shift_judge` | `_trigger_mood_shift_judge` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `ambient_state_judge` | `_trigger_ambient_state_judge` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `nudge_window_advice_judge` | `_trigger_nudge_window_advice_judge` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `physio_state_judge` | `_trigger_physio_state_judge` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `concern_timing_judge` | `_trigger_concern_timing_judge` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `multi_person_aware_judge` | `_trigger_multi_person_aware_judge` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `capability_boundary_judge` | `_trigger_capability_boundary_judge` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `no_hallucinated_tool_use_judge` | `_trigger_no_hallucinated_tool_use_judge` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `unsolicited_callback_guard` | `_trigger_no_hallucinated_tool_use_judge` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `integrity_watcher_report_use` | `_trigger_no_hallucinated_tool_use_judge` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `over_offer_called_out_judge` | `_trigger_over_offer_called_out` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `thinking_pause_aware_judge` | `_trigger_thinking_pause_aware_judge` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |
| `interrupted_aware_judge` | `_trigger_interrupted_aware_judge` | 🟡 vocab/regex 触发 (看 vocab 是否生效) |

**总 directive 47 个**. 真 fire/skip 统计需要 runtime audit, 见 `scripts/directive_fire_stats.py` (TODO)

## 4. vocab 文件: 加了但空 / 没 seed / reflector 不跑

| vocab 文件 | 大小 | active items | 状态 |
|---|---|---|---|
| `_base_correction_vocab.json` | 1150 B | 38/38 | 🟢 健康 |
| `_base_dismiss_vocab.json` | 834 B | 19/19 | 🟢 健康 |
| `ambient_sensor_config.json` | 1529 B | 5/5 | 🟢 健康 |
| `audio_ducking_targets.json` | 2010 B | 1/1 | 🟢 健康 |
| `behavior_inference_vocab.json` | 1993 B | 4/4 | 🟢 健康 |
| `claim_classify_vocab.json` | 5233 B | 7/7 | 🟢 健康 |
| `claim_revisions.json` | 25150 B | 1/1 | 🟢 健康 |
| `claim_stats.json` | 156 B | 5/5 | 🟢 健康 (size 极小) |
| `commitment_conditional_vocab.json` | 1559 B | 9/9 | 🟢 健康 |
| `concern_dismiss_vocab.json` | 856 B | 25/25 | 🟢 健康 |
| `concern_keywords_vocab.json` | 10204 B | 6/6 | 🟢 健康 |
| `concern_summon_vocab.json` | 2584 B | 4/4 | 🟢 健康 |
| `concerns.json` | 34040 B | (skip-detail) | 🟢 ledger |
| `concerns_review.json` | 2 B | (skip-detail) | 🟢 ledger |
| `correction_dispatcher_vocab.json` | 989 B | 24/24 | 🟢 健康 |
| `cross_session_callback.json` | 908 B | 1/1 | 🟢 健康 |
| `cyclic_task_dispatcher_vocab.json` | 979 B | 45/45 | 🟢 健康 |
| `dashboard_intent_vocab.json` | 2090 B | 6/6 | 🟢 健康 |
| `directive_inject_config.json` | 1089 B | 8/8 | 🟢 健康 |
| `directive_registry.json` | 13659 B | (skip-detail) | 🟢 ledger |
| `directive_review.json` | 2394 B | (skip-detail) | 🟢 ledger |
| `directives_vocab.json` | 22581 B | 1/1 | 🟢 健康 |
| `evidence_requirements.json` | 4744 B | 7/7 | 🟢 健康 |
| `feedback_vocab.json` | 4078 B | 10/10 | 🟢 健康 |
| `forbidden_callback_vocab.json` | 3297 B | 2/2 | 🟢 健康 |
| `gate_mode_vocab.json` | 2867 B | 10/10 | 🟢 健康 |
| `hippocampus_decay_config.json` | 1116 B | 8/8 | 🟢 健康 |
| `inconsistency_vocab.json` | 3812 B | 5/5 | 🟢 健康 |
| `integrity_claim_vocab.json` | 4408 B | 2/2 | 🟢 健康 |
| `integrity_suspicious_kw.json` | 825 B | 2/2 | 🟢 健康 |
| `integrity_watcher.json` | 145795 B | 1/1 | 🟢 健康 |
| `intent_fast_path_vocab.json` | 4330 B | 6/6 | 🟢 健康 |
| `intent_resolver_telemetry.json` | 829 B | 5/5 | 🟢 健康 |
| `intent_to_tool_map.json` | 5841 B | 3/3 | 🟢 健康 |
| `jarvis_promise_log.json` | 43640 B | 76/76 | 🟢 健康 |
| `key_router_health.json` | 3434 B | 7/7 | 🟢 健康 |
| `key_router_reset_request.json` | 446 B | 8/8 | 🟢 健康 |
| `key_router_state.json` | 30 B | 1/1 | 🟢 健康 (size 极小) |
| `memory_correction_vocab.json` | 1308 B | 1/1 | 🟢 健康 |
| `memory_deletion_vocab.json` | 2447 B | 2/2 | 🟢 健康 |
| `mic_safety_vocab.json` | 1828 B | 1/1 | 🟢 健康 |
| `nudge_window_vocab.json` | 1562 B | 6/6 | 🟢 健康 |
| `plans.json` | 2 B | 0/0 | 🔴 空 / dead (size 极小) |
| `predicate_keywords.json` | 1700 B | 6/6 | 🟢 健康 |
| `proactive_care_cooldown_vocab.json` | 1313 B | 7/7 | 🟢 健康 |
| `progress_logs.json` | 856 B | 2/2 | 🟢 健康 |
| `progress_tracker_dispatcher_vocab.json` | 914 B | 53/53 | 🟢 健康 |
| `project_hold_phrases_vocab.json` | 4536 B | 6/6 | 🟢 健康 |
| `promise_soft_vocab.json` | 2916 B | 6/6 | 🟢 健康 |
| `reflector_budget_config.json` | 1099 B | 7/7 | 🟢 健康 |
| `refusal_vocab.json` | 3037 B | 8/8 | 🟢 健康 |
| `reject_learner_config.json` | 1239 B | 11/11 | 🟢 健康 |
| `relational_review.json` | 1443 B | 2/2 | 🟢 健康 |
| `relational_state.json` | 28270 B | 4/4 | 🟢 健康 |
| `response_classify_vocab.json` | 2748 B | 4/4 | 🟢 健康 |
| `screen_snapshot.json` | 923 B | 14/14 | 🟢 健康 |
| `screen_tease_vocab.json` | 2950 B | 3/3 | 🟢 健康 |
| `severity_decay_vocab.json` | 1556 B | 1/1 | 🟢 健康 |
| `sir_acked_state.json` | 67 B | 1/1 | 🟢 健康 (size 极小) |
| `sir_milestones.json` | 2464 B | 1/1 | 🟢 健康 |
| `sir_sleep_pattern_vocab.json` | 1474 B | 3/3 | 🟢 健康 |
| `sir_status.json` | 2869 B | 1/1 | 🟢 健康 |
| `sir_status_vocab.json` | 4092 B | 1/1 | 🟢 健康 |
| `sir_struggle_vocab.json` | 3272 B | 3/3 | 🟢 健康 |
| `sleep_cancel_vocab.json` | 1253 B | 5/5 | 🟢 健康 |
| `stand_down_state.json` | 357 B | 11/11 | 🟢 健康 |
| `stm_summarize_config.json` | 1397 B | 12/12 | 🟢 健康 |
| `thinking_pause_vocab.json` | 2150 B | 7/7 | 🟢 健康 |
| `tool_intent_vocab.json` | 2633 B | 4/4 | 🟢 健康 |
| `wake_filler_vocab.json` | 880 B | 7/7 | 🟢 健康 |
| `watch_task_config.json` | 2317 B | 13/13 | 🟢 健康 |
| `watch_tasks.json` | 6297 B | 3/3 | 🟢 健康 |

## 5. 代码中 TODO / FIXME / XXX 等技术债 (sample top 20)

**total: 3 TODO/FIXME marks across jarvis_*.py**

| 文件 | 行 | 内容 |
|---|---|---|
| `jarvis_claim_tracer.py` | L727 | `# 真治本 (β.4.3+ TODO): 加 SYSTEM CLOCK ±2 min 比较 verify, 命中则 found=True.` |
| `jarvis_directives.py` | L2050 | `[REMINDER / TODO READ — truth source]:` |
| `jarvis_sir_status_tracker.py` | L29 | `- L7 reflector 后续 (TODO)` |

## 6. LLM model 配置审计 (能力分配 / 性价比)

| 模型 | 用途数 | 用途文件 | 评级 |
|---|---|---|---|
| `editingNote` | 1 | 1 files | ? |
| `flash` | 3 | 2 files | ? |
| `flash_lite` | 4 | 4 files | ? |
| `gemini-2.5-flash` | 1 | 1 files | 🟢 cloud |
| `gemini-3-flash-preview` | 8 | 4 files | 🟢 cloud |
| `gemini-3.1-flash-lite` | 7 | 3 files | 🟢 cloud |
| `gemini-embedding-2` | 3 | 2 files | 🟢 cloud |
| `google/gemini-2.5-flash-lite` | 12 | 9 files | 🟢 cloud |
| `google/gemini-2.5-flash-preview-09-2025` | 2 | 2 files | 🟢 cloud |
| `google/gemini-2.5-pro` | 1 | 1 files | 🟢 cloud |
| `google/gemini-3-flash-preview` | 5 | 2 files | 🟢 cloud |
| `google/gemini-3.1-pro-preview` | 7 | 6 files | 🟢 cloud |
| `google/gemini-3.5-flash` | 1 | 1 files | 🟢 cloud |
| `hey_jarvis_v0.1` | 2 | 1 files | ? |
| `iic/SenseVoiceSmall` | 1 | 1 files | ? |
| `pro` | 2 | 1 files | ? |
| `qwen2.5:0.5b` | 1 | 1 files | 🟢 local |
| `qwen2.5:14b` | 1 | 1 files | 🟢 local |

## 7. 巨型 .py 文件 (准则 8 可维护性风险)

| 文件 | 行数 | 建议 |
|---|---|---|
| `jarvis_worker.py` | 5828 | 🔴 拆 (>3000 行难维护) |
| `jarvis_chat_bypass.py` | 5692 | 🔴 拆 (>3000 行难维护) |
| `jarvis_utils.py` | 4846 | 🔴 拆 (>3000 行难维护) |
| `jarvis_central_nerve.py` | 4656 | 🔴 拆 (>3000 行难维护) |
| `jarvis_directives.py` | 3804 | 🔴 拆 (>3000 行难维护) |
| `jarvis_dashboard_web.py` | 3182 | 🔴 拆 (>3000 行难维护) |
| `jarvis_dashboard.py` | 2959 | 🟡 考虑拆 sister module |
| `jarvis_skill_registry.py` | 2559 | 🟡 考虑拆 sister module |
| `jarvis_sentinels.py` | 2141 | 🟡 考虑拆 sister module |
| `jarvis_commitment_watcher.py` | 1896 | 🟡 考虑拆 sister module |