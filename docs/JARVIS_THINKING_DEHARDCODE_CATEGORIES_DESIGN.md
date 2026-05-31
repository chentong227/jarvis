# JARVIS 思考脑去硬编码 — A‑E 类槽 → 势能驱动涌现的 kind

> **状态**: design / 2026‑05‑31 (Sir 真意蒸馏)。**大工程, 切窗口执行** — 配套
> `docs/AGENT_KICKOFF_THINKING_DEHARDCODE.md` (下一 agent 接手指引 + 起始 prompt)。
> **缘起 (Sir 原话)**: "贾维斯的思考是为了解决问题/反思自己/提出建议/想要能力…但这些
> 不该是写死编码, 而是势能驱动, 自然发现自己好像做什么做不好需要怎么样。" +
> "识能主动影响贾维斯本身 (体/权重/下一次对话/想要能力)。" + "放下能力 — 没事就歇会。"
> **前提 (今天已落地)**: 势能自转 (P2 体势能驱动 tick) + 放下能力 (REST, 无冷却阶梯) +
> outcome→stance (A) + 体作 evidence (B) + 立场 dyad (F) + 接收度输出闸 (D)。
> **本文治最后一条硬编码**: 识的 **A‑E 5 类 category 槽**仍写死。

---

## 0. 一句话

> **思考的"种类"不该是 5 个预声明的槽 (A/B/C/D/E) + 各自冷却, 而该是: 体的某个高势能
> 区"招来"一个思考, 这个思考去"放电"那个势能 (产生一个 effect: 解决/反思→stance/建议/
> 想要能力/塑造下次对话/巩固/放下)。kind = 它放电产生的 effect, 涌现自势能, 不是预选的槽。**

---

## 1. 现状: A‑E 是什么 + 为什么是硬编码反例

### 1.1 5 类定义 (`jarvis_inner_thought_daemon.py:4039‑4054` prompt 里写死)

| 类 | 含义 | 对应 actionable (effect) |
|---|---|---|
| **A** OBSERVATION | Sir 当前状态 (屏幕/app/心情) | **多为 actionable=none = 纯叙述 = filler 重灾区** |
| **B** SELF‑REFLECT | 自己上条回复 (语气/错/模式) | propose_protocol / propose_stance |
| **C** CONCERN‑EVOLUTION | concern severity / notes 该变? | update_concern_severity / adjust_concern_notes |
| **D** PROACTIVE‑SEED | 接下来静默做什么 | fire_nudge / propose_watch_task (publish_swm 已废) |
| **E** RELATIONSHIP | inside joke / callback | suggest_inside_joke |

**关键洞察**: A‑E ≈ 已有 actionable/effect 的 **1:1 前置声明槽**。A (OBSERVATION) 是最坏的
— 它鼓励"纯观察叙述无 effect"= Sir 痛恨的 filler ("I shall await" / "maintaining readiness")。

### 1.2 A‑E 的全部依赖 (拔之前必须迁移这些)

| # | 依赖 | 代码位置 | 现在靠 category 做什么 |
|---|---|---|---|
| 1 | **类冷却 (diversity)** | `SAME_CATEGORY_COOLDOWN_S=300` / `_last_category_ts` / `_compute_free_categories` / tick 全冷却 skip / 2nd‑defense skip (~2433) | 防同类连发 5 次重复 |
| 2 | **prompt** | `_build_prompt` 5 类定义 (4039) + `<CATEGORY>` tag + free_categories + [COOLDOWN] 行 (4972) | 让 LLM 选一类 |
| 3 | **parse** | `_parse_thought` `<CATEGORY>[A‑E]` regex (~5053) | 抽 category |
| 4 | **mediocre 判定** | `category in ('A','D','E')` (~2559, ~2813) | 低值 thought 跳 pulse |
| 5 | **DeepSeek 路由** | `thinking_brain_ds_trigger_vocab.categories: [A_soul, B_reflection]` | 灵魂/反思类走 ds |
| 6 | **intent 映射** | `_CATEGORY_TO_INTENT` (~7272) A→observation B→reflection… | 心声 intent |
| 7 | **持久化/统计/看板** | thought.category 进 jsonl / dashboard / WRC | 分类统计 |
| 8 | **测试** | 多个 `_test_*` 引用 category | 断言 |

