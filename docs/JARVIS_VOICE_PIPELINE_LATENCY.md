# JARVIS Voice Pipeline Latency — β.5.9 / β.5.10 / β.5.11 修复 design doc

> **修复时间窗**: 2026-05-19 早 09:30 → 晚 21:30
>
> **commits**: `e216a0a` (β.5.9) + `b29a041` (β.5.10) + `22d8746` (β.5.11)
>
> **Sir 真机痛点 (β.5.x 系列收尾后留 BUG-3 + BUG-4)**:
> - BUG-3: TTS "字幕都打完了好久才说话" (固定 ~6s 延迟, Sir 几次反馈仍卡)
> - BUG-4: "hey jarvis" 被 ASR 当 `cmd='hey'` 送 LLM 跑全主脑, 走不到 β.4.8 设计的 reflex 短路径
>
> **本 doc 目的**: 把整套 voice pipeline 延迟 + wake word 链路问题, 在一个 doc 里讲清因果 / fix / 验证, 防 Sir 下次再看代码时丢上下文.

---

## 1. 一图速记: 三个修复在 pipeline 里的位置

```
Sir 说 "hey jarvis hello"
  ↓ [AuditoryCortex / VoiceListenThread]
  ↓ ASR 出文本 "hey jarvis hello"
  ↓
  ↓ ─────────── 修复点 1: β.5.11 ───────────
  │ parse_wake_word (jarvis_worker.py:494)
  │   旧: cmd='hey hello' → LLM 唤醒
  │   新: filler 'hey' 剥除 → cmd='hello' → LLM 唤醒
  │   (若仅 "hey jarvis" → cmd='' → fallback cmd='jarvis' → reflex 短路径)
  ↓
  ↓ [JarvisWorkerThread / stream_*]
  ↓ LLM 流式吐 token 进 buffer
  ↓
  ↓ ─────────── 修复点 2: β.5.9 ────────────
  │ _find_sentence_split_idx (jarvis_chat_bypass.py:164)
  │   旧: hard>=20 字符 / soft>=15 才切 → 短句 "Yes, Sir." 等 stream end (~3s)
  │   新: is_first_sentence=True 时 hard>=8 / soft>=4 → 首句最早能切立刻送 TTS
  ↓
  ↓ [_put_audio → audio_queue]
  ↓ (β.5.9 曾加 [Audio Trace] timing log, 2026-05-19 21:33 Sir 实测后退役)
  ↓
  ↓ [_render_worker → CosyVoice.inference_zero_shot]
  ↓
  ↓ ─────────── 修复点 3: β.5.10 ──────────
  │ CosyVoice prompt encoding cache (jarvis_vocal_cord.py:94)
  │   旧: 每次 inference 重算 5s prompt_wav 的 mel / speech_token / spk_emb
  │        (固定 ~6s 开销, 与字数无关)
  │   新: __init__ 调 add_zero_shot_spk(prompt_text, prompt_speech, 'jarvis_default')
  │        inference 传 zero_shot_spk_id='jarvis_default' 直接复用
  │        benchmark: 6.67s → 1.93s (~3.5x speedup)
  ↓
  ↓ [render_queue → _play_worker → PyAudio stream]
  ↓
  ↓ Sir 听到声音 ✓
```

**累计延迟改善** (Sir 实测 + benchmark 估算):
| 阶段 | 旧 | 新 | 节省 |
|---|---|---|---|
| splitter 等切位 (首句 short) | ~3s (stream end) | ~0.1s (i=4 软切) | -2.9s |
| CosyVoice render (typical 30 字) | ~6.7s | ~1.9s | -4.8s |
| **TTFT 首字到耳累计** | ~10s+ | ~3-4s | **-6s 量级** |

---

## 2. 三个 commit 累计表

