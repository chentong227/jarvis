# JARVIS Intent Resolver Refactor — β.5.44

> **Sir 18:55 真理**: "我说一句话，贾维斯会做什么真的太乱了" + "应该和主动模块一样，把所有都变成 LLM 决策-模块提供数据-大部分都是 push only"

> **设计目标**: 把 7 个被动 input-processing module 从"各自 LLM judge + 自动 mutate state"重构为"publish raw signal + 集中 IntentResolver LLM 决定调 tool". 主脑看 `intent_resolved` 报告, **不再撒谎说"已 corrected"**.

> **β.5.0 三维耦合**在被动 module 落地: 数据强耦合 + 行为弱耦合 + 决策集中主脑.

---

## 1. 当前架构 (混乱) — Sir 18:55 实测

```
Sir: "记错了吧, 应该是第八杯"
                 │
                 ▼
┌──────────────┬──────────────┬─────────────┬────────────────────┐
│ Gatekeeper   │ ConcernFB    │ MemCorrect  │ ProfileCard        │
│ LLM judge:   │ LLM judge:   │ regex 抓:   │ 同步 correction    │
│ has_commit=  │ current=3    │ 九→八杯     │ user_correction=八 │
│ False        │ sev_d=+0.20  │ 没匹配 cell │ (非 hydration)     │
│              │ (LLM 弄反!)  │ 存为孤儿    │                    │
└──────────────┴──────────────┴─────────────┴────────────────────┘
       │            │              │              │
       ▼            ▼              ▼              ▼
   各自 mutate state, 互不知道, 4 处数据不一致
                       │
                       ▼
       主脑 reply: "I've corrected my count to eight"
       (主脑只看 STM 文本, 不知道 4 个 module 谁真改了, 撒谎)
                       │
                       ▼
       Integrity Check: no_tool_called → STM 加 [claim_unverified]
```

**根因**: 7 个 module 各自 LLM judge + 各自 mutate, 主脑看不到全局, 无法自审"我说改了吗实际改了?"

---

## 2. 重构后架构 (清晰)

```
Sir: "记错了吧, 应该是第八杯"
                 │
                 ▼
┌──────────────────────────────────────────────────────────┐
│ Phase 1: Module 退化为 publish-only signal               │
│                                                          │
│ Gatekeeper.publish_intent('commit_candidate', conf=0.1) │
│ ConcernFB.publish_intent('progress_candidate', ...)     │
│ MemCorrect.publish_intent('correction_candidate', ...)  │
│ ProfileCard.publish_intent('profile_update_candidate')  │
│ SelfPromise.publish_intent('jarvis_promise_candidate')  │
│ CommitWatch.publish_intent('deadline_candidate')        │
│                                                          │
│ ↑ 全部 publish 到 SWM, 零 mutation                       │
└──────────────────────────────────────────────────────────┘
                 │
                 ▼ (turn 结束, _assemble_prompt 前)
┌──────────────────────────────────────────────────────────┐
│ Phase 2: IntentResolver 集中 LLM judge → tool_calls      │
│                                                          │
│ resolver.resolve(turn_id):                              │
│   evidence = bus.top_n(types={'sir_intent.*'})          │
│   plan = LLM_unified(                                    │
│     "Sir 这轮说了 X, 7 个 module 各自 candidate 是 Y,    │
│      你该调哪些 tool 改什么 state? JSON 输出"           │
│   )                                                     │
│   for tc in plan['tool_calls']:                         │
│     result = TOOL_REGISTRY[tc.name](**tc.args)          │
│     bus.publish('tool_called', {                        │
│       'name', 'args', 'result', 'ok': bool              │
│     })                                                  │
│   bus.publish('intent_resolved', {                      │
│     'turn_id', 'tool_calls', 'results'                  │
│   })                                                    │
└──────────────────────────────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────────────────────┐
│ Phase 3: 主脑 prompt 看 'intent_resolved' 报告           │
│                                                          │
│ [INTENT RESOLVED THIS TURN]                              │
│ - tool_called: hydration_count_update(current=8)        │
│   result: ok (Concern.daily_progress.current = 8)       │
│ - tool_called: memory_correction_apply(...)              │
│   result: failed (no matching cell, kept in conv)       │
│                                                          │
│ ↑ 主脑能精确说: "Sir, count is now 8 in my tally.       │
│   (knows hydration tool fired ok)                       │
│   I tried to update your earlier 5-cup memory but       │
│   couldn't find it; this turn's correction stays only   │
│   in the conversation."                                 │
│   (knows memory_correction failed)                      │
└──────────────────────────────────────────────────────────┘
```

