# P0+19 — Jarvis Nerve 拆分 & 依赖锁定 Design Doc

**起点**：2026-05-15 23:30 / Sir 与 Claude 4.7 评估对话
**目标**：`jarvis_nerve.py` 17479 行 → < 500 行（保留 `__main__` + 转发垫层），其余按职责拆为 16 个新文件。同时锁定依赖、脱敏 API key。
**总工程量**：~13 h（含 2h 依赖锁定 + ~11h 拆分），分 12 个独立 commit。每个 commit 独立可 `git revert`。

---

## 0. TL;DR

```
P0+19-deps    依赖锁定 + .env 脱敏 + rotate keys             2.0h
P0+19-0       建 tests/_source_corpus.py 统一读源码           0.5h
P0+19-1       jarvis_safety.py（纯函数守卫）                  0.5h
P0+19-2       KeyRouter / LlmReflector / EnvProbe 3 文件      0.75h
P0+19-3       jarvis_sensors.py                                0.5h
P0+19-4       jarvis_routing.py                                0.75h
P0+19-5       jarvis_memory_core.py                            1.0h
P0+19-6       sentinels（5 子文件）                            1.5h
P0+19-7       jarvis_chat_bypass.py (3003 行)                  1.0h
P0+19-8       jarvis_central_nerve.py (2089 行)                1.0h
P0+19-9       jarvis_worker.py + jarvis_ui.py                  1.25h
P0+19-final   nerve.py 收尾 + 全测验收                         0.5h
                                                       合计  ~13.0h
```

---

## 1. 调研发现（决定拆法的 7 个关键事实）

| # | 事实 | 影响 |
|---|---|---|
| 1 | `jarvis_nerve.py` 47 个 class，7 个超 500 行（ChatBypass 3003 / JarvisWorkerThread 2807 / CentralNerve 2089 / Conductor 723 / ReturnSentinel 711 / SmartNudgeSentinel 670 / CommitmentWatcher 549） | 巨无霸 3 个必须单独成文件，不能再塞别处 |
| 2 | **enhanced.py 9 个死代码类**：`PromptCache` / `CorrectionLoop` / `UnifiedMemoryGateway` / `TaskWorkerPool` / `Anticipator` / `ContextRouter` / `ProfileCard` / `ContentPreferenceTracker` / `SoulRouter` 被 nerve.py 自己的版本取代但还留在 enhanced.py | 拆分时**不要碰这些**；P0+19 之后单独清扫批 |
| 3 | **enhanced.py 10 处** `from jarvis_nerve import PhysicalEnvironmentProbe` 延迟 import 规避循环依赖 | P0+19-2 拆完 `PhysicalEnvironmentProbe` 后，循环依赖自动消失，改回顶部 import |
| 4 | 测试 import 路径 20+ 处 `from jarvis_nerve import X`（KeyRouter / NudgeGate / Conductor / CommitmentWatcher / ChatBypass / VoiceListenThread / JarvisWorkerThread / BreathingLightUI / FeedbackTracker / _is_xxx 等） | 只要 `jarvis_nerve.py` 保留 `from xxx import X` 转发垫层，这些测试 **0 行改动** |
| 5 | 测试**源码扫描型** 6 个文件 25+ 处 `_read('jarvis_nerve.py')` 后正则扫源码 | 需建 `tests/_source_corpus.py` 拼多文件读，否则扫描断裂 |
| 6 | API key 硬编码在 `jarvis_nerve.py:17445-17452`（5 个 OpenRouter + 3 个 Google）且已进 git history | rotate 是唯一解；P0+19-deps 处理 |
| 7 | 主入口 `if __name__ == "__main__"` 在 nerve.py:17443，含 `KeyRouter` / `QApplication` / `BreathingLightUI` / `JarvisWorkerThread` / `ScreenshotSentinel` 装配 | 入口逻辑**留在 nerve.py 末尾**，避免一次动太多 |

---

## 2. 目标目录（扁平方案，无 package）

