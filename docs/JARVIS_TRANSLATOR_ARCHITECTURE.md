# JARVIS Translator Architecture — LLM ↔ 系统 翻译层 (L4.6)

> **状态**: 设计构思, 未排 sprint 编号. Sir 真意验证后开工.
>
> **起源**: Sir 2026-05-24 19:49 真理: "**LLM 没有办法把我说的话翻译成我们现有架构可以理解的语言（准确的翻译）**. 大部分的 BUG 是不是来自于这里？这个是不是以后贾维斯长久运行的地基之一？"
>
> **作者**: Sir 19:49 提出 + Cascade 20:00-20:13 多轮盲点反思沉淀 / 2026-05-24
>
> **地位**: 与 **SOUL_DRIVE / INTEGRITY_STACK / β.5.0 三维耦合** 并列的第四条灵魂级架构

---

## 0. TL;DR — 一句话

> **LLM 主脑 emit (FAST_CALL / PROMISE / 等 11+ 个结构化 tag) ↔ 系统精确 schema 之间, 当前散落 60+ 处 ad-hoc fuzzy/parser/alias 治理. 加 L4.6 Translator 统一这层: 纯 python + vocab.json + L7 LLM-propose reflector + Sir CLI 拍板. 不在关键路径加新 LLM. 准则 6 三维耦合 100% 落地.**

---

## 1. 起源 / Sir 真痛点 (本 session 验证)

### 1.1 Sir 19:49 真意

> "其实我感觉现在有一个很大的问题就是 LLM 没有办法把我说的话翻译成我们现有架构可以理解的语言（准确的翻译）.
> 你认为大部分的 BUG 是不是来自于这里？（除了语法错误）
> 这个是不是以后贾维斯长久运行的地基之一？"

### 1.2 本 session 数据验证 — 6 个 BUG 5 个是翻译层问题

| BUG | 真根因 | 是翻译问题? |
|---|---|---|
| BUG #1 `reminder_hands` 幻觉 | LLM 凭语义拼 organ 名, 架构只认精确名 | ✅ **下游翻译** (LLM → schema) |
| BUG #2 `add_reminder` 缺 intent | LLM 同时问 Sir + 抢发 fast_call | ✅ **架构约束未传达** (LLM 不知"参数齐了再调") |
| BUG #3 `FAST_CALL[None/None]` | LLM 输出 malformed schema | ✅ **下游翻译** (格式错) |
| BUG-B Tool Chain 截断 | LLM 重复调 tool 不自觉 | ✅ **架构约束未传达** (LLM 不知"调过不该再调") |
| BUG-2 噪声误触发 | python 没让 LLM 看到 floor evidence | ✅ **上行翻译** (系统状态 → LLM) |
| BUG-X `set_browser_ducking` 失 import | 纯 refactor 漏 | ❌ 物理 BUG |
| BUG-A TTS GPU 累积 | cosyvoice 资源问题 | ❌ 物理 BUG |

**6 个 BUG 5 个是翻译层问题. 比例 83%**.

翻 60 天 history `P5-fix7x` (28 个) / `P0+20-βx.x` (40+ 个) 的 fix, 比例只会更高.

---

## 2. 翻译的 4 方向 + 3 层级 (定义清楚才设计)

### 2.1 翻译的 8 个方向

| # | 方向 | 例子 | 当前实力 |
|---|---|---|---|
| 1 | Sir 语音 → ASR 文本 | 麦克风 → "好第六杯了" | STT 模块, 不在 scope |
| 2 | ASR 文本 → Sir 真意 | "好第六杯了" → "Sir 喝了第 6 杯水" | 主脑 LLM 强项 |
| 3 | Sir 真意 → 系统动作 | "提醒我吃药" → `memory_hands.add_reminder` | **弱 ⚠️** (BUG 主源) |
| 4 | 系统状态 → 主脑 prompt | TTS 慢 → `[SWM] tts_render_slow` | 中 (SWM block 已做) |
| 5 | 主脑生成 → Sir 输出 | reply → TTS / 字幕 | TTS 已做 |
| 6 | 工具结果 → 主脑下轮 | tool_result 注入 | 中 (`_tool_results` 注入) |
| 7 | **LLM emit → 架构 schema** | `reminder_hands` → `memory_hands` | **最弱 ⚠️⚠️** (BUG 集中地) |
| 8 | 架构约束 → LLM 行为 | "调过 tool 不要再调" | 弱 (directive 散落 60+) |

**Sir 真痛点定位: #3 + #7 + #8 — LLM ↔ 架构 的下游 + 横向翻译**.

### 2.2 翻译的 3 个层级

| Lv | 名称 | 例子 | 谁做 |
|---|---|---|---|
| **Lv1** | 词汇翻译 (Vocabulary) | `reminder_hands` → `memory_hands` / "明天 8 点" → "2026-05-25 08:00:00" | Translator (vocab.json 查表) |
| **Lv2** | 结构翻译 (Schema/Format) | `FAST_CALL[None/None]` 拒绝 + 教重写 / 缺 intent 教先问 | Translator (manifest schema 验证) |
| **Lv3** | 意图翻译 (Intent/Semantic) | "那个文件" 上下文消歧 / "好第六杯了" 隐含主语 | 主脑 LLM (天然强项) |

**核心**: Lv1+Lv2 = 80% BUG 来源 → Translator python + vocab 解. Lv3 主脑做, 不重复造.

---

## 3. 跟现有架构关系 (Round 1 盲点反思)

### 3.1 当前已有的"翻译相关"组件 (5 个分散)

