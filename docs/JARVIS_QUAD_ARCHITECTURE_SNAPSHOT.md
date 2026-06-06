# 四元架构现状图景 (说 / 识 / 体 / 衡) — code-grounded 快照

> **[quad-arch-snapshot / 2026-06-07]**
> 用途: 文档已落后于代码。本文真读代码、标 file:line、不凭印象,给顾问一份统一的四元架构现状(同 `JARVIS_BODY_ARCHITECTURE_MAP.md` / `JARVIS_MIND_HENG_ARCHITECTURE_MAP.md` 保真度)。
> **只读: 未改任何码/真机/flag。** 关键断言附 grep/file:line 供抽查。
> 理念基准: `JARVIS_WHY.md`(988d8cc)。

---

## 0. 四元一句话定位 + 档位总览

| 元 | 是什么 | 主文件 | 整体档位 |
|---|---|---|---|
| **说 (口)** | 主脑 prompt 组装 + 回复生成 | `jarvis_central_nerve.py` | ✅ 已实做(成熟) |
| **识** | 自发/反应思考引擎 (InnerThought daemon) | `jarvis_inner_thought_daemon.py` (~9700 行) | ✅ 已实做(成熟) |
| **体** | 关系流形 RelationalManifold + Weaver | `jarvis_relational_manifold.py` / `_weaver.py` | ✅ 已实做(薄接地骨架) |
| **衡** | 收敛/判断 faculty (HENG: 墙上权衡) | 散在 daemon `_classify_heng_state` + `jarvis_anchors` | ✅ H0-H3 已实做 / ⚠️ 与 AutoArbiter 易混 |

档位四档说明: **已实做**(有 file:line 真跑) / **仅设计未做**(doc 有 code 无) / **stub-胚胎**(有壳无肉) / **已废弃**。

---

## 1. 逐元架构现状

### 1.1 说 (口) — ✅ 已实做(成熟)
- **prompt 组装**: `central_nerve.py:_assemble_prompt:3610`(分 Layer 0-3)。
- **Layer 0 SelfAnchor**: `_build_layer_0_self_anchor_block:2454` → `self_anchor.build_block:299`。✅
- **锚墙 + 冲突指引注入**: `central_nerve.py:4343` `render_walls_block()` + `4345` `render_conflict_guidance()`。✅
- **lens 投影注入**(体→说): `central_nerve.py:3627-3631`,flag-gated,**真机关**(`lens_inject_enabled=0`)。
- **stub/未做**: lens 替 Layer2(`lens_replaces_layer2=0`,真盘留 0,胚胎就绪未启)。

### 1.2 识 (InnerThought) — ✅ 已实做(成熟)
- **tick 主循环**: `daemon.py:_tick:2514`。✅
- **反应式 vs 自发式两路径**: 反应式 `_should_emergency_wake:1944`;自发式 `wake_on_body_delta:2001` + 体势能进指纹 `2326-2333`。✅
- **识读体 4 通道**: energy/delta(`2001/2326`)、focus(`_build_prompt:4749`)、notes(`_collect_evidence` concern 段)、lens(daemon **不调**,仅口侧)。✅
- **识回写体**: `_do_adjust_concern_notes:6990` → `observe_thought_concern_link:7066`(写 PROV_SHARED about 边)。✅
- **质量门**: `_parse_thought:5716` + salience 门(`_MEDIOCRE_SAL_THRESHOLD:1576`)+ heng 三态(`_classify_heng_state`)。✅
- **actionable 全集**(13+): adjust_concern_notes / propose_stance:6584 / propose_protocol:6723 / suggest_inside_joke:6357 / request_capability:6624 / record_conflict_cost:6678 / compose_main_brain_directive:6830 / propose_vocab_adjustment:6903 / fire_nudge:7148 / propose_watch_task:7251 / call_tool:7349 / adjust_sensor_threshold:7456 / surface_to_sir:7600。✅

