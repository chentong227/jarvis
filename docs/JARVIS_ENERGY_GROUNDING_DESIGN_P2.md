# 势能层接地化 设计 (P2) — 件 A 止血 · 待顾问审

> **[body-diff-P2 / 2026-06-06]**
> 状态: **设计稿, 待顾问审。审过才碰 compute_energy 代码、才碰真机 flag。**
> 性质: **止血** (同 P1 翻 lens inject=0)。势能层 (compute_energy) 是唯一未设防的 body→brain 活线,
> 实测 (c) 洗白实锤 (识回写接地边 8:0 全沉积假焊区邻域) + 4 对双高频假焊正驱动自发思考往假焊区打转。
> 真理源代码: `jarvis_relational_weaver.py` (compute_energy) / `jarvis_relational_manifold.py` (edge_snapshot/spread/neighbors) / `jarvis_relational_lens.py` (P1 护栏对称模板)。
> 前置: `docs/JARVIS_BODY_ARCHITECTURE_MAP.md` §6 (Phase1 架构补图) + `docs/JARVIS_VALIDATION_STANDARD.md` (双镜像铁律)。

---

## 0. 一句话

`compute_energy` 的 novelty/drift 当前**全量数边** (含 embed mesh + cooccur 假焊), 是规范矩阵里唯一 provenance-blind 的核心 body→brain 通道。P2 加 `energy_grounded_only` flag (默 0 不变行为), flag=1 时 novelty/drift **只数接地边** (白名单 `{shared,said}`, 与 spread 同一 `is_grounded` 谓词); tension 不动。配对称耦合护栏防"一翻回洗白态"。守红线 A (机械 provenance 判定, 非打分)。

---

## 1. 炸半径报告 (改前枚举所有 caller — Sir 6 条约束 #1)

### 1.1 `edge_snapshot` caller 全集 (grep 全仓)

| # | 位置 | 用途 | 消费者 |
|---|---|---|---|
| 1 | `weaver.py:869` `pre_snapshot = manifold.edge_snapshot(now=now)` | weave 前快照边权 | compute_energy (drift 比对基线) |
| 2 | `weaver.py:887` `post_snapshot = manifold.edge_snapshot(now=now)` | weave 后快照边权 | compute_energy (novelty/drift) |

**无外部 caller、无 CLI、无测试直接调 `edge_snapshot`** (测试调 `compute_energy` 时直接传 dict 字面量, 不经 edge_snapshot)。两个 snapshot 唯一下游 = `compute_energy:890` + `_diff_and_emit_deltas`。

### 1.2 方案选型 (#1: 选炸半径小的, 绝不改 edge_snapshot 现有键语义)

| 方案 | 描述 | 炸半径 | 选? |
|---|---|---|---|
| **(a) 纯追加 provenance 字段** | `edge_snapshot` 返回每边追加 `"provs": {kind...}` 集合, 现有 `{a,b,w}` 三键**一字不动** | 极小 (旧读取路径零影响; 2 caller 都只读 a/b/w, 不读新键也无害) | ✅ **选** |
| (b) compute_energy 独立 provenance 查询 | edge_snapshot 不碰, compute_energy 回调 manifold 持锁逐边查 provenance | 更大 (compute_energy 要回查 manifold + 重复持锁 + N 次查询) | ❌ |

**判定: 选 (a) 纯追加**。理由: (i) 现有 3 键语义零变更, 满足约束 #1 "绝不改现有键语义"; (ii) compute_energy 已经在遍历 snapshot, 顺手读 `e["provs"]` 即可, 不引入新查询/新锁; (iii) edge_snapshot 在 manifold 持锁内构造, provs 集合一并取出, 无额外锁竞争。

**安全性结论 (回顾问)**: 纯追加安全。`edge_snapshot` 的 2 个 caller 都只读 `a/b/w`, 追加 `provs` 键对它们透明; compute_energy 是唯一会读 `provs` 的新消费者。

---

## 2. 改点清单 (精确到行 — 审过才动)