| 组件 | 方向 | 现状 | 备注 |
|---|---|---|---|
| **chat_bypass FAST_CALL fuzzy alias** | LLM emit → hand | ad-hoc, 散落 60+ 行 (`+ '_hands'` / `_lookup_organ_by_command`) | 本 session 已加雏形, 待正式化 |
| **Mutation Hub** (`jarvis_memory_gateway.py`) | LLM emit `mutation.update` → layer 路由 | 已立 (β.4.x), `_detect_target_layer` 看 field_path 前缀 → 6 layer | **跟 Translator 同方向, 但只 cover mutation organ** |
| **IntentResolver** (`jarvis_intent_resolver.py`, β.5.44) | sentinel signal → tool_calls | 已立, LLM judge | **平行方向** (sentinel emit 而非主脑 emit), 共享 tool execution layer |
| **ClaimTracer** (`jarvis_claim_tracer.py`) | reply claim → evidence | 已立 (β.4.x) | 后置审计, 跟 Translator **正交** |
| **IntegrityWatcher** (L4.5, `jarvis_integrity_watcher.py`) | reply 后 verify mutation 真完成 | 已立 (P5) | 后置主动 retry, 跟 Translator **正交** |
| **PreFlight** (Gap 2, 设计未实施) | draft reply → self-check | 未实施 | draft 文本审, 跟 Translator **正交** |
| **DirectiveSelfAwareness** (Gap 4, 设计未实施) | directive cluster → 主脑元视角 | 未实施 | prompt 装配时, 跟 Translator **互补** |

### 3.2 关键洞察 — Translator 跟 IntentResolver 的等价结构

```
┌────────────────────────────────────────────────────────────┐
│ 主脑 LLM emit FAST_CALL                                     │   ← Sir 痛点 1
└────────────┬───────────────────────────────────────────────┘
             │
             ▼
┌────────────────────────────────────────────────────────────┐
│ Translator (NEW L4.6 翻译层)                               │
│ - Lv1 organ/cmd alias (vocab.json)                         │
│ - Lv2 schema 验证 (manifest required_params)              │
│ - 失败 → actionable_msg + SWM publish                       │
└────────────┬───────────────────────────────────────────────┘
             │ TranslationResult
             ▼
┌────────────────────────────────────────────────────────────┐
│ Tool Execution Layer (HUB, 已有: hand_registry + mutation) │
│ - hand_registry → 调 hand                                   │
│ - mutation hub layer → 路由                                  │
│ - audit jsonl + SWM publish                                 │
└────────────────────────────────────────────────────────────┘
             ▲
             │ tool_call result
             │
┌────────────────────────────────────────────────────────────┐
│ IntentResolver (β.5.44, 已设计)                            │
│ - sentinel candidates → LLM judge → tool_calls plan        │
│ - publish 'intent_resolved'                                 │
└────────────────────────────────────────────────────────────┘
             ▲
             │
┌────────────────────────────────────────────────────────────┐
│ Sentinel publish_intent (β.5.0 三维耦合)                   │   ← Sir 痛点 2
│ Gatekeeper / MemCorrect / ConcernFB / 6 module             │
└────────────────────────────────────────────────────────────┘
```

**核心发现**: Translator 跟 IntentResolver 是**对称结构**:
- Translator = 主脑 emit → tool (前置 schema 翻译, python)
- IntentResolver = sentinel candidates → tool (LLM judge 决定调啥, LLM)

**共享同一个 Tool Execution Layer**. 接口对齐.

### 3.3 重叠 / 冲突 / 不破现有 验证

| 现有 module | Translator 是否破坏? | 关系 |
|---|---|---|
| Mutation Hub | ❌ 不破坏 | Translator 在 chat_bypass 路由前; mutation hub 在 hand 层. Translator alias 后 mutation hub 继续按 field_path 路由 |
| IntentResolver | ❌ 不破坏 | 平行方向, 共享 Tool Execution Layer 接口 |
| ClaimTracer | ❌ 不破坏 | reply post-hoc, Translator pre-hoc |
| IntegrityWatcher | ❌ 不破坏 | mutation post-verify, Translator emit pre-verify. **共享 mutation 类型 vocab** (8 类) |
| PreFlight (待实施) | ❌ 不破坏 | draft 文本审, Translator schema 审. **互补** |
| DirectiveSelfAwareness (待实施) | ❌ 不破坏 | prompt 装配, Translator emit 后. **互补** |

**所有正交或互补, 无冲突**.

---

## 4. Round 2 盲点反思 — 进化误伤 / Sir 冲突 / 主脑 self-game

### 4.1 盲点 A: 进化误伤 (Translator alias 错)

**场景**: Translator 把 LLM 正确 emit 错改成另一个 organ
```
LLM emit: FAST_CALL[music_hands/play]    (主脑真意: 音乐)
Translator alias: → video_hands.play     (误以为是视频)
tool 执行错 → Sir 不爽
```

**缓解**:
1. Translator alias 时 publish `translator_aliased` SWM event (含原 emit + 改后 emit)
2. 主脑下轮 prompt 看到自己被 alias 过 → 可以反对 / 不反对
3. L7 Reflector 看主脑反对率, 高 → propose vocab.json 标 status=rejected
4. Sir CLI `python scripts/translator_alias_dump.py reject alias_007` 显式拒绝

### 4.2 盲点 B: 主脑 self-game (变懒)

**风险**: 主脑学会 "用错 alias 反正会被自动改对" → 主脑变懒, 不学准确 organ 名

**缓解** (跟 PreFlight Gap 2 同型缓解):
1. Translator alias 后 SWM publish, 主脑 N 轮内看到自己被 alias 过 (鼓励 self-correct)
2. L7 Reflector 跟踪 alias 频次, 单 organ 单 alias 频次 > 阈值 → propose Sir review
3. directive 增强: "若 SWM 显示你近期被 Translator alias 过, 下次 emit 时用精确 organ 名"

### 4.3 盲点 C: Sir 显式冲突 (准则 7 元否决)

**场景**: Sir 故意 emit "错" organ 名让 jarvis 学习 ("你应该叫 `reminder_hands`")

**缓解**:
- Translator 不阻挡 Sir 自然语言, 只翻译 LLM emit
- 但 LLM 可能被 Sir 教唆 emit `reminder_hands` → translator alias → Sir 教学失败
- 解: Sir 可显式 CLI 加 directive "教学模式: skip translator alias" 或 vocab.json 加 alias

### 4.4 盲点 D: vocab 版本演化冲突

**场景**: 早期教过 "todo" = `memory_hands.add_reminder`, 后期改成 "todo" = `text_hands.create_file`

**缓解**:
- vocab.json 每条 alias 有 `version` + `superseded_by` 字段
- 同 `from` 多 `to` 时, **active 状态最新一条 win**
- 历史 alias `status=archived`, 不删 (审计需要)

### 4.5 盲点 E: Reflector LLM propose 出错

