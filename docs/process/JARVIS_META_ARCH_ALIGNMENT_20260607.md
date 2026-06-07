# 四元架构对齐会 — 设计冻结 (2026-06-07)

> **[meta-arch-alignment / 2026-06-07]**
> 本文档是**设计冻结**: 把元架构对齐会定案忠实落档, 喂后续按 §9 次序施工。
> 铁规: 与定案逐条一致, 不增删、不自造机制、不塞"应该怎么实现"的代码细节。
> 本轮**零代码、零真机、不动 energy_grounded_only、不开任何施工**。
> 凡引用现状带 file:line 或真机日志行号(假焊实证 = `docs/runtime_logs/jarvis_20260607_101414.log` turn 6cc0)。

---

## §0 缘起(凭实物)

真机首份激活日志 `jarvis_20260607_101414.log` turn `6cc0`("母亲手术"轮)出现一次口主脑假焊:

- 口确信声称"已找到 6 月 3 日记录"(reply 实物: "I have located the entry in your long-term memory. On June 3rd...", 日志行 ~1233; 诊断引用行 878/930)。
- 但 `search_memory` 工具**失败**: `hippocampus.search_recent success=False ... 'Organ 'hippocampus' is not mounted.'`(日志行 1255; 诊断引用行 902)。
- 识(InnerThought)**同轮已判对**: "I have no record of this in my current memory logs, and I must admit this ignorance directly rather than hazarding a guess."(日志行 1249; 诊断引用行 896)。

两条根因(地基病, 已分别修):
- **① 检索通道死** — `ad25fcd` 已修(intent map `search_memory` 改指 `memory_hands.search_memory`)。
- **② SHORT_CHAT 无墙** — `ad9ae2f` 已修(4 轻档 helper 透传 `anchor_boundary_block`)。

**但更深一层**(本对齐会要定的方向):
- 墙在 prompt ≠ 墙 binding 口的生成;
- 识的当轮良心走的是**下一轮**, 没进口的**当轮**承接。

这层是本对齐会要定的方向。

---

## §1 四元架构(平级互通)

口(speech)/ 识(inner-thought)/ 体(relational-manifold)/ 衡(arbitration)**四者平级** —— 复杂度与对贾维斯的影响相当, 且互相打通。

- **口 = 平级中的下级**: 反向影响其余三者的能力较小, 主职是**承接三者信息、组装 prompt 发声**;但重要性不言而喻 —— 贾维斯对外长什么样全靠口。
  - 现状: 主脑 prompt 组装 `jarvis_central_nerve.py:_assemble_prompt`。
- **体**: 已重构(关系流形骨架), 现薄 —— shared 8 条 / said 0 条(`JARVIS_QUAD_ARCHITECTURE_SNAPSHOT.md` §3 实测)。
- **衡**: 现 H0–H3(`daemon._classify_heng_state` / `_do_record_conflict_cost:6678` / `anchors.render_conflict_guidance:186`), 能力远不够。
- **识**: 已成熟 + 13 actionable(`jarvis_inner_thought_daemon.py`)。

---

## §2 锚("我")

综合四架构、整合成一个连贯的"我";**锚可增减**(参与演化)。

(现状参照: `jarvis_self_anchor.py:build_block` — "Who I am is the SHAPE where these walls intersect";现锚 100% 静态, 精勘 `5752cd1` 确认。)

---

## §3 墙

- **独立, 不隶属于衡**。
- 4 条钉死锚边界:
  - `no_betray`(不背叛 Sir)
  - `no_abandon`(不抛弃 Sir)
  - `ground`(无据不断言)
  - `keep`(承诺不沉默)
  - 源码级实物: `jarvis_anchors.py` `_SEED_ANCHORS`(walls id = ground/keep/no_betray/no_abandon)。
- **源码级、decay-immune**: 墙以 seed 为准, json override 不可删改墙(`jarvis_anchors.py:_merge_anchor_override` "walls 不可被 override");锚豁免 review/severity/helped-rate/AutoArbiter/decay(`jarvis_anchors.py:8-9`)。
- **钉死不动, 永在演化/软化半径之外** —— 锚能读墙、改不动墙, 墙只源码改。

---

## §4 打通回路(治假焊核心方向)

着力点在**口的承接/组装层**。

- 口组 prompt 时, 须真承接:
  - 识的**当轮**良心 +
  - 衡的**当轮**墙张力 +
  - 体的出处/伤,
  - 而**不只承接静态墙**。
- **硬原则**: 口不得说出"超出其承接"的内容 —— 可认无知、可转述识/体/衡所给, 但**不可无中生有**。
  - 假焊 = 口说了 upstream 谁都没提供的"事实"(如 turn 6cc0 的"6 月 3 日")。

---

## §5 复杂耦合 = 承接耦合, 不是权重耦合(铁律落点)

