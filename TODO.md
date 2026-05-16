# Jarvis TODO 工作板

**更新时间**：2026-05-16 02:45（**🎉🎉🎉 P0+19 整轮完工 / Nerve 拆分 98.1% 减少** — `jarvis_nerve.py` **17479 → 324 行**，拆出 **16 个独立文件**：jarvis_safety/key_router/llm_reflector/env_probe/sensors/routing/memory_core/sentinels/conductor/return_sentinel/commitment_watcher/smart_nudge/chat_bypass/central_nerve/worker/ui，**1098 testcase 持续全绿** / enhanced.py 循环依赖死 / 朋友分发套件就绪。**剩 Sir 手动 4 件**：1) rotate 8 keys / 2) 填 `.env` / 3) `git init` / 4) 启动 `python jarvis_nerve.py` 实测一轮 → P0+19-final 完全收尾。详见 `docs/NERVE_SPLIT_PLAN.md` + `docs/AGENT_KICKOFF_PROMPT.md`。）

---

## 📕 AGENT QUICKSTART（Cursor Agent 必读 / 约 30 秒）

> **唯一目的**：让 Agent 用最少的 token 读取最准确的上下文，避免 Cursor 对话超 52MB（`Append data exceeds maximum size of 52428800 bytes`）锁死。**永远不要把整个 TODO / archive / 日志读进上下文。**

### 1. 文件分工

| 文件 | 用途 | Agent 读取规则 |
|---|---|---|
| `TODO.md`（本文件，<300 行） | **当前代办 + 已知 BUG + 章程** | ✅ 每次会话进来先读这个文件（**整个 OK，本文件刻意压在 300 行内**） |
| `docs/TODO_ARCHIVE.md`（~2200 行） | 已完工的迭代回溯 / 因果链 / 测试统计 | ❌ 不要默认读。**仅当 Sir 明确说"上次/上轮/R7/P0+16/轴3…"等历史关键词** → 用 `Grep` 取那段、不要 `Read` 全文 |
| `docs/runtime_logs/jarvis_*.log` | 每次启动的完整 stdout/stderr 实时同步 | ❌ 不要 `Read` 全文。**先看 `docs/runtime_logs/latest.txt`（一行，里面是最新日志的绝对路径），再用 `Grep` 取关键段** |
| `docs/funnel_logs/funnel_*.log` | 智能轻推漏斗的命中/拒绝判定 | 同上，按需 grep |

### 2. "上次/上轮"语义映射（Sir 提到这些词的 SOP）

| Sir 的话 | Agent 该做的事 |
|---|---|
| "上次发生了什么" / "刚才那个 bug" / "前面那段" | (1) `Read docs/runtime_logs/latest.txt` 拿绝对路径；(2) `Grep` 出对应错误/Pipeline/Human 段；(3) 必要时 `Read` 文件**指定行段**（`offset+limit`，**不要全文**） |
| "上轮/上次/上回那个 BUG 修了没" / "P0+18/a.X 修了没" | (1) 先 `Grep` `TODO.md` 看是否在已知未尽；(2) 再 `Grep` `docs/TODO_ARCHIVE.md` 找最后一次出现的 marker（`a.X / P0+X / 轴X / RX`）+ 状态 |
| "重启实测/我刚跑了 N 件事" | (1) 拉最新两份 `jarvis_*.log`；(2) Grep `║ 🗣️\|║ 🤖\|⛔\|❌\|🔁` 抓对话框 + 错误；(3) 报告新 bug 时**抄日志关键行号**，不要复述大段 |

### 3. 减少 token / 避开 52MB 上限的 5 条硬规

1. **`Read` 大文件加 `offset` + `limit`**：>500 行的文件一次最多读 200 行；jarvis_nerve.py 17000+ 行**永远分段读**。
2. **优先 `Grep`**：找"某变量/某 emoji/某错误码"全用 ripgrep（Grep 工具），不要 `Read` 全文 grep。
3. **TODO 写作上限**：本 `TODO.md` 永远 ≤ 300 行；超出 250 行就把"已完成的迭代"剪到 `docs/TODO_ARCHIVE.md` 顶部。
4. **回复给 Sir 的内容**：用表格 + 行号引用，不要复制大段代码；最多 1-2 个`startLine:endLine:filepath` 引用块。
5. **新增 BUG 修复完工**：在本文件**只保留 1-2 行**说明 + marker；详细因果链/测试统计**直接进 archive 顶部**。

### 4. 完工归档协议 / 三轮滚动制（写代码后做的事）

> **核心规则：本文件永远只保留"上一轮 + 当前轮"的内容；再往前的"上上轮"必须沉到 archive。**

