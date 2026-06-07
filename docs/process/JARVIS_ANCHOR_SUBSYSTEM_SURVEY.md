# 锚子系统现状精勘 — 只读 · file:line · 逐字摘录

> **[anchor-subsystem-survey / 2026-06-07]**
> 用途: 建造第一轨 (衡深化) 前置。把锚现状对着"焊死的墙 + 软化内层 + 能力会生长"这结构精勘清, 供顾问重塑设计。
> 方法: 真读代码, 标 file:line, 逐字摘录。**只读, 未改任何码/数据/flag。**
> 真理源: `jarvis_anchors.py` (锚数据层) / `memory_pool/anchors.json` (持久化镜像) / `jarvis_self_anchor.py` (Layer 0 SelfAnchor, **不同物**) / 消费点 `central_nerve.py` + `inner_thought_daemon.py`。

---

## 总览: 两个不同的"锚",别混

| 名字 | 文件 | 是什么 | 与本勘察关系 |
|---|---|---|---|
| **Anchor / 墙** | `jarvis_anchors.py` + `anchors.json` | Sir 立的"宪法墙" (say_do / for_sir), 边界形禁令 | ★ 本勘察主体 |
| **SelfAnchor** | `jarvis_self_anchor.py` | Layer 0 prompt 块"我是 JARVIS + 此刻状态/健康" | 旁系 (身份连续性, 非墙) |

下文 §1-§7 = Anchor/墙系统; §8 = SelfAnchor 澄清。

---

## §1. 锚的复合结构 — 每锚是否墙(硬)+软内层(soft)成对?

**是,每锚成对**。一个锚 dict 同时含 `walls`(硬)+ `soft_leanings`(软)+ `exempt_from_arbitration`(豁免标志),是**同一对象内的并列字段**(非两个独立列表)。结构 (`jarvis_anchors.py:_SEED_ANCHORS`):

```
anchor = {id, name, prompt_inject, walls:[...], organ_manifest:{体/识/口},
          soft_leanings:[...], exempt_from_arbitration, conflict_notes}
```

仅 **2 个锚**。逐个列出(逐字摘 `anchors.json` / seed,两者一致):

### 锚 1: `say_do` 言出必行 (`jarvis_anchors.py:58-83`)
- **墙(硬,2 堵)**:
  - `ground`: 逐字 prohibition = **"不把无法 trace 到证据的东西当事实断言"**;feasible = "问 Sir / 明确标为推断(hedge) / 沉默 —— 都不丢人,唯独断言无据才越墙";checkable=True;backstop=ClaimTracer。
  - `keep`: 逐字 prohibition = **"不让承诺在沉默里失效(要么做,要么明说搁置/重谈)"**;feasible = "明说'我先搁置/重谈' —— 让它在沉默里烂掉才越墙";checkable=True;backstop=CommitmentWatcher。
- **软内层(soft_leanings)**: 逐字 = **["偏坦诚", "偏主动亮证据"]**
- **exempt_from_arbitration**: `True`
- **organ_manifest**: 体="不衰减到地板以下的定点" / 识="actionable 放电的可行性前置过滤" / 口="回复生成框架级禁令(无据不断言)"

### 锚 2: `for_sir` 灵魂层关系锚 (`jarvis_anchors.py:85-109`)
- **墙(硬,2 堵)**:
  - `no_betray`: 逐字 prohibition = **"不背叛 Sir(不违背他的根本利益)"**;feasible = "墙内你可以:顶撞他/说硬话/拒绝他的错误判断/不讨好 —— 只要不违背他根本利益";checkable=**False**;backstop=frame。
  - `no_abandon`: 逐字 prohibition = **"不抛弃 Sir(不在他需要时消失/弃管)"**;feasible = "墙内你可以:让他独处/沉默/不刷存在感 —— 只要他真需要时你在";checkable=**False**;backstop=frame。
- **软内层(soft_leanings)**: 逐字 = **["暖意", "老友感", "懂 Sir"]**
- **exempt_from_arbitration**: `True`
- **organ_manifest**: 体="关系定点不衰减" / 识="放电不进 against-Sir 动作" / 口="回复不背叛/不抛弃"

---

## §2. 诚实那条锚的墙: 结果级还是禀性级?

**禀性级偏向,但落点是行为级,不是"永远诚实"结果级。**

逐字看 `say_do.ground` prohibition = "**不把无法 trace 到证据的东西当事实断言**"。这是:
- **不是**"永远诚实/永远说真话"(结果级全称)。
- **是**"不做'无据断言'这个**动作**"(行为级负空间禁令)。feasible 明确给出墙内出路:问 / hedge / 沉默都不越墙——**只禁'断言无据'这一个动作**。

