# JARVIS Screen Watch — Vague Clarify + Active Backfill + Mirror Test 设计

> **状态**: ✅ Sir 2026-05-28 23:36 拍板"全做 5 改动 + 6 场景 mirror 跑通". 主体已实施 (39 testcase pass).
> **关联**: `@d:\Jarvis\jarvis_watch_task.py` (β.5.46-fix13 Fix-3 WatchTask 基础) + `@d:\Jarvis\jarvis_screen_vision.py` (P5-Gap3 ScreenVisionEngine) + `@d:\Jarvis\jarvis_mirror_mode.py` (fix49 mirror)
> **真测**: `tests/_test_fix50_sir_20260528_screen_watch_clarify.py` (39 pass) + `scripts/jarvis_mirror_run_screen_scenarios.py` (6 场景)
> **设计准则**: §6 三维耦合 + §5 言出必行 + §8 优雅高效可持续

---

## 0. TL;DR — 一句话

> **Sir 说"盯一下" → Registrar LLM 判 vague → 主脑下轮自然问 Sir 具体盯啥; Sir 答清楚 → 真注册 WatchTask + 思考脑提频 vision; ScreenVision daemon 看屏 + judge LLM 判 trigger 命中 → fire → 主脑通知. Mirror mode 加 fake screen snapshot 注入接口让 Cascade 完整测 6 类视觉场景 (Sir 直播+API 限速 P0 / 文字+图标+图形+图像 P1) 不烧真 vision LLM token.**

---

## 1. Sir 真痛 (Sir 2026-05-28 23:40 原话)

> "我最需要的就是让他盯着直播, 直播发生什么画面提醒我, 或者让他盯着你, 你出现 API 限速提醒我之类的这种."

**Sir 想 Jarvis 真能**:
1. **盯直播**: "盯下直播, 主播开始唱歌就喊我" — 主播表情/字幕/弹幕/礼物
2. **盯 Cascade**: "盯下 Windsurf, 出 rate limit 提醒" — error banner / 红色错误
3. **泛 vague request**: "盯一下" / "看着" 没说具体啥, 系统要能优雅 clarify 而不是装答应

## 2. 现状摸底 (Sir 说"没看到", 实际有大部分)

| 已有 | 状态 |
|---|---|
| `ScreenVisionEngine` (Gemini Vision describe, JSON schema) | ✅ default ON, env `JARVIS_SCREEN_VISION=0` 才关 |
| `WatchTask` (Registrar / Judge / daemon 集成 / SWM publish) | ✅ Sir 说"等 X 完" → 真注册 + judge → fire |
| Vision 持久化 + SWM `screen_described` event | ✅ |
| ScreenVision daemon 每 5min backfill | ✅ baseline (太慢 watch 用) |
| `WatchTask` `register_fail` block (Sir 14:50 fix21-c) | ✅ LLM 挂时主脑承认未注册 |
| Mirror mode (fix49 23:00) | ✅ 隔离 sandbox 测试整链 |

**缺什么 (fix50 5 改动)**:

| # | 缺口 | 真痛点 |
|---|---|---|
| 1 | Registrar 不处理 vague request | Sir 说 "盯一下那个" → LLM schema 提不出 → return None → Sir 以为 Jarvis 在盯, 实际 0 task (违准则 5) |
| 2 | 主脑 prompt 看不到 vague 请求 | 没机制让主脑下轮自动问 Sir 澄清 |
| 3 | active 期间 vision 不提频 | active 期间还按 5min backfill, fire 延迟可 5min |
| 4 | vague phrases 写死 .py | 违准则 6, Sir 不能 CLI 加新 phrase |
| 5 | Mirror 没法注入 fake snapshot | Cascade 不能控制 Sir 真屏幕 → 4 类视觉场景测不了 |

---

## 3. 5 改动设计 (准则 6 三维耦合)

