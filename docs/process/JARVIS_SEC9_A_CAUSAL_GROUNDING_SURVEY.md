# §9 A 河床 + 修-因果接地 合并勘察 — 现状图 (只读 / 零代码 / 零真机)

> **[sec9-a-causal-grounding-survey / 2026-06-07]**
> Sir 拍定启动 §9 治假焊主轨。本文**只摸现状**, 四点 file:line + 证据 + 每点一句判定。
> **不提方案、不写代码、不碰真机/flag/墙/宪法散文/facets 生产逻辑。**
> 背景: 失真② 已确认"体不薄但分裂未接地" — 母亲手术/住院/早上没去散在
> `inner_voice_24h.jsonl`, 没接地进 manifold、没关联 promise `p_434796c0`。

---

## 点 1 — manifold / 接地现状 (什么创建 node/edge)

### 1.1 唯一造边核心 = `add_edge` (接地红线: ref 必填)

`jarvis_relational_manifold.py`:

| 入口 | file:line | provenance kind | ref(接地来源) |
|---|---|---|---|
| **核心 mutate** `add_edge` | `:381` | 任意 PROV_* | ref 必填, 无 ref → 拒 (返 None, `:397` 红线) |
| `observe_cooccurrence` | `:480` | PROV_COOCCUR (弱 0.30) | turn_id |
| `observe_explicit_link` | `:496` | **PROV_SAID (强 1.00)** | turn_id |
| `observe_shared_entity` | `:502` | **PROV_SHARED (0.50)** | entity_id |
| `observe_inferred_link` | `:520` | PROV_INFERRED (LLM, review) | turn_id |
| (embed) | `:539` | PROV_EMBED | 'cosine' |
| `_append_provenance` (dedup 键=(kind,ref)) | `:454` | — | 同(kind,ref)刷新不堆 |

provenance 5 类 (`:49-53`): COOCCUR / SAID / SHARED / EMBED / INFERRED。
**接地边** = 仅 PROV_SAID + PROV_SHARED (`node_grounded_provenance:582` 白名单, EMBED/COOCCUR/INFERRED 一律排除)。

### 1.2 谁在真调这些 observer (生产接线)

| caller | file:line | 调的 observer | 写什么边 |
|---|---|---|---|
| Weaver `observe_turn_cooccurrence` | `jarvis_relational_weaver.py:148` | `observe_cooccurrence` | **只 COOCCUR (弱, 非接地)** |
| Weaver `observe_thought_concern_link` | `jarvis_relational_weaver.py:~160` | `observe_shared_entity` | PROV_SHARED (thread→concern, ref=concern_id) |

⟹ **判定: 接地边 (SAID/SHARED) 生产来源极窄**。口写体主路径 (Weaver `observe_turn_cooccurrence`) **只写 COOCCUR 弱边 (非接地)**; 唯一真接地 (SHARED) 来源是"思考脑产带 concern_id 的 thought"那一刻 (`observe_thought_concern_link`)。**PROV_SAID (Sir 一句话显式连) 在生产码无任何 caller** — 仅测试调 (`observe_explicit_link` grep 生产 0 命中, 全在 tests/)。

---

## 点 2 — facet 结晶触发条件 (P0 那套现状)

`jarvis_identity_facets.py`:

| 条件 | file:line | 实际值 |
|---|---|---|
| 资格闸 `qualifies` (全 AND 布尔) | `:129` | ① 真出处 ② 复现 ③ 正交墙 |
| ① 真出处 | `:147` | grounded_provenance 至少 1 条 src ∈ {manifold_said, manifold_shared} |
| ② 复现计数 | `:148` | `recurrence_count >= RECURRENCE_MIN_N` |
| `RECURRENCE_MIN_N` | `:62` | **= 3** (离散硬常量, 非阈值分数) |
| ③ 与墙正交 | `:141` | orthogonal_to_walls=True (不复述/改写 4 墙) |
| 复现计数语义 | `_distinct_event_count:306` | = **不同 ref 个数** (不同 turn / 不同 entity), 非 sum(count) |
| producer | `scan_and_crystallize:568` | flag-gated 默认 off; 枚举 `iter_grounded_nodes`, 够格全结晶, 无 score/sort/argmax |
| 便捷入口 | `crystallize_from_node:321` | resolve 后 node_id = identity_key; recurrence 缺省 = `_distinct_event_count` |

⟹ **判定: 结晶门槛 = 离散 AND (真接地边≥1 ∧ 不同ref≥3 ∧ 正交墙), 纯布尔/计数, 零相似度**。要结晶必须先有 **≥3 个不同 turn/entity 的 SAID/SHARED 接地边** 落在同一 node。母亲那串因果从未写成接地边 (见点4), 故连"候选 node"都不成, 更无从结晶。

---

## 点 3 — promise ↔ manifold 关联现状

