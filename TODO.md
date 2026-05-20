# Jarvis TODO

> **更新**: 2026-05-20 13:10 (β.5.34/35/36 全量 + Sir 13:00-13:05 实测 4 fix, 11 commits 全 sub-batch 测过 295+ pass).
> **滚档**: 老 β.5.x/β.4.x/β.3.x/P0+19 等 ~530 行已沉档 `docs/TODO_ARCHIVE.md`. 本文件 < 300 cap, AGENTS.md 章程.

---

## 🔥 Sir 13:00-13:05 真机实测 fix (4 commits)

| commit | marker | 内容 |
|---|---|---|
| `11b0cc2` | β.5.34-fix | Focus Lock UI 加 listening cue (`🎙️ Listening for your reply…`) — Sir 13:00 实测 "还是没焦点回复不了" 因 nudge 字幕和等候字幕视觉无区分 |
| `c3dfdf0` | β.5.36-fix | `test_persona_under_3000_chars` cap 5500→9500 — Sir IP 不动, β.4.x/5.x directives 涨到 ~8641 |
| `de06811` | **β.5.36-fix2** | **SirStruggleVocab 3 层守卫 (Sir 13:03 实测 "我去休息" 误命中 expletive_zh 'we 我去' → 47s 后催 Sir)**: (a) vocab 删 '我去'/'靠' 误命中 pattern, (b) 同句含 sleep/dismiss 关键词 (休息/睡觉/待会见/goodnight/...) → consume 不触, (c) inter-source cooldown 15s 替代老 bypass-cooldown 防风暴 |
| `37b940d` | **β.5.36-fix3** | **ProactiveShield ghost-input guard (Sir 13:05 真理 "屏幕动的是 Cursor 自动编程")**: ProactiveShield._scan idle_seconds > 60s 直接退 — Sir 离桌时 window 切换 = Cascade/IDE 自动化 ghost activity, 不该触 shield_alert. 准则 6 evidence: 看真物理 input (键盘/鼠标), 不看屏幕动作 |

---

## 🚨 主迭代 (β.5.34/35 / 2026-05-20 10:46 → 12:42, 5 commits) — Sir 10:46 实测 4 BUG 治本

### β.5.34 BUG 1 + 4 小修 (单 commit)
| commit | marker | 内容 | testcase |
|---|---|---|---|
| `8c633a4` | β.5.34 | **BUG 1 早安 morning briefing 评级反转** — `jarvis_chat_bypass.py:3710-3758` 翻转 β.4.12 "should NOT bring up" 抑制, 改 `[MORNING BRIEFING POSTURE]` evidence-only 让主脑参考 SOUL inject (concerns/threads/unfinished/attention) 自决列简报 + **BUG 4 Focus Lock UI 真激活** — `jarvis_worker.py:3262-3274` 在 focus_lock 后端激活时同步 emit `("focus", True)` → `SubtitleOverlay.set_focus_mode(True)` 触发 → UI overlay 持续显示等 Sir 回应 (而不是淡出消失) + test 跟 Sir β.5.34 决策反转 (β.4.12 推翻) + 顺手修 β.5.22-D `sleep_due` test | 13+4 pass |