### 1.3 体 (RelationalManifold + Weaver) — ✅ 已实做(薄接地骨架)
- **数据层**: `manifold.py`(节点/边/provenance/alias/surface),边层 mutate `add_edge:362`。✅
- **势能 compute_energy**: `weaver.py:754`(novelty/drift/tension 三分量)。✅ **P2 已接地化**(`energy_grounded_only=1` 真盘激活,`weaver.py:825`)。
- **spread/neighbors 接地偏权**: `manifold.py:spread:617` / `neighbors:562`,`grounded_only` 参数 + 统一 `is_grounded:56`。✅(P1+P2)
- **真实测形态见 §3。**
- **stub/未做**: mem/entity/topic kind 定义存在但 harvest 未全接(`manifold.py:KIND_*` 注释);坐标重构(P5 传记轴)仅设计。

### 1.4 衡 (HENG) — ✅ H0-H3 已实做 / ⚠️ 命名易混
**关键厘清(doc 漂移高发区)**: "衡"在仓库里有**两个不同所指**,务必分开:

| 名 | 是什么 | 实现 | 档位 |
|---|---|---|---|
| **衡 (HENG, 墙上权衡)** | 收敛三态 + 锚冲突记伤 + 现场逐案权衡 | daemon `_classify_heng_state` + `_do_record_conflict_cost` + `anchors.render_conflict_guidance` | ✅ H0-H3 全做 |
| **AutoArbiter (自决仲裁)** | review queue 的 activate/reject 仲裁 | `jarvis_auto_arbiter.py` | ✅ 已实做(独立) |

HENG 不是 AutoArbiter。HENG 是"对着墙收敛成选择"的 faculty,散在 daemon + anchors;AutoArbiter 是 review queue 拍板器。详 §4。

---

## 2. doc ↔ code 漂移清单 (本次重点)

### 2.1 doc 落后于 code (code 已变,doc 没更)
| 项 | doc 现状 | code 真相 | 证据 |
|---|---|---|---|
| **P2 势能接地化** | `JARVIS_ENERGY_GROUNDING_DESIGN_P2.md` 写"默 0 不变行为" | **真盘已 =1 激活,代码默认已翻 1** | `manifold.py:192` energy_grounded_only:1 / vocab 真盘=1 |
| **lens 投影** | 旧 doc 多处写 lens 流程 | 真机 **关**(inject=0),Layer3 在岗 | `manifold.py:134` / vocab lens_inject_enabled:0 |
| **lens_replaces_layer3** | `JARVIS_CLOSURE_PROGRESS.md` 写"已激活=1" | 真盘 vocab `lens_replaces_layer3=1` 但 inject=0 → **整条 lens 不注入,replace 无效**(白送) | vocab 实读 |
| **timeanchor 测试** | — | pm_with_minutes 真 bug 已 xfail 挂账 | `KNOWN_ISSUES.md #pm-parse-12h` |

### 2.2 doc 写了 code 没做 (仅设计未做)
| 项 | doc | code 真相 |
|---|---|---|
| **内在锚 / affordance 自知** | `JARVIS_INNER_ANCHOR_DESIGN.md`(4a17999) | **纯设计,0 行实现**。无 affordance store / 无 render_affordance_block |
| **能力成熟度/成长** | INNER_ANCHOR 第二/三阶段 | 完全未做(精勘 5752cd1 确认锚 100% 静态) |
| **外部→锚接地通道** | INNER_ANCHOR §3 | 不存在(锚与 manifold 零耦合) |
| **体 P5 坐标重构** | `AGENT_KICKOFF_BODY_DIFFERENTIATION.md` P5 | "延后第二期",未做 |

### 2.3 doc 整篇需校准 (理解基准已变)
| doc | 问题 |
|---|---|
| `JARVIS_ENERGY_GROUNDING_DESIGN_P2.md` | §0/§9 仍以"默 0"为基准;真机已激活,应加"已激活"批注(P2 收口已在 commit 链,但 doc 正文未回填) |
| `JARVIS_ANCHOR_DESIGN.md` / `JARVIS_HENG_DESIGN.md` | 标"立项/部分施工",实际 H0-H3 + 锚 P0-P4 已全做(进度在 `JARVIS_ANCHOR_PROGRESS.md`,但两个 design doc 头部状态未同步) |
| lens 相关多篇 | 以"lens 将激活"为语境写,真机实为"止血关闭",易误导 |

