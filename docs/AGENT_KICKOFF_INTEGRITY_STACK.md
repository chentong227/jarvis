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

═══ 当前进度快照 (截止 β.4.3 commit 0d62236 / tag v0.32.0-claim-classify) ═══

L0   ✅ INTEGRITY ABSOLUTE 在 PERSONA (历史已有)
L0.5 ✅ **Session 0 完工** — 7 vocab × ~330 keyword 全量 json + CLI + L7 入口就位
      (tool_intent / dashboard_intent / memory_correction / inconsistency /
       response_classify / feedback / concern_keywords).
L1   ✅ **Session 2 完工** — Claim 分类器 7 类 vocab + CLI + kinds_hard_map 优先
      (memory_pool/claim_classify_vocab.json + jarvis_claim_classifier.py)
L2   ✅ **Session 2 完工** — Evidence Requirements 中央表 + CLI
      (memory_pool/evidence_requirements.json + jarvis_evidence_requirements.py)
L3   ⚠️ 17 directive 散在 jarvis_directives.py (部分已 json 化)
L4   ✅ **Session 1+2 完工** — ClaimTracer enforce + trace_to_evidence 表驱重写
      Session 1: integrity_audit.jsonl 持久化 + ALERT 注入 (commit d36e9eb)
      Session 2: trace_to_evidence use_vocab=True 走 L1+L2; legacy 路径保 β.2.8.7 回归;
                 time claim 由 SYSTEM CLOCK ±2min 治本 β.4.2-hotfix 死循环 (commit 3ce27b3)
L5   ✅ 闭环 A 完工 (β.2.9.11 commit 3a89168 + 19 testcase)
L6   ⚠️ dashboard 信任审计卡有, 但 L4 ClaimTracer 数据未接入 (→ **Session 3 下一项**)
L7   ❌ LLM-propose / WeeklyReflector 接 audit 未做 (→ **Session 4**)

92/92 testcase pass (run_id test_20260518_200142_2154), 0 regression.

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
║ Session 3 (下一任务) ── L6 dashboard 升级 + 兑现率趋势        ║
╚═══════════════════════════════════════════════════════════════╝

1. scripts/jarvis_dashboard.py 加 reader read_integrity_stats()
   - 读 memory_pool/integrity_audit.jsonl tail (一天 / 七天)
   - 聚合: 总 claim 数, unverified 数, 类型分布 (Past/Future/State/Recall/Social/Tool),
           最高频被 ALERT 的话 top 3
2. 信任审计卡升级显示:
   - 现卡 (β.2.9.7) 只显 MEMORY_UPDATE 真写入, 新加 ClaimTracer 数据段
   - 今日: claim N / verify M (M/N%) / unverify K
   - 7d ASCII chart (mtime tail 多日聚合)
   - 一键看 'integrity_audit.jsonl tail 20' 按钮
3. compute_overall_status 加 "言出必行健康度" headline 一栏
   - 阈值: < 80% verify → 黄 / < 60% → 红
4. testcase _test_p0_plus_20_beta44_dashboard_integrity_persist.py:
   - read_integrity_stats() jsonl 解析准确
   - 损坏 jsonl 行不 crash (fail-safe)
   - compute_overall_status 阈值边界

预期工时: ~2h, tag v0.33.0-dashboard-integrity.

真机风险点预判 (Sir 设计阶段就该想):
- jsonl 文件可能 > 100K 条, tail 实现别全 load (用 file seek -N 行)
- daily/weekly 聚合时区: Sir 在中国, 默认 local time, 不要 UTC
- dashboard 加新卡片不能崩, 任一 reader 异常都 fail-safe 占位 'data unavailable'

╔═══════════════════════════════════════════════════════════════╗
║ Session 4 (灵魂级核心) ── L7 LLM-propose 自我修正            ║
╚═══════════════════════════════════════════════════════════════╝

新文件 jarvis_integrity_reflector.py (daemon, 与 ConcernsReflector / WeeklyReflector 同 pattern):