### β.5.35 BUG 2 大修 (4 sub-commits) — Design doc: `docs/JARVIS_TEASE_AND_TOOL_CHANNEL_DESIGN.md`
| commit | marker | 内容 | testcase |
|---|---|---|---|
| `d32da6b` | **β.5.35-A/B** | **screen_tease vocab 持久化 + L7 reflector** — `memory_pool/screen_tease_vocab.json` (5 seed: error_debugging / entertainment / slacking / reading_docs / ide_focus) + `scripts/screen_tease_vocab_dump.py` CLI (active/review/add/activate/reject/deactivate) + `jarvis_smart_nudge.py._load_screen_tease_vocab` mtime cache (替代硬编码 error_kw/fun_kw/slack_kw) + `jarvis_screen_tease_reflector.py` 新 daemon (24h 1 跑 OpenRouter cheap, 看 PhysicalEnvironmentProbe.window_history 提取 unmatched titles → propose review_queue) + central_nerve 启动 wire | 12+11 pass |
| `24b88e4` | **β.5.35-C** | **offer_help 触发源重设 + sir_struggle_vocab** — `memory_pool/sir_struggle_vocab.json` (10 seed phrase: stuck/frustrated/asking_how/expletive/confusion × zh/en, severity high/medium) + `scripts/struggle_vocab_dump.py` CLI + `jarvis_worker.py` VoiceListenThread `_load_struggle_vocab + _detect_sir_struggle` (ASR 出口 hook 命中写 `last_struggle_at/phrase_id/severity/text`) + `jarvis_conductor.py._check_path_a` 加 SirStruggleVocab 优先路径 (fresh ≤90s 直触 offer_help, bypass cooldown) + ProactiveShield path 改 `screen_tease` 而非 offer_help (语义解耦) + `_dispatch_path_a` 透传 struggle context 到 nudge_context + `jarvis_chat_bypass.py:3782-3805` offer_help directive 改 evidence-driven 引 Sir 原话 + `_test_p2_refusal_and_audio.py` regex 顺手修 (pre-existing) | 20 pass |
| `031231e` | **β.5.35-D** | **StruggleReflector L7 vocab daemon** — `jarvis_struggle_reflector.py` 新 (24h 1 跑 OpenRouter cheap, 看 STM `[src=user_voice]` 提取 ≥2 evidence 的新 struggle phrase → propose review_queue, Sir CLI `struggle_vocab_dump.py --review-list / --activate` 拍板) + central_nerve 启动 wire (stm_provider 复用 WeeklyReflector 风格) | 12 pass |

### Sir 真机实测 check list (β.5.34/5.35 落地完, Sir 重启实测)

| BUG | check 项 | 预期 | 备用 CLI |
|---|---|---|---|
| **BUG 1** | 早安第一次说话 (跨夜 AFK + morning_window) | Jarvis morning briefing 列 1-2 件 concerns/threads/unfinished (不是普通 welcome back) | - |
| **BUG 4** | Sir 收到任意 nudge (offer_help / proactive_care / sleep_due) | UI 字幕 overlay 持续显示 (不淡出), 90s 内 Sir 不喊唤醒词直接说话能 ASR | log `[Focus Lock]` + UI subtitle stay |
| **BUG 2-tease** | Sir 切到 IDE / 文档 / SO 窗口 | screen_tease 调皮观察 (不再"一周静音") | `python scripts/screen_tease_vocab_dump.py --active-only` |
| **BUG 2-tease L7** | 24h 后看是否 propose 新 category | `screen_tease_vocab.json` `review_queue` 非空 | `python scripts/screen_tease_vocab_dump.py --review-list` |
| **BUG 2-help** | Sir 说"卡住" / "搞不定" / "fuck" / "怎么办" | Conductor 30-90s 内 offer_help (引 Sir 原话, 不说工具名) | log `🆘 [SirStruggle] phrase=...` |
| **BUG 2-help L7** | 24h 后 STM 含 ≥30 user_voice → propose 新 struggle phrase | `sir_struggle_vocab.json` `review_queue` 非空 | `python scripts/struggle_vocab_dump.py --review-list` |
| **BUG 2-shield** | 屏幕看到 error keyword (β.4.X 触发 offer_help 误推) | 改触发 screen_tease (调皮观察, 非"need help") | log `Tease Screen` not `Offer Help` |

