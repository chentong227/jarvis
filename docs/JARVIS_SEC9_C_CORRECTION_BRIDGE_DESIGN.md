# §9-C 设计草案 — Sir 纠正撤销键(话→离散键桥)

> **[sec9-C-correction-bridge / 2026-06-07]**
> 依据: 现状图 `5bae992`(JARVIS_SEC9_FALSEWELD_SURVEY.md)审过。
> 核心 = 一座"Sir 这句纠正 → 哪条 facet 的 identity_key"的桥, **死守: 禁相似度**。
> **本轮只出设计草案, 零代码、零真机、不碰 flag/墙/宪法散文/energy_grounded_only。**
> **状态: 草案待顾问审 → Sir 拍 → 才施工。**

---

## ① 凭实物确认: IntentResolver 纠正轮**没有** resolve 出 manifold node_id

现状图 C.3 假设"IntentResolver 可能 resolve 出 node_id 但没传下来"。**深探后证伪 —— 那个 node_id 根本不存在:**

| 实证 | file:line | 结论 |
|---|---|---|
| IntentRouter `resolve_intent` | `jarvis_intent_router.py:265` | 是 **intent-map 查表**(intent_id → tool 名),**不碰 manifold** |
| intent_router 全文 grep `manifold/node_id/relational` | `jarvis_intent_router.py` | **0 命中**(除 `resolve_intent` 自己)→ 纠正路由全程不接触 manifold |
| `tool_memory_correction_apply` 入参 | `jarvis_tool_registry.py:125-160` | `old_value/new_value/field_hint/raw_text` 全 NL,无 node_id |
| worker 纠正落点 | `jarvis_worker.py:3081-3097` | `field_path='preferences.user_correction'` + NL old/new_val + turn_id,无 node_id |
| SWM `sir_intent_correction_candidate` metadata | `jarvis_worker.py:3057-3069` | `judgement:{old_value, new_value}` 全 NL,无 node_id |

**manifold node_id 只在 Weaver 路径产生**(`weaver.py:148` observe_cooccurrence / `:187` observe_shared_entity,识产 thread/concern 时),与纠正 turn 路径**完全不相交**。

⟹ **"穿用 IntentResolver 已 resolve 的 node_id"方案不可行 —— 该 node_id 不存在。** 不强造、更不用相似度去猜(头号红线)。设计必须围绕"纠正路径本就无 manifold 离散键"这个事实展开。

## ② 离散边界(防误撤)— 默认: 纯 profile 纠正不碰 facet

既然纠正路径无 manifold node_id,且 facet 的 `identity_key` = manifold node_id(`kind:raw_id`,P0 既定),**纠正与 facet 之间没有现成的共享离散键**。诚实的离散设计:

**判定规则(纯离散布尔,无相似度):**
- 一条纠正**能否撤 facet** = "该纠正是否携带一个能**精确等于**某 facet `identity_key` 的离散键"。
- 当前所有纠正路径 → **携带的离散键 = 无**(只有 NL + profile field_path)→ **默认: 纯 profile 纠正不碰任何 facet**。
- 这是离散判定(有精确匹配键 / 无),**不是模糊猜**:无键 → 不撤,绝不用 old_value/new_value 文本去相似度匹配 facet content。

**结论:在不引入新离散键来源前,C 的安全默认是"纠正只处理 profile/记忆库(既有逻辑),不动 facet"。** 这本身就是一个合规的、零误撤的终态 —— 直到下面 ③ 的离散键来源被建立。

## ②b 唯一离散安全的"建桥"方向(供顾问定,本轮不施工)

要让纠正能精确命中 facet,必须让**纠正事件携带一个与 facet identity_key 同命名空间的离散键**。唯一不靠相似度的途径:

> **在纠正发生的同一 turn,若该 turn 也经 Weaver/识路径产生了 manifold 接地边(observe_explicit_link/shared_entity),那条边的 node_id 是离散已知的。** 把"本 turn 的 turn_id"作离散关联键:纠正事件带 `turn_id`(已有,`worker.py:3087`),facet 的 provenance 里 ref=turn_id(PROV_SAID,`manifold:500`)。

- **离散关联**:纠正.turn_id == facet.provenance[].ref(turn_id)→ 精确字符串相等,**零相似度**。
- 即"Sir 在 turn T 纠正了某事 + facet F 的某条接地 provenance 也来自 turn T" → F 与该 turn 的纠正离散相关 → 可撤。
- **但需谨慎**(留设计阶段权衡):同 turn 可能有多条无关 facet provenance 共享 turn_id → 可能误撤。是否够"精确"需顾问判;若 turn_id 粒度太粗 → 退回 ② 默认(不碰 facet),**绝不降级到相似度**。

