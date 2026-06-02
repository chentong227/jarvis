# 实机 BUG 追踪 — 2026-06-02 (jarvis_20260602_194104.log)

> 临时文档, 全修完归档/删除。源: Sir 真机 19:42-20:01 session (带齐 C1/C3/F8/F9 重启后)。
> 一个个修, 每个修完镜像/单测验证 + commit + 本表标 ✅。

## BUG 清单 (按优先级)

| # | bug | 根因 | 严重度 | 状态 |
|---|---|---|---|---|
| B1 | **时间指代消解错误**: "6月3号晚上早点休息"(为后天体检) 被 `_detect_sleep_intent` 误判成"现在要睡" → 启动 632s 睡眠倒数 + SleepMode 静音 app | 睡眠意图按关键词硬触发, 不看未来时间指代 | 🔴 高 (误触发整个睡眠链 + 静音) | ✅ commit (未来日期守门) |
| B2 | **打开主页又开面板**: 主脑想开主页却 emit `open_url(8765)` (8765=面板端口, 主页=8766), 记错端口 | 拦截器按端口路由治标; 主脑分不清端口 | 🟡 中 (第2轮自纠了) | ⬜ |
| B3 | **TTFT 退步**: avg 5.6s / max 10.2s / 16轮8轮破5s红线 | breakdown=连接5.4s+等待0.0s → API 建连慢(网络层), 非 prompt 增大 | 🟡 中 (体感慢但非崩溃) | ⬜ |
| B4 | **思考脑反刍仍高**: Cursor 30 / hydration 24 / persist 17 次, filler 30% | F9 已落地但本 session 未触发 let_go (thread 计数/LLM 未输出 LET_GO); 待长跑验 | 🟢 低 (F8/F9 机制已在, 观察) | ⬜ 观察 |

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
- 治本方向: 连接复用 / keep-alive / 建连预热。需先确认是 OpenRouter 还是 Google 通道。

### B4 — 反刍 (观察项)
- F8 (new_topic 归并) + F9 (same_thread 语义聚类) 机制已落地
- 本 session continuity 47/49 same_thread, F9 应聚类 — 但未见 LLM 输出 LET_GO
- 待 Sir 多次重启长跑, 看 let_go 是否随簇 aged 触发。暂不动代码, 观察。
