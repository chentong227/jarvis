# JARVIS 记忆系统统一重构 — Design Doc

> 2026-05-23 22:30 起草. Sir 真意 (22:14):
> "贾维斯的一切都依附于记忆, 没有记忆他的所有一切都是空中楼阁."
> "把贾维斯最最最最最重要的模块做的优雅."

---

## 0. TL;DR

| 项目 | 现状 | 目标 |
|---|---|---|
| **记忆 source 数** | 4+ 冗余 (STM / Hippocampus / Commitments / Profile / mutation_receipts / promise_log / ...) | 6 类 source 各 1 处 truth, 1 个 unified facade |
| **写路径** | 主脑 emit FAST_CALL ↔ Gatekeeper ↔ Reflector ↔ memory_correction 4 条 silo | 1 个 `MemoryHub.write()` 入口 → 自动 cascade 到所有相关 source |
| **读路径** | 主脑 prompt 拼 30+ render block, 各 source 独立 | 1 个 `MemoryHub.read_context()` → 拼成统一 prompt section |
| **同步性** | 改 1 source 不联动其他 (Sir 22:06 真测痛点) | Sir 教 1 次事 → cascade 自动同步多处 |
| **时长** | 当前 35+ 个 mem file + 30+ Reflector | 6 类 file + 6 类 Reflector 各 1 个 |
| **复杂度** | 7000+ lines memory-related py | ~3000 lines, 5x 易维护 |

---

## 1. 为什么需要重构 — Sir 实测痛点 audit (2026-05-23 18:00-22:11)

> 所有今晚的 BUG 都是记忆碎片的**症状**, 不是独立问题.

| 时间 | Sir 真测 | 表面 BUG | 真因 (记忆) |
|---|---|---|---|
| 17:02 | "我喝了八杯水" | 主脑 fabricate cup_ml=200/250/300 各种值 | profile.unit_preferences 没真持久化, ProfileReflector 24h tick 太慢 |
| 18:08 | "今天血压咨询去过了" | 22:00 commitment_check 又说"明天血压咨询" | Hippocampus 记 Completed 但 Commitments db `is_deleted=0`, **2 source 不同步** |
| 21:43 | "我喝了第九杯" | 主脑用 cup_ml=300 算对了, 但下轮又 fabricate | mutation_router 写 `profile.preferences.cup_ml` (错 path) → 不真改 |
| 21:59 | "为什么是这个数字" | 主脑承认用 200 但没看 profile.unit_preferences.cup_ml=300 | **profile retrieve 路径不一致** (render 看 unit_preferences, 主脑写 preferences) |
| 22:00 | mutation.update field=preferences.cup_ml | "(已 atomic 覆写)" log 但实际没改 | gateway split('.')[-1] 丢中间层 + overwrite_field 只 top-level → fallback audit only |
| 22:06 | "血压咨询是今天去的, 明天没安排" | "未找到与 '明天去血压咨询' 高度匹配的旧提醒" | Cancel intent 用 Sir 现在原话, Commitments description 是昨天创建时的话, **fuzzy match 没命中** |
| 22:11 | "10:30 叫我去洗澡" | "I have set a reminder" + "❌ 缺少 intent 参数" → 罐头 "I couldn't" | Gatekeeper 后台已注册 commitment 但**主脑不知道**, 又 emit FAST_CALL 重复 + 缺 intent. 撒谎 |

**共同根因**: **多 source 不同步 + 不互相知**.

---

## 2. 现状 audit (87 个 mem-related file + 30+ Reflector)

### 2.1 真实 source of truth (应该只有 6 类)

| # | 类别 | 含义 | 现状存哪 |
|---|---|---|---|
| **A** | **Identity** (Sir 是谁) | 静态身份 / 偏好 / 个人参数 | `jarvis_config/sir_profile.json` |
| **B** | **Events** (发生过什么) | Sir 做过的 / 系统观察到的 / Sir 教过完成的 | `jarvis_memory.db.TaskMemories` (Hippocampus) |
| **C** | **Commitments** (未来时间锚定) | "10:30 提醒" / "明天血压" / Sir 主动承诺 | `jarvis_memory.db.Commitments` |
| **D** | **Concerns** (我担心啥) | 持续关注的事 (sleep / hydration / posture) | `memory_pool/concerns.json` |
| **E** | **State** (此刻状态) | online / sleeping / stand_down / focus | `memory_pool/sir_status.json` |
| **F** | **Relations** (人际关系 / inside_jokes / threads) | Sir 的关系网 + 共享笑话 + 未完话题 | `memory_pool/relational_state.json` |

