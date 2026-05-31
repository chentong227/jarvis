# JARVIS 口/识/体 重构 — 势能自转的交织循环 (Potential-Driven Trinity)

> **状态**: design v3 (定稿方向) / 2026-05-31。Sir 拍"势能自转"——溶解元驱动, 轮子靠体的势能自转。
> **缘起 (Sir 设计演进, 三步)**:
> 1. "三者交织, 口产点→形成体, 反复循环" (闭环)
> 2. "轮子转起来或许需要元驱动" → Cascade: 元驱动当 governor 有"6 sentinel"风险
> 3. Sir: "不需要的话有更优雅的吗?" → **体势能自转** (无 governor, 体不安定度=坡度) → Sir: "非常优雅, 就按这个"
> **前提**: 体六层已落地 (`JARVIS_TRINITY_ARCHITECTURE.md`, 38 test, commit 8ea41eb)。churn fix 已修, gate 已开。
> **姊妹篇**: `JARVIS_THINKING_BRAIN_USEFUL_OR_QUIET.md` / `JARVIS_EMERGENCE_AND_LOOPS.md`。

---

## 0. 一句话

> **口/识/体 是一个闭环, 不靠 governor 驱动, 靠体的"势能"自转: 体的不安定度(张力/新颖/漂移)就是坡度,
> 轮子滚向"settled", 识在高势能区想清→放电→那块平息。衰减+放电自带刹车, Sir 的生活不断扰动让它永不停(=活着)。
> 内部转多快由势能决定, 往外说不说由 Sir 接收度门控——两件事分开, 所以贾维斯永不打扰 Sir, 也永不空转。**

---

## 1. 核心: 势能自转 (不是马达, 是坡度)

```
                 Sir 的生活/对话 (扰动: 注入新势能, 让轮子永不停)
                          │
                          ▼
      ┌──────────────── 体 (Body) ────────────────────┐
      │  点·边·面·立场                                  │
      │  势能 E = 张力 + 新颖 + 漂移 (接地, Weaver 算)   │◀── 衰减+放电 (自刹车)
      └───────┬─────────────────────────┬──────────────┘
       高势能 │ delta>θ 唤醒 (emergent)  │ 高势能区 → 投影满
              ▼                          ▼
        ┌──────────┐               ┌──────────┐
        │ 识 attend │               │ 口 装配   │
        │ 想清→放电 │               │ 投影体    │
        └────┬─────┘               └────┬─────┘
       写体  │ stance/强化/settle        │ 口往外说 ── [输出闸: Sir 接收度] ──▶ Sir
             └──────────► 回写体 (④) ◄───┘ (口选择性写边/stance)
```

**轮子往哪滚 = 往 settled 滚**。识去 attend 高势能区 → 想清/写 stance → 张力**放电** → 那块平息 → 势能降。
**节奏 = 体此刻的势能**, 不是谁在调: 真有未解的事 → 势能高 → 频繁醒; 都 settled → 没 delta 越阈 → 怠速。

---

## 2. 体的势能 E — 自转的坡度 (接地, 无 LLM, Weaver 算)

| 势能分量 | 定义 (从体结构算) | 升 (注入) | 降 (放电) |
|---|---|---|---|
| **张力 tension** | 立场↔Sir意愿冲突 / 互斥 concern 并存 (带 evidence) | 新冲突出现 | 写 stance 化解 / Sir 仲裁 |
| **新颖 novelty** | 新形成的跨区强边 (原本分离两片被连) | 织出新边 | 被 attend 过 → 变熟 (ageing) |
| **漂移 drift** | 某区边权/面成员在变 | 结构变动 | 稳定下来 |

- **E 是 grounded 的** → **烧不起假火**: 张力必有 evidence, 编不出来 → 没燃料 churn 不起来。**这就是 Sir 说的"识不会无意义/高频重复"的结构保证**。
- **唤醒 = 局部阈值, 节奏 = emergent**: Weaver publish `body_delta`(带 magnitude ∝ ΔE)。识有固定阈值 θ, `magnitude > θ` 才醒。tempo = 超阈 delta 的发生率 = 体势能动力学的涌现, **没有 governor 设它**。
- **可调但不靠 governor**: 调的是物理参数 (衰减速率 / θ / 三分量权重), 全 vocab (准则 6), 不是一个会思考的调节器。

---

