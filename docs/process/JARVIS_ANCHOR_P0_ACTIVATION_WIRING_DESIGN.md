# P0 锚重构激活接线 — 勘察 + 草案设计

> **[anchor-P0-activation-wiring / 2026-06-07]**
> 依据: P0 四步机理(4007f40 Step1 / 68a505c Step2+3 / 11280a2 末轮)已审、红线干净。
> 已确认 `scan_and_crystallize`(producer)/ `reverify_all_facets`(锚减重核)**未接活回路** —
> 光开 flag,facets store 仍空、不自动结晶/重核。本 doc 出**接线勘察 + 草案设计**。
> **本轮零代码、零真机、不碰 flag/墙/宪法散文/energy_grounded_only。** 凡引用现状带 file:line。
> **状态: 草案待顾问审 → Sir 拍, 才施工。**

---

## 一、勘察(凭实物, file:line)

### 1.1 中枢活回路 — 候选 call-site

| 候选 | file:line | 触发频率 | 已有职责 | 别的模块怎么挂的 |
|---|---|---|---|---|
| **RelationalWeaver.weave_once / run_forever** | `jarvis_relational_weaver.py:944`(weave_once)/ `:1022`(run_forever, `while not self._stop`)| **周期**, `weave_interval_s` 默认 **600s**(`:1024`), boot 后延迟 `initial_delay_s`=90s | 体维护器官: harvest 节点 → 织几何边 → decay/prune → 算势能 → 派 body_delta。**与 facets 同域**(facets 源 = manifold 接地边) | weave_once 内顺序调一串 `weave_*` / `maintain` / `compute_surfaces`(`:949-980`),都是"weave 后顺手做的维护步" |
| InnerThoughtDaemon tick | `jarvis_inner_thought_daemon.py`(adaptive tick 60s/3min/10min/30min)| 周期(自适应)| 识: 5 类思考 + 4 actionable | daemon `_tick` 内分支 |
| AutoArbiterDaemon tick | `jarvis_auto_arbiter.py` `TICK_INTERVAL_S=300` | 周期 300s | 衡: review queue 仲裁 | daemon tick |
| per-turn hook(主脑组装路径)| `jarvis_worker.py` turn 编排 / `jarvis_central_nerve._assemble_prompt` | **每轮对话** | 口: 组 prompt + 发声 | turn 内逐步调 |

### 1.2 真机当轮"新增接地边"发生在哪

接地边(PROV_SAID/PROV_SHARED)由 Weaver 的 observer wrapper 写,真机调用点:
- `observe_cooccurrence`(`manifold:480`)/ `observe_explicit_link`(`:496`, PROV_SAID, ref=turn_id)/ `observe_shared_entity`(`:502`, PROV_SHARED, ref=entity_id)。
- 真机生产调用(非测试):`jarvis_relational_weaver.py:148`(`observe_cooccurrence`,turn 节点共现)+ `:187`(`observe_shared_entity`,识产出带 concern_id 的 thought "那一刻" 记 grounded 边)。
- ⟹ 接地边的产生本就**挂在 Weaver/识 的路径上**,不是每轮口路径直接写。这支持"周期扫"而非"每轮扫"(边不是每轮都新增)。

---

## 二、草案设计《P0 激活接线》

### 2.1 producer 接哪、节奏(候选 + 推荐)

**红线(死守)**: 触发节奏必须**离散** —— 绝不按显著度/紧迫度决定何时跑或先扫哪个(后门评分)。`scan_and_crystallize` 内部已是"够格全结晶、不排序"(`iter_grounded_nodes` 不排序 + 逐个独立过闸),接线只决定**何时触发**,同样必须离散。

