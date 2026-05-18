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

═══ 当前进度快照 (截止 β.4.1 commit d36e9eb / tag v0.31.1-claim-enforce) ═══

L0   ✅ INTEGRITY ABSOLUTE 在 PERSONA (历史已有)
L0.5 ✅ **Session 0 完工** — 7 vocab × ~330 keyword 全量 json + CLI + L7 入口就位
      (tool_intent / dashboard_intent / memory_correction / inconsistency /
       response_classify / feedback / concern_keywords).
L1   ❌ Claim 分类器未做 (→ **Session 2 下一项**)
L2   ❌ Evidence 中央表未做 (→ **Session 2 下一项**)
L3   ⚠️ 17 directive 散在 jarvis_directives.py (部分已 json 化)
L4   ✅ **Session 1 完工** — ClaimTracer enforce: integrity_audit.jsonl 持久化 +
      _assemble_prompt prepend [INTEGRITY ALERT] 上轮 unverified claim → 强制 acknowledge
L5   ✅ 闭环 A 完工 (β.2.9.11 commit 3a89168 + 19 testcase)
L6   ⚠️ dashboard 信任审计卡有, 统计粒度浅 (→ Session 3)
L7   ❌ LLM-propose / WeeklyReflector 接 audit 未做 (→ Session 4)

89/89 testcase pass (run_id test_20260518_172619_fa3d), 0 regression.

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
║ Session 2 ── L1 Claim 分类器 + L2 Evidence 中央表             ║
╚═══════════════════════════════════════════════════════════════╝

新文件:
1. jarvis_claim_classifier.py
   - classify(reply_text) → ClaimType 枚举 (6 类: Past/Future/State/Recall/Social/Tool)
   - vocab: memory_pool/claim_classify_vocab.json (Sir 准则 6.5)
   - LLM 1.5B 二次判: 用 safe_openrouter_call('mistralai/mistral-nemo:free') fallback
2. jarvis_evidence_requirements.py
   - EvidenceRequirements 单例
   - 数据源: memory_pool/evidence_requirements.json (Sir 可改)
   - get_requirements(claim_type) → list of evidence_kind

CLI: scripts/claim_classify_dump.py + scripts/evidence_req_dump.py

接通: L4 ClaimTracer 调 L1 classify → 查 L2 requirements → 看 evidence 是否满足 → 不满足写 L4 audit

预期工时: ~5h.

╔═══════════════════════════════════════════════════════════════╗
║ Session 3 ── L6 dashboard 升级 + 兑现率趋势                   ║
╚═══════════════════════════════════════════════════════════════╝

1. scripts/jarvis_dashboard.py 加 reader read_integrity_stats()
2. 信任审计卡升级显示: 今日 claim 数 / verify 数 / unverify 率 / 7d 趋势 ASCII chart
3. compute_overall_status 加 "言出必行健康度" headline 一栏
4. testcase 验证 reader 解析 jsonl

预期工时: ~2h.

╔═══════════════════════════════════════════════════════════════╗
║ Session 4 (灵魂级核心) ── L7 LLM-propose 自我修正            ║
╚═══════════════════════════════════════════════════════════════╝

WeeklyReflector (jarvis_soul_reflector.py) 加 2 个新方法:

1. _reflect_vocab_gaps()
   - 扫 7d STM/LTM 找未命中现有 vocab 但语义重要的 token
   - 用 Gemini-3-Flash LLM 提取候选 vocab → 写各 review queue
     (response_classify_review.json / tool_intent_review.json / ...)
   - Sir 用对应 CLI --review-list 看 → --activate / --reject

2. _reflect_integrity_audit()
   - 扫 7d memory_pool/integrity_audit.jsonl
   - 找 unverified claim 类型分布
   - LLM-propose 新 directive 入 directive_review.json
   - Sir scripts/registry_dump.py --review-list 看 → 决定

核心契约: Sir 永远是仲裁人. propose 只入 review, 不自动激活. Sir 拍板才生效.

预期工时: ~6h.

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

═══ Session 0 + Session 1 已完工 — Session 2 接手位置 ═══

