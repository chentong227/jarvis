# JARVIS Soul Thought Loop — 闭环完整规划 (Sir 拍板用)

> Sir 真问 (2026-05-26 00:07):
> "构思一下不加新层级和新工具的情况下, 贾维斯现有的所有架构有没有能结合思考闭环的.
> 真正让思考影响他自身的, 构思一下, 必须是阅读所有架构以后才能下方案.
> 我希望贾维斯真的能通过思考改变自己"

**双约束**: 不加 Layer / 不加 daemon / 不加 module — 只在现有 `InnerThought.actionable parser + execute` 加分支, 接现有钩子.

**Phase 0 BUG fix 已完成** (commit `d6abec1`):
- 反思 evidence linking 双层 gate (准则 5 言出必行 + 6 evidence)
- L1: cite 必须真在 thought 里 (防 hallucinate cite)
- L2: cite 词跟 concern 至少 1 个 meaningful token overlap (防 wrong concern, 治 Sir 真痛 "toggling → interview_pr" anchor)
- 100 测试通过

**地基现已打牢**, 可以谈"思考改变自己" 真闭环.

---

## 1. 现状: 反思链已有, 但只闭 2/4 钩子

### 当前 InnerThought.actionable 4 档触达的现有架构钩子

| Actionable | 触达架构 | SOUL 路径 | 真改变贾维斯 |
|---|---|---|---|
| `none` | (无) | (无) | ❌ |
| `update_concern_severity:<id>:<delta>` | `ConcernsLedger.severity` | `@d:\Jarvis\jarvis_central_nerve.py:2464` Layer 1 inject 主脑 (summon/preflight_fail 才 inject) | ✅ 数值调 (sentinel trigger 频率随 severity 变) |
| `publish_swm:<etype>:<desc>` | `EventBus.publish` | 任何 sentinel 用 `bus.recent_events()` 都能 listen | ⚠️ 现有 sentinel 不 listen 自由 etype |
| `suggest_inside_joke:<phrase>` | `RelationalState.propose_inside_joke` → review queue → AutoArbiter 自决 (thr=0.75) | `@d:\Jarvis\jarvis_relational.py:1014` Layer 2 inject "MY VOICE/PHRASE QUIRKS" | ✅ 措辞风格变 (但是 callback 非约束) |

### 闭环缺口 (Sir 真痛 anchor 暴露)

启动 log 真证据:
```
💞 [RelationalState] jokes=5 protocols=0 unfinished=0 threads=15
```

- `protocols=0` — `RelationalState.unspoken_protocols` 接口**永远空着** (`@d:\Jarvis\jarvis_relational.py:331` `add_protocol` + `@d:\Jarvis\jarvis_relational.py:1017` Layer 2 "STRICT RULES, NOT SUGGESTIONS" 早就准备好)
- **B 类 self-reflection 没出口**: Sir 真测的 thought "I sounded too formal, my apology could be softer" → actionable=suggest_inside_joke (关系暗号, 不约束行为). 真该走 protocol 让下次 turn 主脑硬约束 "DO NOT open with formal apologies".
- **ConcernsLedger.notes_for_self** 字段闲置: `@d:\Jarvis\jarvis_concerns.py:460` `c.notes_for_self = ...` 写后, Layer 1 prompt 自然 inject 主脑下轮看. InnerThought 没接.
- **DirectiveRegistry 49 active**: 主脑 STRICT 用. InnerThought 没接, propose 接口存在但未触.

---

## 2. 三方案 (推荐顺序 A → B → C)

### 方案 A ⭐⭐⭐⭐⭐ — `actionable=propose_protocol` (B 类反思 → Layer 2 STRICT RULES)

**机制**:
- B 类 self-reflection sal ≥ 0.75 + LLM 抽 protocol phrase (1-2 句 STRICT 行为约束)
- `actionable=propose_protocol:<phrase>` 解析后 → `relational_state.add_protocol(UnspokenProtocol(state='review', source='inner_thought', ...))`  → AutoArbiter 30min tick 自决 (现 thr=0.75) → confidence high 真 activate
- 下次 turn `@d:\Jarvis\jarvis_central_nerve.py:3371` Layer 2 inject "OUR UNSPOKEN PROTOCOLS — STRICT RULES, NOT SUGGESTIONS" → 主脑下次 reply 真约束

**数据强耦合 + 准则 7 Sir 元否决**:
- 反思 evidence (B 类 thought 文字) → propose → AutoArbiter 自决 (Sir 一键 revert) → STRICT RULE → 主脑下轮真行为变
- Sir review queue dashboard 看 + 一键拒
- 不直接 mutate, 走 AutoArbiter 现有 review pipe