为什么不引入 `jarvis/` 包？因为目录化会让 20+ 处 `from jarvis_nerve import X` 测试瞬间红。**扁平 + 兼容垫层是最小爆炸半径**。稳定 3 周后再讨论目录化。

```
d:\Jarvis\
├── jarvis_nerve.py               # 仅 __main__ + import 转发垫层（目标 ~300 行）
├── jarvis_safety.py              # 纯函数守卫（delete/structural/audio）— P0+19-1
├── jarvis_key_router.py          # KeyRouter（含 probe_google_keys_at_startup） — P0+19-2
├── jarvis_llm_reflector.py       # LlmReflector — P0+19-2
├── jarvis_env_probe.py           # PhysicalEnvironmentProbe — P0+19-2
├── jarvis_sensors.py             # 感知/工具类（无 Thread） — P0+19-3
├── jarvis_routing.py             # 路由/三 Center — P0+19-4
├── jarvis_memory_core.py         # 记忆/纠错/睡意/幽默 — P0+19-5
├── jarvis_sentinels.py           # 普通 sentinel（< 500 行的那些） — P0+19-6
├── jarvis_conductor.py           # Conductor 723 行 — P0+19-6
├── jarvis_return_sentinel.py     # ReturnSentinel 711 行 — P0+19-6
├── jarvis_commitment_watcher.py  # CommitmentWatcher 549 行 — P0+19-6
├── jarvis_smart_nudge.py         # SmartNudgeSentinel 670 行 — P0+19-6
├── jarvis_chat_bypass.py         # ChatBypass 3003 行 — P0+19-7
├── jarvis_central_nerve.py       # CentralNerve 2089 行 + JARVIS_CORE_PERSONA — P0+19-8
├── jarvis_worker.py              # JarvisWorkerThread + VoiceListenThread + set_browser_ducking — P0+19-9
└── jarvis_ui.py                  # BreathingLightUI + SubtitleOverlay — P0+19-9
```

---

## 3. 拆分批次详情

### P0+19-deps：依赖锁定 + key 脱敏（独立、低风险、必须先做）

#### Step A：摸清现实依赖
```powershell
.\.venv\Scripts\Activate.ps1
pip freeze > requirements.frozen.txt
```
然后人工 review，把"显式 import 的"和"被依赖的依赖"分开。

#### Step B：建 `requirements.txt`（运行时） + `requirements-dev.txt`（开发）
最少含以下依赖（**版本号从 frozen 拿，不要瞎填**）：
- LLM/API：`openai>=1.50` / `google-genai>=0.4` / `httpx>=0.27` / `python-dotenv>=1.0`
- Audio：`torch` / `torchaudio` / `funasr` / `soundfile` / `pyaudio` / `numpy<2.0`
- Windows：`pywin32>=306` / `comtypes` / `pycaw` / `psutil`
- UI：`PyQt5>=5.15` / `PyOpenGL>=3.1`
- 文本：`Pillow` / `fuzzywuzzy` / `python-Levenshtein` / `colorama` / `SpeechRecognition`
- Dev：`pytest>=8.0` / `pytest-cov` / `ruff>=0.6`

CosyVoice 不在 pypi，作 git submodule 处理。

#### Step C：`pyproject.toml`
```toml
[project]
name = "jarvis-personal-butler"
version = "0.18.0"
requires-python = ">=3.9,<3.11"

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["_test_*.py", "test_*.py"]
addopts = "-q --tb=short"

[tool.ruff]
line-length = 120
exclude = ["CosyVoice/", "memory_pool/", "docs/", "asset/"]

[tool.ruff.lint]
select = ["E", "F", "W", "I"]
ignore = ["E501"]
```