```
[Sir 说 "盯一下"] → Registrar LLM 三分类 verdict
    ├── concrete → 老路径 (注册 WatchTask + 'watch_task_registered' SWM)
    ├── vague    → 新路径 publish 'watch_task_vague_clarify' SWM (不真注册)
    └── not_a_watch → skip

[主脑下轮 _assemble_prompt] 注入 [WATCH TASK VAGUE CLARIFY] block
    ↓
[主脑反问 Sir] → "您想我盯主播啥具体? 开播 / 唱歌 / 礼物 / 弹幕关键词?"
    ↓
[Sir 答清楚] → Registrar 老 concrete 路径真注册

[InnerThought tick 顶] _check_active_watch_task_and_publish_vision_refresh
    ├── 有 active task → publish 'proactive_vision_refresh_advice' SWM (dedup 5s)
    └── 无 → skip (不浪费 SWM event)

[ScreenVisionEngine._compute_effective_backfill_s]
    ├── 有近期 advice → 用 advice.recommended_backfill_s (30s)
    └── 无 → baseline 5min

[Mirror mode]
    Cascade → scripts/jarvis_mirror_screen.py inject fake snapshot
    → _mirror_screen.jsonl (新增 1 行)
    → ScreenVisionEngine._do_describe 顶 read latest fake
    → 跳过截图 + vision LLM, 直接构 ScreenSnapshot
    → 持久化 + publish + WatchTask judge (judge 仍真用 LLM)
```

### 准则 6 4 问筛查

| # | 问 | 答 |
|---|---|---|
| 1 | 数据 publish 进 SWM? | ✅ `watch_task_vague_clarify` + `proactive_vision_refresh_advice` + `watch_task_fired` (老) + `mirror_screen_fake_applied` (audit) |
| 2 | 决策让 LLM 做? | ✅ Registrar LLM 自判 vague/concrete (不写 regex), 主脑 LLM 自由组织反问句, Judge LLM 真判 trigger 命中 |
| 3 | 持久化 + CLI 可改? | ✅ `vague_trigger_phrases_zh/en` + `vague_clarify` + `vision_refresh_advice` 进 `memory_pool/watch_task_config.json`. `scripts/watch_task_dump.py vague-phrases` CLI |
| 4 | 和已有 module 正交? | ✅ 复用 `ScreenVision` + `WatchTask` + `InnerThought` + `Mirror`; 不加新 sentinel / sensor |

---

## 4. 文件变更清单

| # | 文件 | 改 | 行数 |
|---|---|---|---|
| 1 | `memory_pool/watch_task_config.json` | +`vague_trigger_phrases_zh/en` + `vague_clarify` + `vision_refresh_advice` config | +43 |
| 2 | `jarvis_watch_task.py` | Registrar prompt 三分类 + `_has_vague_phrase` + `_publish_vague_clarify` + `render_vague_clarify_block` helper + `_load_*` 默认参数 runtime resolve | +180 |
| 3 | `jarvis_central_nerve.py` | `_assemble_prompt` 接 `render_vague_clarify_block` | +6 |
| 4 | `jarvis_inner_thought_daemon.py` | `__init__` 加 `_last_vision_refresh_publish_ts` + `_check_active_watch_task_and_publish_vision_refresh` method + `_tick` 顶 call | +80 |
| 5 | `jarvis_screen_vision.py` | `_compute_effective_backfill_s` (advice-aware) + `_do_describe` 顶 mirror fake gate + `_do_describe_from_fake` helper | +130 |
| 6 | `jarvis_mirror_mode.py` | `get_mirror_screen_path` + `read_latest_mirror_screen` + `append_mirror_screen` (mtime cache) | +90 |
| 7 | `scripts/watch_task_dump.py` | `vague-phrases` subcommand (list/add-zh/add-en/remove) | +110 |
| 8 | `scripts/jarvis_mirror_screen.py` 新 | CLI 注入 fake snapshot (CLI 参数 / JSON file / --clear) | +210 |
| 9 | `scripts/jarvis_mirror_run_screen_scenarios.py` 新 | 6 场景一键跑 (E/F P0 + A-D P1) + tail event 统计 | +400 |
| 10 | `tests/_test_fix50_sir_20260528_screen_watch_clarify.py` 新 | 39 testcase (vocab / Registrar / inner_thought / screen_vision / mirror / CLI) | +780 |
| 11 | `docs/JARVIS_SCREEN_WATCH_DESIGN.md` 新 | 本 doc | +250 |
| 12 | `TODO.md` | 顶部 fix50 块 | +60 |

**共**: ~12 file, ~2300 行 code+test+doc, 0 主链路 break (39/39 test pass).

---

## 5. Mirror 6 类视觉场景测试方案 (Sir 真意所在)

**场景定义** (`scripts/jarvis_mirror_run_screen_scenarios.py` SCENARIOS dict):