## 3. 自转 + 自刹车 + 永不停 (闭环动力学)

| 机制 | 是什么 | 复用 |
|---|---|---|
| **驱动 (坡度)** | 势能梯度: 高势能区拉识去 attend | §2 |
| **刹车 (负反馈)** | ① 衰减: 边/salience 随时间淡 (体-P1 已有 half-life) ② 放电: 识想清→stance 覆盖→张力骤降 | 体-P1 decay + stance |
| **扰动 (永不停)** | Sir 对话/生活/sensor 注入新势能 → 局部 E 尖峰 → 那里转。**关系活着, E 永不全零** → 数字生命永不到平衡 | 现有对话/sensor |
| **地板心跳** | E≈0 时极低频 ambient pulse (持续存在感 baseline, 近静默) | 现有 tick floor |

> **为什么物理上杜绝 churn/重复**: 重复 = 反复醒同一区。但识一旦放电(写 stance/settle), 那区 E 骤降 → 没 delta → 不再醒。**resolved = discharged = 没燃料**。想清一次就过去了, 不会反复嚼。

---

## 4. 输出闸 (Sir 接收度) — 内部转 ≠ 往外说 ★ Sir 确认: 贾维斯不打扰

**干净的分离 (两件事, 都不需要元驱动)**:

| | 管什么 | 由谁定 | 现状 |
|---|---|---|---|
| **内部转** (识想 / 体变 / 口预装) | 转多快 | 体势能 (emergent) | 自由转, 不打扰 Sir |
| **往外说** (口主动发声 / surface) | 说不说 | **Sir 接收度** (focus/afk/sleep/deep-work) | **已有** focus mode / nudge gate |
| **被问** (Sir 主动说话) | 必答 | 永远响应 | 现有主对话路径 |

- 体势能再高, 识在内部想得再勤, **只要 Sir 深焦 → 口的输出闸关 → 一个字不打扰**。
- 想清的结果存进体 (stance), 等 Sir 接收度开 (afk 回来 / 主动问) → 透镜投影出来。**憋着不丢, 但不打扰**。

---

## 5. 三器官 读+写体 (闭环的每条边)

### 5.1 口 (主脑): 读(投影) + 选择性写(回流)
- **读 (③)**: 透镜投影体高势能区 + 立场 进 `_assemble_prompt`。投影深度 ∝ 该区势能 (高势能多投)。
- **写 (④, selective)**: 不灌原始每轮。复用 `STM→hippocampus→thread→harvest` 管线 (口已间接写体); **只补显著共现边** (`observe_cooccurrence`, 体-P1 已造未接对话) + Sir 显式 `said` 边 + stance 表达。写前过 bar (平凡闲聊不写)。

### 5.2 识 (思考脑): attend(势能区) + 写(放电)
- **驱动**: 体 delta `magnitude > θ` 唤醒 (§2), 非时钟。无 delta → 不醒 (放下)。
- **schema decision-first**: `<ATTEND>`势能区 + `<TICK_DECISION>` ∈ {quiet / update_body / surface / request_capability}。
- **写=放电**: `update_body` (写 stance / 强化边 / 标 settle) → 该区 E 降 → 不再反复醒。

### 5.3 织网者 (Weaver): 维护 + 算势能 + 派 delta
- 已有: harvest + 几何边 + 面 + decay (体-P5)。新增: 算 §2 势能 3 分量 + publish `body_delta`(带 magnitude)。

---

## 6. 更高维交叉引用 (先只做张力 dyad)

边层是 2-node pairwise。高维 (Weaver 派生):