| 时间轴 | 位置 | 内容粒度 |
|---|---|---|
| **当前轮**（进行中） | `TODO.md` 的「当前迭代」段 | 完整任务看板 + 子步骤进度 + 在此处持续更新 |
| **上一轮**（最近一次完工） | `TODO.md` 的「上轮完工速览」段 | 1 个段落 + 关键 marker 列表（让 Sir 切窗口能快速回忆） |
| **上上轮及更早** | `docs/TODO_ARCHIVE.md` 顶部 | 完整因果链 / 测试统计 / 改动清单等所有细节 |

#### 一轮完工时 Agent 必须做的滚动操作

1. **当前轮变上轮**：把「当前迭代」段精简成 1 段「上轮完工速览」（保留：开始/完工时间、修了几个 BUG、marker 列表、绿/红测试数）。
2. **原上轮 → 沉档**：把原「上轮完工速览」整段连同改前的完整看板**追加到 archive 顶部**（在「归档目录」表下方的「📜 原文」段最前）。
3. **archive 目录表更新**：在 archive 顶部表里**插入一行**指向新沉档段的行号区间 + 完工时间 + 主题。
4. **新轮号**：在「当前迭代」段写新一轮的看板（marker 形如 `P0+18-g`, `P0+19`, `轴4-α1` 等连号）。
5. **完工标识**：每个 BUG 修复 commit / 代码段都带 `[<marker> / 2026-05-XX]` 注释，便于 grep。
6. **本文件硬上限**：滚动完后整个 `TODO.md` 行数仍要 ≤ 300 行；超出就再压缩"上轮完工速览"段。

---

## 📌 上轮完工速览（P0+18-f / 2026-05-15 22:00-22:50）

> 详细 4 项看板 + 因果链 + 改动文件 + 测试统计 → `docs/TODO_ARCHIVE.md` 顶部「P0+18-f 完工段」（约第 43-105 行）。

- **起点**：Sir 22:10-22:14 重启实测 P0+18-e，主诉"几轮对话要 20s+，之前 3s 返回"+ 终端打印延迟高 → 锁定 colorama wrap 撤销 / TeeStream 异步化 / strip_ansi 快速路径三处叠加。
- **完工**：f.1 ✅（性能崩溃 TTFT 3s 回归）/ f.2 ✅（NUDGE/AGENDA HONESTY directive 加固）/ f.3 ✅（type-specific 12/24h long-term mute）/ f.4 ✅（Integrity referential pre-filter + 1.5B 反例）/ f.5 ✅（[Perf Diag] / [Asm Diag] 日志埋点）
- **关键 marker**：`P0+18-f.1` `_TEE_QUEUE` / `_tee_worker_loop` / `just_fix_windows_console` / `P0+18-f.2` `[NUDGE / AGENDA HONESTY]` / `P0+18-f.3` `_muted_nudge_types` / `P0+18-f.4` `referential_markers_en` `referential_markers_zh`
- **测试**：48 / 48 suite OK，28 新 testcase，0 FAIL

---

## 🧪 Sir 重启 Jarvis 立刻可验证（≤ 6 条）

1. **TTFT 回到 3s 量级**：随便说一句 → 终端 `[Pipeline Timer] TTFT` 应回到 2-5s（而非 18-27s）。如还慢，去 `latest.txt` grep `[Perf Diag]` 看 connect / wait / queue_depth 哪段瓶颈
2. **终端打印不再延迟**：声波 🎙️ 不再卡，对话框 ║ 🤖 [Jarvis] 立刻出
3. **Sir 说"不用再提"**：Jarvis 应回 "Acknowledged, Sir. I'll hold off on that for now." / "Noted — that prompt is on cooldown." — **不再撒谎说 "struck it from the active agenda"**
4. **dormant_project 当日不复活**：拒绝后 12h 内同款 nudge 不再触发（grep `[SmartNudge/TypeMuted] dormant_project` 验证）
5. **referential 陈述不再误警告**：主脑解释"我说的是 X"时不再触发 `🚨 [Integrity Check] no_tool_called`
6. **测试**：`tests\_runall.ps1` 输出 `REGRESSION SUMMARY: 48 / 48 OK, 0 FAIL`

---

## 🐛 已知未尽 BUG（按优先级）

> 当前 P0+18-f 已全部修完。剩余只有长期工程项 / 留尾候选。

