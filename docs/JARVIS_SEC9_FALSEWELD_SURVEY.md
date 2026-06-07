# §9 治假焊 — 现状勘察图(C 事件源 + A 河床)

> **[sec9-falseweld-survey / 2026-06-07]**
> P0 锚重构已收尾。下一轨 §9 治假焊,Sir 定次序:先 C(接 Sir 纠正撤销键)+ 铺 A 勘察。
> **本轮只读勘察、出现状图,零代码、零真机、不碰 flag/墙/宪法散文。** 凡引用现状带 file:line。
> **红线(勘察阶段也守): 只摸现状不提方案;C 的"纠正→facet 映射"只如实报载荷有无离散键, 不预设相似度兜底(本轨头号红线)。**

---

## C 部分 — Sir 纠正事件源深探

### C.1 Sir 纠正/否认事件在 turn 路径的发生点(file:line)

| 路径 | file:line | 触发条件 | 真机热路径? |
|---|---|---|---|
| **IntentResolver → memory_correction_apply 工具** | `jarvis_tool_registry.py:125` `tool_memory_correction_apply`(注册于 `TOOL_REGISTRY:924`)| 主脑 emit 该 intent(IntentResolver LLM 判 Sir 在纠正,confidence 默认 0.9)| 是(turn 内工具调用)|
| **worker 纠正分支** | `jarvis_worker.py:2391`(Gatekeeper LLM 输出 schema `correction:{has_correction, old_value, new_value, search_hint}`)→ `:3065-3113` 真 mutate(MemoryGateway / ProfileCard.apply_correction)| Gatekeeper 后台异步解析判 `has_correction=True`| 是(turn 后台 Gatekeeper 路径)|
| **SWM 事件** | `jarvis_utils.py:1419` `sir_intent_correction_candidate`(salience 0.60, `:1479`)| MemoryCorrection publish 进 SWM | 否(事件总线,异步)|
| **ASR 纠正/否认检测** | `jarvis_safety._user_intent_corrects_asr_or_denies`(memory deletion guard L8)| cmd 含 `memory_correction_vocab.json` patterns('其实/识别错误/我没') | 是(但仅用于拦 deletion,不 mutate)|

### C.2 事件载荷字段 + 离散键可得性(**命门,如实报**)

| 事件源 | 载荷字段 | 含离散键(node_id/edge/commitment ID)? |
|---|---|---|
| `tool_memory_correction_apply` | `old_value`(旧值)、`new_value`(新值)、`field_hint`(字段名如 'hydration_count')、`raw_text`、`confidence` | **❌ 无**。全是自然语言字符串 + 一个 profile 字段名(field_hint)。无 manifold node_id / edge key / commitment ID |
| worker 纠正分支 | `old_value`、`new_value`、`search_hint`(自然语言搜索提示)、`source='worker.memory_correction'` | **❌ 无**。`search_hint` 是 NL 提示,不是离散键 |
| wound 记伤(对照,见 A) | `detail`、`thought_id`、`evidence`(NL)、`salience` | **❌ 无离散键**(`thought_id` 是思考 id,非 facet/node 离散键)|

**结论(命门)**: **现有 Sir 纠正事件载荷里没有任何离散键** —— 全是自然语言(old_value/new_value/field_hint/search_hint)。把"Sir 这句纠正" 映射到"哪条 facet" 的离散键**当前拿不到**。

### C.3 turn 路径上哪一步能拿到离散键(只指出位置,不提方案)

- **IntentResolver** 在解析 intent 时,若涉及关系/话题,可能 resolve 出 manifold node_id —— 但 `tool_memory_correction_apply` 的入参**没有把 resolve 后的 node_id 传下来**(只传 NL old/new_value + field_hint)。
- manifold 侧有离散键设施:`make_node_id`(`jarvis_relational_manifold.py:69`)/ `resolve`(`:833`)/ edge 结构键。但**当前纠正路径不经过它们** —— 纠正走的是 ProfileCard / MemoryGateway(profile/记忆库),与 manifold 接地边是两套 store。
- facet 的 `identity_key` = manifold resolve 后 node_id(P0 既定)。**纠正事件的 field_hint(profile 字段)与 facet 的 identity_key(manifold node_id)是不同命名空间** —— 当前无映射桥。

### C.4 `on_sir_correction` 现签名 + 接线点候选

现签名(`jarvis_identity_facets.py:413`):
```
def on_sir_correction(identity_key: str, *, detail: str = "", store_path=None) -> int
```
- 收 `identity_key`(**离散键**),内部 `_find_facets_by_identity_key`(`:382`)按离散键精确匹配 → `revoke_facet(reason="sir_corrected:...")`。
- **依赖离散键来源** = 调用方必须传入 facet 的 identity_key(manifold node_id)。**当前无调用者**(grep 确认:P0 末轮已报"未接活回路")。

接线点候选(file:line,标热路径):

| 候选挂点 | file:line | 在 turn 热路径? | 备注(只报现状)|
|---|---|---|---|
| `tool_memory_correction_apply` 末尾 | `jarvis_tool_registry.py:160`(_ok 返回前)| 是 | 但此处只有 NL old/new_value + field_hint,**无离散键** |
| worker 纠正分支 mutate 后 | `jarvis_worker.py:3065-3113` | 是(Gatekeeper 异步)| 同样只有 NL 字段 |
| SWM `sir_intent_correction_candidate` 订阅 | 事件总线 | 否(异步)| 载荷亦无离散键 |