#### Step D：API key 脱敏（**关键步骤**）
1. 在 OpenRouter / Google AI Studio 控制台**先新建 keys 但不删旧 keys**
2. 验证新 keys 跑得通，再删旧 keys
3. 新建 `jarvis_config/keys.py`（**入 .gitignore**）：
```python
import os
from dataclasses import dataclass

@dataclass
class JarvisKeys:
    OPENROUTER_MAIN: str
    OPENROUTER_LIST: list
    GEMINI: str
    GOOGLE_LIST: list

def load_keys() -> JarvisKeys:
    from dotenv import load_dotenv
    load_dotenv()
    return JarvisKeys(
        OPENROUTER_MAIN=os.environ["OPENROUTER_MAIN"],
        OPENROUTER_LIST=[os.environ[f"OPENROUTER_{i}"] for i in range(2, 6)],
        GEMINI=os.environ["GEMINI_KEY"],
        GOOGLE_LIST=[
            os.environ["GEMINI_KEY"],
            os.environ["GOOGLE_KEY_2"],
            os.environ["GOOGLE_KEY_3"],
        ],
    )
```
4. 新建 `.env`（**入 .gitignore**）+ `.env.example`（进 git）：
```
OPENROUTER_MAIN=sk-or-v1-...
OPENROUTER_2=sk-or-v1-...
OPENROUTER_3=sk-or-v1-...
OPENROUTER_4=sk-or-v1-...
OPENROUTER_5=sk-or-v1-...
GEMINI_KEY=AIzaSy...
GOOGLE_KEY_2=AIzaSy...
GOOGLE_KEY_3=AIzaSy...
```
5. **修改** `jarvis_nerve.py:17443-17479` 入口，把硬编码 key 改成 `load_keys()`

#### Step E：`.gitignore` 增量
```
# === Secrets ===
.env
jarvis_config/keys.*.json
jarvis_config/sir_profile.json   # 含 sir 个人信息，确认下要不要排除

# === Runtime ===
memory_pool/*.db
memory_pool/*.db-shm
memory_pool/*.db-wal
docs/runtime_logs/
docs/funnel_logs/

# === Python ===
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
.venv/
```

#### Step F：一键安装脚本 `scripts/install.ps1`
（详见上一轮对话末尾，省略）

#### 验收
- `pip install -r requirements-dev.txt` 干净通过
- 删 `.env` 后 `python jarvis_nerve.py` 抛清晰错误（不是 KeyError 而是友好 message）
- `git log -p -S 'sk-or-v1' -- jarvis_nerve.py` 仍能看到旧 key，但**旧 key 已 rotate**所以已失效

---

### P0+19-0：建 corpus helper（热身、零业务风险）

新建 `tests/_source_corpus.py`：
```python
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NERVE_SOURCES = [
    'jarvis_nerve.py',
    # P0+19-1 后追加 jarvis_safety.py
    # P0+19-2 后追加 jarvis_key_router.py / jarvis_llm_reflector.py / jarvis_env_probe.py
    # ... 每批拆完即往这里加一行
]

def read_source(rel: str) -> str:
    with open(os.path.join(ROOT, rel), 'r', encoding='utf-8') as f:
        return f.read()

def read_nerve_corpus() -> str:
    """读"原 jarvis_nerve.py 涉及的所有文件"，拼接返回。
    供 _test_p0_plus_18_d_brain_db_link.py 等源码扫描型测试用。
    每次拆分一批 → 在 NERVE_SOURCES 加一行 → 扫描行为等价不变。"""
    return '\n# === FILE BOUNDARY ===\n'.join(read_source(p) for p in NERVE_SOURCES)
```

改 6 个测试：
- `_test_p0_plus_18_d_brain_db_link.py`：13 处 `_read('jarvis_nerve.py')` → `read_nerve_corpus()`
- `_test_p0_plus_18_e_link_close.py`：5 处
- `_test_p0_plus_18_c1_promise_leak.py`：1 处
- `_test_p0_plus_18_c2_reminder_firing.py`：1 处
- `_test_p0_plus_18_c3_to_c14_remaining.py`：1 处
- `_test_p0_plus_18_f_perf_and_honesty.py`：3 处

跑 `pytest tests/` 应该全绿（此时 corpus 只读一个文件，行为等价）。

---

### P0+19-1：jarvis_safety.py（最小批，验通工具链）