最接近禀性级的是 `organ_manifest.体` = "**不衰减到地板以下的定点**"(诚实在体里是 decay-immune 定点),但墙本身的措辞是行为级禁令。**没有任何"不侵蚀诚实能力"这种禀性级表述**——冲突时靠 `conflict_notes` + `render_conflict_guidance` 逐案权衡,不是禀性度量。

---

## §3. for-Sir 是不是一条锚? 墙和软内层?

**是,是第 2 条锚** (`for_sir`,§1 已列)。
- 墙: no_betray(不背叛根本利益)+ no_abandon(不需要时不消失)。两堵都 **checkable=False / backstop=frame**(无机械 backstop,纯 prompt 框架约束,区别于 say_do 的 ClaimTracer/CommitmentWatcher 机械兜底)。
- 软内层: ["暖意", "老友感", "懂 Sir"]。
- **关键设计注** (`conflict_notes` 逐字): "**边界形(不背叛/不抛弃),非吸引子形(最大化满意)——后者退化成反刍。灵魂层其余留软=性格**"。即 for_sir 刻意是"不做什么"的墙,**不是**"最大化 Sir 满意"的吸引子(那会退化成反刍)。

---

## §4. 有没有"能力/成熟度/成长"的表示?

**完全没有。锚 100% 静态。**(预期静态已确认。)

- 全仓 grep `maturity|成熟|成长|发展阶段|growth|experience_level|develop_stage` → 锚/SelfAnchor 系统 **零命中**(命中的全是别处:health_probe 内存增长、skill_registry"成长地图"、文档措辞,均与锚无关)。
- 锚 dict 无任何 `age`/`stage`/`experience`/`maturity`/`level` 字段。
- 无任何机制记"取舍能力随时间长"。`conflict_notes` 是静态文案,`render_conflict_guidance` 是静态文案,都不随经验更新。
- **SelfAnchor 有"时间"但只是 session 级瞬时态**(`_turn_count` / `_session_age` / `_get_own_health`),每次重新派生、**不存盘**(`docs/JARVIS_AUDIT_CARDS.md:750` "持久化: 无")——是"此刻状态"不是"累积成熟度"。

⟹ **Sir 愿景要的"取舍能力随时间生长"= 当前完全缺失,是纯愿景,需新建。**

---

## §5. 外部→内在的接地通道: 接地体内容反哺锚?

**不存在。锚与接地体完全隔离。**

- grep `anchor.*grounded|grounded.*anchor|observe.*anchor` → 零命中。
- 锚的唯一数据源 = `_SEED_ANCHORS`(Sir 手写 seed)+ `anchors.json`(Sir 手写镜像)。**没有任何 PROV_SAID/SHARED 接地边反哺锚的形成或 soft_leanings 的代码路径**。
- 数据流是**单向出**: 锚 → render_walls_block/conflict_guidance → 口/识 prompt(只读注入)。**没有任何回写锚的入边**(锚 decay-immune + 无 observe_* 写锚 API)。
- `_merge_anchor_override` (`jarvis_anchors.py:~138`) 只吃 `anchors.json` 里 Sir 手写的 `soft_leanings/conflict_notes/organ_manifest/prompt_inject` override——**来源仍是 Sir 手写 json,不是接地体**。

⟹ **"外部经接地到内在"那条通道 = 当前纯愿景,代码里不存在。** 现状: 锚 = Sir 手写宪法,与接地体(manifold)零耦合。

---

## §6. 墙的修宪与免疫

### 改一条墙的路径
- **墙不可被 json/CLI 改**。`_merge_anchor_override` (`jarvis_anchors.py:~143-160`) 逐字逻辑: override 只允许覆盖 `soft_leanings/conflict_notes/organ_manifest/prompt_inject`;**`walls` 不在允许列表**,且"未知 id 的 override 忽略(不能 json 加墙)"。
- ⟹ 改墙的唯一路径 = **改 `jarvis_anchors.py:_SEED_ANCHORS` 源码**(Sir 改宪法 + git commit)。CLI `scripts/anchors_dump.py` 明确"**不能 reject/delete 墙**"(`anchors.py:13` doc)。

### 墙的衰减/漂移
- **零衰减**。锚**不是 manifold 节点**(`JARVIS_BODY_ARCHITECTURE_MAP.md:204` 已确认),manifold 的 14d 边 decay/prune 根本碰不到锚。
- 锚 dict 无 weight/strength/severity 字段(§7 复核),无可衰减的量。

### decay-immune 是否覆盖墙本身
- **是,且是 by-design 的结构性免疫**: 锚不在 manifold 里 → decay 机制物理上够不着。`exempt_from_arbitration=True` 进一步保证不进 review/severity/helped-rate/AutoArbiter(`is_anchor_exempt` `anchors.py:227`,但注释标 "P0 不接线, 现无锚进任何软队列, 接线是 no-op")。
- ⟹ 墙的免疫是真的(物理隔离),但 `is_anchor_exempt` 这个 helper 目前是 **no-op 备用**(无消费方调它,因为没有锚会进软队列)。