| 优先级 | BUG | 状态 |
|---|---|---|
| **中** | **轴 5.2**：CommitmentWatcher 已 P0+18-e.3 持久化到 SQLite ✅，但仍可扩展（按 deadline 排序检索 / nudge 间隔策略 / cross-session 反查 polish）| ⏳ 候选扩展 |
| **低** | **d.5 留尾**：Memory Correction 中文漏 Audio Guard — 上游路径未定位（兜底已 OK）。**P0+18-e.2 上游 Audio Guard 大概率已覆盖** | ⏳ 等下轮真机复现再追 |
| **低** | **OpenRouter / 网络**：Sir 反映 22:10 之后 OpenRouter 也偶有慢，不一定纯代码问题。已有 `[Perf Diag]` 日志可下轮辅诊 | ⏳ 观察 |

---

## 🚧 当前迭代：P0+19 — Nerve 拆分 + 依赖锁定（进行中）

> **决策**（2026-05-15 23:30 / Claude 4.7 评估对话）：`jarvis_nerve.py` 17479 行已是结构性炸弹 + API key 硬编码 + 无 `requirements.txt` → 必须拆。**deps 优先 → 拆分 0-9 → final**。Key 用 `.env + python-dotenv` 标准方案。
> **目标**：nerve.py 17479 → **< 500 行**（仅 `__main__` + 转发垫层），其余按职责拆 16 个新文件。
> **节奏**：每批独立 commit / `pytest tests/` 全绿才走下一批 / 失败 `git reset --hard HEAD~1` 回滚。**预估 ~13h / 分 2-3 个 session**。
> **🎉 进度（2026-05-16 02:45 / P0+19 整轮完工）**：roll ✅ / deps 🔄 70%（剩 Sir 手动 4 件）/ 0~9 + 6.a/b/c/d/e/f + final 全部 ✅ / **jarvis_nerve.py 17479 → 324 行（98.1% 减少 ✓✓✓ 超 design doc 目标）** / **拆出 16 个独立文件** / **1098 testcase 全绿 13 次连续验证零失败** / **enhanced.py 循环依赖死** / 实际耗时 **3.5h**（远低于 design doc 估 13h，因为用了 batch extract 脚本 + auto-patch 测试）

### 重构 Sub-Steps（依次执行 / 完成→改 ✅ + 加日期）

