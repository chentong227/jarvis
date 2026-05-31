# JARVIS Thinking Brain — Useful-or-Quiet Refactor

> **状态**: design + Phase 1 已落地 (其余分阶段)。
> **缘起**: Sir 2026-05-31 00:46 真痛 —
> > "我要的高频唤醒不是唤醒了一直在重复做无用功。我要么需要他放得下、轻松一点、思考频率降低，
> > 要么他的思考应该真的有用而不是在这编故事 —— 也许是他想到需要什么能力跟我提，也许是他主动想说什么。
> > 这得从思考脑的装配进行一定量的重构。"
> **姊妹篇**: `JARVIS_EMERGENCE_AND_LOOPS.md`(弱/强闭环)、`JARVIS_THINKING_BRAIN_GOVERNOR_DESIGN.md`、
> `JARVIS_GROUNDED_SELF_MEMORY_DESIGN.md`。

---

## 0. 一句话

> **高频唤醒 = 持续存在感，≠ 高频产出。默认安静 + 价值门控降频；产出只走两条有用通道
> (缺能力→跟 Sir 提 / 真值得说→说)，不编故事、不重复提案。**

---

## 1. 深剖 — 思考脑为什么在 over-produce（编故事 + 重复提案 + bloat）

真机 log + 源码核实，5 个根因：

