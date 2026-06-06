# Known Issues — 已知挂账 BUG (诚实可见, 非静默忽略)

> 预存真 bug 的挂账台账。用 `@unittest.expectedFailure` (xfail) 而非 skip — 真 bug
> 必须可见地挂着, 修好后 xpass 会提醒摘标, 不从 _runall 静默消失。

---

## #pm-parse-12h — `_smart_parse_deadline` pm 未 +12

- **发现**: 2026-06-07 (body-diff-P2 真机激活 _runall 重验时撞见)
- **性质**: 预存真 BUG (非 flaky, 非 body-diff-P2 引入 — 干净 HEAD 连跑同红)
- **现象**: `_smart_parse_deadline('11:30pm', '', '')` 解析成 `(11, 30)` 而非 `(23, 30)` — pm 标记未触发 +12 小时。
- **影响测试**: `tests/_test_p0_plus_20_beta297_timeanchor.py::TestSmartParseDeadlineExplicitFormats::test_explicit_pm_with_minutes` (已标 `@unittest.expectedFailure`)
- **影响范围**: 带分钟的 pm 时间 (如 "11:30pm") 解析成上午 → reminder/deadline 可能定错 12 小时。整点 pm 路径需另验。
- **根因方向**: `jarvis_commitment_watcher` (或 deadline 解析模块) 的 pm 分支对 "HH:MMpm" 格式未加 12 (整点 "11pm" 路径可能正常, 带分钟分支漏)。
- **修复计划**: 独立一笔 fix (非 P2 范围)。修好后该测试 xpass → 摘 `expectedFailure` 标 + 本条移到已解决。
- **状态**: OPEN
