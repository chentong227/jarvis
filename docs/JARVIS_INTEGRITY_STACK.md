# Jarvis Integrity Stack — 言出必行 7 层分层架构 (+ 1 横向贯通层)

**版本**: v1.1 / 2026-05-18 (Sir 12:57 升级动态化原则)
**作者**: Sir 12:37 提出 + 12:53 vocab 反硬编码 + 12:57 升级架构原则 + Claude 综合
**地位**: 与 `INTEGRITY ABSOLUTE`（言出必行核心原则）和 `SOUL_DRIVE`（灵魂工程）**并列的第三条灵魂级模块**

## v1.1 升级核心 (Sir 12:57)

> "一切层级架构都要有动态修正的能力，并且不写死任何死编码，应该动态从对话中提取，
>  python 规则无法覆盖的部分引入 LLM。"

新加 **L0.5 Dynamic Vocab Substrate** — 横向贯通所有 7 层的基础设施层：所有 keyword/pattern/list 必须满足 3 硬规（持久化 + CLI 可改 + L7 LLM-propose）。详 AGENTS.md 准则 6.5.

> Sir 12:37 实测发现:
> "我觉得言出必行的约束还是太局限某些特殊的情况了。
>  言出必行不能做成一个大的分层的模块吗？有没有什么设计思路？"
>
> Sir 12:40:
> "甲+不停 A，是对的。完成手上的事，立项，然后给出推进的步骤"

---

## 0. TL;DR — 一句话

> **言出必行不是若干"特定情况的 directive"，而是 Jarvis 输出每一句话都要走的 7 层流水线** — 从立场（L0）到 claim 分类（L1）、evidence 要求（L2）、Pre-emit 拦截（L3）、Post-emit 审计（L4）、行动对账（L5）、可观察 dashboard（L6）、到自我修正循环（L7）。当前散点 directive 都是 L3 一层的局部产物。

---

## 1. 起点 — Sir 的核心洞察

### 1.1 Sir 12:37 提的问题

> 截图: Sir 跟 Jarvis 调侃终端，Jarvis 回 "I tend to view the decor as a shared responsibility" + 调整字体 — 主脑生成的话流畅，但 "I tend to view the decor as a shared responsibility" 已经是个 **state assertion**（声明"我视为共享"），是否需要 evidence？是否应该被 IntegrityStack 审计？

### 1.2 散点治理的局限

当前 14 条 directive 散在 `jarvis_directives.py`，每条对应一个 specific case：

| Directive | 治理的 case |
|---|---|
| `nudge_agenda_honesty` | "我已删提醒"假话 (β.2.7.x) |
| `tool_honesty_directive` | 工具失败假装成功 (P0+18-d) |
| `future_tense_capability_check` | "I can ..." 空头承诺 (β.1.11) |
| `memory_update_honesty` | "我已更新记录"假话 (β.2.9.9) |
| `correction_writepath_no_tool` | 纠正记忆假装调工具 |
| `fuzzy_candidates_policy` | 模糊匹配硬执行 |
| `promise_protocol_directive` | 真承诺时用结构化标签 |
| ... | ... 共 14 条 |

**问题**：
- 每次 Sir 发现新 case → 加一条 directive
- 数量 14 → 17 → 持续增长
- 主脑 prompt 注入越来越大
- 无统一审计 + 无主动迭代机制

### 1.3 Sir 想要的

**分层架构**:
- 每条 reply 自动走流水线
- 不同 claim 类别对应不同 evidence 要求
- 不仅 Pre-emit 拦截（已有），还要 Post-emit 审计 + Action 对账 + 自我修正

---

## 2. 7 层架构详图