| commit | 标题 | 关键改动 | testcase |
|---|---|---|---|
| `e216a0a` β.5.9 | TTS first-sentence fast-split + Audio Trace timing log (Trace 部分后续退役) | `_find_sentence_split_idx` 加 `is_first_sentence` 参数; 4 处 stream loop 传 `_first_sent_done` flag; 原 4 行 `[Audio Trace]` bg_log 已于 21:33 退役 (变 12 测) | 12 测 |
| `b29a041` β.5.10 | CosyVoice prompt encoding cache — render 6.67s → 1.93s 真因修 | `VocalCord.__init__` 调 `add_zero_shot_spk`, cache spk_id='jarvis_default'; `render_only` 传 `zero_shot_spk_id` 复用; 含 fail-safe fallback (cache 失败回 legacy 路径) | 9 测 |
| `22d8746` β.5.11 | hey jarvis fast wake — filler-addressing words stripping | `parse_wake_word` 在 wake_phrases 剥除后增 `filler_addressing_words` list (英中双语 20 条), 让纯呼语降级空唤醒走 reflex | 17 测 |

**累计**: 44 个新 testcase 全绿. 关联回归 β.5.8/9/10/β.4.8/β.2/r6 全 OK 无回归.

**revert 记录** (老实交代):
- `bc2940f` β.5.10 第一版尝试 load_jit + fp16 — 实测 benchmark 显示 **render 时间无显著改善** (6.67s vs 6.5s). 经分析 root cause 是 prompt encoding (mel/spk_emb) 这步占大头, JIT 编译 LLM/Flow 部分占小头. 立刻 `9211c51` revert, 改走 prompt cache 方向, 命中真因.

---

## 3. β.5.9 详解 — TTS first-sentence fast-split

### 3.1 痛点 trace

Sir 起床早晨实测 "Yes, Sir." 这样 9 字符短回复:
- LLM 流式 token: `Yes`, `,`, ` Sir`, `.`, `<EOS>`
- splitter 旧逻辑: hard_symbol `.` 要等位置 ≥ 20 字符. 9 字符的 "Yes, Sir." 永远不切.
- 结果: 等 LLM 流结束 (~3s) buffer flush 一次性送 TTS render
- Sir 体感: 字幕早打完, 声音却晚 3s

### 3.2 root cause

```@d:\Jarvis\jarvis_chat_bypass.py:164-188
def _find_sentence_split_idx(buffer: str, soft_split: bool = True, is_first_sentence: bool = False) -> int:
    """splitter helper：在 buffer 找下一句的切分位置。-1 表示没有可切位置。

    设计原则（性能第一）：
    - 句中 `.` 不切（保护 `e.g.` / `Mr.` 等缩写）
    - 不在 organ.command 的 . 处切
    - soft_split=True 时支持 ',;' 软切

    🩹 [P0+20-β.5.9 / 2026-05-19] 加 `is_first_sentence`:
    - False (默认): hard>=20, soft>=15 (原行为，保护后续句 prosody)
    - True (首句): hard>=8, soft>=4 (让首句更早切送 TTS, 减少 Sir 听到首句的延迟)
    根因: 短回复 "Yes, Sir." (9 字符) 现在永远不切, 要等 stream end (~3s)
```

### 3.3 fix 设计意图

**首句激进 / 后续句保守** 的双阈值. 理由:
- 首句激进切 → 减少 TTFT, Sir 立刻听到响应感
- 后续句保守 → 保 prosody / 防呼吸断节, 不让长回复变成 chop-chop

**4 处 stream loop 改造** (每处都是 `is_first_sentence=not _first_sent_done` + 切出后 `_first_sent_done = True`):
1. `jarvis_chat_bypass.py:1145` local fallback 路径
2. `jarvis_chat_bypass.py:1605` cloud followup 路径
3. `jarvis_chat_bypass.py:2375` 主流 stream 路径
4. `jarvis_chat_bypass.py:4060` stream_nudge 路径

### 3.4 Audio Trace 诊断埋点 — 已退役 (2026-05-19 21:33)