**好处**:
- 1 个 LLM 判断, 不是 7 个 (避免 LLM 各自弄错不同部分)
- 主脑看 tool_called result, 不再撒谎
- Sir 看 dashboard intent_resolved log, 知道 Jarvis 真做了啥
- 数据统一: 1 个 tool 调 1 处 state, 无孤岛

---

## 3. 实施 sub-step 拆分

### Sub-step β.5.44-A: 加 SWM etype `sir_intent.*` + `tool_called` + `intent_resolved` (~30min)

**改 `jarvis_utils.py`**:
```python
DEFAULT_TTL = {
    ...
    'sir_intent_commit_candidate': 60,        # turn 内
    'sir_intent_progress_candidate': 60,
    'sir_intent_correction_candidate': 60,
    'sir_intent_profile_update_candidate': 60,
    'sir_intent_promise_candidate': 60,
    'sir_intent_deadline_candidate': 60,
    'sir_intent_watch_request': 86400,        # 已存在 (sir_watch_request_proposed)
    'tool_called': 300,                        # 5min
    'intent_resolved': 600,                    # 10min (主脑看)
}
DEFAULT_SALIENCE = {
    ...
    'sir_intent_*': 0.55,                     # candidate 中等
    'tool_called': 0.85,                       # 高 (主脑必看)
    'intent_resolved': 0.90,                   # 极高 (turn-level mutation 报告)
}
```

### Sub-step β.5.44-B: Module 1 by 1 加 `publish_intent()` 替代直接 mutate (~2.5h)

**优先级** (按 Sir 18:55 痛点排):
1. **MemoryCorrection** (~30min) — 抓 "记错了" 后改成 publish, 不直接改 memory cell
2. **ConcernFeedback** (~30min) — record 改成 publish, 不直接写 daily_progress
3. **Gatekeeper** (~30min) — has_commit 改成 publish
4. **CommitmentWatcher** (~30min) — 抓承诺后 publish, 不直接注册 deadline
5. **SelfPromiseDetector** (~30min) — detect 后 publish
6. **ProfileCard** (~30min) — sync 改 publish

每个 module 改动模式:
```python
# 旧:
def process(sir_utterance):
    judgement = self._llm_judge(sir_utterance)  # LLM judge
    if judgement['has_X']:
        self._mutate_state(judgement)  # 立刻 mutate
        bg_log(f"[Module] mutated X")

# 新:
def publish_intent(sir_utterance, turn_id):
    judgement = self._llm_judge(sir_utterance)  # LLM judge (仅 candidate)
    if judgement.get('confidence', 0) > 0.3:    # threshold
        bus.publish('sir_intent_X_candidate', {
            'turn_id': turn_id,
            'confidence': judgement['confidence'],
            'judgement': judgement,
            'source_module': 'ModuleName',
        })
        # 不 mutate state
```

### Sub-step β.5.44-C: 新 `jarvis_intent_resolver.py` (~1h)

```python
class IntentResolver:
    def __init__(self, key_router, central_nerve, tool_registry):
        self.key_router = key_router
        self.nerve = central_nerve
        self.tools = tool_registry
        
    def resolve_turn(self, turn_id, sir_utterance):
        """turn 末尾调, 看 SWM intent candidates, LLM 决定调哪些 tool."""
        bus = self.nerve.event_bus
        candidates = bus.top_n(
            types={'sir_intent_commit_candidate',
                   'sir_intent_progress_candidate',
                   'sir_intent_correction_candidate',
                   ...},
            within_seconds=30,
        )
        if not candidates:
            return
        
        prompt = self._build_resolver_prompt(sir_utterance, candidates)
        plan = self._llm_judge(prompt)  # JSON tool_calls
        
        executed = []
        for tc in plan.get('tool_calls', []):
            try:
                result = self.tools[tc['name']](**tc.get('args', {}))
                ok = True
            except Exception as e:
                result = str(e)
                ok = False
            bus.publish('tool_called', {
                'turn_id': turn_id,
                'name': tc['name'],
                'args': tc.get('args', {}),
                'result': str(result)[:300],
                'ok': ok,
            })
            executed.append({'name': tc['name'], 'ok': ok})
        
        bus.publish('intent_resolved', {
            'turn_id': turn_id,
            'tool_calls': executed,
        })
```

