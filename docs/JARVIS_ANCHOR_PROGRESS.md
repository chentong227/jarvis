# JARVIS 锚化 + 衡 工程 — 施工进度 (一步一记录)

> **Sir 2026-06-01 令:一步一记录,保证工程纪律。做完一大步骤开一次镜像实机测试,排查无误再下一步,直到两个立项全做完。**
>
> 两个独立立项(都要做):
> - **锚化工程**(造墙)`JARVIS_ANCHOR_DESIGN.md`:P0 / P1 / P2 / P4
> - **衡工程**(墙上权衡)`JARVIS_HENG_DESIGN.md`:H0 / H1 / H2 / H3
>
> 公理源:`JARVIS_ANCHOR_AND_BOUNDARY.md`。每步:实现 → 单测 → commit → 本文记录 → 镜像实机测 → 排查无误 → 下一步。

---

## 进度看板

| 步 | 工程 | 内容 | 单测 | 镜像验 | commit | 状态 |
|---|---|---|---|---|---|---|
| **P0** | 锚化 | anchors.json + loader + CLI(数据层,零行为) | 6/6 | ✅ | a06b872 | ✅ 完成 |
| H0 | 衡 | 发散/收敛 + 三态精确化 | - | - | - | ⏳ |
| P1 | 锚化 | 言出必行两墙 + Tracer 降级 + 拆 truth>pleasing | - | - | - | ⏳ |
| P2 | 锚化 | 灵魂层边界形 | - | - | - | ⏳ |
| H1 | 衡 | 体召唤升级(锚冲突区) | - | - | - | ⏳ |
| H2 | 衡 | 冲突裁决 + 记代价 + 河床回流 | - | - | - | ⏳ |
| H3 | 衡 | 口现场权衡 | - | - | - | ⏳ |
| P4 | 锚化 | 体算法健康(D2 merge + 模块度) | - | - | - | ⏳ |

---

## P0 — 锚数据层 (anchors.json + loader + CLI) [锚化]

**做了什么:**
- `jarvis_anchors.py`:锚数据层 + 访问器。seed(宪法默认)+ `memory_pool/anchors.json` override(mtime cache)。**override 只吃 soft_leanings/conflict_notes/organ_manifest;墙(walls)以 seed 为准,json 改不动**(锚非软,理念源 §3-公理2)。
  - helper:`get_anchors / anchor_ids / get_anchor / is_anchor_exempt / walls_of / soft_leanings_of / ensure_anchors_file / reset_cache_for_test`。
- `memory_pool/anchors.json`:2 锚持久化 —— `say_do`(言出必行:ground+keep 两墙,可检验)/ `for_sir`(灵魂层:no_betray+no_abandon 两墙,框架志向)。
- `scripts/anchors_dump.py`:CLI 只看+列墙(`--id` / `--walls`),不删墙。

**零行为消费(P0 红线守住):** 无任何运行时代码 import/调用 `jarvis_anchors`。新增模块/数据/CLI,boot 链 0 改动。`is_anchor_exempt` helper 备而未接(现无锚进任何软队列,接线是 no-op,留 P1+)。

**验收:**
- 单测 `_test_anchors_p0_sir_20260601.py` 6/6(含 T5 墙不可被 json 删/改/加)。run_id=test_20260601_110929_ce85。
- CLI `anchors_dump.py` 渲染正常(2 锚 4 墙)。
- 镜像实机:✅ **通过**。镜像 boot 干净(`mirror_voice_worker_started`,无 TypeError/无 profile 崩 = b50d76e 修生效);注入 "Hey Jarvis, are you there? Give me a one-line status." → 3.6s 正常回复 "At your service, Sir; systems are nominal and I am monitoring your progress in Cursor."。零回归确认。镜像已 kill+清。

**溯源:** charter P0 / 理念源 §2(边界)+ §3-公理2(豁免)。

---

*创建于 2026-06-01,docs(anchor): 施工进度记录。每步追加,不删历史。*
