# JARVIS Gap 5 — L8 Reject Learner: Reflector learn to learn

> **状态**: 设计构思, 未排 sprint 编号. 时间可变.
> **关联**: `docs/JARVIS_AGENTS_GAP_ANALYSIS_2026_05_20.md` §3 Gap 5
> **依赖**: 已有 11+ L7 reflector (ConcernsReflector / WeeklyReflector→daily / SoulArchivist / SirRequestReflector / ScreenTease / Struggle / SleepPattern / CompanionRhythm / InsideJoke / Integrity), Sir review queue 机制 (concerns_review.json / relational_review.json / directive_review.json)
> **新模块**: `jarvis_reject_learner.py` + `memory_pool/reflector_self_prompt_patch.json` + L7 reflector 启动时 patch prompt

---

## 0. TL;DR — 一句话

> **L7 reflector propose vocab/concern → Sir review → 通过/拒. 但 Sir reject 后, reflector 下次仍可能 propose 同型 vocab. 加 L8 Reject Learner — 看 Sir reject 模式, LLM 抽 reject 原因, 写"reflector 自我 prompt patch", reflector 启动时 prepend, 让 reflector 真"学 Sir". 准则 6 的元升级 — 不只 LLM 决策, 还 LLM 学怎么决策得更准.**

---

## 1. 起源 / 痛点

### 1.1 Sir 真实反馈 case

`@d:\Jarvis\jarvis_relational.py:525-579` 的 `propose_thread` 代码里有 Sir 02:49 真实痛点注释:

```python
"""
🩹 [β.5.28-dedup / 2026-05-20] Sir 02:49 反馈 'review queue 重复'.
Sir 截图 'Data Alignment Milestone' / 'Implementation' / 'Integrity Milestone'
3 条几乎相同的 thread 堆 review. Root cause: 老 propose_thread 直接 add 不 dedup.
修法: title 前缀 + token jaccard 双策略 (类似 propose_inside_joke). 拒重复.
"""
```

这是 **L7 reflector 不学 Sir 拒绝模式**的症状. Sir 反复拒同型, reflector 反复 propose. Sir 累.

### 1.2 现状: review queue 是 reactive, 没 feedback loop

```
L7 reflector (e.g. SoulArchivistSentinel):
  ↓
  daemon tick (每 X min):
    扫 STM + Sir reply → LLM propose 新 inside_joke / concern / thread
  ↓
  写 review queue (concerns_review.json / relational_review.json)
  ↓
Sir CLI 看 review:
  - python scripts/concerns_dump.py --review
  - python scripts/relational_dump.py --review
  ↓
Sir activate / reject:
  - --activate <id>
  - --reject <id>
  ↓
  ⚠️ Reject 后: 仅状态变 archived. reflector 下次 propose **不学 reject 模式**.
  ↓
  Sir 看到同型再被 propose, 又 reject. 循环.
```

**根本问题**: reject 是单次操作, 不反馈给 reflector. reflector prompt 不变, 行为不变.

### 1.3 治本方向: reflector 自学 — L8

L7 = reflector LLM propose. L8 = reflector 看自己 propose 的接受/拒绝率, **LLM 抽 reject 原因 → 改 reflector 自己 prompt**.

类比: 实习生 (L7) 提议被老板 (Sir) 拒, 学习如何**更好地提议**. 这是真"学 Sir".

---

## 2. 现有 review queue 数据 (Reject Learner 的数据源)

| Review queue | 内容 | reject 信号 |
|---|---|---|
| `concerns_review.json` | L7 ConcernsReflector / WeeklyReflector propose 新 concern | Sir `--reject` |
| `relational_review.json` | L7 SoulArchivist propose inside_joke / thread | Sir `--reject` |
| `directive_review.json` | (规划中) L7 propose 新 directive | Sir `--reject` |
| `behavior_inference_vocab.json` review (β.2.9.12) | L7 propose 新 vocab | Sir 不批 |
| `commitment_conditional_vocab.json` (β.4.11) | L7 propose 软承诺 vocab | Sir 不批 |

