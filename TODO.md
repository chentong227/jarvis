# Jarvis TODO

## 🎯 Sir 想要的新功能 (β.2.9 候选, 等下次启动)

| # | 功能 | 现状 | 实现方向 |
|---|---|---|---|
| 1 | 说 "睡觉" 自动单进程静音 WeChat (准则 5 真做不只说) | 缺 organ.command | 扩 `l4_audio_hands.py` 加 `mute_app(name)` 用 pycaw 单进程音量控制 |
| 2 | 说 "睡觉" 自动 dim 显示器 | 缺 organ | 新 `l4_display_hands.py` 用 Win32 SetBrightness / monitor power state |
| 3 | "睡觉模式" 总调度: 检测 sleep 意图 → 自动 (1) + (2) + 字幕透明化 + ASR mute 30min | 流程已有 (`SleepIntent`) 但缺 hook | sleep_intent → 触发 sleep_mode_routine() 依次调上述 |

 工作板

**更新时间**：2026-05-18 23:23（**🚀 P0+20-β.4.6 L3 Directive vocab 半化 — text+metadata 提到 JSON. 18 directive vocab 化. 准则 6.5 完成度 → 95%+**）。

**今天累计 (5/18 09:00-23:23)**：41 commits / 96/96 testcase 全绿 / 新增 ~461 testcase / 12 tags: `v0.27.0-dashboard` + `v0.28.0-integrity-pact` + `v0.28.1-fastcall-async` + `v0.28.2-closure-loop` + `v0.28.3-vocab-substrate` + `v0.30.0-six-bugs` + `v0.31.0-dynamic-vocab-substrate` + `v0.31.1-claim-enforce` + `v0.32.0-claim-classify` + `v0.33.0-dashboard-integrity` + `v0.34.0-integrity-reflector` + `v0.35.0-directive-vocab`。

**🟢 β.4.6 L3 Directive vocab 半化完工 (Sir Session 5 / 准则 6.5 完成度 → 95%+)**:

| 项 | 变化 | testcase |
|---|---|---|
| `memory_pool/directives_vocab.json` (新, 18 seed) | 18 directive 的 text+priority+state+tier_whitelist+ttl_days+source_marker 提到 JSON. _meta 含 schema_version/states_canonical/edit_via/auto_propose/consumer | 27 测 6 类 |
| `jarvis_directives.py` 加 `_load_directives_vocab` + `_TRIGGER_BY_ID` + `_VOCAB_CACHE` | mtime cache + fail-safe 返 None / 损坏 / 无 directives 字段全 fallback | TestVocabLoad 6 测 |
| `jarvis_directives.py` `bootstrap_default_registry` 改 | 优先读 JSON + py trigger 组装; JSON 缺/全 skip → fallback seed_defs (18 内嵌 hardcode 保留作 seed). state='active' 才注册 (review/dormant/archived 跳过, 准则 7) | TestBootstrap 4 测 |
| `jarvis_directives.py` 加 `_bootstrap_seed_only` | testcase 强制 fallback 路径 | 复用 |
| `scripts/registry_dump.py` 加 4 命令 | `--show <id>` (text 全文) / `--vocab-list` (按 state 分组) / `--edit-text <id> --new-text-file <path>` (替换 text + 加 note 时间戳) / `--archive <id>` (state → archived) + Windows stdout UTF-8 reconfigure | TestCLI 7 测 (用 contextlib.redirect_stdout 隔离) |
| `tests/_test_p0_plus_20_beta46_directives_vocab_persist.py` (新) | 6 TestClass — TestVocabLoad / TestBootstrap / TestTriggerStillWorks / TestCLI / TestFailSafe / TestRedLines | 27 测 |
| `tests/_runall.ps1` | 注册 β.4.6 testcase | - |

**设计准则 (Sir 选 A 半化方案)**:
- 准则 6.5 持久化 + CLI + L7 propose: text/metadata 全 vocab.json 化 (Sir 改 directive 不需要 .py + git commit + push, mtime cache 自动 reload). trigger 仍 py (Python lambda 不能 JSON, 完成度 95% 而非 100%)
- 准则 7 Sir 元否决: 任何非 active state (review/dormant/archived) 跳过注册, 必须 Sir CLI --activate 才入主链. 非法 state → 强制 review (防 LLM 污染)
- 兼容: directive_registry.json (runtime 计数 gitignored) + directive_review.json (legacy decay queue) 全部不动. _test_p0_plus_20_b01_directive_registry.py 旧 testcase 仍 pass (无 regression)
- L7 IntegrityReflector `_propose_directive` 不改 (仍写 legacy directive_review.json), 暂不强求统一到 directives_vocab.json review state — 保留作 β.4.7 可选优化

**Session 5 commit + tag**: `465ee18` / `v0.35.0-directive-vocab`, 96/96 pass run_id `test_20260518_231100_xxxx` (dur 361.79s).

**真机风险点清单 (β.4.6 引入, Sir 黑箱测试看这些)**:
1. **JSON 损坏导致 directive 失效** — _load_directives_vocab fail-safe 返 None → bootstrap fallback 到 seed_defs 18 条 hardcode. 真机 vocab 损坏 bg_log 会写 "directives_vocab.json 不可用, fallback 到 18 条 seed", Sir 看 latest.log 即可
2. **mtime cache 缓存陈旧** — Sir 改 vocab 后 mtime 自动变化触发 reload. 但若 git checkout 还原文件, mtime 也变 → 自动 reload. 极端: NTFS 1s 精度若同秒多次改可能漏 reload
3. **Sir CLI --edit-text 后未重启 Jarvis** — bootstrap 已注册的 Directive 实例不变. 重启或调 `jarvis_directives.reload_directives_vocab()` + `_DEFAULT_REGISTRY=None` + `get_default_registry()` 才能用新 text
4. **_TRIGGER_BY_ID 字典未填** — bootstrap 第一次跑会自动填 (从 seed_defs 抽). 若 Sir 加新 directive id 但 .py 端无对应 trigger 函数 → bootstrap "no-trigger" skip + bg_log
5. **state 字段非法** — 非 'active'/'review'/'dormant'/'archived' → 强制改 'review'. 若 Sir 误写 'enabled' 等 → 不会注册, Sir CLI --activate 才能修正

**🟢 β.4.5 INTEGRITY_STACK Session 4 完工 (准则 7 Sir 仲裁 + 准则 6.5 Reflector 自我修正闭环)**:

