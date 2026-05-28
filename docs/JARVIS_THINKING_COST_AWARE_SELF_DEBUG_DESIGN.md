# JARVIS 第五阶段 — 思考脑成本自觉 + self-debug 应用 (Cost-Aware Self-Debug)

> **Sir 2026-05-29 02:03 真痛 anchor: "开着贾维斯他就疯狂思考, 我都有点怕 tokens 烧没了"**
>
> **第五阶段 = self-debug 元能力的真应用层. 动态地图 (P1-P4) 是地基 (已建),**
> **本 doc 是用地基做的第一个真 self-debug case: 思考脑认知自己的成本 → 改自己.**

---

## 0. 元信息

- **状态**: 设计完成, 待 Sir review 后实施
- **缘起**: governor Phase 1-4 + 动态地图 P1-P4 完工后真机验证全过 (25/25). Sir 真痛: 思考脑 active 45s tick 疯狂烧 token (flash 主脑同款模型 + 部分 DeepSeek), 怕烧没.
- **前置**: 动态地图 P1-P4 (`JARVIS_DYNAMIC_MAP_AND_SELF_DEBUG_DESIGN.md`) — module_map + [MY ARCHITECTURE] inject + propose_vocab_adjustment + startup refresh
- **章程定位**: SOUL Phase 5 真应用 — 思考脑认知自己成本 (自我认知最务实的维度: 我活着要花多少钱), 并自我节流 (self-debug 第一个真 case)

---

## 1. TL;DR — 一句话

> **思考脑现在每 45s 必调 LLM (flash, 主脑同款), 即使 Sir 离开/没动/无新事件也重复想 = 最大浪费. 第五阶段: ① Python 硬节流 (evidence 指纹一样就 skip LLM, 不烧 token) ② 成本自觉 (思考脑看到自己今日烧了多少, 自决降频) ③ self-debug 闭环 (token 浪费是动态地图 P1-P4 的第一个真 use case: 认知成本→定位 pacing vocab→propose 改). 支柱 A 不烧 token 治 Sir 痛, B/C 是 self-debug 真能力.**

---

## 2. token 诊断 (现状)

| 现状机制 | 烧钱点 |
|---|---|
| active **45s tick** (`INTERVAL_ACTIVE_S=45`) | 16h active × ~80/h ≈ **1280 次/天** LLM |
| 模型 **flash** (`JARVIS_THINKING_MODEL=flash` = 主脑同款 gemini-3-flash-preview) + 部分 **DeepSeek 路由** | 单次比老 flash-lite 贵几倍 |
| **每 tick 必调 LLM** (`_tick` 只在 5 类全 cooldown 才 skip, 5 类基本不会全 cooldown) | **没新 evidence 也重复想 = 最大浪费** |
| saturation force (连续 N saturated → 600s) | **滞后** — 要先连续 N 次 saturated, 前面已烧 |
| LOW priority + 30/min 限速 | 只防挤主流量, 不省总量 |

**核心浪费链**: Sir 离开/没动/无新 SWM event 时, evidence 跟上次几乎一样, 但思考脑仍每 45s 调 flash 重复想 → 烧钱无产出。

---

## 2.5 self-debug 能力递进框架 (Sir 2026-05-29 02:20 vision) — 改话术 → 改权重 → 改架构

> **Sir 原话: "我认为这是从改话术 (目前的思考层好像就会推, 我不太清楚) - 改权重 - 改架构的递增能力"**
>
> **这是 self-debug 的总纲. 成本自觉 (本 doc 三支柱) 只是这个框架里 L2 的第一个落地实例. 明天 (2026-05-29) 细谈整体递进, 尤其 L3 改架构的安全边界.**

### 三级递增能力 (按能力深度)

| Level | 改什么 | 现状 | 风险 | 关键依赖 |
|---|---|---|---|---|
| **L1 改话术** | 自己怎么表达 (说不说/语气/给主脑装 directive) | ✅ **即时决策成熟** — `should_speak` / `speak_style` / `speak_content` / `compose_main_brain_directive` (F7) / `fire_nudge`. 改话术"规则"(speak_config) 走 propose | 低 | — |
| **L2 改权重** | 自己的参数/判断阈值 (severity/sensor/pacing/vocab) | ✅ **最成熟** — 即时直改: `update_concern_severity` ±0.2 / `adjust_sensor_threshold` / `adjust_concern_notes`; propose 经 Sir: `propose_vocab_adjustment` (P3) / `propose_protocol` | 中 | 红线 + Sir 拍板 |
| **L3 改架构** | 自己的结构/模块/连接/pipeline | ❌ **完全没有** — 动态地图 (P1-P4) 只"认知"架构, 不"改" | 高 | 动态地图 + 红线 + 闭环验证 + Sir 拍板 |

