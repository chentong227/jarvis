# JARVIS 全流程闭环 — 工作进度 (做一步记一步, 抗上下文丢失)

> **用途**: Sir 担心 agent 上下文超限遗忘 → 本文件是**持久化工作日志**。任何接手 agent (含
> 重置后的我) 读本文件 + `git log` 即可完整恢复状态。**做一步, 记一步, 独立 commit。**
> **总图**: `docs/JARVIS_FULL_CLOSURE_AND_CONVERGENCE.md` (设计真相源)。
> **三位一体**: `JARVIS_TRINITY_ARCHITECTURE.md` (体) + `JARVIS_VOICE_AND_MIND_REFACTOR.md` (口/识/势能自转)。

---

## 已建地基 (commit 链, 倒序)

| commit | 件 |
|---|---|
| fd89550 | E 强闭环写侧: 识 propose_stance → stance(review) → 透镜 |
| a5539d9 | B2 fix: 口写体 turn_id 缺失退时间戳 ref (镜像验出) |
| 200750a | C-wake: 体势能驱动唤醒频次 |
| 6f94636 | B2: 口写体 turn→共现边 |
| d6a106b | C-read: 识 attend 体势能 (BODY SIGNALS) |
| bf82c0b | value-backoff baseline (前轮 WIP, Sir 选 A) |
| af47a62 | B: current_focus 桥 BodyFocus + 口透镜势能 seeds |
| 9a41e36 | B3: 体势能 E + body_delta |
| 03b3d47 | churn fix + 开 gate + 势能自转设计 v3 |
| 8ea41eb | 体六层 P1-P6 (manifold/weaver/stance/lens) |

地基测试: 61+ body test 全绿; 镜像端到端验过 (体势能 Δ=12 + 口 grounded reply + 口写体 15 边)。

---

## 闭环工作清单 (8 项) + 状态

> 排序: 先做自包含/低上下文风险 (D1/hippo), 跨模块调查重的 (A/B/C/E) 稳妥推进。

| # | closure | 闭哪环 | 触哪文件 | 上下文风险 | 状态 |
|---|---|---|---|---|---|
| **D1** | 复杂度度量 (metric 替计数告警) | 维护环 | manifold/weaver (熟) | 低 (纯计算) | ✅ (真机验: blob score 0.222 largest_frac 0.778) |
| **G0** | hippo 永不动 guard + doc | 锚 | 新 test + doc | 低 (小) | ✅ (静态守护 2 test) |
| **D2** | 主动合并决余簇 (alias, 不动源) | 维护环 | manifold/weaver/focus | 中 | ✅ (alias+resolve+Weaver检测+focus去重, 4 test) |
| **A** | outcome→stance (Sir 反应 reinforce/weaken) | 学习环后半 | meta_feedback(查) + stance | 中 (需查 meta_feedback) | ⬜ |
| **C** | nudge 群退化 publish→体能量 | 感知环 | nudge 模块群(查) + 体 | 中-高 | ⬜ |
| **B** | 言出必行用体作 evidence 源 | 验证环 | ClaimTracer(查) + 体 | 中 | ⬜ |
| **E** | SOUL L2/3→体/识 收敛, 删 relational 平行 | 内敛 | SOUL/central_nerve(查) | 高 (敏感, 真机验) | ⬜ |
| **收尾** | D输出闸 / G口吸收Layer1/2 / 硬编码清 / F dyad | — | 热路径 | 高 | ⬜ 最后 |

**状态图例**: ⬜ 待 / 🔵 进行中 / ✅ 完成(commit) / 🔶 部分

---

## 逐步日志 (做一步记一步)

- **[起]** 2026-05-31 ~11:00: 建本进度文档。开始 D1 复杂度度量。
- **[D2 ✅]** ~11:20: manifold alias(add_alias/resolve链+防环/persist) + Weaver weave_geometric 检测 cosine>=merge_threshold(0.90) 近重复→add_alias(代表=度数高) + BodyFocus.current_focus 按 resolve 去重 + complexity merged_dups. **不删源(hippo永不动)**, 体层把 dup 当代表。4 test 绿 + 回归绿。维护环闭合(decay/prune/merge 齐)。下一步: A outcome→stance (需查 meta_feedback, 留给新窗口)。
- **[G0 ✅]** ~11:10: hippo 永不动 guard — 静态扫体 5 模块断言无 hippo 写(INSERT/store_memory/...)+ weaver embed 只读注释。2 test 绿。下一步: D2 主动合并 (针对 blob)。
- **[D1 ✅]** ~11:05: manifold.complexity_report (health/score/largest_surface_frac/grounded_frac) + CLI `--complexity` + Weaver 每 weave log + blob/over_dense 告警。真机验: prod manifold = blob (score 0.222, largest_frac 0.778) — 正确抓出 54 节点 blob。3 test 绿。下一步: G0 hippo guard。

---

## 恢复指南 (若上下文丢失, 接手 agent 读这里)

1. 读本文件 + `git log --oneline -15` → 知道做到哪。
2. 读 `JARVIS_FULL_CLOSURE_AND_CONVERGENCE.md` §4 (5 个 closure) = 工作真相源。
3. 体的 API: `jarvis_relational_manifold.py` (边/面/势能) / `jarvis_relational_weaver.py` (织网+能量+口写体) / `jarvis_body_focus.py` (焦点) / `jarvis_relational_lens.py` (投影) / `jarvis_stance.py` (立场)。
4. 测试: `tests/_test_body_*.py` (全绿基线)。改完跑对应 + 相关回归。
5. 红线: hippocampus 永不动 (体只引用); 全接地 (无 trace 边/stance 拒); Sir 否决; selective 写防 bloat。