| # | 根因 | 证据 |
|---|---|---|
| **R1 节奏与价值脱钩** | active tick 45s；`_maybe_evidence_gate_skip` 只在"**外部输入**指纹不变"时跳过。Sir 活跃 (打字/切窗/AFK返回) → 指纹每 tick 变 → 不跳 → 每 45s 必 think → 但"**有没有值得想的**"没人管 → 用 narration 填空 | `_maybe_evidence_gate_skip` 看 fingerprint=外部输入 |
| **R2 saturation 被 category-hop 绕过** ⚠️ 关键 | `_check_and_update_saturation` 要"连续 N 条**同 category** + 都 no-speak + actionable 无 effect"才 force 降频。但脑每 tick 换 category (B/A/C/D/E) → `all(t.category==cat)` 几乎永假 → counter 一直 reset → **永不到阈值 → 永不降频**。脑用"跨类低值 churn"逃过了所有节流 | `daemon:3589` `all(t.category == cat)` |
| **R3 输出 schema 逼产出** | 每个非 skip tick 必出 `<THOUGHT>` + 常出 actionable。`(quiet)` 允许但 LLM 被 prime 成"产出"，极少选 → 低值 tick 也产 thought + propose | `_build_prompt` FORMAT |
| **R4 弱闭环 → 提案不消停** | `propose_protocol` 注入文字、没真 gate 主脑 → 问题不消失 (主脑照旧"Welcome back") → 换措辞**再提** (躲 jaccard dedup) → bloat。且 propose 被 activate = "有 effect" → 不算 saturated → 更不降频 | log: proto_001857/_002546 都"don't use generic greetings" |
| **R5 concern 脏数据 = narration 原料** | 12 concern 多条 archived/重叠/**错标** (jiazhao_ke1 实为公考: "1128人第二名/上岸/体检") → LLM weave 成自信故事 | `concerns.json` |

> **综合**: 脑被"必须每 45s 产出点什么"驱动，**跨类低值 churn 逃过所有现有节流**，
> 用编故事 + 重复提案填空。bloat 是"提案改不动行为就无限再提"的症状。

---

## 2. 方案 — 装配重构 (default-quiet + value-gated + 两条有用通道)

| Phase | 件 | 治 | 状态 |
|---|---|---|---|
| **P1 价值门控降频** | 跨 category 连续低值 tick → 指数退避 (90→180→300→600)，reset on 高值/should_speak。补 R2 saturation 的 category-hop 漏洞。只拉长不缩短 (clamp 安全) | R1+R2 | ✅ **已落地** (6 test) |
| **P2 默认安静 bar** | prompt reframe: 默认 idle/quiet 是常态；thought+actionable 要过价值 bar；重复主题优先 `let_go` 不再 propose | R3 | 待 |
| **P3 有用通道** | 新 actionable `request_capability:<具体需要>` — 脑意识到缺能力/信息 → 具体跟 Sir 提 (走 surface)，不 narration。"主动想说"走高 bar surface | Sir vision | 待 |
| **P4 弱闭环治本** | propose 真 gate 主脑 (strong loop, emergence §3) + `fired-not-helped` 自动退休 + 收紧 pre-activate dedup | R4 | 待 |
| **P5 concern 卫生** | 修错标 (jiazhao↔公考) + 清 archived/重叠 concern | R5 | 待 |
| **T1 即时清理** | 退/合并 35 joke + 32 protocol 近义/陈旧 (止血) | bloat 现状 | 待 |

---

## 3. P1 已落地细节 (本轮)

- vocab: `inner_thought_saturation_config.json` 加 `value_backoff` (enabled / low_value_salience_floor 0.55 / reset_on_high_salience 0.75 / min_streak_to_backoff 2 / backoff_steps_s [90,180,300,600])。CLI: `scripts/inner_thought_saturation_dump.py`。
- `_update_value_backoff(thought)`: tick 后调，**不看 category**，只看价值。低值 = `salience<floor AND not should_speak AND actionable 无 effect` → `_low_value_streak++` → 指数退避；`should_speak 或 salience>=reset_high` → reset 回 baseline。
- `_tick` clamp: `resolved_interval = max(resolved_interval, value_backoff_interval)`，origin='value_backoff'，bg_log "😌 降频至 Ns (放得下)"。
- 测试 `_test_fix72_*`: 跨 category 低值累积退避 [0,90,180,300,600,600] / 高 sal reset / should_speak reset / 中值不退 / disabled / config present。**6 pass**。

---

## 4. 设计原则锚 (后续 P2-P5 守)

1. **准则 6**: 全 vocab 持久化 + CLI；阈值/措辞不写死；判断交 LLM (capability 需求由脑自决，不 regex)。
2. **准则 1**: 降频 = 省 token；P3 capability-request 不增热路径。
3. **emergence §3 强闭环**: P4 的核心 —— 提案要真 mutate 会 gate 主脑的态，否则永远再提 (bloat 根)。
4. **准则 8**: P1 复用 saturation 框架 (不另起炉灶)，只补 category-hop 漏洞。

*下一步: P2 默认安静 + P3 capability 通道 (需改 `_build_prompt` schema + actionable handler)；T1 清理走 CLI/review。每 phase 独立可测 + Sir 真机验收。*

---

## 5. 体集成 — 让思考脑真有用 (2026-05-31, 体落地后补)

> Sir 原话: "在做完体以后, 根据体和口结合, 分析如何让思考脑确实有用?"
> 前文 R1-R5 + P1-P5 是**体不存在时**写的, "价值"只能靠脑**自评** (salience) — 这恰是它能
> "编故事"骗过自己的原因。**体 (`JARVIS_TRINITY_ARCHITECTURE.md`) 落地后, 价值变成客观可接地的。**

### 5.1 一句话重构

> **识不再是"独白生成器", 变成"体的注意力 + 编辑"**: 每 tick 注意体的一小片 (spreading-activation),
> 只问"这片需要动作吗?" — 动作只有三种 (改体 / 递给口 / 跟 Sir 要能力)。没有 → 安静。
> 频率自然降 (大多 tick 发现体是 settled 的); 产出自然有用 (三条都接地, 没 narration)。

### 5.2 体给的三个客观信号 (治 R1-R4 的根)

| 旧根因 | 体不在时的残缺 | 体落地后的客观解 |
|---|---|---|
| **R1/R2 churn** | "有没有值得想的"靠脑自评 salience → 跨类低值 churn | tick 有用 ⟺ **改了体** (建/强化边、动 concern/stance) **或** 体当前激活里有东西够到口。attended 区已 settled (稠密稳定边 + 已被近期遍历 + 已有高置信 stance 覆盖) → 没事干 → 安静。**"想透了"几何可检测**, 非自评 |
| **R3 schema 逼产出** | 每 tick 必 `<THOUGHT>`, prime 成"产出" | 口/透镜给真目标: schema 改 **decision-first** — `<ATTEND>`(看体哪片, node_id 接地, 不能凭空) + `<TICK_DECISION>` ∈ {quiet / update_body / surface / request_capability}。只有选中的决策才出内容, quiet first-class 且廉价 |
| **R4 弱闭环 bloat** | propose 注文字、没 gate 主脑 → 问题不消失 → 换措辞再提 | **体 = 强闭环**: 学到的东西写成 **stance 节点** (体-P4) → 透镜 (体-P6) 投影进口 → 真改主脑行为 → 问题不再复发 → 脑不再 re-propose (bloat 根治)。stance 就是"Jarvis 学到 X"活着且影响口的地方 |

### 5.3 这同时给 Sir 两个要的东西

- **放得下**: 体记录什么 settled → 脑不反刍 → 安静 → 频率自然降。"放下" = 体的一个属性
  (settled 区 / 低 salience thread), **不是硬 cooldown**。
- **真有用**: 产出只有 改体(强闭环) / 递口(真值得说) / 要能力, **全接地, 无编故事**。

### 5.4 装配重构 (映射 P2-P5 + 体维度; 这是下一 track, 待 Sir go)

| 件 | 改哪 | 用体的什么 | 接地 |
|---|---|---|---|
| **输入**: 体注意力切片 | `_build_prompt` 注入 `manifold.spread(当前语境)` top-K 节点 + settled/live + 边 | 边层(P1/P2) + 透镜原语 | 节点 = 真 store id |
| **输出**: decision-first schema | `_build_prompt` FORMAT 换 `<ATTEND>`+`<TICK_DECISION>` | — | ATTEND 限定在体节点 |
| **价值门控客观化** | tick 后判"体变了吗 / 够到口了吗" → 扩 P1 value-backoff (客观信号替自评 salience) | 边/stance 是否 mutate | mutate 有 provenance |
| **重复检测走体** | 想 X 前查 X 是否落在 settled/稠密区 → 是则 quiet | surfaces(P3) + 边密度 | 替 text-jaccard (R4 说被改写绕过) |
| **能力通道 (P3)** | 反复未满足的需求 = 体里反复被强化却不消解的 concern/node → 脑 surface "我老撞 X 干不了, Sir 我需要 Y" | 边反复强化 + 不消解 | recurrence 接地, 非凭空 |

### 5.5 依赖 + 现状

- 全 reframe 消费 **体-P6 透镜** (口通道) + **体-P4 stance** — **两者已落地** (gated)。
- 部分 (体注意力输入 / 重复走体 / 客观价值门) 只需边层 (已落地) 即可先做。
- **强闭环** (学到的→stance→透镜→改主脑) 需 stance+透镜 (已落地, 默认关) — Sir 真机验透镜投影质量 + 开 `lens_inject_enabled` 后, 这条闭环才真通。

*∴ 顺序建议: ① Sir 真机验透镜 (开 gate A/B 看主脑 reply 质量) → ② 识装配重构 (decision-first + 体注意力 + 客观价值门) → ③ stance 写入闭环 (识 propose stance → Sir review → 透镜投影)。*

