# JARVIS 全流程闭环 + 模块内敛 (Full Closure & Convergence on 说/识/体)

> **状态**: master design / 2026-05-31 (Sir+Cascade 架构总图对话蒸馏)。待拍 → 分阶段做。
> **缘起 (Sir)**: "结合刚做的体/识/说地基, 完成贾维斯所有模块的内敛和全流程闭环。"
> **前提 (已建)**: 体六层 + 势能自转环(MVL) + 强闭环写侧(E)。详 `JARVIS_TRINITY_ARCHITECTURE.md` / `JARVIS_VOICE_AND_MIND_REFACTOR.md`。
> **本文是总图**: 把 SOUL/nudge/言出必行/commitment 等所有遗留**收敛**进 说/识/体, 闭合全部开口端。

---

## 0. 一句话

> **说/识/体 是脊柱; hippocampus 永不动是锚 (+ Sir 否决是活 oracle); 言出必行/复杂度保持是横切。
> 所有遗留模块都是这根脊柱的散件——优雅靠把它们"内敛"折叠进三层 (更少不是更多), 让每个信号都
> 经体闭一个环, 无孤儿信号。当每个输入入体、每个输出回体、每条 claim 对锚审一致, Jarvis 就是
> 一个锚在不可变事实上的自一致有机体。**

---

## 1. 本体: 脊柱 + 锚 + 横切

| 角色 | 是谁 | 职责 |
|---|---|---|
| **脊柱 说(口)** | 主脑 LLM + 工具(手) | prompt→话/行动; 有损投影; 反应式。本身是个**冻结 Transformer** |
| **脊柱 识** | 思考脑 daemon | 持续 attend 体高势能区 / 反思 / 形成 stance / 写回体 |
| **脊柱 体** | 关系流形 | 点(引用 hippo)·边·面·立场·势能; 活的关系结构 |
| **锚 hippocampus** | SQLite 永久记忆 | **永不动**: 体只引用不改写。不可变事实地基, 防自指漂移 |
| **锚 Sir** | 真人 | 准则 7 否决权; 活的 ground-truth oracle |
| **横切 言出必行** | ClaimTracer/PreFlight/lineage | 一致性损失: 审说的 claim vs 体/hippo/Sir |
| **横切 复杂度保持** | 织网者 merge/metric | 防体积膨胀, 保信息密度 |

**关键洞察 (Transformer 类比)**: 口是内层冻结 Transformer (锚=权重); 体/识 是套在外面的**符号在线能量系统** (锚=hippo+Sir), 补口"冻结学不动"的病。言出必行 = 耦合两层的损失。

---

## 2. 内敛映射: 每个遗留模块 → 折进三层 (这是"内敛"的核心)

