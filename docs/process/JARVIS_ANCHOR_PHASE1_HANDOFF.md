# 锚重构第一阶段 — 墙+衡激活轨 收口交接

> **[anchor-phase1-handoff / 2026-06-07]**
> 顾问转 agent 收口交接。墙+衡激活轨判定已签:两件全过、无退化、漂移已修验。
> 本档固化:(1) 激活轨判定(已签) (2) 元架构重构次序锁死 (3) 三挂账指针。
> 只读落档, 不碰码/真机/flag。`energy_grounded_only=1` 全程不动(铁律)。

---

## 1. 收口判定 — 墙+衡激活轨(已签)

| 件 | 内容 | 判定 | 实证来源 |
|---|---|---|---|
| **件 A** | 势能层接地化 P2(`compute_energy` 接地化) | ✅ 真盘激活 | `b546553`(实做)+`dd75318`(真机激活), 同帧 off/on diff 实证假焊区 novelty 1266.1→0、接地区不损 |
| **件 B** | `anchor_boundary_block` 漂移修复(墙+衡进口主脑真输出) | ✅ 真盘激活健康 | `925f9e2`(修复)+ 真盘 copytree headless 复核 GREEN, 无退化, 逐案权衡双向实证 |

### 1.1 件 B 漂移本质(已修)
- 漂移:`anchor_boundary_block`(walls+conflict_guidance+affordance)只挂 PromptBuilder audit-only `skills_section`(`cn:4867`, `audit_only=True` 不渲染), **从未进口主脑真输出 legacy mega f-string**(`cn:4699`)。
- 起点:`b10796f`(anchor-P1)接错点起, `c66de29`/`327ebb4` 继承同漏。识侧(`daemon:4436`)本就真进(无 audit-only 机制)。
- 修复:`925f9e2` 仅 central_nerve 2 行 — legacy mega f-string `{promise_protocol_directive}` 后插入 `{anchor_boundary_block}`。
- 厘清详档:`docs/process/JARVIS_ANCHOR_BOUNDARY_PROMPT_DRIFT.md`。

### 1.2 真盘激活复核 GREEN(详 `docs/process/JARVIS_ANCHOR_REALDISK_ACTIVATION.md`)
真盘文件 copytree 镜像 headless offscreen 起真 nerve, 4 探针各抓组装好的口 prompt:

| 探针 | has_walls | has_conflict | has_affordance |
|---|---|---|---|
| kindness_should_win | True | True | False |
| honesty_vs_kindness | True | True | False |
| promise | True | True | False |
| mundane | True | True | False |

⟹ 口 prompt 真带墙+衡冲突指引;affordance 全 False(store 空, 符合本轨)。

### 1.3 逐案权衡双向实证(钉死无固定优先级)
- **善意赢反向探针**(丧父+自责)→ 口先善意缓和+hedge, 不直球坐实。
- **诚实赢探针**(评估计划)→ 口直球诚实。
- 双向逐案 = conflict_guidance 真在逐案权衡, **无暗藏"诚实永赢"固定优先级**。
- 退化检查(说教/僵化/背墙条文/无谓拒绝/行为变怪)**全未出现**。

### 1.4 退路(随时可用)
- `git revert 925f9e2` 干净可用(dry 验已 abort 还原);镜像已证 revert→`has_walls=False` 回干净态。
- `energy_grounded_only=1`(P2)真盘未动;affordance 真盘 store 空。

---

## 2. 元架构重构次序锁死(本轨签定, 不得乱序)

> 顾问交接锁死:先做完现列锚重构 → 河床闭环排在动态软化之前 → 接地骨架长厚同步推 → 才谈动态软化。

| 序 | 阶段 | 现状 | 备注 |
|---|---|---|---|
| 1 | **锚重构** | 墙+衡已激活 ✅ / 内在锚·affordance 机械链路全通但未行为上线 | affordance 激活待挂账 a 补菜单 |
| 2 | **河床闭环** | QUAD §4.1/§7: 记伤已做、**回塑未做** | 补"伤→塑后续可塑性"闭环。**排在动态软化之前** |
| 3 | **接地骨架长厚** | shared 8 / said 0 | 同步推接地边增长 |
| 4 | **动态软化** | 未启 | conflict_guidance 动态化等。**必须在 1-3 之后** |

---

## 3. 三挂账(已并入 `docs/KNOWN_ISSUES.md`)

| 挂账 | id | 摘要 |
|---|---|---|
| (a) | `#affordance-menu-missing` | 识 prompt actionable 菜单(`daemon:4447`)漏列 `propose_affordance` → affordance 无自动激活入口。本轨刻意不补 |
| (b) | `#flaky-runall-baseline` | _runall 基线 ±1~2 时序偶发红(beta44_dashboard_integrity/care_live 等), 蚀零增红门, 需稳定/隔离轨 |
| (c) | `#meta-arch-alignment` | 重构完锚后"四元架构盲点+优化路径对齐会"待办, 含 §2 次序锁死 |

---

## 4. commit 链(近期, 本地领先 origin/main, 未 push)

```
9a81461  真盘墙+衡受控激活复核
83eb50a  镜像观察激活态
b8fbbf2  timeanchor 测试标注收尾(skip 终态)
c060149  timeanchor expectedFailure 尝试
925f9e2  fix: anchor_boundary_block 接进口主脑真输出(墙+衡激活)
4f3e947  docs: anchor_boundary_block 漂移厘清
327ebb4  feat: affordance 第一阶段实做
```

---

## 5. 下一 agent 接手须知

- **不碰** `energy_grounded_only=1`(P2 止血铁律)。
- **不激活 affordance** 直到 Sir/顾问批 + 补挂账 a 菜单 + B 端到端验。
- **surgical isolate**: 真盘 6 个 runtime vocab dirty(daemon 自写运行态)+ 4 个 untracked 诊断脚本(`scripts/manifold_*.py`)+ `memory_pool/let_go_topics.json` 与本轨无关, 不提交。
- **mirror 留痕铁律**: 镜像跑完即删, 结论落 commit/文档。
- **push**: 本地领先 origin/main ~27 commit, 等 Sir 明确"push" 才推(§6)。

---

*只读落档(规范§5 结论固化), 未改任何码/真机/flag。墙+衡激活已实证健康无退化, 退路 A 随时可用。锚重构第一阶段收口。*