| 项 | 变化 | testcase |
|---|---|---|
| `jarvis_integrity_reflector.py` `dump_claim_stats` + `ClaimStatsDumper(Thread)` | 60s tick daemon dump `_CLAIM_STATS` → `memory_pool/claim_stats.json` 跨进程 (β.4.4 dashboard verify_rate hook 至此生效); `_stop_event` 避 Python 3.9 Thread._stop 冲突 | 16 测 5 类 |
| `jarvis_integrity_reflector.py` `IntegrityReflector(Thread)` | L7 LLM-propose daemon. 7d audit + LLM (Gemini-3.1-pro/2.5-flash-lite fallback) → propose 3 类 review queue: claim_classify keyword / evidence_kind requirement / directive. 触发: weekly 3d 兜底 OR audit≥50 + Sir idle>4h. max_propose=5/run | 30 测 6 类 |
| `jarvis_integrity_reflector.py` `_propose_claim_classify/evreq/directive` | 三类 propose 应用器: dedup (同 id / 同 type+kind) + canonical 列表强制 (claim_type 6 类 / evidence_kind 7 类) + state=review + source=integrity_reflector + atomic write | 准则 7 强制覆盖 |
| `jarvis_central_nerve.py` daemon 注册 | ClaimStatsDumper (β.4.5.1) + IntegrityReflector (β.4.5.2 注入 key_router) 在 Reflectors block 之后启动; 任一失败 fail-safe 静默 | smoke + cross-module |
| `.gitignore` 加 `memory_pool/claim_stats.json` + `memory_pool/*.bak` | runtime 残留 防入库 | - |
| `tests/_test_p0_plus_20_beta451_claim_stats_dump_persist.py` | 5 TestClass / 16 测 — TestDumpStatsToDisk / TestFailSafe / TestClaimStatsDumper / TestCrossModule / TestRedLines | 16 测 |
| `tests/_test_p0_plus_20_beta452_integrity_reflector_persist.py` | 6 TestClass / 30 测 — TestReflectorInit / TestShouldReflectNow / TestReflectIntegrityAudit (LLM mock) / TestProposeWriters / TestFailSafe / TestRedLines | 30 测 |

**设计准则**:
- 准则 5 言出必行: ClaimStatsDumper 让 dashboard 兑现率从 in-memory counter 跨进程兑现 (β.4.4 hook 真接通); IntegrityReflector 反思 audit 提建议给 Sir 而非"已优化"空话
- 准则 6 反硬编码: INTEGRITY_REFLECTOR_PROMPT 只约束 schema, 不教 LLM 具体中文/英文措辞 (TestRedLines 锁"已经/完成了"等不入 prompt)
- 准则 6.5 持久化+CLI+L7 自我修正: 三类 propose 全 review 入 `memory_pool/*.json` (state=review), Sir 用既有 CLI `scripts/claim_classify_dump.py / evidence_req_dump.py / registry_dump.py --review-list` 看 + `--activate <id>` / `--reject <id>` 仲裁
- 准则 7 Sir 元否决: propose 默认 state=review 永不自动 active. dedup + canonical 双校验防 LLM 污染. INTEGRITY_STACK L7 至此闭环

**INTEGRITY_STACK 7 层架构现状 (L0-L7 全立)**:
- L0 ✅ PERSONA INTEGRITY ABSOLUTE
- L0.5 ✅ Dynamic Vocab Substrate (7 vocab Session 0)
- L1 ✅ Claim Classifier (β.4.3.1 Session 2)
- L2 ✅ Evidence Requirements (β.4.3.2 Session 2)
- L3 ⚠️ 17 directive (部分 json 化)
- L4 ✅ ClaimTracer enforce + audit jsonl (β.4.1+β.4.3.3+β.4.2-hotfix Session 1+2)
- L5 ✅ 闭环 A (β.2.9.11)
- L6 ✅ Dashboard 言出必行健康度 (β.4.4 Session 3)
- L7 ✅ IntegrityReflector LLM-propose (β.4.5.2 Session 4 本轮) ← NEW

**Session 4 commit + tag**: `d6b4247` (β.4.5.1) + `9f84743` (β.4.5.2) / `v0.34.0-integrity-reflector`, 95/95 pass run_id `test_20260518_223652_xxxx` (dur 362.26s).

**真机风险点清单 (Session 4 引入, Sir 黑箱测试看这些)**:
1. **ClaimStatsDumper 启动失败** — central_nerve init 异常时 daemon 不起, dashboard verify_rate 仍 "--"; bg_log 会写 `[ClaimStatsDumper] 初始化失败` Sir 看 latest.log 即可定位
2. **IntegrityReflector LLM 调用风险** — audit ≥ 50 触发, 走 key_router 取 openrouter_key 调 Gemini-3.1-pro/fallback. timeout 15s + fail-safe 静默. 没 LLM key 时 `_call_llm` 返 '' 不 raise
3. **propose 重复 / dedup 失效** — 同一 keyword 已 review 但 LLM 又生成 → dedup `same-id skip`; 但若 LLM 改 id 而 keyword 内容一样, dedup 漏抓. β.4.6 可考虑 keyword set 重叠 fuzzy dedup
4. **vocab json 损坏自愈** — `_load_vocab_atomic` 损坏文件 fail-safe 返 `{'patterns': []}`, 但这会让 propose 写入"空 vocab" 即覆盖原数据. 慎重: testcase 已锁此场景, 但 prod 时若 vocab 真损坏建议 Sir 先 git checkout 还原
5. **触发条件 Sir 视感差** — daemon 反思频率 3d 兜底 + audit≥50, Sir 觉得"太慢看不到效果". CLI `python -c "import jarvis_integrity_reflector as ir; r=ir.get_default_integrity_reflector(); print(r.force_run_now())"` 强制跑一次

**🟢 β.4.4 INTEGRITY_STACK Session 3 完工 (准则 5 L6 Sir 一眼看 Jarvis 兑现率)**:

| 项 | 变化 | testcase |
|---|---|---|
| `scripts/jarvis_dashboard.py` `_safe_read_jsonl_tail` | file seek -512KB tail 防 jsonl > 100K 条全 load + partial 首行丢弃 | 1 cross-module |
| `scripts/jarvis_dashboard.py` `read_integrity_stats` | 今日/7d 聚合 + kind 分布 + top 3 高频空头话 + 7d ASCII trend chart + verify_rate hook (Session 4 daemon 兼容) | 6 类 27 测 |
| `scripts/jarvis_dashboard.py` `_render_integrity` + `card_integrity` | 宽卡跨 4 列 (group_obs row 1) + lbl_integrity 标题徽章 + `_make_card` 加 columnspan/height kwargs (兼容老 caller) | UI 渲染 + 中文文案准则 6 |
| `scripts/jarvis_dashboard.py` `compute_overall_status` | 加 integrity 入参 + 阈值 (今日 unverified 0 绿 / 1-5 黄 / >5 红) → headline 直接说事 | 4 阈值测 |
| `scripts/jarvis_dashboard.py` reader bucket-day bug fix | ts 不对齐 00:00 时偏移 1 天 (如 d-3 12:00 落到 d-2 桶), 修法: 先用 ts_day_start 对齐再算 day_offset | trend_7d 测覆盖 |
| `tests/_test_p0_plus_20_beta44_dashboard_integrity_persist.py` | 6 TestClass / 27 测 — TestReadIntegrityStats / TestFailSafe / TestTimeWindow / TestThreshold / TestRenderUI / TestCrossModule | 27 测 |

**设计准则**:
- 准则 5 言出必行: dashboard 数据全 trace 到 jsonl 真实 evidence (`integrity_audit.jsonl`); compute_overall_status 阈值 crit/warn 直接量化 Jarvis 言出必行健康度
- 准则 6: dashboard UI 文案是 Sir 看的事实陈述, 不教主脑句式 (TestRenderUI 锁 "你必须"/"立刻" 红线)
- 准则 6.5: jsonl/stats.json 全部 fail-safe (文件不存在/损坏行/损坏 ts/损坏 stats 全返默认 dict 不 raise); verify_rate 缺 claim_stats.json 时 fallback None (Session 4 daemon 加后自动生效)
- 防御 dual-track: TestCrossModule 显式验 ClaimTracer.write_audit_entry → dashboard reader 端到端协作 + file-seek 大文件 5000 条 fixture

