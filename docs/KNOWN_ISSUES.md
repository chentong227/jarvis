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