进窗口先读 AGENTS.md 全文, 然后读 TODO.md (看头部 Session 1 完工段),
然后读 docs/JARVIS_INTEGRITY_STACK.md (看 L1 + L2 设计).

读完后从 **Session 2 L1 Claim 分类器 + L2 Evidence 中央表** 开始:

1. 新建 `jarvis_claim_classifier.py` (准则 6.5):
   - 6 类: Past / Future / State / Recall / Social / Tool
   - `classify(claim_text) -> ClaimType` (vocab 表驱, regex 兼测)
   - 送 vocab + scripts/claim_classify_dump.py CLI

2. 新建 `memory_pool/claim_classify_vocab.json`:
   - schema: `{type: [keywords]}` (Past → [已/I've/opened/launched], Future → [will/I'll/会/准备], ...)

3. 新建 `jarvis_evidence_requirements.py` + `memory_pool/evidence_requirements.json`:
   - schema: `{claim_type: [accepted_evidence_kinds]}`
   - Past → tool_results (需 ✅)
   - Future → [] (不需 evidence, 仅 record 入 PromiseLog)
   - State → ltm (需 ltm 表查)
   - Recall → stm (需 stm 命中)

4. 改 jarvis_claim_tracer.trace_to_evidence:
   - 现 hardcode (past_action / regex)
   - 变 vocab + requirement 表驱动

5. testcase: `_test_p0_plus_20_beta42_claim_classify_persist.py`
   - 6 type 分类准确性
   - vocab json fallback / mtime reload / CLI
   - trace_to_evidence 接 vocab + requirement 后仍 verify/unverify 正确
   - 准则 6.5 红线 (旧名 _PAT_PAST_ACTION_* 可保 seed, 但主表走 json)

6. 跑全测 89+/89+ OK → commit + tag v0.32.0-claim-classify
7. 预期工时 ~5h.

完工后报 Sir + tag, 等 Sir 拍板进 Session 3 或实测反馈.
```

---

## ⚠️ Sir 操作提示

1. 上面整段一次复制到新对话窗口
2. Agent 自动按 Session 0 → 1 → 2 → 3 → 4 顺序推进
3. 每个 sub-step 完工 Agent 会汇报，你说"继续"就推进下一个
4. 真机实测有反馈直接发新消息，Agent 接住后继续

## 📦 当前 commit 链 (Agent 接手前必看)

```
3e4824d docs(P0+20-β.2.9.11): TODO 滚动 — 18 commits 累计 + INTEGRITY_STACK 立项 + 下轮路线
3a89168 feat(P0+20-β.2.9.11): 灵魂闭环 A 完工 + INTEGRITY_STACK 7 层架构立项
1e4b603 fix(P0+20-β.2.9.11): snippet 截断 'y co' 美化 + ProactiveCare skip 日志节流
ed9c033 docs(P0+20-β.2.9.10): TODO 滚动 — 15 commits 累计 + FAST_CALL 异步治本完工
128d688 feat(P0+20-β.2.9.10): FAST_CALL 软超时异步治本工具卡顿
6c8df92 fix(P0+20-β.2.9.10): 删 ReturnSentinel 模板兜底死代码 + 加正向引导避免'Welcome back'客套
... (更早 commit 见 git log)
```

## 🎯 验收标准 (Session 0 完工)

Sir 跑下面 grep 命令应该 **0 命中** (说明所有 vocab 已迁离 .py):

```powershell
# 在 d:\Jarvis 跑
rg -p "_PATTERNS\s*=\s*[\[\(]" --type py
rg -p "_KEYWORDS\s*=\s*[\[\(]" --type py
rg -p "_VOCAB\s*=\s*[\[\(]" --type py
```

应该只看到:
- `_SEED_<X>_PATTERNS` (fallback 仅, OK)
- `_<X>_PATTERNS_CACHE` (mtime cache 变量, OK)

不应再看到任何 `_<X>_PATTERNS = [...]` / `_<X>_KEYWORDS = (...)` 类硬编码。

---

*文档作者: Sir 2026-05-18 12:57 要求 + Claude 写完整版 / 2026-05-18*
*接手 Agent 严格按 Session 0 → 1 → 2 → 3 → 4 顺序推进, 不跳序.*
