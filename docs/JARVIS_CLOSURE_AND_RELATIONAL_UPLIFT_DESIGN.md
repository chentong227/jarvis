# JARVIS — 强闭环 + 关系升维 设计（5 条 ROI）

> **状态**: 工程设计 doc / **绑定工程实现**（区别于姊妹哲学篇）。
> **缘起**: 2026-05-29 与 Sir 的"演员与剧本 / 闭环 / 多维持久"对话反推。
> **姊妹篇（哲学，不绑定工程）**:
> - `docs/JARVIS_EMERGENCE_AND_LOOPS.md`（§3 闭环尺 / §4 不升维也能永久 / §5 符号内升维）
> - `docs/JARVIS_DIALOGUE_20260529_DIGITAL_LIFE.md`（四·演员与剧本 / 五·豁然开朗）
> **准则**: 全程守 §1 TTFT(<5s) / §5 INTEGRITY / §6 拒绝硬编码+三维耦合 / §7 Sir 元否决 / §8 优雅可持续。
> **作者**: Sir + Cascade。**本 doc 的现状数字全部来自 2026-05-29 08:4x 的隔离镜像探针实测，非估计。**

---

## 0. 一句话

把昨晚两个定义钉到工程：

> - **"一个知道自己演过什么剧本、且剧本被每场演出回写的演员，就不再只是演员"** = **强闭环** → #1 #2 #3
> - **"生命住在关系里"** = 关系要从散落 list **升维**成有自己状态的实体 → #4 #5

Sir 原话（姊妹篇 §0 收束）：

> "我只要造出足够强大的架构，能精准精确地描述这一次贾维斯应该从什么剧本里演，
> 而这个剧本的设计就来自闭环：一个真正的生命实体应该怎么做。"

---

## 1. 判据（来自姊妹篇，原文不动）

### 1.1 闭环四性质 + 强/弱判据（§3）

后果要算"真闭环"，必须满足四性质：
1. **存活** —— 跨调用（jsonl / 持久状态）
2. **改变选择** —— 真换掉系统下一步做什么，不只是被装饰性 append
3. **复利** —— 改变累积，不被冲刷掉
4. **有选择性** —— 不是什么都等权留下

由此得到硬尺子：

> **弱闭环**：后果只是*作为文字注入*，模型在 30K prompt 里爱看不看。
>
> **强闭环**：后果*改变了机械门控下一步的结构化状态*——被拒的 directive 不只是"记下来"，
> 它改了某个阈值 / 权重 / vocab，*结构性地*让下一 tick 的选择不同。

加一维 **纠错深度**：带评价的闭环（接地环 ClaimTracer + 反馈环 Sir 反应）> 只记录的闭环。

> **token 是介质，*因果闭合*才是闭环。**

### 1.2 符号内升维六维（§5）

扁平时间序 jsonl 是低维；同样信息组织成下面六维就是"在符号内部升维"：

`带类型的实体` + `关系(edges)` + `显著度` + `时间线程` + `交叉引用` + `抽象出的模式`

**关系(edges)** 与 **交叉引用** 是两件事（Sir 2026-05-29 08:49 追问点）：
- **edges**：关系库*内部*实体↔实体的有向边（joke ↔ thread ↔ unfinished）。
- **交叉引用**：关系实体*跨库*指回别的记忆（指回"它诞生的那一刻" = 心流 log / STM 的 turn）。

---

## 2. 镜像实测：5 条现状（2026-05-29 08:4x，隔离探针，零污染）

探针：`JARVIS_MIRROR=1` + 真 `DirectiveRegistry` 代码 + registry 落盘指向系统 temp + `relational_state.json` 只读 + 跑完自删。