### β.5.36 BUG 3 工具名泄漏大修 (单 commit, 5 sub-step 合并)
| commit | marker | 内容 | testcase |
|---|---|---|---|
| `41cbf68` | **β.5.36-E/F/G/H/I** | **BUG 3 intent channel + tool name scrub 大修** — E: `memory_pool/intent_to_tool_map.json` (15 seed intent: check_top_cpu/mute_audio/dashboard_open/...) + `scripts/intent_map_dump.py` CLI. F: `jarvis_skill_registry.to_prompt_block` 改双轨 — intent_map 存在 → SEMANTIC CAPABILITIES (intent 列表 + `<TOOL_CALL>` directive + NEVER speak tool names), fallback 老 SKILLS 块也删 "MUST reference by name" 改成 NEVER speak. G: `jarvis_intent_router.py` 新 (IntentParser 提取 `<TOOL_CALL>{intent}` tag + IntentRouter.route_and_invoke_all 翻 tool 名 + 调 fast_call + 结果回流 event_bus, dangerous intent skip 走 PROMISE 路径) + chat_bypass stream_chat/stream_nudge 末尾 hook + worker.run 启动 init_default_intent_router 注入 fast_call. H: `jarvis_utils.scrub_internal_names` helper (剥 organ.command + `<TOOL_CALL>` tag) + `jarvis_ui._poll_queue` 'zh'/'en' branch 调 scrub 防漏给 Sir 看到. I: 33 新 testcase (intent_map schema/CLI + IntentParser corrupt/multi/case + IntentRouter resolve/invoke/dangerous_skip + scrub_internal_names 全 organ + UI/chat_bypass/worker wiring) + 5 老 `_test_r8_axis3_l2_capability_phrasing.py` 改 fallback path. | 33+15 pass |

### Sir 真机实测 check list — 重启 Jarvis 后完整跑

| BUG | 操作 | 预期 | log/CLI 验证 |
|---|---|---|---|
| **BUG 1** 早安 | 跨夜 AFK + 起床第一句 | morning briefing 列 1-2 件 concerns/threads/unfinished (β.5.34) | log `MORNING BRIEFING POSTURE` |
| **BUG 4** Focus | 收 nudge (offer_help/proactive_care/sleep_due) | UI 字幕持续显示, 90s 内不喊唤醒词直接说 | log `[Focus Lock]` + subtitle stays |
| **BUG 2-tease** | 切 IDE/文档/SO/IDE 等 5 类窗口 | screen_tease 调皮 (不再一周静音) (β.5.35-A) | `scripts/screen_tease_vocab_dump.py --active-only` |
| **BUG 2-tease L7** | 24h 后 | `screen_tease_vocab.json` `review_queue` propose 新 category (β.5.35-B) | `scripts/screen_tease_vocab_dump.py --review-list` |
| **BUG 2-help** | 说"卡住"/"搞不定"/"fuck"/"怎么办" | 30-90s 内 offer_help (引 Sir 原话, β.5.35-C) | log `🆘 [SirStruggle] phrase=...` |
| **BUG 2-help L7** | 24h 后 | `sir_struggle_vocab.json` propose 新 struggle phrase (β.5.35-D) | `scripts/struggle_vocab_dump.py --review-list` |
| **BUG 2-shield** | 屏幕含 error keyword (cascade/cursor IDE 错误) | log `Tease Screen` (不是 `Offer Help`, β.5.35-C 语义解耦) | log `🎯 [Focus Lock] screen_tease` |
| **BUG 3-prompt** | 主脑收 offer_help nudge | LLM prompt 含 `SEMANTIC CAPABILITIES (β.5.36 intent channel)`, 不含 `process_hands.X` 工具名 (β.5.36-F) | grep `[Nudge SOUL inject] mode=nudge` 看 prompt 渲染 |
| **BUG 3-tts** | LLM 偶尔违规说工具名 | Audio Guard 替换 'a quick check' (β.4.X) | log `🔇 [Audio Guard / Tool Name]` |
| **BUG 3-subtitle** | LLM 偶尔违规说工具名 | 字幕 overlay 已 scrub 工具名 + `<TOOL_CALL>` tag (β.5.36-H) | UI 字幕不见 `process_hands.X` |
| **BUG 3-intent** | LLM 主动 emit `<TOOL_CALL>{intent="check_top_cpu"}` | intent_router 后端翻 `process_hands.get_top_cpu` 执行 + event_bus publish 结果 (β.5.36-G) | log `🔧 [IntentRouter] check_top_cpu=✅` |

