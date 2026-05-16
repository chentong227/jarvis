# Jarvis 架构审计 — 2026-05-16

**触发**：Sir 反馈"改了这么久，一个简单的对话就有连环 bug"，要求"完整测试一遍贾维斯有没有 bug，有没有耦合问题，有没有不能实现的功能"。

**方法**：手动 + Grep + ripgrep 全工程扫描；动态行为参考 Sir 实测 `jarvis_20260516_123813.log`；并发 explore subagent 补充。

**范围**：23 个根目录 `jarvis_*.py` + tests/ + scripts/ + memory_pool/ + docs/。

**结论**：见下方 5 大类发现 + TL;DR。

---

## A. 死代码（已修）

### A1. jarvis_enhanced.py 962 行死代码（已修 commit f6caa65）

| 死代码类 | 真实使用版位置 |
|---|---|
| PromptCache | jarvis_memory_core.py:300 |
| CorrectionLoop | jarvis_memory_core.py:876 |
| UnifiedMemoryGateway | jarvis_memory_core.py:504 |
| TaskWorkerPool | jarvis_memory_core.py:730 |
| Anticipator | jarvis_memory_core.py:779 |
| ContextRouter | jarvis_routing.py:187 |
| ProfileCard | jarvis_routing.py:486 |
| ContentPreferenceTracker | jarvis_routing.py:280 |
| SoulRouter | jarvis_routing.py:51 |

**根因**：P0+19 拆分时把 enhanced.py 9 类抄到 routing.py / memory_core.py 之后没删 enhanced.py 原版，archive C1-2 已记录"P0+19 拆分时记得要删但没删"，β.1.10 补做。

**影响**：jarvis_enhanced.py `1531 → 569 行 (-63%)`；零运行时影响（全工程零处 `jarvis_enhanced.<class>` 动态访问 + 测试只 import 模块本身）。

**保留**：ProactiveShield + ProactiveCompanion + SkillTreeTracker（3 类是 central_nerve.py:97 真实 import）+ get_user_idle_seconds helper（ProactiveCompanion 在用）。

### A2. 6 处 inline directive 已搬 L2（已修 commit 2c6650f）

| 删除点 | 替代 directive |
|---|---|
| `_assemble_prompt` FACTUAL_RECALL/WAKE_ONLY/light/full branch 4 处 [BILINGUAL DIRECTIVE] | L2 bilingual_directive (priority 10, trigger=always) |
| light/full branch 2 处 [SEARCH DIRECTIVE] | L2 search_directive (trigger=time-sensitive 词) |
| full branch 1 处 [IMAGE CONTEXT] | L2 image_context (trigger=has_screenshot) |
| full branch 1 处 [MEMORY CALLBACK] | L2 memory_callback (trigger=stm >= 3) |

**保留**：PERSONA NUDGE / AGENDA HONESTY 段（P0+18-f.2 testcase 显式断言依赖）；reminder firing branch 的 [BILINGUAL]（特殊路径，TTFT < 2s 关键）；中断处理 prompt 的 [MEMORY CALLBACK]（独立 branch）。

### A3. scripts/_extract_p19_*.py / _patch_p19_*.py 17 个 P0+19 拆分历史脚本

**判断**：保留作历史参考（每个脚本都标 marker，是拆分阶段的"快照"，删了也没人 grep）。**不修。**

---

## B. 耦合问题（已修关键）

### B1. 循环依赖：jarvis_central_nerve ↔ jarvis_chat_bypass（已修 commit a5ebe8d）

- `jarvis_central_nerve.py` import `ChatBypass`（line 103）
- `jarvis_chat_bypass.py` 函数体内用 `JARVIS_CORE_PERSONA`（来自 central_nerve）
- 模块顶部直接 import 会循环依赖

**修法**：函数体内延迟 import + `_JCP` 局部别名兜底。

### B2. 全局单例 `PhysicalEnvironmentProbe._tick_callbacks` 是 class-level list

- `jarvis_central_nerve.py:227` `PhysicalEnvironmentProbe._tick_callbacks.append(self.content_tracker.tick)`
- 单实例 OK（CentralNerve 只 new 一个），但**测试时多个实例会互相污染**

**修法建议**：tests/conftest.py session 开始时 reset，避免测试间污染。**P2 / 暂不修。**

### B3. JarvisState (jarvis_utils.py) vs CentralNerve._in_conversation 双源

- 新代码走 `state.set_active_conversation()` + property setter
- 老代码 `self._in_conversation = True` 直写（已加 setter 兼容）
- 行为一致但**调试时可能造成"两边状态不同步"假象**

**P2 / 已有兼容层**。