| 候选 | 接法 | 代价 | 离散性 |
|---|---|---|---|
| **A. Weaver 周期(推荐)** | weave_once 尾 `if is_facets_enabled(): scan_and_crystallize()`(`weaver.py:944` 区, manifold save 后)| 每 ~600s 扫一次全部接地节点;manifold 刚 weave 完、数据最新;扫的代价 = O(接地节点数), 与 weave 同量级(weave 本就遍历边)| ✅ 每 weave 一次 = 离散周期, 不看显著度 |
| B. daemon 独立周期 | 新起 facets daemon, 每 N 秒 tick | 多一个线程;与 Weaver 重复遍历 manifold | ✅ 离散周期, 但与 Weaver 职责重叠(违准则6 #4 正交) |
| C. 事件触发(挂 observe_*) | observe_explicit_link/shared_entity 成功后触发该节点 crystallize | 最省(只动新增边的节点);但要改 manifold observer 热路径 | ✅ 事件离散, 但侵入 manifold 热路径, 且单边新增时复现计数常 <N(频繁空跑)|

**推荐 = A(Weaver 周期)**。理由:
1. **同域正交**(准则6 #4): facets 源 = manifold 接地边, Weaver 是 manifold 维护器官, "weave 完顺手扫结晶" 与现有 `maintain`/`compute_surfaces` 同性质,不新增线程、不与谁抢职责。
2. **数据最新**: 接在 `manifold.save()` 之后,扫的是刚 weave 的最新接地边。
3. **离散周期纯净**: 每 weave 一次 = 离散节奏,不看任何显著度;`scan_and_crystallize` 内部 `iter_grounded_nodes` 不排序、够格全结晶,先扫哪个/扫不扫都不依赖分数。
4. **代价可控**: weave_once 本就遍历全 manifold(harvest + 织 + prune),facets 扫 O(接地节点数) 同量级,不显著加重(且接地节点 = shared/said 边端点,现实测极薄 shared 8/said 0 量级)。

### 2.2 reverify_all_facets 接哪、节奏

**推荐 = 同 Weaver 周期, 但降频**: weave_once 尾,`if is_facets_enabled() and self._weave_count % R == 0: reverify_all_facets()`(R = 离散常量,如 R=6,即每 6 次 weave ≈ 1h 重核一次,复用现有 `decay_every_n_weaves` 同款离散节拍 `weaver.py:959`)。

- **降级只由证据**(B.6): `reverify_facet` 重 gather 接地 provenance — 边没了 → revoke(`grounding_edge_gone`);边在 → 留 active。
- **时间只触发重核, 不直接降级**(B.6 第3条): `% R == 0` 只是"该去重核了"的离散节拍,reverify 看的是出处事实,不是"facet 老了就降级"。
- Sir 纠正撤销(`on_sir_correction`)是**事件触发**(MemoryCorrection / Sir 显式否认钩子),不在周期里 —— 这条接线属独立事件钩子(可与 producer 接线同轮或后续,接在 IntentResolver/MemoryCorrection 真路径)。

### 2.3 全程 flag-gated

接线处**一律** `if is_facets_enabled():` 包住。默认 off → weave_once 走原路径,真机零变化。`JARVIS_FACETS=1` 才激活(env 显式开,不持久化)。改动可 `git revert`。

### 2.4 幂等 / 代价

- **幂等已具备**: `scan_and_crystallize` 同离散键 → 同 `facet_id`(`_make_facet_id`),重扫安全、不重复结晶。周期反复跑 = 安全。
- **代价上界**(选 A): 每 weave 扫 O(接地节点数)。接地节点 = PROV_SAID/SHARED 边端点(`iter_grounded_nodes` 遍历 `_edges` 一次),与 weave_once 已有的全边遍历同量级,周期 600s → 不进热路径、不影响 TTFT(准则1)。

### 2.5 明确不做(本轮 + 边界)

- 不碰墙 / 宪法散文 / energy_grounded_only。
- 衡记伤→facet 仍接口位(守冻结 §9 次序: 锚重构 → 河床闭环)。
- 本轮不写实现代码(草案);施工在审过后另轮,带 B 验(覆盖 flag-on 周期真跑 → store 真填充 → 渲染进 prompt)。

---

## 三、红线自检表

| 红线 | 草案条款 | 守住? |
|---|---|---|
| **节奏离散非评分** | A: 每 weave 一次(周期离散);reverify: 每 R 次 weave(离散节拍 % R) | ✅ |
| **何时跑不按显著度** | 触发 = 周期/计数节拍,不看任何 salience/紧迫度 | ✅ |
| **先扫哪个不排序** | `scan_and_crystallize` 调 `iter_grounded_nodes`(不排序)+ 逐个独立过闸, 够格全结晶 | ✅ |
| **flag-gated 默认 off** | 接线处 `if is_facets_enabled():` 包住, 默认 off 真机零变化 | ✅ |
| **可 revert** | 接线 = weave_once 内加 gated 几行, git revert 干净 | ✅ |
| **墙·宪法散文不动** | producer/reverify 只读 manifold 接地边 + 写 facets store, 不碰 `_SEED_ANCHORS.walls` / `[WHO I AM]` / `[REFERENT MAP]` | ✅ |
| **降级只证据非时间(B.6)** | reverify 看接地边在否; `% R` 只触发重核不直接降级 | ✅ |
| **§9 次序** | 衡记伤→facet 仍接口位, 本轮不接河床 | ✅ |

---

*勘察(call-site file:line)+ 草案(producer & reverify call-site + 离散节奏 + 推荐 A Weaver 周期 + 理由)+ 红线自检表。零代码/零真机/未碰 flag。施工待顾问审 → Sir 拍。*