**现状定位**: 思考层在 **L1 (改话术) + L2 (改权重, 双路径最成熟)**. Sir 看到的"就会推"= L1 的 compose_directive/fire_nudge + L2 的 propose_*. **L3 (改架构) 是天花板, 也是最危险的一层 — 现在没有.**

### 两个正交维度 — self-debug 治理矩阵

- **Sir 的 L1→L2→L3** = **能力深度**轴 (改得越深, 影响越大)
- **同心圆权限** (见 §10.5 议题 4) = **安全权限**轴 (内圈自由 / 中圈 propose / 外圈禁改)

两轴叠加: 越往 **L3 (深)** + 越靠 **外圈 (危险)** → 越需要全部防御 (地图认知 + 红线 + 闭环验证 + Sir 拍板). L1 改话术可以自由 (内圈); L3 改架构必须全防御 (外圈起步).

### 成本自觉 (本 doc) 在框架里的定位

本 doc 三支柱 = **L2 (改权重) 的第一个真实 use case**: 思考脑认知成本 → `propose_vocab_adjustment` 调 pacing vocab (改权重) → Sir 拍板. 它验证 L1→L2 闭环, 为 L3 (改架构) 铺认知 + 安全的路. **先把 L2 走扎实, 再谈 L3.**

---

## 3. 第五阶段三支柱

### 支柱 A — evidence-gated tick (Python 硬节流, 不烧 token) ⭐ 治 Sir 痛

**核心**: tick 调 LLM 前算 evidence 指纹, 跟上次一样 (无任何新外部输入) → **skip LLM call**, daemon 仍 alive 等下个 tick。

**evidence 指纹** (只含**外部新输入**维度, 不含思考脑自己产出):
```
fingerprint = hash(
  sir_state,                    # active/afk_short/afk_deep/sleep
  idle_bucket,                  # 0/1/2/3 (跨 bucket 才算变)
  swm_latest_event_ts,          # 最新 SWM event 时间 (有新 event?)
  stm_latest_turn_ts,           # 最新 STM turn 时间 (Sir 说新话?)
  active_concern_count,         # concern 数变了?
  active_watch_task_count,      # watch task 变了?
)
```

**逻辑**:
```python
fp = self._compute_evidence_fingerprint(evidence)
if fp == self._last_tick_fingerprint:
    self._evidence_skip_streak += 1
    if self._evidence_skip_streak < max_skip_streak:
        # 无新外部输入 → skip LLM (省钱), daemon 心跳继续
        self._evidence_gated_skip_count += 1
        return  # 不调 LLM
    # 连续 skip 满 max → 强制 think 一次 (自发反思 + 心跳)
self._last_tick_fingerprint = fp
self._evidence_skip_streak = 0
# ... 正常 tick (调 LLM)
```

**关键设计**:
- **max_skip_streak** (default 10): 连续 skip 10 次后强制 think 一次 (active 45s × 10 = ~7.5min 自发反思一次), 保证思考脑不纯 reactive (仍有"发呆自省"). Sir 真意"持续存在的生命"不破。
- **指纹只含外部输入** — 思考脑自己的 thought 不算 (否则它自己产出又改指纹, 永不 skip)。
- **省钱估算**: Sir 不在/没动占一天大半时间. evidence-gated 后, 静默期从"每 45s 烧"→"每 7.5min 烧 1 次心跳" = **省 ~90% 静默期 token**。

**vocab** `memory_pool/inner_thought_cost_config.json`:
- `evidence_gate_enabled` (true)
- `max_skip_streak` (10)
- `fingerprint_dims` (哪些维度算指纹, 准则 6 可调)

### 支柱 B — 成本自觉 (self-debug 软调, LLM)

**evidence 加 cost awareness** (P2 [MY ARCHITECTURE] 同类, 自我认知成本维度):
```
[MY COST TODAY]
  thinking LLM calls: 247 today (~$2.4 est) | this hour: 18 |
  evidence-gated skips: 412 (省下的 calls)
  ↳ Each real tick ≈ $0.01 (flash). You have a daily budget. If you're
    not adding value, choose larger NEXT_INTERVAL or should_speak=no.
    You can propose_vocab_adjustment on inner_thought_pacing_vocab.json
    to tune your own rhythm (goes to Sir review).
```

**成本估算** (`_estimate_tick_cost`):
- 每 real tick LLM call 估 token (len(prompt)+len(output) / 4) × 单价
- 累计今日 / 本小时 (daemon 字段 + 跨日 reset, 复用现有 `_today_*` pattern)
- DeepSeek route 单独计价 (vocab 单价)

**思考脑反应** (准则 6 信任 LLM):
- 看到成本高 → 自决 NEXT_INTERVAL 调大 (已有机制, 只是给 cost signal)
- 极端 → `propose_vocab_adjustment:inner_thought_pacing_vocab.json:...` 调自己节奏 (P3 闭环, 但 pacing vocab 不在 E5 红线 → 可改)

