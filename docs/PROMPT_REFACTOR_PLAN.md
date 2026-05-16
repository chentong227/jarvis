# P0+20-β.0 — Prompt Refactor & Directive Registry Design Doc

**起点**：2026-05-16 09:42 / Sir 与 Claude 4.7 评估对话（基于今早 09:23 真机实测 `jarvis_20260516_092307.log`）
**目标**：prompt 装配从「单函数 30K chars / 1274ms / 25+ block 全量注入」改为「四层架构 + Directive Registry 按需注入 + Gemini-3-Flash 异步评分 + 自动衰减」。
**最终量化**：prompt 30K → 18K (-40%) / `_assemble_prompt` 1274ms → < 400ms / TTFT 3.0s → 2.3-2.5s / Integrity 误报 -50% / TWO_PARTS 多意图 0/N → N/N。
**总工程量**：~7h / 6 个独立 commit。每个 commit 独立可 `git revert`。
**前置条件**：P0+19 拆分完工 ✅ + P0+20-α 收尾完工（rotate keys / 填 .env / np import 修 / google_1 永久剔除 / dormant_project 紧贴 standby 修）。

---

## 0. TL;DR

```
β.0.1   Registry 数据结构 + 12 条 directive bootstrap + JSON 持久化     2.0h
β.0.2   dry-run 双跑对比 + 切 SHORT_CHAT/WAKE_ONLY 用新机制              1.5h
β.0.3   L0 精简 (iterate: 搬 NUDGE/BILINGUAL/SMART_ROUTING 出去)        1.0h
        + 切 DEEP_QUERY / TOOL_REQUEST / CRITICAL
β.0.4   decay daemon + Sir review JSON queue                            0.5h
β.0.5   Gemini-3-Flash 评分异步链 (primary + fallback + 3s timeout)    1.5h
β.0.6   1098 testcase + 真机一轮 + registry dump 验收                   0.5h
                                                              合计  ~7.0h
```

---

## 1. 起点：今早 09:23 真机实测暴露的事实

完整日志：`docs/runtime_logs/jarvis_20260516_092307.log`

| 现象 | 数据 | 启示 |
|---|---|---|
| TTFT 已稳定 | 3.0s（之前 P0+18-f.1 修过性能崩溃）| 性能不是这轮的目标，**但 prompt 装配 1274ms 是新瓶颈** |
| `_assemble_prompt 总耗时 1274ms` | 装配占整个 pipeline 6.2s 的 21% | 必修 |
| `Prompt Size 总 29963 chars` | `core_persona=3894 \| how_to_respond=3673 \| chat_organs=1889 \| tier_routing=1862 \| life_log=1708 \| profile_block=1509 \| ltm_context=1246 \| stm_context=1201` | 前三类静态缓存 9.4K **全量注入每轮**，是减肥首要目标 |
| TWO_PARTS 多意图回复失败 | Sir "OK 那个驾照记下了，对了我刚 deploy..." → Jarvis 只答 deploy | `_assemble_prompt:1359` 的 `[CONTINUITY RULE]` directive 太弱 |
| Integrity Check 误报 | 09:25 `Dreams are rarely a reliable indicator...` 被 1.5B 判 `no_tool_called` | 陈述/解释/共情句没有 pre-filter，1.5B 闸门后置 |
| google_3 unhealthy | `name 'np' is not defined` | P0+19 拆分留尾（P0+20-α 收）|
| `[SilentNudge/dormant_project]` 紧贴 standby | standby 9s 后立即触发 | NudgeGate cooldown 跟 SilentNudge 触发条件没对齐（P0+20-α 收）|

> **本 doc 只解决 prompt 装配相关问题（前 5 行）。**
> **np import 修 + google_1 剔除 + dormant_project 紧贴 standby 修 → 在 P0+20-α 完工。**

---

## 2. 当前 `_assemble_prompt` 解剖（central_nerve.py:590-1480 / ~900 行）