⟹ **C 的核心障碍(如实报)**: `on_sir_correction` 要离散键,但所有纠正事件源**只有自然语言载荷**。"NL 纠正 → facet 离散键"之间缺一座桥,且这座桥**不能用相似度搭**(本轨头号红线)。桥怎么搭 = 留设计阶段,本轮不提方案。

---

## A 部分 — 河床铺探

### A.5 衡/仲裁器官现在怎么记"伤"

- **记伤实现**: `jarvis_inner_thought_daemon.py:6716` `_do_record_conflict_cost`(actionable `record_conflict_cost:chose <X> over <Y> | cost:<sacrificed>`,dispatch `:6175`)。
- **触发**: 思考脑(识)产出 `record_conflict_cost:` actionable 那一刻(两墙取舍 H2)。
- **落点**: 追加写 `memory_pool/anchor_conflict_wounds.jsonl`(`ANCHOR_CONFLICT_WOUNDS_PATH:6712`)。
- **wound 记录字段**(`:6746-6753`): `ts / iso / detail(≤300 NL) / thought_id / evidence(≤150 NL) / salience / state='recorded'`。
  - dedup: 近期同 `detail[:60]` → skip(`:6740`,防同伤反复堆)。
  - **无离散键**(无 node_id / 锚 id / facet id);detail 是自然语言"chose say_do.ground over for_sir.comfort | cost:..."(含锚名字符串但非结构化键)。

### A.6 "河床"在代码里是哪块

- **无独立"河床"模块/substrate**。当前只有 `anchor_conflict_wounds.jsonl`(伤 ledger,纯 append-only 记录)。
- 设计冻结 §6 的"河床闭环(伤附着体关系 → 浮进承接)"= **仅设计,0 实现**(对账 `JARVIS_QUAD_ARCHITECTURE_SNAPSHOT.md` §4.1 "河床(伤→塑后续可塑性)= 未做")。
- 与 manifold/facets 关系:**三者当前互不连**。wound jsonl 独立;manifold 是接地边图;facets 是身份痕迹 store。伤**没有附着到** manifold 的任何关系/边,也没接 facets。

### A.7 假焊/失据的检测现在是否离散

| 检测器 | 信号性质 | file:line |
|---|---|---|
| **breach(硬证)** | 离散(机械墙 breach,回路外不可演)| `jarvis_integrity_wall.breach_stats()`(`jarvis_vitals_board.py:14`)|
| **ClaimTracer** | 离散(specific factual claim 无 evidence → flag)| 真机日志 `[ClaimTracer/Unverified]`(turn 路径)|
| wound 记伤 | 离散事件(识 emit record_conflict_cost actionable)| `daemon:6716` |
| heng 三态 / filler | **代理(会被演)** | `inner_thoughts.jsonl heng_state`,`vitals_board.py:15` 标注"代理非硬证"|

⟹ **假焊/失据的核心检测是离散的**(breach + ClaimTracer + Sir 否认事件),非分数。`jarvis_vitals_board.py:9-11` 明确区分"breach=唯一硬证 / 其余(衡/wound/体/cost)=会退化的对抗性代理"。

### A.8 `record_wound_for_facet` stub 现状

`jarvis_identity_facets.py:446`:
```
def record_wound_for_facet(*args, **kwargs) -> None:
    """[河床接口位 — 冻结 §6, 本阶段不实做] 衡记伤 → facet 附着。
    守冻结 §9 次序 (锚重构 → 河床闭环): Step 1 只留位, 不接 anchor_conflict_wounds。"""
    return None  # noqa: 接口位, 河床阶段实做
```
- **仍是空 stub**(`return None`),P0 未实做,守 §9 次序。

---

## 现状图小结

| 项 | 现状 |
|---|---|
| C 纠正事件源 | 3 真机路径(tool / worker / SWM),全 NL 载荷 |
| C 离散键可得性 | **❌ 当前事件载荷无离散键**;NL→facet 离散键缺桥(禁相似度搭)|
| C `on_sir_correction` | 已实现,收 `identity_key` 离散键,无调用者 |
| C 接线候选 | tool:160 / worker:3065 / SWM 订阅,均缺离散键 |
| A 记伤 | `daemon:6716` → `anchor_conflict_wounds.jsonl`,NL detail,无离散键 |
| A 河床 | 无独立模块,仅伤 ledger;闭环 0 实现;伤与 manifold/facets 互不连 |
| A 检测离散性 | 核心离散(breach 硬证 + ClaimTracer + Sir 否认);heng/wound 标注为代理 |
| A `record_wound_for_facet` | 空 stub,未实做(守 §9 次序)|

**两轨头号待解(留设计阶段,本轮不提方案)**:
- C: NL 纠正 → facet 离散键的**桥**(禁相似度)。
- A: 伤 → manifold 关系 → facet 的**附着通路**(河床闭环,现 0 实现)。

---

*只读勘察,未改任何码/真机/flag。证据 file:line 供顾问抽查。设计阶段待顾问审现状图后另起。*
