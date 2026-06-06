# 识 + 衡 (+ 说) 架构完整方案 — 给顾问消化

> **[mind-heng-arch-map / 2026-06-06]**
> 用途: 件 B (建造前置)。止血 (件 A 势能层接地化) 给共演化清场; 清完场要进建造 (重设计识怎么想 / 衡怎么仲裁 / 体结构怎么长)。建造不能在碎片上做 — 本文给顾问一张和体那张图 (`JARVIS_BODY_ARCHITECTURE_MAP.md` 块1-6) **同等保真度** 的识+衡全景。
> 方法: 真读代码, 标 file:line, 不凭印象。
> 真理源代码: `jarvis_inner_thought_daemon.py` (识, ~9700 行) / `jarvis_auto_arbiter.py` (衡) / `jarvis_anchors.py` + `jarvis_self_anchor.py` (锚) / `jarvis_central_nerve.py` (说/口, 主脑 prompt 组装).
> **B 只读, 未改任何代码、未碰 flag。**

---

## 块1. 识 (InnerThoughtDaemon) — 自发思考的引擎

### 1.1 tick 主循环 (`daemon.py:_tick:2514`) — 一个 tick 怎么决定想不想 / 想什么

```
_tick (2514)
 ├─ sweep ignored / watch-task vision refresh (顶跑, 纯 Python 不烧 token)
 ├─ sir_state = _classify_sir_state()             # 反应式语境 (Sir 在不在/忙不忙)
 ├─ ① 想不想 (3 道闸, 全是 Python 节流, 省 token):
 │    a. cooldown/emergent 预选 (2550-2602)
 │       - emergent 模式: free_categories = ABCDE (拔类冷却, 靠体势能+REST 接管)
 │       - legacy 模式: 全 5 类 cooldown → return 不调 LLM
 │    b. evidence = _collect_evidence (2589)        # 纯 Python 采证
 │    c. evidence-gate skip (2604-2620)             # 指纹同上次 → skip LLM, daemon 仍 alive
 ├─ ② 想什么 (烧 token 段):
 │    a. channel_view = _build_channel_view (2625)  # 7-channel 重组 + 上轮 attention hint
 │    b. prompt = _build_prompt (2630)              # 注入体/锚/concern/STM
 │    c. raw = _call_llm (2634)                     # Flash-Lite, P2 LOW 优先级
 ├─ ③ REST 决策 (2649): 识主动"放下" — settled 无真势能 → <REST> 歇, 不产 filler
 ├─ ④ recall/note tag 处理 (2660-2680, 自发深召回/自写记忆)
 ├─ ⑤ thought = _parse_thought (5716)              # 抽 CATEGORY/THOUGHT/SALIENCE
 └─ ⑥ 执行 actionable + tempo 决策 (见 1.4/1.5)
```

### 1.2 反应式 vs 自发式 — 两条路径 (关键区分)

**Jarvis 的"想"不是单一路径。** 反应式 (Sir 说话→想) 和自发式 (体势能→自发起想) 在**不同层**汇入同一个 `_tick`:

| 维度 | 反应式 | 自发式 |
|---|---|---|
| 触发源 | Sir 说话 / 高 salience SWM event | 体势能 fresh delta (Weaver 派的 body_delta) |
| 入口 file:line | 紧急唤醒 `_should_emergency_wake:1944-1994` + STM 进 evidence/指纹 `_compute_evidence_fingerprint` (STM 最新 turn 段) | `wake_on_body_delta:2001-2017` + 指纹纳入体势能 `2326-2333` |
| 怎么影响 tick | 中断 wait 立即 tick (≈反应) | 撤销 value-backoff 退避回基线 `tick_origin='body_delta_wake':2819-2841` |
| 决定"想什么" | sir_state + STM 进 prompt | BODY SIGNALS (高势能区) 进 prompt `4749-4779` |

**关键**: 自发式的"想什么"由 **BODY SIGNALS** 决定 (`_build_prompt:4749` 调 `get_body_focus().render_attention_block(limit=5)`) — 识 attend 体此刻最高势能区, 而非凭空联想。**这正是件 A 的命门**: 势能若数假焊 → 自发思考被带去 attend 假焊区 (实测 4 对双高频假焊 + 洗白 8:0)。

### 1.3 识读体的四条通道 (体→识)