#### 抽出（nerve.py 中的纯函数 + 常量）
- `_REFERENCE_TOKENS` (nerve.py:124)
- `_strip_reference_tokens` (nerve.py:134)
- `_is_reference_only_hint` (nerve.py:142)
- `_PHYSICAL_FILE_DELETE_MARKERS` (nerve.py:164)
- `_is_physical_file_delete_intent` (nerve.py:185)
- `_box_newline` (nerve.py:6448)
- `_strip_structural_tag_blocks` (nerve.py:6507)
- `_strip_structural_tags_only` (nerve.py:6514)
- `_is_forming_structural_tag` (nerve.py:6519)
- `_sentence_is_chinese_lean` (nerve.py:6540)
- `_STRUCTURAL_TAGS` 常量（搜出位置）
- `_CHINESE_CHAR_RE` 常量

#### nerve.py 留转发
```python
from jarvis_safety import (
    _REFERENCE_TOKENS, _strip_reference_tokens, _is_reference_only_hint,
    _PHYSICAL_FILE_DELETE_MARKERS, _is_physical_file_delete_intent,
    _box_newline, _strip_structural_tag_blocks, _strip_structural_tags_only,
    _is_forming_structural_tag, _sentence_is_chinese_lean,
    _STRUCTURAL_TAGS, _CHINESE_CHAR_RE,
)
```

#### corpus 更新
`NERVE_SOURCES` 加 `'jarvis_safety.py'`

#### 验收
- `pytest tests/` 全绿（1044 testcase）
- 影响的 4 个测试 `from jarvis_nerve import _xxx` **0 行改动**

---

### P0+19-2：KeyRouter / LlmReflector / PhysicalEnvironmentProbe

#### 抽出
- `KeyRouter` (nerve.py:219-557) → `jarvis_key_router.py`
- `LlmReflector` (nerve.py:557-710) → `jarvis_llm_reflector.py`
- `PhysicalEnvironmentProbe` (nerve.py:710-1371) → `jarvis_env_probe.py`

#### nerve.py 留转发 + 删除原类
```python
from jarvis_key_router import KeyRouter
from jarvis_llm_reflector import LlmReflector
from jarvis_env_probe import PhysicalEnvironmentProbe
```

#### **副作业**：消除 enhanced.py 的循环依赖
`jarvis_enhanced.py` 的 10 处：
```python
from jarvis_nerve import PhysicalEnvironmentProbe   # 函数内延迟 import
```
全部改成顶部统一 import：
```python
from jarvis_env_probe import PhysicalEnvironmentProbe   # 顶部，循环依赖消失
```

#### corpus 更新
`NERVE_SOURCES` 加 3 个新文件

#### 验收
- `pytest tests/` 全绿
- `_test_p0_plus_18_c5_embed_rotation.py:61` `from jarvis_nerve import KeyRouter` **0 改动**
- `python -c "import jarvis_enhanced; print('ok')"` 无循环依赖警告

---

### P0+19-3：jarvis_sensors.py

#### 抽出（无 Thread 子类的工具类）
- `SensorFilter` (nerve.py:1448-1715)
- `HabitClock` (nerve.py:1715-1943)
- `CausalChain` (nerve.py:1943-2135)
- `ProjectTimeline` (nerve.py:2135-2280)
- `SubconsciousMailbox` (nerve.py:2280-2317)
- `FunnelLogger` (nerve.py:1371-1448)

#### 测试影响
无（这些类未被 `from jarvis_nerve import` 直接引用）

---

### P0+19-4：jarvis_routing.py

#### 抽出
- `PromptCenter` (nerve.py:3661-3696)
- `GuardianCenter` (nerve.py:3696-3745)
- `CompanionCenter` (nerve.py:3745-3771)
- `SoulRouter` (nerve.py:9595-9731)
- `ContextRouter` (nerve.py:9731-9824)
- `ContentPreferenceTracker` (nerve.py:9824-10030)
- `ProfileCard` (nerve.py:10030-10307)

#### 注意
这一批和 `jarvis_enhanced.py` 重复！`enhanced.py` 里的 `SoulRouter` / `ContextRouter` / `ContentPreferenceTracker` / `ProfileCard` 是死代码。**仍然只搬 nerve.py 的版本**，enhanced.py 不动。

---