### 2.2 当前的冗余 + 散落

| 类 | 应有 1 处 | 实际散在 | 不同步表现 |
|---|---|---|---|
| **A Identity** | `sir_profile.json` | `sir_profile` + `profile_corrections.jsonl` (audit1) + `mutation_receipts.jsonl` (audit2) + `profile_review.json` (Reflector queue) | 主脑写 audit2 不改 main, Reflector 24h tick 才提案 |
| **B Events** | `TaskMemories` | `TaskMemories` (sql) + `stm_recent.jsonl` (30 turn 临时) + `sir_milestones.json` (大事) + `screen_history.jsonl` + `pending_callbacks.jsonl` + ... (~6 处) | STM 沉积到 TaskMemories 不可靠, 主脑 prompt 不一致 |
| **C Commitments** | `Commitments` table | `Commitments` (sql) + `cyclic_task_*` (mem_pool) + `jarvis_promise_log.json` + `pending_callbacks.jsonl` + `watch_tasks.json` (~5 处时间承诺系统) | 主脑用错 organ (commitments vs reminder vs cyclic), Gatekeeper 并发又一处 |
| **D Concerns** | `concerns.json` | `concerns` + `concerns_review.json` (Reflector queue) + `relational_state.violations[]` + ~10 个 `*_vocab.json` | concerns 改时 vocab 不知 |
| **E State** | `sir_status.json` | `sir_status` + `stand_down_state.json` + `sir_acked_state.json` + `relational_state.json (subset)` + `sir_struggle_vocab.json` | 各 sentinel 独立写, 状态查询要拼多处 |
| **F Relations** | `relational_state.json` | `relational_state` + `inside_jokes/` + `concerns.json (subset)` + `sir_milestones.json (subset)` | inside_jokes 散在 reflector 内, 看不全 |

**audit log 类** (~10 个 .jsonl): `profile_corrections` / `mutation_receipts` / `claim_revisions` / `integrity_audit` / `mutation_dump` / `main_brain_meta_audit` / `key_router_reset_audit` / `preflight_stats` / `stand_down_history` / `system_errors` — **过于碎片**. 应合并 1 个 `mem_audit.jsonl` 加 `kind` 字段.

**vocab 类** (~40 个 .json): 大部分合理 (Reflector 各自管自己的 vocab), 但**命名不统一** (有 `*_vocab.json`, 有 `*_keywords.json`, 有 `_base_*_vocab.json`).

---

## 3. 设计 — `MemoryHub` 统一架构

### 3.1 核心抽象

```
                       ┌─────────────────────────────────┐
   主脑 / Sentinel ───▶│        MemoryHub.write(record)  │
   Reflector / Sensor  └────────────┬────────────────────┘
                                    │
                       ┌────────────▼─────────────┐
                       │   record.kind 分发到 source  │
                       └────────────┬─────────────┘
                                    │
       ┌──────────┬─────────┬──────┴──────┬──────────┬──────────┐
       ▼          ▼         ▼             ▼          ▼          ▼
   Identity    Events   Commit-       Concerns    State    Relations
   (Profile)             ments
       │          │         │             │          │          │
       ▼          ▼         ▼             ▼          ▼          ▼
   sir_profile  Task    Commitments   concerns   sir_status   relational
     .json     Memories    table       .json       .json       _state.json
       │          │         │             │          │          │
       └──────────┴────┬────┴─────────────┴──────────┴──────────┘
                       │
                       ▼
                ┌──────────────────────────┐
                │  MemoryHub.cascade()     │
                │  跨 source 自动联动       │
                │  - 教 X 完成 → cancel C  │
                │  - 教参数 → update A    │
                │  - 教事件 → 写 B + cancel C │
                └──────────────────────────┘
                       │
                       ▼
                ┌──────────────────────────┐
                │  mem_audit.jsonl         │
                │  统一审计 (1 处)         │
                └──────────────────────────┘
```