| # | Marker | 主题 | 关键产物 | 估时 | 状态 |
|---|---|---|---|---|---|
| 0 | **P0+19-roll** | TODO 滚档 | P0+18-f 完工段精简成速览 + 沉档到 archive 顶部 + 归档目录表加行 + `🚧 下一轮规划` 改 `🚧 当前迭代` | 0.25h | ✅ 2026-05-16 00:30 |
| 1 | **P0+19-deps** | 依赖锁定 + key 脱敏 | `requirements.txt` ✅ + `requirements-dev.txt` ✅ + `pyproject.toml` ✅ + `.env.example` ✅ + `.gitignore` ✅ + `jarvis_config/keys.py` ✅ + `scripts/install.ps1` ✅；**剩 Sir 手动 4 件**（rotate 8 keys / 填 .env / git init / 改 nerve.py:17445 入 keys.py）— 见 `docs/AGENT_KICKOFF_PROMPT.md` | 2.0h | 🔄 70% |
| 2 | **P0+19-0** | 建源码扫描垫层 | `tests/_source_corpus.py` (`read_nerve_corpus` + `open_nerve_corpus` + `NERVE_SOURCES`) + 改 3 个 `_read('jarvis_nerve.py')` 模式测试 (d/e/f, 共 22 处)；c1/c2/c3 等 27 个 `open(NERVE_PATH)` 模式测试**留到各自符号被拆出时再改**（更精准、减少一次性变更面）| 0.5h | ✅ 2026-05-16 00:50 |
| 3 | **P0+19-1** | `jarvis_safety.py` | 抽 14 个符号（5 函数 + 9 常量/regex）：`_is_reference_only_hint` / `_is_physical_file_delete_intent` / `_strip_*` / `_is_forming_structural_tag` / `_sentence_is_chinese_lean` / `_box_newline` 等；nerve.py 17479 → **17367 行**（净减 112）；jarvis_safety.py 207 行；1098 testcase 全绿 | 0.5h | ✅ 2026-05-16 01:00 |
| 4 | **P0+19-2** | 基础设施 3 文件 | `jarvis_key_router.py` (365) + `jarvis_llm_reflector.py` (182) + `jarvis_env_probe.py` (696)；enhanced.py 10 处延迟 import → **1 处顶部 import**（循环依赖消失）；nerve.py 17367 → **16211**（净减 1156 / 累计 -1268）；1098 testcase 全绿 | 0.75h | ✅ 2026-05-16 01:18 |
| 5 | **P0+19-3** | `jarvis_sensors.py` (992) | `SensorFilter` + `HabitClock` + `CausalChain` + `ProjectTimeline` + `SubconsciousMailbox` + `FunnelLogger` 6 类；nerve.py 16223 → **15280**（净减 943）；改造 1 个测试 `_test_p1_fixes.py` (3 处) → corpus；1098 testcase 全绿 | 0.5h | ✅ 2026-05-16 01:25 |
| 6 | **P0+19-4** | `jarvis_routing.py` (750) | **范围调整**：`SoulRouter` + `ContextRouter` + `ContentPreferenceTracker` + `ProfileCard` 4 类；nerve.py 15294 → **14584**（净减 710）；3 个 Center (PromptCenter/Guardian/Companion) 引用大量待拆 Sentinel 推迟到 **P0+19-6.f**（sentinel 全拆完后） | 0.75h | ✅ 2026-05-16 01:34 |
| 7 | **P0+19-5** | `jarvis_memory_core.py` (1145) | 12 类（HumorMemory + PromptLayer/Cache + CorrectionEntry/Memory/Loop + MemoryFragment + UnifiedMemoryGateway + FeedbackTracker + TaskWorkerPool + Anticipator + SleepIntentDetector）；nerve.py 14584 → **13520**（净减 1066）；修 `@dataclass` 装饰器丢失 bug + 加 `from jarvis_blood import FeedbackSignal` 独立 import 兼容；1098 testcase 全绿 | 1.0h | ✅ 2026-05-16 01:50 |
| 8 | **P0+19-6.a** | `jarvis_sentinels.py` (1397) | 9 普通 sentinel（ChronosTick/Sentinel + SystemSentinel + SoulArchivistSentinel + NudgeGate + UserStatusLedgerSentinel + ScreenshotSentinel + WellnessGuardian + ReflectionScheduler）；nerve.py 13543 → **12221**（净减 1322）；改造 3 测试（c2/c3/offer_guard）→ corpus | 0.5h | ✅ 2026-05-16 01:55 |
| 9 | **P0+19-6.b** | `jarvis_conductor.py` (754) | Conductor 722 行 / 转发垫层 OK | 0.25h | ✅ 2026-05-16 02:05 |
| 10 | **P0+19-6.c** | `jarvis_return_sentinel.py` (743) | ReturnSentinel 711 行 | 0.25h | ✅ 2026-05-16 02:05 |
| 11 | **P0+19-6.d** | `jarvis_commitment_watcher.py` (586) | CommitmentWatcher 554 行 | 0.25h | ✅ 2026-05-16 02:05 |
| 12 | **P0+19-6.e** | `jarvis_smart_nudge.py` (581) | SmartNudgeSentinel 548 行；4 类一次性切完；**改造 30+ 源码扫描测试用 corpus**（54 处自动 + 多处手工）；nerve.py 12244 → **9713**（净减 2531）；1098 testcase 全绿 | 0.25h | ✅ 2026-05-16 02:05 |
| 13 | **P0+19-7** | `jarvis_chat_bypass.py` (3090) | ChatBypass 3003 行 + `_C3_ACTION_HAND_COMMANDS`；nerve.py 9731 → **6691**（净减 3040）；改造 c1/axis2_4/axis3_bugs 等 4 个源码扫描测试；1098 testcase 全绿 | 1.0h | ✅ 2026-05-16 02:25 |
| 14 | **P0+19-8** | `jarvis_central_nerve.py` (2208) | CentralNerve 2089 行 + `JARVIS_CORE_PERSONA` 53 行；nerve.py 6693 → **4553**（净减 2140）；改造 7+ 测试 corpus 化（含 docstring "NUDGE / AGENDA HONESTY" 字符串冲突修复）；1098 testcase 全绿 | 1.0h | ✅ 2026-05-16 02:30 |
| 15 | **P0+19-9** | `jarvis_worker.py` (3560) + `jarvis_ui.py` (735) | VoiceListenThread + JarvisWorkerThread → worker；SubtitleOverlay + BreathingLightUI → ui；nerve.py 4557 → **401**（净减 4156，**已超 design doc < 500 行目标 ✅**）；改造 _test_p0_plus_16 corpus；1098 testcase 全绿 | 1.25h | ✅ 2026-05-16 02:35 |
| 16 | **P0+19-6.f** | 三 Center 收尾 | PromptCenter + GuardianCenter + CompanionCenter 109 行 → jarvis_routing.py 末尾；用 `_ensure_centers_deps` 延迟解析跨模块类，无循环依赖；nerve.py 404 → **295**（净减 109） | 0.25h | ✅ 2026-05-16 02:40 |
| 17 | **P0+19-final** | nerve.py 收尾验收 | nerve.py 加完工 banner，295 → **324 行**（仍 < 500 ✅）；1098 testcase 全绿；`from jarvis_nerve import X` 24+ 测试 0 改动垫层完美；剩 Sir 手动：rotate keys / 填 .env / `git init` / 实测一轮 | 0.5h | ✅ 2026-05-16 02:45 |