**Session 3 commit + tag**: `7bbd890` / `v0.33.0-dashboard-integrity`, 93/93 pass run_id `test_20260518_213535_4ad0`.

**真机风险点清单 (Session 3 引入, Sir 黑箱测试看这些)**:
1. **dashboard 卡片不出现 / 文案错位** — group_obs row 1 weight 改了 (0=2/1=1), 老卡片可能挤压. 真机看 dashboard 4 上+1 宽卡 layout 是否正常
2. **跨夜 trend_7d 偏移** — Sir 中国本地时区 (UTC+8), `time.timezone` 偏移; 真机零点跨夜可能短暂出现今天 0 件但 d-1 突然 +N 的视觉抖动
3. **0 字节 jsonl 文件** — 文件存在但 0 字节时显 "✅ 7 天 0 件" 而非 "📝 还没有任何 audit"; 这是设计决定 (文件存在 = ClaimTracer 跑过, 只是 0 unverified). Sir 若觉得迷糊 → 文案改
4. **claim_stats.json 缺失** — verify_rate 卡片显 "兑现率 -- (Session 4 daemon 待加)"; Sir 看到此即知 Session 4 daemon 没起
5. **大文件性能** — 5000 条 audit (~700KB) 测试通过 file seek -256KB; 真机 jsonl > 1MB 时无回归 (file seek 上限 512KB cap on memory)

**🟢 β.4.3 INTEGRITY_STACK Session 2 完工 (准则 6.5 L1+L2 表驱替换硬编码 / L4 重写)**:

| 项 | 变化 | testcase |
|---|---|---|
| `jarvis_claim_classifier.py` + `memory_pool/claim_classify_vocab.json` + `scripts/claim_classify_dump.py` | L1 7 类 (Past/Future/State/Recall/Social/Tool/Unknown) keyword + kinds_hard_map + mtime cache + seed fallback | β.4.3.4 covers |
| `jarvis_evidence_requirements.py` + `memory_pool/evidence_requirements.json` + `scripts/evidence_req_dump.py` | L2 evidence kinds: tool_results_success/any / stm_match / ltm_match / system_clock_within_2min / promise_log_recorded / uncertainty_marker_nearby | β.4.3.4 covers |
| `jarvis_claim_tracer.py:trace_to_evidence` | `use_vocab=True` 默认走 L1+L2; 老路径 `_trace_via_legacy` 保 β.2.8.7 回归; `_LEGACY_TRACE_LABEL` alias 老短名 | β.4.3.4 + β.2.8.7 双绿 |
| `jarvis_chat_bypass.py` trace_reply 调用点 | 加 `system_clock=time.time()` + `ltm_context` 入参, 治本 β.4.2-hotfix `time` claim 死循环 | bg_log diag |
| `tests/_test_p0_plus_20_beta434_claim_classify_evidence_persist.py` | 9 TestClass — L1+L2+L4 + cross-coupling + 红线 + CLI + dual-track 真机风险口 | 54 测 |

**设计准则**:
- 准则 6.5: L0/L1/L2 全部 vocab + CLI + L7 待 (Session 3); 任一层缺失/损坏均 fail-safe 回退 (legacy / 视为 verified)
- 防御 dual-track: TestCrossModuleCoupling 显式验 vocab_path=bogus 时不 raise 不阻塞主链
- β.4.2-hotfix 治本: time claim 现 SYSTEM CLOCK ±2min verify, 取代 audit_skip (skip 保留 defense-in-depth)

**Session 2 commit + tag**: `0d62236` / `v0.32.0-claim-classify`, 92/92 pass run_id `test_20260518_200142_2154`.

**真机风险点清单 (Session 2 引入, Sir 黑箱测试看这些)**:
1. **L1 关键词冲突边界** — "open notepad" 现归 Tool 而非 State (State `正在/当前/现在` 已删). 若 Sir 看到 "现在" 被分错 → grep `claim_classify_vocab.json` 看 keyword 顺序
2. **L2 evidence_kind 漏匹配** — Past 类必须 tool_results 含 ✅ 才算 verified; 若 Jarvis 真做了事但 tool 没回 ✅ → 会被判 unverified 反复 ALERT, 走 `memory_pool/evidence_requirements.json` CLI 加 evidence kind 或下调 strictness
3. **time claim 系统时钟漂移** — `system_clock_within_2min` 是 ±120s; 跨夜 / Sir 改系统时间 → 可能误判. 真机如出现 → 看 `jarvis_claim_tracer._parse_time_to_hm` 时区/24h 兼容
4. **ltm_context 截断 2000 字** — `jarvis_chat_bypass.py:3238` 上限; LTM 段超长 → 尾部 Recall claim 可能误判 unverified
5. **vocab 文件 IO 故障** — 任一 json 损坏均走 seed fallback (`_SEED_VOCAB`); Sir 看 bg_log `[ClaimClassifier] vocab load failed` / `[EvidenceReq] vocab load failed` 诊断

**🟢 β.4.1 INTEGRITY_STACK Session 1 完工 (准则 5 言出必行 — L4 ClaimTracer 从 trace 升级 enforce)**:

| 项 | 变化 | testcase |
|---|---|---|
| `jarvis_claim_tracer.py` | + `write_audit_entry()` / `read_recent_unverified()` / `build_integrity_alert()` / `_INTEGRITY_AUDIT_PATH`; `trace_reply` unverified 分支 hook 入 jsonl | 5 类 30 测 |
| `jarvis_central_nerve.py:_assemble_prompt` | 入口调 `build_integrity_alert(current_turn_id)` → prepend 到 `system_alert_text` (5 template auto-pick up) + bg_log 诊断 | grep test |
| `memory_pool/integrity_audit.jsonl` | 新 incident log (.gitignore 已 cover `memory_pool/*.jsonl`) | red line test |

**设计准则**:
- 准则 5: ALERT 包含 prior_turn_id + count + claim text + 2 选项 (withdraw / supply evidence)
- 准则 6: ALERT 不教具体中文/英文句式 (`test_alert_does_not_prescribe_chinese_phrasing` 锁红线)
- 准则 6.5: `audit_path` 可注入 (testcase 隔离); jsonl append-only; 仅 unverified 入表 (防膨胀)

**Session 1 commit + tag**: `d36e9eb` / `v0.31.1-claim-enforce`, 89/89 pass run_id `test_20260518_172619_fa3d`.

---

**🟢 β.3.4 INTEGRITY_STACK Session 0 完工 (准则 6.5 L0.5 横向贯通层全量落地, 7 vocab × ~330 keyword)**:

| # | vocab | 迁出位置 | json + CLI | testcase | commit |
|---|---|---|---|---|---|
| 1 | tool_intent | jarvis_directives | `tool_intent_vocab.json` + `tool_intent_dump.py` | 15 | β.3.0-vocab1 |
| 2 | dashboard_intent | jarvis_directives | `dashboard_intent_vocab.json` + `dashboard_intent_dump.py` | 已并入 #1 | β.3.0 |
| 3 | memory_correction | jarvis_directives | `memory_correction_vocab.json` + `memory_correction_dump.py` | 11 | d748f1a |
| 4 | inconsistency | jarvis_inconsistency_watcher | `inconsistency_vocab.json` + `inconsistency_vocab_dump.py` | 10 | bdfb377 |
| 5 | response_classify | jarvis_proactive_care | `response_classify_vocab.json` + `response_classify_dump.py` | 13 | b3905aa |
| 6 | feedback (regex) | jarvis_memory_core.FeedbackTracker | `feedback_vocab.json` + `feedback_vocab_dump.py` | 12 | 9922564 |
| 7 | concern_keywords | jarvis_soul_reflector | `concern_keywords_vocab.json` + `concern_keywords_dump.py` | 16 | 0c663e6 |

**Session 0 范式 (7 vocab 全部一致, Sir CLI 改 json + 不必重启)**:
- `_SEED_<X>` fallback (py 源码仅写 seed, json 损坏/不存在 → 走 seed)
- `_load_<X>_from_json()` + `get_<X>()` mtime cache loader (Sir 改 json → 下一次调用即生效)
- `scripts/<X>_dump.py` CLI list/add/activate/reject/delete + active/review/archived 三态
- `_test_p0_plus_20_beta34_vocab<N>_<X>_persist.py` 7 测覆盖 fallback / mtime reload / 损坏 json / CLI / 兼容 / 红线 (旧名 must be gone)
- 兼容垫层 (concern_keywords): `CONCERN_KEYWORDS` module-level snapshot 保留, 老 import 不破

**Session 0 验收**: kickoff doc §210-218 三条 grep (`_PATTERNS=[\|(`, `_KEYWORDS=[\|(`, `_VOCAB=[\|(`) 在 7 vocab 范围内全清干净, 剩余命中均为非 Session 0 scope (worker tier router / refusal classifier / ANSI color / commitment parser regex / predicate heuristic — 待后续 session 治).

**Session 0 v0.31.0-dynamic-vocab-substrate tag**: commit 0c663e6 (vocab7) 处, 88/88 pass run_id `test_20260518_170331_756d`.

---

**Sir 14:00 实测 6 BUG 全治本 (β.3.0)**:

| # | BUG | 现象 | 治本 |
|---|---|---|---|
| 1 | `dashboard.cmd` 静默失败 | pythonw 隐藏 console, error 看不到 | cmd 默认 python.exe 拉 console + `--quiet` 选项保留 pythonw |
| 2 | "给我看" 过广 | "烦打开给我看一下" 误触发 dashboard | vocab 迁 `memory_pool/dashboard_intent_vocab.json` + CLI + "给我看" archived |
| 3 | `dashboard_open` 未知指令 | chat_bypass 重启没生效 | 端到端 testcase 防回归 + 进程 poll() 假成功修 |
| 4 | 言行不一 "已打开" | tool 失败但主脑说"已打开" | ClaimTracer L4 加 `past_action` 类 + directive `past_action_honesty` (priority 10) |
| 5 | 睡觉瞬间黑屏 | delay_sec=0 立即 sleep_display | 强制最小 30s 倒数 + `cancel_sleep_routine()` + Sir "等等/取消" vocab 触发 |
| 6 | 微信静音没生效 | 硬编码 `'WeChat'` 单进程 + 进程名变体 (WeChatAppEx) 不匹配 | vocab 迁 `memory_pool/audio_ducking_targets.json` + 循环 mute 所有 active + CLI |

**β.3.0 新增 vocab json + CLI (Sir 准则 6.5 治本, 3 个 vocab)**:
- `memory_pool/dashboard_intent_vocab.json` + `scripts/dashboard_intent_dump.py` (Sir 自删过广词)
- `memory_pool/audio_ducking_targets.json` + `scripts/audio_ducking_dump.py` (Sir 自加 sleep 静音目标)
- `memory_pool/sleep_cancel_vocab.json` (Sir 自加撤回睡眠的关键词)
- 全部走"mtime cache + active/review/archived 三态 + seed fallback" 范式 (同 β.3.0-vocab1 tool_intent)

**β.3.0 ClaimTracer L4 升级 — 言行不一治本**:
- 新增 `past_action` claim 类 (regex 抓"已打开/已发送/I've opened"等)
- `trace_to_evidence` 加 past_action 专用路径: 必须 tool_results 含 `✅` 才算 verified
- 没 ✅ → unverified → log + 将来 SoulAlignment missed
- 新 directive `past_action_honesty` (priority 10) 教主脑: 不能在 tool result 来之前说"已 X"

**β.2.9.12 灵魂级升级**:
- **准则 6 升级**: AGENTS.md 加第 5 类反例 (vocab 写死 in py) + 准则 6.5 "动态架构必须 + LLM 兜底" (Sir 12:57 立)
- **L0.5 立项**: INTEGRITY_STACK v1.1 加横向贯通层 Dynamic Vocab Substrate, 所有 7 层共享 3 硬规
- **β.2.9.12 vocab 治本**: `_BEHAVIOR_PATTERNS` 从 py 迁 `memory_pool/behavior_inference_vocab.json` + `scripts/behavior_vocab_dump.py` CLI + mtime cache 自动 reload + 6 testcase 验证
- **新窗口接手 prompt**: `docs/AGENT_KICKOFF_INTEGRITY_STACK.md` 完整一次性复制版, Sir 开新窗口贴即用

**最重大突破** — 诚信审计治本: Sir 10:51 发现 Jarvis "我已更新记录" 是空头话 (CorrectionMemory 表 84h 0 写入). 修法 5 件 (准则 5 言出必行 + 准则 6 不硬编码):
- **A**: directive `memory_update_honesty` 拦"已更新"假话 (除非真 emit MEMORY_UPDATE)
- **B**: ProfileCard.apply_correction 真持久化到 `memory_pool/profile_corrections.jsonl`
- **C**: FeedbackTracker vocab 升级 — 中文 substring + 扩词典覆盖"其实/澄清/搞错/两码事/actually/i meant"
- **D**: 新结构化标签 `<MEMORY_UPDATE field='X' old='A' new='B'/>` — 主脑要说"已更新"必须先发标签
- **E**: dashboard 加"信任审计 (今天真改了什么)"卡片 — Sir 一眼看 jsonl 写入

**Sir 11:09 工具流卡顿修** (反对占位语音 "没人味", 准则 6 主脑自由):
- directive `tool_overture` 教主脑在 FAST_CALL 前自然过渡话 1 句
- tool 执行期间 Sir 听到主脑真生成的话, 不是模板

**Sir 11:09 dashboard 集成主脑** (模糊语义启动):
- chat_bypass.ui_control 加 dashboard_open/close (pythonw.exe detached)
- directive `dashboard_intent` 让"面板/总览/看看状态" 触发主脑 emit FAST_CALL

**β.2.9.7-9 本轮 13 commits 链路**:

| commit | marker | 主题 |
|---|---|---|
| 92c2a8f | β.2.9.7 | InconsistencyWatcher 反复 fire + PromiseLog 测试污染 (3 道防御) |
| c77c968 | β.2.9.7-α | CommitmentWatcher 时间锚启发式 — 治"I will sleep at 11"+1h BUG |
| c90a3a3 | β.2.9.7-β.1 | ProactiveCare LIVE 默认 + SmartNudge disable 开关 + 启动 banner |
| ab5a396 | β.2.9.7-γ.2 | scripts/proactive_care_tail.py 实时观察 |
| a4951c8 | β.2.9.7-β.1.1 | dry_run 切换 test 回归修 |
| 0aa5216 | β.2.9.7-docs | TODO 滚档 |
| 617c428 | β.2.9.8 | dashboard v1 三大块 + 真按钮 + Directive 偏移信号 |
| 7d13e0c | β.2.9.9-A | CommitmentWatcher 时间确定性闸门 — 治"剪辑完就行"误注册 |
| 8d98b70 | β.2.9.9-B+C | dashboard pythonw + UI 美化 + concern 动态权重反馈骨架 |
| bcaa650 | β.2.9.9-集成 | Phase D 焦点 + 诚信 ABCDE + 工具流不卡 + dashboard 集成主脑 |
| 6c8df92 | β.2.9.10 | ReturnSentinel 模板兜底删 + return_greeting directive 正向引导避免 'Welcome back' 客套 |
| 128d688 | β.2.9.10-async | FAST_CALL 软超时异步治本工具卡顿 — ThreadPool + 1.5s 超时 + drain pending 注入 |
| 1e4b603 | β.2.9.11 | snippet "y co" 美化 + ProactiveCare skip 日志节流 |
| 3a89168 | β.2.9.11 | 灵魂闭环 A 完工 + INTEGRITY_STACK 7 层架构立项 doc |
| 043af31 | β.2.9.12 | vocab 持久化治本 + 准则 6.5 升级 + INTEGRITY_STACK v1.1 + 新窗口 prompt |

**Sir 重启可立测 8 项**:
1. `scripts\jarvis_dashboard.cmd` (双击) — 中文看板, 三大块 + 真按钮 + 信任审计卡
2. 跟 Jarvis 说"打开面板看看" — 主脑应 emit FAST_CALL ui_control.dashboard_open
3. 说"打开 Chrome" — Jarvis 应先讲过渡话再 emit FAST_CALL (体感不卡)
4. 纠正 Jarvis 一次记忆 (如"职业考试 vs 成绩") — directive memory_update_honesty 应拦"我已更新"假话, 要主脑老实
5. 等 ProactiveCare 主动发声 nudge — Jarvis 出声后 60s 内你直接口头回应 (不喊 Jarvis), Phase D 焦点应接住
6. dashboard 看"信任审计"卡片 — 今天若有 MEMORY_UPDATE 真写入应显示具体 field/old/new
7. 说"我剪辑完视频就行" — 时间确定性闸门应拒注册 hard commitment, 转 PromiseLog soft (不到点闹)
8. 真启 24h 不重启 — InconsistencyWatcher/Curiosity/ProactiveCare 三个 daemon 健康

**下个 session Agent**: 读 `AGENTS.md` → `TODO.md` → `docs/JARVIS_INTEGRITY_STACK.md` → `docs/AGENT_KICKOFF_INTEGRITY_STACK.md` → 优先级:

🟢 **β.4.6 L3 Directive vocab 半化** ✅ 完工 commit `465ee18` / tag `v0.35.0-directive-vocab`. 18 directive text+metadata 提到 JSON, trigger 留 py. 准则 6.5 完成度 95%+.
🟢 **INTEGRITY_STACK Session 4** ✅ 完工 commit `d6b4247` (β.4.5.1) + `9f84743` (β.4.5.2) / tag `v0.34.0-integrity-reflector`. L7 IntegrityReflector LLM-propose daemon + ClaimStatsDumper 跨进程持久化. 7 层 L0-L7 全立.

🔴 **下一任务 (Sir 拍板)**:
   - 选项 A: **Sir 真机黑箱测** β.4.5.x + β.4.6 风险点 (见上文真机风险点清单), 实机反馈后再 push / 修
   - 选项 B: **进 SOUL_DRIVE 推进** (灵魂工程 Layer 4+: AlignmentEvaluator / RelationalState reflector 二阶段等), 详 `docs/JARVIS_SOUL_DRIVE.md`
   - 选项 C: **Sir 想要的新功能 §1-3** (sleep 模式: 单进程 mute WeChat + dim 显示器 + 总调度), 准则 5 "真做不只说" 落地
   - 选项 D: **β.4.7 directive trigger DSL 化** (从 95% → 98%+) — 把 trigger lambda 抽成 JSON DSL (regex_match / and / or / has_pattern), 17 trigger 重写. 风险高, 收益小 (Sir 改 trigger 概率低于改 text), Sir 三思

🟢 **INTEGRITY_STACK Session 3** ✅ 完工 commit `7bbd890` / tag `v0.33.0-dashboard-integrity`
🟢 **INTEGRITY_STACK Session 2** ✅ 完工 commit `0d62236` / tag `v0.32.0-claim-classify`
🟢 **INTEGRITY_STACK Session 1** ✅ 完工 commit `d36e9eb` / tag `v0.31.1-claim-enforce`
🟢 **INTEGRITY_STACK Session 0** ✅ 完工 tag `v0.31.0-dynamic-vocab-substrate`

🟡 dedup 失效 (overbearing 3 次重复)
🟡 LLM 二次判 correction (FeedbackTracker Phase 2)
🟢 Skill Pack 应用控制 (Cursor/Premiere/Excel))

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

## 📌 上轮完工速览（P0+20-W + α + β.0.1-3 / 2026-05-16 10:20-12:30）

> **本日工作量超 P0+19 整轮**：W 规范化 + α 6 修 + β.0.1-3 三阶段 + α.7 trace 双路修复。13 个 commit / 4 个 tag / 49 testcase 持续全绿。
> 完整 commit 链 + tag 见下方「📦 归档指针」。

- **W**（trace_id 体系 + AGENTS + cursor rules + tests/conftest.py + last_run.json + commit 模板）`v0.20.0-workflow`
- **α.1**（jarvis_memory_core 漏 numpy 修）`dea1eb5`
- **α.2**（KeyRouter 永久剔除 + Hippocampus 跳过日志节流）`2a65cc7`
- **α.3**（Integrity declarative pre-filter + have-been 主语收紧）`a8cd656`
- **α.4**（SmartNudge standby 60s 静默窗口）`1764aea`
- **α.5**（malformed FAST_CALL 强 SYSTEM 反馈 + 收手）`8802757`
- **α.6**（39 处 daemon print→bg_log）`1efab47`
- **α.7**（trace_id 双路分流：终端只主体 / 日志带 prefix）`v0.20.2-trace-stream-fix`
- **β.0.1**（jarvis_directives.py Registry + 12 directive bootstrap + 35 testcase）`2f29162`
- **β.0.2**（_assemble_prompt dry-run + DecayWorker autostart）`04bebde`
- **β.0.3**（L2 directive 真切注入 / 双层注入暂态）`v0.21.0-prompt-refactor-phase1`

---

## 📌 旧上轮 P0+19（2026-05-16 00:30-02:45）

