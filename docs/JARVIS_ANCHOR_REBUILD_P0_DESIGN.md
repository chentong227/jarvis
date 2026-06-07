# 锚重构 P0 — 勘察报告 + 设计草案

> **[anchor-rebuild-P0 / 2026-06-07]**
> 设计冻结 `35c8bb0` §9 第一阶段 = 锚重构。目标方向(冻结 §2/§7):锚综合四架构、可增减(随真接地痕迹长 / 随失效证伪减)。
> 本轮**只产勘察报告 + 设计草案, 零代码、零真机、不动 energy_grounded_only**。凡引用现状带 file:line。
> **状态: 草案待顾问/Sir 审, 审过才动码。**

---

## A. 勘察报告(凭实物)

### A.0 两个"锚"子系统(必须先厘清, 否则设计会串)

现状有**两个独立的"锚"代码物**, 名字都叫 anchor 但层级/职责不同:

| 子系统 | 文件 | 是什么 | 进口主脑路径 |
|---|---|---|---|
| **SelfAnchor (Layer 0 "我")** | `jarvis_self_anchor.py` `SelfAnchor.build_block` | 第一人称"我是谁/我此刻的连续态"散文块(`=== I AM J.A.R.V.I.S. ===`)。日志恒定 `L0=1700c` 即此块。 | `_assemble_prompt` Layer 0 注入(`build_block(max_chars=1700)`) |
| **锚/墙 (宪法 2 锚)** | `jarvis_anchors.py` `_SEED_ANCHORS` | 2 锚(say_do / for_sir)+ 4 墙(ground/keep/no_betray/no_abandon)+ soft_leanings + conflict_guidance | `render_walls_block` → `anchor_boundary_block`(口 `cn:4370` / 识 `daemon:4393`) |

冻结 §2 "锚综合四架构成连贯的'我'" + §3 "墙 4 条钉死" ⟹ **"锚"= 这两者的合体概念**: SelfAnchor 是"我"的载体, `jarvis_anchors.py` 的墙是"我"不动的骨架。本设计的"锚增减"主要落在 **SelfAnchor 的内容来源** + 一个**新的"已结晶身份痕迹"层**, 墙(`_SEED_ANCHORS.walls`)绝不动。

### A.1 SelfAnchor.build_block 全链(`jarvis_self_anchor.py:299-440`)

锚块由 8 段拼成, 逐段标静态/动态:

| 段 | 行 | 内容 | 静态/动态 | 来源 |
|---|---|---|---|---|
| `[WHO I AM]` | 322-340 | "I am JARVIS… 第二锚 for-Sir + 诚实… SHAPE where walls intersect" | **静态写死**(散文常量) | 源码字面 |
| `[MY CURRENT CONTINUITY]` | 342-371 | session uptime / boot / previous session / turn_count / last_spoke / topic / commitments | **动态** | `_get_session_age_minutes` / `_get_previous_session_info`(扫 runtime_logs mtime, `__init__:148-176`)/ `_turn_count` / `_extract_topic(stm)` / `_get_pending_commitments` |
| `[MY OWN HEALTH RIGHT NOW]` | 373-403 | API key capacity / memory chains / active concerns / mood | **动态** | `_get_own_health`(读 KeyRouter/Hippocampus/Concerns, `:210-257`)+ `_derive_mood`(`:56-79`) |
| `[REFERENT MAP]` | 404-411 | "you=ME, I=Sir" 指代映射 | **静态写死** | 源码字面 |
| `[MY LIVED EXPERIENCE]` | 413-437 | 近 30min inner voice 心流 | **动态** | `inner_voice_track.recent` |
| C2 死亡意识 | 439-446 | (注释:**不进 prompt**, 待 Sir 另案) | — | — |