| 项 | 镜像实测现状 | 证据（文件:行 / 数字） |
|---|---|---|
| 基线 | 低效 directive（helped=1/not_helped=9）→ `apply_decay` → **priority 5→3** | 强闭环本身工作，OK |
| #1 | Sir 连拒 3 次 → directive `rejected=0` → 衰减后 **active/p5 不变**；对照组 `record_rejection×3` → **state=review** | **`record_rejection` 生产零调用**；reply meta 的 `directive_id`=思考脑 thought.id **非 L2 id** |
| #2 | `"这不是我想要的"/"算了无所谓"/"你这样不太行"` 全判 `engaged`（**5 漏 3**）；沉默→**永不产 `ignored`** | `chat_bypass.py:3187-3194` 写死 14 词 + 二值 |
| #3 | 好 directive（helped=20/not_helped=0）→ 衰减后 **priority 5→5**，只罚不奖 | `jarvis_directives.py:268-357` 无升 priority 路径 |
| #4 edges | **0 / 366** 实体引用另一实体 id | inside_jokes=99 / unspoken_protocols=238 / shared_history_threads=29 |
| #4 交叉引用 | 字段在但**全空 / 从不解引用 / 单向** | `birth_turn_id`/`learned_from_turn_id`/`origin_turn_id` |
| #5 | 顶层 + 实体级**均无**关系级状态（`_meta` 仅落盘元数据） | 无 temperature/trust/rhythm/... |

---

## 3. 五条设计

### #1 — Sir 反应接进 L2 directive 强闭环（精准归因 · Sir 拍板 Option A）

> **★ 实现纠正（2026-05-29 09:15 真读代码）**：本节原稿有两处错误假设，已订正——
> 1. **id 空间错**：reply meta 的 `directive_id` = 思考脑 `thought.id`（`jarvis_inner_thought_daemon.py:5460` 传 `thought.id`），是 **F7 思考脑 directive**，**不是** L2 `DirectiveRegistry` id。照原稿喂 `registry.record_rejection([directive_id])` 会因 `registry.get(thought_id)=None` **静默空转**（`jarvis_directives.py:254-256`）。
> 2. **rejected 闭环本就是死的**：`record_rejection` **生产零调用**（grep 全仓只 test）。`apply_decay` 的 rejected→review/降级（规则 2/3）在生产从未被触发。`jarvis_directives.py:19` 原设计写了"rejected ← 下一轮 Sir correction_loop"，**从没接线**。

**真实 L2 接线（已查证）**：
- `record_fire`：`jarvis_central_nerve.py:3406-3408`（collect 后），并存 `self._l2_last_fired_ids`（:3503）。
- `helped/not_helped`：`jarvis_chat_bypass.py:5655-5665`（DirectiveEvaluator 用 `_l2_last_fired_ids` 异步 LLM 判 compliance）。
- `rejected`：**无生产源**。
- **时序红利**：V6 reaction 块（`chat_bypass.py:3169-3210`）跑在本轮 `_assemble_prompt` **之前**，此刻 `self.jarvis._l2_last_fired_ids` 仍是**上一轮**（产出 Sir 正在反应那条 reply）的 fired L2 ids。

**做什么（精准归因）**：
1. turn 入口 **snapshot** `prev_fired = list(self.jarvis._l2_last_fired_ids)` + `prev_reply`（pending main_reply）+ `sir_input`。
2. **异步**判 `behavioral_reject`（见 #2 `jarvis_reaction_classifier`）：Sir 是否在**纠正 Jarvis 的行为**（≠ 泛泛不满 / 外部情绪）。
3. `behavioral_reject=yes` → `registry.record_rejection(prev_fired)`；`engaged / ignored / 泛泛不满` → **不动 L2**（engaged 的正向留给 #3）。
4. `priority>=10` 红线 directive 由 `apply_decay:293` 既有保护，不受影响。

**为什么不归因全部 fired（噪音治理）**：核心 directive `nudge_agenda_honesty=9 / tool_honesty=9 / continuity=8 / promise_protocol=8 / fuzzy=7` 均 <10 **不受保护**；若用广义不满归因全部 fired，它们会被 Sir 任何情绪误伤衰减。priority 阈值是钝器（同 9 分分不开该不该衰减），故用 **LLM 精准判 behavioral_reject** 作闸——正是原设计 "correction_loop" 本意。

**准则合规**：§1 LLM 判定**异步 fire-and-forget**（仿 DirectiveEvaluator），且只在 vocab 预筛疑似负面时才调 → 不阻 stream、不每轮调；§5 真接死闭环、不假装；§7 review 仍 Sir 拍板 + 红线保护；§8 精准而非阈值钝器。

