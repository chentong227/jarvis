# 实机 BUG 追踪 — 2026-06-02 (jarvis_20260602_194104.log)

> 临时文档, 全修完归档/删除。源: Sir 真机 19:42-20:01 session (带齐 C1/C3/F8/F9 重启后)。
> 一个个修, 每个修完镜像/单测验证 + commit + 本表标 ✅。

## BUG 清单 (按优先级)

| # | bug | 根因 | 严重度 | 状态 |
|---|---|---|---|---|
| B1 | **时间指代消解错误**: "6月3号晚上早点休息"(为后天体检) 被 `_detect_sleep_intent` 误判成"现在要睡" → 启动 632s 睡眠倒数 + SleepMode 静音 app | 睡眠意图按关键词硬触发, 不看未来时间指代 | 🔴 高 (误触发整个睡眠链 + 静音) | ✅ commit (未来日期守门) |
| B2 | **打开主页又开面板**: 主脑想开主页却 emit `open_url(8765)` (8765=面板端口, 主页=8766), 记错端口 | 拦截器按端口路由治标; 主脑分不清端口 | 🟡 中 (第2轮自纠了) | ✅ commit (拦截器加 Sir 原话意图消歧) |
| B3 | **TTFT 退步**: avg 5.6s / max 10.2s / 16轮8轮破5s红线 | breakdown=连接5.4s+等待0.0s → API 建连慢(网络层), 非 prompt 增大; 根因=每 turn new OpenAI() 新连接池 → 每轮 TLS 握手 | 🟡 中 (体感慢但非崩溃) | ✅ commit (client 连接复用 keep-alive) |
| B4 | **思考脑反刍仍高**: Cursor 30 / hydration 24 / persist 17 次, filler 30% | F9 已落地但本 session 未触发 let_go; 更深根因=放电反馈缺口 (低 agency concern 反复 attend 却不放电→tension 不降→反复召唤) | 🟢 低→治本 | ✅ commit (习惯化 habituation 补全放电反馈) |

## 详情

### B1 — 时间指代消解 (最该修)
- 时间线: 19:49 Sir "6月3号晚上8点后提醒我不喝水、早点休息" (体检准备)
- `Time Hook` 正确调度 6/3 提醒 ✅
- 但 `_detect_sleep_intent` 同时把"早点休息"判成此刻睡眠 → `SleepMode/Countdown 632s` + `MuteApps`
- Jarvis 自己最后承认: "我似乎将您的禁食要求与休息时间混为一谈了...将该逻辑应用到了今晚"
- 治本方向 (准则6): `_detect_sleep_intent` 命中睡眠关键词时, 先查句中有无**未来时间指代** (明天/后天/N月N号/具体日期) → 有则不触发**此刻** SleepMode, 只走提醒调度。时间指代 vocab 持久化 + CLI。

### B2 — 主页端口混淆
- 主脑 emit `url_launcher.open_url(8765)` 想开主页, 但 8765=面板端口
- 拦截器 (commit e03f12c) 忠实 8765→dashboard_open
- 治本方向: 主脑层不该 emit 端口; directive 强化"主页/面板用语义命令 homepage_open/dashboard_open, 永不 emit 端口 URL"。或拦截器结合"主脑刚才说的是主页还是面板"的意图。

### B3 — TTFT 网络建连慢
- breakdown: `连接5.4s + 等待0.0s` → token 一发即来, 慢在建连
- 非 L0 framing 增大导致 (那会体现在 prompt 处理/等待, 不是连接)
- **根因**: `jarvis_chat_bypass.py` 每 turn `new OpenAI()` (主路径 ~871 + fallback ~3880)
  = 每轮新建 httpx 连接池 → 每轮全程 TLS 握手 (无 keep-alive 复用)。OpenRouter 通道。
- **治本 (准则 8, commit)**: `_get_or_client(base_url, key, timeout)` 按 (base_url, key)
  缓存 OpenAI client → keep-alive 复用底层 TCP/TLS 连接 → 第 2 轮起跳过握手。key 轮换
  (KeyRouter 切 key) → 新 cache entry。cache 上限 8 防膨胀。两处构造点都改走 helper。
- 4/4 testcase `tests/_test_b3_client_reuse_sir_20260602.py`。**镜像/单测验复用逻辑**,
  真实 TTFT 改善需 Sir 真机连续多轮测 (单测测不到真实网络 RTT)。

### B4 — 反刍 (深挖治本: 习惯化)
- F8 (new_topic 归并) + F9 (same_thread 语义聚类) 机制已落地, 但都依赖 LLM 显式输出 LET_GO
- **更深根因 (Sir 拍板深挖)**: 设计 §2/§3 承诺"放电→E降→不再醒", 但唯一 wired 放电通道是
  stance-coverage。低 agency concern (hydration) 识反复 attend 却只 `adjust_concern_notes`
  (不改 severity 不立 stance) → 永不放电 → tension=severity 每 weave 重算 → 那区 standing
  energy 居高 → 反复召唤识。Jarvis 明确说"我在机械固执地关注 hydration"却停不下 = 结构缺口
  (早于衡/锚, 纯思考脑版即有)。
- **治本 (习惯化 habituation, 非热补丁)**: 识每 tick publish `body_attention_outcome`
  (node + discharged=heng_state)。Weaver `_habituation_map` 消费: 某 node 反复非放电 attend
  超 free_attends → tension ×= decay_base^excess (到 floor 止); 真放电→重置; 久不 attend→
  spontaneous recovery。只乘 tension 源 1, novelty/drift/nudge 不受 → 真新进展自然突破。
- 详 `docs/JARVIS_VOICE_AND_MIND_REFACTOR.md §3.1`。8/8 testcase
  `tests/_test_b4_habituation_sir_20260602.py`。config vocab `relational_manifold_vocab.json`
  energy.habituation_* (Sir 可调/可关)。
