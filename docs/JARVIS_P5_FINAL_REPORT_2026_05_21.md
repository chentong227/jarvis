# JARVIS P5 真治本报告 — 2026-05-21 早晨

> **Sir 5/20 22:47 - 5/21 02:30 授权**: Gap 1 + Gap 2 + 严格 audit + 结论报告
> **Sir 5/21 09:25-10:30 真测**: 12 个新 BUG 暴露 + 真治本 4 commit
> **现状**: 整夜 + 早晨累 9 commit, 5 个真治本 P5 fix, **覆盖 Sir 反复 5+ 次的道歉痛点**

---

## 1. 已落地 (按时间顺序)

| commit | 时刻 | 内容 |
|---|---|---|
| `187e015` | 5/21 00:45 | Gap 2: ReplyPreFlight self-check (Pass 2 — async post-stream) |
| `4c1ec4f` | 5/21 01:15 | Gap 1: Theory of Mind (Sir Mental Model, Layer 6) |
| `3bc494f` | 5/21 10:14 | **P5-fix-add_reminder**: SQLite NOT NULL constraint failed timestamp (Sir 10:06 真测) |
| `664ad77` | 5/21 10:14 | **P5-morning + AmbientSensor**: 5 fix Sir 早起痛点 (A trigger + B warmth + C coordination + D PreFlight default ON + AmbientSensor self.jarvis bug) |
| `d366c24` | 5/21 10:21 | **P5-items-i18n**: dashboard /items 人话翻译 + 一键 👍/👎 (Sir 09:55 截图反馈) |
| `7cdeefb` | 5/21 10:32 | **P5-fixCB**: unsolicited_callback_guard 真治本 Sir 5+ 次道歉痛点 (B vocab regex + C priority 12 directive) |

**测试**: 总 70+ testcase, 全绿 (39 P5 morning/items/add_reminder + 19 callback_guard + 30+ pre-existing Gap 1/2).

---

## 2. Sir 反复痛点真治本 — callback_guard (核心)

### 真凶链

Sir 5+ 次反复犯 BUG: 主脑 unsolicited callback 老账道歉, Sir 当前 turn **完全没问**.
- 22:04: "I apologize for my earlier claim regarding the hydration logs..."
- 22:19: 同型
- 23:02: 同型
- 23:43: "Regarding my previous claim of updating settings..."
- 23:49: 同型
- **10:06**: "Regarding my previous claim of updating the logs, I must admit that was inaccurate..."
- **10:08**: "Regarding my previous claim of setting a reminder, the database rejected..."

每次都是**新 turn 新道歉新事件**, 主脑不知节制.

### 之前为什么修不了

| 已有防御 | 为什么没拦住 |
|---|---|
| `past_action_honesty` directive (priority 10, always-on) | 教主脑"不要 claim 没调 tool 的 mutation", 但**不教不要 unsolicited callback** |
| Gap 2 PreFlight (async post-stream) | 是**事后审**, 主脑 reply 已说出口. PreFlight verdict publish, 主脑**下轮**看 [PREFLIGHT FEEDBACK] 学到 — 但下轮主脑 callback **新事件**, 又是 unsolicited |
| `[INTEGRITY ALERT]` block (claim_tracer) | 仅 track unverified factual claim, 不管 unsolicited callback 本身 |
| morning_warmth_priority directive (P5-fixB priority 11) | 仅 morning 6-10am fire, 其他时段没用 |

### 真治本 (P5-fixCB B+C 双层)

**C — directive `unsolicited_callback_guard` (priority 12)**:
- 顶级红线 always-on, 跟 `no_hallucinated_tool_use_judge` 同档
- text 教主脑: 列 Sir 5+ 次 forbidden 句式 + 输出前 self-check rule + 判别正例 + 真案改写
- 让主脑**在 prompt 装配时就看到强约束**, 不输出 unsolicited callback