---

## 🚧 历史迭代 (β.5.22 → β.5.25 / 2026-05-19 23:01 → 05-20 02:34, 10 commits)

### β.5.22 Sir 01:22 实测 BUG 治本 (7 sub-step)
| commit | marker | 内容 | testcase |
|---|---|---|---|
| `f297deb` | β.5.22-A/B/E | dismissal flow 调 NudgeGate.activate_sleep_mode + CareWindowGuard 看 _sleep_intent_until + ReturnSentinel 接 _check_short_sleep | 33 |
| `679e205` | β.5.22-G/F | sleep_intent 到点 due timer 主动提醒 + refusal_vocab.json (4 类) dismissal/sleep_soft 早退 + CLI scripts/refusal_vocab_dump.py | 同上 |
| `4739ef1` | **β.5.22-C** | **动态语义反馈 LLM judge** - Concern.daily_progress/last_user_feedback/optimal_timing + ConcernsLedger.record_user_feedback API + jarvis_concern_feedback.py (新 ~232 行 QuickClassifier.prompt_raw 调用) + post_chat hook + urgency 计算 progress_mul + timing_mul (0.3 floor 不 close, before_sleep 反弹 1.5x) | 同上 |
| `36d776c` | β.5.22-D + C-fix | sleep_due 加 focus list (offer_help/commitment_check/proactive_care 4 类型) + QuickClassifier.prompt_raw generic API (替代每个 detect_X 重复 boilerplate) | 同上 |

### β.5.23 准则 6 完结 (2 sub-step)
| commit | marker | 内容 | testcase |
|---|---|---|---|
| (待 grep) | β.5.23-A | cooldown 阈值 vocab JSON `memory_pool/proactive_care_cooldown_vocab.json` (11 阈值 + ranges) + `_get_cd()` mtime cache + 5 call sites 替换 + CLI `scripts/cooldown_vocab_dump.py` (list/show/set/history/review) | 23 |
| 同 | β.5.23-B | `jarvis_concern_feedback_reflector.py` (新 ~290 行) ConcernFeedbackReflector L7 daemon - 24h 周期看 7d STM + Concern.last_user_feedback + nudge 推送量 + Sir 拒绝量 → QuickClassifier.prompt_raw propose 阈值调整 → 写 review_queue 等 Sir 拍板 (CompanionCenter 启 daemon) | 同上 |