**工程落点**：`jarvis_chat_bypass.py:3169-3210`（snapshot + 异步提交）、新 `jarvis_reaction_classifier.py`（behavioral_reject 判定 + 回调 `record_rejection`）；`record_rejection` 复用 `jarvis_directives.py:234`。

**testcase**：behavioral_reject×3 → `apply_decay` → state=review；泛泛不满（外部情绪）→ 不调 `record_rejection`；priority>=10 不动；snapshot 时序正确（取上一轮 fired）。

---

### #2 — reaction 分类器：写死 keyword → vocab + 异步 LLM（behavioral_reject）+ ignored

**现状（证据）**：`_neg_kws = ('别提','别说','不要',...)` 14 词写死 `chat_bypass.py:3187-3191`（违反 §6），二值。镜像实测 5 漏 3 语义否定，`ignored` 永不产出（路径要求 `clean_user_input` 非空，:3180）。注释自己写"V2 可接 SkepticismDetector"（:3186）。

**做什么（§6 三维耦合 + §1 异步）**：
1. **持久化**：`memory_pool/reaction_vocab.json` —— 分级 `negative_candidates`（**预筛闸**：疑似负面才触发 LLM）/ `strong_correction` / `soft` / `ignored_after_min`（静默阈值 N）。
2. **新 module `jarvis_reaction_classifier.py`**（仿 DirectiveEvaluator / SoulAlignmentEvaluator）：
   - `classify_fast(text)`：纯 vocab、O(1)，出 `engaged/rejected/ignored`（喂 meta_feedback_loop，热路径用）。
   - `judge_behavioral_reject_async(sir_input, prev_reply, prev_fired_ids)`：**仅当 `classify_fast` 命中 negative_candidates 才提交**；ThreadPoolExecutor + OpenRouter（不抢 google_pool）+ 限速 + 静默失败；LLM 判 `behavioral_reject: yes/no`（Sir 纠正 Jarvis 行为 vs 泛泛/外部）→ yes 回调 `record_rejection(prev_fired_ids)`（= #1）。
3. **CLI**：`scripts/reaction_vocab_dump.py`（list/add/activate/reject）。
4. **L7 reflector**：观测真 correction → propose 新词入 review（可先 stub 挂既有 reflector）。
5. **`ignored` sweep**：`jarvis_inner_thought_daemon` tick 把超过 `ignored_after_min` 仍 `pending` 的 main_reply 标 `ignored`——**仅喂 meta_feedback_loop，不触发 `record_rejection`**（ignored 太弱/歧义，不该衰减 directive）。
6. 替掉 `chat_bypass.py:3187` 的 `_neg_kws`，改用 `classify_fast`。

**做完变成什么**：三值 + 能识别语义/语气否定；#1 拿到**精准** behavioral_reject 信号（非广义关键词）；词表 Sir 不改源码即可调。

**准则合规**：§6 json+CLI+reflector；§1 fast vocab 在热路径、LLM 异步且预筛闸控 → 不每轮调、不阻 stream；§7 新词 review；§8 精准。

**工程落点**：新 `memory_pool/reaction_vocab.json`、新 `jarvis_reaction_classifier.py`、新 `scripts/reaction_vocab_dump.py`、`jarvis_chat_bypass.py:3186-3210`、`jarvis_inner_thought_daemon`（ignored sweep）。

**testcase**：fast 分类语义否定命中；预筛闸（非负面不调 LLM）；LLM mock behavioral_reject yes/no；ignored N 分触发且不 record_rejection；vocab 热加载；OpenRouter 失败静默。

---

### #3 — `apply_decay` 加正向复利（只罚→可奖）

**现状（证据）**：`apply_decay`（`jarvis_directives.py:268-357`）只有降级路径（rejected→review / rej_rate→priority-2 / not_helped→review/priority-2）。镜像实测 helped=20 的好 directive，`priority 5→5` 纹丝不动。→ 违背 §1.1 第 3 性质"复利"（只单向衰减，无正向累积）。