### 3.2 统一 Record schema

```python
@dataclass
class MemoryRecord:
    # ─── 通用元数据 ───
    record_id: str          # uuid, mem_<6hex>
    kind: str               # 'identity_param' / 'event' / 'commitment' / 'concern_signal' / 'state_change' / 'relation_update'
    source: str             # 'sir_utterance' / 'main_brain_emit' / 'gatekeeper' / 'reflector_X' / 'sensor_Y'
    ts: float
    iso: str
    turn_id: str
    confidence: float       # 0.0-1.0

    # ─── 内容 (kind-specific 子字段) ───
    payload: dict           # 灵活 schema, 由 kind 决定结构

    # ─── 状态 ───
    state: str = 'active'   # 'active' / 'completed' / 'cancelled' / 'archived' / 'deleted'
    state_changed_at: float = 0.0
    state_changed_by: str = ''

    # ─── 关联 ───
    parent_id: str = ''     # 跨 source link (e.g. commitment 关联 event)
    related_ids: list = field(default_factory=list)

    # ─── audit ───
    audit_trail: list = field(default_factory=list)  # 历次 mutation
```

### 3.3 `MemoryHub.write(record)` — 统一入口 (取代 5+ silo)

```python
class MemoryHub:
    def write(self, record: MemoryRecord, cascade: bool = True) -> WriteReceipt:
        """统一 mutation. 路由到正确 source + cascade + audit."""
        # 1. 路由到 source (按 record.kind)
        source_module = self._route_source(record.kind)
        ok = source_module.persist(record)

        # 2. cascade (跨 source 联动)
        if cascade and ok:
            self.cascade(record)

        # 3. audit (统一 1 处)
        self._write_audit(record, ok)

        # 4. publish SWM event (准则 6 三维耦合)
        self._publish_swm(record, ok)

        return WriteReceipt(...)

    def cascade(self, record: MemoryRecord):
        """跨 source 自动联动 (治本 Sir 真意 "教一次, 多处同步")."""
        for rule in self._cascade_rules:
            if rule.matches(record):
                rule.execute(record, hub=self)

    def read_context(self, tier: str, max_chars: int = 4000) -> str:
        """统一 prompt section — 拼 6 source 的相关 evidence."""
        sections = []
        for src in self._sources:
            block = src.render_prompt_block(tier=tier, max_chars=max_chars // 6)
            if block:
                sections.append(block)
        return '\n\n'.join(sections)
```

### 3.4 Cascade rules — 跨 source 自动联动

```python
_DEFAULT_CASCADE_RULES = [
    # Sir 教完成 → Events 写 'Completed:X' + Commitments cancel X
    CascadeRule(
        name='completion_cascade',
        match=lambda r: r.kind == 'event' and r.payload.get('event_type') == 'completion',
        actions=[
            'events.write Completed:<summary>',
            'commitments.cancel_by_keyword(<noun_extracted>)',
            'concerns.dampen_if_related',
        ],
    ),
    # Sir 教参数 → Identity 真改 + 老 audit 标 superseded
    CascadeRule(
        name='param_update_cascade',
        match=lambda r: r.kind == 'identity_param',
        actions=[
            'identity.overwrite_field <path>',
            'mark prior corrections superseded',
            'publish sir_taught_param SWM',
        ],
    ),
    # Sir 取消承诺 → Commitments cancel + Promise mark_cancelled + Concerns dampen
    CascadeRule(
        name='commitment_cancel_cascade',
        match=lambda r: r.kind == 'commitment' and r.state == 'cancelled',
        actions=[
            'commitments.soft_delete <id>',
            'promise_log.mark_cancelled <related>',
            'concerns.dampen <related>',
        ],
    ),
    # Gatekeeper 注册 commitment → 主脑同 turn 跳重复 add_reminder (fix82-Z)
    CascadeRule(
        name='gatekeeper_register_signal',
        match=lambda r: r.kind == 'commitment' and r.source == 'gatekeeper',
        actions=[
            'publish sir_intent_deadline_candidate SWM',
            'mark "gatekeeper_handled" for chat_bypass skip',
        ],
    ),
    # ... 共 ~15 条 rules cover Sir 真意 cascade case
]
```

