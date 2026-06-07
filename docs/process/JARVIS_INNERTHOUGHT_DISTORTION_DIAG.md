# InnerThought 失真勘察 — 现状图 (只读 / 零代码 / 零真机)

> **[innerthought-distortion-diag / 2026-06-07]**
> 依据: 真机 turn `turn_20260607_19xxxx` 一带, 一条 InnerThought 同时出两类失真 +
> kind=empty 思考日志 `…` 截断现象。
> 本文**只摸现状**, 给四点 file:line + 证据, **不提方案、不写代码、不碰真机/flag/墙/宪法散文**。
> 摸清 → 顾问判 → 出修法 → Sir 拍 → 才施工。

---

## 0. 真机现象 (待修锚)

| 失真 | 真机表现 | 性质 |
|---|---|---|
| ① 屏幕态张冠李戴 | "Sir 在看视频" 被说成 `reviewing his schedule on his terminal` (cite=`his terminal`) | 疑引用旧帧 (📷 ScreenVision/wake app='VS Code') |
| ② 因果链渲塌 | Sir 下午 "母亲手术住院→早上没去→下午去医院看母亲" 渲成空泛且方向反的 "his mother's visit / 到访" | 体里只有光秃 promise, 因果背景没喂进 prompt |
| ③ empty 思考截断 | kind=empty 思考日志被 `…` 截断 | 日志格式截断 (非 thought 本身被截) |

---

## 点 1 — 体里到底存了啥 (体薄 / 体不薄判定)

### 1.1 promise 本体 = **光秃** (无因果背景)

`memory_pool/jarvis_promise_log.json:5705-5853` `p_434796c0`:

| 字段 | 值 |
|---|---|
| `description` | `下午去医院看望母亲` (光秃一句, 无 手术/住院/早上没去) |
| `kind` | `commitment` |
| `deadline_str` | `2026-06-07 15:00:00` |
| `author` / `who_promised` | `sir` / `sir` |
| `jarvis_reply` / `turn_id` / `lang` | **全空** (`""`) |
| `state` | `fulfilled` (`fulfilled_at` 19:06:51, evidence `sir_voice`="Sir 说做完了") |
| `evidence[]` | 21 条, **20 条是 `cw_nudge_fired`** ("CW daemon fired nudge: 下午去医院看望母亲 @ deadline_ts=...") + 1 条 `sir_voice` |

⟹ promise 本体里**没有任何** "手术 / 住院 / 早上没去医院 / 母亲病情" 的因果背景。只有 deadline + 一句行为描述 + nudge 点火痕迹。

### 1.2 因果背景**真实存在**, 但在**别处** (inner_voice / promise 的 jarvis_reply 历史)

因果链散落在 `memory_pool/inner_voice_24h.jsonl` 的 `sir_excerpt` 与早轮 promise 的 `jarvis_reply`:

| 实物 file:line | 内容 |
|---|---|
| `inner_voice_24h.jsonl:3099` (sir_excerpt) | `[WORK_MODE] ...今天要早点休息，明天妈妈要做手术` (turn `bf8b`, 6/4 22:42) |
| `inner_voice_24h.jsonl:3299` (sir_excerpt) | `[WORK_MODE] 嗯，今天妈妈手术还算是比较成功的啊，很顺利` (turn `6210`, 6/5 21:20) |
| `inner_voice_24h.jsonl:3678` (sir_excerpt) | `[WORK_MODE] ...我关于我母亲做手术的事情，没有被记录下来吗?` (turn `6cc0`, 6/7 10:19) |
| `jarvis_promise_log.json:5675` (p, jarvis_reply) | `...a hospital visit while unwell would benefit neither of you. I shall monitor for any incoming messages from your father...` (turn `a6ba`, 6/7 10:22 — "早上没去"语境) |

⟹ **判定: 体不薄, 但分裂**。手术/住院/早上没去的因果**确有留痕**, 散在 inner_voice 时间线 + 早轮 promise reply 里; 但被 InnerThought 当作"那条 promise"渲染时, **它读到的那条结构化体 (`p_434796c0`) 是光秃的** — 因果背景与 promise 本体不在同一结构里, 没有任何字段把它们关联。

---

## 点 2 — InnerThought prompt 喂哪些源 ("识带不带体"判定)