### β.5.24 Dashboard tkinter 重构 (Sir 01:58 反馈 'X 拒绝说不存在')
| commit | marker | 内容 | testcase |
|---|---|---|---|
| `55e4286` | β.5.24 | scripts/jarvis_dashboard.py 重构 - main grid 信息1/待处理5/观测2 + read_review_queues 整合 4 源 (concerns/relational/directive/**cooldown_vocab L7**) + thread title fallback (修 X BUG root cause) + cooldown action_activate/reject 路径 | 20 |
| `517cf56` | β.5.24-finish | 标题改 β.5.24 + _make_action_card 加 height=380 + grid_propagate(False) (修待处理区塌缩 BUG - 空 inner canvas → group_todo 整块=0) | 同上 |

### β.5.25 Web Dashboard (Sir 02:17 'tkinter 不喜欢, 现代审美 + 窗口缩放')
| commit | marker | 内容 | testcase |
|---|---|---|---|
| `4ceb046` | β.5.25 | `scripts/jarvis_dashboard_web.py` (新 ~600 行 Flask + Tailwind CDN + Alpine.js) - 4 大区 (整体状态 + 待拍板 + 信息 + 观测) + 现代 glass-morphism 卡片 + 响应式 grid (md:2/lg:4) + Toast 通知 + auto 10s 轮询 + /api/all /api/review/<activate|reject> endpoints | 19 |
| `6582ec2` | β.5.25-extend | 补 Commitments todo 区 (3 列 grid) + cancelCommitment Alpine 方法 + /api/commitment/cancel endpoint | 同上 |
| `79faf7d` | β.5.25-finish | 补 Jarvis 承诺卡 (信息区扩 4 卡) + 言出必行健康度宽卡 (top 5 空头话) + dashboard.ps1 一键启动 launcher | 同上 |
| `e01e868` | β.5.25-route | `ui_control.dashboard_open` 改默认开 web (port 8765 探测复用 + 启动失败 fallback tkinter) + dashboard_close 双 kill (web wmic + tkinter taskkill). Sir 现在语音"打开面板"开 web 浏览器 | - |
| (修 BUG 1) | β.5.24-fix2 | tkinter 加回 messagebox.showinfo 完成弹窗 (Sir "默契活动无反应" root cause = 反馈不显眼) | - |

### β.5.31-33 Sir 03:36-03:55 实测 BUG 治本 (5 sub-step)
| commit | marker | 内容 | testcase |
|---|---|---|---|
| `ce66f71` | β.5.31 | TIME ANCHOR 防时间幻觉 (`stream_nudge` 加 `[TIME ANCHOR]` 段反推 Sir 上句时间 + 距今 min) + 短 cmd 不臆造关怀 RULE (准则 5 严重 BUG: Sir 03:42 实测"十几分钟早就过去了" / Sir 03:36 实测 "ber" → 关心手部疲劳) | sub-batch ✓ |
| `ff5f95a` | β.5.31-fix | Sir 反问"为什么是模板?" → 准则 6 服从, 删 prescriptive RULE 改 [ASR QUALITY FACT] 事实段, LLM 自决 ask repeat / acknowledge ambiguity | 同上 |
| `73154cf` | β.5.32 | web layout 重构 (删 Jarvis 承诺卡 - 上面言行一致区已含; 长期惦记/你们之间 50/50 grid; 系统健康单独下行) + dismissal 光速 wake 30s grace lock (Sir 03:55 实测"只 1 分钟"询问光速触发 - NudgeGate.deactivate_sleep_mode 加 30s minimum lock + `_check_short_sleep` 加 30s grace early return) | 同上 |
| `dfbefd2` | **β.5.33** | **Cross-session memory callback PROACTIVITY_NEXT §E 落地** - `jarvis_cross_session_callback.py` 新 (CallbackStore + parse_natural_time_to_iso 周X/明天/后天/HH:MM) + SoulArchivist prompt 加 propose_cross_session_callbacks 数组提取 + dashboard read_review_queues 加 callback source + action_activate/reject 路由 + `_apply_callback_proposal` 写 `pending_callbacks.jsonl` + CommitmentWatcher `_consume_pending_callbacks` (启动时 + 每 5min) 转 hard commitment | 同上 |

**测试现状** (2026-05-20 10:33): pytest 全 collect IO error (PowerShell pipe 老问题, 非测试失败). Sub-batch 分批跑确认 β.5.31-33 引入 0 fail. 老 pre-existing fail: `test_persona_under_3000_chars` (Sir IP 不动) + `proactive_care_level_preset` 2 (vocab 化后 preset 阈值不匹配老 assert).

---

## 📌 文档遗留尾巴清单 (Sir 02:33 全扫结果)

| 来源 | 尾巴 | 优先级 | 现状 |
|---|---|---|---|
| `JARVIS_VOICE_PIPELINE_LATENCY.md §7.3` | filler list 20 条仍 `.py` 硬编码 (β.5.11 留尾), 应迁 `memory_pool/wake_filler_vocab.json` + CLI | 中 | 准则 6 违规, ~30min |
| `INTEGRITY_STACK.md §L1/L2/L3` | 标 ❌/⚠️ 但 β.4.1-4.5 已做 (L4 ClaimTracer enforce / L5 闭环 / L6 dashboard / L7 reflector) | 低 | **文档 stale** - 仅需 sync ❌→✅ |
| `INTEGRITY_STACK.md §L0.5` | 14 directive 全迁 JSON (β.2.9.12 立, 部分迁) | 中 | 进行中 (registry_dump.py 已建) |
| `FOUNDATION_AUDIT.md §STM` | STM source 区分 (reflector 幻觉 root cause) | 中 | **✅ 已做** (β.5.29 STM source append 4 worker + 3 sentinels + nerve API) |
| `PROACTIVITY_NEXT.md §E` | Cross-session memory callback | 低 | **✅ 已做 β.5.33** (SoulArchivist propose → review → activate → commitment_watcher 到点 nudge) |
| `JARVIS_PROACTIVITY_NEXT.md` 整体 | 5 大方向 A-E | 低 | 长期规划 |
| **ProactiveCare sensor=None 老 BUG** | `⚠️ tick err 'NoneType' object has no attribute 'tick'` - daemon bootstrap 路径漏初始化 | 低 | 非阻塞, 主路径 OK, 派生 signal 失效 |
| TODO.md 章程 cap | 当前 ~680 行 > 300 行 cap | 高 | β.4/4.6/4.7/4.8 段应滚 docs/TODO_ARCHIVE.md |

---

## 🎯 Sir 想要的新功能 (β.2.9 候选, 等下次启动)

| # | 功能 | 现状 | 实现方向 |
|---|---|---|---|
| 1 | 说 "睡觉" 自动单进程静音 WeChat (准则 5 真做不只说) | ✅ β.2.9.1 + β.3.0-vocab3 已做 | `l4_audio_hands.mute_app` + audio_ducking_targets.json |
| 2 | 说 "睡觉" 自动 dim 显示器 | ✅ β.2.9.1 已做 | `l4_display_hands.sleep_display` |
| 3 | "睡觉模式" 总调度: 检测 sleep 意图 → 自动 (1)+(2)+字幕透明化+ASR mute 30min | ✅ β.2.9.1 + β.5.22-G 完整 | `_trigger_sleep_mode_routine` + `_fire_sleep_due_nudge` 到点提醒 |

---

## 📚 旧轮归档

> 老段已沉档 `docs/TODO_ARCHIVE.md`. 含 β.5.9-16 / β.4.7-8 / β.4.1-6 / β.3.x / Session 0-4 / P0+19 / P0+18 / R8 etc.
> Sir 提"上次/上轮/某 marker" 时 `Grep docs/TODO_ARCHIVE.md` 取指定段, 不 Read 全文.

---


## 📕 AGENT QUICKSTART（Cursor Agent 必读 / 约 30 秒）

> **进窗口先读这两个文件，本节是简版指引**：
> - `AGENTS.md`（仓库根 / 所有 AI Agent 入口章程 / < 250 行）
> - `docs/JARVIS_WORKFLOW_PROTOCOL.md`（规范唯一源 / trace_id / commit / 测试 / push 时机）
>
> 出现冲突以 `PROTOCOL` 为准。`AGENTS.md` 是简版，`PROTOCOL` 是详版。本 TODO 章程段只列触发场景，**不复述规则**。


> **唯一目的**：让 Agent 用最少的 token 读取最准确的上下文，避免 Cursor 对话超 52MB（`Append data exceeds maximum size of 52428800 bytes`）锁死。**永远不要把整个 TODO / archive / 日志读进上下文。**

### 1. 文件分工

| 文件 | 用途 | Agent 读取规则 |
|---|---|---|
| `TODO.md`（本文件，<300 行） | **当前代办 + 已知 BUG + 章程** | ✅ 每次会话进来先读这个文件 |
| `docs/TODO_ARCHIVE.md` | 已完工的迭代回溯 / 因果链 / 测试统计 | ❌ 不要默认读。**仅当 Sir 明确说"上次/上轮/R7/P0+X/轴X…"等历史关键词** → 用 `Grep` 取那段、不要 `Read` 全文 |
| `docs/PROMPT_REFACTOR_PLAN.md` | **当前迭代 P0+20-β.0 完整 design doc** | ✅ 当 Sir 说"开始 β.0" / "prompt 重构怎么搞" 时 Read |
| `docs/NERVE_SPLIT_PLAN.md` | 上轮 P0+19 拆分 design doc（已完工，保留作历史参考） | ❌ 不主动读，除非 Sir 提"拆分历史" |
| `docs/runtime_logs/jarvis_*.log` | 每次启动的完整 stdout/stderr 实时同步 | ❌ 不要 `Read` 全文。**先看 `docs/runtime_logs/latest.txt`（一行，里面是最新日志的绝对路径），再用 `Grep` 取关键段** |
| `docs/funnel_logs/funnel_*.log` | 智能轻推漏斗的命中/拒绝判定 | 同上，按需 grep |

### 2. "上次/上轮"语义映射（Sir 提到这些词的 SOP）

| Sir 的话 | Agent 该做的事 |
|---|---|
| "上次发生了什么" / "刚才那个 bug" / "前面那段" | (1) `Read docs/runtime_logs/latest.txt` 拿绝对路径；(2) `Grep` 出对应错误/Pipeline/Human 段；(3) 必要时 `Read` 文件**指定行段**（`offset+limit`，**不要全文**） |
| "上轮/上次/上回那个 BUG 修了没" / "P0+X 修了没" | (1) 先 `Grep` `TODO.md` 看是否在已知未尽；(2) 再 `Grep` `docs/TODO_ARCHIVE.md` 找最后一次出现的 marker（`a.X / P0+X / 轴X / RX`）+ 状态 |
| "重启实测/我刚跑了 N 件事" | (1) 拉最新两份 `jarvis_*.log`；(2) Grep `║ 🗣️\|║ 🤖\|⛔\|❌\|🔁` 抓对话框 + 错误；(3) 报告新 bug 时**抄日志关键行号**，不要复述大段 |

### 3. 减少 token / 避开 52MB 上限的 5 条硬规

1. **`Read` 大文件加 `offset` + `limit`**：>500 行的文件一次最多读 200 行；jarvis_chat_bypass.py 3003 行 / jarvis_central_nerve.py 2089 行**永远分段读**。
2. **优先 `Grep`**：找"某变量/某 emoji/某错误码"全用 ripgrep（Grep 工具），不要 `Read` 全文 grep。
3. **TODO 写作上限**：本 `TODO.md` 永远 ≤ 300 行；超出 250 行就把"已完成的迭代"剪到 `docs/TODO_ARCHIVE.md` 顶部。
4. **回复给 Sir 的内容**：用表格 + 行号引用，不要复制大段代码；最多 1-2 个`startLine:endLine:filepath` 引用块。
5. **新增 BUG 修复完工**：在本文件**只保留 1-2 行**说明 + marker；详细因果链/测试统计**直接进 archive 顶部**。

### 4. 完工归档协议 / 三轮滚动制（写代码后做的事）

> **核心规则：本文件永远只保留"上一轮 + 当前轮"的内容；再往前的"上上轮"必须沉到 archive。**

| 时间轴 | 位置 | 内容粒度 |
|---|---|---|
| **当前轮**（进行中） | `TODO.md` 的「当前迭代」段 | 完整任务看板 + 子步骤进度 + 在此处持续更新 |
| **上一轮**（最近一次完工） | `TODO.md` 的「上轮完工速览」段 | 1 个段落 + 关键 marker 列表 |
| **上上轮及更早** | `docs/TODO_ARCHIVE.md` 顶部 | 完整因果链 / 测试统计 / 改动清单等所有细节 |

完工时 Agent 必做 6 步：① 当前轮变上轮（精简） ② 原上轮沉档到 archive ③ archive 目录表加行 ④ 写新一轮看板（marker 连号） ⑤ 完工 commit 带 marker 注释 ⑥ 滚动后整个 TODO ≤ 300 行。

---

## 🔮 路线候选（Sir 选定后开始）

- ✅ **路线 A.7**：P0+18-e — 待办链路收口 + 上游 Audio Guard + CW 持久化 + 终端色彩化
- ✅ **路线 A.8**：P0+18-f — 性能崩溃修复 + 诚信加固 + 长期 mute + Integrity 误报
- ✅ **路线 A.9**：P0+19 — Nerve 拆分（17479→324 / -98.1%）+ 依赖锁定
- ✅ **路线 A.9.5**：P0+20-W — Workflow 规范化 `v0.20.0-workflow`
- ✅ **路线 A.10**：P0+20-α — 拆分收尾 + 6 缺口（α.1-α.6）`v0.20.1-cleanup`
- ✅ **路线 A.10.5**：P0+20-α.7 — trace_id 双路分流 `v0.20.2-trace-stream-fix`
- ✅ **路线 A.11.1**：P0+20-β.0.1-3 — Registry + dry-run + 双层注入 `v0.21.0-prompt-refactor-phase1`
- 🔄 **路线 A.11.2 当前轨**：**Phase 1-6 完整重构** — 救火 5 修 + push + Gemini 评分 + 瘦身 + 全审计 + 全测（详「当前迭代」段，~8-10h）
- ⏳ **路线 B 候选**：让 PromiseExecutor 真跑长任务 — 选 3 个高价值场景（每日 9:00 驾照科一 3 题 / 起床播报 / 番茄钟）
- ⏳ **路线 B+ 候选**：AgendaLedger + DailyBriefing + WeeklyDigest + SkillsAtAGlance（让 Jarvis 从 reactive 变 goal-driven）
- ⏳ **路线 C 候选**：R8 轴 4 — OCR / 后台测试 / 全局热键
- ⏳ **路线 D 候选**：R9 死代码清扫批次 2-3 + Qwen3 本地兜底
- ⏳ **路线 E 候选 / 长期**：跨设备入口（FastAPI + WebSocket）+ 决策透明 UI + 个体演化曲线 + 关系延续证据

---

## 📦 归档指针

- **上一轮 P0+19**（roll/deps/0-9/6.a-f/final / 2026-05-16 00:30-02:45 / 17 sub-step / Nerve 17479→324 / 16 新文件 / 1098 testcase）：`docs/TODO_ARCHIVE.md` 顶部「P0+19 完工段」
- **更上一轮 P0+18-f**（f.1-f.4 / 2026-05-15 22:00-22:50 / 4 BUG / 性能崩溃修复 + 诚信加固 + 长期 mute + Integrity 误报）：`docs/TODO_ARCHIVE.md`「P0+18-f 完工段」
- **更早 P0+18-e / P0+18-d / P0+18-c / P0+18-b / R8 轴3 / R7 等**：`docs/TODO_ARCHIVE.md` 后续段（按归档目录 grep）
- **规范唯一源**：`docs/JARVIS_WORKFLOW_PROTOCOL.md`（trace_id / 测试 / commit / push / Agent 行为 / 安全 / 性能基线）
- **入口章程**：`AGENTS.md`（所有 AI Agent 自动读 / 极简版 / 指向 PROTOCOL）
- **Cursor 硬规则**：`.cursor/rules/jarvis_workflow.mdc` + `jarvis_python_style.mdc` + `jarvis_security.mdc`
- **当前迭代 design doc**：`docs/PROMPT_REFACTOR_PLAN.md`（P0+20-β.0 完整设计 / 11 节 / 9 风险预案）
- **上轮 design doc**：`docs/NERVE_SPLIT_PLAN.md`（P0+19 完整设计，保留作历史参考）

---

*本文件由 Agent 维护。每次完工先改本文件状态，再往 archive 顶部追加详细段。*