### P0+19-5：jarvis_memory_core.py

#### 抽出
- `PromptLayer` (nerve.py:10307-10318)
- `PromptCache` (nerve.py:10318-10359)
- `CorrectionEntry` (nerve.py:10359-10369)
- `CorrectionMemory` (nerve.py:10369-10513)
- `MemoryFragment` (nerve.py:10513-10522)
- `UnifiedMemoryGateway` (nerve.py:10522-10642)
- `FeedbackTracker` (nerve.py:10642-10707)
- `TaskWorkerPool` (nerve.py:10707-10756)
- `Anticipator` (nerve.py:10756-10853)
- `CorrectionLoop` (nerve.py:10853-10936)
- `SleepIntentDetector` (nerve.py:10936-11197)
- `HumorMemory` (nerve.py:5734-5922)

#### 测试影响
- `_test_p0_plus_deep_audit_fixes.py:377` `from jarvis_nerve import FeedbackTracker` **0 改动**

---

### P0+19-6：sentinel 五子文件

#### Sub-step 6.a：jarvis_sentinels.py（普通 sentinel）
- `ChronosTick` (nerve.py:2317-2557)
- `ChronosSentinel` (nerve.py:2557-2600)
- `SystemSentinel` (nerve.py:2600-2656)
- `SoulArchivistSentinel` (nerve.py:2656-2810)
- `NudgeGate` (nerve.py:2810-2938)
- `UserStatusLedgerSentinel` (nerve.py:3771-4149)
- `ScreenshotSentinel` (nerve.py:4149-4207)
- `WellnessGuardian` (nerve.py:4207-4275)
- `ReflectionScheduler` (nerve.py:4275-4474)

#### Sub-step 6.b：jarvis_conductor.py
- `Conductor` (nerve.py:2938-3661) — 723 行

#### Sub-step 6.c：jarvis_return_sentinel.py
- `ReturnSentinel` (nerve.py:4474-5185) — 711 行

#### Sub-step 6.d：jarvis_commitment_watcher.py
- `CommitmentWatcher` (nerve.py:5185-5734) — 549 行

#### Sub-step 6.e：jarvis_smart_nudge.py
- `SmartNudgeSentinel` (nerve.py:5922-6592) — 670 行

#### 关键技巧
sentinel 之间相互引用密度高（如 `Conductor` 持有 `NudgeGate`）。**用构造注入而非 module-level import**：
```python
class Conductor(threading.Thread):
    def __init__(self, nudge_gate, central_nerve, ...):
        self.nudge_gate = nudge_gate
        ...
```
这一步如果有跨 sentinel 引用打破不了，**回滚那一子步，整批保留**。

#### 测试影响
- `_test_p2_refusal_and_audio.py:30/237/274/308` / `_test_p1_fixes.py:36` / `_test_v5_sleep_intent.py:191/227/275` / `_test_p0_plus_17_commitment_startup_guard.py:114/157` / `test_three_centers.py:388/399/421` 全部 **0 改动**（垫层 OK）

---

### P0+19-7：jarvis_chat_bypass.py（3003 行单刀）

#### 排在 P0+19-6 之后的原因
ChatBypass 内部调 `KeyRouter` / `PhysicalEnvironmentProbe` / 多个 Sentinel —— 这些都已在前批出去，import 路径已清晰。

#### 操作步骤
1. **先 grep**：`Grep "central_nerve\." in jarvis_nerve.py:6592-9595` 列所有反向调用
2. 把 ChatBypass 搬到新文件
3. nerve.py 留 `from jarvis_chat_bypass import ChatBypass`
4. 跑 `_test_p0_plus_18_c1_promise_leak.py` / `_test_axis2_4_local_phrase_pool.py` / `_test_r7_beta2_backchannel.py` 验证

#### 测试影响
- 3 个测试 `from jarvis_nerve import ChatBypass` **0 改动**

---

### P0+19-8：jarvis_central_nerve.py（2089 行）

#### 抽出
- `CentralNerve` (nerve.py:11197-13286)
- `JARVIS_CORE_PERSONA` 字符串常量 (nerve.py:54-106)