**场景**: L7 reflector LLM propose `reminder` → `text_hands` (而真意是 `memory_hands`)

**缓解**:
- propose 永远 `status='review'`, **不自动 activate**
- Sir CLI `--review` 一次性看所有 propose
- Sir `--accept alias_id` / `--reject alias_id` 显式拍板
- Reflector 看 reject 历史, 自学不再 propose 同模式 (准则 6.5 闭环)

### 4.6 盲点 F: Cross-organ 同名 command

**场景**: 两个 hand 都有 `save` command
```
memory_hands.save_memory  (记忆库)
text_hands.save_file      (写 txt, 假设)
```

LLM emit `<UNKNOWN_ORGAN>.save` 时, Translator 反向 lookup 命中 2 个 hand. 怎么选?

**方案 (按优先级)**:
1. **A 最严**: Translator 不消歧 cross-organ, 返 `error_kind='ambiguous_command'` + actionable 教 LLM emit `organ.command` 全名
2. **B 中**: 看 params (有 `intent` → memory_hands, 有 `path` → text_hands)
3. **C 宽**: vocab.json 设 `scope_default` (`save` 默认 → `memory_hands`, Sir 可改)

**推荐 A** (准则 5 言出必行, 不猜).

### 4.7 盲点 G: Translator 跟 LLM 输出 surface 范围

**当前枚举的 LLM 输出 surface (11+ 种)**:

| Surface | 用途 | Translator 范围? |
|---|---|---|
| `<FAST_CALL>JSON</FAST_CALL>` | 调 hand (tool) | ✅ **Phase 1 必做** (BUG 主源) |
| `<PROMISE>JSON</PROMISE>` | 承诺合约 (PromiseLog) | 🟡 Phase 5+ (schema 验证) |
| `<ACTIVATE_PLAN>` / `<CANCEL_PLAN>` / `<RESUME_PLAN>` | 计划状态机 | 🟡 Phase 5+ |
| `<ENGAGE_PHYSICAL_BODY>` / `<REQUEST_PHYSICAL>` / `<IGNORE>` | 主脑交互意图 | ❌ (直接 replace, 无需翻译) |
| `[CLIPBOARD]` | 剪贴板 | ❌ |
| `<AWAIT_GATEKEEPER>` | 等待 Gatekeeper | ❌ |
| `<SLEEP_CONFIRM>yes</SLEEP_CONFIRM>` (β.5.37) | sleep 确认 | 🟡 Phase 5+ (vocab alias `<confirm_sleep>` 同义) |
| `<GHOST_ACK>` / `<SILENT>` / `<STAND_DOWN>` | reaction_space | 🟡 Phase 5+ |
| 主脑 reply 内 mutation verbs ("我已记下") | ClaimTracer 抓 | ❌ (ClaimTracer 范畴) |

**Phase 1 cover FAST_CALL, 其余 Phase 5+ 渐进**.

---

## 5. Round 3 盲点反思 — 准则 1-8 全校验 + 4 问 binding

### 5.1 准则 1-8 校验

| 准则 | Translator 是否违反? | 证据 |
|---|---|---|
| §1 高效 (TTFT < 5s) | ✅ 不违反 | 纯 python + vocab cache (mtime check), < 1ms/次. 反而救 TTFT (避免主脑重试) |
| §2 反应迅速 (终端不卡) | ✅ 不违反 | 不引入 sync block. Reflector 后台 daemon |
| §3 符合人设 (butler) | ✅ 不相关 | Translator 是底层 module, 不影响主脑话术 |
| §4 懂我 (long-term memory) | ✅ 加分 | Sir 习惯 alias 学习, 主脑越来越懂 Sir |
| §5 言出必行 | ✅ 加分 | 失败 schema → actionable msg, 主脑不再撒谎"已 X". Cross-organ 同名时拒绝消歧 (准则 5 不猜) |
| §6 拒绝硬编码 + 信任 LLM | ✅ 加分 | vocab JSON + CLI + Reflector 三件套全立. 不在关键路径加 LLM (信任主脑) |
| §6.5 工程方法论 | ✅ 加分 | 持久化 + CLI + L7 Reflector LLM-propose, 三维耦合落地 |
| §7 Sir 元否决 | ✅ 加分 | Sir CLI `--accept/--reject/--list/--add` 全权拍板. Translator propose 永远 review queue |
| §8 优雅 > 简单 | ✅ 加分 | 统一散落 5+ module fuzzy logic, 准则 6 三维耦合而非 hot-fix |

**全部 ✅, 0 准则违反**.

### 5.2 准则 6 4 问 binding (新 module 引入 4 问)

| # | 问 | Translator 答 |
|---|---|---|
| 1 | 数据 publish 进 SWM? | ✅ 翻译成功 publish `translator_aliased`, 失败 publish `translator_rejected`, schema 命中 publish `translator_schema_matched`. 主脑看 SWM 自决 |
| 2 | 决策让 LLM 做? | ✅ python 只做 vocab 查 + schema 验证. LLM (主脑 / L7 reflector) 做决策. python 规则覆盖不到 (e.g. cross-organ 同名) 时拒绝, 主脑下轮 self-correct |
| 3 | 配置持久化 + CLI 可改? | ✅ `memory_pool/translator_alias_vocab.json` + `memory_pool/translator_schema_vocab.json` + `scripts/translator_alias_dump.py` + `scripts/translator_schema_dump.py` |
| 4 | 和已有 module 正交? | ✅ Round 1 §3.3 表已证明: 跟 7 个已有 module 全正交或互补, 无冲突 |

**全 Yes, 通过准则 6 4 问筛**.

---

## 6. 架构图 (设计后总图)