**做什么**：
1. 加对称规则（在既有 5 条规则后）：`helped >= HELPED_PRIORITY_RAISE_MIN` **且** `helped_ratio > HELPED_RATIO_RAISE`（如 0.7）→ `priority = min(PRIORITY_RAISE_CAP, priority+1)`。
2. **防棘轮**：加 `last_priority_raise` 字段 + 冷却（如 24h 最多升 1），避免每 60s tick 反复升；该字段进 `_PERSISTABLE_FIELDS`（`jarvis_directives.py:93-97`）。
3. **红线**：`PRIORITY_RAISE_CAP ≤ 9`（不得升进 priority≥10 的 always-on 红线区，`jarvis_directives.py:293-295`）。
4. **§6 持久化**：阈值进 `memory_pool/directive_decay_config.json` + `scripts/directive_decay_dump.py`（现有阈值是模块常量，本条把"惩罚/奖励平衡"做成 Sir 可调，符合 §6；旧常量保留作 fallback）。

**做完变成什么**：坏的降、好的升。安静好用的 directive 排序上浮、被优先注入 = "复利"补全，剧本会因"演得好"而强化，不只因"演砸了"而退役。

**准则合规**：§6 config + CLI；§7 红线区不可被自动升；§8 对称而非 hot-fix。

**工程落点**：`jarvis_directives.py`（apply_decay + Directive 加字段 + 常量/config loader）、新 config json + CLI。

**testcase**：helped 高 → priority+1 限幅；冷却内不重复升；priority=9 不越红线；config 热加载。

---

### #4a — 交叉引用复活（`*_turn_id` 死指针）

**现状（证据）**：`birth_turn_id`（`jarvis_relational.py:99`）/ `learned_from_turn_id`（:142）/ `origin_turn_id`（:287）已定义、反序列化读回（:981/:997/:1022），但：
- **常空**：主要生产者思考脑建笑话直接 `birth_turn_id=''`（`jarvis_inner_thought_daemon.py:5154`）；只有 Sir CLI 手动 `--turn_id` 才填（`scripts/relational_dump.py:141/168/195`）。
- **从不解引用**：grep 全仓只有 定义/写入/load 三类，无任何 `resolve(turn_id)` 把它捞回 turn。
- **单向**：turn 不知道自己孕育了实体。

**做什么**：
1. **生产时填**：思考脑 / detector 创建实体时把当前 turn_id 写进 `*_turn_id`（`jarvis_inner_thought_daemon.py:5154` 起）。
2. **可解引用**：加 `resolve_turn(turn_id)`，从心流 log / STM 把"它诞生的那一刻"捞回（需 turn-by-id 查询 API；这是本条唯一新建件）。
3. **可选双向回链**：turn 记录侧加 `spawned_relational_ids`（轻量、按需）。
4. `to_prompt_block` 可在合适时把"这个梗生于那天你说 X"一并带出（按 §1 预算，默认不膨胀 prompt，仅高显著度时）。

**做完变成什么**：贾维斯能说"这个梗是那天你说 X 时冒出来的"——交叉引用从死指针变活链接。**成本低**（字段已在，缺填充 + 一个 resolver）。

**准则合规**：§1 resolve 惰性、不进热路径默认装配；§5 真能 trace 回 turn（强化反幻觉）；§6 不新增硬编码。

**工程落点**：`jarvis_relational.py`（resolve_turn）、`jarvis_inner_thought_daemon.py:5154`（填 turn_id）、心流 log / STM 侧 turn 查询 API。

**testcase**：填入 turn_id → resolve 取回 turn；空 turn_id → 优雅返回 None；双向回链一致。

---

### #4b — 关系 edges（实体↔实体）

**现状（证据）**：镜像实测 **0/366** 实体引用另一实体 id；字段名无任何 link/parent/belongs/thread_id 之类外键。4 类是孤立属性袋（实体字段清单见探针输出）。