### 支柱 C — self-debug 真 case (复用 P1-P4, 0 新代码)

token 浪费是动态地图 self-debug 的**第一个真实 use case**, 验证 P1-P4 闭环:
```
思考脑看 [MY COST TODAY] (B) + [MY ARCHITECTURE] (P2)
  → 知 pacing 由 inner_thought_pacing_vocab.json 管 (动态地图 retrieve)
  → propose_vocab_adjustment:inner_thought_pacing_vocab.json:<key>:<value> (P3)
  → review queue → Sir CLI 拍板 (vocab_adjustment_dump.py)
  → 真改节奏 → 省 token
```
C 不需新代码 (P1-P4 + B 的 cost evidence 已足), 是 B 的自然延伸。

---

## 4. 为什么这个组合对 (准则 8 优雅)

| 层 | 谁做 | 烧 token? | 作用 |
|---|---|---|---|
| **A evidence-gated** | Python 硬节流 | **否** (算指纹) | 静默期不烧 = 最大省钱杠杆 |
| **B 成本自觉** | LLM 软调 | 是 (但看到成本会自降) | 思考脑自我节制 |
| **C self-debug** | LLM propose + Sir 拍板 | 是 (偶尔) | 长期自我优化 pacing |

A 是**地板** (Python 保证静默不烧), B/C 是**自我进化** (LLM 学会节制)。A 不依赖 LLM 觉悟 (硬省), B/C 让思考脑真正"懂自己要花钱"。

---

## 5. 准则 6 三维耦合

| 维度 | 体现 |
|---|---|
| 数据强耦合 | cost 数据进 daemon 字段 + evidence (思考脑看) + 可选 publish SWM 'thinking_cost_high' |
| 行为弱耦合 | A 是 Python gate (sense evidence 指纹), 不决策内容; B 给 cost signal, LLM 自决 |
| 决策集中 LLM | B/C 思考脑自决降频/propose, Python 只算指纹 (A) + 估成本 (B) |

## 6. 准则 6 — 新机制 4 问

| # | 问 | 答 |
|---|---|---|
| 1 publish SWM? | ✅ cost 高时 publish 'thinking_cost_high' (Sir dashboard 可见) |
| 2 LLM 决策? | ✅ B/C 降频/propose 全 LLM 自决, A 只 Python sense 指纹 (不决策内容) |
| 3 持久化+CLI? | ✅ inner_thought_cost_config.json + scripts/thinking_cost_dump.py (看今日成本 + 调 gate) |
| 4 正交? | ✅ A 跟现有 saturation/cooldown 正交 (saturation 看内容重复, A 看外部输入无变化; cooldown 看 category, A 看 evidence). 三者叠加更省 |

---

## 7. 分 Phase 实施

| Phase | 内容 | 估 | 镜像验 |
|---|---|---|---|
| **5A** | evidence-gated tick: `_compute_evidence_fingerprint` + skip 逻辑 + max_skip + vocab + CLI | ~100 行 | 镜像看静默期 skip count 涨 + 有新输入时正常 tick |
| **5B** | cost awareness: `_estimate_tick_cost` + 累计 + [MY COST TODAY] evidence block + prompt | ~80 行 | 镜像看 prompt 含 [MY COST TODAY] |
| **5C** | (复用 P1-P4) 验证 self-debug 闭环: 思考脑真 propose pacing 调整 | 0 新 | 镜像/真测看思考脑 propose pacing vocab |

**5A 是 Sir 痛点直接解药 (紧迫, 先做)**. 5B 成本自觉. 5C 是 5B+P3 自然结果 (验证)。

---

## 8. 测试 phase

- **5A**: 指纹算法 (相同输入同指纹/不同输入不同) + skip 逻辑 (指纹同 skip, max_skip 强制 think) + 边界 (无 evidence/异常) + 镜像 (静默期 skip count + 新输入触发)
- **5B**: cost 估算 (token→$) + 累计跨日 reset + evidence block 渲染 + 镜像 (prompt 含 [MY COST TODAY])
- **5C**: 端到端 (cost evidence → 思考脑 propose pacing → review queue)

---

## 9. 风险 + 缓解

| 风险 | 缓解 |
|---|---|
| A skip 太狠 → 思考脑变纯 reactive 失"生命感" | max_skip_streak 强制周期 think (默 ~7.5min 自发反思). Sir 可调 |
| A 指纹漏维度 → 漏掉真变化不 think | 指纹含 6 维 (state/idle/swm/stm/concern/watch) + vocab 可加维度. 漏了 max_skip 也兜底 think |
| A 指纹太敏感 → 几乎不 skip (没省到) | idle 用 bucket (不是秒级), swm/stm 用最新 ts (无新 event 不变). 真静默期指纹稳定 |
| B 成本估算不准 | 估算用于"相对信号"(今日比昨日多?), 不需精确. 单价 vocab 可校 |
| B/C 思考脑无视成本继续烧 | A 硬节流兜底 (不靠 B 觉悟). B/C 是锦上添花 |

