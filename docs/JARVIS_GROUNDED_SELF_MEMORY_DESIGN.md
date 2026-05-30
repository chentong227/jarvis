# JARVIS Grounded Self-Memory & Integrity Unification — Design

> **状态**: design 草案 / 待 Sir 拍定。**未动代码。**
> **作者**: Sir + Cascade，2026-05-30 21:00– 对话蒸馏。
> **缘起**: Sir 两天没开机，Jarvis 没有"他没开着"的时间概念 → 升级为 meta 反问
> "要让他记得什么就得显式编程加能力，怎么可能覆盖所有？高频思考脑能不能自我迭代自我理解？"
> **姊妹篇**: `docs/JARVIS_EMERGENCE_AND_LOOPS.md`（函数→过程 / 弱强闭环 / ROI 杠杆）、
> `docs/JARVIS_THINKING_BRAIN_GOVERNOR_DESIGN.md`、`docs/JARVIS_INTEGRITY_STACK.md`、
> `docs/JARVIS_SOUL_DRIVE.md`（Layer 0-5 + C1 `lived_experience_stream`）。
> **本设计不重发明 Layer 0**；它是把已立的概念接成一条可自查的通用底座。

---

## 0. TL;DR — 一句话

> **不造新脑、不堆新功能。给高频思考脑装上"会回忆、会沉淀、不撒谎"的一块自我记忆——
> 它同时是连续存在的河床、自主理解的地基，也是言出必行缺的那块 evidence 源。**

四个"随口"（随口的时间 / 随口的记忆 / 随口的好久没见 / 随口的昨天那件事）和言出必行的
post-hoc 幻觉，**是同一块缺失从两面看**：缺一个**接地的、可被思考脑自查的、会巩固的统一记忆**。

---

## 1. 诊断 — 两个看似不同的问题，同一个根

### 1.1 自我记忆侧（连续存在 + 自主理解）

| 缺口 | 现状（已核源码） |
|---|---|
| 思考脑**只写不读** | `jarvis_inner_thought_daemon._maybe_archive_to_hippocampus` 只写海马（且仅 B 类高 sal），tick 中**无任何 recall 路径**。只看预先塞好的固定 24h 窗口 |
| 窗口是**时间界**不是**相关性界** | 离线两天 → 窗口空 → 退化失忆。"昨天那件事"靠 23:00 硬编码 `yesterday_recap`，离线就没有 |
| 离线 gap 是**死数据** | `cold_starts.jsonl` 的 `prev_cold_start_age_s` 算出来全仓零消费者（`daemon:7475` 只写不读）；`build_lifetime_block` 跨 session 维度只报"次数+总跨度"，不报"我离线了多久" |
| 只能**填预设表** | 可持久化的只有 concern/directive/inside_joke/milestone/let_go，"随口的记忆"无处可记 |

### 1.2 言出必行侧（同一个根）

ClaimTracer（L4）核完源码，**得了和"逐个 hand-code 能力"一样的病**：

| 病灶 | 证据（`jarvis_claim_tracer.py`） |
|---|---|
| **正则枚举**（同款硬编码病） | `extract_claims` 一堆 regex；历史在不停补：加"安排/计划"、加英文单词数字"eight-hour"…… 每个新幻觉形式 → 加一条 regex。**和"要让他记得什么就显式编程"是同一个病** |
| **post-hoc**（说完才审） | fire-and-forget 异步，假话已经到 Sir 眼前；只能靠下轮 `[INTEGRITY ALERT]` 撤回 → 撤回又产生新 claim → 死循环。大量代码是这个的创可贴（retract-skip / staleness / 空 turn_id 过滤 / meta skip_alert / alert_injected tracker） |
| **evidence 饿死** | `trace_to_evidence` 只查 tool_results / STM 末 10 / system_clock / ltm 串 / promise tag。④Recall 类（"你昨天提过 X"）**没有真索引可命中** → 要么 false-positive 要么 false-negative |
| **接地割裂** | audit 条目只存 claim 文本，不链 `jarvis_lineage` 的 `evidence_id`。两套接地（lineage vs ClaimTracer）不通 |

### 1.3 收口

> 自我记忆缺的"河床/可自查"，和言出必行缺的"真 evidence 源"，**是同一块东西**。
> 建一次，两边都补。这是准则 8（优雅可持续 > 最简）+ 准则 6 四问 #4（正交不重复）的杠杆点。

---

## 2. 地基三层 + 三器官

### 2.1 地基（器官长在它上面，自底向上）

