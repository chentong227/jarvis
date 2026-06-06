# 体 (Body / RelationalManifold) 架构完整方案 — 给 Sir 消化

> **[body-arch-map / 2026-06-06]**
> 用途: P1 收口后, 让 Sir 完整理解"体"的架构 (数据结构 / 势能 / 全链数据流 / 体↔识闭环), 为下一步"自发思考=体势能地形上的水流"那条主线打底。
> 方法: 真读代码, 标 file:line, 不凭印象。覆盖 Sir 点的 4 块。
> 真理源代码: `jarvis_relational_manifold.py` (边层) / `jarvis_relational_weaver.py` (维护+势能) / `jarvis_body_focus.py` (焦点) / `jarvis_relational_lens.py` (投影) / `jarvis_inner_thought_daemon.py` (识).

---

## 块1. 数据结构

### 1.1 节点 (Node) — 体不重存, 只引用 (`manifold.py:54-78`)
节点 id = `kind:raw_id`, 指回各真理源 store。kind 全集 (`KIND_*`):

| kind | 前缀 | 真理源 store | 自产? |
|---|---|---|---|
| thread | `thread:` | self_threads.json (思考脑 inner-thought 线程) | ✅ 自产 |
| joke | `joke:` | relational_state.json inside_jokes | ✅ 自产 |
| proto | `proto:` | relational_state.json unspoken_protocols | ✅ 自产 |
| concern | `concern:` | concerns.json (Sir 真实生活关注) | ❌ 外部实证 |
| stance | `stance:` | stance.json (Jarvis 接地的关系判断) | 半自产 |
| mem / entity / topic | `mem:`/`entity:`/`topic:` | hippocampus / 实体 / 话题 | (定义存在, harvest 未全接) |

`self_produced_kinds = ["thread","joke","proto"]` (接地不对称的"自产"定义)。

### 1.2 边 (Edge) — provenance tag 全集 (`manifold.py:48-54`)
每边带 provenance (怎么造的 + trace ref, 无 ref 拒写 = 接地红线):

| PROV | 值 | 含义 | 接地? | grounded_only 放行? |
|---|---|---|---|---|
| `PROV_SAID` | said | Sir 一句话显式连 | ✅ 强接地 | ✅ |
| `PROV_SHARED` | shared | 共享实体/concern (about 边) | ✅ 接地 | ✅ |
| `PROV_COOCCUR` | cooccur | 同 turn 共现 | ⚠️ grounded-type 但**偶发可假** (hand_pain↔interview rc=10=玩 AoE4) | ❌ **排** |
| `PROV_EMBED` | embed | embedding cosine 相似 | ❌ 思考相似非真关联 | ❌ 排 |
| `PROV_INFERRED` | inferred | LLM 推断 (propose-not-trust, 标 review) | ❌ | ❌ 排 |

### 1.3 relational_manifold.json schema (`manifold.py:save()`)
```
{"_meta": {...}, "edges": {"<a>␟<b>": {a,b,weight,reinforce_count,
  created_ts,last_reinforced_ts,provenance:[{kind,ref,ts,count,detail?,confidence?}],
  review}}, "surfaces": [...], "aliases": {dup→rep}}
```
- weight: Hebbian 累加 (事件边) / set-to-floor (embed 属性边) / set-to-target (P0a 折扣边); 14d 半衰; <0.05 prune。
- aliases: 近重复节点折叠 (merge_threshold 0.90), `resolve()` 跟链到代表。

### 1.4 当前实测形态 (真数据)
- ~116 节点 / ~2165 边, density ~16-18 (over_dense)。
- 边构成: embed ~1867 / cooccur ~428 / **shared 仅 8** (about 接地骨架极薄)。
- compute_surfaces 实际产出: **1 个大面 (largest_frac ~0.23-0.29) + ~89 孤儿**; 桥 0。"4-10 面"已证伪 (§15)。
- ⟹ 体目前是"薄接地骨架 + embed mesh 霸占", 真分化结晶不出来 (接受薄体, P0 终态)。

---

## 块2. 势能到底存不存在? — **存在, 是真度量, 不只文档概念**

### 2.1 它是什么 (`weaver.py:754 compute_energy`)
势能 E 是**每节点一个标量** (+3 分量), 真算真存:
```
E[node] = w_nov·novelty + w_drift·drift + w_tension·tension
          (w_nov=1.0, w_drift=0.6, w_tension=1.2)
```
- **novelty**: 本轮新边权重计给两端 (新关联升起)
- **drift**: 非新边里权重变动 ≥0.05 的 (关系在变)
- **tension** (3 源相加):
  1. 高 severity concern 且无 active stance 覆盖 (× 习惯化因子 — 反复 attend 不放电则衰)
  2. 近期 nudge/care 警报映射到 concern (感知环穿体)
  3. 立场 dyad (高置信 stance 的阻力势能)

