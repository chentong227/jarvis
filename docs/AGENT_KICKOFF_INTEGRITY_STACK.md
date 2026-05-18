# Agent Kickoff — INTEGRITY_STACK 7 层架构推进

> **用法**: 在 Cursor 中打开新对话窗口，把下面「📋 Sir 复制粘贴版」**整段**贴给 Agent。
> Agent 会自己读所有必读文档然后按 Session 顺序往下推进。

---

## 📋 Sir 复制粘贴版 (完整一次性给 Agent)

```
你要接手 J.A.R.V.I.S. 项目的 INTEGRITY_STACK 7 层架构推进 (与 SOUL_DRIVE 并列的第三条灵魂级模块).

═══ 进窗口必读 (按顺序) ═══

1. AGENTS.md — 项目入口章程 (强制全读, < 250 行)
   特别留意:
   - 准则 5 言出必行 (INTEGRITY ABSOLUTE)
   - 准则 6 拒绝硬编码 5 类反例
   - 准则 6.5 动态架构必须 + LLM 兜底 (Sir 2026-05-18 12:57 升级 — 关键!)

2. TODO.md — 当前迭代状态 (全读, < 300 行)
   看 "上轮完工速览" 段 + 本轮迭代任务

3. docs/JARVIS_INTEGRITY_STACK.md — 本项目立项 (全读, ~400 行)
   特别看:
   - §0.5 L0.5 Dynamic Vocab Substrate (横向贯通层 — 一切层级都遵守)
   - §3 当前状态盘点 (β.2.9.12)
   - §4 推进步骤 5 Session
   - §8 路线图

4. docs/JARVIS_SOUL_DRIVE.md — 相邻灵魂模块 (按需 grep, 不必全读)
   看 L1 ConcernsLedger 部分 (因为 INTEGRITY_STACK L5 闭环 A 复用 reflector vocab)

5. docs/runtime_logs/latest.txt — 1 行 latest log path
   仅在 Sir 反馈 BUG 时用 Grep, 不要全文 Read

═══ 当前进度快照 (截止 β.4.8-PhaseC commit f9378be / β.4.7 commit 2c0730c / β.4.6 commit 465ee18) ═══

✨ **INTEGRITY_STACK 7 层 + Memory Deletion 8 层 + Acoustic Wake (openWakeWord) framework ✨**

L0   ✅ INTEGRITY ABSOLUTE 在 PERSONA (历史已有)
L0.5 ✅ **Session 0 完工** — 7 vocab × ~330 keyword 全量 json + CLI + L7 入口就位
      (tool_intent / dashboard_intent / memory_correction / inconsistency /
       response_classify / feedback / concern_keywords).
L1   ✅ **Session 2 完工** — Claim 分类器 7 类 vocab + CLI + kinds_hard_map 优先
      (memory_pool/claim_classify_vocab.json + jarvis_claim_classifier.py)
L2   ✅ **Session 2 完工** — Evidence Requirements 中央表 + CLI
      (memory_pool/evidence_requirements.json + jarvis_evidence_requirements.py)
L3   ✅ **β.4.6 完工** — 18 directive text/metadata 提到 memory_pool/directives_vocab.json,
      trigger 留 py (半化方案). bootstrap 优先读 JSON + py trigger 组装;
      JSON 损坏 → fallback seed_defs (18 内嵌 hardcode). state='active' 才注册.
      Sir CLI: scripts/registry_dump.py --show / --vocab-list / --edit-text / --archive
      (commit 465ee18 / tag v0.35.0-directive-vocab)
L4   ✅ **Session 1+2 完工** — ClaimTracer enforce + trace_to_evidence 表驱重写
      Session 1: integrity_audit.jsonl 持久化 + ALERT 注入 (commit d36e9eb)
      Session 2: trace_to_evidence use_vocab=True 走 L1+L2; legacy 路径保 β.2.8.7 回归;
                 time claim 由 SYSTEM CLOCK ±2min 治本 β.4.2-hotfix 死循环 (commit 3ce27b3)
L5   ✅ 闭环 A 完工 (β.2.9.11 commit 3a89168 + 19 testcase)
L6   ✅ **Session 3 完工** — dashboard 言出必行健康度宽卡 + reader + 阈值
      (commit 7bbd890 / tag v0.33.0-dashboard-integrity)
L7   ✅ **Session 4 完工** — IntegrityReflector LLM-propose daemon + ClaimStatsDumper
      β.4.5.1: ClaimStatsDumper 60s tick (commit d6b4247) — dashboard verify_rate 跨进程生效
      β.4.5.2: IntegrityReflector LLM (commit 9f84743) — 7d audit 反思 propose 3 类 review queue
      (tag v0.34.0-integrity-reflector)

96/96 + β.4.7 14 测 + β.4.8 33 测 = 大约 143 测 (sanity 4/4 pass), 0 regression.

🆕 **β.4.7 Memory Deletion 第 6/7/8 层守卫 (Sir 21:45 实测 BUG 治本)**:
- L6 cmd 必含显式删除动词 (memory_deletion_vocab.json deletion_verb) + L8 cmd 含 ASR 纠正 (复用 memory_correction_vocab) + L7 vocab thresholds (top_k=1, sim=0.85, 旧 5/0.45 太松).
- 改 jarvis_safety.py 4 helper, jarvis_worker.py direct + correction→delete 两路径都加守卫.
- commit 2c0730c, 测 37/37 (β.4.7 14 + 老 P0+16 23) pass.

🆕 **β.4.8 Acoustic Wakeword (openWakeWord MIT) — P1+PhaseC 完工, Sir Colab 自训中**:
- jarvis_acoustic_wake.py (470 行) AcousticWakeDetector 包装 openWakeWord + vocab + CLI.
- AuditoryCortex.run 接入 _handle_acoustic_wake + non-active feed_pyaudio_buffer.
- vocab.acoustic_wake_enabled=false 默认 (灰度开关), 不破坏现有 parse_wake_word 老路径.
- scripts/mic_diag.py: --vocab-show / --set / --use-model / --use-builtin / --rms / --test-wake.
- commits: 4ecf17d (P1) + f9378be (PhaseC), 测 33/33 (29 + 4 mic_diag CLI) pass.
- ⏳ P2 等 Sir Colab 自训 jarvis_v1.onnx (~1h), 然后 --use-model + 真机调 sensitivity + tag v0.37.0.

═══ 你的工作顺序 (严格按此, 不跳序) ═══

╔════════════════════════════════════════════════════════════════╗
║ Session 0 ✅ 已完工 ── L0.5 Dynamic Vocab Substrate 全面迁移       ║
╚════════════════════════════════════════════════════════════════╝

目标: 把所有 py-hardcoded vocab 迁到 memory_pool/*.json + CLI 工具, 按 AGENTS.md
准则 6.5 三硬规 (持久化 + CLI + 预留 L7 LLM-propose).

✅ **完工状态 (commit 0c663e6 / tag v0.31.0-dynamic-vocab-substrate)**:
- 7/7 vocab 迁完, 共 ~330 keyword, 77 新 testcase, 88/88 全测绿 (run_id test_20260518_170331_756d)
- 验收 grep 在 7 vocab 范围内 0 命中 (剩余命中都是后续 session scope)
- 下一任务接 Session 1

审计现有 py 文件, 找所有 _XXX_PATTERNS = [...] / _XXX_KEYWORDS = (...):

| 当前位置 | 迁移目标 |
|---|---|
| jarvis_directives.py: _TOOL_INTENT_PATTERNS | memory_pool/tool_intent_vocab.json + scripts/tool_intent_dump.py |
| jarvis_directives.py: _DASHBOARD_INTENT_PATTERNS_ZH/EN | memory_pool/dashboard_intent_vocab.json + CLI |
| jarvis_directives.py: _MEMORY_CORRECTION_PATTERNS_ZH/EN | memory_pool/memory_correction_vocab.json + CLI |
| jarvis_inconsistency_watcher.py: _SIR_SLEEP_VERBS / _JARVIS_WRAPPER_MARKERS / _SIR_BREAK_VERBS | memory_pool/inconsistency_vocab.json + CLI |
| jarvis_proactive_care.py: _RESPONSE_POSITIVE / _RESPONSE_NEGATIVE | memory_pool/response_classify_vocab.json + CLI |
| jarvis_memory_core.py: FeedbackTracker._correction_patterns | memory_pool/feedback_vocab.json + CLI |
| jarvis_soul_reflector.py: CONCERN_KEYWORDS | memory_pool/concern_keywords_vocab.json + CLI |

照搬 β.2.9.12 已立的范式 (commit ??):
1. 新 memory_pool/<vocab>.json (含 _meta + patterns/keywords list + state=active/review/archived)
2. 改对应 .py: _SEED_X 留 fallback, 新 helper get_<vocab>() 带 mtime cache
3. 新 scripts/<vocab>_dump.py CLI (list/add/activate/reject/delete)
4. 新 testcase _test_p0_plus_20_beta2X_<vocab>_persist.py
5. 各自独立 commit, 跑全测确保 0 回归
6. 完成 7 项迁移 → tag v0.29.0-dynamic-vocab-substrate

预期工时: ~6h. 每项 ~45min (json 设计 + .py 改 + CLI + test + commit).

╔════════════════════════════════════════════════════════════════╗
║ Session 1 ✅ 已完工 ── L4 ClaimTracer enforce + ALERT 注入         ║
╚════════════════════════════════════════════════════════════════╝

L5: 已完工 (β.2.9.11 commit 3a89168).

L4 enforce ✅ (commit d36e9eb / tag v0.31.1-claim-enforce):
- `jarvis_claim_tracer.py` + `write_audit_entry()` / `read_recent_unverified()` /
  `build_integrity_alert()`; `trace_reply` hook 仅 unverified 入 jsonl
- `jarvis_central_nerve.py:_assemble_prompt` 入口调 `build_integrity_alert` →
  prepend 到 `system_alert_text` (5 个 template auto-pick up) + bg_log 诊断
- `memory_pool/integrity_audit.jsonl` (.gitignore 已 cover)
- 30 testcase (5 类: write / read / build / trace_reply hook / integration grep / red lines)
- 89/89 全测绿 (run_id test_20260518_172619_fa3d)

╔═══════════════════════════════════════════════════════════════╗
║ Session 2 ✅ 已完工 ── L1 Claim 分类器 + L2 Evidence 中央表    ║
╚═══════════════════════════════════════════════════════════════╝

✅ **完工状态 (commit 0d62236 / tag v0.32.0-claim-classify)**:
- L1: jarvis_claim_classifier.py + memory_pool/claim_classify_vocab.json +
      scripts/claim_classify_dump.py (7 类 + kinds_hard_map + mtime cache + seed fallback)
- L2: jarvis_evidence_requirements.py + memory_pool/evidence_requirements.json +
      scripts/evidence_req_dump.py (canonical evidence_kinds + accepted list per type)
- L4 重写: jarvis_claim_tracer.trace_to_evidence(use_vocab=True) 表驱;
      _trace_via_legacy 保 β.2.8.7 测试不破; _LEGACY_TRACE_LABEL alias 老短名
- chat_bypass: trace_reply 入参 system_clock + ltm_context (治本 β.4.2-hotfix)
- testcase: tests/_test_p0_plus_20_beta434_claim_classify_evidence_persist.py
            (9 TestClass / 54 测; cross-coupling + 红线 + CLI + dual-track 风险口)
- 92/92 全测绿 (run_id test_20260518_200142_2154)

真机风险点 (Sir 黑箱测试看 TODO.md 头部清单 5 条):
1. L1 keyword 顺序 (Tool > State, '正在/现在' 已删避免冲突)
2. L2 Past 类 must tool_results ✅
3. time claim ±2min 窗口跨夜可能误判
4. ltm_context 2000 字截断
5. vocab IO 损坏走 seed fallback

╔═══════════════════════════════════════════════════════════════╗
║ Session 3 ✅ 已完工 ── L6 dashboard 言出必行健康度宽卡         ║
╚═══════════════════════════════════════════════════════════════╝

✅ **完工状态 (commit 7bbd890 / tag v0.33.0-dashboard-integrity)**:
- scripts/jarvis_dashboard.py:
  - `_safe_read_jsonl_tail` (file seek -512KB 防大文件全 load)
  - `read_integrity_stats(window, audit_path, stats_path, now_ts)` reader
  - `_render_integrity` (诊断 + 总数 + kind 分布 + top 3 + 7d ASCII trend)
  - `card_integrity` 跨 4 列宽卡 (group_obs row 1) + lbl_integrity 标题徽章
  - `_make_card` 加 columnspan/height kwargs (兼容老 caller)
  - `compute_overall_status` 加 integrity 入参 + 阈值 (今日 0 绿 / 1-5 黄 / >5 红)
  - reader bucket-day bug fix (ts 不对齐 00:00 时偏移 1 天)
  - `print_snapshot` CLI 加言出必行段
- testcase: tests/_test_p0_plus_20_beta44_dashboard_integrity_persist.py
            (6 TestClass / 27 测; reader 基本/fail-safe/时间窗/阈值/UI/cross-module)
- 93/93 全测绿 (run_id test_20260518_213535_4ad0)

真机风险点 (Sir 黑箱测试看 TODO.md 头部清单 5 条):
1. dashboard 卡片 layout 挤压 (group_obs row 1 weight 改了)
2. 跨夜 trend_7d 偏移 (Sir UTC+8 / time.timezone)
3. 0 字节 jsonl 文件诊断 (设计决定: 文件存在 = ClaimTracer 跑过)
4. claim_stats.json 缺失 → verify_rate '--' (Session 4 daemon 待加 hook 留好)
5. jsonl > 1MB 大文件无回归 (file seek -512KB cap on memory)

╔═══════════════════════════════════════════════════════════════╗
║ Session 4 ✅ 已完工 ── L7 LLM-propose 自我修正 + ClaimStatsDumper      ║
╚═══════════════════════════════════════════════════════════════╝

✅ **完工状态 (commit d6b4247 + 9f84743 / tag v0.34.0-integrity-reflector)**:

β.4.5.1 (commit d6b4247): 新文件 jarvis_integrity_reflector.py
  - dump_claim_stats(path): atomic dump _CLAIM_STATS → memory_pool/claim_stats.json
  - ClaimStatsDumper(Thread): 60s tick daemon + _stop_event (避 Python 3.9 Thread._stop 冲突)
  - get_default_claim_stats_dumper: 单例 factory
  - central_nerve 注册 在 Reflectors block 之后
  - .gitignore: memory_pool/claim_stats.json + *.bak
  - testcase: 5 TestClass / 16 测 (TestDumpStatsToDisk/FailSafe/Dumper/CrossModule/RedLines)

β.4.5.2 (commit 9f84743): IntegrityReflector 主体
  - INTEGRITY_REFLECTOR_CONFIG: 3d 兜底 / audit≥50+idle>4h 触发 / max_propose=5 / window=7d
  - INTEGRITY_REFLECTOR_PROMPT: 3 类 schema 约束 (不教具体措辞, 准则 6)
  - IntegrityReflector(Thread): _should_reflect_now / _gather_audit_window /
    _build_top_claims / _existing_review_items / _reflect_once / _call_llm
  - _propose_claim_classify / _propose_evidence_req / _propose_directive:
    写 review state + dedup + canonical 列表强制 (claim_type 6 类 / evidence_kind 7 类)
  - get_default_integrity_reflector: 单例 factory
  - central_nerve 注册在 ClaimStatsDumper 之后 (注入 key_router)
  - testcase: 6 TestClass / 30 测 (Init/Trigger/Reflect-LLM-mock/Propose/FailSafe/RedLines)

95/95 全测绿 (run_id test_20260518_223652_xxxx, dur 362.26s, 0 regression)

核心契约已立: Sir 永远是仲裁人 (准则 7). propose 默认 state=review, 不自动激活.
Sir CLI `scripts/claim_classify_dump.py / evidence_req_dump.py / registry_dump.py --review-list → --activate <id> / --reject <id>` 才生效.

真机风险点 (Sir 黑箱看 TODO.md 头部 5 条):
1. ClaimStatsDumper 启动失败 → bg_log "[ClaimStatsDumper] 初始化失败", dashboard verify_rate 仍 '--'
2. IntegrityReflector LLM 调用: timeout 15s + key_router 取 key + Gemini primary/fallback, 全 fail-safe
3. propose dedup 限 same-id, LLM 改 id 但同 keyword 漏抓 (β.4.6 可 fuzzy dedup)
4. vocab json 损坏 → _load_vocab_atomic fail-safe 返 {patterns:[]}, propose 会覆盖原 vocab. Sir prod 上 git checkout
5. 触发频率低 → Sir 可 CLI `r.force_run_now()` 手动跳一轮试

═══ 执行准则 (跨所有 Session) ═══

1. 准则 6.5: 任何新加的 keyword/pattern/list 必须立刻持久化 json + CLI, 永远
   不在 .py source 写死 list/dict. 例外: 系统级常量 (TICK_INTERVAL 等) 可以.

2. 准则 5 言出必行: 所有 commit message / TODO 描述 / Sir 报告必须 trace 到
   evidence (commit hash / testcase run_id / log basename). 不空头说"已完成".

3. 每个 sub-step 独立 commit + 全测绿. 失败 git reset --hard HEAD 不留烂代码.
   tests\_runall.ps1 必须 0 FAIL 才允许 commit.

4. 不主动 push. 等 Sir 真机实测后说"push" / "上线" 才执行.

5. 不动 .env / jarvis_config/sir_profile.json / memory_pool/*.db 等隐私文件.

6. 每完成 1 个 Session, 写 TODO.md 滚动 + tag (类似 v0.29.X-<feature>) +
   汇报 Sir (commit 链 + 可立测项).

═══ Session 0+1+2+3+4+5+β.4.7+β.4.8 全部完工/进行中 — INTEGRITY_STACK + Mem Del 8 层 + Acoustic Wake ═══

本 KICKOFF 使命已达成. 后续 Agent 进窗口, 优先选项 (Sir 拍板):

选项 A: **β.4.8-P2 完工** (β.4.8 收尾) — Sir Colab 训练完 jarvis_v1.onnx 后接手
  - Sir 把 onnx 放 memory_pool/wakeword_models/jarvis_v1.onnx
  - `python scripts/mic_diag.py --use-model memory_pool/wakeword_models/jarvis_v1.onnx`
  - Sir 真机调 sensitivity: `python scripts/mic_diag.py --test-wake 30` 看 max score
  - 调 threshold: `python scripts/mic_diag.py --set openwakeword_threshold=0.4` (或 0.6)
  - 全测 _runall.ps1 + tag v0.37.0-acoustic-wake + commit β.4.8-P2 完工

选项 B: **Sir 真机黑箱验收** β.4.5.x/β.4.6/β.4.7/β.4.8 风险点 (TODO.md 头部 "真机风险点清单")
  - β.4.7: 重启 Jarvis 后再试 "识别错误啊" 看 L8 拦截 bg_log
  - β.4.8: AuditoryCortex 启动看 print "🔊[AcousticWake / β.4.8] 启用 → keyword=..." 或 "🔇 未启用"
  - dashboard L6 "言出必行健康度" verify_rate 应出真数

选项 C: **进 SOUL_DRIVE Layer 4+** (灵魂工程续作)
  - 详 docs/JARVIS_SOUL_DRIVE.md (AlignmentEvaluator / RelationalState reflector 二阶段)

选项 D: **Sir 想要的新功能 §1-3** (sleep 模式, 见 TODO.md 头部)
  - 单进程 mute WeChat (pycaw) + dim 显示器 (Win32 SetBrightness) + 总调度 (sleep_intent hook)
```