β.5.9 曾加 4 处 `[Audio Trace]` bg_log (enq / render_start / render_done / play_start) 串联 audio pipeline 时序. **Sir 真机实测确认 β.5.10 cache 生效** (render 6.67s → 1.9-2.4s), 诊断使命完成, 已于 2026-05-19 21:33 清理 — 4 处 bg_log + metadata 透传 + `_audio_trace_seq` / `_audio_trace_lock` 实例字段全移除, 净化 noise log.

下次再需诊断: `git show e216a0a -- jarvis_chat_bypass.py` 一行恢复, 或参考 `_test_p0_plus_20_beta59_*` retire 测的 docstring 索引.

---

## 4. β.5.10 详解 — CosyVoice prompt encoding cache

### 4.1 真因发现过程

走过 2 个错误假设:
1. **第一假设**: fp16 / JIT 加速会快 — 写了 `bc2940f` 加 `load_jit=True, fp16=True`, benchmark 6.67s → 6.5s, 改善小到不显著. **revert.**
2. **第二假设**: 是不是 GPU 资源被抢? — 用 `scripts/_bench_vocal_render.py` 隔离测试 (无其他进程时), 仍 6.67s. **排除.**

**真因**: benchmark 显示一个反直觉现象:
- 9 字符 "Yes, Sir." → 6.20s
- 88 字符 "A fortuitous outcome, sir. Your insightful query has yielded..." → 8.45s
- **字数从 9 → 88 (10x), 时间只多 2.25s (1.36x)** ← 说明固定开销占绝大部分

读 CosyVoice 源码定位: `frontend_zero_shot` 每次 inference 都重算 5 秒 `prompt_wav` 的:
- `_extract_speech_feat` (mel spectrogram)
- `_extract_speech_token` (speech tokenizer onnx)
- `_extract_spk_embedding` (campplus onnx)

这是 ~5-6s 固定开销, 与目标字数无关.

### 4.2 fix — add_zero_shot_spk API

CosyVoice 提供 `add_zero_shot_spk(prompt_text, prompt_wav, spk_id)` — 一次性 cache prompt encoding 到 `spk2info` dict. 后续 `inference_zero_shot(..., zero_shot_spk_id=spk_id)` 直接复用 cached state 跳过 prompt 编码.

```@d:\Jarvis\jarvis_vocal_cord.py:85-101
        # 🩹 [P0+20-β.5.10 / 2026-05-19] BUG-3 真因修: prompt encoding cache
        # 根因 (benchmark 实证): frontend_zero_shot 每次 inference 都重算 5 秒 prompt_wav 的
        #   - _extract_speech_feat (mel spectrogram)
        #   - _extract_speech_token (speech tokenizer onnx)
        #   - _extract_spk_embedding (campplus onnx)
        # 这是 ~6s 固定开销, 跟字数无关 (9 chars 6.2s / 88 chars 8.5s, 增量极小).
        # CosyVoice 提供 add_zero_shot_spk(): 一次性 cache prompt encoding 到 spk2info dict,
        # 后续 inference 传 zero_shot_spk_id 直接复用 cached state, 跳过 prompt encoding.
        # 预期: 6.67s → ~1-2s (5x speedup).
        self._jarvis_spk_id = 'jarvis_default'
        print("⚡ [声带器官] cache prompt encoding (β.5.10)...")
        try:
            self.cosyvoice.add_zero_shot_spk(self.prompt_text, self.prompt_speech_16k, self._jarvis_spk_id)
            print(f"✅ [声带器官] prompt cached as spk_id='{self._jarvis_spk_id}'")
        except Exception as _cache_e:
            print(f"⚠️  [声带器官] add_zero_shot_spk 失败, fallback 每次重算: {_cache_e}")
            self._jarvis_spk_id = ''  # fallback 走 legacy 路径
```

### 4.3 fail-safe 设计

