# Dashboard 重构盘点 — β.5.41 (Sir 16:43 真理)

> Sir 16:43 关键要求:
> 1. **所有 Sir 拍板的事全面出现在面板**
> 2. **交互设计要清晰明了**
> 3. **交互后的状态要能实时看到**
> 4. **让我知道操作会影响什么**
> 5. **重构这部分能力和面板的 UI 设计**

---

## 1. 盘点结果 — 21 类 Sir 可操作项

### A. Review Queue 类 (L7 propose 等 Sir 拍板, 11 类)

| # | 类别 | 源文件 | Schema | 当前 dashboard? |
|---|---|---|---|---|
| 1 | **concerns review** | `memory_pool/concerns_review.json` | id/what_i_watch/why_i_care/severity | ✅ scan |
| 2 | **inside_jokes review** | `memory_pool/relational_review.json.inside_jokes` | id/phrase/birth_context/tone | ✅ scan |
| 3 | **threads review** | `memory_pool/relational_review.json.shared_history_threads` | id/title/highlights | ✅ scan |
| 4 | **screen_tease review** | `screen_tease_vocab.json.review_queue` | id/keywords/directive_hint | ✅ β.5.39-fix |
| 5 | **struggle vocab review** | `sir_struggle_vocab.json.review_queue` | id/patterns/severity | ✅ β.5.39-fix |
| 6 | **directives review** | `directives_vocab.json.review_queue` + `directive_review.json` | id/text/priority/state | ✅ β.5.39-fix |
| 7 | **sleep_pattern review** | `sir_sleep_pattern_vocab.json.review_queue` | typical_hour/source | ✅ β.5.39-fix |
| 8 | **behavior_inference review** | `behavior_inference_vocab.json.review_queue` | id/keywords/kind | ✅ β.5.39-fix |
| 9 | **callback review** | `cross_session_callback.json` (state=review) | when/action | ✅ β.5.33 |
| 10 | **cooldown vocab review** | `proactive_care_cooldown_vocab.json.review_queue` | key/proposed/rationale | ✅ β.5.24 |
| 11 | **rejected history** (各 vocab) | `rejected_history` segments | Sir 可恢复 | ❌ 无入口 |

### B. Active State 类 (已生效, Sir 可修正/删除, 9 类)

| # | 类别 | 源文件 | Sir 可操作 | 当前 dashboard? |
|---|---|---|---|---|
| 12 | **active concerns** | `concerns.json` (state=active) | 改 severity/why_i_care, 归档 | 🟡 只展示 |
| 13 | **active inside_jokes** | `relational_state.json.inside_jokes` (active) | 改 phrase/tone, 归档 | 🟡 只展示 |
| 14 | **active threads** | 同上.shared_history_threads (active) | 改 title/highlights | 🟡 只展示 |
| 15 | **active unspoken_protocols** | 同上.unspoken_protocols (active) | 改 rule | 🟡 |
| 16 | **active unfinished_business** | 同上.unfinished_business (state=open/active) | 改 topic/状态 | 🟡 |
| 17 | **active screen_tease categories** | `screen_tease_vocab.json.categories` (active) | 改 keywords | ❌ |
| 18 | **active sir_struggle phrases** | `sir_struggle_vocab.json.phrases` (active) | 改 patterns/severity | ❌ |
| 19 | **active commitments** | hippocampus DB `commitments` 表 | cancel | ✅ web β.5.25 |
| 20 | **active directives** | `directives_vocab.json.directives` (active) | 改 priority/state | ❌ |

### C. Sir 自己加的 (1 类)

| # | 类别 | 源文件 | Sir 可操作 | 当前 dashboard? |
|---|---|---|---|---|
| 21 | **sir_profile** | `jarvis_config/sir_profile.json` | 改任何 field (走 apply_correction API) | ❌ 无入口 |

---

## 2. 当前 dashboard 缺口

| 缺口 | 严重度 |
|---|---|
| **active state 没修正按钮** (12-20) — Sir 只能看, 改要走 CLI 工具 | 🔴 主诉 |
| **没"影响预览"** — Sir 改 inside_joke phrase 不知会影响下次主脑引用 | 🔴 主诉 |
| **没实时状态** (修正后要刷新才看到) | 🟠 |
| **没统一 API** — 每个源单独 endpoint, UI 散乱 | 🟠 |
| **没 sir_acked 状态** — Sir 看过 vs 没看的不区分 | 🟠 |
| **active sir_profile / directives 无入口** | 🟡 |
| **rejected_history 无入口** (Sir 误删想恢复也没法) | 🟡 |

---

## 3. β.5.41 重构方案 (4 sub-step)

### β.5.41-A: Backend 统一抽象 (~2h)

新模块 `jarvis_actionable_items.py`:
```python
def get_all_sir_actionable_items(filter_category=None, filter_state=None) -> List[ActionableItem]:
    """返回所有 Sir 可操作 item, 统一 schema."""
```

`ActionableItem` 统一 schema:
```python
{
  'id': 'joke_furniture_dang_a3f7',
  'category': 'inside_joke',  # 21 类之一
  'subcategory': 'relational',   # group
  'state': 'review' / 'active' / 'archived',
  'preview': '家具党 — Sir 说自己买家具上瘾',
  'fields': {  # 可修正字段
    'phrase': '家具党',
    'birth_context': 'Sir 说自己买家具上瘾',
    'tone': 'self-deprecating',
  },
  'impact_if_modified': 'Jarvis 下次引用此梗时会用新文本, 影响 ~50% 主脑 reply',
  'impact_if_deleted': 'Jarvis 永远不会再引用 (archived, 可恢复)',
  'created_at': 1779260000,
  'sir_acked': False,
  'auto_proposed': True,
  'proposed_by': 'InsideJokeReflector',
  'use_count': 3,
  'last_used_at': 1779280000,
}
```

