# M6 NERVE_SPLIT — central_nerve.py 拆分 audit

> **2026-05-24 Cascade audit**: 重构期间最大 god object — 4790 行 / 32 method / 1 class.
> 按 Sir 准则 8 (优雅可持续 > 简单), M6 必须分多 sub-step 渐进 + 每步真测.

---

## 📊 现状量化

| 指标 | 值 | 评价 |
|---|---|---|
| 总行数 | **4790** | god file |
| Class 数 | 1 (`CentralNerve`) | god class |
| Method 数 | 32 | OK |
| **__init__ 行数** | **957** (line 259-1216) | **god init** |
| **_assemble_prompt 行数** | **2537** (line 1502-4039) | **god method** ⚠️⚠️⚠️ |
| run() 行数 | 364 (line 4320-4684) | 3-brain 长任务流 (Q2 decision: move to _legacy) |

`_assemble_prompt` 是真痛点 — 2537 行单方法承担:
- prompt block 组装 (soul / state / hippocampus / commitments / concerns / SWM ...)
- 5 档 prompt tier 分流
- 多个 sentinel 数据收集
- 时间 stamp / persona 渲染
- 主对话 + nudge + factual_recall 多场景 dispatch

---

## 🎯 M6 子步拆分 plan (按 risk 从低到高)

### M6.1 — _assemble_prompt 子函数化 (低 risk, 8-12 step)
拆每个 `[XXX BLOCK]:` 渲染逻辑成独立 `_build_xxx_block(...)` 私有 method (仍在 CentralNerve class 内, 只是组织清晰).

| Block | 真痛 LOC | 拆到方法 |
|---|---|---|
| persona / time_persona | ~80 | `_build_persona_block` |
| state ledger | ~120 | `_build_state_block` |
| concerns | ~150 | `_build_concerns_block` |
| commitments / promise_log | ~180 | `_build_commitments_block` |
| hippocampus recall | ~100 | `_build_hippo_block` |
| SWM (event bus) | ~80 | `_build_swm_block` |
| skill_tree / project | ~70 | `_build_skill_block` |
| soul_router tags | ~60 | `_build_soul_tags_block` |
| recent completed / lifetime anchor | ~90 | `_build_anchor_block` |
| ... | ... | ... |

**预期**: 2537 行 god method → 主 `_assemble_prompt` ~300 行 (dispatch) + 12 个 `_build_*` 方法 ~200 行 each.
**risk**: 低 (仅重构, 行为不变).
**真测**: pytest + Sir 1 轮对话验 prompt 仍 work.

### M6.2 — _assemble_prompt 5 tier 分流抽离 (中 risk)
现在 5 tier (FULL / WAKE_ONLY / FACTUAL_RECALL / SHORT_CHAT / STANDARD) 嵌套 if/else 散在 2537 行里. 抽 5 个 dedicated method:
- `_assemble_full_prompt(...)`
- `_assemble_wake_only_prompt(...)`
- `_assemble_factual_recall_prompt(...)`
- `_assemble_short_chat_prompt(...)`
- `_assemble_standard_prompt(...)`
- 顶层 `_assemble_prompt` 仅 dispatch (~50 行)

**风险**: 中 (5 个 tier 的 prompt 必须各自真测不漏 block).

### M6.3 — __init__ 957 行拆 init_X 方法 (中 risk)
按职责分组:
- `_init_blood_organs()` — JarvisBlood / VocalCord / Hippocampus / HabitClock ...
- `_init_layered_brain()` — RightBrain / LeftBrain / L5Brain (3-brain, M3.D 后删)
- `_init_sentinels()` — NudgeGate / SleepDetector / Conductor ...
- `_init_memory_facades()` — MemoryHub / ProfileCard / status_ledger ...
- `_init_event_bus_and_sensors()` — bus / sensors / probes ...
- `_init_reflectors_and_evaluators()` — L0-L7 reflectors ...
- `__init__` 顶层 ~80 行 dispatch + class-level state

**风险**: 中 (init 顺序敏感, 一些 sentinel 依赖前面 init 完成).

### M6.4 — class 拆分 (高 risk, 真 NERVE_SPLIT)
把 `CentralNerve` 拆成多个 class (按职责):
- `JarvisCore` — 核心 state machine + blood + hippocampus
- `JarvisPromptAssembler` — `_assemble_prompt` + 12 _build_* + 5 _assemble_* tier
- `JarvisStateRestorer` — STM / task_snapshot / persist daemon
- `JarvisLifecycle` — sleep / wake / archive / on_activity

`CentralNerve` 退化为 facade (compose 4 个 class).

**风险**: 高 (各 class 间接口要 design, 现有调用 `nerve.X` 全要改 / 留 facade).
**预计**: 应该等 M6.1+M6.2+M6.3 全部稳定 (Sir 真用 2 周) 才能动.

### M6.5 — 3-brain 整体移走 (M3.D 决议执行)
- `git mv l1_right_brain.py _legacy/3_brain_attempt/`
- 同款 mv l3 / l5
- `central_nerve.run()` 364 行整段移到 `_legacy/3_brain_attempt/central_nerve_run_v1.py`
- 删 self.left_brain / right_brain / l5_brain 实例化
- 删 self.eyes/hands/env init (M3.A 暂留的)
- 删 worker.trigger_routing
- 20+ noqa F401 import 删

**风险**: 中-高 (worker.trigger_routing 调 central_nerve.run, 老路径必须无人用).
**真测**: Sir 24h 真用, 看是否有 task 路由失败.

---

## 🚦 推荐路线 (按 Sir 准则 8)

```
M6.1 (低 risk, ~3 commit, 1 周)  →  Sir 真测稳定
  ↓
M6.2 (中 risk, ~2 commit, 1 周)  →  Sir 真测稳定
  ↓
M6.3 (中 risk, ~3 commit, 1 周)  →  Sir 真测稳定
  ↓
M6.5 (M3.D 3-brain mv, ~1 commit, 1 周)  →  Sir 真测稳定
  ↓
M6.4 (高 risk, 真 class split, 2 周)  →  Phase D 收官
```

**每个子步独立 commit + 立刻 git revert 可回滚**. 不要一次性做 M6.4 (god class split) 不真测就 commit.

---

## ⚠️ 不可一次性全做

audit doc 说 M6 "4 周 (1 周 1 file)", 但实际只数 file 是误判 — `central_nerve.py` 1 个 file 5104 行, 不是 4 个 1000 行 file. 真拆要 6 周 + 充分真测.

按 Sir 准则 8: **Cascade 不应连续 commit 整个 M6**, 必须 sub-step 之间留 Sir 真测窗口.