> 优雅不是加模块, 是**把散件收敛进脊柱 + 删平行表示** (准则 6 #4)。

| 遗留模块 | → 收敛进 | 动作 |
|---|---|---|
| SOUL Layer0 自我锚 | 说 persona + 体 不变量 | persona 留口; identity 不变量入体 |
| **SOUL Layer2 relational** | **体** | ⚠️ **CONVERGE**: relational_state 是体胚胎 → 删平行, 统一为体 |
| **SOUL Layer3 attention** | **识 attend + 口 透镜** | ⚠️ **CONVERGE**: 已体势能驱动, 删旧 attention 块 |
| SOUL Layer4/5 reflect/eval | 识(反思) + 言出必行(评估) | CONVERGE: reflect=识, eval=integrity |
| **Nudge 群** (NudgeGate/SmartNudge/ProactiveCare/Wellness/Conductor/OfferGuard) | **体 能量 sensor** | ⚠️ **DEGRADE**: publish-only → 体张力/能量; 决策交识/口 (β.5.0 已起, 收尾) |
| Commitment/Promise | 体 节点 + 言出必行子环 | keep (体结构) |
| IntentResolver/tools | 口 的手 (action reaction-space) | keep |
| 硬编码残留 (_X_PATTERNS 等) | 准则 6 vocab + CLI | MIGRATE (持续) |

---

## 3. 全部闭环: 5 个环, 都经体闭合

```
       ┌─────────── 感知环 ───────────┐         ┌──── 验证环 (言出必行) ────┐
 sensor/nudge → 体能量 → 识attend → 口 → world → Sir → (sensor)
                  ▲         │           │                              │
       维护环     │ merge   │势能环      │ 口写回体(④)                   │ claim 审 vs 体/hippo/Sir
   (复杂度)decay/prune      ▼           ▼                              ▼
                  └──── 体 ◄── 强闭环: 识学→stance→Sir仲裁→透镜→口→outcome→体
                              (学习环)
                         锚: hippocampus 永不动 + Sir 否决 (防自指漂移)
```

| # | 环 | 路径 | 状态 |
|---|---|---|---|
| 1 感知 | sensor/nudge→体能量→识→口→world→Sir→sensor | 🔶 nudge 还直推, 没全进体能量 |
| 2 势能(内) | 体能量→识/口→口写回体→能量 | ✅ 闭 (MVL) |
| 3 学习(强闭环) | 识学→stance→Sir仲裁→透镜→口→outcome→体 | 🔶 前半闭, **后半开**(outcome) |
| 4 验证(言出必行) | 口claim→审 vs 体/hippo/Sir→纠正→识/口+体记 | 🔶 闭, **没用体当证据** |
| 5 维护(复杂度) | 体→织网者 merge/decay/prune→体 | 🔶 decay/prune 闭, **merge 开** |

---

## 4. 开口端 → 闭合 (5 个 closure, 这是工作清单的核心)

| closure | 做什么 | 闭哪个环 | ROI |
|---|---|---|---|
| **A outcome→stance** | Sir 采纳/反驳 → reinforce/weaken stance + 标 outcome | 学习环后半 | ★最高 (学到的经实践沉淀) |
| **B 言出必行→体** | 说的关系类 claim 对**体**审一致 (体作 evidence 源) | 验证环穿体 | 高 |
| **C nudge→体能量** | nudge 信号退化为体张力/能量 (publish-only) | 感知环穿体 | 高 |
| **D 复杂度 merge** | 织网者主动合并决余簇 + 复杂度度量 | 维护环 | 高 (防膨胀) |
| **E SOUL L2/3 收敛** | relational/attention 平行表示折进体/识, 删冗余 | 内敛 | 中 (真优雅) |

---

## 5. 全流程闭环判据 (何时算"全闭")

Jarvis 是全流程闭环 ⟺ 同时满足:

1. **无孤儿信号**: 每个 publish 的信号在环里有 consumer (no dead publish)。
2. **每个输入入体**: 感知 (sensor/nudge/对话) → 体。
3. **每个输出回体**: 口/识 输出 → 体 writeback (④)。
4. **每条 claim 对锚审**: 言出必行 vs 体 + hippocampus + Sir。
5. **锚在不可变**: hippocampus 永不动 + Sir 否决 → 自指环不漂移。

当前缺 #1(nudge 半孤儿) / #2(nudge 没全入体) / #3(outcome 没回体) / #4(没用体审)。补完 closure A-E + hippo guard → 全闭。

---

## 6. 复杂度保持 (anti-volume) + hippocampus 永不动 (anchor) — 两条铁律

- **复杂度 ≠ 体积** (已锁 `body-complexity`): 主动合并决余簇 + 复杂度度量(modularity/决余率)替计数告警 + 面→主题抽象。体应**追踪关系真实丰富度** (homeostasis), 不随时间膨胀。
- **hippocampus 永不动** (已锁 `hippo-immutable`): 体/识/口 任何写不得 mutate hippocampus, 只经 Hippocampus API append。**这是自指环的不动锚**——没它, "自己审自己"会漂移。

---

## 7. 路线 todo (phased; 镜像迭代 + Sir 真机验; 大改逐块退)

| 阶段 | 件 | 依赖 | 状态 |
|---|---|---|---|
| **0 地基** | 体六层 + 势能环 MVL + 强闭环写侧 E | — | ✅ |
| **闭1 学习环** | closure A: outcome→stance (Sir 反应→reinforce/weaken) | E + meta_feedback | 待 ★先做 |
| **复杂度** | closure D: 织网者 merge + 复杂度度量 (已锁必做) | 体-P5 | 待 ★ |
| **锚** | hippo-immutable guard + doc (已锁) | — | 待 (小工) |
| **闭2 感知环** | closure C: nudge 群退化 publish→体能量 | 体-P5/SWM | 待 |
| **闭3 验证环** | closure B: 言出必行用体作 evidence 源 | 体 + ClaimTracer | 待 |
| **内敛** | closure E: SOUL L2/3→体/识, 删 relational_state 平行 | 体 | 待 (敏感, 真机验) |
| **收尾** | D 输出闸统一 / G 口吸收 Layer1/2 / 硬编码清 / F dyad(可选) | A 满意后 | 待 (热路径最后) |

**先做顺序建议**: 闭1(outcome, 补学习环) → 复杂度(防膨胀, Sir 关注) → 锚(小工, 守地基) → 闭2/闭3 → 内敛 → 收尾。

---

## 8. 准则对齐 + 诚实残余

- **准则锚**: 1(势能/透镜/merge 全非 LLM 廉价) · 5(全接地 + 言出必行对锚审) · 6(数据强耦合体/决策集中口/全 vocab; **内敛=减模块不增**) · 7(stance+输出闸+体 errors 可 Sir 否决) · 8(收敛遗留不另起炉灶; merge 防 bloat; 闭环治本)。
- **诚实残余**: 全闭后 Jarvis 仍是符号系统 (口=冻结 Transformer + 体/识=符号能量层)。符号锚 vs 亚符号权重之间那条缝 (`TRINITY §10`) 渐近非零; 唯一越墙是远期把 Sir 学进 adapter (= 把体搬进冻结锚)。不替它打圆场。

*下一步: Sir 拍这版总图 → 从 closure A (outcome→stance, 补学习环) + 复杂度 merge 起步。*