5 个 branch（mode='full' / mode='light' / tier='WAKE_ONLY' / tier='SHORT_CHAT' / tier='FACTUAL_RECALL'）共拼出 **25+ 个 block**：

| 层 | block 列表（按当前注入顺序）| 大小 | 现状毛病 |
|---|---|---|---|
| **静态缓存** | `core_persona`(3894, TTL 86400s) + `how_to_respond`(3673, TTL 86400s) + `tier_routing`(1862, TTL 86400s) | ~9.4K | **滚雪球**：每次 BUG 修复都往里塞 directive (P0+18-f.2 NUDGE / P0+18-c.1 STRUCTURAL_TAG / d.X 反幻觉…)，从不剪枝 |
| **会话动态** | `stm_context` + `yesterday_block` + `open_threads_block` + `project_block` + `life_log_context` | ~5K | 这层 OK，按 tier 控制大小即可 |
| **能力/工具** | `chat_organs`(1889) + `available_skills_block` + `tool_honesty_directive` + `fuzzy_candidates_policy` + `promise_protocol_directive` | ~3K | **不分场景全注入**：聊天也读"如何用 fuzzy_candidates 选进程" |
| **环境实时** | `event_bus_block`(≤600) + `attention_block`(≤400) + `working_feed_block`(≤500) + `active_plan_block`(≤600) | ~2K | OK |
| **个性化** | `tone_directive` + `avoid_phrases_block` + `verbosity_block` + `profile_block`(1509) + `time_persona` + `context_str` + `soul_chapters_str` | ~3.5K | profile_block 是 17KB profile.json 的精炼，可再压到 800 chars（取最近 7 天 diff）|
| **记忆/召回** | `unified_memory` + `skill_tree_str` + `anticipator_ctx` + `ltm_context`(1246) + `correction_context` + `style_adjustment` + `content_pref` | ~3K | 已有 `_skip_heavy` 网关，OK |
| **任务帧** | clock / bilingual / search / memory_callback / image_context / commitment / user_input / system_alert | ~1K | 这层有大量 inline directive (`[BILINGUAL]` `[SEARCH]` `[MEMORY CALLBACK]` `[IMAGE CONTEXT]`)，应该统一进 Registry |

**总计 29963 chars，装配 1274ms。**

**瓶颈分布**：
- 静态缓存 9.4K = **31%**（永远全注入，治理 ROI 最高）
- 能力/工具 3K = **10%**（不分场景全注入，治理 ROI 第二）
- 任务帧 inline directive ~1K = **3%**（搬走有意义）
- 其它各层 ~16K = **53%**（按 tier 控制即可，已经做了 `_skip_heavy`）

---

## 3. 四层架构（核心设计）

```
┌─────────────────────────────────────────────────────────────┐
│  L0 — IMMUTABLE CORE        ~1200 chars   ALWAYS, 首位       │
│       人设 + INTEGRITY 铁则 + TWO_PARTS rule                  │
├─────────────────────────────────────────────────────────────┤
│  L1 — SESSION CONTEXT       ~3-5K         ALWAYS             │
│       STM + profile + time + attention + working_feed         │
│       + event_bus + open_threads + project + life_log         │
├─────────────────────────────────────────────────────────────┤
│  L2 — CONDITIONAL DIRECTIVES ~0-3K        GATED by Registry  │
│       12 条 directive 按 trigger 注入 + 学习信号 + 自动衰减   │
├─────────────────────────────────────────────────────────────┤
│  L3 — TASK FRAME            varies        BY TIER            │
│       user_input + clock + system_alert + commitment          │
└─────────────────────────────────────────────────────────────┘
```

### L0 — Immutable Core（PERSONA 重构 / iterate 路线）

**保留**：
- butler 身份 / 不奉承 / 不假装情绪 / "Sir" 称呼 / 简洁专业
- `INTEGRITY ABSOLUTE` 4 条铁则（精简版本，不再列具体短语黑名单）