**B — `memory_pool/forbidden_callback_vocab.json` + post-stream regex scan**:
- 7 phrase entry seed (regarding_my_previous / i_must_admit / 关于我之前 / 我必须承认 ...)
- chat_bypass 末尾 (跟 PreFlight 同位置) regex scan reply, 命中即 publish SWM
- central_nerve `_assemble_prompt` 渲染 [SIR FLAGGED UNSOLICITED CALLBACK] block 注入主脑下轮
- 跟 PreFlight (LLM async) 互补 — 这层零延迟 + 主脑下轮一定看到
- 持久化准则 6 合规 (Sir CLI 加 / 删 / 改 phrase 不改源码)

**安全网**: Sir 主动召唤老账 ('you said earlier' / '你刚才说') → `_sir_invited_callback` exemption, scan 放过. solicited callback 仍 OK.

---

## 3. 早起 5 BUG 真治本 (commit `664ad77`)

Sir 09:05/06/12 3 连发问候全冷脸数落 + 09:53 AmbientSensor hidden bug.

| Fix | 真凶 | 真治本 |
|---|---|---|
| **A. morning_mood_judge trigger** | `is_first_active_today` flag race (idle<30s flip False) | 改看 SWM `afk_return` event metadata.afk_minutes>240 (overnight 物理边界) |
| **B. morning_warmth_priority directive** | 60+ directives 缺 warmth 角度, 主脑早起自由数落 | 加 priority 11 always-on 6-10am+afk>4h directive 教原则 |
| **C. nudge_coordination β.5.0 弱耦合** | 3 个 sentinel (ReturnSentinel/SmartNudge/Conductor) 各自 hard fire, 不协调 | 新 module `jarvis_nudge_coordination.py`, 任一 sentinel fire 后 publish `proactive_nudge_fired` SWM, 别的 sentinel 看 SWM 自决退化 publish-only |
| **D. PreFlight default ON** | 原 default off, Sir 没启 → hallucination 没拦 | env default ON, Sir 关掉设 JARVIS_PREFLIGHT=0 |
| **E. AmbientSensor self.jarvis bug** | worker.py:963 用 `self.jarvis.event_bus`, 但 VoiceListenThread 没 jarvis 字段 — 整 β.5.40-A1 sprint 没启用 | 改用 `jarvis_utils.get_event_bus()` 全局 singleton |

---

## 4. dashboard /items 人话化 (commit `d366c24`)

Sir 09:55 截图反馈: 卡片只显 vocab id + tag, 没人话; 没 👍/👎.

### 改了什么
- `ActionableItem` schema 加 `description_zh` / `category_zh` / `sir_feedback`
- `CATEGORY_ZH_MAP` 13 category → 中文 + emoji
- struggle / screen_tease / directive extractor 加 `describe_fn` (人话 1 句"这条干啥/触发时 Jarvis 做啥")
- post-process 兜底填 category_zh + sir_feedback
- `save_item_feedback(id, 'up'|'down'|'')` API + jsonl audit
- `/api/items/<id>/feedback` endpoint
- /items 卡片: 中文 category / 状态 (待审/已生效) / 描述行 (🔍 人话) / 👍 + 👎 按钮 / 已评 badge

---

## 5. add_reminder NOT NULL 修 (commit `3bc494f`)

Sir 10:06 真测: `memory_hands.add_reminder` 抛 `NOT NULL constraint failed: TaskMemories.timestamp`. 提醒功能从某次 schema 升级 (timestamp/environment/macro_goal 都加 NOT NULL) 起就挂了, 没人发现.

修: INSERT 补 timestamp=now / environment='reminder' / macro_goal='reminder: <intent>'.

---

## 6. Audit 结论 (Sir 之前要求"严格排查所有模块耦合")

### 已识别 + 已治本