### 3.5 Prompt block 统一渲染

```python
# 老: _assemble_prompt 拼 30+ render block (~600 line code)
# 新: 1 个调用
prompt_evidence = memory_hub.read_context(tier='STANDARD', max_chars=4000)
# 内部: 6 source 各 render <500 char, 合并去重排序
```

---

## 4. 迁移路线 (1 周, 分 5 phase)

### Phase 1: foundation (Day 1, 4h)
- 创建 `jarvis_memory_hub.py` (MemoryHub + MemoryRecord + WriteReceipt + cascade engine)
- 创建 `memory_sources/` package: `identity.py` / `events.py` / `commitments.py` / `concerns.py` / `state.py` / `relations.py` (薄 adapter, wrap 现有 ProfileCard / Hippocampus / CommitmentWatcher / ConcernsLedger / SirStatus / RelationalState)
- 单 testcase 验 1 个 cascade (e.g. completion_cascade) 走通

### Phase 2: cascade rules (Day 2, 4h)
- 实现 ~15 条 cascade rules (按今晚 audit 出来的真实 case 设计)
- 每条配 testcase
- vocab 持久化到 `memory_pool/cascade_rules.json` (准则 6)
- CLI `scripts/cascade_rules_dump.py` 看 / 加 / 拒

### Phase 3: 写路径迁移 (Day 3-4, 6h)
- worker.memory_correction → `memory_hub.write(kind='identity_param')`
- IntentResolver tools → `memory_hub.write`
- Reflector propose → `memory_hub.write(state='proposed')` + Sir CLI activate → `state='active'`
- Hippocampus.seal_memory_async → `memory_hub.write(kind='event')`
- Gatekeeper → `memory_hub.write(kind='commitment', source='gatekeeper')` + cascade 自动 publish SWM
- 每一处迁移配 1098 个 existing testcase 验不破

### Phase 4: 读路径迁移 (Day 5, 4h)
- `_assemble_prompt` 30+ render block → `memory_hub.read_context()`
- 减少 prompt 重复 (现状 STANDARD tier ~36000 chars, 目标 ~25000 chars)
- 测主脑回答质量不降

### Phase 5: cleanup + audit consolidation (Day 6, 3h)
- 删 / 归并冗余 file (10+ audit jsonl → 1 mem_audit.jsonl)
- Deprecated 旧 API 加 warning 1 个版本周期后删
- testcase 全 pass + Sir 真测 OK + docs/AGENTS.md 更新

### Phase 6: extender hooks (Day 7, 持续)
- 暴露 `MemoryHub.register_source()` / `register_cascade_rule()` 给后续 module 加
- Sir 可加自定义 cascade rule via JSON + reload
- 1 个 `scripts/mem_hub_dump.py` 全局看 / debug

---

## 5. Acceptance Criteria — 重构成功的可测条件

> 这些是 Sir 痛点的直接验证 — 任何一条不达标 = refactor 失败

| # | Criteria | 验证方法 |
|---|---|---|
| 1 | Sir 教 "一杯 300 ml" 1 次 → 永久持久化 (重启后保留) | 重启 Jarvis 后 `cat sir_profile.json | grep cup_ml` = 300 |
| 2 | Sir 教 "X 已完成" → Commitments 表 mark deleted + Hippocampus 写 'Completed:X' + 主脑下轮 prompt 看到 | unit test cascade rule + Sir 真测后续问 X 不重提 |
| 3 | Gatekeeper 注册 commitment → 主脑同 turn 内**不**再 emit 重复 add_reminder | unit test SWM event + chat_bypass skip |
| 4 | Sir 取消 commitment → 同 keyword 的 promise / concern 也降级 | unit test cascade_cancel + Sir 真测 |
| 5 | 主脑 prompt 中所有 source 的 evidence 来自 1 个 `read_context()` 调用 (不是 30+ 散散 render block) | grep code: `_parts.append` < 5 处 |
| 6 | 重启后 60s 内 MemoryHub 加载 6 source 完成 | startup log timing |
| 7 | 35+ 个 mem-related file → 12+ (-65%) | `wc -l memory_pool/*.json` |
| 8 | 1098+ 个现有 testcase 全 pass | `pytest tests/` |