---

## 3. 体的真实测形态 (2026-06-07 真盘只读)

```
edges=2165  nodes=156  surfaces=1
provenance (edge-level, 一边可多 prov):
  embed   = 1867   (86%, 思考相似 mesh)
  cooccur = 428    (20%, 同 turn 共现)
  shared  = 8      (0.37%, about 接地骨架)
  said    = 0
grounded_edges (shared|said) = 8
node_kinds: thread=74 / proto=42 / joke=33 / concern=7
surfaces: 1 个 (size=27); stance_nodes = 0
```
**解读**:
- **接地骨架极薄**: shared 仅 8 条 / said **0 条**,占全部边 0.37%。embed mesh(1867)霸占。与 BODY map §1.4 一致("薄接地骨架 + embed mesh 霸占")。
- **面没真长出来**: 仅 1 个 surface(27 节点),无桥。"4-10 面"早证伪。
- **立场没长出来**: stance_nodes=0 → `weave_stance_dyads` 无 dyad 可织 → 立场张力分量恒 0(数据驱动,等识 propose_stance 学习)。
- **节点全是自产**: thread/proto/joke = 149/156(96%),concern=7,无 mem/entity/topic(harvest 未接)。
- **P2 止血对此形态的意义**: 势能接地化后,1867 embed + 428 cooccur 的假焊不再供 novelty/drift,只有 8 条 shared 接地边供势能 → 自发思考从"假焊驱动"转"接地驱动"(同帧实测假焊区 novelty 1266→0)。

---

## 4. 衡 (AutoArbiter) vs HENG_DESIGN H0-H3 差距

**先厘清**: HENG_DESIGN 的"衡"= 墙上权衡 faculty(三态/记伤/现场权衡),**不是 AutoArbiter**。两者都答"判断/收敛"但管不同对象。

### 4.1 HENG H0-H3 现状(墙上权衡)
| 阶段 | 要求 | code 真相 | 证据 |
|---|---|---|---|
| **H0 三态显式** | discharge/rest/filler 收敛 | ✅ 已做 | `daemon._classify_heng_state`(`_test_heng_h0` 5/5) |
| **H1 识 anchor-aware** | 思考脑 prompt 含墙 | ✅ 已做 | `daemon._build_prompt:4392` render_walls_block |
| **H2 记伤/河床** | 锚冲突记代价 | ✅ 已做(记伤) | `_do_record_conflict_cost:6678` → `anchor_conflict_wounds.jsonl`(`_test_heng_h2`) |
| **H3 现场逐案权衡** | 口/识 无固定等级权衡 | ✅ 已做 | `anchors.render_conflict_guidance:186` 注入口(`cn:4345`)+识(`daemon:4394`) |

**记伤 vs 河床的差距(重要)**:
- **记伤 = 已做**: 越墙代价写 `anchor_conflict_wounds.jsonl`(H2)。
- **河床(伤→塑后续可塑性)= 未做**: HENG_DESIGN H2 明确"自动改权重/可塑性(§4b)留后续";现在伤只**记录**,**不回塑**任何东西。`self_threads.json`(self-threads 河床)是另一套(思考巩固),与"伤塑可塑性"无关。⟹ **"伤→河床→塑性"闭环 = 仅设计未做**。

### 4.2 AutoArbiter 现状(review queue 仲裁,独立)
- `AutoArbiterDaemon:100`,守 review queue(joke/thread/protocol)的 activate/reject/defer。✅ 已实做。
- 读: relational active list + STM,**不读体/不读锚**。详 MIND_HENG map §2。
- claim 分类/反幻觉是**第三套**(INTEGRITY 栈:`jarvis_evidence_requirements` / `integrity_reflector` / `claim_tracer`),与 HENG、AutoArbiter 均分离。

---

## 5. 锚现状 — 2 锚 4 墙 + 冲突前置