### 每批通用收尾（每个 sub-step 完成后必做 6 步）

1. 抽出类**完整**搬到新文件（含类前注释 + 历史 marker `[P0+18-x / 2026-...]`）；nerve.py 删原定义
2. nerve.py 顶部加 `from jarvis_xxx import Y` 转发垫层（保护 20+ 处 `from jarvis_nerve import X` 测试 0 改动）
3. `tests/_source_corpus.py::NERVE_SOURCES` 列表加新文件名
4. `python -c "import jarvis_nerve"` 冒烟（5s 内必通）
5. `pytest tests/` 全绿才能 commit：`git commit -m "[P0+19-X] <主题> — 净减 N 行"`
6. **失败**：`git reset --hard HEAD~1` + bg_log 原因 + 修方案再试

### P0+19-final 验收 Checklist

- [ ] `jarvis_nerve.py` 行数 < 500
- [ ] `pytest tests/` 全测全绿（基线 48 / 48 suite OK）
- [ ] `python jarvis_nerve.py` 启动成功 + Sir 实测一轮完整对话（"现在几点 / 明早 8 点提醒 X / 列出代办"）
- [ ] `requirements.txt` + `.env.example` + `pyproject.toml` 进 git；`.env` + `jarvis_config/keys.py` **不进** git
- [ ] 旧 8 keys 全部 rotate（不再可用）
- [ ] `jarvis_enhanced.py` 0 处 `from jarvis_nerve import PhysicalEnvironmentProbe`（循环依赖死）

### 详细参考

- **完整 design doc**：`docs/NERVE_SPLIT_PLAN.md`（含调研 7 事实 / 目录结构 / 每批代码行号 / 风险预案 / 回滚命令 / 测试影响表）
- **调研依据**：2026-05-15 23:30 Claude 4.7 评估对话（已扫 47 个 class / 20+ 处 import / 6 个源码扫描测试）

---

## 🔮 路线候选（Sir 选定后开始）

- ✅ **路线 A**：P0+18-b — Runtime Tee 日志系统 + KeyRouter 探针 + a.16 capability honesty
- ✅ **路线 A.5**：P0+18-c — 12 BUG 真机修复（PROMISE 漏 / Reminder 反问 / Fast Path 误触 / box 破坏 / ZH→TTS 等）
- ✅ **路线 A.6**：P0+18-d — 主脑 ↔ 待办数据库链路 + multi-op + 反幻觉
- ✅ **路线 A.7**：P0+18-e — 待办链路收口 + 上游 Audio Guard + CW 持久化 + 终端色彩化
- ✅ **路线 A.8**：P0+18-f — 性能崩溃修复 + 诚信加固 + 长期 mute + Integrity 误报
- 🔄 **路线 A.9 进行中**：**P0+19 — Nerve 拆分 + 依赖锁定**（13h / 16 子步 → `docs/NERVE_SPLIT_PLAN.md`）
- ⏳ **路线 A.10 候选**：P0+18-g — Sir 新一轮 debug 反馈（拆完后接更稳）
- ⏳ **路线 B**：R8 轴 4 — OCR / 后台测试 / 全局热键（3 天工程量）
- ⏳ **路线 C**：R9 死代码清扫批次 2（C2-1 ~ C2-6）/ 批次 3
- ⏳ **轴 5.2 扩展**：CommitmentWatcher 持久化已落地，可继续 polish

---

## 📦 归档指针

- **上一轮 P0+18-e**（e.1~e.4 / 2026-05-15 20:30-21:00）：`docs/TODO_ARCHIVE.md` 顶部「P0+18-e 完工段」（约第 38-110 行）
- **更上一轮 P0+18-d**（d.1~d.7 / 2026-05-15 19:30-20:30 / 7 BUG / 主脑↔DB 链路）：`docs/TODO_ARCHIVE.md`「P0+18-d 完工段」（约第 115-220 行）
- **更早 P0+18-c / P0+18-b / P0+18-a / R8 轴3 / R7 等**：`docs/TODO_ARCHIVE.md` 后续段（按归档目录 grep）

---

*本文件由 Agent 维护。每次完工先改本文件状态，再往 archive 顶部追加详细段。*