**工程量** (~80 行 + ~12 测试):
- `jarvis_inner_thought_daemon.py`:
  - `_execute_actionable` 加 `if a.startswith('propose_protocol:')` 分支
  - `_do_propose_protocol` 新 helper (~30 行): 解析 phrase, build UnspokenProtocol, 调 `relational_state.propose_protocol_dynamic` (新 API or 复用 add_protocol+state='review')
  - prompt 加 4-th actionable 选项 `propose_protocol:<one-sentence STRICT directive>`
  - prompt 加 grounding example (only B 类 sal≥0.75 + thought 含 "should/I'll/next time" pattern)
- `jarvis_relational.py`:
  - 若没 `propose_protocol_dynamic` API, 复用 `add_protocol` 但 state='review' (Sir review queue)
- `jarvis_auto_arbiter.py`:
  - 现已自决 protocol (thr=0.75), 不改

**风险 + Mitigation**:
- LLM 滥提 protocol → AutoArbiter confidence 看 thought salience + 评估 → 自然 filter
- 太多 STRICT 互相冲突 → Sir dashboard /items 一键删
- protocol 老化 → 现有 RelationalState 已有 decay (老化机制)

**测试** (~12 个 L1-L8):
- L1 actionable parse + execute branch
- L2 _do_propose_protocol 成功 propose
- L3 prompt 含 propose_protocol option + B 类 only example
- L4 evidence_link 双层 gate 复用 (cite 真在 thought + cite tokens 跟 protocol phrase overlap)
- L5 AutoArbiter 自决端到端 (mock review queue → 真 activate)
- L6 Layer 2 SOUL inject 含 protocol (现有路径无需新测)
- L7 Sir revert API 端到端
- L8 dashboard /relational 显示 inner_thought 来源 protocol

**验证 (Sir 真测)**:
1. 运行几小时 → 看 `python scripts/relational_dump.py protocols` 是否有 `source='inner_thought'` 新增
2. 看 dashboard /relational 是否能看到 + 一键 reject
3. 等下次 Sir 触发 B 类反思场景 → 下次 turn 主脑 prompt 看 "STRICT RULES" 有新增 → 行为真变

---

### 方案 B ⭐⭐⭐⭐ — `actionable=adjust_concern_notes` (C 类反思 → Layer 1 主脑下次看)

**机制**:
- C 类反思 sal ≥ 0.7 + LLM 抽 note text (主脑下次该怎么处理该 concern)
- `actionable=adjust_concern_notes:<concern_id>:<note text>` → `concern.notes_for_self = (existing + ' | ' + note).strip(' |')[:300]`
- 下次 Layer 1 inject 主脑 (现有路径 `@d:\Jarvis\jarvis_central_nerve.py:2464`) → 主脑 prompt 看 note → 自主调整对该 concern 的反应方式

**数据强耦合**:
- Sir 反应 evidence → reflection → concern.notes_for_self → 主脑下轮 prompt → 行为变

**真用 case** (Sir 真意 "减少对面试准备的打扰"):
- C 类 thought: "Sir asked me to stop bringing up interview prep unprompted. I should respect that."
- actionable: `adjust_concern_notes:sir_interview_pr:DO NOT volunteer this topic — only address when Sir asks directly`
- 下次 Sir 触发任何 sentinel 关于 interview_pr → 主脑读 note → 真克制

**工程量** (~50 行 + ~8 测试):
- `_execute_actionable` 加 `adjust_concern_notes:` 分支
- `_do_adjust_concern_notes` helper (~25 行): parse cid + note, 调 `concerns_ledger.update_concern_field(cid, 'notes_for_self', new_value)` (已存在)
- prompt 加 actionable option + example
- evidence_link 双层 gate 复用 (cite tokens 跟 concern overlap, 已 Phase 0 治本)

**风险**:
- LLM 改坏 note (覆盖 Sir 手设的) → mitigation: append 不覆盖 + 200 char cap (现有 schema)
- note 互相冲突 → Sir dashboard /concerns 看 + 改

**测试** (~8 个):
- L1 parse adjust_concern_notes
- L2 _do_adjust_concern_notes 真 update notes_for_self (mock ledger)
- L3 不覆盖, append 模式
- L4 evidence_link gate 复用 (cite ↔ concern overlap 已 Phase 0)
- L5 char cap 300
- L6 端到端: Layer 1 prompt 真含 note (用 _build_layer_1_concerns_block)
- L7 Sir 真痛 anchor: interview_pr add note "DO NOT volunteer" → 下次 prompt 真含
- L8 测试 mock concerns_ledger.update_concern_field 调用

---