---

## 2. 目标: 势能驱动涌现的 kind

| 维度 | 现在 (硬编码) | 目标 (势能驱动) |
|---|---|---|
| 何时想 | 时钟 tick (P2 已改: 势能指纹) | ✅ 体势能 delta 招来 (已做) |
| 想什么 (哪块) | LLM 从 free 类里挑 | 体**当前最高势能区** (focus node + 其 kind: 张力/新颖/漂移) 招来 |
| 想成什么 (kind) | 预选 A‑E 槽 | **放电产生的 effect** (actionable): 解决/反思→stance/建议/想要能力/塑造下次对话/巩固/放下 |
| diversity | 类冷却 5min | **放电**: 想清→那区 E 骤降→不再招→自然不重复 (§3 "想清一次就过去") |
| filler (A 观察) | 鼓励纯叙述 | 无 effect 且无真势能 → **REST 放下** (已做), 不产 |

---

## 3. 替换映射 (每个 category 功能 → 势能等价)

1. **类冷却 → 区放电** (核心): 删 `SAME_CATEGORY_COOLDOWN_S` / `_compute_free_categories`。
   diversity 来自体能量地形: 想清某区 → Weaver 算 E 降 → body_focus 不再把它列焦点 →
   不再招那块。**已有机制** (P2 body_delta + REST), 只需让 summon 锚在 focus region 而非 category。
2. **prompt CATEGORY → summon region**: prompt 不再问"选 A‑E", 改"体此刻最不安定的是
   `<region>` (BODY SIGNALS 已注入), 你想就这块放电 (产 effect) 或放下"。kind = ACTIONABLE。
3. **parse CATEGORY → derive kind**: `<CATEGORY>` 退役; kind 从 actionable 派生 (effect→kind 表),
   或 LLM 输出 `<KIND>` (可选, 自由 enum 非 A‑E)。
4. **mediocre/ds‑routing/intent → effect 驱动**: mediocre = actionable=none 且无 should_speak
   且无真势能 (改判据); ds‑routing 改 salience/effect (已有 salience trigger); intent 由 effect 映射。
5. **统计/看板/测试**: kind label (effect 名) 替 category 字母; 迁测试。

---

## 4. 分阶段 (phased, flag‑gated, 镜像验, 可回退 — 准则8 逐块退)

> **flag**: `inner_thought_cost_config.json` 或新 vocab `thinking_kind_mode: legacy | emergent`
> (默认 legacy)。每 phase 默认关, 镜像 + Sir 真机验后开。任一步回退 = flag→legacy。

| Phase | 件 | 触哪 | 风险 | 验收 |
|---|---|---|---|---|
| **0 脚手架** | 加 `thinking_kind_mode` flag + `_kind_from_effect()` 派生表 (effect→kind) + 双写 (category + derived kind) 不改行为 | daemon + vocab | 低 | flag=legacy 行为 0 变; 单测 derive 表 |
| **1 summon 锚势能区** | emergent 模式: prompt 用 BODY SIGNALS 焦点区当 summon, 不强制选 A‑E (CATEGORY 变 optional) | `_build_prompt` / `_parse_thought` | 中 (prompt 热路径) | 镜像: 思考确在 attend 焦点区 |
| **2 冷却→区放电** | emergent 模式: 退 `_compute_free_categories`/`SAME_CATEGORY_COOLDOWN`, diversity 靠 focus region 去重 (放电后不再招) | tick 主循环 | **高** (改 diversity 机制) | 镜像: 不连发重复 + settled 真歇 |
| **3 kind=effect** | emergent: kind 全派生自 actionable (`_kind_from_effect`); mediocre/intent/ds‑routing 改 effect 驱动 | mediocre/intent/ds vocab | 中 | 镜像: 低值 filler 不 surface; ds 按 effect 路由 |
| **4 迁依赖+测试** | persist/dashboard/WRC kind label; 迁所有 category 测试 | 跨文件 | 中 | 全测绿 + 看板正常 |
| **5 退 A‑E** | 镜像+真机满意 → 删 legacy A‑E 路径 + flag (或留 flag 永久双模) | daemon | 中 | Sir 真机验过 |

