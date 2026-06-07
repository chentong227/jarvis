# 旁路语误判诊断 + 最小修方案 (false bypass)

> **[bypass-false-positive-diag / 2026-06-07]**
> 真机现象 (turn_20260607_190721_7984 附近): Sir 直接回话
> "…我离我妈妈那个医院很近啊, 不用开车过去, 我走路回去就到了…" 被判旁路语忽略,
> 日志 `🔇 [Bypass Speech] 旁路语 score=0.20 breakdown={'third_person': -0.30}`。
> **只读勘察 + 诊断 + 最小修方案, 零施工、零真机。** 审 + Sir 拍才动。

---

## 一、打分器逻辑 (file:line)

打分器: `jarvis_voice_listen_thread.py:625` `classify_jarvis_directness(text) -> (score, breakdown)`。

**基线 + 全特征权重:**

| 特征 | 权重 | 触发条件 | file:line |
|---|---|---|---|
| 基线 | `score=0.5` | 中性起点 | `:636` |
| `wake_word` | **+0.5** | 含 `_JARVIS_DIRECT_WAKE`(jarvis/贾维斯/小贾…)| `:640` |
| `en_direct_verb` | +0.35 | 含英文 direct verb(help me/find/open…)| `:645` |
| `zh_direct_verb` | +0.35 | 含中文 direct verb(帮我/告诉我/打开/关了…)| `:648` |
| `phone_opener` | -0.4 | 以电话开场词起头(hello/喂…)| `:654` |
| **`third_person`** | **-(0.2~0.4)** | 命中第三人称指代 ≥1(详下)| `:680-687` |
| `long_multi_question` | -0.2 | len>40 且 ?≥2 | `:690` |
| `conversational_marker` | -0.15 | 含 "和我/跟我/我和/我跟" | `:697` |
| `too_short` | -0.15 | ≤3 字且无 wake | `:702` |

**阈值**(`:631-634`): `≥0.6` 直接触发 / `0.3–0.6` 灰区(交主脑自决,见 `_evaluate_focus_directness:715`)/ `<0.3` 视旁路语,**ASR 层丢弃不触发主脑**。

### third_person 这条(罚分核心)

```
third_hits_zh = sum(1 for w in _THIRD_PERSON_INDICATORS_ZH if w in text)   # :680
third_hits_en = sum(1 for w in _THIRD_PERSON_INDICATORS_EN if w in t_pad)  # :681
if third_hits_zh + third_hits_en >= 1:
    penalty = min(0.4, 0.2 + (hits)*0.1)        # 1 命中 → 0.3
    if _is_addressing_jarvis:                    # 转述降权
        penalty *= 0.5
    score -= penalty
    breakdown['third_person'] = -penalty
```

- `_THIRD_PERSON_INDICATORS_ZH`(`:616`): `他说/她说/他们/她们/他在/她在/`**`你妈/你爸/我妈/我爸/我儿/我女`**。
- 关键: **`我妈`/`我爸` 等"第一人称所属亲属称谓"被直接列进"第三人称指代"** → 命中即扣分。

### `_is_addressing_jarvis` 降权闸(本句的命门)

```
_wo_count = text.count('我')                                          # :673
_has_family_indicator = any(w in text for w in ('我妈','我爸','我儿','我女'))  # :674
_is_first_person_narrative = (_wo_count >= 2 and not _has_family_indicator)   # :675
_is_addressing_jarvis = (wake_word or zh_direct_verb or en_direct_verb
                         or '你' in text or _is_first_person_narrative)        # :676
```

⚠️ **自相矛盾点**: `_has_family_indicator=True`(含"我妈")会**直接关掉** `_is_first_person_narrative`,理由注释(`:670`)"`我妈/我爸` 家庭指代 → 那是真转述他人对话"。于是含家人称谓的第一人称自叙**拿不到 narrative 豁免**,third_person 罚分**不降权**(full -0.3)。

---

## 二、复盘本句 score=0.20 (完整 breakdown)

句子: `我离我妈妈那个医院很近啊，不用开车过去，我走路回去就到了`

| 步骤 | 计算 | 结果 |
|---|---|---|
| 基线 | | 0.5 |
| wake_word | 无 jarvis/贾维斯 | — |
| zh_direct_verb | "开车"≠"打开"、无"帮我/告诉我"等 | **未命中** |
| `third_hits_zh` | `'我妈' in "我离我妈妈…"` → 子串命中 | **1** |
| `_wo_count` | "我离" / "我妈妈" / "我走路" | **3** |
| `_has_family_indicator` | "我妈" ∈ text | **True** |
| `_is_first_person_narrative` | `3>=2 and not True` | **False** ← 被家人称谓关掉 |
| `_is_addressing_jarvis` | 无 wake/verb/"你"/narrative | **False** |
| third_person penalty | `min(0.4, 0.2+0.1)=0.3`,未降权(addressing=False)| **-0.30** |
| **score** | `0.5 - 0.30` | **0.20** ✅ 与日志一致 |

**触发 token**: `第三人称`被 **"我妈"**(出自"我妈妈")命中 —— 即**第一人称所属的亲属称谓("我妈妈")被当成了第三人称指代**,且因 `_has_family_indicator` 又把唯一能救它的 first-person-narrative 豁免关掉,导致 full -0.3 落到 0.20 < 0.3 阈值 → 旁路丢弃。

---

## 三、根因诊断

**是的 —— "提及亲属"被一刀切当成"非对话",且双重失误叠加:**