**关键发现**:
- "我是谁"的**身份内核**(`[WHO I AM]` 322-340 + `[REFERENT MAP]`)= **100% 静态散文写死**, 无任何动态成分。
- 动态成分全是**当下状态采集**(uptime/health/topic/心流), **不是"身份结晶"** —— 它们每 turn 重新派生、不持久化(`SelfAnchor` docstring `:111` "不持久化, 每次重新派生")。
- ⟹ 现状 = 冻结 §2 所谓"综合四架构成连贯的我"**只做到读当下状态拼散文, 没有任何"痕迹结晶进身份"的机制**。这正是锚重构要补的。

### A.2 单向只读现状(对账 MIND_HENG #5/#6)

`jarvis_anchors` 全工程消费者(grep `import jarvis_anchors`):

| 读方 | 接口 | file:line | 方向 |
|---|---|---|---|
| 口(central_nerve) | `render_walls_block` | `cn:4370` | 锚→口, **只读** |
| 识(daemon) | `render_walls_block` | `daemon:4393` | 锚→识, **只读** |
| homepage | `get_anchors` | `jarvis_homepage.py:84` | 锚→展示, 只读 |
| CLI | `ensure_anchors_file` | `scripts/anchors_dump.py:56` | seed→disk(幂等), 可调 soft_leanings |
| tests | `get_anchors` 等 | 多处 | 只读 |

**唯一写路径**: `_merge_anchor_override`(`jarvis_anchors.py:138-158`)—— json override **只吃** soft_leanings/conflict_notes/organ_manifest/prompt_inject;**walls 不可被 override**(`:153-154` "墙以 seed 为准")。

**确切读写方向**:
- 锚被口/识/说**单向只读注入**(MIND_HENG 块4.3 "单向只读", `cn:4370`/`daemon:4393`)。
- 锚**不读** 识/体/衡 —— `jarvis_self_anchor.py` 只 import `os/re/threading/time` + `TraceContext` + `inner_voice_track`(grep 确认无 manifold/auto_arbiter/anchors 互读);`jarvis_anchors.py` 是纯数据层(`:11-12` "不消费、不改任何运行时行为")。
- 锚**读墙**: 仅 SelfAnchor `[WHO I AM]` 散文里**字面提了一句** "SHAPE where these walls intersect"(`:333-339`)—— 这是**散文描述, 不是程序读 `_SEED_ANCHORS.walls`**。SelfAnchor 代码层**不 import jarvis_anchors**(grep 确认)。墙的程序化读在口/识的 `render_walls_block`, 与 SelfAnchor 是两条独立注入。

### A.3 锚 vs 墙的现有关系(实物)

- 墙定义: `jarvis_anchors.py:_SEED_ANCHORS` 4 墙(ground/keep/no_betray/no_abandon, `:56-86`)。
- 墙 decay-immune / 不可改: `:8-9`(豁免 review/severity/AutoArbiter/decay)+ `_merge_anchor_override:153-154`(walls 不可 override)。
- 锚**读墙不改墙**实物: 唯一"改"路径 `_merge_anchor_override` 明确跳过 walls;无任何代码写 `_SEED_ANCHORS`。✅ 现状符合"锚读墙、改不动墙"。

### A.4 锚 vs 体(接地痕迹)— 凭实物确认"没有通路"

- `jarvis_self_anchor.py` import: 仅 `os/re/threading/time` + `TraceContext` + `inner_voice_track`(`:45-49` + `:124`/`:411`)—— **无 `jarvis_relational_manifold` / `jarvis_relational_weaver`**。
- `jarvis_anchors.py`: 纯数据层, 无 manifold import。
- 体(manifold)的真痕迹 PROV_SAID/PROV_SHARED(`jarvis_relational_manifold.py`)**无任何通路进锚**。
- ⟹ **确认(非假设)**: 锚与体零耦合(对账 MIND_HENG 块4.2 "体↔锚 无直接接触" + QUAD §3 "外部→锚接地通道 不存在")。锚 100% 静态身份内核 + 当下状态采集, 接地痕迹进不了身份。

---

## B. 设计草案(锚"增减"机制 — 正面回答硬问题, 每条守冻结红线)