---

## 6. 风险 + 缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| **现有 30 个 Reflector 各自 hardcoded 写自己 file** | refactor 需大量改 | Phase 3 提供薄 adapter 兼容老 API, 渐进迁移 |
| **1098 testcase 验证耗时** | Phase 3-5 时间长 | 每 phase 末跑 regression, 不通过不进下一 phase |
| **Sir 真测可能发现新 cascade case** | 迁移中 Sir 痛点不断 | cascade rules 持久化 + L7 LLM-propose, Sir 可加新 rule 不改源码 |
| **prompt block 减少导致主脑能力下降** | reply 质量降 | Phase 4 测 100 个 Sir 真测 case, 质量降 > 5% 回滚 |

---

## 7. 不做的事 (out of scope)

- **不**重写 Hippocampus 的 embedding logic — 现状已足够
- **不**改 STM 的 30 turn 滚动 (那是工作记忆, 不是长期)
- **不**砍 vocab 系统 (40+ vocab json 是合理设计, 不冗余)
- **不**改主脑 prompt 长度 cap (Sir 不在乎 tokens)
- **不**改 ScreenVision / ASR / TTS — 这些不是记忆模块

---

## 8. 当前已做 (Phase 0 — 今晚 fix81-82)

- ✅ fix81 BUG-X: `ProfileCard.overwrite_field` 嵌套写 + `preferences.X` alias
- ✅ fix81 BUG-Y: ScreenVision 鼠标位置红圈
- ✅ fix82-X: MemoryGateway cascade_completion (准则 6 第 1 步) — vocab + cancel + add_completed_event
- ✅ fix82-Z: chat_bypass Gatekeeper skip dup add_reminder
- ✅ `Hippocampus.add_completed_event` + `list_recent_completed_events`
- ✅ Prompt `[RECENT COMPLETED]` block in `_assemble_prompt`

这些是**重构的第 0 阶段**, 不是新加 silo. 它们的 cascade logic / vocab / API 在 Phase 1-2 直接复用迁到 `MemoryHub`.

---

## 9. Sir 拍板需决定的事

1. **是否同意分 6 类 source** (Identity / Events / Commitments / Concerns / State / Relations)? 还是 Sir 想拆得更细?
2. **是否同意 1 周 phased migration**? 还是想更激进 / 更保守?
3. **是否同意每 phase 必须过 1098 testcase + Sir 真测**? (推荐)
4. **是否要 `MemoryHub` 暴露 Python API 给 Sir 写自定义 cascade rule**? (推荐, 准则 6)
5. **cascade_rules 是否要走 L7 LLM-propose** (Sir 教过的复杂 case 自动 propose new rule)?

---

## 10. 准则 6 三维耦合在记忆系统的体现

| 维度 | 在 `MemoryHub` 的体现 |
|---|---|
| **数据强耦合** | 所有 MemoryRecord publish 进 SWM (ConversationEventBus). 主脑 prompt 看 `to_swm_block()` 含所有 source 最近 mutation. |
| **行为弱耦合** | 各 source adapter 是 publish-only sentinel, 不 hard gate. cascade rule 是中央 LLM-augmented 决策, 不分散在 30 个 sentinel. |
| **决策集中主脑** | `cascade()` 是 deterministic (vocab-driven) + LLM-fallback (复杂语义). 主脑 prompt 看 [MEMORY CONTEXT] block 自决怎么 ack. |

---

## 11. 总结 — 为什么是优雅?

**老**: 30 个 reflector + 35 个 file + 30 个 render block + 5 个 audit jsonl + 5 个 silo write path = **大杂烩, 维护成本指数级**.

**新**: 1 个 `MemoryHub` + 6 source adapter + 1 cascade engine + 1 audit log + 1 read_context() = **优雅, 维护成本线性**.

Sir 真意: "贾维斯的一切都依附于记忆, 没有记忆他的所有一切都是空中楼阁."

→ 记忆模块的优雅 = Jarvis 整体的优雅.

— 本 design doc 由 Sir + Cascade 2026-05-23 22:30 起草, Sir 拍板后进入 Phase 1.