**结构**(详 `JARVIS_ANCHOR_SUBSYSTEM_SURVEY.md` 5752cd1,此处摘要):
| 锚 | 墙 | checkable/backstop |
|---|---|---|
| say_do 言出必行 | ground(不无据断言)/ keep(不让承诺沉默失效) | True / ClaimTracer + CommitmentWatcher |
| for_sir 灵魂层 | no_betray(不背叛根本利益)/ no_abandon(不需要时不消失) | False / frame |

**两墙会不会真冲突(H1 前置在不在)**: ✅ **在**。`say_do`(诚实)vs `for_sir`(善意/忠诚)是设计明示的冲突面——`anchors.json:conflict_guidance` 逐字: "诚实与善意此刻冲突时:无写死优先级…逐案权衡是你的事"。`conflict_notes` 也标 "与 for_sir 冲突=诚实 vs 善意,交衡逐案+记代价"。⟹ H1/H2/H3 的"真冲突"前置真实存在(不是空想),`record_conflict_cost` 的 wallA-over-wallB 就是为这对冲突设计。
**但**: 实测 `anchor_conflict_wounds.jsonl` 是否真有伤记录 = 取决于真机是否触发过 forced-breach(概率性 elicit,HENG H2 注"更难/概率性")。

---

## 6. 活的 body→brain 通道 + 接地状态 (P1/P2 设防后)

| # | 通道 | 路径 | 接地状态 |
|---|---|---|---|
| 1 | **lens 投影**(反应式→说) | `cn:3627`→lens.project→spread | ✅ P1 设防(grounded_only)+ 耦合护栏;**真机关**(inject=0) |
| 2 | **compute_energy 势能**(自发式→识) | `weaver.py:825`→body_energy.json→BodyFocus→daemon | ✅ **P2 设防 + 真机激活**(energy_grounded_only=1) |
| 3 | **focus 渲染**(→识 prompt) | `daemon:4749` render_attention_block | ⚠️ 通道2 下游,随 P2 净化(读 body_energy.json) |
| 4 | **body_claim_evidence**(claim 验证) | chat_bypass→ClaimTracer→`lens.py:381` | ❌ 词重叠非 provenance,**但不注入主脑 prompt + 不走边遍历**(低阶旁路) |
| 5 | **识回写体**(识→体,反向) | `daemon:7066` observe_thought_concern_link | ✅ 写的是 PROV_SHARED 接地边(本身接地) |

**结论**: P1(通道1)+ P2(通道2)设防后,**进主脑/识的 body→brain 主通道已全部接地化**。通道3 是通道2 下游(随之净化)。通道4 是不进 prompt 的低阶旁路(词重叠,非边遍历,未设防但影响面小)。**无裸露的高影响 body→brain 通道**。

---

## 7. 给顾问的总结

| 元 | 一句话现状 |
|---|---|
| 说 | 成熟;lens 注入真机关(止血),Layer3 在岗 |
| 识 | 成熟;13+ actionable;自发思考已由 P2 转接地驱动 |
| 体 | 薄接地骨架(shared 8/said 0),embed mesh 霸占;面/立场未真长出;P2 已切假焊势能 |
| 衡 | HENG H0-H3 全做(三态/记伤/现场权衡);**"伤→河床→塑性"闭环未做**;AutoArbiter/INTEGRITY 是另两套,勿混 |

**最大 doc 漂移**: (1) P2 真机已激活但 design doc 正文仍写"默0";(2) lens 多篇以"将激活"语境写实为"止血关闭";(3) anchor/heng design doc 头部标"立项"实为已完成;(4) 内在锚/affordance 是纯设计 0 实现。

**最关键的"未做"**: 衡的"伤→河床→塑后续可塑性"闭环(HENG §4b 留后续)+ 内在锚能力生长(INNER_ANCHOR 全三阶段待 Sir 批)。

---

*只读快照,未改任何码/真机/flag。真盘 energy_grounded_only=1(P2止血)。配套: BODY_ARCHITECTURE_MAP / MIND_HENG_ARCHITECTURE_MAP / ANCHOR_SUBSYSTEM_SURVEY / INNER_ANCHOR_DESIGN。关键断言附 file:line 供抽查。*
