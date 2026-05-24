# Jarvis Legacy Cleanup Checklist

> **Sir 指示 (2026-05-24 08:29)**: "保证我们重构结束并且稳定以后把老版本逐步褪去, 保证架构的 neat."
>
> 此 doc 跟踪 Phase D reshape 期间引入的**所有临时 backward-compat layer / stub / dual-write / shim**.
> 每项有明确的 **cleanup trigger** (= 何时安全删除), 防止临时层永久存在 → 架构 neat.

---

## 总览: 7 类临时 layer

| # | 类型 | 当前数量 | 真删触发条件 |
|---|---|---|---|
| 1 | **Deprecated stub class** (delegate to new) | 2 | M5+ 真 0 instantiate |
| 2 | **Backward-compat file shim** (re-export) | 1 | 18 caller 全 update import |
| 3 | **Dual-write** (老 SQLite + 新 PromiseLog) | 1 | M4.5.3 daemon 切 PromiseLog |
| 4 | **`noqa: F401` 转发 import** | 20+ | 对应 stub 真删后 |
| 5 | **`__unknown__` 兼容标记** (老数据 backfill) | 1 | 1 个月 (老数据全 backfill 后) |
| 6 | **TypeError fallback** (老签名兼容) | 1 | M2.C 阶段完成后 |
| 7 | **Hardcoded fallback** (config 优先, fallback 硬编码) | 1 | (永久保留 — defense in depth) |

---

## 详细 cleanup 表

### 1. Deprecated stub class (delegate to new) — 2 项

| Stub | 文件 | 行 | Delegate 到 | Cleanup trigger | 预计 milestone |
|---|---|---|---|---|---|
| `UnifiedMemoryGateway` | `jarvis_memory_core.py` | 515-562 | `MemoryHub.query/.to_prompt_block` | 0 真 instantiate (grep `UnifiedMemoryGateway(\b`) 1 周 + 20 个 `noqa F401` 删 | **M5** (1 周稳定后) |
| `TaskWorkerPool` | `jarvis_memory_core.py` | 755-? | 已是死类无 active code | 同上 | **M5** |

**Cleanup 操作** (M5+ 后):
```bash
# 1. 删 class 定义 (jarvis_memory_core.py 2 处)
# 2. 删 20+ `noqa F401` import 转发 (grep -l "UnifiedMemoryGateway\|TaskWorkerPool" *.py)
# 3. 跑 pytest 全集验证
```

---

### 2. Backward-compat file shim (re-export) — 1 项

| Shim | 文件 | 真 source | Cleanup trigger | 预计 milestone |
|---|---|---|---|---|
| `jarvis_memory_gateway.py` (整 file) | shim 转发 → `jarvis_memory_hub.py` | `jarvis_memory_hub.py` | 18 caller 全改 import `from jarvis_memory_hub` (grep `from jarvis_memory_gateway`) | **M6 NERVE_SPLIT** |

**Cleanup 操作**:
```bash
# 1. grep -rn "from jarvis_memory_gateway" *.py tests/ scripts/ → 18+ 处
# 2. 全改 from jarvis_memory_hub
# 3. git rm jarvis_memory_gateway.py
```

---

### 2.4 — M3 / M4 / M6 deferred sub-steps (合 M6.4 真 class split 一起做)

按 Sir 准则 7+8 (元否决权 + 优雅可持续), 以下 sub-steps 真做风险高 + 跟 M6.4 真 class split 一并做更优雅. 不重复改 import.