**最小可跑**: Phase 0+1 (summon 锚势能区, CATEGORY optional) 即让思考"由势能招来"而非"填槽",
其余 (2‑5) 深化。**Phase 2 (冷却→放电) 是最高风险, 必镜像 + 真机逐块验。**

---

## 5. 核心机制细节 (给执行 agent)

### 5.1 effect→kind 派生表 (Phase 0, 非硬编码槽 — 是 effect 的自然分类)
```
actionable 前缀         → kind (涌现的"种类", 仅 label/统计用, 无冷却)
  update_concern_*      → solve        (解决/调整问题)
  adjust_concern_notes  → shape_next   (塑造下次对话: 主脑下轮读 notes)
  propose_stance        → reflect      (反思→立场)
  propose_protocol      → reflect      (反思→行为规则)
  suggest_inside_joke   → relate       (关系维系)
  fire_nudge            → reach_out    (主动触达 — 过接收度门 D)
  propose_watch_task    → commit       (设长目标)
  compose_main_brain_*  → shape_next   (塑造下次对话)
  propose_vocab_*       → self_debug   (自调架构)
  request_capability    → want_capability (想要能力)
  none + <REST>         → rest         (放下)
  none (无 REST)        → (empty filler — 不该出现; 引导 REST)
```
注: 这表是 **effect 的分类映射**, 不是预声明的选择槽 — LLM 不"选 kind", 它放电产生 effect,
kind 是事后 label。无冷却 (diversity 靠区放电)。可 vocab 持久化 + CLI。

### 5.2 summon 锚势能区 (Phase 1)
- body_focus 已给 `current_focus()` = 体此刻最高势能节点 + kind (张力/新颖/漂移)。
- prompt: "体此刻最不安定: `[tension] concern:sir_sleep — 连续熬夜风险`。想就这块放电, 或放下。"
- 不再 `<CATEGORY>A|B|C|D|E>`; 改 `<KIND>` optional (自由词) 或纯派生。

### 5.3 冷却→区放电 (Phase 2, 最险)
- 删 `_compute_free_categories` 的"全冷却 skip" → 改 "无高势能焦点区 → REST" (放下, 已有)。
- 删 2nd‑defense 同类 skip → 改 "同一焦点区刚放电过 (E 已降) → body_focus 自然不再列它"。
- diversity 不再靠类计数, 靠体能量地形 (Weaver decay + 放电)。

---

## 6. 风险 + 回退

| 风险 | 缓解 |
|---|---|
| 拔冷却后连发重复 (Phase 2) | 区放电未必即时 (Weaver 600s 才重算 E) → 加"焦点区刚 attend 过 N min 软抑制" 过渡; 镜像验 |
| prompt 热路径退化 (Phase 1) | flag‑gated 默认关; 镜像 A/B reply 质量; 逐块退 |
| ds‑routing/mediocre 漏迁 → 行为变 | Phase 3 双跑对比; 测试覆盖 |
| 测试大面积红 | Phase 4 专门迁; 每 phase 独立 commit 可 revert |

**回退**: 任一 phase = `thinking_kind_mode=legacy` 立即恢复 A‑E。

---

## 7. 验收判据 (何时算"拔干净")

1. emergent 模式下, 思考由**体焦点区**招来 (镜像可见 attend 焦点)。
2. diversity 来自**放电**而非类冷却 (settled→真歇; 想清→不复发)。
3. kind = effect (无预选槽); filler (none 无 REST) → 引导 REST。
4. A‑E / `SAME_CATEGORY_COOLDOWN_S` / `_compute_free_categories` 退役 (或永久双模 flag)。
5. 全测绿 + Sir 真机验"思考少而精, 在解决真问题"。

---

## 8. 准则对齐

- **准则 6**: kind 不再写死槽; effect→kind 表 vocab 持久化 + CLI; flag 可切。
- **准则 8**: flag‑gated 逐块退, 镜像 + 真机验, 可回退; 不一次全换 (Phase 2 最险单独验)。
- **诚实残余**: 完全拔 A‑E 是深耦合大改; 若 Phase 2 真机风险高, 可停在"summon 锚势能区 +
  kind=effect 派生"(Phase 0/1/3), 保留类冷却作 diversity 兜底 (双模永久共存) — 仍大幅去硬编码。

*下一步: 按 `AGENT_KICKOFF_THINKING_DEHARDCODE.md` Phase 0 起步。*
