# JARVIS Mutation Interface — 新 Source 接入协议

**起源**: `docs/JARVIS_MEMORY_AND_MUTATION_REFACTOR.md` Part 5  
**定位**: 给未来加新 source / memory module 时, 让它能**通用走 mutation refactor**.

> Sir 21:55 真痛点: "以后加上更多的记忆和知识和现状 (如 vision, 26 项本地数据等) 的模块时, 可以通用使用这个修正架构来修正".

---

# 1. 接入协议 (4 步)

## 1.1 实现 4 个标准接口

新 source class 必须实现 (或新增):

```python
class MyNewSource:
    # ----- (1) prompt 注入 (如要进 prompt) -----
    def render_prompt_block(self, max_chars: int = 300) -> str:
        """返回 [SOURCE_NAME] block 文本 (可空)."""
        ...

    # ----- (2) mutation 接口 (统一 schema) -----
    def update_field(self, field: str, new_value, source: str = '',
                       turn_id: str = '', reason: str = '') -> Tuple[bool, str, Any]:
        """Args:
              field: top-level field name
              new_value: 新值 (任意 JSON-serializable)
              source: caller 标识 ('fast_call_mutation' / 'sir_cli' / ...)
              turn_id: trace id
              reason: Sir 原话 / 主脑解读
            Returns: (ok, message, old_value)
        """
        ...

    # ----- (3) subject resolver (主脑模糊 keyword 找精确 ID) -----
    def find_by_keyword(self, keyword: str) -> Optional[str]:
        """返回 top-1 subject ID. e.g. 'Windsurf' → memory_id 1482"""
        ...

    # ----- (4) schema 白名单 (防主脑乱改) -----
    _OVERWRITE_ALLOWED_FIELDS = frozenset({...})  # top-level field 白名单
```

`update_field` 写源后必须:
- 写 audit trail (推荐 jsonl)
- SWM publish event (`<source>_field_updated` 或类似 etype)
- 不 raise — 错误返回 (False, message, old_value)

## 1.2 注册到 LAYER_REGISTRY

修 `jarvis_memory_gateway.py:_detect_target_layer`:

```python
def _detect_target_layer(field_path: str) -> str:
    fp = field_path.lower()
    # ... existing
    if fp.startswith(('my_new_source.',)):
        return 'MyNewSource'
    return 'unknown'
```

并在 `update_sir_field` 内加 `elif layer == 'MyNewSource':` 路由 (复用模式).

## 1.3 把 instance 挂到 nerve

```python
# jarvis_central_nerve.py __init__
self.my_new_source = MyNewSource(...)
```

gateway 通过 `getattr(nerve, 'my_new_source', None)` 拿到.

## 1.4 (可选) 加 prompt 注入点

如新 source 要进 prompt, 在 `_assemble_prompt` 适当位置加:

```python
try:
    if self.my_new_source is not None:
        block = self.my_new_source.render_prompt_block(max_chars=300)
        if block:
            _parts.append(block)
except Exception:
    pass
```

---

# 2. 主脑 Emit FAST_CALL 协议

主脑学一次 `correction_dispatcher` directive, 自动支持新 source. **不需要为新 source 加新 directive**.

主脑 emit:

```json
<FAST_CALL>{"organ":"mutation","command":"update","params":{
  "field_path": "my_new_source.<field>",
  "new_value": "...",
  "intent": "revise",
  "reason": "Sir 教正: ..."
}}</FAST_CALL>
```

ChatBypass FAST_CALL parser 自动:
- 拿 `field_path` 前缀路由到 `MyNewSource`
- 调 `update_field` (高置信路径) 或 fallback (低置信路径)
- 写 mutation_receipts.jsonl
- SWM publish
- 返回人话 result 给主脑下轮看

---

# 3. ClaimTracer 集成 (自动)

Mutation 跟 ClaimTracer **自动协同**:
- 主脑 reply 含 "I've updated / 已记下 / 已修正" 等 mutation verb
- ClaimTracer 抓本轮 `mutation_receipts.jsonl` 是否有真 receipt
- 没有 → 标 unverified → 下轮 INTEGRITY ALERT

新 source 实现 `update_field` 写 receipt 后, **自动获得诚信审计**, 不需新加 ClaimTracer 规则.

---

# 4. 已有 6 layer 路由参考

| layer | source | field_path 格式 | 实现位置 |
|---|---|---|---|
| A 静态身份 | ProfileCard | `profile.<top_field>` | `jarvis_routing.py:overwrite_field` |
| A 静态身份 | Milestones | `milestone.<title>` | `jarvis_tool_registry.py:tool_milestone_register` |
| B 长期信念 | ConcernsLedger | `concerns.<cid>` | `jarvis_concerns.py:record_signal` |
| B 长期信念 | RelationalStateStore | `relationships.archive.<jid>` / `protocol.archive.<pid>` / `unfinished.done.<uid>` / `thread.archive.<tid>` | `jarvis_relational.py:archive_*` / `mark_unfinished_done` |
| C 长期事实 | Hippocampus LTM | (走 `memory_hands.modify_record` hand) | `jarvis_hippocampus.py` |
| D 当前状态 | StandDown | (走 `stand_down` 专 organ) | `jarvis_stand_down.py` |
| D 当前状态 | SirStatus | (待加) | `jarvis_sir_status_tracker.py` |
| E 承诺 | PromiseLog | `promise.fulfill.<k>` / `promise.cancel.<k>` (推荐 promises 专 organ) | `jarvis_promise_log.py:mark_*` |
| E 承诺 | CommitmentWatcher | `commitment.cancel.<k>` / `commitment.update.<k>` | `jarvis_commitment_watcher.py:cancel_by_keyword/update_by_keyword` |
| F 教学 | DirectiveRegistry | (Sir CLI 改, 主脑暂不 emit) | `scripts/registry_dump.py` |