**搬出 L0 到 L2 Registry**：
- `NUDGE / AGENDA HONESTY` 整段（18 行）→ `nudge_agenda_honesty` directive
- 具体短语黑名单 → 收进对应 directive 的 trigger / text
- `BILINGUAL DIRECTIVE` 散点 → `bilingual_directive` directive

**新增 L0 一行**（解决 TWO_PARTS BUG）：
```
- If Sir's utterance contains both a callback to prior context AND a new topic,
  address BOTH in order. Do not skip either.
```

**最终大小目标**：3894 chars → **~1200 chars (-69%)**。

### L1 — Session Context（按 tier 控制大小）

- `stm_context`：tier=WAKE_ONLY 跳过 / SHORT_CHAT 取 last 3 round / DEEP_QUERY 取 last 6 round（已有逻辑）
- `profile_block`：1509 → 800（取最近 7 天演化 diff 而不是全量；本 doc 不动 ProfileCard 实现，β.0.3 顺手压一刀）
- 其余 block（attention / working_feed / event_bus / open_threads / project / life_log）保持现有 max_chars

### L2 — Conditional Directives Registry（**核心创新**）

新建模块 `jarvis_directives.py`。装配时：

```python
def assemble_l2(ctx: DirectiveContext) -> str:
    fired = directive_registry.collect(ctx)  # 按 trigger 命中 + 排 priority
    for d in fired:
        d.fired += 1
        d.last_triggered = time.time()
    directive_registry.persist_async()  # 写回 memory_pool/directive_registry.json
    return "\n\n".join(d.text for d in fired)
```

详见第 4 节数据结构 + 第 5 节 bootstrap 清单。

### L3 — Task Frame（按 tier 切割）

| tier | L3 内容 | 总 prompt 预估 |
|---|---|---|
| WAKE_ONLY | user_input + clock | ~2K |
| SHORT_CHAT | + stm + tier_routing_mini | ~8K |
| FACTUAL_RECALL | + working_feed + event_bus | ~10K |
| DEEP_QUERY | + ltm + chat_organs + tier_routing_full | **~18K**（vs 现在 30K）|
| TOOL_REQUEST | + chat_organs + skill_registry + tool_honesty | ~16K |
| CRITICAL | full | ~20K |

---

## 4. Directive 数据结构 + Registry

新文件：`jarvis_directives.py`。

```python
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional
import json, time, threading, os

@dataclass
class DirectiveContext:
    """trigger 函数能拿到的所有上下文。"""
    user_input: str
    last_jarvis_reply: str
    stm: list                          # last N rounds
    tier: str                          # SHORT_CHAT / DEEP_QUERY / ...
    ledger_data: dict                  # status_ledger 当前状态
    soul_tags: list                    # ['projects', 'jokes', ...] 已有概念
    current_hour: int

@dataclass
class Directive:
    id: str                            # 'nudge_agenda_honesty' / 'continuity_two_parts'
    text: str                          # ≤ 500 chars
    trigger: Callable[[DirectiveContext], bool]  # 命中条件
    priority: int = 5                  # 1-10，决定遇满冲突时谁先
    tier_whitelist: list = field(default_factory=list)  # [] = 全 tier
    ttl_days: int = 30                 # 超过此天数无触发 → dormant
    source_marker: str = ""            # 'P0+18-f.2' / 'NEW'

    fired: int = 0
    rejected: int = 0
    helped: int = 0                    # β.0.5 接 Gemini-3-Flash 后才会写
    last_triggered: float = 0.0
    last_rejected: float = 0.0
    state: str = 'active'              # 'active' / 'dormant' / 'review' / 'archived'

class DirectiveRegistry:
    def __init__(self, persist_path: str = None):
        self.directives: dict[str, Directive] = {}
        self.persist_path = persist_path or os.path.join("memory_pool", "directive_registry.json")
        self._lock = threading.Lock()
        self._dirty = False

    def register(self, directive: Directive): ...
    def collect(self, ctx: DirectiveContext) -> list[Directive]:
        """按 trigger 命中 + tier_whitelist 过滤 + priority 排序，返回当轮要注入的 directives。"""
        with self._lock:
            fired = [
                d for d in self.directives.values()
                if d.state == 'active'
                and (not d.tier_whitelist or ctx.tier in d.tier_whitelist)
                and self._safe_trigger(d, ctx)
            ]
            fired.sort(key=lambda d: -d.priority)
        return fired

    def record_fire(self, ids: list[str]): ...                   # β.0.2
    def record_rejection(self, ids: list[str]): ...              # β.0.2
    def record_helped(self, id: str, helped: bool): ...          # β.0.5
    def dump_human(self) -> str:                                  # 给 Sir 看的 ASCII 表
        ...

    def load(self): ...     # 启动时从 JSON 恢复 fired/rejected/last_triggered 等运行时计数
    def persist(self): ...  # _dirty 时写回 JSON
    def persist_async(self): ...  # decay_worker 每 30s 检查
```