| # | 文件:行 | 改动 | 性质 |
|---|---|---|---|
| C1 | `manifold.py:908 edge_snapshot` | 每边追加 `"provs": {p.get("kind") for p in e.get("provenance", [])}` | 纯追加键 |
| C2 | `manifold.py` (新模块级函数) | 抽 `is_grounded(provs_set, grounded_provs) -> bool` 共享谓词 | 提取(保行为) |
| C3 | `manifold.py:588-593 neighbors` | 内联白名单判定改调 `is_grounded(e_provs, grounded_provs)` | 提取(保行为) |
| C4 | `weaver.py:765 novelty 循环` | flag=1 时 `if not is_grounded(e["provs"], gp): continue` | 加门(flag-gated) |
| C5 | `weaver.py:771 drift 循环` | flag=1 时同上 | 加门(flag-gated) |
| C6 | `manifold.py:168 "energy" 配置块` | 加 `"energy_grounded_only": 0` | vocab(默 0) |
| C7 | `weaver.py validate_energy_coupling()` | 新函数, 对称 lens `validate_lens_coupling` | 护栏 |
| C8 | `weave_once:890` 前 | 调护栏 (热路径 fail-loud, 见 §5) | 护栏 |

**tension (`weaver.py:778-802`) 一字不动** — Phase1 已确认它读 concern severity / stance / nudge, **不数边**, 与 provenance 无关。

---

## 3. 统一谓词 `is_grounded` (盲点 #2/#3 落地 — Sir 约束 #2 保行为重构)

### 3.1 谓词定义 (红线 A: 机械 provenance 白名单, 非打分/utility)

```python
def is_grounded(edge_provs: set, grounded_provs: set) -> bool:
    """边是否接地 = 其 provenance kinds 与接地白名单有交集。
    纯集合交, 无标量打分/排名 (红线 A)。spread+energy 共用一个关口一次审计。"""
    return bool(edge_provs & grounded_provs)
```