**做什么**：
1. 加可选外键字段：`InsideJoke.thread_id`（梗属于哪条 thread）、`UnfinishedBusiness.spawned_protocol_id`（未竟事牵出的 protocol）等（保守、按需，不强制）。
2. `to_prompt_block` 按簇组织（同 thread 的梗/highlight 聚一起注入），更连贯。
3. **reflector 自动连边**：L7 看对话流 propose "joke A 属于 thread B" → review → Sir 拍板（不 LLM 自动写）。
4. 边也走 review 制，去重沿用 F5 jaccard 思路。

**做完变成什么**：4 个平铺 list → 带边的图，能顺藤摸瓜（这个梗←那条 thread←那次未竟事），注入更连贯 = §5 升维落地。**成本中**（从无到有加结构 + reflector）。

**准则合规**：§6 边由 reflector propose + Sir review（不硬连）；§7 Sir 拍板；§8 schema 演进非 hack。

**工程落点**：`jarvis_relational.py`（dataclass 加字段 + to_prompt_block 聚簇 + schema_version 升级）、新/扩 reflector。

**testcase**：边 propose→review→activate；聚簇注入顺序；schema 兼容旧 json（无边字段默认空）。

---

### #5 — 二元体对象 `RelationshipState`

**现状（证据）**：镜像实测顶层 + 实体级均无关系级状态字段；最接近的只有 per-item `use_weight`（单个笑话的权重，非关系整体）。"关系"靠散落 list 推断，不是一个有自己轨迹的实体。

**做什么**：
1. 立第一类对象 `RelationshipState`（temperature / trust / rhythm / recent_friction / closeness 等维度，具体维度走 §6 vocab 可加）。
2. **reflector 从对话流更新**（publish 进 SWM，不硬写）：近期摩擦↑→temperature↓；长期稳定协作→trust↑。
3. **持久化 + CLI**：`memory_pool/relationship_state.json` + `scripts/relationship_state_dump.py`（Sir list/调/纠）。
4. **每 tick 注入一行**：主脑/思考脑 prompt 读到关系**整体**温度/节奏，而非只看单条笑话（按 §1 预算，一行摘要）。

**做完变成什么**："关系"成为有自己轨迹的实体——Sir 定义的"生命住在关系里"在工程上立住。主脑据关系整体状态调演法（如近期摩擦多→收敛 nudge）。**成本大**（新对象 + reflector + 注入 + CLI），建议单开一轨。

**准则合规**：§6 三件套（json + CLI + reflector publish-only）；§7 Sir 可纠任何维度；§4 问全过（见 §5 检查表）；§1 仅注入一行摘要。

**工程落点**：新 `jarvis_relationship_state.py` + `memory_pool/relationship_state.json` + `scripts/relationship_state_dump.py` + 注入点（central_nerve 装配 / inner_thought channel view）+ reflector。

**testcase**：维度更新单调性、SWM publish、CLI 改、prompt 一行注入、持久化往返。

---

## 4. ROI + 顺序 + 依赖

| 顺序 | 条目 | 成本 | 价值 | 依赖 |
|---|---|---|---|---|
| 1 | **#1 + #2（一对）** | 小 | 最高：头号 meta-loop 弱→强 | #1 的 `ignored` 依赖 #2 |
| 2 | **#3** | 中 | 复利补全，坏降好升 | 独立 |
| 3 | **#4a** | 低 | 交叉引用复活（trace 回诞生时刻） | 需 turn 查询 API |
| 4 | **#4b** | 中 | list→graph 升维 | 建议在 #4a 后 |
| 5 | **#5** | 大 | 关系成第一类实体（单开一轨） | 独立，量大 |

**建议先落 #1+#2**：最小改动，把"知道自己演过什么剧本的演员"真正接通。

---

## 5. 准则 6 — 新 module 4 问筛查（#5 为例，全 Yes 才加）

| # | 问 | #5 RelationshipState |
|---|---|---|
| 1 | 数据 publish 进 SWM? | ✅ reflector publish 维度变化进 SWM |
| 2 | 决策让 LLM 做? | ✅ python 只 sense + publish，调演法由主脑读关系状态自决 |
| 3 | 配置持久化 + CLI? | ✅ relationship_state.json + dump CLI |
| 4 | 和已有 module 正交? | ✅ relational 管"具体梗/协议"，#5 管"关系整体"，不重叠 |