| # | 通道 | file:line | 读什么 | 接地状态 |
|---|---|---|---|---|
| 1 | **energy/body_delta** (唤醒 + tempo) | `2001-2017`(休息中被扰醒) / `2184-2192`(间隔 floor) / `2326-2333`(指纹纳势能) / `2819-2841`(撤退避) | `BodyFocus.has_fresh_delta()` + `current_focus()` (= body_energy.json 产物) | ❌ **未设防 (件 A 主战场)** |
| 2 | **focus** (渲染进 prompt) | `_build_prompt:4749-4779` | `render_attention_block(limit=5)` → BODY SIGNALS 块 | ⚠️ 通道1 下游, 随件A净化 |
| 3 | **lens** (反应式投影) | daemon **不调**; 仅口侧 `central_nerve.py:3627-3631` | — | ✅ P1 已设防 + 真机关 |
| 4 | **notes** (concern notes) | `_collect_evidence` concern 段 (`list_active` + `notes_for_self`) | concern 文本 + daily_progress + last_user_feedback (vocab gate) | ✅ concern 本身接地 |

**通道 1 = 自发思考的势能源 = 件 A 接地化的对象。** 通道 2 (focus 渲染) 是它的纯下游 (读 body_energy.json), 件 A 接地化通道 1 即顺带净化通道 2。

### 1.4 识回写体 (识→体) — 强闭环写侧

| actionable | file:line | 写什么 | 接地 |
|---|---|---|---|
| **adjust_concern_notes** | `_do_adjust_concern_notes:6990` | (i) `observe_thought_concern_link:7066` → manifold **PROV_SHARED about 边** (ii) `notes_for_self` append | ✅ concern_id 机械 ref (双层 evidence_link gate `7050`) |
| propose_stance | `6584` | stance.json (关系立场) → review queue | ✅ |
| update_concern_severity | `6293` | concern severity | ✅ |
| suggest_inside_joke / propose_protocol | `6357` / `6723` | relational **review queue** → 衡 (AutoArbiter) 自决 | review (待仲裁) |

**洗白动力学的代码位置 (件 A 实测根)**: `_do_adjust_concern_notes:7066` 的 `observe_thought_concern_link` 写的接地边本身 OK (PROV_SHARED + concern_id ref), 但**落点**由势能驱动的 attend 决定 — 势能数假焊 → 识被带去假区 attend → 在假区产 C 类 thought → 接地边落假区邻域 (实测 8:0)。**件 A 切断的是"势能往假区带"这一步, 不是回写本身。**

### 1.5 thinking_brain + 质量门 (thought 产出后怎么被过滤)

```
raw (LLM) → _parse_thought:5716 (regex 抽 CATEGORY[A-E]/THOUGHT/SALIENCE; 缺→silent None)
 → A/B/C/D/E 分类 (585-589)
 → salience 门: _MEDIOCRE_SAL_THRESHOLD=0.5 (1576) — sal<0.5+无 actionable+cat∈ADE = mediocre (仅抑制字幕闪, thought 仍 persist)
 → speak rate cap: 5min 内 ≥3 yes → force silent (2674-2696)
 → heng_state 三态: _classify_heng_state:2864 → discharge(真解张力)/rest(空且已歇)/filler(空未歇)
 → actionable 执行: _execute_actionable:6029 (effect_to_kind 映射 472-476)
 → 习惯化反馈: publish body_attention_outcome (Weaver 消费 → 反复 attend 不放电的区 tension 渐衰)
```

**质量门 = salience (自评) + heng_state (放电效果, 非自评) 双轨。** value-backoff (`2783`) 用 heng_state 客观信号防自评虚高。

---

## 块2. 衡 (AutoArbiter) — 自决仲裁引擎

### 2.1 它守什么 (`auto_arbiter.py:AutoArbiterDaemon:100`)

衡 = "灵魂工程 Layer 2.5 自决引擎" (`auto_arbiter.py:9`)。**守 review queue 的仲裁**: 识 propose 的 inside_joke / thread / protocol / concern / directive → 衡自己拍板 activate / reject / defer_to_sir, Sir 元否决可一键 revert。

```
3 后台 thread (start):
  ├─ tick (TICK_INTERVAL_S=300, 5min):       拉 review queue → 逐项 _evaluate_and_decide
  ├─ daily_reflection (03:xx):                看 24h Sir revert 率 → 自动调阈值 (校准)
  └─ monitor (15min):                         bloat/dedup/revert 异常 → publish auto_arbiter_anomaly
```

### 2.2 它读哪些输入 (`_collect_evidence:1994`)

