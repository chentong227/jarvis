# Known Issues — 已知挂账 BUG (诚实可见, 非静默忽略)

> 预存真 bug 的挂账台账。用 `@unittest.expectedFailure` (xfail) 而非 skip — 真 bug
> 必须可见地挂着, 修好后 xpass 会提醒摘标, 不从 _runall 静默消失。

---

## #pm-parse-12h — `_smart_parse_deadline` pm 未稳定 +12 (真 bug + 时间依赖双重)

- **发现**: 2026-06-07 (body-diff-P2 _runall) / **复核更新**: 2026-06-07 (inner-anchor _runall)
- **性质**: 预存真 BUG **+ 时间依赖**双重 (非 P2/affordance 引入)。
- **现象**: `_smart_parse_deadline('11:30pm', '', '')` 期望 `(23,30)`。解析逻辑 pm 未稳定 +12;且**结果随当前真实时钟浮动** — 某些时段恰好对、某些时段错。
- **关键教训**: 初次误标 `@expectedFailure`(以为稳定红)→ 时间依赖致偶发 xpass。中途改 `@skip`。顾问收尾尝试**确定性 expectedFailure**(mock `time.time` 固定时刻)→ 单跑 3 次稳定红,但 **_runall 整套上下文里仍偶发 xpass**(`_to_24h`/`localtime` 等多处时间耦合,单跑稳套跑漂)→ unittest unexpected-success → 整 suite 误红。**结论: 确定性不可达** → **终态退回 `@unittest.skip`**(顾问预案: 做不到确定性则 skip 带响亮 reason + 留 KNOWN_ISSUES,别静默埋)。
- **根因精确**: `_smart_parse_deadline` 步骤1 hh:mm 正则(`jarvis_commitment_watcher.py:817`)匹配 `11:30` 后立即 `return _to_24h(11,30,None)` — **pm 后缀被吞、am_pm=None**,pm 没 +12。
- **影响测试**: `test_explicit_pm_with_minutes`(`@unittest.skip` 终态)
- **修复计划**: 独立一笔 fix:步骤1 hh:mm 正则带可选 am/pm 后缀传入 `_to_24h`。修好后摘 skip。
- **状态**: OPEN
---

## #affordance-menu-missing — 识 prompt actionable 菜单漏列 `propose_affordance` (挂账 a)

- **发现**: 2026-06-07 (锚重构第一阶段 affordance 实做收尾, TASK 5/9)
- **性质**: 设计缺口 (非 bug)。本轨**刻意只上墙+衡, 不激活 affordance** — 此缺口与该决定一致, 故意不补。
- **现象**: `propose_affordance` 的 dispatch(`jarvis_inner_thought_daemon.py:6171`)+ handler(`:6681`)已接通, 但识 LLM 的 actionable 菜单(`jarvis_inner_thought_daemon.py:4447`)**未列出 `propose_affordance` 选项** → 识 LLM 不知道该 actionable 存在 → 识无法在无人介入下自填 affordance store → affordance 块永不自动出现(store 恒空)。
- **影响**: affordance 子系统机械链路全通(store/核验闸/render/CLI/13 测全绿), 但因菜单漏列, 无自动激活入口。真盘 store 空、口/识 prompt 的 `has_affordance=False` 即此缘故。
- **修复计划**: 待独立动作(顾问/Sir 批激活 affordance 时)→ 在 `:4447` actionable 菜单加 `propose_affordance:<cap_id>[:reason]` 选项 + 走 B 端到端验。本轨不补。
- **状态**: OPEN (deferred by design)

---

## #flaky-runall-baseline — _runall 基线 ±1~2 时序偶发红 (挂账 b)

- **发现**: 2026-06-07 (墙+衡激活轨多次 _runall 观测)
- **性质**: 测试基础设施时序不稳, 非生产码 bug。
- **现象**: `tests/_runall.ps1` 全套跑时, 个别时序敏感套件(`beta44_dashboard_integrity` / `care_live` 等)偶发 ±1~2 红, 单跑则绿。蚀了"_runall 零增红"门的判定确定性 — 难以一眼区分"本笔引入的红" vs "基线 flaky 红"。
- **影响**: 收口判定需逐笔人工核对 flaky 套件名, 增加审查负担。已用"base commit 上跑 _runall 前后对比"法证过 +1 红非本轨 2 行 f-string 引入(TASK 8)。
- **修复计划**: 需独立"flaky 稳定化 / 隔离轨" — 给时序套件注入确定性时钟或 mock IO, 或移出零增红门单独跑。本轨不做。
- **状态**: OPEN

---

## #meta-arch-alignment — 重构完锚后四元架构盲点 + 优化路径对齐会 (挂账 c)

- **发现**: 2026-06-07 (锚重构第一阶段收口, TASK 9)
- **性质**: 待办事项 (非 bug), 元架构治理。
- **内容**: 锚重构第一阶段(墙+衡激活)收口后, 需开一次"四元架构盲点 + 优化路径对齐会":对账 `JARVIS_QUAD_ARCHITECTURE_SNAPSHOT.md` 现状(说/识/体/衡四档实做度)+ MIND_HENG #5/#6 待解张力 + 确认后续重构次序执行。
- **锁死的元架构重构次序**(本轨签定, 不得乱序):
  1. 先做完现列**锚重构**(墙+衡已激活 ✅ → 内在锚/affordance 后续阶段)
  2. → **河床闭环**(QUAD §4.1/§7: 记伤已做、回塑未做 → 补"伤→塑后续可塑性"闭环)**排在动态软化之前**
  3. → **接地骨架长厚**(shared 8 / said 0 → 同步推接地边增长)
  4. → 才谈**动态软化**(conflict_guidance 动态化等)
- **修复计划**: 锚重构完成后由 Sir 召集对齐会。
- **状态**: OPEN (deferred, 待锚重构完成)