1. **误分类**: `我妈/我爸/我儿/我女` 这些**第一人称所属亲属称谓**被列进 `_THIRD_PERSON_INDICATORS_ZH`(`:619`)。但"我妈妈"是 Sir 在跟 Jarvis 讲**自己的事**(第一人称自叙),不是第三人称指代(他/她/他们)。
2. **豁免被反向关闭**: `_is_first_person_narrative` 本是救"多个'我'的自叙"的豁免,却因 `_has_family_indicator` 主动排除了带家人称谓的句子(`:674-675`)—— 设计原意是"我妈/我爸 = 真转述他人对话",但**现实里"我离我妈妈医院近"是第一人称自叙,不是转述他人对话**。这条假设过宽。

**能否区分"第一人称对话里提到家人" vs "真旁路(转述他人/旁人插话/对第三方说)"?**
- 当前特征**不能**可靠区分。`我妈`同时触发 third_person 罚分 + 关闭 narrative 豁免,把"提到家人的自叙"和"转述他人对话"混为一谈。
- 真旁路的离散信号其实是: `他说/她说`(转述他人言论)、`和我/跟我...说`(对话标记)、电话开场词 —— 这些与"我妈妈"(第一人称所属)是不同性质。

---

## 四、最小修方案候选 (只提案, 不施工)

### 候选 A(推荐): "我X" 第一人称所属亲属称谓不计 third_person
- **改法**: `我妈/我爸/我儿/我女`(第一人称所属)从 `_THIRD_PERSON_INDICATORS_ZH` 移除 / 或在命中判定时,若亲属称谓前缀是"我"(第一人称所属)则不计入 third_hits。保留 `你妈/你爸`(第二人称,可能在跟别人说)+ `他说/她说/他们`(真第三人称)。
- **对真旁路影响**: 真旁路"他说他下午要来取东西"靠 `他说/他们` 仍命中(测试 `_test_p0_plus_20_beta2710_directness.py::test_third_person_with_long` / `test_third_person_no_jarvis_address_still_bypass` 用的是"他说他…",不含"我妈",**不受影响**)。转述他人对话若说"我妈说…"→ 见候选 C 补充。
- **放过真旁路风险**: 极低。"我妈妈"出现在真旁路(对第三方说话)的概率远低于第一人称自叙。

### 候选 B: first-person narrative 豁免不再被家人称谓关闭
- **改法**: `_is_first_person_narrative = (_wo_count >= 2)`,删掉 `and not _has_family_indicator`。即多个"我"的自叙一律给 narrative 豁免 → third_person 罚分降权 50%(0.3→0.15)。
- **效果**: 本句 score = 0.5 - 0.15 = **0.35**(进灰区,交主脑自决,不再 ASR 层丢弃)。
- **对真旁路影响**: "我妈说她下午来"(_wo_count 可能仅 1)不受益;但"我跟我妈说了我今天…"(多个我)会被豁免降权 —— 这种本就是 Sir 自叙,合理。真第三人称转述"他说他…"无"我"→ 不受豁免,仍全罚。
- **风险**: 比 A 略宽,但只降权不清零,且落灰区(主脑兜),不会直接放行。

### 候选 C(配合 A/B): 区分"我妈" vs "我妈说"
- **改法**: 只有当亲属称谓后跟言说动词(我妈**说**/我爸**讲**)才算转述他人 → 计 third_person;单纯"我妈妈医院"(所属/叙事)不计。
- **对真旁路影响**: 最精准 —— "我妈说她要来"(转述)仍罚,"我离我妈妈医院近"(自叙)不罚。
- **代价**: 逻辑略复杂(需检亲属称谓 + 后续言说动词),但仍纯离散关键词,无相似度。

### 推荐组合
**A(移除"我X"亲属的 third_person 罚)+ C(若要保住"我妈说"转述场景的旁路)**。最小改、不误伤真旁路("他说/他们"系仍全罚,"我妈说"经 C 仍罚)。B 是更轻的单点改(只松豁免),但不如 A+C 精准。

**影响面共识**: 现有测试 `test_third_person_with_long` / `test_third_person_no_jarvis_address_still_bypass` 用 "他说他…"(无"我妈")→ A/B/C 都**不影响**这些真旁路用例,绿不变。`test_family_indicator_not_treated_as_narrative`(`_test_..._sir_20260525_2114_bypass_speech.py:118`)是**针对"我妈"现行为的断言** → 选 A/C 需同步更新该测试预期(它现在锁的是"我妈仍全罚"的旧行为)。

---

## 交付小结

| 项 | 结论 |
|---|---|
| 打分器 | `jarvis_voice_listen_thread.py:625` classify_jarvis_directness,阈值 <0.3 旁路 |
| 本句 breakdown | base 0.5 − third_person 0.3 = **0.20**;触发 token = **"我妈"**(出自"我妈妈")|
| 根因 | "我妈/我爸"被列为第三人称指代(`:619`)+ `_has_family_indicator` 反向关闭 first-person narrative 豁免(`:675`)→ 第一人称自叙提到家人被误判旁路 |
| 最小修 | A(移除"我X"亲属罚)/ B(松 narrative 豁免)/ C(只罚"我妈说"转述);推荐 A+C,真旁路"他说/他们"不受影响,需同步更新 sir_20260525_2114 测试预期 |

---

*只读诊断 + 提案。未改任何码/真机/flag。证据 file:line + 日志 turn 可抽查。最小修候选待顾问审 + Sir 拍才施工。*