**本草案立场**:②(纯 profile 不碰 facet)是**零风险安全默认,先落**;②b(turn_id 离散关联)是**可选增强,需顾问评估 turn_id 粒度误撤风险后再定**。两者都不碰相似度。

## ③ 选定挂点 + 理由

**推荐挂点 = `tool_memory_correction_apply` 末尾(`jarvis_tool_registry.py:160`,_ok 返回前)。**

| 候选 | 选否 | 理由 |
|---|---|---|
| `tool_memory_correction_apply:160` | ✅ 选 | 纠正的**单一显式入口**(IntentResolver 判定后唯一落点);turn_id 可经 TraceContext 取;改动集中一处 |
| worker 纠正分支 `:3081` | ✗ | Gatekeeper 异步路径,且与 tool 路径重复(两路都 mutate);挂两处 = 冗余 |
| SWM 订阅 | ✗ | 异步、延迟,且要新起订阅者(违准则6 #4 正交)|

- **是否真机 turn 热路径**:是(工具调用在 turn 内)。
- **不拖垮 turn**:facet 撤销整段裹 `try/except`(照 P0 接 weave 范式),facet 任何异常 swallow + log,不影响 profile 纠正主逻辑的返回。

## ④ flag-gated / 幂等 / 多 node_id

- **flag-gated**:facet 撤销行为全 `if is_facets_enabled():` 包住。flag off → 纠正照常处理 profile,**完全不碰 facet**(真机零变化,可 revert)。
- **幂等**:`on_sir_correction` → `_find_facets_by_identity_key`(`facets.py:382`)+ `revoke_facet` 幂等;facet 已 revoked → `revoke_facet` 标 revoked 不重复(同一纠正重复到达安全)。
- **多 node_id/多 facet**:若一次纠正离散关联到多条 facet(②b 下同 turn 多 facet),**各自独立离散撤**(逐个调 `on_sir_correction`/`revoke_facet`,不排序、不挑、不打分 —— 同 P0 producer 范式)。
- **不碰既有逻辑**:只在 profile/MemoryGateway 纠正逻辑**之后**附加 flag-gated 的 facet 撤销分支,不改既有 apply_correction / update_sir_field 任何行为;不碰墙/宪法散文。

## ⑤ 红线自检表

| 红线 | 草案条款 | 守住? |
|---|---|---|
| **桥走离散键非相似度** | ① 证伪 node_id 穿用;② 默认无键不碰 facet;②b 仅 turn_id 精确字符串相等关联;**全程零 old/new_value 文本相似度匹配** | ✅ |
| **纯 profile 纠正不误撤** | ② 离散边界: 无精确匹配键 → 不碰 facet(profile 字段纠正默认不动 facet) | ✅ |
| **挂点不拖垮 turn** | ③ tool:160 单点 + try/except swallow(P0 范式)| ✅ |
| **flag-gated 默认 off** | ④ `if is_facets_enabled():` 包住,off 时纠正只动 profile | ✅ |
| **可 revert** | 挂点 = tool 末尾加 gated 几行 + facet 模块已有 on_sir_correction,git revert 干净 | ✅ |
| **不碰 profile 既有逻辑/墙/宪法散文** | ④ 只在既有纠正逻辑后附加,不改 apply_correction/update_sir_field;不碰 walls/[WHO I AM]/[REFERENT MAP] | ✅ |

---

## 给顾问的决断点(本草案需顾问定)

1. **②(默认不碰 facet)单独落,还是 + ②b(turn_id 离散关联)?**
   - ② = 零误撤、零风险,但 facet 永不被 Sir 纠正撤(只能等 reverify 因接地边消失而撤)。
   - ②b = 能撤,但 turn_id 粒度可能误撤同 turn 无关 facet。需顾问评估 turn_id 是否足够精确,或要更细的离散键。
2. 若 ②b 的 turn_id 粒度被判太粗 → 是否需要**先建一个更精确的离散关联键来源**(那又是另一轨,且仍须离散)。

**本草案不替顾问拍 ①/②b 选择 —— 只钉死: 无论选哪个, 都不许用相似度。**

---

*C 设计草案。① IntentResolver node_id 穿用方案凭实物证伪(纠正路径不接 manifold);② 离散安全默认 + ②b 可选 turn_id 关联;③ 挂点 tool:160;④ flag-gated/幂等/多 facet;⑤ 红线自检全守。零代码/零真机/未碰 flag。待顾问审 + 拍 ①/②b。*