#1/#2/#3/#4a/#4b 同理过筛（均不新增独立 sentinel，多为扩既有 module）。

---

## 6. 红线 / 不做什么

- **不碰** INTEGRITY / commitment / safety vocab（复用 E5 `protected_vocab` 红线，`jarvis_inner_thought_daemon.py` `_check_red_line_vocab_adjustment`）。
- **不破** priority≥10 always-on 红线 directive（#1 不误伤、#3 不越 cap）。
- **不破** §1 TTFT：#1 O(1)、#2 regex 先行 LLM 兜底、#4a 惰性 resolve、#5 仅一行注入。
- **不 LLM 自动写关系**：#4b 边 / #5 维度 / #2 新词全走 review + Sir 拍板（§7）。
- **不 hot-fix**：#3 走对称规则 + config，不加 hard cooldown 糖衣（§8）。

---

## 7. 验收（每条镜像可复验）

- #1：镜像 rejected×3 → `apply_decay` → state=review（对照现状 active）。
- #2：镜像喂语义否定 → 判 rejected；静默 N 分钟 → 产 `ignored`。
- #3：镜像 helped 高 → priority+1（限幅、冷却、不越红线）。
- #4a：镜像 resolve_turn(birth_turn_id) → 取回 turn。
- #4b：镜像实体加边 → 0/366 变 N/366；聚簇注入。
- #5：镜像 reflector 更新 → relationship_state.json 维度变化 + 一行注入。
- 全程：回归 pytest 绿 + 镜像零污染 `memory_pool`。

---

## 8. 与姊妹篇的钩子

- §1.1 闭环尺 = `JARVIS_EMERGENCE_AND_LOOPS.md` §3 原文。
- §1.2 升维六维 = 同篇 §5。
- #1/#2/#3 实现"强闭环"，#4/#5 实现"符号内升维"——合起来是 Sir §0 那句"剧本的设计来自闭环"在工程上的两条腿。

---

## 9. 实施记录（2026-05-29，#1+#2 + 清理）

### 9.1 真读代码后的关键纠正（设计 doc §假设修正）

- **`directive_id` ≠ L2 registry id**：reply meta 的 `directive_id` = 思考脑 `thought.id`（`inner_thought_daemon` 传），非 L2 `DirectiveRegistry` id。直接喂 registry = 空转。
- **`record_rejection` 生产零调用**：`apply_decay` 的 rejected→review/降级是死路径，从未接线。
- **L2 真接线**：`record_fire` 在 `central_nerve`（存 `_l2_last_fired_ids`）；`helped` 在 `chat_bypass`（`DirectiveEvaluator` 用 `_l2_last_fired_ids`）。V6 reaction 块跑在本轮装配前，此刻 `_l2_last_fired_ids` = 上一轮（产出 Sir 正反应那条 reply）的。

### 9.2 #2 reaction 精准化（已实现）

- `memory_pool/reaction_vocab.json`：`negative_candidates` / `strong_correction` / `soft` / `ignored_after_min`（准则 6 持久化）。
- `jarvis_reaction_classifier.py`：`classify_fast`（热路径 O(1) vocab）+ `judge_behavioral_reject_async`（异步 fire-and-forget LLM 判 behavioral_reject，仅在 vocab 预筛出疑似负面时才调，准则 1 不每轮调）+ rate limit + fallback。
- `scripts/reaction_vocab_dump.py`：list/show/add/remove/history/review CLI（准则 6 可改）。
- `jarvis_chat_bypass.py` V6 块：替换硬编码 `_neg_kws` 为 classifier 快路 + 异步判。
- **ignored sweep**：`inner_voice_track.mark_stale_pending_main_replies_ignored(older_than_min, max_age_min)` + `inner_thought_daemon._sweep_ignored_main_replies`（每 tick 顶跑，纯 Python 不烧 token）：pending main_reply 静默老于 `ignored_after_min` → 标 `ignored`，**仅喂 V6 meta_feedback_loop，不 record_rejection**。

### 9.3 #1 精准归因（已实现）