### Sub-step β.5.44-D: TOOL_REGISTRY 注册所有 mutation tool (~30min)

```python
# jarvis_tool_registry.py
TOOL_REGISTRY = {
    'hydration_count_update': hydration_update_fn,
    'memory_correction_apply': memcorrect_apply_fn,
    'commitment_register': commitwatch_register_fn,
    'concern_progress_record': concern_progress_fn,
    'profile_field_update': profile_update_fn,
    'self_promise_register': selfpromise_register_fn,
}
```

每个 tool fn 接 args 真 mutate state, 返 result dict.

### Sub-step β.5.44-E: `_assemble_prompt` 注入 `[INTENT RESOLVED]` block (~30min)

```python
# jarvis_central_nerve.py _assemble_prompt
intent_resolved = bus.recent_events(types={'intent_resolved'}, within_seconds=120)
if intent_resolved:
    ir = intent_resolved[-1]
    tool_lines = []
    for tc in ir.get('metadata', {}).get('tool_calls', []):
        status = '✓' if tc['ok'] else '✗'
        tool_lines.append(f"  {status} {tc['name']}")
    prompt += '\n[INTENT RESOLVED THIS TURN]\n' + '\n'.join(tool_lines)
```

### Sub-step β.5.44-F: Dashboard `intent_resolved` log (~30min)

Dashboard 加 panel "💬 这轮系统做了什么", 显示 `intent_resolved` events 时序, Sir 一眼看到 Jarvis 真做了啥.

---

## 4. 风险 + 反例

### 风险 1: 双 LLM 串行 → TTFT 变慢

- 现在: 7 个 module LLM 并行 (但浪费 token)
- 重构后: 主脑 LLM + IntentResolver LLM 串行

**缓解**: IntentResolver 用 `gemini-2.5-flash-lite` (~200ms), 串行后 TTFT 多 ~300ms, 不破 5s 红线. 且 IntentResolver 是 turn 末尾跑, 不卡 TTFT (主脑 reply 已发出).

### 风险 2: IntentResolver LLM 弄错 / 漏调 tool

- 缓解: candidate 含 confidence, 低于 0.5 IntentResolver 不调; 调失败 publish `tool_called.ok=false`, 主脑看到 fall back acknowledge-only.

### 风险 3: 6 个 module 重构动很多 file

- 缓解: 1 个 sub-step 1 个 module, 独立 commit, 单点回滚. 每改一个跑 regression.

---

## 5. 测试策略

每个 sub-step 独立 testcase:
- A: SWM etype 注册验证
- B: 每个 module 改 publish_intent 后, 验 publish 命中 + 不 mutate
- C: IntentResolver 集成 test — mock candidates, 验 plan + tool calls
- D: TOOL_REGISTRY callable 验证
- E: prompt block 注入验证
- F: dashboard endpoint 测试

---

## 6. 完成定义 (DoD)

Sir 18:55 实测 scenario 重放:

1. Sir: "记错了吧, 应该是第八杯"
2. MemoryCorrection / ConcernFB / Gatekeeper 仅 publish candidate, 不 mutate
3. IntentResolver LLM 看全部 candidate + Sir 原话, 决定调 `hydration_count_update(current=8)`
4. tool 真 mutate Concern.daily_progress.current = 8
5. publish `tool_called.ok=true`
6. 主脑看 `intent_resolved` block, reply: **"Noted, Sir — your count is now 8 in my tally."** (基于真实 tool result, 不是撒谎)
7. Integrity Check 通过 (no_tool_called 不触发, 因为 IntentResolver 调了)

---

## 附录: Sir 准则 6 vocab 检查

✅ TOOL_REGISTRY 是系统级常量 (准则 6 递归边界), .py 写死 OK
✅ Candidate threshold (0.3) 持久化到 `memory_pool/intent_resolver_config.json`, CLI 可调
✅ IntentResolver prompt 文本持久化 (`memory_pool/intent_resolver_prompt.json`)
✅ tool_called / intent_resolved etype 注册 `jarvis_utils.py` (准则 6 边界)