| 输入源 | 读什么 | file:line |
|---|---|---|
| **识/relational** | entity 自身 + active list (inside_jokes/threads/protocols, dedup 参考) | `1996-2046` |
| **口 (STM)** | `nerve.short_term_memory` 最近 N turn (vocab `stm_lookback_turns`) | `2048-2090` |
| **SWM** | AmbientSensor laughter event (inside_joke 强 ACT 信号) | `2092-2100+` |
| **不读** | ❌ 不直接读 manifold (体) ❌ 不直接读 concern notes ❌ 不读 anchors | grep 确认 |

**决策两层 (准则 6 耦合)**: Python deterministic strong-gate (强 ACT/强 REJ bypass LLM, 省 token) `_*_strong_gate:941/1081/1196/1300` → 无强信号才走 `_llm_evaluate:2144`。阈值 `DEFAULT_THRESHOLDS:131` + 风险档 `RISK_LOW/MEDIUM:146`。

### 2.3 它在管线坐哪 (上游/下游)

```
上游 (喂它): 识 _do_propose_protocol/_do_suggest_inside_joke + 各 reflector
              → relational.write_review_queue
                          │
                          ▼
              衡 tick (5min) → _evaluate_and_decide:1525
                          │
下游 (写):    ├─ memory_pool/auto_arbiter_log.jsonl (_persist_decision:2657)
              ├─ auto_arbiter_calibration.json (阈值校准)
              ├─ relational.activate_from_review/reject_from_review (真执行)
              └─ publish auto_arbiter_anomaly (SWM) → 识 evidence 反思 (双向回喂)
```

### 2.4 claim_classify / evidence_requirements — **不在衡, 是独立 INTEGRITY 栈**

顾问注意: claim 分类/反幻觉**不在 AutoArbiter**, 是独立子系统 (与衡平行, 都守"诚实"但管不同对象):

| 组件 | file | 守什么 |
|---|---|---|
| `jarvis_evidence_requirements.py` | vocab `evidence_requirements.json` | claim 需要什么证据级别 |
| `jarvis_integrity_reflector.py` | `claim_classify_vocab.json` (L7 propose) | claim 分类规则的 LLM-propose |
| `jarvis_claim_tracer.py` + `jarvis_integrity_wall.py` | `integrity_claim_vocab.json` | 主脑回复里的 specific factual claim → trace evidence (准则 5) |

**衡 (AutoArbiter) 管"识 propose 的关系产物该不该 activate"; INTEGRITY 栈管"口说出的 claim 有没有证据"。两者都是"衡"的广义体现, 但代码上分离。**

---

## 块3. 说 (口/主脑) — 下游渲染, 松耦合 (简要)

主脑 prompt 组装 `central_nerve.py:_assemble_prompt:3610`。读体/识/锚的注入点 (与本文相关者):
- **Layer 0 SelfAnchor**: `_build_layer_0_self_anchor_block:2454` → `SelfAnchor.build_block:3596/3641`
- **锚墙 + 冲突指引**: `4334-4340` (`render_walls_block` + `render_conflict_guidance`)
- **lens 投影** (体→说, P1 已设防): `3627-3631` (flag-gated, 真机关)
- **inner_thoughts pull** (识→说): Layer 1.5/1.6 从 `inner_thoughts.jsonl` 拉

说是下游消费者, 松耦合, 不回写体/识 (除 STM 累积)。

---

## 块4. 体 ↔ 识 ↔ 衡 ↔ 锚 耦合契约图 (命根子 — 共演化判断用)

### 4.1 接触面全图

```
                    ┌─────────────────────────────────────────────────┐
                    │                  锚 (anchors.json)                │
                    │   墙不可改 / SelfAnchor / decay-immune (宪法层)    │
                    └────┬──────────────────────┬─────────────────┬────┘
                 读墙+冲突│ (4390-4404)      读 build_block│(口)    ❌不读│
                         ▼                      ▼                  ▼
        ┌────────────────────┐  body_delta  ┌──────────┐      ┌─────────┐
        │   识 (InnerThought) │◀────────────│ 体(Manifold│      │衡(Arbiter│
        │                    │  energy(❌)   │ +Weaver)  │      │         │
        │  自发思考引擎       │─────────────▶│           │      │ 仲裁引擎 │
        │                    │ observe_link │           │      │         │
        └─────┬──────────────┘ (PROV_SHARED)└───────────┘      └────┬────┘
              │ write_review_queue                                  │
              │ (propose_protocol/joke)                             │
              └───────────────────────────────────────────────────▶│
              ◀────────────── auto_arbiter_anomaly (SWM) ───────────┘
                            activate → relational active
```