| Sub-step | 真做内容 | Defer 到 | 状态 (2026-05-24) |
|---|---|---|---|
| **M3.E** ✅ | `jarvis_enhanced.py` 拆 3 file (ProactiveShield + ProactiveCompanion + SkillTreeTracker) | — | **DONE** (commit `1d23014`) facade re-export 兼容 |
| **M3.B.Claim rename** | 真 rename `Claim → FactClaim` (251 处 grep) | M6.4 后 (alias 已加 backward compat) | DEFER (alias 已加 + ClaimSchemaV2/Authored alias) |
| **M3.C/D/G/F** ✅ | 真 `git mv l1/l3/l5 → _legacy/` + `central_nerve.run()` 364 行 stub + worker.trigger_routing dual-emit | — | **DONE** M6.5.1+M6.5.2+M6.5.3 (3-brain mv to `_legacy/3_brain_attempt/`, run() stub raise + chat_bypass fallback, archive doc) |
| **M4.6** | grep 替换 18+ caller `add_commitment` → `hub.write_commitment` (M4.5.1 dual-write 已让数据进 PromiseLog, caller 改是 stylistic) | DEFER | 不做 — M4.5.1 dual-write 已透明, 改 caller 真 0 收益, 反破现有 test |
| **M4.7** ✅ | `dashboard pending_callbacks.jsonl` 消费时读 PromiseLog | — | **DONE** (commit `7ce9ed6`) dashboard dual-write to PromiseLog kind='cross_session_callback' |
| **M5.3** | 停 `__NUDGE__` push, Conductor 100% publish-only (需主脑被 SWM 主动触发机制) | M7+ | DEFER — 需配套 nerve_voice_event_loop SWM-trigger main brain 机制. M5.1 dual-emit + M5.2 swm_block 注入主脑已 OK, 真停 __NUDGE__ 需 trigger mechanism |
| **M6.1** ✅ first+second wave | `_assemble_prompt` 拆 12 个 `_build_xxx_block` | partial done | **6/12 helpers DONE** (memory_gateway/skill_tree/anticipator/profile_block/habit_clock/context_router). 剩 soul_block (~1200 行 大) 留 M6.4 真 class split 时一并 design |
| **M6.2** ✅ first wave | 5 tier 抽离 5 个 `_assemble_*_prompt` | partial done | **WAKE_ONLY done** (commit `a4277cc`). FACTUAL_RECALL/SHORT_CHAT/TOOL_REQUEST/DEEP_QUERY 留 M6.4 (参数 ≥10 — 真适合 PromptAssembler class) |
| **M6.3** ✅ first wave | `__init__` 957 行拆 `_init_xxx` 6 个方法 | partial done | **audio_recovery done** (commit `1f2b624`). 剩 ~25 个 init section 大, 留 M6.4 真 class split 时一并 design |

**理由**: 大部分 sub-step 第一波已做 (3-brain 真 mv / enhanced split / dashboard dual-write / 6 prompt helper / 1 init helper / WAKE_ONLY tier). 剩余 deferred 部分跟 M6.4 真 class split 一并做更优雅, 不重复 refactor 两次.

**M6.4 触发条件**: Sir 真用 1-2 周稳定 + cleanup checklist deferred 项数 < 3 → 启动 M6.4 真 class split.

---

### 3. Dual-write / Dual-emit (老路径 + 新 SWM publish) — 3 项

| Dual-write | 文件 | 行 | Cleanup trigger | 预计 milestone |
|---|---|---|---|---|
| `CommitmentWatcher.add_commitment` dual-write to PromiseLog | `jarvis_commitment_watcher.py` | 1020-1039 | M4.5.3 daemon 真切 PromiseLog 后, 老 SQLite write 删 → dual-write 退化为单写 PromiseLog | **M4.5.3** |
| `Conductor._dispatch_path_a/_execute_path_b` dual-emit `conductor_intent` SWM | `jarvis_conductor.py` | 573-600, 821-847 | M5.3 主脑能从 [CONDUCTOR INTENT] block 自决纳/弃 后, 停 `__NUDGE__` push, 完全靠 SWM | **M5.3** |
| `worker.trigger_routing` deprecation warn + dual-emit `deprecated_3_brain_invoked` SWM | `jarvis_worker.py` | 5073-5103 | M6.5 真删时看 SWM event 数 (0 触发 1 周 → 安全 git rm 3 file + run() 移 _legacy/) | **M6.5** |

**渐进 cleanup**:
- **M4.5.1 ✅**: CW dual-write 同时进 PromiseLog + SQLite
- **M4.5.2 ✅**: CW daemon init dual-source restore
- **M4.5.3 (then)**: 停 SQLite 写 (dual-write block 删)
- **M5.1 ✅**: Conductor dual-emit `__NUDGE__` + `conductor_intent` SWM publish
- **M5.2 (next)**: 主脑 prompt 加 `[CONDUCTOR INTENT]` block + 自决纳/弃
- **M5.3 (then)**: 停 `__NUDGE__` push, Conductor 100% publish-only sentinel

