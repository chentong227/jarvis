# "桥"聚焦勘察 — manifold 实体 resolve (NL→node_id) 离散可行性 (只读 / 零代码 / 零真机)

> **[sec9-bridge-resolve-survey / 2026-06-07]**
> Sir 拍定。背景: 合并勘察 `96e31da` 确认 — 因果接地(写 said 边需 node_id)与 §9 A
> 即撤(on_sir_correction 需 identity_key=node_id)共卡同一座断桥: NL → 离散 node_id 映射。
> 本轮只摸这座桥的**离散可行性**。**头号红线: 禁相似度/embedding。**
> 五点 file:line + 证据 + 每点一句判定。**不提方案、不写代码、不碰真机/flag/墙/宪法散文/facets 生产逻辑。**

---

## 点 1 — resolve 入口 (NL/实体名 → node_id?)

`jarvis_relational_manifold.py`:

| 函数 | file:line | 作用 |
|---|---|---|
| `make_node_id(kind, raw_id)` | `:69` | 组命名空间 id `kind:raw_id` (raw_id 指回真理源 store) |
| `split_node_id` | `:81` | 拆 `kind:raw_id` → (kind, raw_id) |
| `resolve(node_id)` | `:888` | **跟随 alias 链到代表节点** (输入已是 node_id, 非 NL) |

⟹ **判定: 没有"一段 NL → node_id"的 resolve 函数**。manifold 的 `resolve` 输入**已是 node_id**(`kind:raw_id`), 只做 alias 链折叠 (node_id→代表 node_id), **不接受自然语言**。"NL→node_id"这一步在 manifold 层**根本不存在** —— 这正是断桥的核心: 桥的"上游半截"(把话变成 node_id)无现成入口。

---

## 点 2 — crystallize_from_node 的 "resolve 后 node_id" 具体是什么

`jarvis_identity_facets.py:crystallize_from_node:321` 注释 "identity_key = manifold.resolve 后的离散 node_id"。追实物:

- 调用处 (`:339-344`): `try: import jarvis_relational_manifold; ikey = manifold.resolve(node_id) except: ikey = node_id`
- 即它调的是 **`manifold.resolve(node_id)`(`:888`)** —— 输入**已经是** node_id(来自 `iter_grounded_nodes:613` 枚举的现存节点), resolve 只把它折叠到 alias 代表。

⟹ **判定: 那个 "resolve" = 点1 的 alias 链折叠 (node_id→代表 node_id), 非 NL→node_id**。crystallize_from_node 的输入 node_id 来自 `scan_and_crystallize` 枚举**已存在的接地节点**(`iter_grounded_nodes`), 全程没有"从话里认出实体"的步骤。它处理的是"已在体里的节点", 不是"把新话接进体"。

---

## 点 3 — 离散还是相似度 (resolve 关键判定行)

`resolve` 全文 (`:888-895`):
```
def resolve(self, node_id, _depth=0):
    if _depth > 8: return node_id          # 深度封顶防坏数据死循环
    rep = self._aliases.get(node_id)        # 纯 dict.get 精确键查
    return self.resolve(rep, _depth+1) if rep else node_id
```
`make_node_id` 规范化 (`:72-78`): `kind.strip()` + `raw_id.strip()` + 非法字符检查 (`_NODE_SEP`/`_KEY_SEP`), 然后 `f"{kind}:{raw_id}"` 纯字符串拼接。

⟹ **判定: resolve + make_node_id 全程纯离散 (exact/canonical 键)**。`resolve` = `dict.get` 精确键查 + 链跟随, **零相似度/embedding/向量**。`make_node_id` = strip + 拼接, 无 lower/同义归一(连大小写都不折叠, 纯字面)。**这半截桥(node_id 层的折叠)是干净的离散键。**

---

## 点 4 — 新实体怎么得 node_id (首次出现)

- `make_node_id(kind, raw_id)` 是**纯函数**: 给任意 (kind, raw_id) 即时拼出 id, **不要求该 node 已存在**(`:69`, 无 store 查、无"存在性"校验, 只查非空+非法字符)。
- node 的"存在"是**隐式**的: manifold 无独立 `add_node` (合并勘察点6已证); 节点随 `add_edge`/`add_alias` 第一次引用时隐式产生。
- `resolve` 对未知 node_id: `self._aliases.get(node_id)` 返 None → `return node_id`(`:894`), **原样返回, 不报错、不新建 alias**。

⟹ **判定: node_id 能为新实体即时生成 (make_node_id 纯拼接, 不需预存)**, **但前提是已有 (kind, raw_id) 这对离散键**。命门转移到: **raw_id 从哪来?** —— 对 thread/concern/joke 等, raw_id = 真理源 store 的现成 id(thread_id/concern_id, 见点5.1); 对"妈妈手术"这种**对话里首提的自由实体**, **没有任何机制产出它的 raw_id**(无"NL→entity raw_id"抽取, 见点5)。故"首提实体→node_id"卡在 **raw_id 的产出**, 而非 make_node_id 本身。

---

## 点 5 — add_alias 近重复判定 + 现成实体抽取

### 5.1 现成"NL→实体"抽取 (用于把一句话拆成实体)

`jarvis_relational_weaver.py`:

| 机制 | file:line | 类型 | 产物 |
|---|---|---|---|
| `_distinctive_terms` | `:94` | **规则/分词** (CJK 2/3-gram 滑窗 + 英文≥4字母 + 去停用词) | 词列表 (用于 lexical 匹配, **非** 生成 node_id) |
| `observe_turn_cooccurrence` | `:117` | lexical 匹配 | 把 turn 文本里命中的词去比对**已存在节点文本** (`_cached_node_texts`), 命中现存 node → 连边 |
| `harvest_nodes` | `:372` | 从真理源 store 取 id | thread_id/concern_id/joke_id/... → `make_node_id` (raw_id 全来自现成 store id) |