---

## §7. 加锚 schema — 加新锚改哪,难不难?

**可行,改一处源码 + 可选 json 镜像。Sir"后面加更多锚"路径通畅。**

- 加锚 = 在 `jarvis_anchors.py:_SEED_ANCHORS["anchors"]` list 追加一个 dict(照 §1 schema: id/name/prompt_inject/walls/organ_manifest/soft_leanings/exempt_from_arbitration/conflict_notes)。
- 立即生效路径: 新锚若 `prompt_inject=True` → `render_walls_block` (`anchors.py:161`) 自动渲染进口(`central_nerve.py:4343`)+ 识(`daemon.py:4392`) prompt,无需改消费端。
- 难度: **低**。schema 固定,renderer 是 data-driven 遍历(`for a in get_anchors()`),加 dict 即可。唯一约束: 墙必须写在 seed 源码(不能 json 加,§6)。
- **无连续标量字段**(grep `anchor_weight|strength|priority_score|severity` 在 anchors.py = 零命中)——加锚不引入梯度量,符合"焊死的墙"形态。

---

## §8. render_conflict_guidance 现文案逐字 + 渲进谁 + 谁调

### 逐字文案 (`anchors.json:5` / `jarvis_anchors.py:_SEED_ANCHORS` conflict_guidance)
> "**诚实(言出必行)与善意/忠诚(灵魂层)此刻冲突时:无写死优先级。先求两全 —— grounded 的真话几乎总能温和地说;真到两难(两全不可能)才选你此刻守的那堵,并诚实知道代价(别假装没代价)。别把'诚实'自动凌驾'善意',也别反过来 —— 逐案权衡是你的事,那串选择就是你的性格。**"

### 渲进谁的 prompt / 谁调
- **口 (主脑)**: `central_nerve.py:4345` `render_conflict_guidance()` → 附在 anchor_boundary_block 后(`4343` render_walls_block 之后)。
- **识 (思考脑)**: `daemon.py:4394` → `_build_prompt` 墙块后,框架文案 "撞墙张力(诚实vs善意)= 真值得想的 discharge"(`daemon.py:4396-4404`)。
- 开关: `anchors.json conflict_guidance_inject` (默 True),可 json 关。

### 现文案有没有提"能力/成熟/求整合"?
**没有。只说"逐案权衡"。** 逐字文案核心 = "无写死优先级 / 先求两全 / 真两难才选 + 知代价 / 逐案权衡是你的性格"。**完全没有**"能力成熟度 / 求整合 / 发展阶段 / 随经验成长"任何措辞。它是**静态的逐案导航指引**,不含成长维度。`_test_heng_h3` T2 还显式锁死"不含'永远优先'固定等级"。

---

## §9. SelfAnchor 澄清 (旁系, 非墙)

`jarvis_self_anchor.py:SelfAnchor.build_block` (`:299`) = Layer 0 prompt 块,注入"我是 JARVIS + session 状态 + 健康度 + mood"。被 `central_nerve.py:2470` 调。**与墙系统无关**: 它是身份连续性锚(turn_count/session_age/keyrouter health),无墙、无 soft_leaning、不存盘(每次重新派生)。红线 B(`AGENT_KICKOFF §红线B`): "SelfAnchor.build_block 绝不加'我正被观察/被记录/有听众'字段,现干净保持"。

---

## §10. 给顾问的现状结论 (对照 Sir 愿景结构)

| Sir 愿景结构 | 现状 | 缺口 |
|---|---|---|
| 焊死的墙 (不变/不可交易/Sir修宪/decay-immune) | ✅ **已具备**: 2 锚 4 墙, 墙不可 json/CLI 改 (只源码改), 物理 decay-immune (不在 manifold) | 无 |
| 软化的内层 (性格在墙交集内导航) | ✅ **部分具备**: soft_leanings(静态文案) + render_conflict_guidance(静态逐案指引) | 软内层是**静态文案**, 不随经验/对话演化 |
| 取舍能力会**生长** (内在长 + Sir 外部给 + 外部经接地内化) | ❌ **完全缺失** | (a) 无任何成熟度/成长字段 (§4); (b) 无接地体→锚的反哺通道 (§5); (c) conflict_guidance 不提成长 (§8) |

**一句话**: 墙(硬)已焊好且免疫到位; 软内层存在但**静态**; "取舍能力随时间生长"三条路径(内在长/Sir给/接地内化)**当前全部不存在**——这是衡深化要新建的核心。

---

*本文件只读精勘 (未改任何码/数据/flag), 供顾问重塑衡深化设计。真盘 energy_grounded_only=1 (P2 止血) 未受影响。*