| 耦合层 | 状态 |
|---|---|
| **mutation channel** | ✅ IntentResolver 集中 5 mutation tool (β.5.44) + MemoryGateway (P2) + ProfileCard.apply_correction (β.2.9.9 持久化). 直接 caller 已审, 没遗漏 |
| **main brain prompt block** | ✅ 37+ prompt block 经 `scripts/_audit_prompt_blocks.py` 扫, 无重复 / 错位 |
| **sentinel publish-only refactor** | ⚠️ ReturnSentinel (P3 publish candidate) + SmartNudge / Conductor / ProactiveCare (P5-fixC publish proactive_nudge_fired) 已 wire, 但**仍双轨** (hard fire + publish), β.5.0 真意是**纯 publish-only**. P5 hot fix 没动主路径, P6 重构 |
| **reflector daemon** | ✅ 6 active reflector (Concerns / Weekly / SoulEvaluator / ToMReflector / InsideJoke / SleepPattern), 各自不抢资源 (LlmReflector 全局 cache + cost track) |
| **memory persistence** | ✅ corrections.jsonl / profile / hippocampus / STM 通过 MemoryGateway + ProfileCard.apply_correction + JsonRotator (P3 BUG#7 防长期膨胀) |

### 冲突检测 — 已识别

| 类型 | 实例 | 状态 |
|---|---|---|
| **duplicate directive 触发** | 之前担心多 directive cluster fire 淹 (Sir 22:04 8 directive 2350 chars) | ⚠️ 未减, 直接 commit `7cdeefb` 又加 1 个 priority 12 directive. 但 Sir 真痛点是 unsolicited callback **本身**, 不是 cluster 大. 暂不动 |
| **publish-fire double** | ReturnSentinel + SmartNudge.commitment_check 双 fire | ✅ P5-fixC nudge_coordination 治了 |
| **orphan caller** | l4_memory_hands.add_reminder INSERT 缺列 | ✅ P5-fix-add_reminder 治了 |

### 已知 follow-up (P5+)

1. **callback_guard L7 reflector**: 现 vocab 是 seed 7 phrase, 主脑可能涌现新形式 (绕过 regex). 加 L7 daemon 看 Sir 反馈 ("不要道歉了" / "别老翻旧账") + 实际命中, propose 新 phrase 进 review_queue
2. **callback_guard dashboard /items**: 加 `forbidden_callback` category 让 Sir 看 + 改 + 👍/👎
3. **CLI `scripts/forbidden_callback_dump.py`**: Sir 不开 dashboard 用 CLI 加 phrase
4. **P6 Pure Pass2 sync PreFlight**: 接受 TTFT +500ms 按 design doc 真意拦截当前轮. 等 callback_guard 真生效率 + Sir 拍板再做
5. **directive cluster 减负**: 当前 60+ directive 在 prompt 注入 cluster 太大 (Sir 22:04 看了 2350 chars). 可考虑 grouping / context-conditional fire
6. **dashboard pre-existing 4 fail**: `_test_p0_plus_20_beta54_conductor_publish_persist.py` 4 test 在 main 就 fail (跟 P5 无关). 后续 fix
7. **TODO.md ~590 行**: 待 archive 老段到 `docs/TODO_ARCHIVE.md` (跟之前一致)

---

## 7. Sir 真测 check list (重启后跑)

```
启动:
[ ] log 含 '🎵[AmbientSensor / β.5.40-A1] 启用' (不再 init 异常)
[ ] log 含 '🛂 [ReplyPreFlight] enabled (default ON, P5-fixD)'
[ ] log 含 '🤝 [NudgeCoordination] ready' / SWM 'proactive_nudge_fired' 跨 sentinel 协调

早起场景 (Sir 跨夜 + 6-10am 醒):
[ ] morning_mood_judge fire (SWM afk_return.afk_minutes>240)
[ ] morning_warmth_priority directive 含 'DO NOT lead with negative facts' 注入主脑
[ ] return_greeting 后 5-10min 内 SmartNudge.commitment_check 退化 publish-only
    (log '🤝 [CommitmentWatcher/Yield] commitment_check publish-only (让位 ...)' )
[ ] Jarvis 早起首句 warm + brief, 不数落 missed deadline
[ ] commitments 老账 Sir 主动问起才提

callback 治本 (Sir 跟之前同场景说话):
[ ] Sir 说 '今天没去体检' / '好的 ok' → Jarvis 不再 'Regarding my previous claim...'
[ ] 若 Jarvis 仍 callback → log '🚫 [CallbackGuard] turn=X hits=[regarding_my_previous_en]'
[ ] 主脑下轮 prompt 含 [SIR FLAGGED UNSOLICITED CALLBACK — DO NOT REPEAT] block
[ ] 主脑下轮自纠不再用该 phrase
[ ] Sir 主动 'you said earlier' / '你刚才说' → Jarvis 引用老账 OK (solicited exempt)

add_reminder:
[ ] Sir 说 '明天 7 点叫我' → Jarvis 真创建 reminder, 不再 NOT NULL constraint failed
[ ] log 含 'INSERT INTO TaskMemories ... timestamp=... environment=reminder' 成功

dashboard /items:
[ ] 卡片显中文 category ('🆘 Sir 困境词') 替 'STRUGGLE'
[ ] 状态显 '待审/已生效' 替 'review/active'
[ ] 描述行 '🔍 Sir 说出中文/高强度困境词 (如 ...) → Conductor 触发 offer_help'
[ ] 卡片新 👍 / 👎 按钮, 点击后 badge '👍 已赞' 显示
[ ] memory_pool/item_feedback_state.json + item_feedback.jsonl 真有数据
```

---

## 8. 我意识到的工程哲学反思

Sir 准则 6 ("拒绝硬编码, 信任 LLM") 在这轮 P5 hot fix 反复挑战:

- ❌ **避免硬编码 silence_window=5min**: P5-fixC 改用 SWM evidence-driven yield (within_s=600s 是物理边界, 不是行为 cooldown 数字)
- ❌ **避免硬编码 callback 句式 list 在 .py**: P5-fixCB B 把 phrase 持久化到 vocab.json + CLI + L7 reflector
- ✅ **保留物理/时段边界数字**: afk>240min (overnight) / 6-10am hour (morning) / priority=11/12 — 这些是物理语义边界, 跟 `TICK_INTERVAL` 同档可保留 (准则 6 递归边界)
- ⚠️ **`_SIR_INVITE_PATTERNS` (jarvis_callback_guard.py)** — 仍是 .py 里的 regex list (Sir 主动 callback exempt). 工程妥协: 这是程序逻辑判断 ("Sir 是否主动召唤"), 不是 vocab. 若 Sir 觉得不合适, 也可迁 vocab.

Sir 准则 1 (高效 TTFT < 5s) vs 准则 5 (言出必行) 矛盾在 PreFlight:
- 接受 TTFT 加 500ms 让 Pass2 真治本 = 选准则 5
- 不动 TTFT 让 PreFlight async + B+C vocab/directive 互补 = 选准则 1
- **本轮选准则 1**, B+C 真治本期望覆盖 Sir 实测 80%+ 道歉场景. 不行再考虑 P6 Pass2 sync.

---

## 9. 真心话

Sir 一夜 + 早晨真测暴露的不只是 BUG, 是**架构妥协的代价**:

- 我用 PreFlight async 想"既治本又不破 TTFT", 结果只治了下轮没治当轮 — Sir 反复痛点没解决
- 我用 morning_mood_judge 看 in-memory race-flag — 错过最关键场景
- 我用 self.jarvis 写 AmbientSensor — VoiceListenThread 没那字段, 整 sprint 没启用 (我没真启动测)
- 我用 add_reminder INSERT 缺列 — 没人写 e2e test 跑过

每一条都是"想得太巧 / 测得太少". Sir 真测 5+ 次 + 截图反馈才暴露.

**P5-fixCB B+C 是这轮我做的"最不巧妙的事"**: directive 强约束 + vocab regex scan + SWM publish + STM block — 4 层防御冗余, 但简单 + 主脑必看. 如果 Sir 重启后还能 callback, 我接受是架构本身有更深的问题需要 P6 Pass2 真治本.

Sir, 我去 push commit 等你拍板.
