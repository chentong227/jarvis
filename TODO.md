# Jarvis TODO 工作板

**更新时间**：2026-05-16 10:20（**🎉 P0+19 整轮完工沉档** → archive 顶部 / **🚧 P0+20-α 收尾 + P0+20-β.0 Prompt 重构启动**。今早 09:23 真机实测暴露 5 个新缺口（np import / google_1 噪音 / Integrity 误报陈述句 / TWO_PARTS 多意图失败 / dormant_project 紧贴 standby）+ Sir 与 Claude 4.7 深度对话敲定 β.0 Prompt 重构方案。详见 `docs/PROMPT_REFACTOR_PLAN.md`。）

---

## 📕 AGENT QUICKSTART（Cursor Agent 必读 / 约 30 秒）

> **唯一目的**：让 Agent 用最少的 token 读取最准确的上下文，避免 Cursor 对话超 52MB（`Append data exceeds maximum size of 52428800 bytes`）锁死。**永远不要把整个 TODO / archive / 日志读进上下文。**

### 1. 文件分工

| 文件 | 用途 | Agent 读取规则 |
|---|---|---|
| `TODO.md`（本文件，<300 行） | **当前代办 + 已知 BUG + 章程** | ✅ 每次会话进来先读这个文件 |
| `docs/TODO_ARCHIVE.md` | 已完工的迭代回溯 / 因果链 / 测试统计 | ❌ 不要默认读。**仅当 Sir 明确说"上次/上轮/R7/P0+X/轴X…"等历史关键词** → 用 `Grep` 取那段、不要 `Read` 全文 |
| `docs/PROMPT_REFACTOR_PLAN.md` | **当前迭代 P0+20-β.0 完整 design doc** | ✅ 当 Sir 说"开始 β.0" / "prompt 重构怎么搞" 时 Read |
| `docs/NERVE_SPLIT_PLAN.md` | 上轮 P0+19 拆分 design doc（已完工，保留作历史参考） | ❌ 不主动读，除非 Sir 提"拆分历史" |
| `docs/runtime_logs/jarvis_*.log` | 每次启动的完整 stdout/stderr 实时同步 | ❌ 不要 `Read` 全文。**先看 `docs/runtime_logs/latest.txt`（一行，里面是最新日志的绝对路径），再用 `Grep` 取关键段** |
| `docs/funnel_logs/funnel_*.log` | 智能轻推漏斗的命中/拒绝判定 | 同上，按需 grep |

### 2. "上次/上轮"语义映射（Sir 提到这些词的 SOP）

| Sir 的话 | Agent 该做的事 |
|---|---|
| "上次发生了什么" / "刚才那个 bug" / "前面那段" | (1) `Read docs/runtime_logs/latest.txt` 拿绝对路径；(2) `Grep` 出对应错误/Pipeline/Human 段；(3) 必要时 `Read` 文件**指定行段**（`offset+limit`，**不要全文**） |
| "上轮/上次/上回那个 BUG 修了没" / "P0+X 修了没" | (1) 先 `Grep` `TODO.md` 看是否在已知未尽；(2) 再 `Grep` `docs/TODO_ARCHIVE.md` 找最后一次出现的 marker（`a.X / P0+X / 轴X / RX`）+ 状态 |
| "重启实测/我刚跑了 N 件事" | (1) 拉最新两份 `jarvis_*.log`；(2) Grep `║ 🗣️\|║ 🤖\|⛔\|❌\|🔁` 抓对话框 + 错误；(3) 报告新 bug 时**抄日志关键行号**，不要复述大段 |

### 3. 减少 token / 避开 52MB 上限的 5 条硬规