→ **每条 reject 都是 Sir 在教 reflector**. 现在被浪费.

---

## 3. 设计 — Reject Learner + Reflector Self-Patch

### 3.1 数据流

```
Sir CLI --reject <id>:
  ↓
  现有: state → archived
  ↓
  [NEW] publish SWM 'reflector_proposal_rejected':
    {
      'reflector': 'SoulArchivistSentinel',
      'item_type': 'inside_joke',
      'item_id': 'joke_xxx',
      'item_content': {'phrase': '...', 'birth_context': '...'},
      'rejected_at': ts,
      'rejected_by': 'sir_manual',
      'reject_reason': '' (默认空, Sir 可加注解)
    }
   ↓
[NEW] RejectLearner daemon (异步, 每天 tick 1 次):
  ↓
  扫 SWM 'reflector_proposal_rejected' 最近 30 天
  ↓
  按 reflector_name + item_type group:
    e.g. {('SoulArchivistSentinel', 'shared_history_thread'): [10 条 reject]}
  ↓
  LLM judge (flash, 较深思考):
    输入: 该 reflector 该 type 最近 N 条 reject (含 item_content)
    prompt: "Sir 拒了这 N 条 proposal. 找出 reject 模式. 
             propose: reflector 下次 propose 时该避免什么?"
    输出 JSON:
      {
        'pattern_detected': '...',
        'patch_text': 'AVOID: ...',  # 短 instruction, 给 reflector prompt prepend 用
        'confidence': 0.0-1.0,
        'evidence_count': N
      }
   ↓
  写 memory_pool/reflector_self_prompt_patch.json:
    {
      'SoulArchivistSentinel': {
        'shared_history_thread': [
          {
            'patch_id': 'patch_xxx',
            'patch_text': 'AVOID propose *_Milestone 系列 thread — Sir 拒过 5 条同型',
            'evidence_count': 5,
            'confidence': 0.85,
            'created_at': ts,
            'last_validated_at': ts,
            'state': 'active'  # 'active' / 'review' / 'rejected_by_sir'
          }
        ]
      }
    }
   ↓
  写 review queue (`reflector_patch_review.json`) — Sir 拍板 patch
   ↓
  Sir --activate-patch <patch_id> → state=active
  Sir --reject-patch <patch_id> → state=rejected_by_sir
```

### 3.2 Reflector 启动时 patch prompt

```python
# Reflector base class 改:
class L7Reflector:
    def _load_self_patches(self) -> str:
        """读 reflector_self_prompt_patch.json 中本 reflector 的 active patch, 
        返回 prepend 到 LLM prompt 的字符串.
        """
        from jarvis_reject_learner import load_patches_for
        patches = load_patches_for(self.__class__.__name__)
        if not patches:
            return ''
        lines = ['[LESSONS FROM SIR (do not propose these patterns):]']
        for p in patches:
            lines.append(f"  - {p['patch_text']} (Sir rejected {p['evidence_count']}x)")
        return '\n'.join(lines) + '\n\n'
    
    def _build_llm_prompt(self, context) -> str:
        # 现有 prompt
        prompt = self._build_base_prompt(context)
        # 🆕 patch prepend
        patch_prefix = self._load_self_patches()
        return patch_prefix + prompt
```

### 3.3 关键设计原则

1. **不直接改 reflector 源码 prompt**: patch 是**runtime prepend**, 持久化, Sir 可仲裁
2. **patch 也走 review queue**: Sir 仲裁是最终, RejectLearner 自己不能直接改 reflector 行为
3. **evidence_count 必须 ≥ 3**: 防 single reject 就误学 (Sir 偶尔 reject 不代表模式)
4. **patch 跨 reflector / 跨 item_type 隔离**: 不混淆 (SoulArchivist 学的 thread 模式不影响 ConcernsReflector)
5. **patch decay**: 90 天不再验证 (e.g. 没有再 reject 同型) → 自动 archive (Sir 可能改主意了)