- turn 入口 snapshot 上一轮 `_l2_last_fired_ids` + `prev_reply` excerpt。
- 异步 `behavioral_reject=yes` → `registry.record_rejection(snapshot_ids)`。`engaged`/`ignored` 不动 L2（engaged 留给 #3 正向复利）。
- `priority≥10` 红线 directive 仍受 `apply_decay` 保护。

### 9.4 测试 + 回归

- `tests/_test_sir_20260529_0925_reaction_classifier_record_rejection.py`：**25/25**（classify_fast / vocab CLI / async judge record_rejection / 预筛闸 / priority≥10 红线 / ignored sweep ×4）。
- 回归 **176 passed / 0 failed**：reaction(25) + directive/evaluator/V6(86) + inner_thought tick/phase5/fix63/fix3/fix11(65)。

### 9.5 清理记录（第三步，Sir 关机后执行，全备份可回滚）

> 调查工具：模块级只读探针 `_cleanup_survey.py`（已自删）。执行：`_cleanup_apply.py`（已自删）。备份：`_legacy/data_migration_backup/20260529_094405_cleanup/`（relational_state / relational_review / inner_voice_24h / inner_thoughts 四文件）。

| Tier | 动作 | 结果 |
|---|---|---|
| 1 | 硬删 review backlog（未过审 inner_thought 过度提议） | 删 **158 协议 + 28 梗**，review 队列 → **0** |
| 2 | active 协议保守去重（Jaccard≥0.7） | **0** 条字面近义（active 字面各异），列全 29 条供 Sir 语义判断 |
| 3 | `inner_voice_24h.jsonl` truncate 到真 24h | 删 **781 行** >24h（留 1490；该文件不在 jsonl_rotator 防爆列表） |

- **不碰** `inner_thoughts.jsonl`：WRC 需 7d outcome（文件仅 4d 数据）+ 已在 `jarvis_jsonl_rotator` 防爆列表。
- AFTER：protocols active=29/review=0/archived=52；jokes active=35/review=0/archived=36；threads 不变。重 load 校验通过。

### 9.6 根因发现（留后续，非本次清理）

29 条 active 协议有 **~5-6 个语义主题反复**（少正式/反 nudge/喝水/integrity/收尾告别），字面各异故 Jaccard 去不掉。**根因**：思考脑 propose 协议时 (a) dedup（F5 jaccard）只挡字面、挡不住语义近义；(b) 提议时没"看见"已有协议清单。建议单开一修：**语义去重**（embedding/LLM）+ **提议前注入已有协议清单**（让思考脑知道"这条我已经提过"）。这是 `思考脑不成熟` 的工程真因。

### 9.7 #3 正向复利（已实现）

- `memory_pool/directive_reinforcement_config.json`：`enabled` / `min_fired` / `min_helped` / `min_helped_ratio` / `max_rejected_rate` / `cooldown_hours` / `priority_step` / `max_priority`（默认 9，不越 priority≥10 红线）。
- `scripts/directive_reinforcement_dump.py`：list/set/enable/disable/runtime CLI（Sir 不改源码即可调）。
- `jarvis_directives.py`：`last_reinforced` 持久化 + `_load_reinforcement_config()` + `apply_decay()` 正向规则：
  - `helped` 足够、`helped/(helped+not_helped)` 高、`rejected/fired` 低、未到 `not_helped` 降级阈值、冷却已过 → `priority += priority_step`。
  - `priority` 自动升权 cap 到 `max_priority<=9`；`priority>=10` critical directive 仍先 `continue`，完全不被自动正/负向改。
  - mixed signal（`not_helped >= NOT_HELPED_PRIORITY_DROP`）不奖励，只是不因高 helped ratio 被误降。
- 测试：`tests/_test_sir_20260529_0955_directive_positive_reinforcement.py` 覆盖 boost / cooldown / cap / redline / disabled / mixed-signal no boost / persist-load。目标回归 **85 passed / 0 failed**。

### 9.8 #4a 交叉引用复活（已实现）

- `jarvis_inner_thought_daemon.py`：思考脑创建 relational entity 时写入当前 `TraceContext.get_turn_id()`：
  - `InsideJoke.birth_turn_id`
  - `UnspokenProtocol.learned_from_turn_id`