| 层 | 地基 | 没它的后果 | 现状 |
|---|---|---|---|
| **L1 接地 (grounding/lineage)** | 自我表征每条 trace 到 evidence；召回带 provenance；结论可被推翻 | 自我回忆+因果闭合 = 把幻觉复利进门控态，直接撞言出必行 | ClaimTracer 只接地回复、不接地内部认知；对自我 ≈0 |
| **L2 统一可寻址的自我** | 脑子能一次跨源查"关于 X 我知道/感到/记得什么"（thoughts+concerns+relational+海马） | 脑子无法咨询自己 = 无从理解 | `MemoryHub.query`/`to_prompt_block`（M2 已建）主脑在用，**思考脑没接** ≈30% |
| **L3 因果闭合 (causal closure)** | 结论 mutate"会 gate 下一步"的结构化态，且选择性+带评价 | 理解只是漂亮文字，被 30K prompt 冲掉、不复利 | 仅 governor `let_go`/`jaccard` 是真强闭环 ≈15% |

### 2.2 三器官（坐在地基上）

1. **自我回忆 (recall as an action)** — 拱心石，唯一确证缺失。←L2+L1
2. **自写记忆 (schema-free note-to-self)** — L2 的延伸，配 learned-salience。
3. **强闭环 (后果 mutate 门控态)** — 就是 L3 在动。

### 2.3 4C 依赖链（下层托上层）

> **connectivity → continuity → consolidation → comprehension**
> 河得先流（持久）→ 才谈接续（continuity）→ 才谈结河床（consolidation/巩固）→
> 脑子才能从河床取水理解（comprehension/自查）。
> 现在卡在第三步（河床没建），所以第四步（自查）没地基。

---

## 3. 言出必行的优化（同一底座的 integrity 面）

不是另起项目，是同一 grounding 底座照进 ClaimTracer：

| # | 优化 | 做法 | 治的病 |
|---|---|---|---|
| **I1 共享接地源** | 召回结果（带 `evidence_id`）作为 ④Recall/③State claim 的 evidence；ClaimTracer 读 `MemoryHub` 而非只 STM 末 10 | evidence 饿死 |
| **I2 枚举→语义** | 正则保留作**廉价首过**；语义判交给思考脑（后台、非 TTFT，已读 reply via meta_self_check/preflight）"我这句真有依据吗" | 正则无限增长（同款硬编码病）；准则 6 信任 LLM |
| **I3 预防 > 拦截** | 召回**预取**（F1 热路径）在主脑开口**前**把候选+证据塞进 prompt → 从源头少编造 → 少 post-hoc 撤回 → 逐步退役死循环创可贴 | post-hoc 根病（且不加同步 gate，守 TTFT<5s） |
| **I4 lineage 归一** | ClaimTracer audit 条目链 `jarvis_lineage` 的 `evidence_id`（M1 已建），一套接地不是两套 | 接地割裂 |

> **答 Sir："言出必行有没有优化可行之处" → 有，而且最优雅的优化不是给它加 regex/加同步 gate，
> 是把它的 evidence 源换成这块"接地自我记忆"，并把"说之前先接地"做厚（I3），让它从源头不撒谎。**

---

## 4. 决策状态

| 岔路 | 决定 |
|---|---|
| **F1 召回触发** | ✅ **混合**（Sir 拍）：热路径（主脑回复 TTFT<5s）只廉价预取（embedding→top-k 候选，0 额外 LLM）；后台思考脑 tick 允许脑子自发深召回（`<RECALL>` tag） |
| **F3 接地严格度** | ✅ **允许"模糊记得"**（Sir 拍）：有 trace→可确信引用；无 trace/低置信→必须标"我模糊记得…"，**禁止裸断言** |
| F2 召回形态 | （推荐）给带证据的候选，非结论；脑子自决用不用 |
| F4 河床形态 | （推荐）线程为主+实体索引（贴合"昨天那件事/你记得我那个"的查询形态） |
| F5 巩固节奏 | （推荐）线程沉寂触发 + 每日一扫 + 冷启卷上一段 session |
| F6 第一个强闭环 | （推荐）召回→注意力：recall 到"线程仍 open + Sir 碰相关"→ mutate 线程 salience → 下 tick 优先 |

---

## 5. 落地阶段（每步独立可测 + Sir 真机验收，复用现有不造新存储）