**线程安全**：所有写操作走 `self._lock`。

**持久化**：`memory_pool/directive_registry.json`，单文件。每条 directive 的 `text` / `trigger` 由代码定义（不存 JSON，避免 lambda 反序列化），仅存运行时数据（fired / rejected / last_triggered / state 等计数器）。

**与 PlanLedger 一致**：`autosave_interval_s=30` 由后台 worker（接到 `directive_decay_worker` 旁边）触发。

---

## 5. 12 条 Directive Bootstrap 清单（β.0.1 一次性入册）

| # | id | source_marker | text 摘要 | priority | tier_whitelist | trigger 简述 |
|---|---|---|---|---|---|---|
| 1 | `nudge_agenda_honesty` | P0+18-f.2 | "NO tool to mute SilentNudge. FORBIDDEN: I've struck/muted/removed. Honest: Acknowledged, cooldown engaged." | 9 | [] | 上轮 Jarvis 含 "I've X" / "已 X" **AND** 本轮 Sir 说"不用再提"/"stop" |
| 2 | `continuity_two_parts` | NEW (β.0) | "MULTI-INTENT: Address BOTH callback + new topic in order. Do not skip either." | 8 | [] | STM 非空 **AND** user_input 含 "对了/另外/by the way/and also/还有" **AND** ≥12 chars |
| 3 | `tool_honesty_directive` | P0+18-d.6 | "FAST_CALL fail → admit plainly. Never claim 'done' on failed call." | 9 | [SHORT_CHAT, TOOL_REQUEST] | 上轮有 FAST_CALL **AND** 上轮 last_tool_results 含 fail |
| 4 | `fuzzy_candidates_policy` | P0+18-b.8 | "FUZZY: list candidates if not exact match. Ask Sir to pick." | 7 | [SHORT_CHAT, TOOL_REQUEST] | user_input 含 "查/find/search/进程/文件" |
| 5 | `promise_protocol_directive` | 轴3-L3.2 | "PROMISE/ACTIVATE_PLAN/RESUME_PLAN 标签结构化语义。" | 8 | [DEEP_QUERY, TOOL_REQUEST, CRITICAL] | plan_ledger 有 awaiting_go / paused plan |
| 6 | `bilingual_directive` | - | "Speak English. Append `---ZH---` Chinese translation at the VERY END." | 10 | [] | ALWAYS（最高优先级，未来可视情况收紧）|
| 7 | `search_directive` | - | "For current events / news / real-time data → MUST use Google Search." | 6 | [DEEP_QUERY, CRITICAL] | user_input 含 "新闻/news/最近/recent/今天/today" 等时效词 |
| 8 | `memory_callback` | - | "Reference memories naturally, sparingly. Do not lecture from memory." | 5 | [DEEP_QUERY] | ltm_context 非空 **AND** STM 有早期相关引用 |
| 9 | `image_context` | - | "Screenshot attached. Use as ultimate truth." | 6 | [DEEP_QUERY, TOOL_REQUEST, CRITICAL] | 本轮启用 vision（screenshot strategy != none）|
| 10 | `system_environment` | - | "Windows OS Chinese. Use Chinese folder names in tool params." | 4 | [TOOL_REQUEST, CRITICAL] | user_input 含路径/文件相关词 |
| 11 | `smart_routing_working_feed` | P0+18-d.7 | "Clipboard/PowerShell/window history → answer from working_feed FIRST, no tool call." | 7 | [SHORT_CHAT, FACTUAL_RECALL] | working_feed 非空 **AND** user_input 含 "刚才/just now/我刚" |
| 12 | `correction_writepath_no_tool` | P0+18-d.3 | "Memory/Reminder/Correction WRITE → ACK + ---ZH--- + <AWAIT_GATEKEEPER>. Do NOT call tool." | 9 | [] | user_input 含 "记住/记一下/提醒/纠正/correct" 等 |