```
┌─────────────────────────────────────────────────────────────┐
│                  Sir 说一句话 (麦克风 → ASR 文本)           │
│                                                              │
│  ┌──────────────────────────────────────────────┐           │
│  │  主脑 LLM (Gemini, 关键路径唯一 LLM)         │           │
│  │  - Lv3 意图翻译 (主脑天然强项)               │           │
│  │  - 看 SWM block / STM / LTM / directives     │           │
│  │  - emit <FAST_CALL> / <PROMISE> / reply text │           │
│  └────────────────┬──────────────────────────────┘          │
│                   ↓                                          │
│  ┌──────────────────────────────────────────────┐           │
│  │  L4.6 Translator (NEW, 纯 python)            │           │
│  │  - 输入: organ_name, command, params         │           │
│  │  - Lv1 alias (vocab.json 查)                 │           │
│  │  - Lv2 schema 验证 (manifest 申报 required) │           │
│  │  - 失败 → actionable_msg + SWM publish       │           │
│  │  - 成功 → TranslationResult + SWM publish    │           │
│  └────────────────┬──────────────────────────────┘          │
│                   ↓                                          │
│  ┌──────────────────────────────────────────────┐           │
│  │  Tool Execution Layer (existing HUB)         │           │
│  │  - hand_registry → 调 hand                   │           │
│  │  - mutation hub → layer 路由                 │           │
│  │  - audit jsonl + SWM publish                 │           │
│  │  - tool_result → 主脑下轮 prompt 注入       │           │
│  └──────────────────────────────────────────────┘           │
│                                                              │
│  后台 (异步 daemon, 不阻塞):                                │
│  ┌──────────────────────────────────────────────┐           │
│  │  L7 TranslatorReflector (NEW, LLM 离线)      │           │
│  │  - 每 5min 扫 translator_aliased event       │           │
│  │  - 离线 LLM propose 新 alias 进 vocab review │           │
│  │  - Sir CLI 拍板 → vocab.json activate        │           │
│  └──────────────────────────────────────────────┘           │
│                                                              │
│  Sir 工具 (准则 7 元否决):                                  │
│  - scripts/translator_alias_dump.py (list/add/activate)     │
│  - scripts/translator_schema_dump.py (manifest schema)       │
└─────────────────────────────────────────────────────────────┘
```

**关键路径: 1 个 LLM (主脑) + 1 个 python translator. 后台: 1 个离线 reflector LLM. 完全符合 Sir 设计原则.**

---

## 7. 详细设计

### 7.1 接口契约 (`jarvis_translator.py`)

新文件, 类似 `jarvis_blood.py` 是底层契约:

```python
# jarvis_translator.py
from dataclasses import dataclass, field
from typing import Optional, Any
import time

@dataclass
class TranslationResult:
    """Translator 翻译结果."""
    success: bool
    organ_name: Optional[str] = None      # 翻译后精确 organ (e.g. memory_hands)
    command: Optional[str] = None         # 翻译后精确 command
    params: dict = field(default_factory=dict)  # 翻译后参数 (normalization 过)
    
    # 失败时:
    error_kind: Optional[str] = None      # unknown_organ / unknown_command / 
                                          # missing_param / invalid_format / ambiguous
    actionable_msg: Optional[str] = None  # 教 LLM 下轮 self-correct
    
    # 元数据:
    aliased_from: dict = field(default_factory=dict)  # 记录原始 LLM emit
    schema_validated: bool = False        # 是否过 Lv2 schema 验证
    translated_at: float = field(default_factory=time.time)


class Translator:
    """L4.6 LLM → 架构 schema 翻译层. 纯 python + vocab.
    
    职责:
    - Lv1 词汇 alias: organ / command 同义名 → 精确名 (vocab.json)
    - Lv2 schema 验证: 必填参数 / 格式 / 类型 (manifest required_params)
    - Lv2 actionable msg: 失败时返 LLM 能 self-correct 的 msg
    - SWM publish: translator_aliased / translator_rejected / translator_schema_matched
    
    不职责:
    - Lv3 意图翻译 (主脑做)
    - 真正执行 (Tool Execution Layer 做)
    - Cross-organ 消歧 (拒绝, 准则 5 不猜)
    """
    
    def __init__(self, hand_registry: dict, hand_manifests: dict,
                 event_bus=None, gemini_key=None):
        self.hand_registry = hand_registry
        self.hand_manifests = hand_manifests
        self.event_bus = event_bus
        self.gemini_key = gemini_key
        self._alias_vocab = None      # lazy load (mtime check)
        self._schema_vocab = None     # lazy load
        self._command_index = None    # lazy build
    
    def translate(self, organ_name: str, command: str, params: dict) -> TranslationResult:
        """主入口. 不破现有路径 — 失败时返不 success, 不抛 exception."""
        # 1. None / 空 guard
        if not organ_name or not command:
            return TranslationResult(
                success=False,
                error_kind='malformed',
                actionable_msg=(
                    "⚠️ FAST_CALL malformed — organ_name 或 command 为空. "
                    "请用完整 organ.command 格式. 若不确定 organ, 改问 Sir."
                ),
                aliased_from={'organ': organ_name, 'cmd': command},
            )
        
        # 2. Lv1 organ alias resolve (3 层 waterfall)
        resolved_organ = self._resolve_organ(organ_name, command)
        if resolved_organ is None:
            return self._make_unknown_organ_result(organ_name, command, params)
        
        # 3. Lv1 command alias resolve (organ scope 内)
        resolved_cmd = self._resolve_command(resolved_organ, command)
        if resolved_cmd is None:
            return self._make_unknown_command_result(resolved_organ, command, params)
        
        # 4. Lv1 param 归一化 (e.g. trigger_time '明天 8 点' → ISO)
        normalized_params = self._normalize_params(resolved_organ, resolved_cmd, params)
        
        # 5. Lv2 schema 验证 (manifest required_params)
        ok, err_kind, err_msg = self._validate_schema(resolved_organ, resolved_cmd, normalized_params)
        if not ok:
            return TranslationResult(
                success=False,
                organ_name=resolved_organ,
                command=resolved_cmd,
                params=normalized_params,
                error_kind=err_kind,
                actionable_msg=err_msg,
                aliased_from={'organ': organ_name, 'cmd': command, 'params': params},
            )
        
        # 6. 成功 — publish SWM event
        self._publish_translation_success(organ_name, command, resolved_organ, resolved_cmd)
        
        return TranslationResult(
            success=True,
            organ_name=resolved_organ,
            command=resolved_cmd,
            params=normalized_params,
            aliased_from={'organ': organ_name, 'cmd': command, 'params': params},
            schema_validated=True,
        )
    
    def _resolve_organ(self, organ_name: str, command: str) -> Optional[str]:
        """3 层 waterfall: 精确 → +_hands → vocab alias → 反向 command lookup."""
        # 1. 精确命中
        if organ_name in self.hand_registry:
            return organ_name
        # 2. + '_hands' 兜底
        if not organ_name.endswith('_hands'):
            aliased = organ_name + '_hands'
            if aliased in self.hand_registry:
                self._publish_aliased(organ_name, aliased, 'suffix_hands')
                return aliased
        # 3. vocab.json alias 查
        vocab_to = self._lookup_vocab(kind='organ', from_name=organ_name)
        if vocab_to and vocab_to in self.hand_registry:
            self._publish_aliased(organ_name, vocab_to, 'vocab_alias')
            return vocab_to
        # 4. 反向 command lookup
        by_cmd = self._lookup_organ_by_command(command)
        if by_cmd:
            self._publish_aliased(organ_name, by_cmd, 'by_command')
            return by_cmd
        return None
    
    def _validate_schema(self, organ: str, command: str, params: dict):
        """Lv2 schema 验证 — manifest 申报 required_params."""
        schema = self._lookup_schema_hint(organ, command)
        if not schema:
            return True, None, None  # 没 schema 定义就放过
        for req in schema.get('required_params', []):
            if req not in params or not params[req]:
                actionable = self._build_missing_param_msg(organ, command, req, schema)
                return False, 'missing_param', actionable
        return True, None, None
    
    def _build_missing_param_msg(self, organ, command, missing_param, schema):
        """生成 actionable msg, 教 LLM 下轮 self-correct."""
        examples = schema.get('examples', [])
        common_mistakes = schema.get('common_mistakes', [])
        msg = (
            f"❌ {organ}.{command} 缺 {missing_param} 参数. "
            f"下一轮: 先用自然语言问 Sir, Sir 答了再 emit FAST_CALL. 不抢发."
        )
        if examples:
            msg += f"\n正确示例: {examples[0]['fast_call']}"
        if common_mistakes:
            msg += f"\n常见错: {common_mistakes[0]}"
        return msg
    
    # ... (_lookup_vocab / _lookup_schema_hint / _lookup_organ_by_command /
    #      _normalize_params / _publish_aliased / etc. 省略)
```

