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

### 3. Dual-write (老 SQLite + 新 PromiseLog) — 1 项

| Dual-write | 文件 | 行 | Cleanup trigger | 预计 milestone |
|---|---|---|---|---|
| `CommitmentWatcher.add_commitment` dual-write to PromiseLog | `jarvis_commitment_watcher.py` | 1020-1039 | M4.5.3 daemon 真切 PromiseLog 后, 老 SQLite write 删 → dual-write 退化为单写 PromiseLog | **M4.5.3** |

**渐进 cleanup**:
- **M4.5.1 ✅ (此 commit)**: dual-write 同时进 PromiseLog + SQLite
- **M4.5.2 (next)**: daemon 改读 PromiseLog (优先, SQLite fallback)
- **M4.5.3 (then)**: 停 SQLite 写 (commit dual-write block 删, hub.write_commitment 单写)

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