> 核心立场: 锚的"长"= **离散资格判定的身份痕迹结晶**, 不是显著度排序取 topN。下面每条都对照冻结 §5(不评分/不交易)/ §3·§10(墙钉死)/ §7(随真接地非旋钮)。

### B.5 锚增的资格与内容(离散资格, 非排序打分)

**新增一层: "已结晶身份痕迹"(identity facets), 独立 store, 围绕墙生长, 不碰墙。**

什么够格结晶进锚 —— **离散资格闸(全 AND, 无打分)**:
1. **真出处**: 该痕迹在体(manifold)里有 `PROV_SAID` 或 `PROV_SHARED` 接地边(不是 embed mesh 假焊、不是 cooccur 偶发)。出处是**布尔资格**, 不是权重。
2. **接地条件(离散事件, 非阈值分数)**: 该关系痕迹被**复现 ≥ N 次真实事件**(N 是离散计数, 如"Sir 在 ≥3 个不同 turn 真的提了同一关系/承诺/立场"), **且**每次都经接地核验(同 affordance 的 `verify_and_write` 命门: 证据点亮, 非"说过"点亮)。
3. **与墙正交**: 结晶内容不得是墙的复述/改写(墙已在 `_SEED_ANCHORS`)。身份痕迹是**墙内自由空间里长出的具体性格/关系定点**, 不是新墙。

**"长"怎么发生而不变成排序**:
- 不存在"所有候选痕迹打分→排序→取 top5 进锚"。
- 每条痕迹**独立**过资格闸(1+2+3 全 AND)→ 过了就**离散地**写入 identity facets store(一个布尔事件: 结晶 or 不结晶)。
- 没有跨候选比较、没有公共货币、没有 argmax。多条同时够格 → 多条都进(受 §B.8 容量上限约束, 但上限是**离散 FIFO/出处优先级的硬规**, 不是分数排序 —— 见 B.8)。

> 红线守: 资格闸是离散 AND(真出处 ∧ 复现计数 ∧ 正交), **无系数/权重/打分/argmax** → 守 §5/§10。

### B.6 锚减的触发(离散事件驱动, 非分数掉阈值)

什么算"失效/证伪" —— **离散事件**:
1. **出处被 Sir 纠正**: 该痕迹对应的源被 Sir 显式纠正/否认(如 MemoryCorrection 事件、Sir 直接说"不是这样")→ 立即撤销结晶(离散事件, 非降分)。
2. **接地边消失**: 该痕迹在体里的 PROV_SAID/SHARED 接地边被删/不再存在(真出处没了)→ reverify 失败 → 撤销。
3. **长期无复现 ≠ 自动减**(关键守红线): 单纯"久没出现"**不直接降级身份**(对照 affordance 补遗-1: 时间不单独降级 can, 只触发**重新核验**)。时间到 → 触发"去 reverify 出处是否还在", reverify 看的是**出处事件**(还在=留, 没了=撤), 不是"显著度分数掉到阈值下"。

> 红线守: 三条全是离散事件(纠正/边消失/reverify 出处), **无"分数掉阈值下"** → 守 §5/§7。

### B.7 锚综合四架构的实在含义(不含糊)

锚"综合"口/识/体/衡, **读它们的什么、合成什么**:

| 架构 | 锚读它的什么(离散事实, 非分数) | 合成进锚的什么 |
|---|---|---|
| **体** | identity facet 的**接地出处**(PROV_SAID/SHARED 边存在与否 + 复现计数) | B.5 资格闸的"真出处"判据来源 |
| **识** | 识 propose 的**立场/关系痕迹**(actionable 产物, 离散事件) | 候选 facet 的来源之一(仍须过 B.5 资格闸) |
| **衡** | 衡的**记伤**(`anchor_conflict_wounds.jsonl`, 离散伤事件)→ 见 §6 河床(冻结 §6, 排在锚重构后) | (本阶段不接, 留河床闭环阶段;此处只标接口位) |
| **墙** | `_SEED_ANCHORS.walls`(只读, 4 墙) | 身份痕迹必须**正交于墙**(B.5 条件3), 墙是不动骨架 |