---

## ⚠️ Sir 操作提示

1. 上面整段一次复制到新对话窗口
2. Agent 自动按 Session 0 → 1 → 2 → 3 → 4 顺序推进
3. 每个 sub-step 完工 Agent 会汇报，你说"继续"就推进下一个
4. 真机实测有反馈直接发新消息，Agent 接住后继续

## 📦 当前 commit 链 (Agent 接手前必看)

```
f9378be feat(P0+20-β.4.8-PhaseC): AuditoryCortex 接 Acoustic Wakeword (openWakeWord 集成)
4ecf17d feat(P0+20-β.4.8-P1): Acoustic Wakeword Framework (openWakeWord MIT) - 治 23:50 麦克风误拾/难唤醒 BUG
2c0730c fix(P0+20-β.4.7): Memory Deletion 第 6/7/8 层防御 - Sir 21:45 实测误删 5 条治本
465ee18 feat(P0+20-β.4.6): L3 directive vocab 半化 - text/metadata 提到 JSON, trigger 留 py
c681d6b docs(P0+20-β.4.5-session4): INTEGRITY_STACK Session 4 done - TODO + KICKOFF roll
9f84743 feat(P0+20-β.4.5.2): INTEGRITY_STACK Session 4 sub-step 2 - IntegrityReflector L7 LLM-propose daemon
d6b4247 feat(P0+20-β.4.5.1): INTEGRITY_STACK Session 4 sub-step 1 - ClaimStatsDumper 跨进程持久化
d5dafe0 docs(P0+20-β.4.4-session3): INTEGRITY_STACK Session 3 done - TODO + KICKOFF roll
7bbd890 feat(P0+20-β.4.4): INTEGRITY_STACK Session 3 - L6 dashboard 言出必行健康度宽卡
012e1b3 docs(P0+20-β.4.3-session2): INTEGRITY_STACK Session 2 done - TODO + KICKOFF roll
0d62236 feat(P0+20-β.4.3.4): INTEGRITY_STACK Session 2.4 - L1+L2+L4 cross-module testcase + classifier tighten
3ce27b3 feat(P0+20-β.4.3.3): INTEGRITY_STACK L4 trace_to_evidence rewrite vocab+requirement table-driven
2ea4504 feat(P0+20-β.4.3.2): INTEGRITY_STACK L2 Evidence Requirements - table + CLI
60646c0 feat(P0+20-β.4.3.1): INTEGRITY_STACK L1 Claim Classifier - vocab + CLI
ca3d0f1 test(P0+20-β.4.2-hotfix-followup): β.4.1 testcase 兼容 time kind audit skip
0c9bc66 fix(P0+20-β.4.2-hotfix): Sir 18:46 实测 time claim 进 audit 死循环治本
d36e9eb feat(P0+20-β.4.1): INTEGRITY_STACK Session 1 - L4 ClaimTracer enforce + ALERT 注入
... (更早 commit 见 git log)
```