- `jarvis_promise_log.py` grep `manifold|node_id|node|edge|relational` → **0 命中**。
- `Promise` dataclass 字段 (`:166-205`): id / description / kind / deadline_str / jarvis_reply / turn_id / lang / state / registered_at / fulfilled_at / evidence[] / author / who_promised / trigger_pattern / bound_to_concern_id。**无任何 manifold node_id / edge_key 引用字段**。
- 反向: manifold (`jarvis_relational_manifold.py`) 无 promise_id 字段。
- 唯一弱联系: `Promise.bound_to_concern_id` (`:~204`) — 可绑 concern_id; 而 manifold SHARED 边 ref 也用 concern_id (`observe_shared_entity`)。但两者**无代码层关联逻辑** (没有"promise → 找同 concern_id 的 manifold 边"的桥), 只是恰好都能引 concern_id。

⟹ **判定: promise 与 manifold 是完全两套独立存储**, 零字段/边/node_id 互引。`p_434796c0` ("下午去医院看望母亲") 是孤立 promise, 与 manifold 任何 node 无结构关联。仅 `bound_to_concern_id` 提供"理论上可经 concern_id 间接搭桥"的潜在锚点, 但当前无桥代码。

---

## 点 4 — 因果背景为何分裂 (有无现成接地路径)

### 4.1 对话因果事实的去向 = 只进 inner_voice 时间线 + STM, 不接地 manifold

母亲因果实物 (复用上轮勘察):
- `inner_voice_24h.jsonl:3099/3299/3678` (sir_excerpt: 妈妈做手术/手术成功/我前两天讲过) — append-only 时间线
- promise `p_434796c0` (光秃描述, 无背景)

接地进 manifold 的**唯二**生产路径 (点1.2):
1. `observe_turn_cooccurrence` (Weaver) — 但只 COOCCUR 弱边, **且** 要求 turn 内 lexical 命中 **≥2 个已知体节点** (`:147` `min_match_nodes=2`); "妈妈要做手术" 这种新事实没有对应已建 node, 命中 0~1 → **直接 return 0 不写** (`:148`)。
2. `observe_thought_concern_link` — 仅当思考脑产出带 concern_id 的 C 类 thought 那一刻才写 SHARED 边; 母亲事件没被挂成 concern, 故无此触发。

⟹ **判定: 缺口在"对话新因果事实 → manifold 接地"无路径**。现状:
- 口写体主路径 (cooccur) 要求"已存在 ≥2 个匹配 node"才写边, **新引入的事实** (首次提母亲手术) 必然命中不足 → 不写 → 永远进不了体。
- 唯一接地 (SHARED) 靠"思考脑挂 concern_id", 母亲事件未成 concern → 没接上。
- PROV_SAID (Sir 显式连两实体, 强接地) 生产无 caller → "妈妈→手术"这种 Sir 明说的因果**根本没有机制写成 said 边**。
- 故母亲因果只能停在 inner_voice 时间线 + STM 截断摘要, 既不结晶 facet (点2 门槛进不去), 也不被 InnerThought 结构化读到 (上轮已修 promise 读, 但 manifold 因果仍读不到)。

---

## 点 5 (§9 A) — 离散硬证现状 + facet 撤销路径

### 5.1 三类信号的离散键可得性

| 信号 | 产生处 file:line | 载荷字段 | 带离散键? |
|---|---|---|---|
| **Sir 纠正** `memory_correction_apply` | `jarvis_tool_registry.py:125` | old_value / new_value / field_hint / raw_text / confidence | **❌ 全 NL** (field_hint 如 'hydration_count' 是 profile 字段名, **非** manifold node_id / facet_id) |
| Sir 纠正 (worker LLM 判) | `jarvis_worker.py:2306` | has_correction / old_value / new_value / search_hint | **❌ 全 NL** (search_hint = 中文关键词) |
| Sir 纠正 SWM candidate | `jarvis_utils.py:1419` `sir_intent_correction_candidate` | — | publish-only, NL |
| **ClaimTracer/Unverified** | `jarvis_claim_tracer.py:trace_reply:695` + `write_audit_entry:860` | turn_id / claim(text) / kind / evidence_kind / found / reason | **❌ 无离散键** (claim = NL 文本片段, kind='time/percent/count/quote'; turn_id 是轮级非节点级) |
| **breach (机械墙)** | `jarvis_integrity_wall.breach_stats()` (经 `jarvis_vitals_board.py:86`) | total_breaches / session_breaches / by_kind / last_breach_iso | **❌ 计数+kind 聚合**, 无 node/facet 离散键 |

### 5.2 facet 撤销/回塑路径现状