---

### 4. `noqa: F401` 转发 import — 20+ 处

20+ 文件含老 P0+19-5 拆分时遗留的:
```python
try:
    from jarvis_memory_core import (  # noqa: F401
        PromptLayer, PromptCache, CorrectionEntry, CorrectionMemory,
        MemoryFragment, UnifiedMemoryGateway, FeedbackTracker,
        TaskWorkerPool, Anticipator, CorrectionLoop, SleepIntentDetector,
        HumorMemory,
    )
except Exception:
    pass
```

**Cleanup trigger**: stub 删后, 对应 import 也跟着删. 同 M5 一起.

**Cleanup 操作**:
```bash
# 1. grep -l "noqa: F401.*UnifiedMemoryGateway" *.py
# 2. 每个 file 删整个 try/except 块 (或保留剩 active import)
```

---

### 5. `__unknown__` 兼容标记 — 1 项

| 位置 | 用途 | Cleanup trigger |
|---|---|---|
| `jarvis_promise_log._load() author='__unknown__'` | 老数据无 `author` 字段 → 临时标记触发 backfill | 跑 1 次 Jarvis 后 `_backfill_authors` 把所有老 promise author 真值填上, 之后 `__unknown__` 不再出现 |

**Cleanup 操作** (1 个月后):
```python
# 删 jarvis_promise_log.py:486 的 if not _had_author: p.author = '__unknown__' 行
# 删 jarvis_promise_log.py:_backfill_authors 整方法
```

---

### 6. TypeError fallback (老签名兼容) — 1 项

| 位置 | 老路径 | 新路径 | Cleanup trigger |
|---|---|---|---|
| `central_nerve._assemble_prompt:2860-2865` | `memory_gateway.to_prompt_block(text, top_k)` (老 UnifiedMemoryGateway 签名) | `memory_gateway.to_prompt_block(text, top_k, nerve=self)` (新 Hub 签名) | `UnifiedMemoryGateway` stub 真删后 (M5+) — 老签名不会再被触发 |

**Cleanup 操作**:
```python
# 删 central_nerve.py:2863-2865 try/except TypeError block, 保留新 signature 调用
```

---

### 7. Hardcoded fallback — 1 项 (永久保留)

| 位置 | 用途 |
|---|---|
| `jarvis_utils._load_proxy_url()` fallback `'http://127.0.0.1:7890'` | `jarvis_config/network.json` 读不到时 fallback (defense in depth) |

**说明**: 这不是临时 layer, 是**故意的容错**. config 文件被改坏 / 误删 时 jarvis 仍能启动. **永久保留**, 不进 cleanup queue.

---

## Cleanup 总进度跟踪

| Milestone | 状态 | 完成时间 | 备注 |
|---|---|---|---|
| **Phase D-1 (reshape 构建期)** | ✅ 进行中 | 2026-05-24 ~ | M1+M2+M3.partial+M4 |
| **Phase D-2 (稳定观察期)** | ⏸ 1-2 周 | TBD | Sir 真用 1-2 周, 无 regression |
| **Phase D-3 (cleanup)** | ⏸ | TBD | 按此 checklist 逐项删 |

---

## 加新 layer 时 — 必填表 (准则 8)

引入新 backward-compat / shim / dual-write / stub 时, **必须在此 checklist 加一行**, 含:
- ✅ 文件 + 行号
- ✅ 真 source / 替代
- ✅ Cleanup trigger (具体 — "0 真 caller" / "M5 后" / etc.)
- ✅ 预计 milestone

**没填 → 不允许 commit**. Sir 准则 8 强制.

---

## 维护

- 每完成一项 cleanup → 此 doc 划掉对应 row + 注 commit hash
- 每加新 layer → 立刻加 row
- Sir 每月可问 "现在还有几个临时 layer?" — 看这 doc 一目了然

> **Sir 原话 (2026-05-24 08:29)**: "保证我们重构结束并且稳定以后把老版本逐步褪去, 保证架构的 neat."
> 此 doc 就是兑现这句话的工具.