1. **`Read` 大文件加 `offset` + `limit`**：>500 行的文件一次最多读 200 行；jarvis_chat_bypass.py 3003 行 / jarvis_central_nerve.py 2089 行**永远分段读**。
2. **优先 `Grep`**：找"某变量/某 emoji/某错误码"全用 ripgrep（Grep 工具），不要 `Read` 全文 grep。
3. **TODO 写作上限**：本 `TODO.md` 永远 ≤ 300 行；超出 250 行就把"已完成的迭代"剪到 `docs/TODO_ARCHIVE.md` 顶部。
4. **回复给 Sir 的内容**：用表格 + 行号引用，不要复制大段代码；最多 1-2 个`startLine:endLine:filepath` 引用块。
5. **新增 BUG 修复完工**：在本文件**只保留 1-2 行**说明 + marker；详细因果链/测试统计**直接进 archive 顶部**。

### 4. 完工归档协议 / 三轮滚动制（写代码后做的事）

> **核心规则：本文件永远只保留"上一轮 + 当前轮"的内容；再往前的"上上轮"必须沉到 archive。**

| 时间轴 | 位置 | 内容粒度 |
|---|---|---|
| **当前轮**（进行中） | `TODO.md` 的「当前迭代」段 | 完整任务看板 + 子步骤进度 + 在此处持续更新 |
| **上一轮**（最近一次完工） | `TODO.md` 的「上轮完工速览」段 | 1 个段落 + 关键 marker 列表 |
| **上上轮及更早** | `docs/TODO_ARCHIVE.md` 顶部 | 完整因果链 / 测试统计 / 改动清单等所有细节 |

完工时 Agent 必做 6 步：① 当前轮变上轮（精简） ② 原上轮沉档到 archive ③ archive 目录表加行 ④ 写新一轮看板（marker 连号） ⑤ 完工 commit 带 marker 注释 ⑥ 滚动后整个 TODO ≤ 300 行。

---

## 📌 上轮完工速览（P0+19 / 2026-05-16 00:30-02:45）

> 详细 17 sub-step 看板 + 调研事实 + 改动文件清单 + 测试统计 → `docs/TODO_ARCHIVE.md` 顶部「P0+19 完工段」。
> 完整 design doc → `docs/NERVE_SPLIT_PLAN.md`（保留作历史参考）。

- **起点**：`jarvis_nerve.py` 17479 行已是结构性炸弹 + API key 硬编码 + 无 `requirements.txt`，Claude 4.7 评估后决定 deps 优先 → 拆分 0-9 → final。
- **完工**：roll ✅ / deps 🔄 70%（剩 Sir 手动 4 件）/ sub-step 0-9 + 6.a/b/c/d/e/f + final 全部 ✅ / **jarvis_nerve.py 17479 → 324 行（-98.1% / 超 design doc < 500 行目标 ✓✓✓）** / 拆出 **16 个独立文件** / **1098 testcase 全绿 13 次连续验证零失败** / enhanced.py 循环依赖死。
- **关键 marker**：`P0+19-deps` / `P0+19-1` jarvis_safety / `P0+19-2` key_router+llm_reflector+env_probe / `P0+19-3` sensors / `P0+19-4` routing / `P0+19-5` memory_core / `P0+19-6.a-f` sentinels+conductor+return+commitment+smart_nudge+centers / `P0+19-7` chat_bypass(3003) / `P0+19-8` central_nerve(2089) / `P0+19-9` worker+ui / `P0+19-final`
- **测试**：1098 / 1098 testcase OK，0 FAIL
- **实际耗时**：~3.5h（vs design doc 估 13h，因为用了 batch extract 脚本 + auto-patch 测试）

---

## 🧪 Sir 重启 Jarvis 立刻可验证（≤ 6 条）

1. **TTFT 仍 3s 量级**：随便说一句 → 终端 `[Pipeline Timer] TTFT` 应 2-5s。如慢，`latest.txt` grep `[Perf Diag]` 看 connect / wait / queue_depth
2. **拆分后 import 全通**：`python -c "from jarvis_nerve import KeyRouter, ChatBypass, CentralNerve, JarvisWorkerThread, BreathingLightUI; print('ok')"`
3. **跑测**：`tests\_runall.ps1` 输出 `REGRESSION SUMMARY: 1098+ / 1098+ OK, 0 FAIL`
4. **真机一轮**：启动后跑 "现在几点 / 提醒我 8 点 X / 列出代办" 三步流，无 crash 即拆分后基线稳

