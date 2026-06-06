# Stash 停车记录 — prev-agent 未提交改动

> **[validation-standard §5 留痕 / 2026-06-06]**
> 用途: 记录被 stash 停车的 prev-agent 未提交改动, 防"查无 artifact"(05-31 事故教训)。
> 任何 agent / Sir 看到此文件即知有一笔停车 stash 待认领。

## 停车事实

- **stash 标签**: `prev-agent uncommitted chat_bypass/daemon/worker+vocab+docs(15.7)+2tests @c34cd2d`
- **基于 commit**: `c34cd2d` (feat body-diff-P1 grounded_only)
- **停车时间**: 2026-06-06
- **取回**: `git stash list` 找到该条 → `git stash pop`(或 `git stash apply 'stash@{N}'`)
- **原则**: 不盲提(运行时代码意图未验)、不摧弃(可能是真活, 不可逆破坏禁止)、停车等原 agent 认领。

## 停车内容 (18 项, 3 类)

| 类 | 文件 | 处理建议 |
|---|---|---|
| **运行时写回 vocab** (测试副作用, 非真编辑) | `auto_arbiter_calibration.json` / `inner_thought_propose_quality_vocab.json` / `claim_classify_vocab.json` / `evidence_requirements.json` / `llm_routing_vocab.json` / `module_map.json` / `screen_tease_vocab.json` / `sir_behavior_temporal_vocab.json` / `sir_sleep_pattern_vocab.json` / `sir_struggle_vocab.json` / `thinking_brain_ds_trigger_vocab.json` | **绝不提交** (提了=拿一次测试 run 随机态污染真机 config); pop 后大概率再被跑测写花 = 卫生债, 该 gitignore 或测试走 temp (另轨, 单记) |
| **真代码改动** (碰真机运行时) | `jarvis_chat_bypass.py` / `jarvis_inner_thought_daemon.py` / `jarvis_worker.py` | 意图未验, 绝不盲提; 原 agent 回来 review 提交 |
| **doc 半成品 + 2 新测** | `docs/AGENT_KICKOFF_BODY_DIFFERENTIATION.md` (§15.7 块) / `docs/JARVIS_ARCHITECTURE_MAP_AUTO.md` / `tests/_test_fix_sir_20260604_memory_correction_none_safe.py` / `tests/_test_fix_sir_20260606_greeting_detemplate.py` | 原 agent 认领 |

## 已知副作用 (非阻塞)

- `tests/_runall.ps1` (c34cd2d 已提交) 列表含 `_test_fix_sir_20260604_memory_correction_none_safe` + `_test_fix_sir_20260606_greeting_detemplate` 两套, 但其文件已随本 stash 停走 → 下次 `_runall` 跑到它们会 FAIL (文件缺失)。这 2 测试依赖的代码改动 (chat_bypass/daemon) 也在 stash 内, 即使保留测试文件也会红。原 agent pop 回来后这 2 测试 + 其依赖代码一并恢复, 副作用消失。
- runtime vocab pop 回来会再被跑测写花 = 独立卫生债, 不在 body-diff 轨, 单独记。

## 认领指引

原 agent (chat_bypass/daemon/worker 那轨) 回来:
1. `git stash list` 找到本条
2. `git stash pop`
3. 逐文件 review: runtime vocab **丢弃** (`git checkout HEAD -- memory_pool/<那批>.json`), 真代码 + doc + 2 测 review 后正常提交。

*本文件由 body-diff-P1 轨 agent 创建 (stash 停车留痕)。原 agent 认领提交完毕后可删。*
