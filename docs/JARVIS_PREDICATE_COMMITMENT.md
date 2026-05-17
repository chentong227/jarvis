# Jarvis Predicate-Driven Commitment System — 抽象语义承诺设计

**版本**: v1.0 / 2026-05-17 (β.2.8.6 设计)
**作者**: Sir 提出方向 + Claude 综合
**前置**: `docs/JARVIS_PROACTIVE_CARE_ENGINE.md`, `jarvis_promise_log.py`

> Sir 22:42: "加某个类型, 是不是有点类似硬编码? 如果不是睡觉的情况呢?
> 是我'导出完视频就去喝水'之类的抽象承诺呢? 贾维斯会如何判断?
> 我们能不能设计一套这种抽象语义的承诺系统?"

---

## 0. 痛点起源

之前 CommitmentWatcher 只支持**时间锚** (deadline_ts = 09:00). Sir 实测
"明早醒了刷题" 被 Gatekeeper 解成 `09:00 hardcoded`, 9:00 准时出声不管 Sir
是否真醒. 我加了 wake-trigger 硬编码 (β.2.8.6 first cut), Sir 立刻指出:

  "Sir 还有上百种条件触发场景, 你不可能每种加一个 if 分支."

正确路: 把"触发条件"抽象为**谓词** (predicate), 配套 LLM 翻译层.

---

## 1. 概念模型 — 承诺三角 (Sir 2026-05-17 23:28 澄清)

```
┌─────────────────────────────────────────────────────────────────┐
│  Commitment = (predicate, action, ttl, commit_type)              │
│              with subject_of_predicate + subject_of_action       │
├─────────────────────────────────────────────────────────────────┤
│  commit_type ∈ {'sir_self_promise',                              │
│                 'conditional_reminder',  ← Sir 托付 Jarvis 监视  │
│                 'jarvis_self_promise'}                           │
│                                                                  │
│  Predicate.evaluate(ctx) -> bool                                 │
│    .subject ∈ {'sir' (默认), 'jarvis' (未来扩展)}                │
│    ctx 含 Sir 维度: idle_ms, sensor_snap, window_title, stm,     │
│            recent process_died_events, ...                       │
│    未来 ctx 加 Jarvis 维度: jarvis_running_tasks, jarvis_state,  │
│            self_promise_pending, key_health, ...                 │
│                                                                  │
│  Action.executor ∈ {'voice_nudge' (默认走 stream_nudge),         │
│                     'tool_call' (将来扩展, 自动执行 organ.cmd),  │
│                     'silent_log' (只 PromiseLog 不出声)}         │
│  Action.target   ∈ {'sir' (默认), 'jarvis' (自我变更),           │
│                     'system' (改全局 state)}                     │
└─────────────────────────────────────────────────────────────────┘
```

**为什么三角**: Sir 22:48 反例 "等我导出完视频去喝水":
- 承诺人 ≠ Sir (不是 "我承诺我要去喝水"; Sir 没承诺)
- 谓词主体 = Sir (Premiere 进程退出 = Sir 行为状态变化)
- 行动主体 = Jarvis 提醒 Sir
→ commit_type='conditional_reminder', predicate.subject='sir',
   action.executor='voice_nudge', action.target='sir'

未来扩展场景 — Jarvis 自主任务:
- "Jarvis 把视频压缩完了告诉我 + 自动放到 Sir 桌面"
- predicate.subject='jarvis' (检测 Jarvis 自己的压缩 task 完成)
- action.executor='tool_call' (file_operator.move)
- action.target='sir' (move 到 Sir 桌面 + 顺带通知)

| Sir 自然语言 | Predicate | Action |
|---|---|---|
| 明早醒了刷题 | `WakeFirstActive() AND TimeAfter("06:00")` | nudge "刷半小时" |
| **导出完视频去喝水** | `ProcessExited("Adobe Premiere Pro.exe") AND IdleFor(60)` | nudge "去喝水" |
| 改完文件提交 | `FileSaved(path) AND NoChangeFor(300)` | nudge "git commit" |
| Cursor 跑完测试 | `TerminalContains("passed") OR ProcessExited("pytest.exe")` | nudge "测试结果" |
| 见妈妈问身体 | `WeChatUnread("妈妈") AND WeChatActive()` | nudge "问身体" |
| 今晚 11 点睡觉关 chrome | `TimeAfter("23:00") AND SirSaidSleepIntent()` | tool: kill chrome |