## 🎯 验收标准 (Session 3 完工后跑)

Sir 跑下面 grep 命令应该 **0 命中** (说明所有 vocab 已迁离 .py):

```powershell
# 在 d:\Jarvis 跑
rg -p "_PATTERNS\s*=\s*[\[\(]" --type py
rg -p "_KEYWORDS\s*=\s*[\[\(]" --type py
rg -p "_VOCAB\s*=\s*[\[\(]" --type py
rg -p "_REQUIREMENTS\s*=\s*[\[\(]" --type py
```

应该只看到:
- `_SEED_<X>` (fallback 仅, OK)
- `_<X>_CACHE` (mtime cache 变量, OK)
- `_LEGACY_TRACE_LABEL` (向后兼容 alias, OK)

不应再看到任何 `_<X>_PATTERNS = [...]` / `_<X>_KEYWORDS = (...)` / `_<X>_REQUIREMENTS = {...}` 类硬编码。

额外 Session 2 验收:
```powershell
# L1 vocab loaded OK
python -c "from jarvis_claim_classifier import classify; print(classify('I have opened notepad'))"
# L2 vocab loaded OK
python -c "from jarvis_evidence_requirements import get_requirements; print(get_requirements('Past'))"
# trace_reply 端到端
python -c "from jarvis_claim_tracer import trace_reply; import time; r = trace_reply('It is 10:30 now', [], [], 'test', system_clock=time.time()); print(r)"
```

---

*文档作者: Sir 2026-05-18 12:57 要求 + Claude 写完整版 / 2026-05-18*
*接手 Agent 严格按 Session 0 → 1 → 2 → 3 → 4 顺序推进, 不跳序.*