### 7.2 Vocab Schema (`memory_pool/translator_alias_vocab.json`)

```json
{
  "schema_version": 1,
  "last_modified": "2026-05-25T20:00:00",
  "aliases": [
    {
      "id": "alias_001",
      "kind": "organ",
      "from": "reminder_hands",
      "to": "memory_hands",
      "status": "active",
      "evidence": "Sir 22:11 真测 / P5-fix82-Z / 2026-05-23 + Cascade BUG #1 fix 2026-05-24",
      "added_by": "L7-reflector",
      "added_at": "2026-05-24T19:30:00",
      "activated_by": "Sir",
      "activated_at": "2026-05-24T19:35:00",
      "hit_count": 0,
      "last_hit_at": null,
      "version": 1,
      "superseded_by": null
    },
    {
      "id": "alias_002",
      "kind": "command",
      "scope_organ": "memory_hands",
      "from": "remind_me",
      "to": "add_reminder",
      "status": "review",
      "evidence": "L7 reflector propose, Sir 待审"
    }
  ]
}
```

### 7.3 Schema Vocab (`memory_pool/translator_schema_vocab.json`)

```json
{
  "schema_version": 1,
  "schema_hints": [
    {
      "organ": "memory_hands",
      "command": "add_reminder",
      "required_params": ["intent", "trigger_time"],
      "param_formats": {
        "trigger_time": "YYYY-MM-DD HH:MM:00"
      },
      "param_normalization": {
        "trigger_time": "natural_language_to_iso"
      },
      "common_mistakes": [
        "没问 Sir 提醒内容时就 emit, intent 为空",
        "trigger_time 用 '明天 8 点' 而不是 ISO 格式"
      ],
      "examples": [
        {
          "scenario": "Sir 说 '8 点叫我吃药'",
          "fast_call": "FAST_CALL[memory_hands/add_reminder]{intent='吃药', trigger_time='2026-05-25 08:00:00'}"
        }
      ]
    }
  ]
}
```

### 7.4 CLI 工具 (`scripts/translator_alias_dump.py`)

```python
# 用法 (类 concerns_dump.py 风格):
python scripts/translator_alias_dump.py list                    # 全 alias
python scripts/translator_alias_dump.py list --status review    # 待审
python scripts/translator_alias_dump.py list --kind organ       # 仅 organ alias
python scripts/translator_alias_dump.py add --kind organ --from X --to Y --evidence Z
python scripts/translator_alias_dump.py activate alias_001
python scripts/translator_alias_dump.py reject alias_001
python scripts/translator_alias_dump.py archive alias_001       # 软删除, 保留审计
python scripts/translator_alias_dump.py stats                   # 看 hit_count / age
```

### 7.5 集成点 (`jarvis_chat_bypass.py`)

替换本 session 加的 ad-hoc fuzzy logic (line 3582-3637):

**Before** (现有 ad-hoc):
```python
hand_class = self.jarvis.hand_registry.get(organ_name)
if hand_class is None and not organ_name.endswith('_hands'):
    _aliased = organ_name + '_hands'
    hand_class = self.jarvis.hand_registry.get(_aliased)
    ...
if hand_class is None:
    _by_cmd = self._lookup_organ_by_command(command)
    ...
```

**After** (Translator 统一):
```python
result = self.jarvis.translator.translate(organ_name, command, params)
if not result.success:
    # actionable msg 进 tool_result, 主脑下轮看到 self-correct
    tool_result = result.actionable_msg
    exec_res = ExecutionResult(success=False, msg=result.actionable_msg)
    # bg_log + SWM publish 已在 translator 内做
    continue
organ_name, command, params = result.organ_name, result.command, result.params
hand_class = self.jarvis.hand_registry.get(organ_name)
# 后续 hand_inst.execute(Action(command, params)) 不变
```

### 7.6 L7 Reflector (`jarvis_translator_reflector.py`)