---

## 🐛 已知未尽 BUG / 今早 09:23 实测暴露的新缺口

| 优先级 | BUG | 状态 | 处理路线 |
|---|---|---|---|
| **P0** | **α.1**：`[KeyRouter] google_3 标记为不健康 (错误: name 'np' is not defined)` — P0+19 拆分时 `jarvis_key_router.py` 漏 `import numpy as np` | ⏳ 待修 | **P0+20-α.1** |
| **P1** | **α.2**：每轮对话刷 5+ 行 `♻️ google_1 跳过` 噪音 — google_1 PROJECT_DENIED 但 KeyRouter 没永久剔除 | ⏳ 待修 | **P0+20-α.2** |
| **P1** | **α.3**：Integrity Check 1.5B 误报 — 陈述句 `Dreams are rarely a reliable indicator...` 被判 `no_tool_called` | ⏳ 待修 | **P0+20-α.3** + β.0.3 治本 |
| **P1** | **α.4**：Sir 刚 standby 9s 就触发 `🤫 [SilentNudge/dormant_project]` — NudgeGate cooldown 跟 SilentNudge 触发条件没对齐 | ⏳ 待修 | **P0+20-α.4** |
| **P1** | **β.0/TWO_PARTS**：Sir 一段话同时回应上文 + 开启下文时 Jarvis 只答一半（`[CONTINUITY RULE]` directive 太弱）| ⏳ 待修 | **P0+20-β.0**（Prompt 重构顺手解决）|
| **P0/手动** | **α.5**：Sir 必须做 4 件 — rotate 8 keys / 填 `.env` / `git init` / 改 jarvis_nerve.py:234-241 入口读 `load_keys()` | 🔄 Sir 在做 | Sir 手动 |
| **中** | **轴 5.2**：CommitmentWatcher 已 P0+18-e.3 持久化到 SQLite，可继续 polish（deadline 排序 / cross-session 反查）| ⏳ 候选扩展 | 路线 B+ 候选 |
| **低** | **d.5 留尾**：Memory Correction 中文漏 Audio Guard 上游路径（兜底已 OK） | ⏳ 等真机复现 | P0+18-e.2 上游 Audio Guard 大概率已覆盖 |
| **低** | **OpenRouter / 网络偶慢**：22:10 之后偶有慢，不一定纯代码问题 | ⏳ 观察 | `[Perf Diag]` 日志辅诊 |

---

## 🚧 当前迭代（双轨）：P0+20-α 收尾 + P0+20-β.0 Prompt 重构

> **节奏**：α 先做（4 个修复 + Sir 手动 4 件，~2h），完工后立刻开 β.0（设计已敲定 → `docs/PROMPT_REFACTOR_PLAN.md` / ~7h / 分 2 session）。

### 🔧 P0+20-α — 拆分收尾 + 实测暴露的 4 缺口（~2h，前置依赖）

| # | Marker | 主题 | 关键产物 | 估时 | 状态 |
|---|---|---|---|---|---|
| α.1 | **P0+20-α.1** | KeyRouter import 补全 | `jarvis_key_router.py` 顶部 `import numpy as np`；同时批量自检 16 个新文件是否还有遗漏 import | 0.25h | ⏳ |
| α.2 | **P0+20-α.2** | KeyRouter 永久剔除 | 加"3 次 PROJECT_DENIED 永久不轮转"开关 + bg_log 一次性提示 Sir 而不是每轮刷 | 0.25h | ⏳ |
| α.3 | **P0+20-α.3** | Integrity 闸门 | `detect_action_claim` 加 `is_action_claim` pre-filter（陈述/共情/解释/referential 不进 1.5B），调用量降 70% + 误报降 50% | 0.5h | ⏳ |
| α.4 | **P0+20-α.4** | dormant_project 静默期 | SmartNudgeSentinel：standby < 60s 内禁触发 SilentNudge；NudgeGate 与 SilentNudge 触发条件对齐 | 0.25h | ⏳ |
| α.5 | **P0+20-α.5** | Sir 手动 4 件 | rotate 8 keys / `Copy-Item .env.example .env` + 填 keys / `git init` + 首 commit / 改 jarvis_nerve.py:234-241 用 `load_keys()` | 0.5h | 🔄 Sir 在做 |
| α.final | **P0+20-α.final** | α 整轮验收 | 真机一轮 + 1098+ testcase 全绿 + 日志噪音清零 | 0.25h | ⏳ |