⟹ **判定: 有"NL→词"的规则分词 (`_distinctive_terms`, 可复用、非 LLM、非相似度), 但没有"NL→新实体 raw_id"的抽取**。现有 `observe_turn_cooccurrence` 只把对话词去**匹配已存在节点**(命中才连边), **从不为对话里的新名词创建实体节点**。`harvest_nodes` 的 raw_id 全部来自真理源 store 的现成 id —— 即体里的节点永远是"已被别的 store 记下的东西"(thread/concern/joke), **自由对话实体(妈妈/手术)无 store 收容 → 无 raw_id → 进不了体**。

### 5.2 add_alias "近重复"判定依据

`add_alias` 自身 (`:875`) **不含任何相似度**: 只 `resolve(rep)` 防环 + 写 `self._aliases[dup]=rep_r`(纯 dict)。
但**调 add_alias 的上游**决定 dup/rep 怎么选出:

| caller | file:line | "近重复"判据 |
|---|---|---|
| `auto_merge_near_dups` (Weaver) | `jarvis_relational_weaver.py:544`, 比对 `:490` `sim = Mn @ Mn.T` | **🔴 cosine 相似度** (`merge_threshold` 默 0.90 / `auto_merge_dups.threshold` 0.93) |
| `cmd_merge_dups` (CLI) | `scripts/manifold_dump.py:276` | **🔴 cosine 相似度** (同 threshold) |

> ### 🔴 红字 — 相似度/embedding 出没点 (设计必须绕开或隔离)
> 1. **`add_alias` 的上游合并判定走 cosine**: `jarvis_relational_weaver.py:490` `sim = Mn @ Mn.T` (向量点积) + `merge_threshold` (`manifold:110`=0.90 / `auto_merge_dups`:174=0.93)。`add_alias` 函数本身离散, 但"谁该 alias 谁"由 **embedding cosine** 决定。
> 2. **embed 边整类**: `add_geometric_edge:527` / `PROV_EMBED` (`manifold:52`) — `embed_threshold` 0.72 cosine 才连边。这是体里相似度的主来源(但**已被接地白名单排除**: facets 资格闸 `node_grounded_provenance:582` 只认 SAID/SHARED, EMBED 一律排除 — 见合并勘察点2)。
> 3. **桥若要"把新话归并到已有节点"绝不能借道 5.2 的 cosine 合并** —— 那正是 §9 假焊的来源。桥的离散版必须走 exact/canonical raw_id 键, 不碰 alias 的 cosine 上游。

⟹ **判定: add_alias 本体离散, 但其"近重复"上游判据是 cosine 相似度 (红线)**。alias 机制本身(dict 折叠)可安全复用; 但**绝不能复用它的 cosine 合并上游**来做桥。

---

## 桥现状图小结 (五点)

| 点 | 判定 | 核心 file:line |
|---|---|---|
| 1 resolve 入口 | **无 NL→node_id 函数**; manifold.resolve 输入已是 node_id, 只折叠 alias 链 | `manifold:888` |
| 2 crystallize resolve | 那个 "resolve" = alias 链折叠 (node_id→代表), 非 NL→node_id; 输入来自枚举现存接地节点 | `facets:321/339`; `manifold:888` |
| 3 离散/相似度 | resolve = `dict.get` 精确键 + 链跟随; make_node_id = strip+拼接; **全程零相似度** (node_id 层干净) | `manifold:888/69` |
| 4 新实体 node_id | make_node_id 纯函数即时生成不需预存; resolve 未知键原样返回不报错; **但命门=raw_id 从哪来** | `manifold:69/894` |
| 5a 实体抽取 | 有规则分词 `_distinctive_terms`(非LLM非相似度,可复用) 但**只匹配已存在节点**, **无"NL→新实体raw_id"抽取** | `weaver:94/117/372` |
| 5b add_alias 判据 | 🔴 add_alias 本体离散, 但上游"近重复"= **cosine 相似度** (weaver:490 / merge_threshold 0.90); embed 边整类是相似度来源 | `weaver:490/544`; `manifold:110/527` |

### 总判: 桥能否离散搭?

**半截能、半截缺、一处雷。**
- **能 (离散干净)**: node_id 层 — `make_node_id` (拼接) + `resolve` (dict 链) 全离散, 给定 (kind, raw_id) 即得稳定离散键, 新实体也能即时生成 id, 零相似度。
- **缺 (断点)**: "NL → 实体 raw_id" 这一上游步骤**完全不存在** —— 现有只有"NL→词→匹配已存在节点"(lexical, 不产新实体)和"从真理源 store 取现成 id"(harvest)。自由对话实体(妈妈/手术)无 store 收容 → 拿不到 raw_id → make_node_id 无米下锅。桥要离散搭, 缺的是"把一段话里的实体确定性地映射到一个 canonical raw_id"的离散机制(且不得借 cosine)。
- **雷 (红线)**: 唯一现成的"把相近东西归一"机制 (`add_alias` 上游 `auto_merge_near_dups`) **走 cosine** (weaver:490, merge_threshold 0.90)。桥设计**必须绕开它**, 不能用 embedding 近邻来"认出这句话说的是已有的哪个节点"。

→ 一句话: node_id 的"折叠"半截是纯离散键(干净可复用), 但"把话变成 raw_id"的上游半截根本没有, 且唯一现成的归并捷径踩 cosine 红线 — 桥要离散搭, 得新造"NL→canonical raw_id"的离散映射, 绕开 alias 的相似度上游。