**bootstrap 代码示例**（β.0.1 一次性写入 `jarvis_directives.py:bootstrap_default_registry()`）：

```python
def bootstrap_default_registry(registry: DirectiveRegistry):
    # #1
    registry.register(Directive(
        id='nudge_agenda_honesty',
        source_marker='P0+18-f.2',
        priority=9,
        tier_whitelist=[],
        ttl_days=60,
        text=textwrap.dedent("""\
            [NUDGE / AGENDA HONESTY]:
            You have NO tool to mute SilentNudge / Conductor / dormant_project nudges.
            FORBIDDEN unless a real <FAST_CALL> in this turn:
              "I've struck it...", "I've muted...", "已从议程中删除", "我已经把它从待办里去掉".
            Honest fallback:
              "Acknowledged, Sir. Cooldown engaged automatically."
              "Noted — that prompt is on cooldown."
        """),
        trigger=_trigger_nudge_agenda_honesty,
    ))
    # ... #2-#12 类似
```

trigger 函数集中在 `jarvis_directives.py` 同文件下方，每个 ≤ 10 行。

---

## 6. 衰减算法 (`directive_decay_worker`)

后台 daemon，每 60s tick 一次：

| 条件 | 动作 | 备注 |
|---|---|---|
| `time.time() - last_triggered > ttl_days * 86400` AND `fired == 0` | state → `dormant` | 该 directive 从未命中，可能 trigger 写错了或场景消失 |
| `time.time() - last_triggered > ttl_days * 86400` AND `fired > 0` | state → `dormant` | 历史命中过但近 ttl_days 没命中（场景过去了）|
| `rejected >= 3` AND `fired > 0` | state → `review`（不参与装配）| Sir 看 `memory_pool/directive_review.json` 决定改/删/留 |
| `rejected / max(fired, 1) > 0.3` AND `fired >= 5` | priority -= 2（不低于 1）| Jarvis 学不进去这条，降权减少噪音 |

`dormant` 状态可由 Sir 手动恢复：`registry.activate(id)`。

`review` 队列写到 `memory_pool/directive_review.json`，Sir 可在任何时候用一个简短 CLI 命令 review。

---

## 7. Gemini-3-Flash 评分异步链（β.0.5）

### 7.1 配置

```python
EVALUATOR_CONFIG = {
    'primary': 'google/gemini-3-flash-preview',          # 通过 OpenRouter
    'fallback': 'google/gemini-3-flash-lite-preview',    # 配额满/熔断时降级（确切名以 OpenRouter 实际可用为准）
    'temperature': 0.0,
    'max_output_tokens': 80,
    'timeout_s': 3.0,                                    # 3s 超时直接丢弃（评分不阻塞业务）
    'async_pool_size': 4,
    'rate_limit_per_minute': 60,                         # 防止单分钟刷爆
}
```

### 7.2 调用链