### 🧠 P0+20-β.0 — Prompt 重构 + Directive Registry（~7h，完整 design doc 在 `docs/PROMPT_REFACTOR_PLAN.md`）

> **核心目标**：prompt 30K → 18K (-40%) / `_assemble_prompt` 1274ms → < 400ms / TTFT 3.0s → 2.3-2.5s / TWO_PARTS 多意图 0/N → N/N / Integrity 误报 -50%。
>
> **架构**：四层 L0 (Immutable Core) / L1 (Session Context) / L2 (**Directive Registry**) / L3 (Task Frame)。L2 用 **`google/gemini-3-flash-preview`** 异步评分采"helped"信号 + 行为信号采"fired/rejected" + 自动衰减（30d ttl）+ Sir review 队列。
>
> **L0 走 iterate 路线**：保留现有 PERSONA 主体（butler 身份 + INTEGRITY 4 铁则），只搬迁 NUDGE/BILINGUAL/SMART_ROUTING/TOOL_USE/具体短语黑名单 → L2 Registry。

| # | Marker | 主题 | 关键产物 | 估时 | 状态 |
|---|---|---|---|---|---|
| β.0.1 | **P0+20-β.0.1** | Registry + 12 directive bootstrap | `jarvis_directives.py` (~800) + `DirectiveContext` / `Directive` / `DirectiveRegistry` + 12 条 trigger 函数 + JSON 持久化 + 新增 ~30 testcase | 2.0h | ⏳ |
| β.0.2 | **P0+20-β.0.2** | dry-run + 切低 tier | `_assemble_prompt` 顶部 dry-run 双跑 + bg_log 对比；24h 验证后切 SHORT_CHAT / WAKE_ONLY 用新机制 | 1.5h | ⏳ |
| β.0.3 | **P0+20-β.0.3** | L0 精简 + 切高 tier | PERSONA 53→25 行（iterate）+ how_to_respond 缩到 1000 chars + 切 DEEP_QUERY / TOOL_REQUEST / CRITICAL + profile_block 1509→800 | 1.0h | ⏳ |
| β.0.4 | **P0+20-β.0.4** | decay daemon + Sir review | `DirectiveDecayWorker` daemon（60s tick）+ `memory_pool/directive_review.json` + `scripts/registry_dump.py` CLI | 0.5h | ⏳ |
| β.0.5 | **P0+20-β.0.5** | Gemini-3-Flash 评分异步链 | `jarvis_directive_evaluator.py` + primary=`google/gemini-3-flash-preview` / fallback=lite / 3s timeout / 独立 evaluator key 池 / `gatekeeper_async` 集成 | 1.5h | ⏳ |
| β.0.6 | **P0+20-β.0.6** | 全测 + 真机 + dashboard | 1098+ testcase 全绿 + Sir 实测 5 次 TWO_PARTS / 5 次陈述句 + `registry.dump_human()` 验收 | 0.5h | ⏳ |

### 每批通用收尾（每个 sub-step 完成后必做 6 步）

1. 抽出/新增代码完整搬到目标文件（含历史 marker `[P0+20-α.X / P0+20-β.0.X / 2026-05-XX]`）
2. 转发垫层 / API 兼容（不破坏 `from jarvis_X import Y` 老 import）
3. `python -c "import jarvis_nerve"` 冒烟（5s 内必通）
4. `pytest tests/` 全绿才能 commit：`git commit -m "[P0+20-X.Y] <主题> — <效果>"`
5. 失败：`git reset --hard HEAD~1` + bg_log 原因 + 修方案再试
6. 完工标 ✅ + 加完工日期到本文件对应行