### B4. jarvis_enhanced 顶部 `from jarvis_env_probe import PhysicalEnvironmentProbe`

- env_probe 又被 sentinels / sensors 等 import → 形成菱形依赖
- Python 能解（因为 env_probe 简单）但**改 env_probe 的 API 会四处波及**

**P2 / 不动**。

---

## C. NameError 留尾（已修关键）

### C1. jarvis_chat_bypass.py 缺 JARVIS_CORE_PERSONA import → B8 OfferHelp 未出声（已修）

### C2. jarvis_return_sentinel.py 缺 win32api import → B9 归来感知失效（已修）

### C3. jarvis_smart_nudge.py 缺 win32api import → 主循环 idle_ms 永 0（已修）

### C4. jarvis_commitment_watcher.py 缺 win32api import → 承诺过期分支静默丢失（已修）

### C5. 防御性回归 testcase（已加 commit a5ebe8d）

- _test_p0_plus_20_b1_nameerror_guards.py：12 个 testcase
- 包含全量 23 模块 import smoke：未来再加新模块自动覆盖

---

## D. 老 BUG 留尾（部分已修）

### D1. **future-tense capability lie**（已修 commit 9b979ab）

- α.3 注释明示"不扩到这块" → 从未实施
- β.1.11 加 13 号 directive `future_tense_capability_check`：
  - 上一轮答 "I can take a closer look" / "我会去看一下" 等空头承诺 → 本轮注入诚实兜底 directive
  - 强制 LLM (a) FAST_CALL 真兑现 / (b) 当场撤回
- 23 testcase 覆盖（13 EN + 10 ZH 模式 + trigger 行为）

### D2. **TWO_PARTS 多意图**（β.0.3 已注入，未真机验证收敛）

- L2 directive `continuity_two_parts` 已注入 prompt
- `_has_multi_intent_connector` 要求 `len(text) >= 12 + 含连接词`
- **风险**：Sir 短句"对了..."(< 12 chars) 不触发 → directive 漏掉
- **建议**：β.1.X 后续放宽到 `>= 8 chars`，但要防误触发短 affirmation

### D3. **β.1.7 Sir 自我打断白名单**（已修 commit 71e2e39）

- 10 pattern 覆盖 "不对不对" / "我我X" / "wait/let me" 等 → 跳过 Help Refusal 误判

### D4. **B1/B2 时间 + Memory Correction 守卫**（已修 commit 71e2e39）

- sanitize_trigger_time + detect_semantic_category 后处理
- 26 testcase 覆盖

### D5. **β.0/false_tool_chain_after_malformed**（α.5 + β.1.11 部分覆盖）

- α.5 SYSTEM HARD CONSTRAINT 反馈消息禁止 "captured/checked/refreshed" + "Done, Sir/already completed" 一气呵成假完成
- β.1.11 future_tense_capability_check 进一步覆盖
- **风险残留**：LLM 仍可能在 malformed 第一段判为幻觉后，第二段编新的 FAST_CALL。**P1 / 等真机暴露**。

### D6. **β.0/asr_video_leak**（未修）

- active_conversation 期间视频音被录入，但 worker.py 已有 `mute_until` + `_suppress_wave` 防护
- VAD/speaker diarization 是真彻底解，但工程量大
- **路线 D 候选 / 暂不修**

### D7. **d.5 中文 Audio Guard 上游路径**（部分修，等真机复现）

- jarvis_safety.py `_sentence_is_chinese_lean` 已在 chat_bypass.py:1968 splitter 调用
- 兜底 Audio Guard 仍生效
- **可观察性 OK**

---

## E. 偶尔失效 / 未实测验证的模块（P5b）

### E1. PromiseExecutor —— daemon 启动 OK，无实测触发记录

| 项目 | 现状 |
|---|---|
| daemon 启动 | ✅ `[PromiseExecutor] 后台执行器已启动 (tick=1.0s)` (log:33-34) |
| _fast_call/_say 注入 | ✅ `fast_call+say 已注入 + daemon 已启动` |
| 真跑过 promise.start_step | ❓ Sir 12:43-14:30 session 无 `Promise.activated/started` 痕迹 |
| promise 持久化 | ❓ memory_pool/promises.json 是否存在？|

**结论**：daemon 健康，但等 Sir 真说"开始驾照科一"才能验证 end-to-end。**P1 / 待真机验证**。

### E2. SoulArchivist —— 真触发过

- `[SoulArchivist] 潜意识归档引擎就绪 (每小时触发模式)` (log:65)
- `[SoulArchivist] Sir的资料已更新，沉淀了新的洞察` (log:305) ✅

**结论**：归档链路真 work。

