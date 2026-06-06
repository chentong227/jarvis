# Known Issues — 已知挂账 BUG (诚实可见, 非静默忽略)

> 预存真 bug 的挂账台账。用 `@unittest.expectedFailure` (xfail) 而非 skip — 真 bug
> 必须可见地挂着, 修好后 xpass 会提醒摘标, 不从 _runall 静默消失。

---

## #pm-parse-12h — `_smart_parse_deadline` pm 未稳定 +12 (真 bug + 时间依赖双重)

- **发现**: 2026-06-07 (body-diff-P2 _runall) / **复核更新**: 2026-06-07 (inner-anchor _runall)
- **性质**: 预存真 BUG **+ 时间依赖**双重 (非 P2/affordance 引入)。
- **现象**: `_smart_parse_deadline('11:30pm', '', '')` 期望 `(23,30)`。解析逻辑 pm 未稳定 +12;且**结果随当前真实时钟浮动** — 某些时段恰好对、某些时段错。
- **关键教训**: 初次误标 `@unittest.expectedFailure`(以为稳定红)。但时间依赖导致它在"恰好对"时变 **xpass** → unittest `FAILED (unexpected successes=1)` → _runall 误判整 suite 红。**改用 `@unittest.skip` 无条件隔离**(不受时钟漂移影响)。
- **影响测试**: `tests/_test_p0_plus_20_beta297_timeanchor.py::...::test_explicit_pm_with_minutes`(`@unittest.skip`)
- **影响范围**: 带分钟的 pm 时间解析可能错 12 小时(随时段)。
- **修复计划**: 独立一笔 fix(非 affordance 范围):(1) pm 稳定 +12;(2) 去掉随当前时钟浮动的逻辑(应纯函数化或注入固定 now)。修好后摘 skip 标。
- **状态**: OPEN