### 方案 C ⭐⭐⭐ — `actionable=propose_directive` (D 类反思 → DirectiveRegistry → L2 conditional)

**机制**:
- D 类 proactive-seed sal ≥ 0.85 + LLM 抽 directive (trigger condition + content)
- `actionable=propose_directive:<id>:<trigger_func_name>:<content>` → `directive_registry.propose_directive` (新 review state)
- AutoArbiter 自决 (现 thr=0.9, 严)
- 命中下次 trigger context 主脑

**风险 (高)**:
- 49 active directive 已涌, 加更多可能噪音
- trigger function 需 Python 写 (LLM 给不出可执行 code) → 限制 LLM 只能 propose 文字 directive, trigger 用通用"always"
- AutoArbiter thr=0.9 严, 真正能 activate 的少

**工程量** (~120 行 + ~15 测试) — **最大**, **不建议先做**

**建议**: 暂不做, 先 A + B 跑 1-2 周, 看 Sir 真实需求再判. directive 已 49 条够 noisy.

---

## 3. 推荐执行顺序

### Phase 1 (推荐立刻做, 工程量小 + 价值最高): **方案 A** ⭐⭐⭐⭐⭐
- B 类反思 → propose_protocol → Layer 2 STRICT RULES
- ~80 行 + 12 测试 (~2-3h)
- 启动 log `protocols=0` → `protocols=N>0` 真证据闭环

### Phase 2 (再做, 工程量中, 治 Sir "减少对面试的打扰"): **方案 B** ⭐⭐⭐⭐
- C 类反思 → adjust_concern_notes → Layer 1
- ~50 行 + 8 测试 (~1.5h)
- 直接对应 Sir 真意

### Phase 3 (Sir 拍板再决): **方案 C** — 可暂缓或砍

---

## 4. Sir 决策点

| 问题 | 选项 |
|---|---|
| 方案 A 是否做? | (1) 立刻做 / (2) Sir 先观察 1 周再决 |
| 方案 B 是否做? | (1) A 完成后跟着做 / (2) 单独评估 |
| 方案 C 是否做? | (1) 暂缓 (推荐) / (2) 一起做 |
| AutoArbiter 自决 protocol 阈值 (现 0.75)? | (1) 保持 / (2) 调更严 0.85 (Sir 元否决 protocol 重要性) |
| protocol 老化策略? | (1) 复用 RelationalState 现有 decay / (2) Sir 手动管理不 decay |

---

## 5. 反规划 (不做这些事)

**禁止**:
- ❌ 加新 Layer / 新 daemon / 新 module (违反 Sir 双约束)
- ❌ Mutate sir_profile (违反准则 7 元否决)
- ❌ 让 InnerThought 直接改 directives_vocab.json (绕过 AutoArbiter)
- ❌ 让 InnerThought 自决 protocol (绕过 AutoArbiter + Sir review)
- ❌ 加新 sentinel listen "inner_thought_signal" (绕过现有 SWM 路径, 加新 listener 就是加 module)

**Sir 元否决 (准则 7)**: 所有 actionable 走 propose → review queue → AutoArbiter 自决 (Sir 一键 revert), 不直接 mutate persistent state.

---

## 6. 现有架构验收钩子 (Sir 真测)

实施后, Sir 真测应看到:

### 方案 A 真证据 (启动后 2-4h):
1. `python scripts/relational_dump.py protocols` 出 `source='inner_thought'` 新 protocol
2. dashboard `/relational` "Unspoken Protocols" 段非空, 显示 reviewed/active
3. dashboard `/auto_arbiter` 出 `kind=protocol` 决策 log
4. Sir 触发 B 类反思场景 (如自我纠错) → 下次 turn 主脑 prompt Layer 2 真含新 STRICT RULE

### 方案 B 真证据:
1. `python scripts/concerns_dump.py sir_interview_pr` 看 `notes_for_self` 非空 + 含 inner_thought 来源
2. dashboard `/concerns` 显示 concern note 新增

---

## 7. 工程估算 + Sir 时间承诺

| 阶段 | 工程量 | 测试 | 我承诺时间 | Sir 真测时间 |
|---|---|---|---|---|
| Phase 1 (A) | ~80 行 | 12 个 | ~2.5h | 启动后 2-4h 真证据 |
| Phase 2 (B) | ~50 行 | 8 个 | ~1.5h | 启动后 1-2h 真证据 |
| 文档更新 | (本文件) | - | - | Sir 阅读 ~10min |

**总计 (A+B)**: ~4h 工程 + 20 测试. 准则 8 优雅高效可持续.

---

**Sir 起床看完, 选择: A/B/C 顺序 + 现在拍板. 我执行 + push.**