---

## 4. 实施层级

### Layer A — 核心 module
- 新文件: `jarvis_reject_learner.py` (~400 行)
  - `RejectLearner` daemon class
  - `_scan_recent_rejects(reflector_name, item_type, days=30)`
  - `_llm_extract_pattern(rejects) -> patch_dict`
  - `_write_patch_to_review(patch)`
  - `load_patches_for(reflector_name) -> list[active_patches]`
  - thread-safe, 异步 daemon
- 新文件: `memory_pool/reflector_self_prompt_patch.json` + `reflector_patch_review.json`
- 测试: ~12 testcase

### Layer B — Review queue 加 reject publish
- 改 `jarvis_concerns.py` reject 路径 → publish 'reflector_proposal_rejected'
- 改 `jarvis_relational.py` reject 路径 → publish
- 改 (未来) `jarvis_directives_review` reject 路径 → publish
- 改 (未来) vocab review 路径 → publish

### Layer C — Reflector base class 集成
- 改 L7Reflector base class (如果没基类, 用 mixin)
- 各 reflector 启动时 prepend patches
- 测试: 验 patch 真注入 LLM call

### Layer D — CLI 工具
- 新文件: `scripts/reflector_patch_dump.py`
  - `--review` 看 RejectLearner propose 的 patch 待审
  - `--activate-patch <id>` Sir 通过
  - `--reject-patch <id>` Sir 拒 (元 reject — 学过头了!)
  - `--list-active` 看 active patch 列表
  - `--audit <reflector>` 看某 reflector 的 patches 演化历史

### Layer E — 元自评
- RejectLearner 自己也有 review queue (Sir reject patch)
- 如果 Sir 多次 reject 同型 patch → 也学 — meta-meta-learning (L9?)
- 这是无限递归递归, **Cascade 设计建议**: 实施 Layer A-D, L9 留 future doc, 不递归

---

## 5. 准则 6 4 问 binding

| # | 问 | 本设计答 |
|---|---|---|
| 1 | 数据 publish 进 SWM? | ✅ reject event publish SWM. patch 持久化 + 也走 review queue |
| 2 | 决策让 LLM 做? | ✅ pattern 抽取全 LLM. patch 也是 LLM propose. Sir 最终仲裁 |
| 3 | 配置持久化 + CLI 可改? | ✅ reflector_self_prompt_patch.json + scripts/reflector_patch_dump.py |
| 4 | 和已有 module 正交? | ✅ 跟 L7 reflector / review queue 互补. L8 是 L7 的元层 (学 L7 的行为) |

---

## 6. 风险 & 缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| **学过头**: Sir 偶尔 reject → patch 永久压制某类 propose | 中 | 高 | 1) evidence_count ≥ 3 才 propose patch 2) 90 天 decay 3) Sir CLI --reject-patch 反向纠正 |
| **patch 之间冲突** (e.g. patch A "propose 多点 X" + patch B "少点 X") | 低 | 中 | LLM 抽 pattern 时检测冲突, 优先时间近的 |
| **reflector prompt 越来越长** (patch 累积) | 低 | 低 | active patch 最多 5 条/reflector, 老的 decay |
| **Sir 觉得 reflector "变僵"** (patch 太多导致 propose 减少) | 中 | 中 | Sir 可 CLI --clear-patches <reflector> 全清重学 |
| **L8 自己也错** (LLM 抽错 pattern) | 中 | 中 | patch 必走 review queue, Sir 仲裁 |

---

## 7. 完成验收 (Sir 真机判定)