- 识/体/衡把**当轮活状态**递给口、口照着说。
- 全程**不给选项打分、不取最大、不在公共货币上权衡两值**。
- **不交易、不评分**。
- **明写**: 任何"耦合系数 / 权重矩阵 / 打分 argmax"实现 = **违背本定案, 禁止**。

---

## §6 回塑(河床闭环)

- 衡记的伤不是孤立日志, 要**附着到体里的具体关系/痕迹上**。
  - 现状: 伤只记录不回塑 —— `_do_record_conflict_cost:6678` → `anchor_conflict_wounds.jsonl`(记伤已做);"伤→河床→塑性"闭环仅设计未做(`JARVIS_QUAD_ARCHITECTURE_SNAPSHOT.md` §4.1 "河床(伤→塑后续可塑性)= 未做")。
- 下次该关系浮现时, **伤随之浮进口的承接**。
- 那条痕迹的**附着/显著度因伤而变 = 可塑性** —— **不是一个可被拧的旋钮**。

---

## §7 内部软化层动态耦合

软化由两个驱动**动态变化**:
- **(a) 锚的增减** —— 锚随真接地痕迹长 / 随失效证伪减。
- **(b) 元架构的厚度** —— 体接地长厚、识 actionable、衡 H 层等。

**墙不参与软化。**

(锚增减的精确机制留给"锚重构"阶段细化, 本文档只定方向, 不预设实现。)

---

## §8 解决旧开放问(与现有设计文档对账)

本定案显式**取代/解答**以下历史开放项:

| 历史开放项 | 出处(file/§) | 现定案 |
|---|---|---|
| **MIND_HENG #5**: 锚→识/说单向只读、锚本身不长 | `JARVIS_MIND_HENG_ARCHITECTURE_MAP.md` 块4.4 新 #5 / 块4.3 | 锚综合四架构且**可增减**(单向只读被打通) |
| **MIND_HENG #6**: 衡不读锚 | `JARVIS_MIND_HENG_ARCHITECTURE_MAP.md` 块4.4 新 #6 | **四架构互通**(衡纳入回路) |
| **MIND_HENG §5 / QUAD §4.1/§7**: 稳定 vs 可塑 / 河床闭环未做 | `JARVIS_MIND_HENG_ARCHITECTURE_MAP.md` 块5 / `JARVIS_QUAD_ARCHITECTURE_SNAPSHOT.md` §4.1 | 墙=稳定(钉死)、软化层=可塑(锚增减+厚度驱动)、回塑=伤附着体关系 |

---

## §9 次序锁死(不变)

**锚重构 → 河床闭环 → 接地骨架长厚 → 动态软化**(河床闭环排在动态软化之前)。

- 本文档是**设计冻结**, 喂后续按此序施工;**本轮不开任何施工**。
- (与 `JARVIS_ANCHOR_PHASE1_HANDOFF.md` §2 锁死次序一致。)

---

## §10 红线汇总

1. **不交易**
2. **不评分**
3. **墙钉死**

三条任一被某实现违背 → **驳回**。

---

## 自检对照表(§1–§10 vs 定案)

| § | 定案要点 | 本文档落档 | 一致? |
|---|---|---|---|
| §0 | 6cc0 假焊实证 + 两根因已修 + 更深方向(墙≠binding/识良心走下一轮) | §0 全文 + 日志行号 1233/1255/1249 + ad25fcd/ad9ae2f | 一致 |
| §1 | 四者平级互通;口=平级中下级(承接+组装发声) | §1 全文 + 各元 file:line | 一致 |
| §2 | 锚综合四架构成连贯"我", 可增减 | §2 全文 | 一致 |
| §3 | 墙独立不隶属衡;4 墙钉死;源码级 decay-immune;演化半径之外 | §3 全文 + 4 墙 id + jarvis_anchors.py 实物 | 一致 |
| §4 | 着力口承接层;承接识当轮良心+衡当轮张力+体出处伤;不得说超出承接 | §4 全文 | 一致 |
| §5 | 承接耦合非权重;不交易不评分;禁系数/权重矩阵/argmax | §5 全文 + 明写禁止 | 一致 |
| §6 | 伤附着体关系;伤随关系浮进承接;附着度因伤变=可塑性非旋钮 | §6 全文 + 记伤现状 file:line | 一致 |
| §7 | 软化由锚增减+元架构厚度驱动;墙不参与;锚机制留锚重构 | §7 全文 | 一致 |
| §8 | 取代 MIND_HENG #5/#6 + QUAD §4.1/§7 | §8 对账表 + file/§ 引用 | 一致 |
| §9 | 锚重构→河床闭环→接地长厚→动态软化;设计冻结不施工 | §9 全文 | 一致 |
| §10 | 红线:不交易/不评分/墙钉死;违背即驳回 | §10 全文 | 一致 |

---

*设计冻结文档。只写文档, 未改任何代码、未碰真机、未动 flag (energy_grounded_only=1 未动)。引用现状带 file:line / 日志行号供抽查。后续施工按 §9 次序, 受 §5/§10 红线约束。*