### P0+20-β.0 最终验收 Checklist

- [ ] `[Prompt Size]` 日志：DEEP_QUERY 总 < 19000 chars
- [ ] `[Asm Diag]` 日志：assemble 总耗时 < 450ms
- [ ] `[Pipeline Timer] TTFT`：< 2.6s
- [ ] `pytest tests/` 1098+ testcase 全绿
- [ ] **TWO_PARTS 实测**：Sir 故意说复合句 5 次，至少 4 次 Jarvis 答两段
- [ ] **Integrity 误报**：实测 5 个陈述句 / 共情句，0 次误报
- [ ] `python scripts/registry_dump.py` 输出符合预期（12 条 active + 0 review）
- [ ] `[Evaluator]` 异步评分链路 OK，bg_log 能看到 `helped=yes/no/partial`
- [ ] 拔网线测试：评分链路超时不影响主对话

---

## 🔮 路线候选（Sir 选定后开始）

- ✅ **路线 A.7**：P0+18-e — 待办链路收口 + 上游 Audio Guard + CW 持久化 + 终端色彩化
- ✅ **路线 A.8**：P0+18-f — 性能崩溃修复 + 诚信加固 + 长期 mute + Integrity 误报
- ✅ **路线 A.9**：P0+19 — Nerve 拆分（17479→324 / -98.1%）+ 依赖锁定
- 🔄 **路线 A.10 当前轨 1**：**P0+20-α** — 拆分收尾 + 4 缺口修复（np / google_1 噪音 / Integrity 闸门 / dormant 静默期）
- 🔄 **路线 A.11 当前轨 2**：**P0+20-β.0** — Prompt 重构 + Directive Registry（L0/L1/L2/L3 四层 + Gemini-3-Flash 评分）
- ⏳ **路线 B 候选**：让 PromiseExecutor 真跑长任务 — 选 3 个高价值场景（每日 9:00 驾照科一 3 题 / 起床播报 / 番茄钟）
- ⏳ **路线 B+ 候选**：AgendaLedger + DailyBriefing + WeeklyDigest + SkillsAtAGlance（让 Jarvis 从 reactive 变 goal-driven）
- ⏳ **路线 C 候选**：R8 轴 4 — OCR / 后台测试 / 全局热键
- ⏳ **路线 D 候选**：R9 死代码清扫批次 2-3 + Qwen3 本地兜底
- ⏳ **路线 E 候选 / 长期**：跨设备入口（FastAPI + WebSocket）+ 决策透明 UI + 个体演化曲线 + 关系延续证据

---

## 📦 归档指针

- **上一轮 P0+19**（roll/deps/0-9/6.a-f/final / 2026-05-16 00:30-02:45 / 17 sub-step / Nerve 17479→324 / 16 新文件 / 1098 testcase）：`docs/TODO_ARCHIVE.md` 顶部「P0+19 完工段」
- **更上一轮 P0+18-f**（f.1-f.4 / 2026-05-15 22:00-22:50 / 4 BUG / 性能崩溃修复 + 诚信加固 + 长期 mute + Integrity 误报）：`docs/TODO_ARCHIVE.md`「P0+18-f 完工段」
- **更早 P0+18-e / P0+18-d / P0+18-c / P0+18-b / R8 轴3 / R7 等**：`docs/TODO_ARCHIVE.md` 后续段（按归档目录 grep）
- **当前迭代 design doc**：`docs/PROMPT_REFACTOR_PLAN.md`（P0+20-β.0 完整设计 / 11 节 / 9 风险预案）
- **上轮 design doc**：`docs/NERVE_SPLIT_PLAN.md`（P0+19 完整设计，保留作历史参考）

---

*本文件由 Agent 维护。每次完工先改本文件状态，再往 archive 顶部追加详细段。*