> 详细 17 sub-step 看板 + 调研事实 + 改动文件清单 + 测试统计 → `docs/TODO_ARCHIVE.md` 顶部「P0+19 完工段」。
> 完整 design doc → `docs/NERVE_SPLIT_PLAN.md`（保留作历史参考）。

- **起点**：`jarvis_nerve.py` 17479 行已是结构性炸弹 + API key 硬编码 + 无 `requirements.txt`，Claude 4.7 评估后决定 deps 优先 → 拆分 0-9 → final。
- **完工**：roll ✅ / deps 🔄 70%（剩 Sir 手动 4 件）/ sub-step 0-9 + 6.a/b/c/d/e/f + final 全部 ✅ / **jarvis_nerve.py 17479 → 324 行（-98.1% / 超 design doc < 500 行目标 ✓✓✓）** / 拆出 **16 个独立文件** / **1098 testcase 全绿 13 次连续验证零失败** / enhanced.py 循环依赖死。
- **关键 marker**：`P0+19-deps` / `P0+19-1` jarvis_safety / `P0+19-2` key_router+llm_reflector+env_probe / `P0+19-3` sensors / `P0+19-4` routing / `P0+19-5` memory_core / `P0+19-6.a-f` sentinels+conductor+return+commitment+smart_nudge+centers / `P0+19-7` chat_bypass(3003) / `P0+19-8` central_nerve(2089) / `P0+19-9` worker+ui / `P0+19-final`
- **测试**：1098 / 1098 testcase OK，0 FAIL
- **实际耗时**：~3.5h（vs design doc 估 13h，因为用了 batch extract 脚本 + auto-patch 测试）

---

## 🧪 Sir 重启 Jarvis 立刻可验证（≤ 6 条）

1. **TTFT 仍 3s 量级**：随便说一句 → 终端 `[Pipeline Timer] TTFT` 应 2-5s。如慢，`latest.txt` grep `[Perf Diag]` 看 connect / wait / queue_depth
2. **拆分后 import 全通**：`python -c "from jarvis_nerve import KeyRouter, ChatBypass, CentralNerve, JarvisWorkerThread, BreathingLightUI; print('ok')"`
3. **跑测**：`tests\_runall.ps1` 输出 `REGRESSION SUMMARY: 1098+ / 1098+ OK, 0 FAIL`
4. **真机一轮**：启动后跑 "现在几点 / 提醒我 8 点 X / 列出代办" 三步流，无 crash 即拆分后基线稳

---

## 🐛 已知未尽 BUG / 12:43 实测暴露的 7 个新缺口（重点）

> **B1-B7 是 Phase 1 救火直接对应**（F1-F5 修这些）。其它老 BUG 留给 Phase 4 (β.0.6 瘦身) / Phase 5 (架构审计) 一起治本。

### 🆕 Sir 12:43 + 14:30 实测暴露的新 BUG（jarvis_20260516_123813.log）

| ID | 优先级 | BUG | log 证据 | 修复 |
|---|---|---|---|---|
| **B1** | P0 | 时间硬编码偏 AM：Sir 中午说"两点起床" → 凌晨 02:00 | log:100/215 | ✅ **F2** sanitize_trigger_time + prompt 5a 收紧 |
| **B2** | P0 | Memory Correction 把"两点起床"→"两点睡觉" 性质完全变 | log:217 | ✅ **F3** detect_semantic_category + Correction Guard |
| **B3** | P0 | Help Refusal 误触发（Sir 自我打断"不对不对，我我..." 被判拒绝）| log:91-93 | ✅ **F4** 自我打断白名单 10 条 pattern |
| **B4** | P1 | prompt 装配 1274ms → 3074ms（β.0.3 双层注入翻 2.4x）| log:177 | ⏳ Phase 4 β.0.6 瘦身后自然回落 |
| **B5** | P1 | TTFT 暴涨：第三轮 26.7s → Full pipeline 78s | log:121/264/272 | ⏳ 网络抖动 + B7 连锁，瘦身后改善 |
| **B6** | P0 | 声波打印 30K bytes 单行 → PowerShell 阻塞 → 麦克风录乱 | log:88/145/200-205 | ✅ **F1** 100ms 节流 + 段尾换行 |
| **B7** | P1 | google_1 永久剔除策略没持久化（重启后又试又挂）| log:282 | ✅ **F5** memory_pool/key_router_state.json + reset 接口 |
| **B8** | P0 | OfferHelp 未出声：`NameError("name 'JARVIS_CORE_PERSONA' is not defined")` | log:324 | ✅ **F6** chat_bypass.py 函数体内延迟 import |
| **B9** | P0 | 归来感知没出现（Sir 睡 1+ 小时回来）：`win32api` 没 import → idle_ms 永 0 | （静默吞，无显式 log）| ✅ **F7** return_sentinel + smart_nudge + commitment_watcher 全修 |

### 已知老 BUG（治本路径推迟到 β.0.6 瘦身 / Phase 5 全审计）

| 优先级 | BUG | 处理路线 |
|---|---|---|
| **P1** | **β.0/TWO_PARTS**：Sir 一段话同时回应上文+开启下文，Jarvis 只答一半 | β.0.3 directive `continuity_two_parts` 已注入，待真机验证收敛 |
| **P1** | **β.0/future-tense lie**：Jarvis 用未来时编造没有的能力（"I can take a closer look..."）| β.0.6 瘦身 + SkillRegistry capability 反查 |
| **P1** | **β.0/asr_video_leak**：active_conversation 期间视频音被录入 | Phase 5 候选 / 路线 D（VAD / speaker diarization）|
| **P0** | **β.0/false_tool_chain_after_malformed**：第一段判幻觉对了，同轮后段又编 FAST_CALL 假完成 | α.5 已收手 + β.0.6 directive 联动 |
| **中** | **轴 5.2**：CommitmentWatcher 可继续 polish（deadline 排序 / cross-session 反查） | 路线 B+ 候选 |
| **低** | **d.5 留尾**：Memory Correction 中文漏 Audio Guard 上游路径 | 等真机复现 |
| **低** | **OpenRouter / 网络偶慢** | `[Perf Diag]` 日志辅诊 |

---

## 🚧 当前迭代：P0+20-β.0 完整重构（6 Phase / ~8-10h / **进行中 / F1 卡在 Sir 暂停**）

> **总目标（Sir 12:45 拍板）**：
> 1. 修日志暴露的 7 个 BUG（B1-B7）
> 2. push 当前已完工 13 个 commit
> 3. β.0.5 异步评分链接入
> 4. β.0.6 PERSONA iterate（人设不变 / 删旧 inline / prompt 30K→18K）
> 5. 全架构测试 + BUG / 死代码 / 偶尔失效模块完整修复
>
> **当前位置**：⏸️ Phase 1 / F1 进行中暂停（Sir 处理外事）。代码已定位 `jarvis_worker.py:490/505` 声波 print。Sir "继续" 后从 F1 接着干。

### Phase 1 — 救火现修（~1.5h，Phase 2 push 前必清）

**已完工 / commit 71e2e39 / tag v0.20.3-firefighting / commit a5ebe8d / tag v0.20.4-nameerror-guards**