### 4.2 耦合强度表 (紧耦合 vs 可解耦)

| 接触 | 介质 | 方向 | 耦合度 | 件 A 影响 |
|---|---|---|---|---|
| 体→识 (energy/delta) | body_energy.json + body_delta event | 体→识 | **紧** (势能直驱唤醒+tempo+attend) | ★ 件 A 接地化此通道 |
| 识→体 (回写) | `observe_thought_concern_link` PROV_SHARED 边 | 识→体 | **紧** (强闭环, 洗白发生处) | 件 A 不改回写, 改"势能往哪带" |
| 识→衡 | relational review queue | 识→衡 | 中 (异步队列, 可解耦) | 无 |
| 衡→识 | auto_arbiter_anomaly SWM event | 衡→识 | 松 (事件回喂, 已解耦) | 无 |
| 锚→识 | render_walls_block / conflict_guidance | 锚→识 | 中 (prompt 注入, 单向只读) | 无 |
| 锚→说 | SelfAnchor.build_block + 墙块 | 锚→说 | 中 (prompt 注入, 单向只读) | 无 |
| 锚↔衡 | **无直接接触** | — | 解耦 | — |
| 体↔锚 | **无直接接触** (锚不是 manifold 节点) | — | 解耦 (但见盲点 #4) | — |

### 4.3 自我涌现的关键接触面 (锚的交集处)

Sir 原话"自我在锚的交集处涌现"。代码层的对应:
- **多锚交集** (`self_anchor.py:build_block` 注释): "Who I am is the SHAPE where these walls intersect" — 第一锚 (诚实/言出必行) + 第二锚 (for-Sir), 单锚会退化成反刍。
- **锚→识接触面** (`daemon.py:4390-4404`): 识 prompt 注入"撞墙张力 = 真值得想的 discharge" — **锚的冲突 (诚实 vs 善意) 是自发思考的高价值 discharge 源**。这是自我涌现在"识"侧的代码落点。
- **关键观察 (给顾问综判)**: 锚与识的接触是**单向只读注入** (识读锚墙, 但识不回写锚, 锚 decay-immune)。自我涌现目前是"识在锚约束下自由活动"的形状, **锚本身不随识/体演化** (墙不可改 by design)。这是稳定性 (锚不漂) 与可塑性 (自我能否成长) 的张力 — 共演化设计的核心问题。

### 4.4 盲点 / open-question (给顾问综判共演化路线)

| # | 盲点 | 状态 |
|---|---|---|
| #4 (件 A 继承) | 锚本体 decay-immune, 但锚主题的 concern/stance **镜像节点**随 manifold 边 14d 衰减 | open-q, P3 候选。锚↔体无直接接触, 但锚主题在体里的"投影残影"会衰减 |
| 新 #5 | 锚→识/说是**单向只读**, 锚不随演化更新。自我涌现 = 锚约束下的自由活动, 锚本身不长 | 共演化设计的核心张力, 待顾问定方向 |
| 新 #6 | 衡 (AutoArbiter) 不读锚, 仲裁 review queue 时无锚约束。识 propose 的产物经衡 activate 时, 锚不参与 | 待综判: 衡是否该看锚 |

---

## 块5. 给顾问的综判锚点 (件 B 目的)

件 A (势能层接地化) = **止血**, 切断体→识唯一未设防通道 (块4.2 ★)。止血后, 共演化建造的开放问题 (块4.4) 浮现:
1. **识怎么想**: 自发思考由接地势能驱动 (件 A 后), 模式会怎么变? 洗白是否截断? (件 A Tier2 weave_once + 周期只读实测监控)
2. **衡怎么仲裁**: 衡当前不读体/不读锚, 纯看 review queue + STM。是否该接体势能 / 锚约束?
3. **体结构怎么长**: 接地骨架极薄 (shared 仅 8 条), 真分化结晶不出来 (P0 终态"接受薄体")。接地化后接地边怎么健康生长?
4. **锚怎么参与演化**: 锚单向只读 + decay-immune (块4.3/#5)。自我涌现需要锚稳定, 但成长需要可塑 — 这个张力怎么解?

---

*本文件件 B 交付, 只读勘察 (未改代码/未碰 flag)。供顾问综判共演化路线。与 `JARVIS_BODY_ARCHITECTURE_MAP.md` 配套 = 体+识+衡+锚 全景。件 A (势能层接地化设计) 见 `JARVIS_ENERGY_GROUNDING_DESIGN_P2.md`, 待顾问审。*