### β.5.41-B: API endpoints 扩 (~1h)

在 `scripts/jarvis_dashboard_web.py` 加:
- `GET /api/items?category=&state=` — list ActionableItem
- `POST /api/items/<id>/modify` — Sir 修正 (写 corrections.jsonl + update vocab)
- `POST /api/items/<id>/delete` — Sir 归档 (item.state=archived + 写 corrections.jsonl)
- `POST /api/items/<id>/restore` — 从 archived 恢复
- `POST /api/items/<id>/ack` — Sir 看过 (sir_acked=true, dismiss 提醒)
- `POST /api/items/<id>/activate` — review → active (老路径保留)
- `POST /api/items/<id>/reject` — review → archived

### β.5.41-C: UI 重构 (~2-3h)

`scripts/jarvis_dashboard_web.py` 主区改 3-pane layout:

```
┌───────────────────────────────────────────────────────────────┐
│ Sidebar       │ Card stream                  │ Detail panel   │
│ ─────────     │ ──────────────────────────── │ ─────────────  │
│ 🔥 Review (8) │ ┌──────────────────────────┐ │ id: ...        │
│ 💭 Jokes (12) │ │ 📅 family_furniture      │ │ category: ...  │
│ 🎯 Concerns 5│ │   "家具党"               │ │ fields:        │
│ 📜 Threads 4 │ │   [auto / 3天前 / 已看]  │ │   phrase:[___] │
│ ⏱️ Tasks 1   │ │   [👁 看] [✏ 修正] [🗑 删]│ │   tone:[___]   │
│ 🎬 Screen 3  │ │   ⚠ 改此条会影响下次引用 │ │ impact: 改影响│
│ 🆘 Struggle 5│ ├──────────────────────────┤ │   50% reply tone│
│ 📡 Directives│ │ 🎯 concern_back_health   │ │ [保存] [取消]  │
│ 💤 Sleep     │ │   "Sir 30 天没拉伸"      │ │                │
│ ⏰ Cooldown  │ │   [active / 1天前 / 未看 ⚠]│ │                │
│ 📞 Callbacks │ │   [👁] [✏] [🗑]           │ │                │
│ 👤 Profile   │ │ ...                       │ │                │
│ 🗑 Rejected  │ │ (上下滑动看更多)         │ │                │
└───────────────┴──────────────────────────────┴────────────────┘
```

**UI 特性**:
- 左 sidebar: 21 类分组, 每类显示数量
- 中卡片流: 当前选中类目所有 item, 卡片含 preview + 状态标记 + 3 操作按钮
- 右 detail panel: 点 [✏ 修正] 时显示, 含所有可修字段 + 影响预览 + 保存按钮
- 实时刷新: WebSocket 或 5s 轮询
- Toast 反馈: 修正/删除后立刻显示 "✅ 已修正, Jarvis 下次会用新版"
- Sir 看过 30s 自动 ack (不弹窗, 静默)
- 未 ack ⚠️ 标记 + 顶部红点提醒

### β.5.41-D: corrections.jsonl + 主脑 prompt 注入 + 自动 ack (~1h)

- `memory_pool/sir_corrections.jsonl` (append-only):
  ```jsonl
  {"ts":..., "iso":..., "category":..., "item_id":..., "old":{...}, "new":{...}, "sir_note":"..."}
  {"ts":..., "category":..., "item_id":..., "action":"delete", "reason":"..."}
  ```

- 主脑 prompt assembler 加 `[SIR CORRECTIONS / last 24h]`:
  ```
  - inside_joke "家具党" → Sir 纠: 不是"上瘾", 是"搬家"
  - concern "back_health" → Sir 删了 (说"不需要这个")
  ```

- `sir_acked_state.json` (Sir 看了哪些 item, 30s 后 auto ack):
  ```json
  {"item_acks": {"joke_furniture_dang_a3f7": 1779280030, ...}}
  ```

### β.5.41-E: 测试 (~1h)

- Backend: 21 类全 cover, modify/delete/restore/ack 闭环
- corrections.jsonl 写入 + 主脑 prompt 注入  
- UI HTML render

---

## 4. 总时长估算 + 顺序

| sub-step | 时长 | 依赖 |
|---|---|---|
| **A** Backend abstract | ~2h | 无 |
| **B** API endpoints | ~1h | A |
| **C** UI 重构 | ~2-3h | B |
| **D** corrections + ack | ~1h | A |
| **E** tests | ~1h | A-D |

**总 ~7-8h**, 1 个长 session 可完.

---

## 5. 等 Sir 拍板确认

1. **21 类范围对吗?** 我盘点全了 (Sir 看是否有漏)
2. **UI 布局: 3-pane sidebar + cards + detail? 还是其他**?
3. **修正不动 vocab 文件 vs 直接 mutate?** 我建议: 直接 mutate vocab (Sir 改了立刻生效) + 同时写 corrections.jsonl 留痕
4. **sir_acked 自动 30s 合适吗?** 或要 Sir 显式点 "已看"?
5. **callback / cooldown / dangerous 操作要不要保留二次确认?** (大多 vocab 我建议 not)
6. **rejected_history 入口要不要?** (Sir 误删想恢复, 我建议要)

---

**状态**: audit 完, 等 Sir 拍板范围 + sprint 启动.