```python
class TranslatorReflector(threading.Thread):
    """每 5 min 一轮, 扫 SWM translator events, propose 新 vocab.
    
    跟 PracticeReflector / HabitVocabReflector 同型, 准则 6.5 三件套.
    """
    
    TICK_INTERVAL = 300  # 5 min
    
    def run(self):
        while not self._stop_flag.is_set():
            try:
                self._scan_and_propose()
            except Exception as e:
                bg_log(f"⚠️ [TranslatorReflector] error: {e}")
            self._stop_flag.wait(self.TICK_INTERVAL)
    
    def _scan_and_propose(self):
        # 1. 扫 SWM recent 'translator_aliased' / 'translator_rejected' events
        events = self.bus.recent_events(
            within_seconds=600,
            types={'translator_aliased', 'translator_rejected'},
        )
        if not events:
            return
        
        # 2. 离线 LLM (gemini-flash-lite, 不阻塞主对话) 分析:
        #    - 哪些 alias 是 outlier (一次性)?
        #    - 哪些是模式 (值得入 vocab)?
        #    - Sir 反对了哪些 (从 'translator_rejected' 学)?
        prompt = self._build_propose_prompt(events)
        try:
            propose = self._llm_judge(prompt)
        except Exception:
            return  # LLM 失败不阻塞, 下轮再来
        
        # 3. 写 vocab.json status='review'
        if propose.get('new_aliases'):
            self._add_to_vocab(propose['new_aliases'])
            bg_log(
                f"📚 [TranslatorReflector] propose {len(propose['new_aliases'])} "
                f"new alias to review. Sir CLI: "
                f"python scripts/translator_alias_dump.py list --status review"
            )
```

### 7.7 SWM event etype (`jarvis_utils.py`)

```python
DEFAULT_TTL = {
    ...
    'translator_aliased': 600,            # 10 min (主脑下轮看, self-correct 用)
    'translator_rejected': 1800,          # 30 min (主脑反对学习用)
    'translator_schema_matched': 60,      # 1 min (低 salience, 仅 metric)
    'translator_proposed': 86400,         # 1 day (L7 propose, Sir 审)
}
DEFAULT_SALIENCE = {
    ...
    'translator_aliased': 0.55,           # 中等 (主脑可参考)
    'translator_rejected': 0.75,          # 高 (主脑反对/学习重点)
    'translator_schema_matched': 0.20,    # 低 (仅 metric)
    'translator_proposed': 0.45,          # 中等 (Sir 看 review queue)
}
```

---

## 8. 4 Phase 落地路径 (准则 8 优雅, 不破现有)

### Phase 1 (~1 周): 接口 + 迁移现有 fuzzy

**目标**: 把本 session 加的 ad-hoc fuzzy logic 迁进 Translator, 不破现有

**步骤**:
1. 新 `jarvis_translator.py` (接口 + `_resolve_organ` + `_validate_schema`)
2. 新 `memory_pool/translator_alias_vocab.json` (seed: `reminder_hands → memory_hands`, `memory → memory_hands`)
3. 新 `memory_pool/translator_schema_vocab.json` (seed: `memory_hands.add_reminder` required params)
4. 新 `scripts/translator_alias_dump.py` (CLI list/add/activate/reject)
5. 改 `jarvis_central_nerve.py` __init__ 挂 `self.translator = Translator(...)`
6. 改 `jarvis_chat_bypass.py` 灰度: `if FEATURE_TRANSLATOR: new_path; else: old_path`
7. SWM etype 注册 (`translator_aliased` / `translator_rejected` / etc.)
8. Test: 20+ testcase (alias / schema / SWM / fail-soft)

**完成条件**:
- 现有 ad-hoc fuzzy logic 全走 Translator (功能等价)
- 全 test pass + 真测 3 天稳定才切默认 `FEATURE_TRANSLATOR=1`

### Phase 2 (~1 周): 表现 hand 补 manifest schema

**目标**: 3 个表现 hand 补 schema_vocab 让 Translator 有 Lv2 验证能力

**改 manifest 加 schema_vocab 关联**:
- `memory_hands` → required: intent + trigger_time, examples, common_mistakes
- `system_hands` → required params per command
- `ui_control` → command 白名单

**改 main prompt**: 主脑 prompt 自动列 examples + common_mistakes (从 schema_vocab 读) → 主脑少犯 BUG

**完成条件**:
- 3 个 hand schema 完整
- 主脑 prompt 注入 examples block (< 500 chars)
- 真测验 BUG #1 / BUG #2 不再发生

### Phase 3 (~1 周): L7 Reflector + 主脑 self-correct

**目标**: L7 reflector 后台 daemon + 主脑能 self-correct

**步骤**:
1. 新 `jarvis_translator_reflector.py` (后台 daemon, 5 min 一轮)
2. nerve.start_reflectors() 加 `self.translator_reflector.start()`
3. directive 加 "translator_correct_after_alias": 看 SWM `translator_aliased` event, 主脑下轮 emit 精确名
4. dashboard 加 `/translator` page 显 stats (alias 命中率 / propose 数 / Sir activate 率)

**完成条件**:
- Reflector 真扫真 propose
- Sir CLI 看 review queue 有真数据
- 主脑 self-correct 率 > 50% (alias 过的 organ 名, 下次自己用对)

### Phase 4 (~1 周): 老 fuzzy 路径物理 retire

**目标**: Phase 1-3 真测 1 周稳定 → 切单源 + 老路径删

**步骤**:
1. 删 chat_bypass 老 `+ '_hands'` fuzzy + `_lookup_organ_by_command` (Translator 已 cover)
2. `FEATURE_TRANSLATOR` flag 删, 默认全走 Translator
3. 现有 5+ 处 ad-hoc fuzzy logic 全迁完 (一处一处确认)
4. Test 跑全 regression 0 fail 才切

**完成条件**:
- chat_bypass 无 fuzzy logic (全在 Translator)
- 准则 6 全立: vocab 持久化 + CLI + reflector + 主脑 self-correct
- 真测 1 周 0 regression

**总时长**: 4 周 (1 + 1 + 1 + 1).

### Phase 5+ (未来): 扩展到其他 LLM 输出 surface

- `<PROMISE>` JSON schema 验证 (goal + steps)
- `<ACTIVATE_PLAN>` plan_id resolve
- `<SLEEP_CONFIRM>` confirmation token vocab
- 主脑 reply 内 mutation verb 跟 ClaimTracer 联动

**触发条件**: Phase 1-4 稳定 1 个月后, Sir 真测多 BUG 后启动.

---

