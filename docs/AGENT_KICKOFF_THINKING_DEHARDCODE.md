# AGENT KICKOFF — 思考脑去硬编码 (A‑E 类槽 → 势能驱动 kind)

> **给下一 agent (切窗口执行)**。本文是接手指引 + 起始 prompt。
> **设计真相源**: `docs/JARVIS_THINKING_DEHARDCODE_CATEGORIES_DESIGN.md` (必读全文)。
> **轨道**: 思考脑 kind 去硬编码 (口识体收尾最后一条硬编码)。

---

## 1. 进窗口必读顺序 (30 秒)

| 顺序 | 文件 | 为何 |
|---|---|---|
| 1 | `AGENTS.md` | 入口章程 (commit 模板 / 准则 6 不硬编码 / 准则 8 逐块退 / 镜像) |
| 2 | **`docs/JARVIS_THINKING_DEHARDCODE_CATEGORIES_DESIGN.md`** | 本工程设计真相源 (§1 现状依赖表 / §4 phased / §5 机制细节) |
| 3 | `docs/JARVIS_CLOSURE_PROGRESS.md` | 今天的进度 + commit 链 (口识体/放下能力全貌) |
| 4 | `docs/JARVIS_VOICE_AND_MIND_REFACTOR.md` §2/§3/§5 | 势能自转原理 (放电=diversity 的依据) |
| 5 | `docs/JARVIS_AGENT_MIRROR_TESTING.md` | 镜像 A/B 怎么跑 (本工程每 phase 必镜像验) |

---

## 2. 当前进度快照

- **今天完成 (口识体 + 放下能力)**: P1 进度跨天守门 / P2 体势能驱动 tick / P3 拒绝动作不重试 /
  D 接收度输出闸 / E 透镜替 Layer3(prod 已开) / F 立场 dyad / 放下能力 build1‑3 (REST + request_capability
  + 优雅 rest 无冷却阶梯)。
- **唯一剩的硬编码**: 识的 **A‑E 5 类 category 槽** (本工程拔它)。
- **关键已有基础设施 (复用, 别重造)**: 体势能 (`body_focus.current_focus()` 给焦点区) /
  REST 放下 (`_handle_rest_decision`) / actionable 全套 effect (propose_stance/adjust_concern/
  request_capability/...) / 镜像 (`scripts/jarvis_mirror.py`)。

## 3. 当前 commit 链 (起点)

```
7baf139 refactor(放下能力/build3): rest 去写死冷却阶梯 → 存在心跳 floor + 真扰动唤醒
7df288f feat(放下能力/build2): request_capability
bf2d7ae feat(放下能力/build1): REST 决策
da9891b feat(口识体-F): 张力 dyad
a3f30de feat(口识体-E激活): prod 翻 lens_replaces_layer3
4fc4d52 feat(口识体-D): 输出闸 — Sir 接收度单一门
ac497a7 feat(口识体-P2): 体势能进 evidence 指纹 — 势能驱动 tick
```

---

## 4. 本轨 Phase 列表 (按设计 §4; 每 phase 独立 commit + 镜像验)

| Phase | 件 | 预计 | 风险 |
|---|---|---|---|
| **0 脚手架** | `thinking_kind_mode` flag (默 legacy) + `_kind_from_effect()` 派生表 (设计 §5.1) + 双写不改行为 | 2‑3h | 低 |
| **1 summon 锚势能区** | emergent: prompt 用 BODY SIGNALS 焦点区 summon, `<CATEGORY>` 变 optional | 3‑4h | 中 (热路径) |
| **2 冷却→区放电** | emergent: 退 `_compute_free_categories`/`SAME_CATEGORY_COOLDOWN`, diversity 靠区放电 + 过渡软抑制 | 4‑6h | **高** |
| **3 kind=effect** | mediocre/intent/ds‑routing 改 effect 驱动 | 3‑4h | 中 |
| **4 迁依赖+测试** | persist/dashboard/WRC + 全 category 测试迁 | 3‑5h | 中 |
| **5 退 A‑E** | 镜像+真机满意 → 删 legacy 或留永久双模 | 2h + Sir 真机 | 中 |

---

## 5. 第 1 个 sub‑step (Phase 0) — 7 步, 具体到代码层

1. **读**: 设计 §1.2 依赖表 + `jarvis_inner_thought_daemon.py:4039‑4054`(5类定义) +
   `:7272`(`_CATEGORY_TO_INTENT`) + `:1350`(`SAME_CATEGORY_COOLDOWN_S`) + `:2606`(`_compute_free_categories`)。
