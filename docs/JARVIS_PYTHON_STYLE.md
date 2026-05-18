# Jarvis Python Style — 跨 Agent 硬规

> **用途**: 任何 agent (Cursor / Windsurf / Codex / Claude Code / Cline / Aider) 改 `jarvis_*.py` 之前按需 Grep 本文件。
> **真理源**: 本 markdown 是单点真相。`.cursor/rules/jarvis_python_style.mdc` 是 Cursor 自动激活的 mirror, 不要逐字 sync, 内容以本文件为准。
> **入口**: `AGENTS.md §2` 必读表已引用本文件 (按需 Grep, 非全文 Read)。

---

## 1. Imports — Safety Net

每个新 `jarvis_*.py` 文件顶部 (docstring 后) 必须有这套预 import:

```python
from __future__ import annotations

# [P0+X-Y.Z / 2026-XX-XX] 一行 import 审计注释 (如需)
import os  # noqa: F401
import sys  # noqa: F401
import io  # noqa: F401
import re  # noqa: F401
import time  # noqa: F401
import json  # noqa: F401
import threading  # noqa: F401
import collections  # noqa: F401
# ... 实际用到的 imports 不带 noqa
import numpy as np  # 文件里有任何 np.* 调用就必须显式 import
```

**理由**: 这层 safety net 抓 `name 'np' is not defined` / `name 'json' is not defined` 这类 P0+19 split 时炸的 NameError。用 `# noqa: F401` 是因为这些是"为后续 split 准备"的预 import, linter 不该警告。

**反例 / 教训**: P0+20-α.1 commit `<old>` — `jarvis_memory_core.py` 漏 `import numpy as np` 导致 KeyRouter 误把 NameError 当成 google_3 key 的 403 PERMISSION_DENIED, 浪费 4h 排查。

---

## 2. Marker 注释 — 三处一致

每个有意义的源码改动必须打 marker:

```python
# [P0+20-α.3 / 2026-05-16] Integrity Check pre-filter for declarative sentences
def is_action_claim(text: str) -> bool:
    ...
```

格式: `# [<commit-marker> / <ISO date>] <一行说明>`

**三处一致**:
- 代码注释 marker `[P0+20-α.3 / 2026-05-16]`
- commit message marker `feat(P0+20-α.3): ...`
- TODO 看板状态 `✅ P0+20-α.3`

三者同步, grep-friendly for archeology.

---

## 3. Logging — 路径选择树

| 场景 | 用什么 | 不用什么 |
|---|---|---|
| 后台线程 / sentinel / daemon | `bg_log(...)` (auto trace_id 注入) | NOT `print` (绕过 trace_id) |
| 主线程一次性启动 print | `print(...)` 可用 (不污染 dialog) | NOT `logging.info` (项目不用 stdlib logging) |
| Sir 看到的 reply / dialog 输出 | dialog box API | NOT `print` (污染渲染路径) |
| daemon 里抓异常 | `bg_log(... + traceback.format_exc())` | NOT `raise` (daemon 应 swallow + 写 log) |

---

## 4. Forbidden Anti-patterns

| 反例 | 原因 | 替代 |
|---|---|---|
| `from jarvis_nerve import *` | 破坏 P0+19 split 后的 forwarding shim | 显式 `from jarvis_nerve import X, Y` |
| `time.sleep(0.01)` busy-loop 在主线程 | 阻塞主线程 ≥ 10ms 影响 Qt 事件循环 | `QTimer.singleShot` / `threading.Timer` |
| Raw `sqlite3.connect("memory_pool/...")` | 跳过 Hippocampus 的并发控制 / schema 升级 | 走 `Hippocampus` / `CommitmentWatcher` API |
| `print(...)` 在 dialog 渲染路径 | 污染 Sir dialog box | 用 dialog box API |
| `_<X>_PATTERNS = [...]` / `_<X>_KEYWORDS = (...)` 写死 | 违准则 6.5 — vocab 不能硬编码 in py | `memory_pool/<x>_vocab.json` + `_SEED_*` + `get_*()` + CLI (见 §6) |
| `logging.info(...)` / `logging.basicConfig` | 项目用 `bg_log` 体系, stdlib logging 会撕 trace_id 链 | `bg_log` |

---

## 5. Type Hints

- **强烈推荐**, 不强制 (split 前的老代码部分缺)
- **新文件 / 新公共方法**: 必须类型 hint (`def foo(x: str) -> bool:`)
- 内部 private helper: 推荐但不必须
- `Optional[T]` / `Union[A, B]` / `List[T]` 用 typing 模块, `from __future__ import annotations` 已经允许字符串形式延迟求值

---

## 6. 准则 6.5 红线 — Vocab 持久化范式

任何 `_<X>_PATTERNS` / `_<X>_KEYWORDS` / `_<X>_VOCAB` 列表 / 元组**必须**走这套范式:

### 6.1 三件套硬规

| 件 | 路径 | 作用 |
|---|---|---|
| 1. 持久化 | `memory_pool/<x>_vocab.json` | active/review/archived 三态机 + _meta |
| 2. CLI | `scripts/<x>_dump.py` | list/add/activate/reject/delete |
| 3. py 改造 | `jarvis_<file>.py` | `_SEED_X_PATTERNS` (fallback) + `get_x_patterns()` (mtime cache) |