## 9. 风险 + 缓解 (Round 2 盲点反思的强化)

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| **Translator alias 错** (误改主脑正确 emit) | 低 | 高 | SWM publish + 主脑下轮看 + Sir CLI `--reject` + Reflector 学反对 |
| **主脑 self-game** (变懒不学准确名) | 中 | 中 | SWM publish 让主脑看到自己被 alias 过 + directive 教 self-correct + L7 监控频次 |
| **L7 Reflector propose 错** | 中 | 低 | propose 永远 `status='review'`, 不自动 activate, Sir 拍板 |
| **Cross-organ 同名歧义** | 低 | 中 | 拒绝消歧, 返 `error_kind='ambiguous'` (准则 5 不猜), 教 LLM emit 全名 |
| **vocab 演化冲突** | 低 | 低 | `version` + `superseded_by` 字段, active 状态最新 win, 历史 archive 不删 |
| **vocab cache 不一致** | 低 | 低 | mtime check, CLI 改后下一秒生效 |
| **加 1 个 module 工程量** | 中 | 中 | 4 Phase 渐进, 不一次性大改. 每 Phase 独立 commit + 真测验证 |
| **Translator 自己 BUG** | 低 | 中 | 失败时不抛 exception, 返不 success 让老路径兜底 (灰度切换) |

---

## 10. 验收标准 (Sir 真测话术)

### 10.1 Phase 1 完成验收

```
1. 启动 jarvis, 看 log:
   '📚 [Translator] loaded N aliases from translator_alias_vocab.json'
   '📚 [Translator] loaded M schema hints from translator_schema_vocab.json'

2. Sir: "Jarvis, 8 点叫我吃药"
   主脑可能 emit FAST_CALL[reminder_hands/add_reminder]
   → 应见 log:
     '🔀 [Translator] alias reminder_hands → memory_hands (by_command)'
     '✅ [Translator] schema OK for memory_hands.add_reminder'
   → 提醒应真注册成功

3. 故意 Sir: "你应该用 reminder_hands"
   主脑 emit reminder_hands.add_reminder, 缺 intent
   → 应见 log:
     '🔀 [Translator] alias reminder_hands → memory_hands'
     '❌ [Translator] missing param intent for memory_hands.add_reminder'
   → tool_result 是 actionable msg, 主脑下轮先问 Sir 提醒内容

4. Sir CLI 看 vocab:
   python scripts/translator_alias_dump.py list
   → 应见 'reminder_hands → memory_hands' status=active

5. Sir CLI activate review propose:
   python scripts/translator_alias_dump.py list --status review
   → 应见 L7 reflector propose 的新 alias
   python scripts/translator_alias_dump.py activate alias_XXX
   → 该 alias 立即生效
```

### 10.2 Phase 2 完成验收

```
1. memory_hands.add_reminder 缺 intent 时:
   → actionable msg 应含 example "FAST_CALL[memory_hands/add_reminder]{intent='X', trigger_time='Y'}"
   → 主脑下轮看到 example, 真问 Sir intent 后再 emit (不抢发)

2. system_hands / ui_control 同上.

3. 主脑 prompt 应注入 [HAND SCHEMA EXAMPLES] block:
   $env:JARVIS_DEBUG_PROMPT=1; python jarvis_nerve.py
   → log 应见 prompt 末尾有 examples + common_mistakes
```

### 10.3 Phase 3 完成验收

```
1. L7 reflector 5 min 后扫:
   python scripts/translator_alias_dump.py list --status review
   → 应见 reflector propose 的新 alias

2. 主脑 self-correct 率:
   python scripts/translator_alias_dump.py stats
   → 显 alias 命中率 / hit_count / 主脑 self-correct 率
```

### 10.4 Phase 4 完成验收

```
1. grep -n "+ '_hands'" jarvis_chat_bypass.py
   → 0 命中 (老 fuzzy 已删)
2. grep -n "_lookup_organ_by_command" jarvis_chat_bypass.py  
   → 0 命中 (helper 已迁进 Translator)
3. 全 test pass + 真测 1 周 0 regression
```

---

## 11. 准则 6.5 三件套 binding (验证持久化 + CLI + Reflector)

| 准则 6.5 要求 | Translator 实现 |
|---|---|
| **持久化** | `memory_pool/translator_alias_vocab.json` + `memory_pool/translator_schema_vocab.json` |
| **CLI 可改** | `scripts/translator_alias_dump.py` (list/add/activate/reject/archive/stats) + `scripts/translator_schema_dump.py` |
| **L7 Reflector LLM-propose** | `jarvis_translator_reflector.py` (5min daemon, 离线 LLM propose, review queue) |
| **递归边界** | Translator 自己是 `< 400 行` 单文件 (准则 6.5 系统级常量), 不再下钻 |

**100% 符合准则 6.5 工程方法论**.

---

## 12. 与现有 5 灵魂级架构的关系

| 架构 | 关系 |
|---|---|
| **INTEGRITY ABSOLUTE** (PERSONA 核心) | Translator 是 INTEGRITY 的执行层 — schema 失败时 actionable msg 让主脑不撒谎说"已 X" (言出必行) |
| **SOUL_DRIVE** (β.2 灵魂工程) | 正交. SOUL 关注 Jarvis 是谁, Translator 关注 LLM emit → 系统精确翻译 |
| **INTEGRITY_STACK** (L1-L7 言出必行栈) | Translator 是 L4.6 新层, 介于 L4 (Post-emit Audit) 和 L4.5 (Active Verify+Retry, IntegrityWatcher) 之间. **emit 前 schema 验证 vs emit 后真完成验证** |
| **β.5.0 三维耦合** (数据强耦合 + 行为弱耦合 + 决策集中主脑) | Translator 100% 落地三维: 数据 publish SWM, 行为 publish-only, 决策让主脑 self-correct |
| **β.5.44 IntentResolver** (sentinel → tool 翻译) | 平行结构. Translator (主脑 emit → tool) + IntentResolver (sentinel candidate → tool) 共享 Tool Execution Layer |

**Translator 是这 5 灵魂级架构的有机补全, 不替代任何**.

---

## 13. 涌现 — Phase 5+ 未来扩展