### 2.1 prompt 构造处

- `_build_prompt(sir_state, evidence, free_categories, channel_view)` 于 `jarvis_inner_thought_daemon.py:4356`
- evidence dict 组装于 `_collect_evidence` 区, init 于 `:3325` (`'swm_events'/'stm'/'concerns'/'recent_thoughts'`)
- channel_view 源映射于 `:4014-4047` (`channel_sources` dict)

### 2.2 喂进去的源 (全清单, file:line)

| 源 key | file:line | 内容 |
|---|---|---|
| `recent_thoughts` | `:3333-3372` | 上 N 条自产 thought (lookback vocab, 默 15 条/30min, thought[:200]) |
| `topic_distribution` | `:3380+` | thread_id count + 语义簇 (反刍检测) |
| `meta_feedback_loop` | `:3490+` | 近 60min main_brain reply + sir_reaction |
| `swm_events` | `:3560+` | SWM top event (type+desc[:120], 8 条) |
| `recent_jarvis_actions` | `:3640+` | filter ACTION etype (NUDGE/published/...) |
| `runtime_log_tail` | `:3690` | `_collect_runtime_log_tail(max_lines=12)` |
| `anticipated_ltm_context` | `:3700+` | Anticipator preload LTM (`[:1500]`) |
| `daemon_health` | `:3720+` | SWM daemon_health_warning |
| `time_pattern` / `time_deviation_today` | `:3760+` | TimeAwareness hour pattern |
| **`stm`** | **`:3602-3610`** | `nerve.short_term_memory` **last 5 turn**, `user[:250]` / `jarvis[:400]` / when |
| `sir_declared_status` | `:3850+` | Sir 声明 status (sleep/lunch/...) |
| `sir_profile_mini` | `:3870+` | `ProfileCard.to_prompt_block(400)` |
| `active_directives` | `:3890+` | top N directive |
| `concerns` / `all_active_concern_ids` | `:3960+` | active concern + severity + daily_progress |
| `active_protocols` / inside_jokes | `:4000+` | relational_state |

### 2.3 关键缺口 — **不读 promise store, 不读 manifold 结构化关系**

grep `jarvis_inner_thought_daemon.py` 全文 `promise` / `manifold` 命中:
- `promise` 仅出现在 `_check_red_line_let_go`(`:1226-1253`, 红线 let_go 校验, **非 prompt 喂源**) 与 fingerprint 前缀表(`:1640` `'promise_'` 是 SWM etype 过滤, 非 promise store 读)
- `manifold` 在 prompt builder / evidence 收集区 **零命中** (只在 fingerprint 的 `b:{node}` body-delta 指纹, `:2336`, 那是势能扰动 magnitude, 非结构化关系读)

⟹ **判定: 识不带体 (结构化体)**。InnerThought 的 evidence **只读 STM 摘要 (5 turn, user[:250]/jarvis[:400]) + 屏幕/SWM 快照 + 自产 thought + concern/profile/directive**。它**从不读** `jarvis_promise_log.json` 结构化 promise, 也**从不读** manifold 结构化关系边。

⟹ 对失真②的解释: InnerThought 渲染"母亲"那段时, 唯一可依据的是 STM 里 Sir 最近 5 turn 的对话片段 (user[:250] 截断) + 自产旧 thought。它既看不到 `p_434796c0` 光秃 promise, 更看不到散在 inner_voice 的手术/住院因果链 → 只能凭 STM 截断片段**猜**, 渲成空泛反向的 "his mother's visit"。

---

## 点 3 — ScreenVision 帧时效 (为何 "terminal" 是旧的)

### 3.1 ScreenVision 抓帧触发 + 刷新频率

`jarvis_screen_vision.py`:

| 项 | file:line | 值 |
|---|---|---|
| 触发条件 | `:19` (docstring) | `wake_word / sir_explicit_screen_ref / app_switch / 5min backfill / Sir CLI` |
| backfill 间隔 | `:74` `DEFAULT_BACKFILL_INTERVAL_S` | **300.0s (5min)** idle 自动 |
| cache TTL | `:75` `DEFAULT_CACHE_TTL_S` | **60.0s** 同 turn 内复用旧帧 |
| 持久 latest 1 帧 | `:69` `DEFAULT_SNAPSHOT_PATH` | `memory_pool/screen_snapshot.json` (atomic 覆盖, `_persist_latest:698`) |
| rolling N 帧 | `:70` `DEFAULT_HISTORY_PATH` | `memory_pool/screen_history.jsonl` (keep 100) |
| `is_fresh` | `:136` | `age_s <= ttl_s` (默 60s) |
| 提频机制 | `:228-280` | InnerThought publish `proactive_vision_refresh_advice` SWM → daemon 临时 backfill 5min→30s (仅 active WatchTask 时) |

### 3.2 InnerThought 取屏幕态用的是**缓存帧**

- InnerThought evidence **不直接调** ScreenVision 截图。它只能从 SWM event (`swm_events`, `:3560+`) 看到 ScreenVision daemon **异步** publish 的描述 (latest snapshot)。
- snapshot 是 **5min backfill / 60s TTL 的缓存** (`screen_snapshot.json` 单帧覆盖)。无 active WatchTask 提频时, idle backfill = 5min。
- ⟹ **节奏对不上**: InnerThought tick (秒~分级) 与 ScreenVision backfill (idle 5min) 异步。Sir 切到"看视频"后, 若上一帧是 5min 前 wake 时抓的 app='VS Code'/terminal, InnerThought tick 时 SWM 里仍是那条旧帧描述 → cite="his terminal" 是 **5min 窗口内的 stale frame**, 不是当前"看视频"实时态。

⟹ 对失真①的解释: cite="his terminal" = 引用了 backfill 间隔内未刷新的旧 snapshot。

---

## 点 4 — empty 思考 `…` 截断 (日志格式截断 vs thought 被截)

### 4.1 `…` 来自**日志渲染格式**, 非 thought 本身被截

thought 日志渲染于 `_emit`/log 区:

| 路径 | file:line | 截断 |
|---|---|---|
| mediocre skip 路径 | `:2958-2960` | `f"...] {thought.thought[:60]}…{meta_str}{kind_str}"` — **硬 `[:60]` + 字面 `…`** |
| 正常路径 | `:2964-2971` | `_tt = _truncate_at_word_boundary(thought.thought, 300)` — word-boundary 截 300 char + `…` suffix |
| truncate helper | `:1443-1471` | `_truncate_at_word_boundary` — `len<=max → 原样返`; 否则 cut + `…` |

### 4.2 thought 本体**完整持久化** (不被截)

- 持久路径 `PERSIST_PATH = 'memory_pool/inner_thoughts.jsonl'` (`:1486`), `_persist_thought` (`:7964`) append-only, **写整条 thought**。
- SOUL inject (`:37-38`) top 3 by salience, ~500 char cap (那是注入主脑 prompt 的 cap, 不影响持久体)。

⟹ **判定: `…` 是日志格式截断**。kind=empty 的思考多半走 mediocre skip 路径 (`:2958`, `thought[:60]` 硬切 + 字面 `…`), Sir 在 runtime log 看到的 `…` 是 log 行的 60 字硬截显示, **thought 本体在 jsonl 里是完整的**。

---

## 现状图小结 (四点)

| 点 | 判定 | 核心 file:line |
|---|---|---|
| 1 体里存了啥 | promise 本体光秃 (无因果); 因果背景**确存但分裂**在 inner_voice / 早轮 reply | `jarvis_promise_log.json:5705`; `inner_voice_24h.jsonl:3099/3299/3678` |
| 2 识带不带体 | **不带**。prompt 只喂 STM 摘要(5turn user[:250]) + 屏幕/SWM/自产thought/concern, **不读 promise store / manifold 结构化关系** | `:4356`(builder); `:3602`(STM); promise/manifold 喂源零命中 |
| 3 屏幕帧时效 | 缓存帧 (5min backfill / 60s TTL 单帧覆盖), InnerThought 取 SWM 异步旧帧 → cite stale | `screen_vision.py:74/75/69` |
| 4 empty 截断 | **日志格式截断** (`thought[:60]…` 硬切), thought 本体 jsonl 完整 | `:2958-2960`; `:1443` |

→ 一句话: 识只看 STM 截断片段, 不读 promise/manifold 结构体, 屏幕帧还是旧的, `…` 只是日志切的。