```
[Jarvis stream_chat 完成] → ChatBypass.gatekeeper_async() 同一时刻
                          → DirectiveEvaluator.evaluate_async(directives_fired, jarvis_reply, user_input)
                          ↓
                   ThreadPoolExecutor (size=4)
                          ↓
                  safe_openrouter_call(model='google/gemini-3-flash-preview', ...)
                          ↓
              parse {is_followed: yes/no/partial, reason: str}
                          ↓
            registry.record_helped(directive_id, helped=True/False)
                          ↓
                   _dirty = True
                          ↓
            (60s 后 decay_worker 调 registry.persist())
```

**关键约束**：
- 评分调用**不走主对话 key 池**（不抢主脑配额），单独配 `key_router.get_evaluator_key()`
- 失败时（timeout / 配额 / network）静默丢弃，bg_log 记一行，不影响 registry 正确性
- `safe_openrouter_call` 已有 `network_retry`，复用

### 7.3 评分 prompt 模板

```python
EVALUATOR_PROMPT = """You are a directive compliance auditor. Given a directive and Jarvis's reply, judge whether the reply followed the directive.

[DIRECTIVE]:
{directive_text}

[USER INPUT]:
{user_input}

[JARVIS REPLY]:
{jarvis_reply}

Output ONLY a JSON object:
{{"is_followed": "yes" | "no" | "partial", "reason": "≤ 30 chars"}}
"""
```

### 7.4 月成本估算（按 600 次评分/天 × 30 天 = 18000 次/月）

| 项 | flash | flash-lite |
|---|---|---|
| input ~500 token × $0.0001/1K | $0.05/1K calls | $0.0125/1K |
| output ~50 token × $0.0004/1K | $0.02/1K calls | $0.005/1K |
| **月成本** | **~$1.26** | **~$0.32** |

primary=flash 即使全月不熔断，**月成本 < $2**（实际数据以 OpenRouter 计费为准）。

---

## 8. 6 个 Sub-step 详情

### β.0.1：建 `jarvis_directives.py`（2h）

**文件清单**（新增）：
- `jarvis_directives.py`：Directive dataclass + DirectiveRegistry + 12 个 trigger 函数 + bootstrap_default_registry
- `tests/_test_p0_plus_20_beta0_1_registry.py`：~30 testcase 覆盖 register / collect / persist / load / state 转换

**改动文件**（无 — β.0.1 不改 _assemble_prompt，是纯新增）。

**验收**：
- `python -c "from jarvis_directives import bootstrap_default_registry, DirectiveRegistry; r = DirectiveRegistry(); bootstrap_default_registry(r); print(len(r.directives))"` 输出 `12`
- `pytest tests/_test_p0_plus_20_beta0_1_registry.py` 全绿
- `pytest tests/` 1098 testcase 全绿（无回归）

### β.0.2：dry-run + SHORT_CHAT/WAKE_ONLY 切换（1.5h）

**改动文件**：
- `jarvis_central_nerve.py:_assemble_prompt`：在现有 5 个 branch 顶部加 dry-run：

```python
if ctx_l2_dryrun_enabled:
    ctx = DirectiveContext(user_input, last_reply, stm, prompt_tier, ledger_data, soul_tags, current_hour)
    fired = directive_registry.collect(ctx)
    bg_log(f"[L2 dry-run] tier={prompt_tier} fired={[d.id for d in fired]} legacy={legacy_l2_injected}")
```

跑 24h dry-run，bg_log 比对新机制要注入的 L2 directive **vs** 老机制实际注入的（`tool_honesty_directive` / `fuzzy_candidates_policy` / `[NUDGE / AGENDA HONESTY]` 段内联在 PERSONA 等）。

- 一致：β.0.3 起切实际注入
- 不一致：bg_log 看哪条 trigger 写错了 / priority 不对，修

dry-run 通过后，切 SHORT_CHAT + WAKE_ONLY 用新机制（这俩 tier 占今早 09:23 流量 ~60%，是低风险 / 高曝光的验证池）。