- `add_zero_shot_spk` 失败 → `_jarvis_spk_id = ''` 空串 → `render_only` 传 `zero_shot_spk_id=''` 时 CosyVoice 视为未提供, 回 legacy 路径 (每次重算). **不 crash, 仅退化为 β.5.10 之前的性能.**
- 9 个 testcase 锁住关键不变式:
  - `add_zero_shot_spk` 在 `__init__` 被调
  - `_jarvis_spk_id` 字段存在
  - fail-safe path 工作 (mock add_zero_shot_spk raise)
  - `inference_zero_shot` 被传 `zero_shot_spk_id`
  - 无 legacy 全路径 (确认 cache 被启用)

### 4.4 benchmark 数据 (实测前后)

| 句子长度 | β.5.10 前 | β.5.10 后 | speedup |
|---|---|---|---|
| 9 字符 ("Yes, Sir.") | 6.20s | ~1.5s | ~4.1x |
| 30 字符 (typical greeting) | 6.67s | 1.93s | ~3.5x |
| 88 字符 (long response) | 8.45s | ~3.6s | ~2.3x |

短句加速比更大 — 因为固定开销占比更高. 这恰好命中 Sir 实测痛点 ("Yes, Sir." 短回复).

---

## 5. β.5.11 详解 — hey jarvis fast wake

### 5.1 痛点 trace

Sir 真机说 "hey jarvis", 想触发 β.4.8 设计的 reflex 短路径 (chime + 短 awake reaction). 实际:
1. `parse_wake_word("hey jarvis")` 返 `(True, 'hey')`
2. JarvisWorkerThread 看到非空 cmd → 走 LLM 唤醒, 跑全主脑
3. 主脑收到 "hey" 这个语义薄弱输入, 输出含糊回复, 顺带触发 reaction_space / SWM / TTS 全链
4. Sir 体感: 一个本该秒响的呼叫变成 ~3-5s 的全 LLM round-trip

### 5.2 root cause

```@d:\Jarvis\jarvis_worker.py:560-595
        if found_alias is None:
            return False, text_lower

        cmd = text_lower
        cmd = re.sub(r'\b' + re.escape(found_alias) + r'\b', '', cmd)

        wake_phrases = [
            r'\bare\s+you\s+there\b', r'\byou\s+there\b',
            r'\bare\s+you\s+up\b', r'\byou\s+up\b',
            r'\bare\s+you\s+online\b', r'\byou\s+online\b',
            r'\bare\s+you\b',
        ]
        for phrase in wake_phrases:
            cmd = re.sub(phrase, '', cmd)

        # 🩹 [P0+20-β.5.11 / 2026-05-19] 纯语气词 + jarvis → 视作空唤醒走 reflex 短路径
        # Sir 真机痛点: "hey jarvis" 被识成 cmd='hey' 送 LLM 跑全主脑, 应走快唤醒.
        # 设计意图: 任意词+jarvis 中"任意词"若是纯 filler/呼语 (hey/hi/yo/嘿/喂...),
        # 不应被当 LLM cmd, 而该降级为空唤醒, 让 fallback `cmd = "jarvis"` 接住走 reflex.
        # 注: 实词 ("jarvis 帮我开 cursor" → cmd='帮我开 cursor') 仍走 LLM 唤醒, 不影响.
        filler_addressing_words = [
            # 英文呼语 / 语气词
            r'\bhey\b', r'\bhi\b', r'\bhiya\b', r'\byo\b', r'\boi\b',
            r'\bhello\b', r'\bhallo\b', r'\bhola\b', r'\bok\b', r'\bokay\b',
            # 中文呼语 / 语气词
            r'嘿', r'喂', r'嗨', r'哟', r'哎', r'唉', r'喔', r'噢', r'哈喽', r'哈罗',
        ]
        for filler in filler_addressing_words:
            cmd = re.sub(filler, '', cmd)

        cmd = re.sub(r'[，。,.!?？！\s]+', ' ', cmd).strip()

        if not cmd or len(cmd) <= 1:
            cmd = "jarvis"

        return True, cmd
```