---

# 5. 例: 加 Vision Local DB (Sir 提的 26 项本地数据)

假设有 sqlite `local_knowledge.db` 含 Sir 本地资料:

## 5.1 实现 jarvis_local_db.py

```python
class LocalKnowledgeDB:
    _OVERWRITE_ALLOWED_FIELDS = frozenset({
        'description', 'tags', 'category',
    })

    def render_prompt_block(self, max_chars=300):
        # query 最近 N 条 + format
        ...

    def update_field(self, field, new_value, source='', turn_id='', reason=''):
        # validate field in whitelist, write to sqlite, audit, SWM publish
        ...

    def find_by_keyword(self, keyword):
        # SQL LIKE / fuzzywuzzy match
        ...
```

## 5.2 注册到 gateway

```python
# jarvis_memory_gateway.py:_detect_target_layer
if fp.startswith(('local_knowledge.', 'local_db.')):
    return 'LocalKnowledgeDB'

# update_sir_field elif
elif layer == 'LocalKnowledgeDB':
    db = getattr(nerve, 'local_db', None)
    if db is not None:
        # field_path: 'local_db.<id>.<field>'
        parts = field_path.split('.', 2)
        item_id = parts[1] if len(parts) >= 2 else ''
        field = parts[2] if len(parts) >= 3 else ''
        ok, msg, old = db.update_field(item_id, field, new_value, source, turn_id)
        ...
```

## 5.3 挂到 nerve

```python
# jarvis_central_nerve.py
self.local_db = LocalKnowledgeDB(...)
```

## 5.4 主脑直接能用 (不需新 directive)

```
Sir: "我那个 X 项目细节改成 Y"
主脑: <FAST_CALL>{"organ":"mutation","command":"update","params":{
  "field_path":"local_db.X.description",
  "new_value":"Y",
  "intent":"revise"
}}</FAST_CALL>
```

主脑学一次 correction_dispatcher → 通用所有 source.

---

# 6. 反例 — 不要这么做

## ❌ 反例 1: 不实现 update_field, 让主脑直接调底层 API

不要让主脑 `<FAST_CALL>{"organ":"local_db","command":"update_field",...}}</FAST_CALL>`. 应**统一**走 `mutation` organ. 否则:
- 主脑要记每个 source 的 organ syntax (Sir 21:55 抓的痛点)
- ClaimTracer 难以审计 (各 organ 自己 receipt 格式不一)
- 新加 source 要新 directive (不可扩展)

## ❌ 反例 2: 写 audit jsonl 但不真改源 (corrections.jsonl 死代码教训)

`profile_corrections.jsonl` 历史教训: 主脑说 "已更新" → 写 audit → 但主源 `sir_profile.json` **永远不变** → Sir 看的还是老 profile.

**正确**: 真覆写源 + audit jsonl + SWM publish (3 必备).

## ❌ 反例 3: 没 schema 白名单, 主脑乱改坏结构

`overwrite_field` 必须有 `_OVERWRITE_ALLOWED_FIELDS` 白名单. 否则主脑可能 emit `{"field":"hacked_field","new_value":"..."}` 破坏 source data 结构.

## ❌ 反例 4: SWM publish 用错 etype (订阅者收不到)

SWM event etype 应跟现有约定一致 (`<source>_field_updated` / `<source>_archived` 等). 订阅者 (ProactiveCare / SOUL / IntentResolver) 通过 etype 识别. 自创 etype 会让订阅者收不到, mutation 失语.

---

# 7. 验证清单

新 source 接入后, 跑下面 5 个 smoke test 全过才算上线:

| # | 测试 | 通过条件 |
|---|---|---|
| 1 | 主脑 emit `<FAST_CALL>{"organ":"mutation",...}}` 路由到新 source | gateway return ok=True |
| 2 | 真覆写源 (atomic) | 文件读出值 == new_value |
| 3 | mutation_receipts.jsonl 写入 | jsonl tail 含 mutation_id + ok=True |
| 4 | SWM event publish | recent_events 含 etype |
| 5 | schema 白名单保护 | non-whitelist field → ok=False, 不污染源 |

参考 `scripts/_audit_mutation_gateway.py` 模板.

---

**doc 长度** ~250 行. 给开发者 / 未来加 module 时参考.  
**核心**: 新加 source 不动主脑 directive, 不动 ChatBypass parser, 只实现 4 接口 + 注册 LAYER_REGISTRY 即可.