- `grounded_provs` 来源: `cfg.get("spread_grounded_provenance", [PROV_SHARED, PROV_SAID])` — **spread 和 energy 复用同一 vocab 键**, 不新增第二份白名单 (盲点 #3 统一契约: 体对消费方只有一个"何为真"接口)。
- 白名单 = `{shared, said}`。**排除 cooccur** (§15.7 hand_pain↔interview rc=10=玩 AoE4 的偶发假焊) + **排除 embed** (cosine 思考相似非真关联)。与 P1 spread 白名单逐字一致。

### 3.2 保行为重构证明 (Sir 约束 #2)

`neighbors` 现有内联判定:
```python
e_provs = {p.get("kind") for p in e.get("provenance", [])}
if not (e_provs & grounded_provs):
    continue
```
提取后 = `if not is_grounded(e_provs, grounded_provs): continue` — **逻辑逐字等价** (同一个集合交)。

**保行为门**: P1 零假焊门 `_test_body_diff_p1_zero_falseweld` (3/3) 走真 spread→neighbors 路径。提取 `is_grounded` 后该门**必须仍 3/3 绿** = "提取没改语义"的证明。**变红即回退** (约束 #2)。

---

## 4. cooccur/embed novelty 归零 = 显式取舍 (Sir 约束 #3 — 不许静默藏)

**显式声明 (落档, 不藏代码)**:

> `energy_grounded_only=1` 时, cooccur/embed 边对 novelty/drift 的贡献 → 0。这是**有意取舍**: 接受丢失"弱共现先验"(同 turn 共现 + embedding 相似带来的探索性势能)。代价可接受, 因为**真关系会以接地边 (shared/said) 重现** — 若两节点真有关联, 识回写 about 边 (PROV_SHARED) 或 Sir 显式连 (PROV_SAID) 会让它重新进入势能。embed/cooccur 提供的只是"未接地的猜测性势能", 正是它驱动自发思考往假焊区打转 (实测 4 对双高频假焊)。

**为何接受**: 准则 6 "拒绝硬编码信任 LLM" 的精神延伸到体层 = 拒绝"未接地的几何先验冒充真关注"。少数真关联短暂失去探索性势能 < 自发思考被假焊系统性带偏 (洗白 8:0)。

---

## 5. 耦合护栏 (Sir 约束 — 对称 lens, 防"一翻回洗白态")

### 5.1 lens 护栏的对称迁移

lens 护栏防的是: `inject=1 但 grounded_only=0` = 裸 naive lens 投假焊。
energy 护栏防的是反向风险: **energy 被改成"只计非接地边"** (即有人把白名单反转/清空 → 势能只吃假焊 = 洗白态复活)。

```python
def validate_energy_coupling(*, raise_on_violation=False) -> Optional[str]:
    """对称 lens validate_lens_coupling。校验: energy_grounded_only=1 时,
    spread_grounded_provenance 白名单非空且 ⊆ {shared,said,cooccur...}合法接地集。
    白名单被清空/反转 (只剩非接地 prov) → energy 只数假焊 = 洗白态 → fail-loud。"""
```

**护栏触发条件 (fail-loud)**:
- `energy_grounded_only=1` 但 `spread_grounded_provenance` 为空 → 势能无边可数 (退化) → WARN + 当 flag=0 处理。
- `energy_grounded_only=1` 但白名单含 embed/inferred (非接地 prov 混入) → 违背接地语义 → WARN。

### 5.2 落点

- **层1 启动期 loud 早警**: `weave_once` 首次调用前 / weaver 初始化时调 `validate_energy_coupling()` (对称 lens 在 `_init_relational_weaver` 调)。
- **层2 热路径**: `compute_energy` 入口, flag=1 但白名单非法 → bg_log 限流 (`_refuse_log_once` 同款) + 当 flag=0 走老行为 (全量数边)。**不静默退化**。

---

## 6. 红线 A 显式声明 (Sir 约束)

> **红线 A 守住**: `energy_grounded_only` 是**机械 provenance 白名单判定** (集合交 `edge_provs & {shared,said}`), **不引入任何 argmax / utility / 打分 / 排名标量**。它不"给边打分选最优", 只"按 provenance tag 二元放行/拒绝", 与 P1 spread `grounded_only` 完全同构。compute_energy 的权重 (w_novelty/w_drift/w_tension) 是**既有**的分量加权, P2 不碰、不新增。

---

## 7. 盲点标注 (Sir 约束 — 设计须写, 别飘掉)

| 盲点 | 内容 | P2 处置 |
|---|---|---|
| **#1 接地≠正确** | grounded 只保证**可追溯** (有 trace ref), 不保证关联**正确**。corroborated (经 Sir 确证) 是更高层级真度量。 | **P2 不碰**, 留未来。设计显式声明: 接地是"防假焊"的下限, 非"保正确"的上限。 |
| **#4 锚镜像节点衰减** | 锚本体 decay-immune (`anchors.py:227`, Phase1 已确认), 但锚主题的 concern/stance **镜像节点**仍随 manifold 边 14d 衰减。与自我涌现相关。 | **P2 不修**, 记 **open-q 标 P3 候选**。不在本轮 scope, 但钉档防飘。 |

---

## 8. 落地纪律 (同 P1, 一步不跳 — 审过才执行)

### 8.1 测试 (Sir 约束 #4 势能零假焊常驻单测 = 主力门)

**先红后绿** (确定性单测, 压势能值不压 LLM reply):
1. **拍1 RED**: 构造只有假焊邻居 (embed/cooccur, 无 shared/said) 的节点 → flag=0 (off) → compute_energy 该节点 novelty/drift **> 0** (证明这道门能抓到势能层吃假焊)。在**未加门的代码**上必须 RED。
2. **拍2 实做**: C1-C8。
3. **拍3 GREEN**: flag=1 (on) → 同节点 novelty/drift **= 0** (假焊不再供势能); 对照接地边节点 novelty/drift **不变** (接地区 E 不损)。
4. **保行为门**: P1 零假焊 3/3 提取 `is_grounded` 后仍绿。
5. **洗白代理监控**: 8:0 走**周期性重跑只读实测**当常驻监控 (真机翻 flag 后重测"识回写边还落不落假区")。两者 (势能零假焊单测 + 洗白只读实测) 都进《验收规范》。

### 8.2 _runall 零增红 + Tier2 weave_once 验证 (零 token)

- `_runall` 零增红 (基线 88/40)。
- **Tier2 势能层验证 = weave_once 本地计算 (零 token, 非 LLM)**: mirror 副本开 `energy_grounded_only=1` → 跑一次 `weave_once` → 比 `body_energy.json` off vs on → 确认**假焊区 E 归零、接地区 E 不损**。
- 结果回顾问审 → **审过才翻真机 `energy_grounded_only`。不裸翻。**

---

## 9. 验收规范增补 (落 JARVIS_VALIDATION_STANDARD.md)

P2 完工时向《验收规范》新增两条常驻维:
1. **势能零假焊** (确定性单测主力门): 只有假焊邻居的节点 → novelty/drift 贡献 = 0。
2. **洗白方向监控** (周期性只读实测): 识回写接地边落"假区邻域 vs 真分化区"的比值, 真机翻 flag 后应从 8:0 向 0:N 反转。

---

*本设计待顾问审。审过 agent 才执行 §2 改点 + §8 先红后绿。不碰 compute_energy 代码、不碰真机 flag (设计阶段)。件 B (识+衡架构图) 并行起草, 互不阻塞。*