### 6.2 py 改造范式 (照搬 β.3.0-vocab1)

```python
_SEED_<X>_PATTERNS = (  # fallback only, json 损坏 / 首次启动用
    'kw1', 'kw2', ...
)

_<X>_VOCAB_PATH = os.path.join('memory_pool', '<x>_vocab.json')
_<X>_PATTERNS_CACHE: Optional[tuple] = None
_<X>_PATTERNS_MTIME: float = 0.0


def _load_<x>_patterns_from_json() -> Optional[tuple]:
    if not os.path.exists(_<X>_VOCAB_PATH):
        return None
    try:
        with open(_<X>_VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        out = []
        for p in data.get('patterns', []):
            if not isinstance(p, dict) or p.get('state') != 'active':
                continue
            for k in p.get('keywords') or []:
                if isinstance(k, str) and k:
                    out.append(k)
        return tuple(out)
    except Exception:
        return None


def get_<x>_patterns() -> tuple:
    global _<X>_PATTERNS_CACHE, _<X>_PATTERNS_MTIME
    try:
        mtime = os.path.getmtime(_<X>_VOCAB_PATH) if os.path.exists(
            _<X>_VOCAB_PATH) else 0
    except OSError:
        mtime = 0
    if _<X>_PATTERNS_CACHE is None or mtime > _<X>_PATTERNS_MTIME:
        loaded = _load_<x>_patterns_from_json()
        _<X>_PATTERNS_CACHE = loaded if loaded is not None else _SEED_<X>_PATTERNS
        _<X>_PATTERNS_MTIME = mtime
    return _<X>_PATTERNS_CACHE
```

### 6.3 json schema

```json
{
  "_meta": {
    "schema_version": 1,
    "created_at": "2026-XX-XXTHH:MM:SS",
    "purpose": "<一句话用途>",
    "source_origin": "<迁自哪个 .py 文件:line>",
    "edit_via": "scripts/<x>_dump.py --add/--activate/--reject/--delete",
    "auto_propose": "INTEGRITY_STACK L7 WeeklyReflector (未来) propose 新 keyword 入 review state",
    "consumer": "jarvis_<file>.py:get_<x>_patterns()"
  },
  "patterns": [
    {
      "id": "<unique_id>",
      "category": "<category_tag>",
      "keywords": ["kw1", "kw2"],
      "state": "active",
      "source": "seeded",
      "created_at": 1779080100.0,
      "note": "<可选备注>"
    }
  ]
}
```

### 6.4 系统级常量豁免

少数"系统级常量"可以保留为 py 字面量, 不必走 vocab 范式 (例外):
- `TICK_INTERVAL = 60`
- `MAX_RETRY = 3`
- HTTP 错误码常量
- API 不可重试错误黑名单 (e.g. `_NON_RETRYABLE_KEYWORDS = ('PERMISSION_DENIED', ...)`)

**判别**: 这些是底层系统常量, 不是"Sir 自然语言会触发的语义 vocab"。Sir 永远不会通过 CLI 加新 HTTP 错误码。

---

## 7. Sensitive Data Access (从 security 协议提取)

| 文件 | 读操作 | 注意事项 |
|---|---|---|
| `jarvis_config/sir_profile.json` | ✅ OK (供 ProfileCard 注入) | **NEVER print to chat reply** — 内容是 Sir 私人画像, 17KB intimate context |
| `memory_pool/*.db` | ⚠️ 仅通过 `Hippocampus` / `CommitmentWatcher` API | NOT raw `sqlite3.connect("memory_pool/...")` |
| `jarvis_config/keys.py` | ✅ 这是 loader, NOT keys 本身 | 读 OK, 但不要 print loaded values |
| `.env` | ❌ NEVER read in agent flow | 真实 keys, Sir 手动维护 |

---

## 8. 何时更新本文件?

| 触发 | 操作 |
|---|---|
| 项目升级出新 forbidden anti-pattern (e.g. β.X 发现新 NameError 教训) | §4 加新行 + commit `docs(P0+X-Y.Z): JARVIS_PYTHON_STYLE.md v<n>` |
| 准则 6.5 vocab 范式升级 | §6 升级范例代码 |
| 新增 sensitive data 类型 | §7 加新行 |
| 跨 agent 实测发现新 gap | 立刻补 + 同步 `.cursor/rules/jarvis_python_style.mdc` 头部 mirror 引用 |

**禁止**: 在 `.cursor/rules/jarvis_python_style.mdc` 写新规则却不 mirror 进本文件 — 那会让非 Cursor agent 看不到, 违反 Sir "跨 IDE 可携带性"目标。

---

*本文件由 `P0+20-β.3.1 / 2026-05-18` 创建, 提炼自 `.cursor/rules/jarvis_python_style.mdc` + `.cursor/rules/jarvis_security.mdc §Sensitive Data Access`。变更走 `docs(P0+X-Y.Z): JARVIS_PYTHON_STYLE.md v<n>` commit。*