### E3. ChronosTick / ChronosSentinel —— 启动 OK，本次 session 无 reminder fire

- `fetch_due_reminders(current_ts)` 周期性查 DB（jarvis_sentinels.py:393）
- `_pending_reminders[reminder_id] = {...}` 真注册（jarvis_sentinels.py:369）
- 本次 session Sir 没设过新 reminder + 没 reminder 到期 → 0 fire 是合理

**结论**：代码健康，等 Sir 设个真 reminder 实测。**P1 / 待真机验证**。

### E4. SkillRegistry 130 skill —— bootstrap OK，调用率未追踪

- `bootstrap 完工: loaded=0 scanned=130 new=130 total=130`（health_check 实测）
- 30 KB 的 metadata 写到 memory_pool/skill_registry.jsonl
- **未追踪**：130 个里面哪些被 `_execute_fast_call` 调过、哪些一年没人调

**建议**：β.1.X 后续给 skill_registry 加 `last_called_at` + `total_calls` 字段，跑半年扫一次发现"死 skill"。**P2**。

### E5. ScreenshotSentinel —— hash 比对 OK

- log:115 `[Screenshot] strategy=fresh | elapsed=37ms`
- 已生效

### E6. SmartNudgeSentinel —— fired 累计 0（fingerprint 1 次）

- log:91 `[Help Refusal] 用户拒绝帮助 (#1, strong=False)` → 累计 1 次
- 但因 B3 误触发，应该 0 才对（β.1.4 修后会 0）

### E7. CommitmentWatcher —— 真注册过

- jarvis_20260516_123813.log 中有 commitment 注册痕迹
- 但本次 session 没 commitment 到期触发

---

## F. 性能热点

### F1. _assemble_prompt 装配 1274ms → 3074ms（B4 / β.0.3 双层注入翻 2.4x）

- β.1.8 删 6 处 inline directive（约省 800-1000 chars + ~200ms 装配）
- **建议**：β.1.X 后续加 `[Asm Diag/Stage]` 细分日志，看哪一层最慢

### F2. TTFT 第三轮 26.7s（B5 / 网络抖动 + B7 google 全挂连锁）

- B7 google_1 永久剔除已持久化（β.1.5 commit 71e2e39）
- 网络抖动是 OpenRouter 测的，**不可控**

### F3. Hippocampus.search_memory Embedding 调用次数

- 每次对话装配若 `needs_ltm=True` 调 1-2 次 embed
- **未量化**，需要加 `[Hippocampus/EmbedDiag]` 日志后采集

---

## TL;DR — 项目"哪里最危险"（3 句话）

1. **P0+19 拆分留尾**是当前最大风险源（B8 OfferHelp + B9 归来感知 + jarvis_enhanced.py 962 行死代码 + 4 处 win32api 缺 import 都源自 P0+19），β.1.6-10 已系统性扫清，并加 38 testcase + 体检脚本防回归。

2. **静默吞错 + 泛用 try/except** 是次大风险源（NameError 进 try/except 不报警，模块依赖任何外部对象失败都返回 None 兜底），β.1.7 在 ReturnSentinel 加启动自检 + 5min 诊断日志（grep `[ReturnSentinel/Health]` / `[ReturnSentinel/Diag]`）作为模式范例。

3. **prompt 装配链 + LLM 行为约束** 是结构性挑战而非 bug：未来增长方向是把更多 inline directive 搬到 L2 conditional registry（已 13 条），用 fired/rejected/helped 三层学习信号自动衰减；当前 prompt 仍 30K chars / 装配 ~3s，β.1.X 后续按需做 PERSONA iterate。

---

## 修复进度（β.1 全轮）

| Marker | 修复内容 | commit / tag |
|---|---|---|
| β.1.1-5 | 救火 5 修（B1/B2/B3/B6/B7）| `71e2e39` / `v0.20.3-firefighting` |
| β.1.6-7 | NameError 留尾批量修（B8 OfferHelp + B9 归来感知）| `a5ebe8d` / `v0.20.4-nameerror-guards` |
| β.1.8 | 删 6 处 inline directive（L2 单一注入路径）| `2c6650f` |
| β.1.9 | scripts/health_check.py 9 项体检 | `c0ec391` |
| β.1.10 | 删 962 行死代码（jarvis_enhanced.py 1531→569）| `f6caa65` |
| β.1.11 | future-tense capability lie 治本 + 23 testcase | `9b979ab` |

**总计**：6 个工程 commit + 2 个 tag + **52/52 testcase 全绿** + 体检 8 OK / 1 WARN / 0 FAIL。

---

*本文件由 P0+20-β.1 全轮收尾自动归档。后续轮次按需追加新审计段。*