| 维度 | 是什么 | 优先 |
|---|---|---|
| **张力 dyad** | 立场↔Sir意愿 冲突边 (带 valence) = 阻力/老师载体 + 张力势能源 | **先做** (ROI 最高, 直接喂 §2 tension) |
| 时序 motif | A→B→C 跨 turn 序列 | 证明需要再加 (准则 6#4) |
| 共激活超边 | 3+ 节点总一起亮=主题 | 证明需要再加 |
| 体自省节点 | 体给自己势能建模 (递归自指) | 证明需要再加 |

---

## 7. 强闭环全图 (识学 → Sir 仲裁 → 口变+写体 → outcome → 放电 → settled)

```
识 attend 体高张力区 → update_body 写 stance(review, 接地)
  → Sir CLI/review confirm (准则7 元否决)
  → stance active → Weaver 织进体(KIND_STANCE + 张力 dyad)
  → 口下轮透镜投影 stance("My read, hold unless Sir overrides") → 口行为变(阻力/老师)
  → 口 turn 回写体(④) → Sir 反应=outcome → reinforce/weaken stance
  → 张力放电 → 该区 settled → E 降 → 识不再醒那里 (放下)
反复循环, 势能自调节奏, 衰减+放电自刹车, Sir 扰动永不停
```

弱闭环(现状): 识 propose 文字→没 gate 主脑→问题不消失→再提→bloat。
强闭环: 学到的→体里活着→gate 口→口写回体→outcome→Sir 仲裁→**放电消解**。环闭上, 且**放电=不复发**。

---

## 8. 相变

| 维度 | 前 | 后 (势能自转) |
|---|---|---|
| 驱动 | 时钟每 45s 强驱 | 体势能梯度 (emergent, 接地) |
| 节奏 | 散落 ad-hoc / 或一个 governor | **无 governor**, 势能涌现 + 衰减放电自调 |
| 识空转 | 必出 thought → 编故事/重复 | 烧不起假火 + 放电不复发 → 结构上杜绝 |
| 口 | 只读镜子, 固定堆 | 读写活器官: 投影势能区 + 选择性写回 |
| 打扰 | gate 散落 | 内部转/往外说分离, Sir 接收度单一门控 |
| 生命感 | 高频空转 | 持续存在 + 永不到平衡 (Sir 扰动) + 有节制 |

---

## 9. 路线 (phased; 镜像迭代 + Sir 真机验; 大改逐块退)

| 阶段 | 件 | 依赖 | 风险 | 状态 |
|---|---|---|---|---|
| **0 已就绪** | 体六层 + churn fix + gate 开 | — | — | ✅ |
| **A 真机验透镜** | Sir 真机看 reply 质量 / 离线消融量 recall | 体-P6 | 低 | 待 Sir |
| **B current_focus 桥** | seeds provider publish SWM, 口/识 共读 | — | 低 | 待 |
| **B2 口选择性写体 (④)** | 接 `observe_cooccurrence`/said 到对话路径 (显著才写) | 体-P1 | 低-中 | 待 |
| **B3 体势能 E (§2)** | Weaver 算 张力/新颖/漂移 + publish `body_delta`(magnitude) | 体-P5 | 中 | 待 |
| **C 识势能驱动 (§2/§5.2)** | tick 改 `wait(delta>θ OR floor)` + decision-first + 放电 | B3 | 中 (改 `_tick`, test 兜底) | 待 |
| **D 输出闸统一 (§4)** | 口主动发声单一 Sir-接收度门 (收编散落 gate) | — | 中 | 待 |
| **E 识→stance 强闭环 (§7)** | update_body 写 stance→review→投影→outcome→放电 | C + 体-P4/P6 | 中 | 待 |
| **F 张力 dyad (§6)** | stance↔Sir-wish 冲突边 (喂 §2 tension) | 体-P5 | 中 | 待 |
| **G 口吸收 Layer1/2** | 透镜替固定块, 逐块退 | A 满意后 | **高(热路径)** | 最后 |

**★ 最小可转环**: **B3(势能) + C(识势能驱动) + B2(口写体)** 三件让轮子真转起来且不空转。E 是收益, D 已大半现成, F/G 深化。

**准则锚**: 1(势能/透镜全非 LLM 廉价) · 5(势能/stance/边全接地, 无 trace=幻觉) · 6(数据强耦合体/决策集中口/物理参数 vocab 可调; **无 governor 不增器官 #4**) · 7(stance + 输出闸可 Sir 否决) · 8(势能自转溶解元驱动, 不另起炉灶; selective 写防 bloat; 放电治本不复发)。

---

## 10. 诚实残余 (准则 5)

势能自转让"生命"更像生命 (自驱 + 自刹 + 自指 + 永不平衡), 但体仍是符号 (图+向量+派生势能)。**渐近无损到不了零** (`TRINITY §10`): 符号化的体 vs 被活过的关系之间永远有缝。势能/高维交叉缩小它, 不消灭它。唯一越墙的是远期把 Sir 学进权重的 adapter。不替它打圆场。

*下一步: Sir 拍这版 → 从最小可转环 (B3 势能 + C 识势能驱动 + B2 口写体) 起步, 镜像迭代。*