1. _reflect_vocab_gaps()
   - 扫 7d STM/LTM 找未命中现有 vocab 但语义重要的 token
   - 用 Gemini-3-Flash LLM 提取候选 vocab → 写各 review queue
     (response_classify_review.json / tool_intent_review.json / claim_classify_review.json / ...)
   - Sir 用对应 CLI --review-list 看 → --activate / --reject

2. _reflect_integrity_audit()
   - 扫 7d memory_pool/integrity_audit.jsonl
   - 找 unverified claim 类型分布 + L2 evidence_requirements 漏配口
   - LLM-propose 新 directive 入 directive_review.json
   - LLM-propose 新 evidence_kind 入 evidence_req_review.json
   - Sir scripts/registry_dump.py / evidence_req_dump.py --review-list 看 → 决定

3. 触发: weekly (周日 03:00 idle 时) 或 audit 累积 > 50 条触发

核心契约: Sir 永远是仲裁人. propose 只入 review, 不自动激活. Sir 拍板才生效.

预期工时: ~6h, tag v0.33.0-integrity-reflector (与 Session 3 合并 tag 或分开都可).

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

═══ Session 0 + 1 + 2 已完工 — Session 3 接手位置 ═══

进窗口先读 AGENTS.md 全文, 然后读 TODO.md (看头部 Session 2 完工段 + 5 个真机风险点),
然后读 docs/JARVIS_INTEGRITY_STACK.md (看 L6 dashboard 部分).

读完后从 **Session 3 L6 Dashboard 信任卡升级** 开始:

1. scripts/jarvis_dashboard.py 加 reader `read_integrity_stats(window='today'|'7d')`:
   - 读 memory_pool/integrity_audit.jsonl tail (避免全 load, file seek)
   - 聚合 claim_type 分布 + unverify 率 + top 3 frequent unverified text
   - 损坏行 fail-safe skip (有 testcase 验)

2. 信任审计卡升级 (在 β.2.9.7 MEMORY_UPDATE 卡片下加新段):
   - 标题: "言出必行健康度"
   - 今日 claim/verify/unverify 数 + %
   - 7d ASCII trend chart
   - 类型分布 (Past N / Future N / State N / Recall N / Social N / Tool N)

3. compute_overall_status 加 headline:
   - verify_rate >= 80% → "健康" 绿
   - 60-80% → "留意" 黄
   - < 60% → "问题" 红

4. testcase: _test_p0_plus_20_beta44_dashboard_integrity_persist.py
   - 6 类: jsonl 解析 / 损坏行 fail-safe / time window 边界 / 阈值 / 中文渲染 / cross-module

5. 跑全测 92+/92+ OK → commit + tag v0.33.0-dashboard-integrity
6. 预期工时 ~2h.

完工后等 Sir 拍板进 Session 4 (L7 LLM-propose) 或实测反馈.
```

---

## ⚠️ Sir 操作提示

1. 上面整段一次复制到新对话窗口
2. Agent 自动按 Session 0 → 1 → 2 → 3 → 4 顺序推进
3. 每个 sub-step 完工 Agent 会汇报，你说"继续"就推进下一个
4. 真机实测有反馈直接发新消息，Agent 接住后继续

## 📦 当前 commit 链 (Agent 接手前必看)

```
0d62236 feat(P0+20-β.4.3.4): INTEGRITY_STACK Session 2.4 - L1+L2+L4 cross-module testcase + classifier tighten
3ce27b3 feat(P0+20-β.4.3.3): INTEGRITY_STACK L4 trace_to_evidence rewrite vocab+requirement table-driven
2ea4504 feat(P0+20-β.4.3.2): INTEGRITY_STACK L2 Evidence Requirements - table + CLI
60646c0 feat(P0+20-β.4.3.1): INTEGRITY_STACK L1 Claim Classifier - vocab + CLI
ca3d0f1 test(P0+20-β.4.2-hotfix-followup): β.4.1 testcase 兼容 time kind audit skip
0c9bc66 fix(P0+20-β.4.2-hotfix): Sir 18:46 实测 time claim 进 audit 死循环治本
d36e9eb feat(P0+20-β.4.1): INTEGRITY_STACK Session 1 - L4 ClaimTracer enforce + ALERT 注入
... (更早 commit 见 git log)
```

## 🎯 验收标准 (Session 2 完工后跑)

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