#### 关键
CentralNerve 持有所有 sentinel 引用，必须排在 6/7 后。

#### 测试影响
- `test_three_centers.py:297` `from jarvis_nerve import CentralNerve` **0 改动**

---

### P0+19-9：jarvis_worker.py + jarvis_ui.py

#### 抽出（worker）
- `VoiceListenThread` (nerve.py:13286-13944)
- `JarvisWorkerThread` (nerve.py:13944-16751)
- `set_browser_ducking` (nerve.py:13203)
- 内部辅助函数若干

#### 抽出（ui）
- `SubtitleOverlay` (nerve.py:16751-17164)
- `BreathingLightUI` (nerve.py:17164-17442)

#### 测试影响
- `_test_axis1_5_visual_pulse.py:79` / `_test_r6_bus_and_tier.py:104/164/219` / `_test_v5_sleep_intent.py:90` / `_test_axis1_6_unicode_safe_print.py:112/150` 全部 **0 改动**

---

### P0+19-final：nerve.py 收尾

#### 目标结构（~300 行）
```python
"""[P0+19 / 2026-05-XX] 拆分完工：本文件曾 17479 行，现仅余 __main__ + import 转发垫层。
新代码请直接 from jarvis_xxx import Y，不要再往 nerve.py 加东西。"""
import multiprocessing, sys
from PyQt5.QtWidgets import QApplication

# === 转发垫层（保持旧 `from jarvis_nerve import X` 测试无改动） ===
from jarvis_safety import *
from jarvis_key_router import KeyRouter
from jarvis_llm_reflector import LlmReflector
from jarvis_env_probe import PhysicalEnvironmentProbe
from jarvis_sensors import (SensorFilter, HabitClock, CausalChain,
                            ProjectTimeline, SubconsciousMailbox, FunnelLogger)
from jarvis_routing import (PromptCenter, GuardianCenter, CompanionCenter,
                            SoulRouter, ContextRouter, ContentPreferenceTracker, ProfileCard)
from jarvis_memory_core import (PromptLayer, PromptCache, CorrectionEntry,
                                CorrectionMemory, MemoryFragment, UnifiedMemoryGateway,
                                FeedbackTracker, TaskWorkerPool, Anticipator,
                                CorrectionLoop, SleepIntentDetector, HumorMemory)
from jarvis_sentinels import (ChronosTick, ChronosSentinel, SystemSentinel,
                              SoulArchivistSentinel, NudgeGate,
                              UserStatusLedgerSentinel, ScreenshotSentinel,
                              WellnessGuardian, ReflectionScheduler)
from jarvis_conductor import Conductor
from jarvis_return_sentinel import ReturnSentinel
from jarvis_commitment_watcher import CommitmentWatcher
from jarvis_smart_nudge import SmartNudgeSentinel
from jarvis_chat_bypass import ChatBypass
from jarvis_central_nerve import CentralNerve, JARVIS_CORE_PERSONA
from jarvis_worker import JarvisWorkerThread, VoiceListenThread, set_browser_ducking
from jarvis_ui import BreathingLightUI, SubtitleOverlay
from jarvis_blood import FeedbackSignal

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from jarvis_config.keys import load_keys
    keys = load_keys()
    
    key_router = KeyRouter(
        main_brain_key=keys.OPENROUTER_MAIN,
        google_keys=keys.GOOGLE_LIST,
        openrouter_keys=keys.OPENROUTER_LIST,
    )
    key_router.probe_google_keys_at_startup(async_mode=True)
    
    app = QApplication(sys.argv)
    ui = BreathingLightUI()
    ui.show()
    
    jarvis_worker = JarvisWorkerThread(
        api_key=keys.OPENROUTER_MAIN,
        gemini_key=keys.GEMINI,
        key_router=key_router,
    )
    jarvis_worker.state_changed.connect(ui.change_state)
    jarvis_worker.start()
    
    subtitle_overlay = SubtitleOverlay(ui)
    jarvis_worker.jarvis.chat_bypass.subtitle_queue = subtitle_overlay.subtitle_queue
    jarvis_worker.subtitle_overlay = subtitle_overlay
    
    ScreenshotSentinel().start()
    sys.exit(app.exec_())
```