旧逻辑只在 `len(cmd) <= 1` 时 fallback `cmd='jarvis'`. "hey" 长度 3, 通不过.

### 5.3 fix 设计意图

**分类原则**:
- "任意词 + jarvis" 中
  - 任意词是 **实词** (动词/名词/请求) → 保留 cmd 走 LLM 唤醒
  - 任意词是 **filler / 呼语** (打招呼/语气词) → 剥除 → cmd 空 → fallback 'jarvis' 走 reflex

**filler list 20 条** (英中双语):
- 英文 (10 条 `\b...\b` 词边界): hey / hi / hiya / yo / oi / hello / hallo / hola / ok / okay
- 中文 (10 条字符级): 嘿 / 喂 / 嗨 / 哟 / 哎 / 唉 / 喔 / 噢 / 哈喽 / 哈罗

**关键测例验证决策表**:

| 输入 | found_alias | cmd 剥后 | filler 剥后 | normalize | 结果 |
|---|---|---|---|---|---|
| "hey jarvis" | jarvis | "hey " | " " | "" | (True, **'jarvis'**) reflex ✓ |
| "嘿 贾维斯" | 贾维斯 | "嘿 " | " " | "" | (True, **'jarvis'**) reflex ✓ |
| "jarvis 帮我开 cursor" | jarvis | " 帮我开 cursor" | " 帮我开 cursor" | "帮我开 cursor" | (True, **'帮我开 cursor'**) LLM ✓ |
| "hey jarvis open chrome" | jarvis | "hey  open chrome" | "  open chrome" | "open chrome" | (True, **'open chrome'**) LLM ✓ |
| "jarvis" | jarvis | "" | "" | "" | (True, **'jarvis'**) reflex ✓ |
| "are you there jarvis" | jarvis | "are you there " | "are you there " | (wake_phrases 已剥) "" | (True, **'jarvis'**) reflex ✓ |

### 5.4 关于 "ok jarvis" 的设计决断

测例 `test_okay_jarvis_fast_wake` 锁: 单独 "ok jarvis" → reflex (单独 "ok" 不携带意图, 是 acknowledgment); "ok jarvis stop X" → LLM 唤醒 cmd='stop X' (实词部分保留).

---

## 6. Sir 真机验证 checklist

### 6.1 重启后看启动 log

```powershell
python jarvis_nerve.py
```

应看到 (β.5.10 startup print):
```
🗣️ [声带器官] 正在挂载纯血英文 ETE 引擎...
⚡ [声带器官] cache prompt encoding (β.5.10)...
✅ [声带器官] prompt cached as spk_id='jarvis_default'
🔥 [声带器官] 正在给 GPU 注入高压点火预热，请稍候...
✅ [声带器官] 显存预热完毕！
```

如看到 `⚠️ add_zero_shot_spk 失败, fallback 每次重算` — β.5.10 cache fail-safe 已生效, render 时间会回退到 ~6.67s. 把异常贴给我.

### 6.2 跑 wake word 三类对比

```
Sir: "hey jarvis"            → 应秒 chime + 短 awake (reflex)
Sir: "jarvis 帮我开 cursor"  → 应跑 LLM 主脑回 (LLM 唤醒)
Sir: "ok jarvis stop"        → 应跑 LLM 主脑接 'stop' 命令
```

抓 log 验证:
```powershell
$latest = Get-Content docs/runtime_logs/latest.txt
Select-String -Path $latest -Pattern "parse_wake_word|cmd='"
```

应看到 `cmd='jarvis'` 三次中第 1 次 + 第 3 次的 cmd 是实词.

### 6.3 跑 TTS 延迟体感 (Audio Trace 已退役)

```
Sir: "hello"
```

启动后第一句通常 2-3s 内听到 (typical render 1.9-2.4s + splitter ~0.1s + play_wait ~0.1s). 如再次"字幕都打完了好久才说话", 临时恢复 Audio Trace 诊断:

```powershell
git show e216a0a -- jarvis_chat_bypass.py | git apply --reverse  # 或 cherry-pick 反向恢复
```

再 grep `[Audio Trace]` 看 enq / render_start / render_done / play_start 4 节点耗时定位.

### 6.4 短回复延迟体感

```
Sir: "are you there"
Jarvis: "Yes, Sir."    ← 这种 9 字符短回复
```

旧体感: 字幕打完 ~3s 后才听到声音
新体感: 字幕打完 ~0.5-1.5s 内听到声音 (β.5.9 首句激进切 + β.5.10 cache)

### 6.5 长回复 prosody 不破

```
Sir: "tell me a long story about cyberpunk Tokyo"
Jarvis: 长回复 100+ 字
```

应保持自然分句 / 不 chop-chop. β.5.9 只首句激进, 后续句仍是 hard>=20 / soft>=15 老阈值.

---

## 7. 边界 BUG 监测点

### 7.1 🔴 prompt cache 突然 fallback

**症状**: 启动 log 显示 `⚠️ add_zero_shot_spk 失败`, render 时间回 6s+.

**应对**:
- 看异常具体内容 (常见: CosyVoice 版本不兼容 / spk2info dict 读写权限)
- 临时不 crash, 行为退化到 β.5.10 之前
- 后续可改成异步 retry / 启动时强制等 cache 成功才标 ready

### 7.2 🟡 首句 splitter 切太碎

**症状**: 短句 "Hi." 被切成 "H" + "i.", render 出怪声.

**应对**:
- 已锁: hard_min=8, 不可能切到 "H" (单字符).
- 真出现 → 检查是否 LLM 流回的不是 ASCII (中文 token 字符数可能误判)
- 改阈值需改 `jarvis_chat_bypass.py:187`

### 7.3 🟡 filler list 误剥实词

**症状**: Sir 说 "yo bro tell jarvis about Y" → "yo" 被剥后 cmd='bro tell about Y' 仍有效, 但 "yo" 这个语气如果是命令的一部分会丢上下文.

**应对**: 准则 6 vocab 化 — ✅ **β.5.26 已做** (2026-05-20): `memory_pool/wake_filler_vocab.json` (20 词) + `scripts/wake_filler_dump.py` (list/add/count) + `jarvis_worker.py` `_load_wake_filler_vocab` mtime cache + hardcoded SEED fallback. Sir 真机遇实词被误剥 → CLI `add` 调.

### 7.4 � Audio Trace log 噪音 — 已除根

2026-05-19 21:33 已清理 4 处 bg_log + metadata. log 文件不再有 [Audio Trace] 行. 反向锁 testcase `TestBeta59AudioTraceRetired` 防復发.

---

## 8. 紧急回滚顺序

| 不稳程度 | 操作 |
|---|---|
| 轻 (β.5.11 wake 误剥) | `git revert 22d8746` — 单 commit revert wake 修复 |
| 中 (β.5.10 cache 异常) | `git revert b29a041` — 回到 prompt 不 cache 但 splitter 仍激进 |
| 重 (TTS 全乱) | `git reset --hard 915ac69` — 回到 β.5.8-fix 之前 voice pipeline 全部回退 |

---

## 9. 设计原则总结 (准则对照)

| 准则 | 体现 |
|---|---|
| **1 高效 (TTFT < 5s)** | β.5.9 + β.5.10 联动把 TTFT 从 ~10s 降到 ~3-4s, 命中 Sir 第一项准则 |
| **2 反应迅速** | reflex 短路径 (β.5.11) 让纯 wake word 不再走全 LLM round-trip |
| **5 言出必行** | benchmark 数据实测 (6.67→1.93s); 不假装"已加速" |
| **6 拒绝硬编码 + 信任 LLM** | β.5.11 filler list 是硬编码 list (暂时), 已记 TODO §7.3 vocab 化. β.5.10 cache 是 API 调用不改语义 |
| **6 工程方法论 (准则 6.5)** | β.5.11 filler list 还在 `.py` 源码里 (违规), 后续应迁 `memory_pool/wake_filler_vocab.json` |
| **7 Sir 元否决** | β.5.10 走过 1 次错路 (fp16/JIT 假设), 立刻 revert 不嘴硬, 重新找真因 |