---

## 2. 4 层架构

### L1 Predicate Base + Library

```python
class Predicate(ABC):
    name: str
    description: str

    @abstractmethod
    def evaluate(self, ctx: dict) -> bool: ...
    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, d: dict) -> 'Predicate': ...


class WakeFirstActive(Predicate):
    """Sir 今天首次活跃 (PhysicalEnvironmentProbe.is_first_active_today)
    + idle_ms < 60s (真醒, 不是被动唤醒)."""
    name = 'wake_first_active'

    def evaluate(self, ctx):
        return ctx.get('first_active_today') and ctx.get('idle_ms', 9999) < 60_000


class TimeAfter(Predicate):
    """now >= HH:MM (today)."""
    def __init__(self, hh_mm: str):
        self.hh_mm = hh_mm

    def evaluate(self, ctx):
        now = time.localtime(ctx.get('now_ts', time.time()))
        h, m = map(int, self.hh_mm.split(':'))
        return (now.tm_hour, now.tm_min) >= (h, m)


class ProcessExited(Predicate):
    """指定进程在过去 max_recent_s 内 alive→dead. ctx['process_died'] 由 sensor 提供."""
    def __init__(self, exe_name: str, max_recent_s: int = 300):
        self.exe = exe_name.lower()
        self.max_recent_s = max_recent_s

    def evaluate(self, ctx):
        events = ctx.get('process_died_events', [])
        return any(e['exe'].lower() == self.exe and
                   (time.time() - e['when']) < self.max_recent_s
                   for e in events)


class IdleFor(Predicate):
    def __init__(self, seconds: int):
        self.seconds = seconds

    def evaluate(self, ctx):
        return ctx.get('idle_ms', 0) >= self.seconds * 1000


class WindowTitleContains(Predicate):
    def __init__(self, keyword: str):
        self.kw = keyword.lower()

    def evaluate(self, ctx):
        return self.kw in str(ctx.get('window_title', '')).lower()


class StmContains(Predicate):
    """最近 N 轮 STM 含某 keyword (Sir 主动提到了相关话题)."""
    def __init__(self, keywords: list, lookback_turns: int = 5):
        self.kws = [k.lower() for k in keywords]
        self.lookback = lookback_turns

    def evaluate(self, ctx):
        stm = ctx.get('recent_stm', [])
        recent = stm[-self.lookback:]
        return any(any(k in str(e.get('user', '')).lower() for k in self.kws)
                   for e in recent)
```

### L2 CompositePredicate

```python
class AndPredicate(Predicate):
    def __init__(self, *children): self.children = children
    def evaluate(self, ctx): return all(c.evaluate(ctx) for c in self.children)

class OrPredicate(Predicate):
    def __init__(self, *children): self.children = children
    def evaluate(self, ctx): return any(c.evaluate(ctx) for c in self.children)

class NotPredicate(Predicate):
    def __init__(self, child): self.child = child
    def evaluate(self, ctx): return not self.child.evaluate(ctx)
```

### L3 LLM Parser (Gatekeeper 扩展)

Gatekeeper prompt 已经做 commitment 解析. 加一个 `condition` 输出字段:

```json
{
  "has_commitment": true,
  "description": "导出完视频去喝水",
  "deadline_str": "",   // 旧字段, 仅 time-based 时填
  "condition": {        // 新字段, 复杂条件填这
    "type": "AND",
    "args": [
      {"type": "process_exit", "name": "Adobe Premiere Pro.exe"},
      {"type": "idle_for", "seconds": 60}
    ]
  },
  "action": "nudge",
  "action_text": "Sir, 该喝水了."
}
```

LLM 看到 fenced predicate library doc, 选合适的组合. 解析失败 → fallback 走老 `deadline_str`.

### L4 PredicateWatcher (CommitmentWatcher 扩展)

```python
def run(self):
    while True:
        ctx = self._snapshot_ctx()       # idle / sensor / stm / window
        for c in self.commitments:
            if c['nudged']: continue
            pred = c.get('predicate')
            if pred is not None:
                if pred.evaluate(ctx):
                    c['nudged'] = True
                    self._dispatch_commitment_nudge(c)
                # ttl 过期 → archived
                if time.time() - c['created_at'] > c.get('ttl_s', 86400):
                    c['nudged'] = True
                    c['status'] = 'expired_no_predicate_fire'
            else:
                # 老路径: 按 deadline_ts 触发
                ...
        time.sleep(30)
```