```
╔═════════════════════════════════════════════════════════════════╗
║ L0.5  Dynamic Vocab Substrate (横向贯通所有 7 层)              ║
║      ── 准则 6.5: 所有 keyword/pattern/list 必须:               ║
║         (1) 持久化 memory_pool/*.json                          ║
║         (2) CLI 工具 scripts/<thing>_dump.py 看/加/激活/拒绝   ║
║         (3) L7 Reflector LLM-propose 新 vocab 入 review        ║
║      已立此规范: concerns / directive_registry / relational /   ║
║                 behavior_inference_vocab                       ║
║      待补 (任何新模块都自动适用): predicate library / claim     ║
║              分类器 vocab / evidence 要求表 / tool overture     ║
║              vocab / dashboard_intent vocab / memory_correction ║
║              vocab / etc.                                       ║
╠═════════════════════════════════════════════════════════════════╣
│ L0  根本立场  ── INTEGRITY ABSOLUTE 静态 PERSONA                │
│      Jarvis 的"魂"，不可绕过的根本规则                         │
│      ── 现状: ✅ 已有                                          │
├─────────────────────────────────────────────────────────────────┤
│ L1  Claim 分类  ── 任何 reply 自动归为 6 类之一                │
│   ① Past-action     ("我已 X / I've done Y")                   │
│   ② Future-action   ("我会 X / I'll Y")                        │
│   ③ State assertion ("现在是 11 点 / X 是开的")                │
│   ④ Recall          ("你昨天提过 X / 我们之前讨论过")          │
│   ⑤ Social opener   ("Welcome back / 好的")                    │
│   ⑥ Tool intent     (emit FAST_CALL)                          │
│      ── 现状: ❌ 缺 ── 没有 Claim 分类器                       │
├─────────────────────────────────────────────────────────────────┤
│ L2  Evidence 要求  ── 每类对应必备 evidence                    │
│   ① Past-action     → 必须有真 FAST_CALL result / DB 写入       │
│   ② Future-action   → 必须 skill_registry 含 + 兑现追踪         │
│   ③ State assertion → 必须有 fresh sensor / hippocampus 索引    │
│   ④ Recall          → 必须 STM/LTM 索引命中                    │
│   ⑤ Social opener   → 无需 evidence (社交无害)                 │
│   ⑥ Tool intent     → 无需 evidence (是动作不是声明)           │
│      ── 现状: ❌ 缺 ── 规则散在 directive 文本里               │
├─────────────────────────────────────────────────────────────────┤
│ L3  Pre-emit Filter  ── 生成前 directive 阻断                  │
│      14 条 directive (jarvis_directives.py) 都是这层产物       │
│      ── 现状: ⚠️ 部分 ── 散点 case-by-case, 缺统一框架         │
├─────────────────────────────────────────────────────────────────┤
│ L4  Post-emit Audit  ── reply 完成后 ClaimTracer 审计          │
│      抓 reply 里的 specific claim → 查 evidence 是否真存在     │
│      不存在 → terminal warning + audit log +                  │
│              下一轮 prompt 注入"上一轮 X 未 verify, 主动撤回"  │
│      ── 现状: ⚠️ 半 ── ClaimTracer 只 trace 不 enforce         │
├─────────────────────────────────────────────────────────────────┤
│ L4.5  Active Verify+Retry  ── IntegrityWatcher (P5 / Sir 14:11)│
│      L4 是被动 audit (写 log), L4.5 主动 verify mutation 是否真完成│
│      失败递归 retry, 真做不到 → handoff Sir 手动方案           │
│      Sir 14:11: "wachter 负责贾维斯所有行为(除调 tool)是否成功的 │
│      审查机构, 植入言出必行层级中. 主动重试, 真做不到给 Sir 道歉│
│      并且提出让 Sir 手动解决的方案"                             │
│      Sir 14:30: vocab + LLM 二维 (3 层 waterfall — vocab 主路径,│
│      LLM 仅边界 case async judge), 不阻塞 TTFT                  │
│      监督 Jarvis 内部 8 类: reminder/commitment/promise/memory/ │
│      milestone/profile/concern/relational                       │
│      Tool 失败本身让主脑知道 (主脑→工具→主脑路径), 不归 watcher │
│      ── 现状: ✅ P5 完工 (β.5+ commit c116938)                 │
├─────────────────────────────────────────────────────────────────┤
│ L5  Action-Reconciliation  ── 行动结果对账 (灵魂闭环)          │
│      Jarvis 承诺 → PromiseLog → 履约/违约 detect →             │
│        反馈 concern.severity ±                                  │
│      Sir 承诺 → CommitmentWatcher → 履约/违约 detect →         │
│        反馈 concern.severity ±  (Sir 10:43 灵魂级要求)         │
│      ── 现状: ✅ 已做 (β.2.9.11 commit ?? — 本轮成果)          │
├─────────────────────────────────────────────────────────────────┤
│ L6  Integrity Dashboard  ── 透明度可观察                        │
│      dashboard "信任审计"卡片 (β.2.9.9 已有)                  │
│      加: claim 数 / verify 数 / unverify 比例 / 兑现率统计     │
│           每日/每周趋势                                         │
│      ── 现状: ⚠️ 半 ── 信任审计卡有, 统计粒度浅                │
├─────────────────────────────────────────────────────────────────┤
│ L7  Self-Correction Loop  ── 每周自反思 + propose 迭代         │
│      WeeklyReflector 看 L4 audit log + L5 履约率              │
│      → 高 unverified rate → propose 改 PERSONA / 加新 directive│
│      → Sir review queue → 半自动迭代                           │
│      ── 现状: ❌ 缺                                            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 当前实现状态盘点（截 2026-05-20 β.5.25, 全 STACK ✅）

> 🩹 [β.5.25-doc-sync / 2026-05-20] Sir 02:33 反馈"看看文档有什么尾巴". 全扫发现
> L1/L2/L3/L4/L6/L7 文档 stale (实际 β.4.x 已完成). 此表全 sync 真状态.

| 层 | 状态 | 已做 | commit / marker |
|---|---|---|---|
| **L0.5** | ✅ | 14 directive / claim 分类 / tool overture / dashboard intent / behavior vocab 全迁 json + CLI | β.2.9.12 + β.3.0-vocab1-3 + β.5.23-A (cooldown vocab 也加入) |
| L0 | ✅ | INTEGRITY ABSOLUTE 在 PERSONA | (持续维护) β.5.21 加 review/look at 动词 + 异步承诺 FORBIDDEN |
| L1 | ✅ | Claim 分类器完成 (jarvis_claim_classifier.py + vocab json + CLI + LLM 二次判) | β.4.3 |
| L2 | ✅ | EvidenceRequirements 中央表 (jarvis_evidence_requirements.py + json) | β.4.3 |
| L3 | ✅ | directive_registry.json 全迁 + CLI registry_dump.py + review queue + propose 接口 | β.4.6 |
| L4 | ✅ | ClaimTracer enforce + integrity_audit.jsonl + 下一轮 prompt 注入撤回 | β.4.1 + β.4.3.3 + β.4.2-hotfix |
| **L4.5** | ✅ | **IntegrityWatcher** (P5 / Sir 14:11): 主动 verify Jarvis 内部 8 类 mutation, 失败递归 retry, 真做不到 handoff Sir + actionable. 3 层 waterfall (vocab + kw gate + LLM async). vocab `memory_pool/integrity_claim_vocab.json`, kw `integrity_suspicious_kw.json`, CLI `scripts/integrity_claim_vocab_dump.py`, prompt block `[INTEGRITY WATCHER REPORT]` | β.5+ commit c116938 |
| L5 | ✅ | β.2.9.11 闭环 A + infer vocab json 迁完 (β.2.9.12) + **β.5.22-C 动态语义反馈 LLM judge** (Concern.daily_progress + ConcernsLedger.record_user_feedback API + post_chat hook + urgency 反向注入) | β.2.9.11 + β.5.22-C |
| L6 | ✅ | dashboard 信任审计卡 + 兑现率 + 7d 趋势 ASCII chart + Web Dashboard 言出必行宽卡 (top 5 空头话) | β.4.4 Session 3 + **β.5.25 web** |
| L7 | ✅ | IntegrityReflector LLM-propose + **β.5.23-B ConcernFeedbackReflector 24h daemon** (看 7d STM + nudge 推送量 + Sir 拒绝量 → QuickClassifier.prompt_raw propose cooldown 调整 → 写 review_queue) | β.4.5.2 + β.5.23-B |

**STACK 全 ✅, 不再有 ❌/⚠️.** 后续维护 = 加新 vocab / 调阈值 / 应对真机新 BUG.

---

## 4. 推进步骤 — 5 个 session 分阶段 (v1.1 加 Session 0 vocab 迁移)

### Session 0 — L0.5 Dynamic Vocab Substrate 全面迁移（必须先做，~3h）

**目标**: 把现有所有 py-hardcoded vocab 迁到 json + CLI + 预留 LLM-propose 接口

按 AGENTS.md 准则 6.5 审计现有 py 文件, 找所有 `_XXX_PATTERNS = [...]` / `_XXX_KEYWORDS = (...)`:

| 当前位置 | 迁移目标 |
|---|---|
| `jarvis_directives.py:_TOOL_INTENT_PATTERNS` (打开/关闭/搜) | `memory_pool/tool_intent_vocab.json` + `scripts/tool_intent_dump.py` |
| `jarvis_directives.py:_DASHBOARD_INTENT_PATTERNS` | `memory_pool/dashboard_intent_vocab.json` + CLI |
| `jarvis_directives.py:_MEMORY_CORRECTION_PATTERNS` | `memory_pool/memory_correction_vocab.json` + CLI |
| `jarvis_inconsistency_watcher.py:_SIR_SLEEP_VERBS / _JARVIS_WRAPPER_MARKERS / _SIR_BREAK_VERBS` | `memory_pool/inconsistency_vocab.json` + CLI |
| `jarvis_proactive_care.py:_RESPONSE_POSITIVE / _RESPONSE_NEGATIVE` | `memory_pool/response_classify_vocab.json` + CLI |
| `jarvis_commitment_watcher.py:_BEHAVIOR_PATTERNS` | ✅ 已迁 `memory_pool/behavior_inference_vocab.json` (β.2.9.12) |
| `jarvis_memory_core.py:FeedbackTracker._correction_patterns` | `memory_pool/feedback_vocab.json` + CLI |
| `jarvis_soul_reflector.py:CONCERN_KEYWORDS` | `memory_pool/concern_keywords_vocab.json` + CLI |

每个迁移 step 独立 commit, 跟 β.2.9.12 一样的范式: `_SEED_X` py 留 fallback + json 优先 + mtime cache + CLI.

### Session 1 — L5 + L4 enforce（本周完成，~3h）

**目标**: 关闭闭环 + ClaimTracer 升级 trace → enforce

- ✅ L5 闭环 A（β.2.9.11 本轮完工，commit 3a89168 + testcase 19 通过）
- ⏳ L4 enforce 升级：
  - ClaimTracer 把 unverified claim 记入 `memory_pool/integrity_audit.jsonl`
  - 下一轮 `_assemble_prompt` 头部 prepend "[INTEGRITY ALERT] 上一轮你 X claim 未 verify (evidence missing), 主动撤回或补 evidence"
  - 主脑被强制 acknowledge 上轮 unverified

### Session 2 — L1 + L2（中期，~5h）

**目标**: 加 Claim 分类器 + Evidence 要求中央表

- 新 `jarvis_claim_classifier.py`:
  - 入口 `classify(reply_text) → ClaimType` (6 类)
  - **vocab 持久化**: `memory_pool/claim_classify_vocab.json` + CLI + LLM 二次判 fallback
  - 用 regex (从 json 加载) + LLM-1.5B 二次判 (前者快、后者细)
- 新 `jarvis_evidence_requirements.py`:
  - 中央表 `EvidenceRequirements[ClaimType] = required_evidence_kinds`
  - **持久化** `memory_pool/evidence_requirements.json` + CLI 可改
  - 给 L4 ClaimTracer 反查
- L3 directive 不动（仍兼容）但减少新增

### Session 3 — L6 dashboard 升级（短期，~2h）

**目标**: dashboard 信任审计卡升级 + 加趋势

- 加 reader `read_integrity_stats()` 从 `integrity_audit.jsonl`
- dashboard 卡片显示:
  - 今日 claim 数 / verify 数 / unverify 数 / 兑现率
  - 7d 趋势 ASCII chart
  - 顶部整体评估加 "言出必行健康度: ✅/⚠️/❌"

### Session 4 — L7 自我修正 + LLM-propose（长期，~6h，灵魂级）

**目标**: WeeklyReflector 看 L0.5 所有 vocab + L4 audit log + L5 履约率 → LLM-propose 新 vocab/directive 入 review

- WeeklyReflector 加 `_reflect_vocab_gaps()`:
  - 扫 7d 对话 STM/LTM, 找不能命中现有 vocab 但语义关键的 token
  - 用 Gemini-3-Flash LLM 提取候选 vocab → 写 review queue
  - Sir CLI review → activate → 自动加进对应 json
- WeeklyReflector 加 `_reflect_integrity_audit()`:
  - 扫 7d `integrity_audit.jsonl`
  - 找 unverified claim 类型分布 (e.g. "Past-action 类 unverify 率 30%")
  - LLM-propose 新 directive 入 review
- **核心契约**: Sir 永远是仲裁人, propose 只入 review, Sir 拍板才生效

---

## 5. 与现有 SOUL_DRIVE 的关系

| 维度 | SOUL_DRIVE (β.2 灵魂工程) | INTEGRITY_STACK (β.3+ 言出必行) |
|---|---|---|
| 关注 | "Jarvis 是谁 / 关心什么 / 跟 Sir 之间" | "Jarvis 说的话靠不靠谱" |
| 数据源 | Concerns / Relational / SelfAnchor | PromiseLog / CommitmentWatcher / ClaimTracer |
| 输出 | nudge 主动话 / prompt 注入 | claim 拦截 / 撤回提示 / 审计 log |
| 关系 | INTEGRITY 是 SOUL 的护栏 — Jarvis 关心 Sir 的同时, 言出必行约束他不说做不到的事 |

两者通过 L5 (Action-Reconciliation) 连通: 履约/违约 → 反馈 concern severity. 闭环。

---

## 6. 验收（Sir 拍板用）

完整完成 4 个 session 后, Sir 实测应感到:

1. **Past-action**: Jarvis 说"我已 X" → 必有真工具 result, 否则被 L4 拦截
2. **State**: Jarvis 说"现在是 11 点" → 必有真 sensor 读, 否则被 L4 拦截
3. **Recall**: Jarvis 说"你昨天提过 X" → 必有 STM/LTM 索引, 否则被 L4 拦截
4. **Future**: Jarvis 说"I'll X" → 必有 skill_registry + L5 兑现追踪
5. **Social**: "Welcome back" 不被拦 (不是 claim, 是社交)
6. **dashboard**: 一眼看 7d 兑现率 / unverify 比例 / 趋势
7. **WeeklyReflector**: 每周自动 propose "近期 Past-action 漏 verify 多, 建议加 directive X"

---

## 7. 当前迭代成果（β.2.9.11 commit ??）

**L5 灵魂闭环 A 完工**:
- `CommitmentWatcher.add_commitment` 加 `concern_link` + `expected_behavior` 字段
- `infer_concern_link(description)` — 复用 ConcernsReflector `CONCERN_KEYWORDS` 反查
  （准则 6: 加新 concern → 此函数自动覆盖, 0 改动）
- `infer_expected_behavior(description)` — vocab 表驱动 4 类:
  - `idle_min` (sleep/rest) / `process_exit` (剪完视频) / `stm_contains` (任务) / 更多扩展
- `_backfill_concern_link` — ProactiveCare nudge 后 120s 内 register 的 commitment 自动关联
- `_check_fulfillment` — 通用 4 类验证 (准则 6 kind 驱动)
- `_on_fulfillment` — 履约: severity -= 0.2 + notify_aligned; 违约: severity += 0.1 + notify_rejected
- PromiseLog 配对 evidence: 履约也算 Jarvis 言出必行的证据
- 19 testcase 验证 (覆盖 4 类 fulfillment + auto infer + 反馈 ledger/pce/promise_log)

---

## 8. 路线图

| Session | 何时 | 内容 | 验收 |
|---|---|---|---|
| **0** | ✅ β.3.4 完工 | L0.5 vocab 全面迁移 (7 项 py-hardcoded → json + CLI) | py 不再含任何 Session 0 scope 内 `_XXX_PATTERNS = [...]`, 审计 Grep 范围内 0 命中, tag `v0.31.0-dynamic-vocab-substrate` |
| 1 | ✅ β.4.1 完工 | L5 闭环 (✅ β.2.9.11) + L4 enforce (✅ β.4.1) | claim 未 verify 时 ALERT 注入下一轮 prompt, tag `v0.31.1-claim-enforce` |
| 2 | 下周 | L1 Claim 分类器 + L2 Evidence 表 (都 json + CLI) | claim 自动分类 + evidence 要求中央化 |
| 3 | 下周 | L6 dashboard 升级 + 趋势 | Sir 看 7d 兑现率 |
| 4 | 下下周 | L7 WeeklyReflector LLM-propose + Sir review | 每周自动 propose 新 vocab/directive, Sir CLI 一键拍板 |
| **5** (β.5+) | **章程治理升级** | **L8 章程合规 Reflector (水位 4)** — 扫每 agent commit / 双层报告, 自动 detect 违反 `AGENTS.md §9.X` 双层 / §1 准则 / `JARVIS_PYTHON_STYLE.md` 任何条款 → 写 `memory_pool/charter_compliance_review.json` queue → Sir `scripts/charter_compliance_dump.py --review` 看. **β.4 stress test 暴露真违章数据后启动**, 不空建 | 当 Windsurf/Cursor/其他 agent 累计被 detected ≥ 5 个 missable 违章时, 真实数据驱动设计 |

### 8.1 Session 5 设计原则 (β.3.5 沉淀)

- **Sir 章程治理已到水位 3** (β.3.3 testcase 红线 + β.3.6 docs 漂移 detect). 水位 4 是"自动监督"的 L8 Reflector
- **不空建**: 等真实违章数据积累 (β.4 stress test 后) 再实施, 避免基于猜想设计 → 设计跑偏
- **复用 L7 (WeeklyReflector) 基础设施**: 同步 daemon / 同 review queue / 同 CLI 模式, 不另起炉灶
- **Sir 仲裁仍是唯一 ground truth**: Reflector 只 propose 不 enforce, 任何"违章" 都需 Sir `--accept` 才算
- **递归终止**: Reflector 自己也是 `< 400 行` 单文件硬规, 不再下钻"Reflector 监督 Reflector" (准则 6.5 递归边界 / AGENTS.md §1 末)

### 8.2 启动条件 (β.5 是否启动?)

启动: **当下面任一条件满足**:

1. β.4 完工后 Sir 跑 Windsurf/Cursor 实测累计 ≥ 5 个 "应该被章程挡住但 testcase 没挡住" 的 missable 违章
2. Sir 主动决策"章程治理优先级 > 新功能"
3. 章程膨胀超 cap (AGENTS.md > 400 / 必读总和 > 1500) 但精简效果有限, 需自动化辅助治理

不启动条件: β.4 / β.5 任务挤压 + 实测违章率 < 1 个/周 → 推迟到 β.6+

---

*文档作者: Sir 12:37 提出 + Claude 12:40 立项 / 2026-05-18*
*β.3.5 路线升级: 加 Session 5 L8 章程合规 Reflector (水位 4 路线沉淀) / 2026-05-18.*
*这是和 INTEGRITY ABSOLUTE + SOUL_DRIVE 并列的第三条灵魂级架构.*
*下个 Agent 接手按 Session 顺序推进, 不要跳序.*