| # | Marker | 主题 | 状态 |
|---|---|---|---|
| F1 | P0+20-β.1.1 | 声波打印 100ms 节流 + 段尾换行（治 B6）| ✅ |
| F2 | P0+20-β.1.2 | sanitize_trigger_time + prompt 5a 收紧（治 B1）| ✅ |
| F3 | P0+20-β.1.3 | detect_semantic_category + Correction Guard（治 B2）| ✅ |
| F4 | P0+20-β.1.4 | 自我打断白名单 10 pattern（治 B3）| ✅ |
| F5 | P0+20-β.1.5 | KeyRouter 持久化 + reset 接口（治 B7）| ✅ |
| F6 | P0+20-β.1.6 | chat_bypass.py 延迟 import JARVIS_CORE_PERSONA（治 B8）| ✅ |
| F7 | P0+20-β.1.7 | return_sentinel + smart_nudge + commitment_watcher win32api try-import（治 B9）| ✅ |
| F8 | P0+20-β.1.8 | 删 6 处 inline directive（L2 单一注入路径）| ✅ |
| F9 | P0+20-β.1.9 | scripts/health_check.py 9 项体检 | ✅ |
| F10 | P0+20-β.1.10 | jarvis_enhanced.py 删 962 行死代码（1531→569）| ✅ |
| F11 | P0+20-β.1.11 | future-tense capability lie 治本 + 23 testcase | ✅ |
| F12 | P0+20-β.1.final | docs/ARCHITECTURE_AUDIT_2026_05_16.md 归档 + tag v0.21.0 | ✅ |
| Tests | — | 52/52 OK，新增 61 testcase（firefighting 26 + nameerror 12 + future-tense 8 + b01 update 15）| ✅ |

### Phase 2 — push 到 GitHub

| # | 动作 | 状态 |
|---|---|---|
| P2.1 | 21 commits push | ✅ |
| P2.2 | 7 tags push | ✅ |

### Phase 3 — β.0.5 Gemini-3-Flash 异步评分链（~2h）

新文件 `jarvis_directive_evaluator.py` + `safe_openrouter_call` 集成 + post-turn 异步评分回写 `directive.helped`。详 `docs/PROMPT_REFACTOR_PLAN.md` §7。

### Phase 4 — β.0.6 PERSONA iterate + 瘦身（~2h）

- 核对 L2 12 条 directive 已覆盖所有旧 inline（NUDGE / BILINGUAL / SMART_ROUTING / TOOL_USE / MEMORY WRITE / SEARCH / IMAGE / SYSTEM_ENV）
- 删除 `_assemble_prompt` 里 5 处 inline directive；保留 PERSONA 主体
- 实测 prompt size 30K → 18K 目标
- 装配耗时 3074ms → < 400ms 目标
- TTFT 实测回到 3s 以下

### Phase 5 — 全架构审计（~2h）

输出 `docs/ARCHITECTURE_AUDIT_2026_05_16.md`，含：
- **死代码扫描**：enhanced.py 9 类（PromptCache / CorrectionLoop / UnifiedMemoryGateway / TaskWorkerPool / Anticipator / ContextRouter / ProfileCard / ContentPreferenceTracker / SoulRouter）+ 全文 grep 未被引用的私有方法
- **偶尔失效模块**：PromiseExecutor 是否真跑过长任务 / SkillRegistry 130 skill 是否真被调过 / ScreenshotSentinel 频率 / SoulArchivist 归档命中率
- **未跑通的老 BUG**：d.5 中文 Audio Guard / TWO_PARTS 实测命中率 / future-tense lie / asr_video_leak
- 出修复优先级 + 工时估算

### Phase 6 — 全测 + tag

- `tests\_runall.ps1` 49+ testcase 持续全绿
- 新增回归 testcase 覆盖 B1-B7
- 真机一轮 Sir 验收
- tag `v0.21.0-prompt-refactor-full`

### 🧬 P0+20-W — Workflow 规范化（trace_id / 测试 / commit / Agent 章程）

| # | Marker | 主题 | 关键产物 | 估时 | 状态 |
|---|---|---|---|---|---|
| W.1 | **P0+20-W.1** | 规范唯一源 | `docs/JARVIS_WORKFLOW_PROTOCOL.md`（8 节 / trace_id 三层 / 测试规范 / commit 模板 / push 时机 / Agent 行为 / 性能基线 / 安全协议） | 0.75h | ✅ |
| W.2 | **P0+20-W.2** | TraceContext + bg_log 注入 | `jarvis_utils.py` 加 `TraceContext` 单例 + `bg_log` 自动注入 `[sess_xxx] [turn_xxx]` 前缀；`jarvis_nerve.py:__main__` 启动调 `init_session`；`jarvis_worker.py` text_ready emit 前调 `new_turn`，Full pipeline 后调 `clear_turn` | 0.5h | ✅ |
| W.3 | **P0+20-W.3** | pytest conftest + runall 升级 | `tests/conftest.py` (session/finish hooks + trace_id fixture) + `tests/_runall.ps1` 加 test_run_id / git_head / 写 `tests/last_run.json` 含完整统计 | 0.5h | ✅ |
| W.4 | **P0+20-W.4** | AGENTS.md | 仓库根 `AGENTS.md`（11 节 / 所有 AI Agent 自动读 / 极简入口指向 PROTOCOL） | 0.25h | ✅ |
| W.5 | **P0+20-W.5** | Cursor 硬规则 | `.cursor/rules/jarvis_workflow.mdc`（alwaysApply）+ `jarvis_python_style.mdc`（globs=jarvis_*.py）+ `jarvis_security.mdc`（alwaysApply）3 个聚焦规则 | 0.25h | ✅ |
| W.6 | **P0+20-W.6** | TODO 章程段升级 | 顶部 QUICKSTART 改成"读 AGENTS.md + PROTOCOL"指针，不复述规则；α.5 标已随 deps 完成；BUG 表加 future-tense lie | 0.25h | ✅ |
| W.7 | **P0+20-W.7** | 全测 + commit + tag | `tests\_runall.ps1` 全绿；commit W 整轮；`git tag v0.20.0-workflow` | 0.25h | ⏳ |

### ✅ P0+20-α — 拆分收尾 + 6 修（已完工 / 保留作历史参考）

> **保留位置原因**：Sir 切回旧 Agent 窗口能立刻看到 α 系列做了啥；commit `dea1eb5` ~ `1efab47`，tag `v0.20.1-cleanup`。
> **范围保守**：α.3 Integrity 闸门只解决"陈述/共情/解释/referential 句"误报，**不**扩到"future-tense 撒谎"（那是 β.0 的范围）。