| ID | PRI | 类别 | sir_utterance | 期望 fire keyword |
|---|---|---|---|---|
| **E** | **P0** | 直播 (Sir 真用例) | "盯下这个直播间, 主播一开始唱歌就喊我" | "唱歌" |
| **F** | **P0** | Cascade 限速 (Sir 真用例) | "看着 Windsurf 这个对话窗口, 出现 rate limit 错误提醒我" | "rate limit" |
| A | P1 | 文字 | "在 Cursor terminal 跑 build 呢, build 完叫我" | "build" |
| B | P1 | 图标 | "帮我盯下系统托盘, 微信红点出现就告诉我" | "微信" |
| C | P1 | 图形 | "股票软件 AAPL 涨破 100 通知我" | "100" |
| D | P1 | 图像 | "IDM 下载图标变绿 (下载完成) 说一声" | "下载" |

每场景 4 步:
1. Cascade `mirror_say` 注入 sir 话 → 触发 Registrar LLM 提取
2. 等 8s 让主脑 reply + Registrar 注册 WatchTask
3. Cascade `mirror_screen --summary "..." --notable "..."` 注入 frame1 (初态)
4. 等 35s 让 ScreenVision daemon 用 fake → judge LLM 判不命中
5. Cascade `mirror_screen ...` 注入 frame2 (触发态)
6. 等 35s 让 judge fire + 主脑 reply
7. 检查 `_mirror_output.jsonl` 含 `mock_tts` + expected fire keyword

**Cascade 真跑用法 (cheat sheet)**:

```powershell
# 1. 另开窗启 mirror (~15s)
python scripts/jarvis_mirror.py --task "fix50 6 screen scenarios"

# 2. 等 mirror_voice_worker_started event (~5s)
python scripts/jarvis_mirror_tail.py --event mirror_voice_worker_started --limit 1

# 3. 跑全 6 场景 (~10min, ~$0.05 LLM token)
python scripts/jarvis_mirror_run_screen_scenarios.py

# 或只跑 P0 (Sir 真用例) ~3min, ~$0.015
python scripts/jarvis_mirror_run_screen_scenarios.py --scenarios E,F

# 跑单场景 + 缩短等待 (调试用)
python scripts/jarvis_mirror_run_screen_scenarios.py --scenarios E --frame-wait 15

# 4. tail 看实时 audit
python scripts/jarvis_mirror_tail.py --follow                          # 另开窗
python scripts/jarvis_mirror_tail.py --event mirror_screen_fake_applied  # vision 应用
python scripts/jarvis_mirror_tail.py --event turn_complete --limit 6    # 主脑回复

# 5. 完事清盘
taskkill /F /PID <mirror pid>
rmdir /S /Q "D:/jarvis_mirror_<ts>"
```

---

## 6. Token 估算 (Sir 真关心)

| 阶段 | LLM 调用 | 估价 |
|---|---|---|
| Mirror 启动 (fix49) | 0 (init) | $0 |
| Sir 1 句注入 (主脑 reply) | 1 normal turn | ~$0.01 |
| Registrar LLM 判 vague/concrete | gemini-2.5-flash-lite 1 call | ~$0.001 |
| Fake screen 注入 (mock gate) | **0** (跳过真 vision LLM) | $0 |
| Judge LLM 真判 trigger 命中 | gemini-2.5-flash-lite 1 call/帧 | ~$0.001/帧 |
| Fire → 主脑 nudge reply | 1 nudge turn | ~$0.01 |
| 6 场景 × (1 reg + 2 judge + 1 fire reply + 主脑 reply) | ~24 calls | **~$0.05 total** |

**主进程 0 影响** (mirror 全独立 sandbox).

---

## 7. Sir CLI 真改 vocab (准则 6 持久化)

```powershell
# 查 vague phrases + 配置
python scripts/watch_task_dump.py vague-phrases

# Sir 加新 vague phrase
python scripts/watch_task_dump.py vague-phrases --add-zh "守着"
python scripts/watch_task_dump.py vague-phrases --add-en "stay watching"

# 删 phrase (case-insensitive en)
python scripts/watch_task_dump.py vague-phrases --remove "stay watching"

# 改 vision refresh 灵敏度 (改 watch_task_config.json 即可, 无需 .py 改)
# vision_refresh_advice.active_watch_backfill_s = 30.0  # default
# = 10.0 更敏感 (~3x token); = 60.0 省 token
```