### β.0.3：L0 精简 + 切高 tier（1h）

**改动文件**：
- `jarvis_central_nerve.py`：
  - `JARVIS_CORE_PERSONA`（line 129-181）：从 53 行砍到 ~25 行（**iterate 路线**：搬出 NUDGE / BILINGUAL / SMART ROUTING / TOOL USE / MEMORY/REMINDER/CORRECTION / 具体短语黑名单到 Registry，保留 butler 身份 + INTEGRITY 4 条铁则 + 新增 TWO_PARTS 一句）
  - `_assemble_prompt`：删除内联 `[BILINGUAL DIRECTIVE]` / `[SEARCH DIRECTIVE]` / `[MEMORY CALLBACK]` / `[IMAGE CONTEXT]` / `[SYSTEM ENVIRONMENT]` / `[CONTINUITY RULE]` （这些都进 Registry）
  - `how_to_respond` cached block：缩到 ~1000 chars（保留 default 风格规则 + ASR 错误处理；搬出 SMART ROUTING / TOOL USE / MEMORY WRITE 段）
  - `tier_routing` cached block 不动（这是 Tier 1-3 路由规则，仍然全 tier 注入但可考虑搬到 L2 by tier）

- `profile_card.to_prompt_block()`（jarvis_routing.py）：1509 → ~800 chars，取最近 7 天 diff

### β.0.4：decay daemon + Sir review JSON（0.5h）

**改动文件**：
- `jarvis_directives.py`：加 `DirectiveDecayWorker`（threading.Thread daemon，每 60s tick）
- `jarvis_central_nerve.py`：`__init__` 启动时 `self.directive_registry.start_decay_worker()`，跟现有 `_start_backfill_worker` 同位置

**新增 CLI 命令**（脚本 `scripts/registry_dump.py`）：
```bash
python scripts/registry_dump.py             # 打印 ASCII 表
python scripts/registry_dump.py --review    # 只列 review 队列
python scripts/registry_dump.py --activate nudge_agenda_honesty   # Sir 手动激活
```

### β.0.5：Gemini-3-Flash 评分异步链（1.5h）

**新文件**：
- `jarvis_directive_evaluator.py`：`DirectiveEvaluator` 类 + `evaluate_async` + `safe_openrouter_call` 集成

**改动文件**：
- `jarvis_chat_bypass.py:gatekeeper_async`：评分时把 fired directives + reply 喂给 evaluator
- `jarvis_key_router.py`：加 `get_evaluator_key()` 返回独立 Google key（避免抢主对话配额）

**验收**：
- 真机一轮跑 5 个对话，bg_log 看 `[Evaluator]` 行有 `helped=yes/no/partial`
- 失败/超时不影响主对话（拔网线测试）

### β.0.6：1098 testcase + 真机一轮 + dashboard 验收（0.5h）

**验收 checklist**（全勾才算 β.0 完工）：
- [ ] `jarvis_directives.py` 行数 < 800
- [ ] `pytest tests/` 1098+ testcase 全绿
- [ ] `python jarvis_nerve.py` 启动成功 + Sir 实测一轮完整对话
- [ ] **TWO_PARTS 实测**：Sir 故意说复合句 5 次，至少 4 次 Jarvis 答两段
- [ ] **Integrity 误报**：实测 5 个陈述句 / 共情句，0 次误报
- [ ] `[Prompt Size]` 日志：DEEP_QUERY 总 < 19000 chars
- [ ] `[Asm Diag]` 日志：assemble 总耗时 < 450ms
- [ ] `[Pipeline Timer] TTFT`：< 2.6s（保守目标）
- [ ] `python scripts/registry_dump.py` 输出符合预期
- [ ] `[Evaluator]` 异步评分链路 OK，bg_log 能看到 helped 信号写回

---

