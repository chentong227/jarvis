# Jarvis Integrity Stack — 言出必行 7 层分层架构

**版本**: v1.0 / 2026-05-18
**作者**: Sir 12:37 提出 + Claude 综合设计
**地位**: 与 `INTEGRITY ABSOLUTE`（言出必行核心原则）和 `SOUL_DRIVE`（灵魂工程）**并列的第三条灵魂级模块**

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
┌─────────────────────────────────────────────────────────────────┐
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

## 3. 当前实现状态盘点（截 2026-05-18 β.2.9.11）

| 层 | 状态 | 已做 | 缺什么 |
|---|---|---|---|
| L0 | ✅ | INTEGRITY ABSOLUTE 在 PERSONA | — |
| L1 | ❌ | — | Claim 分类器 (LLM-based or pattern-based) |
| L2 | ❌ | Evidence 要求散在 directive 文本 | 中央 EvidenceRequirements 表 |
| L3 | ⚠️ | 14 条 directive | 统一注册表 + claim 类型 → directive 反查 |
| L4 | ⚠️ | ClaimTracer 抓 | enforce: 下一轮 prompt 注入"撤回上一句" |
| L5 | ✅ | β.2.9.11 闭环 A (本轮) | (基本完整) |
| L6 | ⚠️ | dashboard 信任审计卡 | 兑现率 / claim verify 比例 / 趋势图 |
| L7 | ❌ | — | WeeklyReflector 接 audit log → propose 改 PERSONA |

---

## 4. 推进步骤 — 4 个 session 分阶段

### Session 1 — L5 + L4 enforce（本周完成，~3h）

**目标**: 关闭闭环 + ClaimTracer 升级 trace → enforce

- ✅ L5 闭环 A（β.2.9.11 本轮完工，commit ?? + testcase 19 通过）
- ⏳ L4 enforce 升级：
  - ClaimTracer 把 unverified claim 记入 `memory_pool/integrity_audit.jsonl`
  - 下一轮 `_assemble_prompt` 头部 prepend "[INTEGRITY ALERT] 上一轮你 X claim 未 verify (evidence missing), 主动撤回或补 evidence"
  - 主脑被强制 acknowledge 上轮 unverified

### Session 2 — L1 + L2（中期，~5h）

**目标**: 加 Claim 分类器 + Evidence 要求中央表

- 新 `jarvis_claim_classifier.py`:
  - 入口 `classify(reply_text) → ClaimType` (6 类)
  - 用 regex + LLM-1.5B 二次判（前者快、后者细）
- 新 `jarvis_evidence_requirements.py`:
  - 中央表 `EvidenceRequirements[ClaimType] = required_evidence_kinds`
  - 给 L4 ClaimTracer 反查"这类 claim 应有什么 evidence"
- L3 directive 不动（仍兼容）但减少新增（让 L1+L2+L4 自动覆盖）

### Session 3 — L6 dashboard 升级（短期，~2h）

**目标**: dashboard 信任审计卡升级 + 加趋势

- 加 reader `read_integrity_stats()` 从 `integrity_audit.jsonl`
- dashboard 卡片显示:
  - 今日 claim 数 / verify 数 / unverify 数 / 兑现率
  - 7d 趋势 ASCII chart
  - 顶部整体评估 + 加 "言出必行健康度: ✅/⚠️/❌"

### Session 4 — L7 自我修正（长期，~4h）

**目标**: WeeklyReflector 看 L4+L5 数据 → propose 改 PERSONA / 加 directive

- WeeklyReflector 加 `_reflect_integrity_audit()`:
  - 扫 7d `integrity_audit.jsonl`
  - 找 unverified claim 类型分布 (e.g. "Past-action 类 unverify 率 30%")
  - propose 新 directive 加入 review queue
- Sir review → activate → 自动加进 L3

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
| 1 | **本周** | L5 闭环 (✅ β.2.9.11) + L4 enforce | Sir 实测看 reply 含"我已 X"未 verify 时主脑下一轮撤回 |
| 2 | 下周 | L1 Claim 分类器 + L2 Evidence 表 | claim 自动分类 + evidence 要求中央化 |
| 3 | 下周 | L6 dashboard 升级 + 趋势 | Sir 看 7d 兑现率 |
| 4 | 下下周 | L7 WeeklyReflector 自我修正 | 每周自动 propose 新 directive |

---

*文档作者: Sir 12:37 提出 + Claude 12:40 立项 / 2026-05-18*
*这是和 INTEGRITY ABSOLUTE + SOUL_DRIVE 并列的第三条灵魂级架构.*
*下个 Agent 接手按 Session 顺序推进, 不要跳序.*
