# JARVIS Audit Cards (Phase A.1)

> Phase A 模块审计集中文档. 每模块 1 张 card. 按 `JARVIS_GRAND_REFACTOR.md` §4 批次顺序.
>
> **进度**: 1/140 (0.7%) — 批次 a (5 核心枢纽) 进行中.
>
> **使用**: 任何 agent 写新 card → 追加到本文末尾 + 更新 `JARVIS_GRAND_REFACTOR.md` §6.2.

---

## 批次 a: 5 核心枢纽

### #1 `jarvis_nerve.py` (329 行) — 主入口 __main__ + 转发垫层

**职责**: 启动 Jarvis (PyQt5 main loop + 实例化全部 component + 线程 wiring). 兼容旧 import (`from jarvis_nerve import X`) 通过转发垫层.

**核心 method / class**:
- `__main__` (line 238-329) — 启动序列, 顺序极重要:
  1. `multiprocessing.freeze_support()` (Windows EXE)
  2. `TraceContext.init_session()` → `sess_YYYYMMDD_HHMMSS_<PID>` (后续 bg_log 自动带前缀)
  3. `load_keys()` 从 `.env` 读 API key
  4. 实例化 `KeyRouter(main_brain, google_list, openrouter_list)`
  5. `key_router.probe_google_keys_at_startup(async_mode=True)` (2s 后检测 Google key 健康)
  6. `QApplication(sys.argv)` PyQt5 主 app
  7. `BreathingLightUI()` 实例化 Orb UI
  8. `JarvisWorkerThread(api_key, gemini_key, key_router)` 实例化 worker (内含 `CentralNerve`)
  9. wire `jarvis_worker.state_changed → ui.change_state`
  10. `jarvis_worker.start()`
  11. `SubtitleOverlay(ui)` + 注入到 chat_bypass.subtitle_queue
  12. `ScreenshotSentinel()` + `UserStatusLedgerSentinel(...)` 启动
  13. 连接 `jarvis.conductor / reflection_scheduler / commitment_watcher` 等 attr
  14. 共享 `HumorMemory` 单例 (避免双实例)
  15. `VoiceListenThread()` 启动 + wire 信号 (text_ready/interrupt/awake)
  16. 双向 wire voice_worker.state ↔ jarvis_worker.state ↔ `AttentionSlot` 共享
  17. `voice_worker.start()` + `app.exec_()`

**数据**:
- 读: `.env` (`load_keys` from `jarvis_config/keys.py`) — `OPENROUTER_MAIN` / `GOOGLE_LIST` / `OPENROUTER_LIST` / `GEMINI`
- 写: 进程内全局 — UI / worker / voice_worker / sentinel 实例
- SWM publish: 通过 `TraceContext.init_session()` 间接 (subsequent bg_log)

**上游 (谁调它)**: 无 (本身是 `__main__` 入口) — Sir 运行 `python jarvis_nerve.py`

**下游 (它调谁, 32 个 import)**:
- 转发垫层 import (~25 个老 module, e.g. `KeyRouter` / `PhysicalEnvironmentProbe` / `ChronosTick` / `ChatBypass` / `CentralNerve` / `Worker` / `UI` / ...)
- 启动 wiring 实际调: `KeyRouter` / `BreathingLightUI` / `JarvisWorkerThread` / `SubtitleOverlay` / `ScreenshotSentinel` / `UserStatusLedgerSentinel` / `VoiceListenThread` / `AttentionSlot` / `TraceContext`

**跟记忆的耦合**:
- 直接写: 无
- 直接读: 无
- 间接耦合: 启动时实例化 `CentralNerve` (含 `ProfileCard` / `Hippocampus` / `ConcernsLedger` / `CommitmentWatcher` / ...) — **本模块是所有记忆 component 的 owner / lifecycle 入口**

**跟其他模块的耦合**:
- `jarvis_central_nerve.py`: 实例化 `CentralNerve` (通过 Worker)
- `jarvis_chat_bypass.py`: 通过 `jarvis_worker.jarvis.chat_bypass` 间接 wire `subtitle_queue`
- `jarvis_worker.py`: `JarvisWorkerThread` 是主 Worker
- `jarvis_ui.py`: `BreathingLightUI` + `SubtitleOverlay`
- `jarvis_utils.py`: `TraceContext` + `AttentionSlot` + `safe_gemini_call` 等
- `jarvis_config/keys.py`: `.env` loader
- `l1_right_brain.py` / `l3_left_brain.py` / `l5_reflection_brain.py`: 老 3-brain 架构 import (实际可能未用, **待审**)

**已知问题 / TODO marker**:
- Line 28-49: 重复 import + 历史遗留 (`speech_recognition` / `funasr` / `comtypes` / `PIL.ImageGrab` 等, 可能现状不全用)
- Line 51: `# [C1-7] 删除未使用的 difflib import` — 历史 cleanup 标记
- Line 70-71: 已 deprecated 的重复 import 标 cleanup
- Line 73-74: **硬编码 HTTP_PROXY=127.0.0.1:7890** — Sir 个人代理, EXE 部署时会失效
- Line 58-60: `l1_right_brain` / `l3_left_brain` / `l5_reflection_brain` 老 3-brain 架构, **可能已废弃需 audit**
- Line 62: `ProactiveShield` / `SkillTreeTracker` / `ProactiveCompanion` from `jarvis_enhanced.py` — `enhanced.py` 无 docstring, **可能历史遗留**

**关联 design doc**: 无专 doc (本模块是薄垫层). `JARVIS_ARCHITECTURE_MAP.md` §3.1 提到.

**重构含义 (Phase B 设计参考)**:
- **保留**: __main__ 启动序列 (已稳定)
- **可优化**:
  - 启动 wiring 太多手动 attr 注入 (line 268, 274-300) — 应集中 `CentralNerve.wire_dependencies()` 一处管
  - `l1/l3/l5_brain` import 可能 deprecated — Phase A.5 历史审时确认
  - `jarvis_enhanced.py` 是否真在用 — 同上
- **不动**: TraceContext / KeyRouter / 转发垫层 (老代码兼容)

**审计结论**: 入口模块, 行少, 大部分是 wire. 重构关注点是 wiring 集中化 + 旧 brain 清理. 不在记忆系统主线.

---