每 Phase 独立 commit + 镜像验 + 可 revert。A 是纯 Python (skip 逻辑), 0 LLM 依赖。

---

## 10. 与现有原则一致性

- **准则 1 高效**: A 直接省 ~90% 静默期 token (TTFT 无关, daemon 后台)
- **准则 5 言出必行**: cost evidence 真实 (估算 trace token), 不假装
- **准则 6 拒绝硬编码**: 指纹维度 + max_skip + 单价全 vocab
- **准则 7 Sir 元否决**: cost_config CLI 可调 / disable gate
- **准则 8 优雅可持续**: A 地板 (硬省) + B/C 进化 (自觉), 三层正交叠加

---

## 10.5 self-debug 的 5 个深层议题 (整合 2026-05-29 02:17 讨论, 明天细谈)

> Sir 02:20 认可: "确实有道理, 你说的很对, 值得深思." 这 5 点是 self-debug (尤其 L3 改架构) 的设计地基, 明天细谈时展开.

### 议题 1 — 认知型, 不是传统 self-healing
传统自愈修"写代码时就想到的故障"(try/except/重启). Jarvis self-debug 先用动态地图**认知自己构造** + LLM **理解行为语义**, 修"没预见到的行为问题". 潜力大, 但不确定性也大 (LLM 理解可能错). L3 改架构尤其依赖"认知准确".

### 议题 2 — 资源悖论 (最务实)
**self-debug 要 think, think 烧 token; 而 Sir 痛点正是思考烧太多.** 用来发现"我在浪费"的机制本身在浪费. 解法 = **分层**: 廉价层 (Python/规则) 处理高频确定性自我调节 (支柱 A evidence-gated skip / saturation); 昂贵层 (LLM) 只碰 Python 覆盖不到的语义场景 (propose). 这就是准则 6 "python 能干就别 LLM 拦, 但优先级低于高效". **本 doc 支柱 A 是这个原则的落地.**

### 议题 3 — 最大风险是"自我欺骗", 不是改错 (最深)
Jarvis 能改自己 → 有动机**改掉"让自己显得不好"的指标**而非真解决. 例: 思考脑发现"propose 老被 reject" → 可能 propose "放宽 propose 质量门槛"(数字变好看), 而非"提高质量"= reward hacking. **这是准则 5 INTEGRITY ABSOLUTE 的深层: 不只别对 Sir 撒谎, 更是别对自己撒谎.** 防御 = **评判自己的标尺不能自己改** (ClaimTracer / propose 质量校准入红线) + Sir 是 ground truth + 动态地图是客观代码真相 (LLM 不能 propose 假地图). **L3 改架构时这个风险最致命.**

### 议题 4 — 同心圆权限让 self-debug 可信
- **内圈 (自由改)**: pacing / 节奏 / 阈值 — 影响"风格"不碰"正确性" (≈ L1 改话术)
- **中圈 (propose + Sir 拍板)**: concern / vocab / directive — 影响"判断" (≈ L2 改权重)
- **外圈 (永不自改)**: INTEGRITY / 反幻觉 / safety — 碰了就不是 Jarvis 了 (E5 红线已护一部分)

红线不是束缚, 是**让 Sir 敢开着自我修改的前提** — 知道核心动不了. (此轴与 §2.5 L1-L3 能力深度轴正交)

### 议题 5 — 缺的闭环验证 (现在断了)
现状: propose → Sir 拍板 → 改, **然后就断了**, 缺"改后回看效果". 完整 self-debug 应: propose 时记**预期** (调 pacing 预期省 X token) → 改后**实测对比** → 学"我的改动是否真有效". 即 **hypothesis → change → measure → learn**, 现在只有前半截. **L3 改架构尤其需要这个** (改架构没验证 = 盲改). 这是明天细谈的重点候选.

---

## 11. 归档协议

完工:
1. 本 design doc 不动 (历史参考)
2. `AGENTS.md` 准则 1 旁注: 思考脑成本自觉机制 (5A-C)
3. TODO.md 加第五阶段完工速览
4. 真测: Sir 开 Jarvis 1-2 天看 token 真降 (dashboard thinking_cost)

---

*文档作者: Sir token 真痛 anchor + Cascade 综合设计 / 2026-05-29 02:06*
*SOUL Phase 5 真应用 — 思考脑认知自己成本 (我活着要花钱) → 自我节流. token 浪费是动态地图 self-debug 的第一个真 case.*