- `jarvis_lineage.py`：新增 `LineageTracer.find_decisions_by_turn(turn_id)`，惰性扫描 `lineage.jsonl` 的 decision record。
- `jarvis_relational.py`：新增 `RelationalStateStore.resolve_turn(turn_id)`，封装 lineage resolver；空 id / 找不到均优雅返回 `not_found=True`。
- 边界：resolver 不进 prompt 装配热路径；只给 CLI/debug/高显著度引用使用，避免 prompt 膨胀。
- 测试：`tests/_test_sir_20260529_1000_relational_turn_cross_reference.py` 覆盖 turn lookup / empty id / resolver wrapper / thought proposal 写 turn id。相关回归 **61 passed / 0 failed**。

### 9.9 #4b list→graph edges（已实现）

- `jarvis_relational.py`：新增一等 `RelationalEdge`：
  - `from_kind/from_id` → `to_kind/to_id`
  - `relation_type` / `weight` / `evidence_turn_id` / `note`
  - `state` / `source` / `created_at` / `last_referenced`
- `RelationalStateStore`：新增 `add_edge()` / `get_edge()` / `list_edges()` / `list_edges_for()` / `archive_edge()`。
- 持久化：`relational_edges` 存入同一个 `relational_state.json`，`schema_version=3`；`load()` 保持旧四键返回兼容，同时恢复 edges。
- Prompt：`to_prompt_block(..., top_edges=0)` 默认不注入 edges，避免热路径 prompt 膨胀；显式 `top_edges>0` 时渲染 `[RELATIONAL LINKS]`，并受 `max_chars` 截断保护。
- Dump：`dump_human()` 显示 edges count 与 edge 列表。
- 测试：`tests/_test_sir_20260529_1008_relational_graph_edges.py` 覆盖 CRUD / archive / persist-load / prompt default-off / prompt explicit-on / dump。目标测试+关键回归 **21 passed / 0 failed**。

### 9.10 #5 RelationshipState 第一类实体（base 已实现）

- `jarvis_relationship_state.py`：新增 `RelationshipState` / `RelationshipStateStore`。
  - 维度：`temperature` / `trust` / `rhythm` / `recent_friction` / `closeness`。
  - 边界：所有维度 clamp 到 `0.0..1.0`；`to_prompt_line()` 永远一行且受 `max_chars` 限制。
  - 更新：`set_dimension()` 持久化并 publish `relationship_state_updated` 到 SWM；不自动决策主脑行为。
- `memory_pool/relationship_state.json`：默认状态文件落地，Sir 可直接看/改。
- `scripts/relationship_state_dump.py`：CLI 支持 `list` / `set <dimension> <value> --note ...`，并支持 `--path` 用于镜像/测试隔离。
- Review flow：`propose` 只写 `review[]` 并 publish `relationship_state_proposed`，不改 active 维度；`approve` 才应用，`reject` 只标记 rejected。
- `jarvis_relationship_reflector.py`：新增 propose-only reflector helper；可从 STM/LLM JSON 生成 review proposal，但不自动改 active RelationshipState，也不默认启动 daemon。
- `jarvis_inner_thought_daemon.py`：预留低频 hook，读取 `memory_pool/relationship_reflector_config.json`；默认 `enabled=false/use_llm=false`，因此不增加后台 token 成本。
- `jarvis_central_nerve.py`：Layer 2 relational block 前注入一行 `RELATIONSHIP STATE: ...`；无 relational_state 时也可单独注入该行。
- 暂未做：默认启动后台 daemon。原因：避免额外 token 与自动写关系；现阶段为手动/测试/后续调度入口。
- 测试：`tests/_test_sir_20260529_1023_relationship_state_base.py` + `tests/_test_sir_20260529_1033_relationship_reflector.py` + `tests/_test_sir_20260529_1043_relationship_reflector_inner_hook.py` 覆盖 persistence / clamp / unknown dimension reject / central_nerve 一行注入 / CLI temp path / proposal approve/reject / reflector forced JSON propose-only / inner_thought hook 默认关闭。镜像 CLI smoke 使用 `JARVIS_MIRROR=1` + temp file。