#### 最终验收
1. `jarvis_nerve.py` 行数 < 500
2. `pytest tests/` 1044 testcase 全绿
3. `python jarvis_nerve.py` 启动成功，Sir 实测一轮完整对话（"现在几点 / 提醒我明天早上 8 点做某事 / 列出代办"）
4. `requirements.txt` + `.env.example` + `pyproject.toml` 进 git；旧 keys 全部 rotate
5. `jarvis_enhanced.py` 0 处 `from jarvis_nerve import PhysicalEnvironmentProbe`（循环依赖死）
6. 写一段 P0+19 上轮速览到 `TODO.md`，沉档 P0+18-d 到 `docs/TODO_ARCHIVE.md`

---

## 4. 风险表 & 回滚预案

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 抽类时漏抓某个模块级常量（如 `_CHINESE_CHAR_RE`）→ ImportError | 中 | 启动失败 | 每批后立刻 `python -c "import jarvis_nerve"` 冒烟，再跑全测 |
| ChatBypass 内部用 `self.central_nerve.xxx` 反向引用，拆出去后顺序错乱 | 中 | AttributeError | 拆前先 grep `central_nerve\.` 列清所有反向调用，转构造注入 |
| Sentinel 互引用（Conductor 持 NudgeGate）→ 循环 import | 中 | 跑时 ImportError | 用构造注入而非 module import |
| 测试源码扫描型批改测试逻辑变了 | 低 | 测试错过 bug | P0+19-0 引入 corpus helper 是**行为等价**改造，0 业务逻辑变化 |
| Rotate API key 时旧 key 还在跑 → 通信中断 | 高 | 当下不能用 | 在控制台先新建 key 但不删旧，验通新 key 后再删旧 |
| Git history 含旧 key | 取决于公开/私库 | 私库无影响 | 私库无所谓；如果公开过用 `git filter-repo` 或 BFG 清史 |

**回滚**：每批是独立 commit，`git revert <commit>` 即可。即使第 7 批失败，前 6 批成果保留。

---

## 5. 工程量预估 & 落地建议

| 阶段 | 估时 | 累计 |
|---|---|---|
| P0+19-deps | 2.0h | 2.0h |
| P0+19-0 | 0.5h | 2.5h |
| P0+19-1 | 0.5h | 3.0h |
| P0+19-2 | 0.75h | 3.75h |
| P0+19-3 | 0.5h | 4.25h |
| P0+19-4 | 0.75h | 5.0h |
| P0+19-5 | 1.0h | 6.0h |
| P0+19-6（5 子步） | 1.5h | 7.5h |
| P0+19-7 | 1.0h | 8.5h |
| P0+19-8 | 1.0h | 9.5h |
| P0+19-9 | 1.25h | 10.75h |
| P0+19-final | 0.5h | 11.25h |
| Buffer | 1.75h | **13.0h** |

**建议节奏**：分 2-3 个 session 做。
- Session 1（4h）：deps + 0 + 1 + 2 + 3
- Session 2（5h）：4 + 5 + 6
- Session 3（4h）：7 + 8 + 9 + final

---

## 6. 验收 / 完工归档协议

完工时（P0+19-final 通过后）：
1. 把本 design doc **不动**（保留作为历史参考）
2. `TODO.md` 把当前 P0+19 看板**精简成 1 段「上轮完工速览」**
3. 原 P0+18-d 上轮速览段 + P0+19 完整看板**整段沉档到 `docs/TODO_ARCHIVE.md` 顶部**
4. archive 目录表插入新行：`P0+19 / 2026-05-XX / Nerve 拆分 + 依赖锁定`
5. `TODO.md` 在「当前迭代」段写新一轮看板（候选 P0+20 或 R9 死代码清扫）

---

*文档作者：Claude 4.7 / Sir 2026-05-15 23:45*
*详见对话上下文：上一轮 Claude 评估 + 调研 grep 输出*
