# Known Issues — 已知挂账 BUG (诚实可见, 非静默忽略)

> 预存真 bug 的挂账台账。用 `@unittest.expectedFailure` (xfail) 而非 skip — 真 bug
> 必须可见地挂着, 修好后 xpass 会提醒摘标, 不从 _runall 静默消失。

---

## #pm-parse-12h — `_smart_parse_deadline` pm 未稳定 +12 (真 bug + 时间依赖双重)

- **发现**: 2026-06-07 (body-diff-P2 _runall) / **复核更新**: 2026-06-07 (inner-anchor _runall)
- **性质**: 预存真 BUG **+ 时间依赖**双重 (非 P2/affordance 引入)。
- **现象**: `_smart_parse_deadline('11:30pm', '', '')` 期望 `(23,30)`。解析逻辑 pm 未稳定 +12;且**结果随当前真实时钟浮动** — 某些时段恰好对、某些时段错。
- **关键教训**: 初次误标 `@unittest.expectedFailure`(以为稳定红)→ 时间依赖致偶发 xpass → unittest `FAILED (unexpected successes)` → _runall 抖动。中途改 `@unittest.skip` 无条件隔离。**最终方案(顾问收尾)**: 改回 `@unittest.expectedFailure` 但 **mock 模块级 `time.time` 到固定时刻(下午14:00)做成确定性** → 稳定红不偶发 xpass(连跑3次退出码稳定0),保住"修好那天 xpass 提醒摘标"的可见性。
- **根因精确**: `_smart_parse_deadline` 步骤1 hh:mm 正则(`jarvis_commitment_watcher.py:817`)匹配 `11:30` 后立即 `return _to_24h(11,30,None)` — **pm 后缀被吞、am_pm=None**,pm 没 +12。
- **影响测试**: `tests/_test_p0_plus_20_beta297_timeanchor.py::...::test_explicit_pm_with_minutes`(`@unittest.expectedFailure` + 固定时钟)
- **影响范围**: 带分钟的 pm 时间解析错 12 小时。
- **修复计划**: 独立一笔 fix(非 affordance 范围):步骤1 hh:mm 正则带上可选 am/pm 后缀并传入 `_to_24h`。修好后该 case xpass → 摘 expectedFailure 标 + 本条移到已解决。
- **状态**: OPEN