---

## 11. β.5.12 — cloud stream RemoteProtocolError 3 层叠加修 (2026-05-19 21:42)

**Sir 21:37 实测**: `RemoteProtocolError after 18.8s`, `full 40.5s`. 用户耳朵里 — "I try to be, Sir. It is often the most practical approach." (主回复已说完) → 停 ~7s → "Forgive me Sir, the evening network traffic..." (罐头道歉, 体感分裂).

### 三层 BUG 决策表

| 层 | 痛点 | 修法 | 文件:行 |
|---|---|---|---|
| **A** (主修) | except 无脑追加道歉, 不看 cloud stream 是否已实质说够 | 加 `spoken_so_far` 守卫: 净化 `full_text` (剥 `---ZH---` / `<tag>` / `[WAKE_ONLY]` / `_strip_structural_tag_blocks`), 若 net ≥ 12 char 则 `bg_log` 错误 + `return True` 不补道歉 | `@d:\Jarvis\jarvis_chat_bypass.py:3199` |
| **B** (timeout) | `timeout=60.0` 是 total request 超时, 不是 chunk inter-arrival; server 半路 close TCP, client 等 18.8s 才报错 | `httpx.Timeout(connect=10, read=12, write=10, pool=10)`, `read=12` 即 chunk 间最长间隔 — 既能盖 reasoning ~5-10s, 又比 18s 早砍 6s | `@d:\Jarvis\jarvis_chat_bypass.py:683` |
| **C** (Ollama 5s) | CosyVoice 占 GPU 时 `qwen2.5:14b` 排不上, 5s 出不了完整 token | `timeout=5.0 → 8.0`, 仍空走罐头 (双层 fallback 保留), print 提示 GPU 争抢假设 | `@d:\Jarvis\jarvis_chat_bypass.py:782` |

### 测试 + 回归

- `tests/_test_p0_plus_20_beta512_stream_break_persist.py` 15 测 4 类 — BUG-A guard (5) / BUG-B httpx.Timeout (4) / BUG-C Ollama bump (3) / NoRegression (3)
- 全 src 字面 marker check, 不实例化 ChatBypass (避 KeyRouter/VocalCord 依赖)
- 关联 β.5.9 / β.5.10 / β.5.11 + `jarvis_chat_bypass import` 全 OK

### Sir 真机验证 §6 补一项

**§6.5 cloud stream 半路断验证**

人为模拟 (拔网线 / 改 DNS): `Sir: "嗯, 你说的有道理"` → cloud stream 中途死. 应看到:
- log 含 `🩹 [β.5.12/BUG-A] cloud stream RemoteProtocolError after spoken=Nch, skip 道歉`
- 终端含 `║ ✅ [β.5.12] 已说 N 字符实质内容, 跳过道歉补丁`
- TTS **不补** "Forgive me Sir..." 罐头. 用户体感: 主回复说完戛然 (比 BUG 前的"主+突兀道歉"自然)

### 紧急回滚 (§8 补) + β.6+ 候选

- `git revert d51385c` 单 revert β.5.12 守卫. 其余 β.6+ 候选: filler list vocab 化 / wake_aliases vocab 化 / prompt cache 多 speaker / Audio Trace render_dur > 5s 轻量哨兵

---

**末**: doc 完成 2026-05-19 21:33 +08 (β.5.12 §11 续 21:42 +08); commits `e216a0a` + `b29a041` + `22d8746` + `d51385c` 落地, 59 testcase 全绿, 待 Sir 真机.