2. **加 flag**: `memory_pool/inner_thought_cost_config.json` 加 `thinking_kind_mode: "legacy"`
   (或新 vocab 文件); daemon 加 `_thinking_kind_mode()` reader (mtime cache, fail→legacy)。
3. **加派生表**: `_KIND_FROM_EFFECT` dict (设计 §5.1) + `_kind_from_effect(actionable, has_rest)`
   方法 → 返 kind label (solve/reflect/shape_next/want_capability/relate/reach_out/commit/self_debug/rest)。
4. **双写 (不改行为)**: 在 `_persist_thought` / 日志处, legacy 模式下**额外**记 `derived_kind`
   (= `_kind_from_effect(thought.actionable)`), 与 category 并存, 不影响任何决策。
5. **测**: 新 `tests/_test_dehardcode_p0_kind_derive.py` — 每 actionable → 正确 kind; REST → rest;
   none 无 rest → empty; flag 默认 legacy。
6. **跑全测**: `.\tests\_runall.ps1` 绿 (Phase 0 flag=legacy 必须 0 行为变化)。
7. **commit**: `feat(thinking-dehardcode-P0): kind_mode flag + effect→kind 派生表 (脚手架, legacy 0 变)`
   + 双层报告 Sir。

---

## 6. 验收标准 (可 grep / 可跑)

- Phase 0: `thinking_kind_mode` 默 legacy; `python -c "from jarvis_inner_thought_daemon import ...; 派生表测"` 过; 全测绿 + 行为 0 变 (镜像对比 reply 一致)。
- Phase 1+: 镜像注入几句 → tail turn_complete + 看 daemon log "attend 焦点区 X" (势能招来, 非选槽)。
- Phase 2: 镜像 settled → 真歇 (REST), 不连发重复; 真机验。
- 全轨: 设计 §7 五条判据。

---

## 7. 红线 (本轨特有)

- **每 phase flag‑gated 默认关 + 镜像验 + 可回退** (`thinking_kind_mode=legacy`)。**别一次全换。**
- **Phase 2 (冷却→放电) 最险**: 必镜像 + Sir 真机逐块验, 怀疑就停在 Phase 0/1/3 (双模共存也是大进步)。
- 不动 hippocampus (体只引用); stance/concern 接地红线不破 (无 trace 的 effect 拒)。
- A‑E 退役前, ds‑routing vocab (`thinking_brain_ds_trigger_vocab.categories`) 必同步迁 effect, 否则 ds 路由失效。

---

## 8. 起始 prompt (切窗口直接粘这段给下一 agent)

```
你接手 J.A.R.V.I.S. (d:\Jarvis) 的"思考脑去硬编码"大工程 — 拔掉识的最后一条硬编码
(A‑E 5 类 category 槽), 让思考的 kind 由体势能涌现 (Sir 真意: 思考是为解决问题/反思/
建议/想要能力, 但不该写死槽, 而是势能驱动自然发现)。

第一步必读 (30 秒):
1. AGENTS.md
2. docs/JARVIS_THINKING_DEHARDCODE_CATEGORIES_DESIGN.md  ← 设计真相源 (现状依赖表/phased/机制)
3. docs/AGENT_KICKOFF_THINKING_DEHARDCODE.md  ← 本接手指引 (Phase 列表 + 第1步7步 + 红线)
4. docs/JARVIS_CLOSURE_PROGRESS.md  ← 今天进度 + commit 链 (起点 7baf139)

已建基础 (复用别重造): 体势能 body_focus.current_focus() / REST 放下 _handle_rest_decision /
全套 actionable effect / 镜像 scripts/jarvis_mirror.py。

任务: 按 KICKOFF §4 Phase 0→5 逐 phase 做 (查→改→测→镜像验→记 CLOSURE_PROGRESS→独立 commit)。
红线: 每 phase flag‑gated (thinking_kind_mode, 默 legacy) + 镜像验 + 可回退; Phase 2 最险必真机验;
别一次全换; hippocampus 永不动; commit 模板见 AGENTS.md §5 (PowerShell 多 -m)。

先做 Phase 0 (脚手架: flag + effect→kind 派生表 + 双写不改行为), 7 步见 KICKOFF §5。
做完双层报告 Sir, 等 Sir 真机/拍板再推进 Phase 1。
```

---

*本 kickoff 由 2026‑05‑31 口识体收尾 agent 写, 配 `JARVIS_THINKING_DEHARDCODE_CATEGORIES_DESIGN.md`。*