**合成 = 离散写入 identity facets store**(每条 facet 一条记录: `{facet_id, content, provenance:[{source∈{manifold_said,manifold_shared,inner_thought}, ref, recurrence_count, ts}], crystallized_ts, status∈{active,revoked}}`)—— **无 strength/weight/score 标量字段**(同 affordance store 范式)。SelfAnchor.build_block 渲染时**离散列出** active facets(像现在列 commitments 一样), 不排序打分。

> 红线守: 读的全是离散事实(出处存在/复现计数/记伤事件), 合成是离散写入 + 离散渲染, **无打分合成** → 守 §5。

### B.8 稳定 vs 可塑 怎么共存(§3 边界)

- **稳定来源 = 墙(源码级骨架, 永不动)**: `_SEED_ANCHORS` 4 墙 + SelfAnchor `[WHO I AM]`/`[REFERENT MAP]` 静态内核(可保留为"宪法散文")。这部分**锚改不动**(墙在演化半径外, 冻结 §3/§7)。
- **可塑部分 = identity facets 层(围绕墙生长)**: 新结晶的具体性格/关系定点, 增减都在这一层, **绝不触及 `_SEED_ANCHORS.walls`**。
- **"我"连贯不漂散的保证**:
  1. facets 必须**正交于墙 + 围绕墙生长**(B.5 条件3)—— 自由只在墙内空间。
  2. 增减是**离散资格事件**, 不是连续漂移 —— 没有"分数缓慢移动"导致身份悄悄变形。
  3. 容量上限若需要 → 用**离散硬规**(如 FIFO 淘汰最老的 revoked, 或按出处类型的硬优先级 PROV_SHARED > PROV_SAID), **不是按分数排序砍** —— 仍守 §5。

### B.9 红线自检表

| 红线 | 草案条款 | 守住? |
|---|---|---|
| **§5 不评分**(无系数/权重/argmax) | B.5 资格闸=离散 AND;B.7 合成=离散写入/渲染;store 无 strength/score 字段;B.8 容量=离散硬规非排序 | ✅ 守住 |
| **§5 不交易**(不在公共货币权衡两值) | 每条 facet 独立过闸, 无跨候选比较、无公共货币 | ✅ 守住 |
| **§3/§10 锚改不动墙** | facets 层独立于 `_SEED_ANCHORS.walls`;`_merge_anchor_override` 已守 walls 不可改;新层不碰 walls | ✅ 守住 |
| **§7 锚增=随真接地, 非旋钮** | 增=真出处(manifold PROV_SAID/SHARED)+ 离散复现计数 + 接地核验;无"拧显著度旋钮" | ✅ 守住 |
| **§7 锚减=离散事件, 非分数掉阈值** | 减=Sir 纠正 / 接地边消失 / reverify 出处没了;时间只触发 reverify 不直接降级(对照 affordance 补遗-1) | ✅ 守住 |
| **§6 回塑次序** | 衡记伤→facet 的接驳**本阶段不做**(只标接口位 B.7), 留河床闭环阶段(冻结 §9 次序: 锚重构→河床) | ✅ 守次序 |

---

## C. 边界 + 代理 dev 注

- **零施工**: 本轮未改任何代码、未碰真机、未动 energy_grounded_only。本文档为**设计草案**, 待顾问/Sir 审, **审过才动码**。
- **施工次序提示**(冻结 §9): 锚重构(本设计)→ 河床闭环 → 接地骨架长厚 → 动态软化。B.7 衡记伤→facet 接驳属河床阶段, 本设计只预留接口位不实做。

---

*勘察报告(A, 带 file:line)+ 设计草案(B, 正面答 §5–§9 硬问题 + 红线自检)+ 边界确认。零代码/零真机/未动 flag。草案待顾问审 → Sir 审过才进施工。*