| 扩展 | 触发 | 内容 |
|---|---|---|
| **PROMISE schema 翻译** | Phase 4 稳定 1 个月 | `<PROMISE>JSON</PROMISE>` 内 goal + steps schema 验证, 同 FAST_CALL 走 Translator |
| **reaction_space alias** | Phase 4 稳定 + reaction_space 上线 | `<SILENT>` / `<VOICE>` / `<VISUAL_PULSE>` 同义 alias |
| **Translator + ClaimTracer 联动** | Phase 5 | 主脑 reply mutation verb ("我已记下") → ClaimTracer 抓 → 反查 Translator 这轮是否真有 mutation FAST_CALL → 真没有 → 自动 INTEGRITY ALERT |
| **Sir 私域 vocab vs 通用 vocab** | Phase 6 | vocab 分层: Sir 个人习惯 → 私域. 通用 alias → 通用 (但 Jarvis 只 Sir 1 用户, 这层可能多余) |
| **Translator self-evolution** | Phase 6 | L7 reflector 学 Sir 反对模式 → 主动 propose archive 旧 alias |

---

## 14. 落地决策点 (Sir 拍板用)

### 14.1 现在 Sir 拍板什么?

**最低拍板**: 同意架构方向, 是否启动 Phase 1?

### 14.2 Phase 1 启动条件

| 选项 | 适用 | 时点 |
|---|---|---|
| **A. 立刻启动** | Sir 觉得当前 BUG 模式急需治本 | 本 session 启动 |
| **B. 真测 1 周后** | Sir 想验证本 session 已修 3 个 fast_call BUG + BUG-A/B 是否真减 | 1 周后 |
| **C. 真测 2 周后** | Sir 想充分验证 + 看真 BUG 模式新增 | 2 周后 |
| **D. 不启动, 维持现状** | Sir 觉得 ad-hoc fuzzy 够用, 维护成本可接受 | 永不 |

### 14.3 Phase 内子选项

| 子选项 | 默认 | Sir 可改 |
|---|---|---|
| FEATURE_TRANSLATOR 默认状态 | Phase 1 灰度 (`=0`), Phase 4 切默认 (`=1`) | ✅ |
| 表现 hand 数 (Phase 2) | 3 (`memory_hands` + `system_hands` + `ui_control`) | ✅ 可加 / 减 |
| Reflector tick | 5 min | ✅ Sir 可调 |
| vocab 路径 | `memory_pool/translator_*.json` | ✅ |

---

## 15. 关键参考 (本 doc 依据)

- `@d:\Jarvis\jarvis_chat_bypass.py:3582-3637` 本 session 加的 ad-hoc fuzzy + 反向 command lookup (将迁进 Translator)
- `@d:\Jarvis\jarvis_intent_resolver.py` β.5.44 IntentResolver (平行结构参考)
- `@d:\Jarvis\jarvis_memory_gateway.py` Mutation Hub layer 路由 (Translator 在它前置)
- `@d:\Jarvis\jarvis_claim_tracer.py` ClaimTracer (正交后置审计)
- `@d:\Jarvis\jarvis_integrity_watcher.py` IntegrityWatcher (L4.5 mutation 主动 retry)
- `@d:\Jarvis\docs\JARVIS_INTENT_RESOLVER_REFACTOR.md` β.5.44 sub-step
- `@d:\Jarvis\docs\JARVIS_MUTATION_INTERFACE.md` 新 source 接入 4 步 (Translator 同型)
- `@d:\Jarvis\docs\JARVIS_INTEGRITY_STACK.md` L0.5/L4/L4.5/L7 已立栈
- `@d:\Jarvis\docs\JARVIS_REPLY_PREFLIGHT.md` Gap 2 (互补, draft 后)
- `@d:\Jarvis\docs\JARVIS_DIRECTIVE_SELF_AWARENESS.md` Gap 4 (互补, prompt 装配)
- `@d:\Jarvis\docs\JARVIS_SENSOR_TO_SWM_ARCHITECTURE.md` β.5.37 三层 (Translator 在层 3 后)

---

## 16. 验收 checklist (开发者用)

完整完成 4 Phase 后:

- [ ] `jarvis_translator.py` < 400 行 (准则 6.5 边界)
- [ ] `memory_pool/translator_alias_vocab.json` + schema_vocab.json 持久化
- [ ] `scripts/translator_alias_dump.py` + schema_dump.py CLI 5+ 命令
- [ ] `jarvis_translator_reflector.py` 5 min daemon
- [ ] chat_bypass 老 fuzzy 全删
- [ ] 20+ testcase pass (alias / schema / SWM / fail-soft)
- [ ] 主脑 prompt 注入 examples block
- [ ] dashboard `/translator` page
- [ ] 真测 1 周 0 regression
- [ ] Sir 拍板 4 Phase 全通过

---

## 17. 设计沉淀

**沉淀 1**: Translator 是 LLM 时代 software 架构的**第一性问题** —
LLM emit 自然语言式 schema, 系统认精确 schema, 中间永远有 gap. 准则 6 拒绝硬编码 + 信任 LLM, 但**信任不等于盲信** — 该有翻译层兜底 + 学习.

**沉淀 2**: Translator 跟 IntentResolver 是**对称结构** —
两条 LLM emit 路径 (主脑 + sentinel) 共享同一个 Tool Execution Layer. 应该共享接口, 不重复造.

**沉淀 3**: 准则 6.5 三件套 (持久化 + CLI + Reflector) 是**通用 module 模板** —
任何新 module 都该走这个三件套. Translator 不例外.

**沉淀 4**: 不在关键路径加 LLM 是**准则 1 + 准则 6 双重要求** —
TTFT 5s 红线 + 信任主脑. 翻译层用 python + vocab, LLM 仅离线后台 (Reflector).

**沉淀 5**: Sir 元否决权 (准则 7) 永远是 final —
Translator propose / vocab 改 / Phase 启动 全 Sir 拍板. 章程不反制 Sir.

---

*文档作者: Sir 19:49 提出 + Cascade 20:00-20:13 多轮盲点反思沉淀 / 2026-05-24*
*这是 Jarvis 长久运行的**第四条灵魂级架构** (并列 SOUL_DRIVE / INTEGRITY_STACK / β.5.0 三维耦合).*
*下一 Agent 接手按 Phase 1-4 顺序推进, 不要跳序. Sir 拍板后启动.*