### L5 Sir 可观察

`scripts/predicate_tail.py`:
- 看每个 pending commitment 的 predicate 当前 evaluation 状态
- 历史 evaluation 时间线 (last 100 evaluation, 命中 / 未命中)
- ttl 还剩多久
- 自动报告 "永远 false 的 predicate" (LLM 翻译错了)

---

## 3. 与现有系统的关系

| 现有模块 | 处置 |
|---|---|
| `CommitmentWatcher` | 扩展: 加 predicate 字段, 老 deadline 路径保留兼容 |
| `Gatekeeper` (worker._do_gatekeeper) | prompt 加 condition 字段 + predicate library doc 注入 |
| `SelfPromiseDetector` | 检测到含条件词 → 自动绑 predicate (e.g. "我在你导出完视频之前再说一次" → ProcessExited) |
| `ProactiveCareEngine` | 不动. Predicate 是 reactive trigger, ProactiveCare 是 proactive concern push, 互补 |
| `PromiseExecutionLog` | 不动. Predicate fire → mark_fulfilled(promise_id) 自然兜底 |

---

## 4. 实施 4 阶段

| 阶段 | 工时 | 内容 | 必做 | 状态 |
|---|---|---|---|---|
| **β-1 Predicate base + library** | 2h | 12 个内置 predicate + Composite + 持久化 + subject 接口 | ✅ | **DONE** (β.2.8.6) |
| **β-2 Watcher 接 predicate** | 1.5h | CommitmentWatcher tick 跑 evaluate, 老路径并存 | ✅ | **DONE** (β.2.8.6) |
| **β-3 LLM Parser** | 3h | Gatekeeper prompt 加 condition 字段 + 测试 5 类自然语言场景 | ⭐ 核心 | 待做 |
| **β-4 scripts/predicate_tail.py + 真机** | 1.5h | Sir 实测 + 边角调 | ⭐ | 待做 |
| **β-5 接 action.executor='tool_call'** | 2h | tool_call 通道接通 — Jarvis 自动 organ.cmd 不只是出声 | 推荐 | 待做 (β.2.9+) |
| **β-6 接 predicate.subject='jarvis'** | 1.5h | ctx 加 jarvis 维度 + Jarvis 自主任务监视 (压缩/上传/备份完成) | 推荐 | 待做 (β.2.9+) |

---

## 5. 真机验证场景

| 场景 | Sir 自然语言输入 | 期望 predicate | 期望行为 |
|---|---|---|---|
| 早起刷题 | "明早醒了提醒我刷题" | `WakeFirstActive() AND TimeAfter("06:00")` | Sir 9:30 醒 → 9:30 提醒. Sir 仍睡 → 静默 |
| 导出后喝水 | "导出完视频去喝水" | `ProcessExited("Premiere") AND IdleFor(30)` | Premiere 进程消失 30s 后提醒 |
| Pomodoro 完成 | "这一段写完测试再说" | `ProcessExited("pytest") OR TerminalContains("passed")` | 测试 passed 后立刻提醒 |
| 见妈妈 | "看到妈妈微信弹了告诉我" | `WeChatUnread("妈妈")` | 妈妈发消息立刻提醒 |
| 不复杂的时间 | "下午 3 点提醒我喝水" | `TimeAfter("15:00")` | 走老路径 / 也可走 predicate 都行 |

---

## 6. 安全 + 防误触

| 风险 | 防御 |
|---|---|
| LLM 把无关条件翻译成 predicate → 误 fire | predicate evaluator 出错 → fallback 走 deadline_str, 不静默吃错误 |
| Predicate 永不 fire → commitment 堆积 | ttl_s 强制 (默认 24h), 过期 → mark untracked |
| 多 predicate fire 间隔太密 → Sir 烦 | per-commitment cooldown + 共用 ProactiveCare 的 last_any_nudge_ts |
| Sir 设的 predicate 太奇怪 → Jarvis 一直 evaluating 浪费 CPU | 每 predicate evaluate 时间 ≤ 1ms, 超 → 自动 disable + log |

---

*文档作者: Sir 提需求 + Claude 综合 / 2026-05-17 22:45*
*与 `JARVIS_PROACTIVE_CARE_ENGINE.md` 平级架构层文档.*
*下个 Agent 接手按 β-1 起步, 渐进扩展, 不一次性替换 deadline_ts.*