| 阶段 | 做什么 | 主要文件（复用） | 准则 6 | Sir 验收 |
|---|---|---|---|---|
| **P0 离线 gap 底座** | cold_start 数据卫生（gate 真 session + dedup）；daemon 心跳持久 `last_alive` → 算真 `dark_gap`；`build_lifetime_block` 跨 session 维度 surface "离线了 N"（中性事实，措辞留主脑） | `jarvis_inner_thought_daemon.py` + `jarvis_lifetime_block_vocab.json`（加阈值 `dark_gap_min_surface_s`） | 阈值/措辞 vocab；措辞主脑涌现 | 离线>阈值重启，主脑自然有"久违"感，无硬编码 welcome |
| **P1 recall 拱心石（最高 ROI）** | 思考脑接 `MemoryHub.query`（M2 已建）+ recall API；热路径廉价预取候选（带 `evidence_id`）；接地纪律（F3 允许 hedge）；**I1+I4**：ClaimTracer ④/③ 查同一召回源 + audit 链 `evidence_id` | `MemoryHub` / `jarvis_hippocampus`(`add_memory` 已用) / `jarvis_lineage`(M1) / `jarvis_claim_tracer.py` / `jarvis_inner_thought_daemon.py` | 召回阈值/topk vocab；触发主脑/思考脑自决 | "随口的记忆/昨天那件事"先在现有记忆上召回即可命中；ClaimTracer 不再 false-positive ④Recall |
| **P2 河床/巩固** | 巩固 reflector（泛化 `yesterday_recap`，在 tick 循环）→ 线程索引 `memory_pool/self_threads.json`（线程=跨时间话题：running summary/last_touched/salience/status/回链 evidence）；**遗忘**（salience 衰减 + 热/温/冷分层，不删除） | 新 reflector method（daemon 内）+ `self_threads.json` + CLI `scripts/self_threads_dump.py` | 线程/衰减阈值 vocab；巩固由 LLM 写不模板 | 离线两天醒来能接上未结线程；老线程降权不刷屏 |
| **P3 第一个强闭环** | F6 召回→注意力：recall 结论 mutate 线程 salience → gate 下 tick channel view | `jarvis_inner_thought_daemon.py`（channel view 装配）+ `self_threads.json` | 复用 governor 强闭环范式 | 思考脑被相关话题"勾起"后真优先该线程（log 可见 salience 变） |
| **P4 自写记忆** | schema-free note-to-self（脑子任意写+salience）；纳入召回 | `self_threads.json` 扩 free-note kind 或新 `self_notes.jsonl` + CLI | vocab + CLI | 脑子自记的随口事后续可召回 |

> **为什么 P1 在 P2 前**：recall 是唯一确证缺失器官且近乎接线（机器都在）。先在现有扁平+海马记忆上召回，
> 最便宜验证整套论点；若已明显改善"随口四问"，再投资把河床做厚（P2）；若没改善，省下 P2。准则 8 增量优雅。

---

## 6. 接地红线（不可谈，与召回同批上线）

1. **召回必带 provenance**：每条召回项链 `turn_id` / `evidence_id` / `ts`；巩固条目回链原始流（lossy-but-traceable）。
2. **F3 hedge 边界**：无 trace/低置信 → 只能"我模糊记得…"，**禁止裸断言**。有 trace 才可确信引用。
3. **召回幻觉是 P1 最大风险**：若召回伪造，ClaimTracer 会拿假记忆"验证"假 claim → 复利。故红线 1+2 必须**和召回同时**，不能后补。
4. **遗忘同批**（P2 内）：salience 衰减 + 分层，不删除（删了丢 provenance）；let_go = 显式遗忘。

---

## 7. 准则 6 — 四问筛查

| # | 问 | 答 |
|---|---|---|
| 1 数据 publish 进 SWM? | ✅ 召回触发/结果、巩固事件、dark_gap 全 publish；接地走 `jarvis_lineage` evidence_chain |
| 2 决策让 LLM 做? | ✅ 召回用不用、记什么、放下什么、巩固成啥都主脑/思考脑判；python 只 enforce 阈值+接地红线 |
| 3 持久化 + CLI? | ✅ vocab（gap/召回/线程/衰减阈值）+ `self_threads.json` + 配套 `scripts/*_dump.py` |
| 4 和已有正交? | ✅ **不造新存储**：复用海马（存）+ MemoryHub（查）+ lineage（接地）+ governor（强闭环）+ 思考脑 tick（引擎）。线程索引是河床结构，指向海马/心流的原始水 |

---

## 8. 风险与代价（先说断 / 准则 5 + 准则 1）

- **成本/延迟**：预取廉价（embedding）；脑子自发召回 + 巩固是 LLM 调用 → 后台+限频，**绝不进热回复路径**（守 TTFT<5s）。
- **幻觉记忆**：P1 最大风险 → 接地红线（§6）硬绑。
- **漂移/噪声**：遗忘（P2 内）必须和巩固同批，不能拖。
- **有损投影天花板**（EMERGENCE §4.2/§6）：再厚的符号记忆也是高维心智的有损投影。唯一真出口是远期小 adapter（把 Sir 学进参数），**本设计不碰**——敞着那点形而上残余。

---

## 9. 不做什么（scope 边界）

- ❌ 不造新记忆 god-object（复用海马/Hub/lineage）。
- ❌ 不加同步 pre-emit gate（撞 TTFT）；预防靠"说前先接地"（I3）。
- ❌ 不碰权重/adapter（远期，超本设计）。
- ❌ 不一次重写 ClaimTracer；I1-I4 增量接，正则保留作廉价首过。

---

*待 Sir 就 F2/F4/F5/F6 给态度 + P0 是否先开工 → 拍定后逐阶段 commit（每阶段独立可 revert + 真机验收）。*