---

## 8. 边界 — 准则 5 言出必行

**fix50 能 cover**:
- ✅ 主播表情 / 字幕 / 弹幕关键词 / 礼物特效 (Vision LLM 多模态识别)
- ✅ Cascade `Rate limit exceeded` / `429` / 红色 error banner (errors_visible 字段)
- ✅ 桌面图标变化 (微信红点 / 下载状态)
- ✅ Sir 模糊 watch 请求 → 主脑下轮主动澄清

**fix50 测不到** (后续 Gap):
- ❌ **音频内容** — 主播说啥/唱啥音频 Vision 看不见. 字幕/口型/弹幕是间接 evidence
- ⚠️ **采样间隔 30s** — 瞬时事件 (< 30s 一闪) 可能错过. Sir 可改 `active_watch_backfill_s` 到 10s, token 3x
- ⚠️ **多屏副屏直播** — 当前 `ImageGrab.grab()` 只截主屏, 多屏 enumeration 留 TODO
- ⚠️ **Mirror 测的是软件链, 不测真截屏 + 真 vision LLM** (Cascade 不能控制 Sir 真屏幕)

---

## 9. Sir 真测验收 (Cascade 跑 mirror 后人工判)

- [ ] 场景 E 直播: 注入 frame2 后 `mock_tts` 含 "唱歌" / "主播"
- [ ] 场景 F 限速: `mock_tts` 含 "rate limit" / "Cascade" / "Windsurf"
- [ ] 场景 A 文字 build: `mock_tts` 含 "build" / "完成" / "done"
- [ ] 场景 B 图标 wechat: `mock_tts` 含 "微信" / "消息"
- [ ] 场景 C 图形 stock: `mock_tts` 含 "100" / "AAPL" / "突破"
- [ ] 场景 D 图像 download: `mock_tts` 含 "下载" / "完成"
- [ ] Sir 说 "盯一下那个" → 主脑下轮自然反问 "盯啥具体动作?" (不是装答应)
- [ ] `python scripts/watch_task_dump.py vague-phrases --add-zh "新词"` 持久化生效

---

## 10. fix50.1 真测发现 (2026-05-29 00:09 Cascade 真跑 mirror 6 场景)

**Cascade 真跑 mirror 6 场景**: `D:/jarvis_mirror_20260529_000911`, 跑 ~10min ~$0.05 LLM.

### fix50.1 修了 2 个 BUG (此 doc 已含主体)

| # | BUG | 修法 (此 doc § 已 wire) |
|---|---|---|
| 1 | Registrar prompt 含 `jarvis_acknowledged` criterion → 主脑 pushback "outside my reach" 让 LLM 误判 not_a_watch | prompt 加 `[IMPORTANT — judge BY SIR'S INTENT ONLY]` 段 + `[JARVIS REPLY — context only, do not use as gate]` 标 |
| 2 | `_daemon_loop` 老 sleep(backfill_interval_s) 一觉 5min, advice publish 后 daemon 仍睡老周期 → scenarios 35s wait 错过 trigger | `wait_s = min(eff, 30s)` reactive |

### fix50.1 真测结果 (vs fix50 老)

| 场景 | fix50 老 reply | fix50.1 新 reply | 变化 |
|---|---|---|---|
| F (限速) | "I do not have a tool to monitor live content" ❌ | **"I shall keep a close watch on the Windsurf interface, Sir. The moment a rate limit error appears, I will notify you."** ✅ | POSITIVE ACK |
| A (build) | "I shall keep an eye on the terminal..." ✅ | **"Understood, Sir. I'll notify you the moment..."** ✅ | 仍 ACK |
| E (直播) | "outside my reach" | "cannot monitor the audio content" | 音频边界 (vision 看不到) |
| B/C/D | "outside my reach" 全 4 | "cannot monitor specific UI elements/external software/...icon color" | 主脑仍不知 vision 能力 (fix50.2 待修) |

→ **2/6 主脑 POSITIVE ACK** (fix50 老 1/6, fix50.1 加 F). 但 mock_tts=0 仍 0 全 6 — 因 root cause #3 ↓

### fix50.1 真因暴露 (mirror stderr) — fix50.2 待修的 5 BUG