- [ ] Sir 拒 `*_Milestone` 系列 thread 3+ 次后, RejectLearner propose patch "AVOID *_Milestone 系列"
- [ ] Sir activate patch 后, SoulArchivistSentinel 真的不再 propose 同型 (1 个月内 0 复发)
- [ ] Sir CLI --audit 看 patch 历史觉得"L8 真在学我"
- [ ] reflector review queue 容量减少 30%+ (噪音变少 → Sir 审更快)
- [ ] Sir 偶尔需要 --reject-patch (说明 L8 是真"会错", 但可纠 — 健康)

---

## 8. 与现有架构的关系

```
L7 (现有): reflector LLM propose vocab / concern / joke / thread
   ↓ review queue
Sir 仲裁: activate / reject
   ↓ activate → 系统行为变
   ↓ reject → [现有: state=archived, 仅此]
   
[NEW] L8 RejectLearner:
   ↓ 看 reject 模式, LLM 抽 pattern
   patch propose → reflector_patch_review.json
   ↓
Sir 仲裁 patch: --activate-patch / --reject-patch
   ↓ activate-patch → 写 reflector_self_prompt_patch.json (active)
   ↓ reject-patch → patch state=rejected_by_sir, 元 reject (Sir 不让 L8 学这个)
   
L7 reflector 启动:
   ↓ _load_self_patches() 拿 active patches
   ↓ prepend 到自己 LLM prompt
   ↓ 下次 propose 自然避开 Sir 拒过的模式
```

L8 是**纯增量**, 不替换任何现有 layer.

---

## 9. 跟其他 Gap 的关系

| Gap | 关系 |
|---|---|
| Gap 1 ToM | ToMReflector 也是 L7. 它的 hypothesis 被 Sir CLI 修正后, L8 学"Sir 不喜欢哪类 hypothesis" |
| Gap 2 PreFlight | PreFlight scrap verdict 也是 reject 信号 — 主脑自己 reject draft. L8 可学"哪些 draft 模式 PreFlight 总 scrap" → propose 主脑 prompt patch (Layer 之上的 L8) |
| Gap 4 Directive Self-Awareness | directive fired cluster + PreFlight verdict 是 L8 数据源. L8 可 propose "X+Y directive 组合冲突, 建议调 priority" |

---

## 10. 关键参考

- `@d:\Jarvis\jarvis_concerns.py:153-200` Concern register + review queue
- `@d:\Jarvis\jarvis_relational.py:474-620` propose_inside_joke / propose_thread + dedup (是 L8 雏形)
- `@d:\Jarvis\jarvis_llm_reflector.py:1-150` LlmReflector 共享 LLM 反思引擎 (L8 复用)
- `@d:\Jarvis\scripts\concerns_dump.py` Sir CLI 仲裁 (L8 CLI 参考其风格)
- `@d:\Jarvis\docs\JARVIS_SOUL_DRIVE.md` L4 Reflectors 总设计
- `@d:\Jarvis\AGENTS.md` 准则 6 持久化 + CLI + L7 reflector (L8 是其元升级)

---

## 11. 落地后涌现的可能 Gap

- **L9 Meta-Meta-Learner**: Sir 拒 patch 模式也学, 但**Cascade 建议不实施** — 无限递归不健康. L8 已足够
- **跨 reflector patch**: 跨多 reflector 抽共通模式 (e.g. "Sir 不喜欢被 propose 任何含 '里程碑' 字眼") → 通用 patch
- **主脑 patch**: 主脑 reply 被 PreFlight scrap 多了 → L8 propose 主脑 prompt patch (Layer 6 ToM 之上的 L8)
- **Sir 偏好画像演化**: L8 patches 综合分析 → 写 Sir 偏好元档 ("Sir 不喜欢: ...")

---

*文档作者: Sir 22:47 真授权 + Cascade 23:05 沉淀 / 2026-05-20*
*这是准则 6 的元升级, 让"LLM 决策"再上一层 — LLM 学怎么决策得更准.*
