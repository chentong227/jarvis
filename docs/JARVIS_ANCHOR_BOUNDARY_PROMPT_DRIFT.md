# anchor_boundary_block 真 prompt 对账 — 只读厘清 (供顾问对账 3f2a41f)

> **[anchor-boundary-drift / 2026-06-07]**
> 只读勘察, 未改任何码/真机/flag。整机 B (headless) 抓到的真集成漏洞的对账报告。
> 核心问题: anchor_boundary_block(walls + conflict_guidance + affordance)到底什么进真主脑 prompt。

---

## 1. 口 (central_nerve) 真输出 prompt 含哪些 section

**真输出 = legacy mega f-string** (`jarvis_central_nerve.py:4699`) → 经 PromptBuilder 的 `legacy_full` block(`audit_only=False` 真渲染, `:4906-4912`)passthrough 输出。

legacy mega f-string (`:4699-4783`) 实际拼接的变量(逐字枚举):
```
core_persona / yesterday_block / stm_context / [CONTINUITY RULE] /
open_threads_block / project_block / active_reminders_block /
available_skills_block / tool_honesty_directive / fuzzy_candidates_policy /
promise_protocol_directive / swm_block / event_bus_block / attention_block /
working_feed_block / active_plan_block / tone_directive / avoid_phrases_block /
verbosity_block / soul_chapters_str / how_to_respond / time_persona /
context_str / _pc_block_value / correction_context / style_adjustment /
content_pref / unified_memory / skill_tree_str / anticipator_ctx / ledger_str /
life_log_context / landmarks_str / tier_routing / chat_organs /
translator_schema_block / ltm_context / commitment_context / current_time /
sensor_state_block / _l2_injected_block / user_input / system_alert_text
```

**`anchor_boundary_block` 不在这个 f-string 里。** (逐行确认 `:4699-4783`,无该变量。)

---

## 2. 各块挂在哪 / 是否 audit_only

| 块 | 赋值点 | 进真输出? | 证据 |
|---|---|---|---|
| `anchor_boundary_block` (变量) | `cn:4340-4362` (render_walls_block + conflict_guidance + affordance 拼成) | ❌ | 只挂 `skills_section` |
| → walls (`render_walls_block`) | `cn:4343` | ❌ | 同上 |
| → conflict_guidance (`render_conflict_guidance`) | `cn:4346` | ❌ | 同上 |
| → affordance (`render_affordance_block`) | `cn:4355` (327ebb4) | ❌ | 同上 |
| `skills_section` (含 anchor_boundary_block) | `cn:4867-4871` | ❌ **audit_only=True** | `cn:4845` 注释"audit_only=True → 不渲染, 仅 audit. legacy mega 仍是真输出" + `:4899-4904` BlockSpec audit_only=True |
| `legacy_full` (= legacy mega) | `cn:4906-4912` | ✅ **audit_only=False** | 真渲染, 但内容 = `result.strip()` (f-string, 不含 anchor_boundary_block) |

**口侧结论**: walls / conflict_guidance / affordance **三者均未进口主脑真输出 prompt**。它们活在 `skills_section`(audit-only, 不渲染)。

---

## 3. 对账 3f2a41f 快照"conflict_guidance 已进口 cn:4345"

**该条是漂移误判, 登记在案。** 快照看到 `cn:4345` 有 `render_conflict_guidance()` 调用 + 赋给 `anchor_boundary_block`,据此判"进了 prompt"。但**赋值 ≠ 进真输出**——该变量只接到 audit-only section,从未拼进 legacy mega。

⟹ **衡 H3 现场权衡良心之声(conflict_guidance)从未到达口主脑。** 同理 walls(衡 H1 锚边界)也没到口主脑。快照 §4.1/§5 关于"口侧锚墙/冲突指引已注入"的描述应更正为"仅 audit-only, 未进真输出"。

---

## 4. 口 / 识 分开答 (关键差异)

| 路 | anchor_boundary 内容进真 prompt? | 证据 |
|---|---|---|
| **口 (central_nerve)** | ❌ **没进** | `anchor_boundary_block` 只在 audit-only `skills_section`,不在 legacy mega f-string(§1/§2) |
| **识 (daemon)** | ✅ **真进** | `daemon._build_prompt`: `_anchor_walls`(walls + conflict_guidance + affordance)在 `:4436` 真拼进 `system` prompt 字符串(`f"{_anchor_walls}"`),system 是 daemon LLM 的真 prompt |

**⟹ 识侧锚边界(含衡 H3 冲突指引 + affordance)真到达思考脑;口侧三者全漂。** 这是口/识两路的不对称:同一份 render 函数,识接对了(进 system),口接错了(进 audit-only)。

---

## 5. 漂移起点 (commit / file:line)

- **起点 = `b10796f` feat(anchor-P1) 言出必行边界块注入主脑** —— 引入 `anchor_boundary_block` 时**就直接接在 `skills_section`**(audit-only section),从未接进 legacy mega f-string。
- 证据:`git log -S anchor_boundary_block -- jarvis_central_nerve.py` → b10796f 的 diff 显示新增 `anchor_boundary_block = ""` + `render_walls_block()` 赋值 + `('skills_section', ...[anchor_boundary_block])`,**无对 legacy f-string 的改动**。
- b10796f 注释自称"注入 central_nerve skills_section (gated)",但 skills_section 当时已是 `audit_only=True`(P5-fix66 `audit_only` 机制早于 anchor P1)。
- **非后续回归**:walls 口侧从 anchor P1 第一天起就没进真输出。后续 `c66de29`(conflict_guidance)+ `327ebb4`(affordance)都接到同一个漂移变量,继承了同一漏。

---

## 6. 给顾问的对账结论

| 项 | 真相 |
|---|---|
| 口主脑真输出含 anchor_boundary? | ❌ 否(walls/conflict/affordance 全在 audit-only,未渲染) |
| 识思考脑真输出含 anchor_boundary? | ✅ 是(`daemon:4436` 真拼进 system) |
| 3f2a41f"conflict 进口 cn:4345" | 漂移误判(赋值≠进输出);衡 H3 现场良心之声从未到口主脑 |
| 漂移起点 | `b10796f`(anchor P1),引入即接错到 audit-only section,非回归 |
| 修法方向(需顾问/Sir 定) | 把 anchor_boundary_block 接进 legacy mega f-string(`cn:4699` 区,如紧跟 promise_protocol_directive 后),= 改口主脑真输出 = 真机行为半径,需 B 验 + 审 |

**影响面**: 这不止 affordance —— 衡 H1(墙边界)+ 衡 H3(冲突逐案权衡)在**口主脑**层一直是空投(只识侧生效)。修这个漂移会让口主脑首次真正看到锚墙 + 冲突指引 + affordance,是一次有行为半径的改动,应作为独立轨、走 B + Sir 审。

---

*只读厘清, 未改任何码/真机/flag。真盘 energy_grounded_only=1 未动。证据: file:line + commit hash 供抽查。*