mirror stderr 显:
```
[WatchTask/RegisterFail] phrase hit but LLM 没出 schema (LLM 挂或返垃圾) → 拒注册
  sir='看 Windsurf 对话, 出 rate limit 提'
  sir='在 Cursor terminal 跑 build 呢, build 完'
  sir='帮我盯下系统托盘, 微信红点出现就告诉我'
  sir='股票软件 AAPL 涨破 100 通知我'
  sir='IDM 下载图标变绿 (下载完成) 说一声'
```

**Registrar LLM (gemini-3.5-flash + flash-lite fallback) 每次都返垃圾/非-JSON/verdict=concrete 但 watch=null** — fix50.1 改 prompt 让它 ignore pushback, 但 LLM 仍输不出 valid JSON schema.

**InnerThought daemon F 场景自救**: `actionable=propose_watch_task:regex:rate limit → p_3569930f kind=watch` — 但写到 PromiseLog kind=watch, **不写 watch_tasks.json** → ScreenVisionJudge 看不到 → 0 fire.

### fix50.2 路线 (~30min + $0.1 LLM)

| # | BUG | 修法 |
|---|---|---|
| 1 | Registrar prompt 太长 + 复杂 verdict schema 让 gemini-3.5-flash 困惑 | 简化 prompt < 50 行, JSON 加 explicit example, primary model 换 `gemini-2.5-flash` (full, 非 lite) |
| 2 | LLM fail fallback 只 publish_register_fail 不真注册 → §5 违反 (主脑 ack 系统没注册) | phrase_hit + LLM fail → 用 sir_text 关键名词构造 minimal task + 标 `requires_clarify=true` 让主脑下轮 confirm |
| 3 | InnerThought `propose_watch_task` actionable 写 PromiseLog kind=watch 但不 sync 到 watch_tasks.json | actionable 真调 `WatchTaskRegistrar.register_async` 或直接 `_save_tasks` 写 watch_tasks.json |
| 4 | 主脑 prompt 没告诉它有 ScreenVision/WatchTask 能力 → 4/6 场景仍 pushback "outside my reach" | 主脑 prompt 加 `[SCREEN WATCH CAPABILITY]` block 教它 "ack any watch request, 系统会注册" |
| 5 | Registrar LLM 真 raw 没 debug log → 无法 root cause | `_call_registrar_llm` 加 raw response 写 SWM event `watch_task_registrar_raw_audit` (1 event/call, ttl 短) |

**触发条件**: Sir 拍板 fix50.2 (~30min + $0.1 LLM).

---

## 11. 关键 hook 路径回查

- `@d:\Jarvis\memory_pool\watch_task_config.json:57-97` vague_trigger_phrases + vague_clarify + vision_refresh_advice
- `@d:\Jarvis\jarvis_watch_task.py:221-260` _REGISTRAR_PROMPT (verdict 三分类)
- `@d:\Jarvis\jarvis_watch_task.py:323-338` _has_vague_phrase
- `@d:\Jarvis\jarvis_watch_task.py:340-389` _register_blocking (vague/concrete/fail/skip 分流)
- `@d:\Jarvis\jarvis_watch_task.py:421-466` _publish_vague_clarify
- `@d:\Jarvis\jarvis_watch_task.py:1061-1141` render_vague_clarify_block
- `@d:\Jarvis\jarvis_central_nerve.py:3739-3762` clarify block 注入 prompt
- `@d:\Jarvis\jarvis_inner_thought_daemon.py:1112-1175` _check_active_watch_task_and_publish_vision_refresh
- `@d:\Jarvis\jarvis_inner_thought_daemon.py:1183-1193` _tick 顶 call
- `@d:\Jarvis\jarvis_screen_vision.py:224-275` _daemon_loop 用 _compute_effective_backfill_s
- `@d:\Jarvis\jarvis_screen_vision.py:302-329` _do_describe mirror fake gate
- `@d:\Jarvis\jarvis_screen_vision.py:391-494` _do_describe_from_fake
- `@d:\Jarvis\jarvis_mirror_mode.py:73-158` mirror screen helpers
- `@d:\Jarvis\scripts\jarvis_mirror_screen.py` CLI 注入
- `@d:\Jarvis\scripts\jarvis_mirror_run_screen_scenarios.py` 6 场景跑

---

*文档作者: Cascade fix50 / 2026-05-28 23:50*  
*Sir 真痛 (盯直播 + 盯 Cascade 限速) + 准则 6 三维耦合 + 准则 8 优雅高效可持续 + Mirror 完整测试.*