### 2.2 存哪 / 谁写 / 谁读 / 驱动什么 (全链)
```
Weaver.weave_once (后台 600s)
  → compute_energy → 写 memory_pool/body_energy.json
  → _diff_and_emit_deltas: 节点 E 上升超 delta_threshold(0.30) → 派 body_delta
        │
   ┌────┴─────────────────────────────────────┐
   ▼ (读 body_energy.json)                      ▼ (读 body_delta)
BodyFocus.current_focus()/focus_seeds()    InnerThoughtDaemon
  = "体此刻哪里有势能" 单一焦点源              (见块4: 势能驱动自发思考的醒/睡)
   │
   ├─→ Lens.default_seeds() (投影 seed)
   └─→ daemon BODY SIGNALS 渲染 + 指纹
```
**结论**: 势能是地基级真实存在的运行态 (body_energy.json), 不是概念。它**直接驱动**: (a) lens 投影选 seed; (b) **自发思考的醒不醒 + 想哪块** (块4)。这正是 Sir "自发思考=体势能地形上的水流"的代码对应物。

---

## 块3. 全链数据流 + 进主脑的所有投影通道

### 3.1 lens 投影链 (反应式, 进主脑 prompt)
```
_assemble_prompt (central_nerve.py:3610)
  → build_lens_block (lens.py) [gate: lens_inject_enabled, 真机=0 关]
      [耦合护栏: inject=1 但 grounded_only=0 → return "" (ac4483b)]
  → RelationalLens.project (lens.py:165)
      → manifold.spread (manifold.py:575) [grounded_only flag 控走哪些边]
      → 取激活 top-N 节点文本 → RELATIONAL CONTEXT block
  → [lens_replaces_layer3=1: lens_block 非空才顶 Layer3]
```

### 3.2 进主脑/决策的所有体消费通道 (规范"不只 lens"核查)
| 通道 | 路径 | 走 spread? | 进主脑 prompt? | grounded 状态 |
|---|---|---|---|---|
| **lens 投影** | `_assemble_prompt`→build_lens_block→project→spread | ✅ | ✅ | 已加 grounded_only + 耦合护栏; 真机关 |
| **body_claim_evidence** | chat_bypass→ClaimTracer body_evidence_provider | ❌ (词重叠 `_node_text_map`) | ❌ (post-stream claim 验证, 不注入) | 低阶旁路, 不走 spread (TODO: 词重叠可能匹到假焊节点文本误判 verified — 已记, 非 prompt 注入) |
| **思考脑 BODY SIGNALS** | daemon `_build_prompt` | ❌ (读 body_focus energy, 非 spread) | 思考脑 prompt (非主脑对话) | 读势能/焦点, 不走边遍历 (见块4) |
| CLI / dashboard / vitals | manifold_dump / homepage / 仪表 | spread/surfaces | ❌ (display) | 诊断/展示 |

**核查结论**: 进主脑 prompt 的 spread 注入线**唯一 = lens**, 已上 grounded_only + 耦合护栏。无第二条未设防的活线。body_claim_evidence 是低阶旁路 (不走 spread/不注入 prompt), 思考脑读势能不走边遍历。

---

## 块4. 体↔识 闭环 — **有闭环, 且有一条回写体边的路径 (重点查清)**

### 4.1 识**读**体 (体→识)
InnerThoughtDaemon 自发思考确实读体, 两处:
1. **势能驱动醒/睡** (`daemon:2323` evidence-gate 指纹 + `:2187` rest floor + `:2001` rest 唤醒): 体有 fresh delta (够幅度) → 指纹变 → daemon 醒去想那块; 体 settled → idle/rest。**这就是"势能地形上的水流"**: 体不安定→识转, 体平息→识静。
2. **BODY SIGNALS 渲染进思考 prompt** (`daemon._build_prompt`, 读 body_focus.current_focus)。

### 4.2 识**回写**体 (识→体) — ⚠️ 有一条写边路径
`daemon._do_adjust_concern_notes` (`daemon:7067`): 思考脑产出带 concern_id 的 C 类 thought 时, **当场调 `observe_thought_concern_link(thread_id, concern_id)`** → 在体里写一条 **thread→concern 的 PROV_SHARED about 边** (manifold)。这是识→体的**回写闭环**。

### 4.3 这条回写会不会把假焊固化进体? — **未测, 两条待实测 open-question (不给安全定性)**

⚠️ **本节结论未经实测, 不下"安全/不固化"定论 (规范: 没 B/数据证据不许称验过)。** 已知事实 + 两条 open-question:

**已知事实 — 回写的边本身是接地的, 不是假焊**:
- `observe_thought_concern_link` 写 `PROV_SHARED` 边, ref = concern_id (机械, 非 cosine), 触发需 actionable 显式带 concern_id + evidence_link 双层 gate 过。⟹ 这条边是"念头 X 关于 concern Y"的真 provenance, 是 P0c #1 要补的接地骨架, 单看它**不是假焊**。

**但闭环有两条放大/洗白动力学, 均【待实测】, 不可据"边本身接地"就判全局安全**:

- **Open-Q1 (势能层放大 — 没设防的核心通道)**: 假焊边 (embed/cooccur) **全量参与 `compute_energy` 的 novelty/drift** (块2; novelty/drift 不分接地, 所有边都算)。⟹ 假焊边权变动 → drift 势能 → body_delta → **唤醒识去 attend 那个被假焊连起来的区** + BODY SIGNALS 进思考脑 prompt。**这条通道完全没走 spread、完全没被 grounded_only 设防、现在仍在全量吃假焊。** 块3"进主脑唯一 spread 线=lens"只在**反应式 spread 注入**口径成立; 这条**自发式势能通道**是另一条 body→brain 路径, 一直敞着。**这是比 lens 更核心的主战场 (势能层接地化), P1 范围未覆盖。**

- **Open-Q2 (接地边洗白假焊区 — 比 Q1 更隐蔽)**: 闭环可能让假焊"洗白":
  1. 假焊势能 (Q1) 误导识去 attend 假关联区;
  2. 识在假区产 C 类 thought → 写一条真接地 thread→concern 边 (本身接地, "好事");
  3. **但这条真接地边落在假焊区邻域** → 假区有了真 provenance 的接地脚手架;
  4. 重复 → 假焊区被越来越多真接地边包裹, 越来越"合法", 越来越难与真分化区区分。
  - = **洗钱**: 假焊招募真接地边沉积到自己周围, 把自己镶金边。假焊不是被写回, 是它**招募真接地边给自己洗白**。**时间站在假焊那边。**
  - ⟹ "接受薄体 + 慢慢长接地边" (P0 终态) 若势能层不先接地化, **可能反在喂这个洗白过程**。

**6 天假焊事件影响重估**: lens 投影(读)是已证污染路径 (95.6%); 但 Q1/Q2 这两条 (假焊势能带偏自发思考 / 接地边洗白假区) **是否真在发生, 尚无证据, 待块5 只读实测**。这比"投一次 prompt"深 — 它问"假焊有没有渗进自发思考的势能地形"。

### 4.4 闭环全图
```
        ┌─────────────────────────────────────────────┐
        │                  体 (Manifold)                │
        │  edges (含假焊 embed/cooccur + 真接地 shared)  │
        └───┬───────────────────────────────▲──────────┘
   compute_energy│ (假焊边也算 novelty/drift)  │ observe_thought_concern_link
   body_energy.json│                          │ (写 PROV_SHARED about 边, 接地)
            ▼                                  │
      BodyFocus (current_focus/delta)          │
            │ 势能驱动醒/睡 + BODY SIGNALS      │
            ▼                                  │
      InnerThoughtDaemon (自发思考) ───C类thought──┘
            │ adjust_concern_notes → concern.notes_for_self
            ▼
      主脑 prompt (notes 进 Layer / lens 投影[真机关])
```

---

## 5. 下一步: 只读实测 (红先于绿, 不设计修法)

势能层接地化是否要做, **取决于实测**, 不先推测设计。两件只读实测 (body_energy.json + inner_thoughts.jsonl, 零 token 零风险):

- **实测1 (Open-Q1 势能带偏)**: body_energy.json 历史里长期高 E (top novelty/drift) 的节点, 是不是 hand_pain↔interview 这类假焊区? inner_thoughts.jsonl 自发 thought 是不是长期围假焊连起来的节点打转?
- **实测2 (Open-Q2 洗白实锤)**: 统计识回写的 thread→concern 接地边, 多少落在假焊区邻域 vs 真分化区。假区邻域持续沉积接地边 = 洗白实锤 (非推测)。

三种可能 → 决定优先级:
- (a) 假焊势能基本没带偏识 → 影响仅限 lens 那次读 → 势能层可暂不动;
- (b) 带偏但没洗白 → 中度, 记账;
- (c) 洗白实锤 → 势能层接地化升为下一个 P 主线, 优先级高于任何重开 lens。

**修法约束 (若需修, 红线 A)**: 势能层接地化**不能拿 argmax/utility 标量糊** (红线 A: C 层不加标量最优; 势能在 A 层但接地化判据须是 provenance 机械判, 非打分)。具体待实测出 (c) 再设计。

*本文件由 body-diff-P1 收口后 agent 创建, 供 Sir 消化体架构。基于真读代码 (file:line 标注)。块4.3/块5 为待实测 open-question, 未给安全定性。*