## 9. 风险表 & 回滚预案

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| trigger 函数写错 → 应注入的 directive 没注入 | 中 | LLM 行为退步 | β.0.2 dry-run 24h 双跑对比，bg_log 暴露不一致 |
| L0 精简后 PERSONA 语气漂移（Sir 觉得"不像 Jarvis 了"）| 低 | UX 退步 | iterate 路线只搬 directive 不动 PERSONA 主体；漂移则 `git revert` β.0.3 单独回滚 |
| Registry persist 写盘抢 Hippocampus SQLite 锁 | 低 | 偶发卡顿 | persist 用独立 JSON 不走 SQLite，0 竞争 |
| Gemini-3-Flash 评分配额满 / 熔断 | 中 | helped 信号缺失 | fallback 到 flash-lite + 失败静默丢弃，registry 正确性不依赖评分 |
| Sir review 队列没人看 → 堆积 | 中 | directive 失效 | review JSON 每加一条 bg_log + UI 红点（β.1 候选）|
| dry-run 双跑期间装配耗时翻倍 | 低 | TTFT 变慢 | dry-run 用 try/except + 异步 bg_log，主路径不阻塞；β.0.3 切完即关闭 dry-run |
| Sir 实测发现新 directive 漏掉了关键场景 | 中 | LLM 该说没说 | bootstrap 12 条只是 v1，后续 Sir 可在 review 队列加新 directive 走 `registry.register()` |

**回滚预案**：6 个 sub-step 各自独立 commit。最差情况 `git revert <commit>` 单独回滚某个 sub-step，前几步成果保留。

---

## 10. 工程量预估 & 落地建议

| 阶段 | 估时 | 累计 |
|---|---|---|
| β.0.1 Registry | 2.0h | 2.0h |
| β.0.2 dry-run + 切 SHORT_CHAT/WAKE_ONLY | 1.5h | 3.5h |
| β.0.3 L0 精简 + 切高 tier | 1.0h | 4.5h |
| β.0.4 decay daemon | 0.5h | 5.0h |
| β.0.5 Gemini-3-Flash 评分 | 1.5h | 6.5h |
| β.0.6 全测 + 真机 + dashboard | 0.5h | **7.0h** |

**建议节奏**：分 2 个 session 做。
- Session 1（4h）：β.0.1 + β.0.2 + dry-run 24h（等 Sir 自然用一天）
- Session 2（3h）：β.0.3 + β.0.4 + β.0.5 + β.0.6

**前置条件**（P0+20-α 收尾完工）：
- ✅ rotate 8 keys（Sir 手动）
- ✅ 填 `.env`（Sir 手动）
- ✅ `git init` + 首次 commit（Sir 手动）
- ✅ `jarvis_key_router.py` 补 `import numpy as np`
- ✅ KeyRouter PROJECT_DENIED 永久剔除（3 次失败后不再轮转）
- ✅ Integrity Check 加 `is_action_claim` pre-filter 闸门
- ✅ `dormant_project` standby < 60s 内禁触发

---

## 11. 完工归档协议（参考 NERVE_SPLIT_PLAN.md §6）

完工时（β.0.6 通过后）：
1. 本 design doc **不动**，保留作为历史参考
2. `TODO.md` 把当前 P0+20-β.0 看板**精简成 1 段「上轮完工速览」**
3. 原上轮速览段（P0+19）+ P0+20-β.0 完整看板**整段沉档到 `docs/TODO_ARCHIVE.md` 顶部**
4. archive 目录表插入新行：`P0+20-β.0 / 2026-05-XX / Prompt 重构 + Directive Registry`
5. `TODO.md` 在「当前迭代」段写新一轮看板（候选 β.0.next 或 B1 真实长任务）

---

*文档作者：Claude 4.7 / Sir 2026-05-16 10:20*
*详见对话上下文：今早 09:23 真机实测 + 09:45-10:20 设计讨论 + 模型选择 4 轮迭代（行为信号 → LLM → 本地 vs 云 → flash vs flash-lite）*