| # | Marker | 主题 | 关键产物 | 估时 | 状态 |
|---|---|---|---|---|---|
| α.1 | **P0+20-α.1** | numpy import 补全 | `jarvis_memory_core.py:30` 加 `import numpy as np`（拆分时漏的 9 处 `np.*` 调用）→ 解决 google_3 PROJECT_DENIED 误归因刷屏 | 0.25h | ✅ `dea1eb5` 2026-05-16 |
| α.2 | **P0+20-α.2** | KeyRouter 永久剔除 + Hippocampus 节流 | 3 次 PROJECT_DENIED → `permanently_dead=True` 不再 `_auto_recover`，一次性醒目提示 `⛔ [KeyRouter PERMANENT]` + 剩余健康 key 数；Hippocampus 跳过日志加 60s 节流（per-key），永久死亡完全静默 | 0.25h | ✅ `2a65cc7` 2026-05-16 |
| α.3 | **P0+20-α.3** | Integrity 闸门治标治本 | 新增第 0.55 层 declarative/empathic/explanatory pre-filter (`Dreams are X` / `It is likely X` / `Unless X` / `Often X` / 中文同款)；第 1 层 `have been` / `has been` 收紧到主语必须是 Jarvis 自己。**不扩到 future-tense 撒谎**（β.0 治本）| 0.5h | ✅ `a8cd656` 2026-05-16 |
| α.4 | **P0+20-α.4** | dormant_project 静默期 | `JarvisState.seconds_since_conv_off()` 新公共方法；SmartNudge 主循环 0 ≤ secs_off < 60s 跳过本 tick。解决 standby 9s 后 SilentNudge 触发的"骚扰" | 0.25h | ✅ `1764aea` 2026-05-16 |
| α.5 | **P0+20-α.5** ✨ | Malformed FAST_CALL 收手 | Malformed warning `print → bg_log`（不污染对话框）；SYSTEM HARD CONSTRAINT 反馈消息禁止 "captured/examined/checked/refreshed" + "Done, Sir/already completed" 一气呵成假完成，给唯一合法 fallback template | 0.25h | ✅ `8802757` 2026-05-16 |
| α.6 | **P0+20-α.6** ✨ | print → bg_log 治理（轻量版） | 39 处 daemon 异常 print 降级到 bg_log（chat_bypass 8 + central_nerve 12 + worker 8 + vocal_cord 5 + enhanced 6）。**保留**：对话框结尾错误（Local/Cloud/FAST_CALL Failed）、启动 banner、Mount/麦克风启动失败。深度版（全量 print review）留路线候选 | 0.5h | ✅ `1efab47` 2026-05-16 |
| α.7 | ~~**P0+20-α.7**~~ | ~~Sir 手动 4 件~~ | rotate 8 keys / `.env` / `git init` / `load_keys()` 入口替换 — 已随 `P0+19-deps` 完成 | — | ✅ |
| α.final | **P0+20-α.final** | α 整轮验收 | 48/48 testcase 全绿（test_run_id=`test_20260516_114313_65e8`，dur=219.83s，git_head=`1efab47`）；tag `v0.20.1-cleanup`；本地 commit 已就绪，**未 push**，等 Sir 真机实测后再决定 | 0.25h | ✅ 2026-05-16 |

### 🧠 P0+20-β.0 — Prompt 重构 + Directive Registry（部分完成 / β.0.4-6 推到 Phase 3-6，完整 design doc 在 `docs/PROMPT_REFACTOR_PLAN.md`）

> **核心目标**：prompt 30K → 18K (-40%) / `_assemble_prompt` 1274ms → < 400ms / TTFT 3.0s → 2.3-2.5s / TWO_PARTS 多意图 0/N → N/N / Integrity 误报 -50%。
> **当前进度**：β.0.1 ✅ + β.0.2 ✅ + β.0.3 ✅（双层注入）/ β.0.4 (decay daemon 已随 β.0.1 一起) / **β.0.5 (Gemini-Flash 评分) → 上面 Phase 3** / **β.0.6 (瘦身) → 上面 Phase 4**。
>
> **架构**：四层 L0 (Immutable Core) / L1 (Session Context) / L2 (**Directive Registry**) / L3 (Task Frame)。L2 用 **`google/gemini-3-flash-preview`** 异步评分采"helped"信号 + 行为信号采"fired/rejected" + 自动衰减（30d ttl）+ Sir review 队列。
>
> **L0 走 iterate 路线**：保留现有 PERSONA 主体（butler 身份 + INTEGRITY 4 铁则），只搬迁 NUDGE/BILINGUAL/SMART_ROUTING/TOOL_USE/具体短语黑名单 → L2 Registry。

| # | Marker | 主题 | 关键产物 | 估时 | 状态 |
|---|---|---|---|---|---|
| β.0.1 | **P0+20-β.0.1** | Registry + 12 directive bootstrap | `jarvis_directives.py` (~800) + `DirectiveContext` / `Directive` / `DirectiveRegistry` + 12 条 trigger 函数 + JSON 持久化 + 新增 ~30 testcase | 2.0h | ⏳ |
| β.0.2 | **P0+20-β.0.2** | dry-run + 切低 tier | `_assemble_prompt` 顶部 dry-run 双跑 + bg_log 对比；24h 验证后切 SHORT_CHAT / WAKE_ONLY 用新机制 | 1.5h | ⏳ |
| β.0.3 | **P0+20-β.0.3** | L0 精简 + 切高 tier | PERSONA 53→25 行（iterate）+ how_to_respond 缩到 1000 chars + 切 DEEP_QUERY / TOOL_REQUEST / CRITICAL + profile_block 1509→800 | 1.0h | ⏳ |
| β.0.4 | **P0+20-β.0.4** | decay daemon + Sir review | `DirectiveDecayWorker` daemon（60s tick）+ `memory_pool/directive_review.json` + `scripts/registry_dump.py` CLI | 0.5h | ⏳ |
| β.0.5 | **P0+20-β.0.5** | Gemini-3-Flash 评分异步链 | `jarvis_directive_evaluator.py` + primary=`google/gemini-3-flash-preview` / fallback=lite / 3s timeout / 独立 evaluator key 池 / `gatekeeper_async` 集成 | 1.5h | ⏳ |
| β.0.6 | **P0+20-β.0.6** | 全测 + 真机 + dashboard | 1098+ testcase 全绿 + Sir 实测 5 次 TWO_PARTS / 5 次陈述句 + `registry.dump_human()` 验收 | 0.5h | ⏳ |

### 每批通用收尾（每个 sub-step 完成后必做 6 步）

1. 抽出/新增代码完整搬到目标文件（含历史 marker `[P0+20-α.X / P0+20-β.0.X / 2026-05-XX]`）
2. 转发垫层 / API 兼容（不破坏 `from jarvis_X import Y` 老 import）
3. `python -c "import jarvis_nerve"` 冒烟（5s 内必通）
4. `pytest tests/` 全绿才能 commit：`git commit -m "[P0+20-X.Y] <主题> — <效果>"`
5. 失败：`git reset --hard HEAD~1` + bg_log 原因 + 修方案再试
6. 完工标 ✅ + 加完工日期到本文件对应行

### P0+20-β.0 最终验收 Checklist

- [ ] `[Prompt Size]` 日志：DEEP_QUERY 总 < 19000 chars
- [ ] `[Asm Diag]` 日志：assemble 总耗时 < 450ms
- [ ] `[Pipeline Timer] TTFT`：< 2.6s
- [ ] `pytest tests/` 1098+ testcase 全绿
- [ ] **TWO_PARTS 实测**：Sir 故意说复合句 5 次，至少 4 次 Jarvis 答两段
- [ ] **Integrity 误报**：实测 5 个陈述句 / 共情句，0 次误报
- [ ] `python scripts/registry_dump.py` 输出符合预期（12 条 active + 0 review）
- [ ] `[Evaluator]` 异步评分链路 OK，bg_log 能看到 `helped=yes/no/partial`
- [ ] 拔网线测试：评分链路超时不影响主对话

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