| 函数 | file:line | 现状 |
|---|---|---|
| `revoke_facet` | `jarvis_identity_facets.py:352` | [Step 2 接口位] 真实撤销 (按 facet_id 标 STATUS_REVOKED) — **已实做** |
| `reverify_facet` | `:386` | 离散重核: 接地边没了 → 调 revoke_facet(reason='grounding_edge_gone') — 已实做 |
| `reverify_all_facets` | `:435` | 周期重核全部 active — 已实做 (Weaver % R 接线调) |
| `on_sir_correction(identity_key)` | `:413` | 收**离散 identity_key** → `_find_facets_by_identity_key` → revoke。**已实做但无生产调用者** (`_test_sec9_c:28` 静态守护证实) |
| `record_wound_for_facet` | `:446` | **空 stub** ([河床接口位 — 冻结 §6, 本阶段不实做]) |

⟹ **判定: facet "撤"侧机制已齐 (revoke/reverify 实做), 但硬证→撤的"输入键"断裂**。`on_sir_correction` 要的是离散 identity_key (= manifold resolve 后 node_id), 而三类硬证信号 (纠正/ClaimTracer/breach) **载荷全是 NL + 轮级 turn_id, 无一个带 manifold node_id / facet_id**。`reverify` 走的是"接地边消失"(结构自检, 不需外部键, 已能跑); `on_sir_correction` 走"Sir 显式否认"(需离散键, 但无人喂键也无生产 caller)。`record_wound_for_facet` 仍是空 stub。

---

## 点 6 (接口) — 接地加关系 vs 硬证撤 facet 是否同一突变层

### 6.1 manifold 写入/变更 API (单层, 集中)

`jarvis_relational_manifold.py` 全部 mutate 入口:
- `add_edge` (`:381`) — 唯一造/强化边核心, 所有 observe_* 都走它
- `_append_provenance` (`:454`) — add_edge 内部调
- `prune` (`:561`) — 删衰减低于 floor 的边
- `add_alias` (`:875`) — 近重复 node 指向代表 (不删源)
- (无 add_node 独立函数 — node 随 edge/alias 隐式产生; 无 remove_node/delete_edge 显式单删)

### 6.2 facet 写入/变更 API (另一层, 独立文件)

`jarvis_identity_facets.py`: `crystallize` / `crystallize_from_node` / `revoke_facet` / `reverify_facet` — 操作 `memory_pool/identity_facets*.json` store, **与 manifold store 分离**。

⟹ **判定: "接地加关系"(manifold add_edge 层) 与 "硬证撤 facet"(facets revoke 层) 是两个独立突变层, 不同文件不同 store**。
- manifold 写入集中在 `add_edge` 单核 (好: 加因果边只需走 observe_* → add_edge)。
- facet 撤销集中在 `revoke_facet` 单核 (好: 撤只需走它)。
- 二者**无统一上层**: 加关系动 manifold store, 撤 facet 动 facets store; facet 经 identity_key (=node_id) 单向引 manifold (gather_grounded_provenance 只读), 但 manifold 不知 facet 存在。"硬证→撤"要跨两层: 先把 NL 硬证映射到离散 node_id (= 当前断裂点, 点5.1), 再 node_id→facet (on_sir_correction 已能做)。

---

## 现状图小结 (六点)

| 点 | 判定 | 核心 file:line |
|---|---|---|
| 1 接地现状 | 唯一造边核 `add_edge` (ref 必填); 接地边=SAID/SHARED; 生产只 Weaver 写 COOCCUR弱边 + 思考脑 concern SHARED, **PROV_SAID 生产无 caller** | `manifold:381/480/496/502` |
| 2 结晶门槛 | 离散 AND: 真接地边≥1 ∧ 不同ref≥3 ∧ 正交墙; 零相似度 | `facets:129/62/568` |
| 3 promise↔manifold | **完全独立两套存储**, 零互引; 仅 bound_to_concern_id 是潜在 concern_id 搭桥锚点(无桥码) | `promise_log:166` (manifold 0命中) |
| 4 因果为何分裂 | **新对话因果事实→manifold 无接地路径**: cooccur 要≥2已知node(新事实命中不足), SHARED靠concern挂(母亲没成concern), SAID生产无caller | `weaver:148`; `manifold:496` |
| 5 §9 硬证 | 撤侧 revoke/reverify 已实做; 但纠正/ClaimTracer/breach **载荷全NL+turn_id无离散node/facet键**; on_sir_correction(需离散键)无生产caller; record_wound 空stub | `tool_registry:125`; `claim_tracer:860`; `facets:352/413/446` |
| 6 接口 | 接地加边(manifold add_edge层) 与 撤facet(facets revoke层) **两独立突变层不同store**; 无统一上层; 跨层桥=NL硬证→node_id 映射(=断裂点) | `manifold:381`; `facets:352` |

→ 一句话: 母亲因果没机制写进体(SAID没人调/cooccur要旧node), 硬证想撤 facet 又缺"话→node_id"的离散键桥; 撤的机器有了, 喂键的管子没接。
