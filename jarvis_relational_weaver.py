"""jarvis_relational_weaver.py — 织网者 (Weaver), 体(Body)的维护器官.

体-P5 / 体-P2 (2026-05-31). 详 docs/JARVIS_TRINITY_ARCHITECTURE.md §4.

织网者 = 和"识"(思考脑)同级的后台 peer。它不"活"(那是识的事), 不"投影"(那是透镜的事),
它只做一件慢工: **维护关系流形**。
- **harvest**: 从各真理源 store (self_threads / concerns / relational_state) 取节点 + 文本。
- **几何织网 (体-P2)**: embed 节点文本 (复用 hippocampus 向量器, 带缓存), 算两两 cosine,
  相似度 >= 阈值 → 连 embed 边。**相似度是静态属性** → set-to-floor (不 Hebbian 累加)。
- **维护**: 周期 decay (关系慢衰) + prune (删枯边)。
- **接地红线**: embed 边 ref='cosine' + detail=cos值 (可复现), 不是幻觉。

准则 1 (TTFT): 全程后台慢工 (默认 600s 一轮), 不在主脑热路径。
准则 6 #1/#3: 数据进 manifold (持久化), 织网逻辑非 LLM (纯几何), 配置 CLI 可改。
"""

from __future__ import annotations

# [体-P5 / 2026-05-31] import safety net (JARVIS_PYTHON_STYLE §1)
import os  # noqa: F401
import sys  # noqa: F401
import io  # noqa: F401
import re  # noqa: F401
import time
import json
import math  # noqa: F401
import threading
import hashlib
import collections  # noqa: F401
from typing import Dict, List, Optional, Callable, Any

import numpy as np

from jarvis_relational_manifold import (
    RelationalManifold, get_manifold, get_manifold_config,
    make_node_id, split_node_id, KIND_THREAD, KIND_CONCERN, KIND_JOKE,
    KIND_PROTOCOL, KIND_STANCE, KIND_ENTITY, PROV_SHARED, PROV_SAID, is_grounded,
)

EmbedFn = Callable[[List[str]], List[Optional[List[float]]]]


def _log(msg: str) -> None:
    try:
        from jarvis_utils import bg_log
        bg_log(msg)
    except Exception:
        pass


def _default_event_bus():
    """口识体-C: 默认读全局 SWM (生产). 注入便于 test 隔离。失败返 None。"""
    try:
        from jarvis_utils import get_event_bus
        return get_event_bus()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Default embedder — 复用 hippocampus 向量器 (Gemini embedding + key 轮换)
# ---------------------------------------------------------------------------

_EMBED_HIPP = None
_EMBED_LOCK = threading.Lock()

# ---- 口写体 (口识体-B2): 对话 turn → 显著共现边 ----
# node 文本 TTL 缓存 (per-turn 调, 不每次 harvest 4 文件)
_TURN_TEXT_CACHE: Dict[str, str] = {}
_TURN_TEXT_TS = 0.0
_TURN_TEXT_TTL = 120.0
_TERM_CJK = re.compile(r"[\u4e00-\u9fff]{2,6}")
_TERM_EN = re.compile(r"[A-Za-z]{4,}")
# 太常见 → 不算 distinctive (每个节点都含, 匹配无意义)
_TERM_STOP = frozenset({
    "sir", "jarvis", "your", "this", "that", "with", "have", "will", "would",
    "should", "could", "贾维斯", "先生", "应该", "可能", "需要", "我们", "他的", "自己",
})


def _cached_node_texts() -> Dict[str, str]:
    global _TURN_TEXT_CACHE, _TURN_TEXT_TS
    now = time.time()
    if _TURN_TEXT_CACHE and (now - _TURN_TEXT_TS) < _TURN_TEXT_TTL:
        return _TURN_TEXT_CACHE
    try:
        _TURN_TEXT_CACHE = RelationalWeaver(manifold=get_manifold()).harvest_nodes()
    except Exception:
        _TURN_TEXT_CACHE = _TURN_TEXT_CACHE or {}
    _TURN_TEXT_TS = now
    return _TURN_TEXT_CACHE


def _distinctive_terms(text: str, k: int = 12) -> List[str]:
    """抽节点文本里的 distinctive 词: CJK run 滑窗 2/3-gram + 英文 ≥4 字母, 去停用词。

    (滑窗 gram 是为了让长 CJK run 如 '连续熬夜风险' 产出 '熬夜' 以匹配对话, 牺牲少量精度换召回。)
    """
    english = [w.lower() for w in _TERM_EN.findall(text or "")
               if w.lower() not in _TERM_STOP]
    grams3, grams2 = [], []
    for run in _TERM_CJK.findall(text or ""):
        for i in range(len(run) - 2):
            g = run[i:i + 3]
            if g not in _TERM_STOP:
                grams3.append(g)
        for i in range(len(run) - 1):
            g = run[i:i + 2]
            if g not in _TERM_STOP:
                grams2.append(g)
    # 优先序: 英文词(最 distinctive) + CJK 2-gram(中文词多为双字) + 3-gram
    seen: set = set()
    uniq = [t for t in (english + grams2 + grams3) if not (t in seen or seen.add(t))]
    return uniq[:k]


def observe_turn_cooccurrence(
    turn_text: str, turn_id: str, *,
    text_map: Optional[Dict[str, str]] = None, manifold=None,
    max_nodes: int = 6, min_match_nodes: int = 2, save: bool = True,
) -> int:
    """口写体 (B2): 一轮对话提到的体节点 (lexical 匹配) → 两两共现边。

    **选择性 (准则 8 防 bloat)**: 平凡闲聊 → 0-1 节点匹配 → 不写。只有真激活 >=2 个已知
    体节点的 turn 才回写共现边 (turn_id 接地)。词消化进体走现有 STM→thread 管线, 这里只补边。
    返回新增/强化边数。失败非致命。
    """
    if not turn_text:
        return 0
    # turn_id 缺失 (mirror 文本注入 / 某些路径 turn_id 未及设) → 退回时间戳 ref:
    # 共现仍是真实事件 (接地到 time T), 精度降到"何时"而非"哪轮", 不丢接地 (准则 5)。
    if not turn_id:
        turn_id = f"turn@{int(time.time())}"
    try:
        m = manifold if manifold is not None else get_manifold()
        tmap = text_map if text_map is not None else _cached_node_texts()
        tl = turn_text.lower()
        scored: List[tuple] = []
        for nid, ntext in tmap.items():
            terms = _distinctive_terms(ntext)
            hits = sum(1 for t in terms if (t in tl if t.isascii() else t in turn_text))
            if hits >= 1:
                scored.append((nid, hits))
        scored.sort(key=lambda x: x[1], reverse=True)
        nodes = [n for n, _ in scored[:max_nodes]]
        if len(nodes) < min_match_nodes:
            return 0  # 平凡闲聊 / 没激活已知结构 → 不写
        n = m.observe_cooccurrence(nodes, turn_id)
        if save and n:
            m.save()
        return n
    except Exception as exc:
        _log(f"[Weaver] observe_turn_cooccurrence failed ({exc!r})")
        return 0


def observe_thought_concern_link(
    thread_id: str, concern_id: str, *, manifold=None, save: bool = True,
) -> Optional[str]:
    """[body-diff-P0c-Tier1 / Sir 2026-06-03] thread→concern "about" 边 (生成期连).

    思考脑产出带 concern_id 的 thought (C 类 adjust_concern_notes) **那一刻**调: 把"这念头
    在嚼哪个 concern"当场记成 grounded 边 — observe_shared_entity([thread_node, concern_node],
    entity_id=concern_id)。

    **判据 = concern_id 机械 ref, 绝非 cosine, 绝非 LLM** (准则1 边生成纯几何/机械; 不变量②
    接地形态)。修 P0c 诊断真根因: 老码 concern_id 只 append concern.notes_for_self, 从不写成
    manifold 边 → thread 节点进体只剩 summary → 靠 embed/偶发 cooccur → 49 thread 孤儿。

    拓扑效果 (Sir 背书): 反刍 thread 都连到它嚼的 concern → concern 成面**轴心(hub)**,
    反刍挂其上自然长面; 跨多主题 concern = 天然桥。不用 thread↔thread 直连。

    thread_node id = make_node_id(KIND_THREAD, thread_id), 与 weaver harvest self_threads.json
    的节点同 id (consolidate 用同一 thread_id, 已核对) → 边接真节点非幽灵。
    返 edge_key 或 None。失败非致命 (背景, 不阻 daemon)。
    """
    try:
        cid = (concern_id or "").strip()
        tid = (thread_id or "").strip()
        if not cid or not tid:
            return None
        m = manifold if manifold is not None else get_manifold()
        tnode = make_node_id(KIND_THREAD, tid)
        cnode = make_node_id(KIND_CONCERN, cid)
        if tnode == cnode:
            return None
        n = m.observe_shared_entity([tnode, cnode], cid)
        if save and n:
            m.save()
        return f"{tnode}\u241f{cnode}" if n else None
    except Exception as exc:
        _log(f"[Weaver] observe_thought_concern_link failed ({exc!r})")
        return None


# ===========================================================================
# 🆕 [causal-grounding-P1 / Sir 2026-06-07] 对话关系事实接地: Sir 显式关系标记
# → entity 节点 + PROV_SAID 边 (§9 A 前置 / 修-因果接地首刀)
# ---------------------------------------------------------------------------
# 设计 (顾问/Sir 阶段0对齐拍板):
#   - 实体来源 = **关系模式正则的捕获组** (非 _distinctive_terms 全量, 后者半噪音)。
#   - 保守触发: 只在 Sir 用明确关系标记 (领属/动作/处所) 显式连两实体时才写 SAID。
#     无模式命中 → 不写 (漏接优于假接: 太松会把弱共现伪装成强 SAID = 造假焊)。
#   - 离散清洗护栏: 捕获串剥人称/领属前缀 + 去时间/副词噪音 (小离散停用词表), 清洗后
#     空/过长/仍多词噪音 → 跳过 (绝不建 entity:我妈妈明天 / entity:妈明 垃圾节点)。
#   - canonical: strip + 空白归一 + 英文 lower → make_node_id('entity', raw_id)。
#   - resolve 查/建: 命中复用、不命中隐式建 (写边即建)。**绕开 auto_merge cosine** —
#     变体 (妈妈/母亲) 映不同 raw_id、不归并 (禁相似度红线)。
#   - 写边: observe_explicit_link (内部 add_edge(PROV_SAID, ref=turn_id))。
# 红线: 全程正则 + make_node_id + exact resolve, 零相似度/embedding/cosine。
# ===========================================================================

# 关系标记小模式集 (规则正则, 非 LLM 非相似度)。
# 🆕 [causal-grounding-tighten / Sir 2026-06-07] 收紧: 删高频虚词 的/在 (会误触造假焊:
#   现在很累→现~很累 / 重要的事情→重要~事情), 删 陪 (陪审/陪练/陪同 复合词 → 法院陪审团
#   →法院~审团 假焊)。保留高特异连接词, 新增明确事件动词。漏接优于假接。
# 槽内不含标点/空白 (实体是连续片段), 防把整句吞进一个槽。
_REL_SLOT = r"([^\s，。,.！？!?、；;：:]{1,12})"   # 实体槽: 1-12 非标点非空白字符

# 二元关系 (两实体槽 A<连接>B, 两端都是真实体)。连接词高特异 (非高频虚词/非复合词碎片)。
_REL_BINARY_PATTERNS = [
    # 动作 A要做B / A做B (母亲要做手术 → 母亲~手术)。"做手术/做检查" 高特异事件。
    re.compile(_REL_SLOT + r"要?做" + _REL_SLOT),
    # 处所-入 A住进B (母亲住进医院 → 母亲~医院)。"住进" 双字, 不在常见复合词碎片。
    re.compile(_REL_SLOT + r"住进" + _REL_SLOT),
    # 探访 A看望B (哥哥看望母亲 → 哥哥~母亲)。"看望" 双字干净动词, 极少入复合词。
    re.compile(_REL_SLOT + r"看望" + _REL_SLOT),
]

# 事件-单宾 (固定事件实体名 + 单实体槽)。主语隐式/时间噪音时仍能接地 (下午去看望母亲)。
# 高特异事件动词把对象实体连到事件节点 (entity:<事件名>)。每条: (事件名, 正则[1组])。
_REL_EVENT_PATTERNS = [
    # 去看望<X> (下午去看望母亲 → entity:看望 ~ entity:母亲)。"去看望" 三字高特异,
    # 避开 Sir 警示的高频单字"去"(去年/去吧 不含 "去看望")。
    ("看望", re.compile(r"去看望" + _REL_SLOT)),
    # <X>住院 (母亲住院 → entity:母亲 ~ entity:住院)。"住院" 医疗事件高特异;
    # (?!部) 排除 "住院部" 复合词。主语槽在前。
    ("住院", re.compile(_REL_SLOT + r"住院(?!部)")),
]

# 离散清洗停用词 (位置剥离 + 噪音过滤; 纯关键词比对, 禁相似度)。
# 人称/领属前缀: 实体头部若以这些开头, 逐个剥 (我妈妈→妈妈)。
_CLEAN_PERSON_PREFIX = ("我", "你", "他", "她", "咱", "您")
# 时间/副词噪音词: 实体含这些 token → 视为噪音捕获, 剥除; 剥完空则跳过。
_CLEAN_NOISE_TOKENS = (
    "明天", "今天", "昨天", "后天", "刚才", "刚刚", "已经", "正在", "马上",
    "现在", "待会", "稍后", "今早", "今晚", "早上", "晚上", "下午", "上午",
    "要", "会", "想", "在", "了", "的", "去", "来", "过",
)
_CLEAN_MAX_ENTITY_LEN = 8   # 清洗后实体过长 (>8 字) = 多词噪音, 跳过


def _clean_entity(raw: str) -> Optional[str]:
    """离散清洗捕获串 → 核心实体 (护栏: 漏接优于假接)。

    纯位置剥离 + 离散停用词, **零相似度**。剥不出干净实体 → 返 None (跳过不写)。
    步骤: ① strip + 空白归一 + 英文 lower
          ② 逐个剥人称/领属前缀 (我妈妈→妈妈, 只剥头部)
          ③ 去时间/副词噪音 token (子串移除)
          ④ 空 / 过长 / 含残余空白 (仍多词) → None
    """
    if not raw:
        return None
    s = " ".join(raw.split()).strip()       # 空白归一
    if not s:
        return None
    # 英文 lower (中文不受影响)
    s = s.lower()
    # ② 剥人称/领属前缀 (只剥头部, 逐个; 防把单字实体剥空)
    changed = True
    while changed and len(s) > 1:
        changed = False
        for p in _CLEAN_PERSON_PREFIX:
            if s.startswith(p) and len(s) > len(p):
                s = s[len(p):]
                changed = True
                break
    # ③ 去时间/副词噪音 token (子串移除)
    for tok in _CLEAN_NOISE_TOKENS:
        if tok in s:
            s = s.replace(tok, "")
    s = s.strip()
    # ④ 护栏: 空 / 过长 / 仍含空白 (多词残余) → 跳过
    if not s:
        return None
    if len(s) > _CLEAN_MAX_ENTITY_LEN:
        return None
    if any(ch.isspace() for ch in s):
        return None
    return s


def observe_sir_relational_link(
    turn_text: str, turn_id: str, *, manifold=None, save: bool = True,
) -> List[str]:
    """[causal-grounding-P1] Sir 显式关系标记 → entity 节点 + PROV_SAID 边。

    管线 (全离散): 关系模式正则捕获两实体槽 → _clean_entity 离散清洗 → make_node_id
    ('entity', raw_id) canonical → resolve 查/建 (绕开 cosine) → observe_explicit_link
    (PROV_SAID, ref=turn_id) 写边。无模式命中 / 清洗不出干净实体 → 跳过 (不写)。

    返回新增/强化的 edge_key 列表 (空 = 没写任何边)。失败非致命。
    红线: 禁相似度 (全程正则 + make_node_id + exact resolve, 不碰 auto_merge)。
    """
    out: List[str] = []
    if not turn_text:
        return out
    if not turn_id:
        turn_id = f"turn@{int(time.time())}"
    try:
        m = manifold if manifold is not None else get_manifold()
        seen_pairs: set = set()

        def _link(a_ent: Optional[str], b_ent: Optional[str]) -> None:
            """两清洗后实体 → entity 节点 + SAID 边 (离散, 绕开 cosine)。"""
            if not a_ent or not b_ent or a_ent == b_ent:
                return  # 清洗不出干净实体 / 同实体 → 跳过 (漏接优于假接)
            a_node = m.resolve(make_node_id(KIND_ENTITY, a_ent))
            b_node = m.resolve(make_node_id(KIND_ENTITY, b_ent))
            pair = (min(a_node, b_node), max(a_node, b_node))
            if pair in seen_pairs:
                return
            seen_pairs.add(pair)
            ek = m.observe_explicit_link(
                a_node, b_node, turn_id, detail=f"sir_rel:{a_ent}~{b_ent}",
            )
            if ek:
                out.append(ek)

        # 二元关系: 两实体槽 (A<连接>B)
        for pat in _REL_BINARY_PATTERNS:
            for mt in pat.finditer(turn_text):
                _link(_clean_entity(mt.group(1)), _clean_entity(mt.group(2)))
        # 事件-单宾: 固定事件名 + 单实体槽
        for event_name, pat in _REL_EVENT_PATTERNS:
            for mt in pat.finditer(turn_text):
                _link(event_name, _clean_entity(mt.group(1)))

        if save and out:
            m.save()
        return out
    except Exception as exc:
        _log(f"[Weaver] observe_sir_relational_link failed ({exc!r})")
        return out



# energy 与 lens 不对称 (设计 §5 收紧2): lens 安全态是 OFF, energy 安全态是 ON
# (compute_energy 永远在跑, 无总开关)。最危险复发 = energy_grounded_only 翻回 0 =
# 势能又全量吃假焊 = 洗白态复活 (盲点① "翻回 6 天前" 在势能层的对应)。
# [2026-06-07 真机激活后] 默认已翻 1 (接地=缺省安全态)。本护栏校验两类:
#   (1) effective flag=0 → relapse loud 告警 (限流, 非 refuse; 0 仍允许=显式 override 调试)
#   (2) flag=1 但白名单空/混非接地 prov → 配置自洽 violation (防洗白态借配置复活)
_ENERGY_GROUNDED_PROVS = frozenset({PROV_SHARED, PROV_SAID})


def validate_energy_coupling(*, raise_on_violation: bool = False) -> Optional[str]:
    """校验 energy_grounded_only 配置 (对称 lens 耦合护栏 + relapse 告警)。

    effective flag=0 (真机激活后默认已 1, 此为显式 override 回 0): loud relapse 告警
      "生产期势能未接地 = 已知洗白态" (限流由调用方 _energy_coupling_warn_once; 0 仍允许,
      调试用, 但每次都喊防默默翻回)。返 violation str。
    flag=1: spread_grounded_provenance 白名单须 (a) 非空 (b) ⊆ 合法接地 prov {shared,said}。
      - 空 → 势能无边可数 (退化) → violation。
      - 含非接地 prov (embed/cooccur/inferred) → 势能数假焊 = 洗白态借配置复活 → violation。

    返回: None = OK (flag=1 且白名单合法); 否则 violation 描述 str (已 print + bg_log WARNING)。
    raise_on_violation=True → 违规 raise RuntimeError。
    """
    try:
        cfg = get_manifold_config()
        flag = bool(int((cfg.get("energy", {}) or {}).get("energy_grounded_only", 1)))
    except Exception:
        return None
    msg = None
    if not flag:
        # relapse 告警 (盲点①): 真机已激活接地化, effective=0 = 有人/某流程翻回洗白态。
        msg = ("[Energy][COUPLING-GUARD] WARNING relapse: energy_grounded_only=0 "
               "(effective) — 生产期势能未接地 = 已知洗白态 (假焊驱动自发思考 + 洗白 8:0)。"
               "真机已于 2026-06-07 激活接地化; 0 仅供显式 override 调试。"
               "翻回 1 恢复止血 (JARVIS_ENERGY_GROUNDING_DESIGN_P2 §5 flip 检查单)。")
    else:
        wl = set(cfg.get("spread_grounded_provenance", [PROV_SHARED, PROV_SAID]))
        bad = wl - _ENERGY_GROUNDED_PROVS
        if not wl:
            msg = ("[Energy][COUPLING-GUARD] WARNING 误配: energy_grounded_only=1 但 "
                   "spread_grounded_provenance 白名单为空 — 势能无边可数 (退化)。"
                   "应含 {shared,said}。")
        elif bad:
            msg = ("[Energy][COUPLING-GUARD] WARNING 误配: energy_grounded_only=1 但白名单含"
                   f"非接地 provenance {sorted(bad)} — 势能将数假焊 = 洗白态借配置复活 "
                   "(JARVIS_ENERGY_GROUNDING_DESIGN_P2 §5)。白名单应 ⊆ {shared,said}。")
    if msg:
        try:
            print(msg)
        except Exception:
            pass
        _log(msg)
        if raise_on_violation:
            raise RuntimeError(msg)
        return msg
    return None


def default_embed_fn(texts: List[str]) -> List[Optional[List[float]]]:
    """批量 embed (复用 Hippocampus._embed_with_rotation)。

    故障开放: 无 key / 网络挂 / 任何异常 → 返回 [None]*len (Weaver 跳过几何织网,
    不崩)。这是后台慢工, 失败下一轮再试。
    """
    global _EMBED_HIPP
    texts = list(texts)
    if not texts:
        return []
    try:
        with _EMBED_LOCK:
            if _EMBED_HIPP is None:
                # 标准方式建 key_router (load_keys + 三池) 再给 Hippocampus,
                # 否则 embed_content 无 api_key (standalone CLI 场景)。
                from jarvis_hippocampus import Hippocampus
                kr = None
                try:
                    from jarvis_config.keys import load_keys
                    from jarvis_key_router import KeyRouter
                    _keys = load_keys()
                    kr = KeyRouter(
                        main_brain_key=_keys.OPENROUTER_MAIN,
                        google_keys=_keys.GOOGLE_LIST,
                        openrouter_keys=_keys.OPENROUTER_LIST,
                    )
                except Exception as ke:
                    _log(f"[Weaver] key_router 构建失败 ({ke!r}) — embed 将无 key")
                # 海马体永不动红线 (口识体-G0): 体唯一碰 Hippocampus 的地方, 且**只读** —
                # 仅调 _embed_with_rotation (embed 向量), 绝不写/改 hippocampus 永久记忆。
                # tests/_test_body_g0_hippo_immutable.py 静态守护此红线。
                _EMBED_HIPP = Hippocampus(
                    db_path=os.path.join("memory_pool", "jarvis_memory.db"),
                    key_router=kr)
        resp, _key = _EMBED_HIPP._embed_with_rotation(contents=texts)
        out: List[Optional[List[float]]] = []
        embs = list(getattr(resp, "embeddings", []) or [])
        for i in range(len(texts)):
            if i < len(embs):
                out.append(list(embs[i].values))
            else:
                out.append(None)
        return out
    except Exception as exc:
        _log(f"[Weaver] embed failed ({exc!r}) — 本轮跳过几何织网")
        return [None] * len(texts)


# ---------------------------------------------------------------------------
# RelationalWeaver
# ---------------------------------------------------------------------------

class RelationalWeaver:
    """织网者: 维护体的边。harvest → embed(cached) → 几何边 → decay/prune。"""

    def __init__(
        self,
        manifold: Optional[RelationalManifold] = None,
        embed_fn: Optional[EmbedFn] = None,
        *,
        root: str = "",
        threads_path: Optional[str] = None,
        concerns_path: Optional[str] = None,
        relational_path: Optional[str] = None,
        vectors_path: Optional[str] = None,
        stance_path: Optional[str] = None,
        energy_path: Optional[str] = None,
        delta_publisher: Optional[Callable[[Dict[str, Any]], None]] = None,
        event_bus: Optional[Any] = None,
    ):
        self.manifold = manifold if manifold is not None else get_manifold()
        # 口识体-C: 读 SWM nudge/care 警报算体张力 (感知环). None → 生产 lazy 全局 bus。
        self._event_bus = event_bus
        self.embed_fn = embed_fn if embed_fn is not None else default_embed_fn
        mp = os.path.join(root or ".", "memory_pool")
        self.threads_path = threads_path or os.path.join(mp, "self_threads.json")
        self.concerns_path = concerns_path or os.path.join(mp, "concerns.json")
        self.relational_path = relational_path or os.path.join(mp, "relational_state.json")
        self.vectors_path = vectors_path or os.path.join(mp, "manifold_vectors.json")
        self.stance_path = stance_path or os.path.join(mp, "stance.json")
        self.energy_path = energy_path or os.path.join(mp, "body_energy.json")
        # 体势能 (口识体-B3): delta 发布 (默认进 SWM, 注入便于 test) + 跨 weave 状态
        self.delta_publisher = delta_publisher
        self._prev_energy: Dict[str, Dict[str, float]] = {}
        self._recent_deltas: List[Dict[str, Any]] = []
        self._vec_cache: Dict[str, Dict[str, Any]] = {}
        self._weave_count = 0
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._energy_coupling_warn_last: Optional[str] = None  # P2 护栏限流状态
        self._load_vectors()

    def _wcfg(self) -> Dict[str, Any]:
        return get_manifold_config().get("weaver", {}) or {}

    def _ecfg(self) -> Dict[str, Any]:
        return get_manifold_config().get("energy", {}) or {}

    def _energy_coupling_warn_once(self, msg: str) -> None:
        """🆕 [body-diff-P2 护栏 层2 限流 / Sir 2026-06-06] 误配 warn 只在状态变化时 log
        一次 (weave 600s 一跑, 不刷屏; validate_energy_coupling 已 print+bg_log, 此处限流)。"""
        if msg != self._energy_coupling_warn_last:
            self._energy_coupling_warn_last = msg
            _log(f"[Weaver] energy coupling 误配持续: {msg[:80]}")

    # ---- json read helpers (robust) ----
    @staticmethod
    def _read_json(path: str) -> Any:
        try:
            if not os.path.exists(path):
                return {}
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    # ---- harvest nodes (体只引用真理源, 不重存) ----
    def harvest_nodes(self) -> Dict[str, str]:
        cfg = self._wcfg()
        maxc = int(cfg.get("max_text_chars", 400))
        minc = int(cfg.get("min_node_text_chars", 4))
        out: Dict[str, str] = {}

        def _add(nid: str, *parts: Optional[str]) -> None:
            text = " ".join(p.strip() for p in parts if p and p.strip()).strip()
            if len(text) >= minc:
                out[nid] = text[:maxc]

        # threads (self_threads.json)
        tdata = self._read_json(self.threads_path)
        if isinstance(tdata, dict):
            for t in tdata.get("threads", []) or []:
                if not isinstance(t, dict):
                    continue
                tid = t.get("thread_id")
                if tid and t.get("status") != "let_go":
                    _add(make_node_id(KIND_THREAD, tid), t.get("summary"))

        # concerns (concerns.json: top-level id -> obj)
        cdata = self._read_json(self.concerns_path)
        if isinstance(cdata, dict):
            for cid, c in cdata.items():
                if not isinstance(c, dict) or cid.startswith("_"):
                    continue
                if c.get("state") == "archived":
                    continue
                _add(make_node_id(KIND_CONCERN, c.get("id", cid)),
                     c.get("what_i_watch"), c.get("why_i_care"))

        # relational_state.json: inside_jokes + unspoken_protocols
        rdata = self._read_json(self.relational_path)
        if isinstance(rdata, dict):
            for jid, j in (rdata.get("inside_jokes") or {}).items():
                if isinstance(j, dict) and j.get("state") == "active":
                    _add(make_node_id(KIND_JOKE, j.get("id", jid)),
                         j.get("phrase"), j.get("birth_context"))
            for pid, p in (rdata.get("unspoken_protocols") or {}).items():
                if isinstance(p, dict) and p.get("state") == "active":
                    _add(make_node_id(KIND_PROTOCOL, p.get("id", pid)), p.get("rule"))

        # 立场 (体-P4): active 立场进体, 让 Jarvis 自己的 view 也长边
        sdata = self._read_json(self.stance_path)
        if isinstance(sdata, dict):
            for sid, s in (sdata.get("stances") or {}).items():
                if isinstance(s, dict) and s.get("state") == "active":
                    _add(make_node_id(KIND_STANCE, s.get("stance_id", sid)), s.get("claim"))
        return out

    # ---- vector cache (embed 一次, 文本不变就复用) ----
    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:16]

    def _load_vectors(self) -> None:
        data = self._read_json(self.vectors_path)
        if isinstance(data, dict):
            self._vec_cache = data.get("vectors", {}) or {}

    def _save_vectors(self) -> None:
        payload = {"_meta": {"schema": "manifold_vectors",
                             "updated_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
                             "count": len(self._vec_cache)},
                   "vectors": self._vec_cache}
        tmp = self.vectors_path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self.vectors_path) or ".", exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, self.vectors_path)
        except Exception as exc:
            _log(f"[Weaver] save vectors failed ({exc!r})")

    def _ensure_vectors(self, nodes: Dict[str, str]) -> Dict[str, List[float]]:
        """保证 nodes 都有最新向量 (文本变了才重 embed)。返回 {node: vec}。"""
        # 清掉已消失节点的缓存
        for nid in list(self._vec_cache.keys()):
            if nid not in nodes:
                del self._vec_cache[nid]
        # 找需要 (重)embed 的
        need = [nid for nid, txt in nodes.items()
                if self._vec_cache.get(nid, {}).get("hash") != self._hash(txt)]
        if need:
            bs = max(1, int(self._wcfg().get("embed_batch_size", 32)))
            for i in range(0, len(need), bs):
                chunk = need[i:i + bs]
                vecs = self.embed_fn([nodes[n] for n in chunk])
                for n, v in zip(chunk, vecs):
                    if v:
                        self._vec_cache[n] = {"hash": self._hash(nodes[n]),
                                              "vec": list(v), "ts": time.time()}
            self._save_vectors()
        return {nid: self._vec_cache[nid]["vec"]
                for nid in nodes if nid in self._vec_cache}

    # ---- 几何织网 (体-P2) ----
    def weave_geometric(self, nodes: Optional[Dict[str, str]] = None,
                        now: Optional[float] = None) -> int:
        now = time.time() if now is None else now
        if nodes is None:
            nodes = self.harvest_nodes()
        vecs = self._ensure_vectors(nodes)
        ids = list(vecs.keys())
        if len(ids) < 2:
            return 0
        cfg = get_manifold_config()
        thr = float(cfg.get("embed_threshold", 0.72))
        topk = int(cfg.get("embed_top_k_per_node", 8))
        # 🆕 [body-diff-P0a] 接地不对称折扣 (不变量②): 两端都自产 → embed 边权打折.
        sp_kinds = set(cfg.get("self_produced_kinds", ["thread", "joke", "proto"]))
        sp_discount = float(cfg.get("self_produced_edge_discount", 0.5))
        M = np.array([vecs[i] for i in ids], dtype=np.float32)
        norms = np.linalg.norm(M, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        Mn = M / norms
        sim = Mn @ Mn.T
        merge_thr = float(cfg.get("merge_threshold", 0.90))
        seen = set()
        added = 0
        dup_pairs: List[tuple] = []
        for i in range(len(ids)):
            row = sim[i].copy()
            row[i] = -1.0
            order = np.argsort(row)[::-1][:topk]
            for j in order:
                c = float(row[j])
                if c < thr:
                    break
                a, b = ids[i], ids[int(j)]
                key = (a, b) if a <= b else (b, a)
                if key in seen:
                    continue
                seen.add(key)
                # 接地不对称: 两端都自产 (thread/joke/proto) → 边权折扣 (不删节点, 只降权)
                _ws = 1.0
                if (split_node_id(a)[0] in sp_kinds
                        and split_node_id(b)[0] in sp_kinds):
                    _ws = sp_discount
                if self.manifold.add_geometric_edge(a, b, c, weight_scale=_ws, now=now):
                    added += 1
                if c >= merge_thr:           # 近重复 → 候选合并
                    dup_pairs.append((a, b))
        # 口识体-D2: 近重复 → 合并 alias (代表=度数高/更 established; 不删源)
        merged = 0
        for a, b in dup_pairs:
            ra, rb = self.manifold.resolve(a), self.manifold.resolve(b)
            if ra == rb:
                continue
            if self.manifold.degree(ra) >= self.manifold.degree(rb):
                rep, dup = ra, rb
            else:
                rep, dup = rb, ra
            if self.manifold.add_alias(dup, rep):
                merged += 1
        if merged:
            _log(f"[Weaver/D2] 合并近重复 {merged} 对 (cosine>={merge_thr}) — 防 bloat, 不动源")
        return added

    # ---- 维护 ----
    def maintain(self, now: Optional[float] = None) -> int:
        now = time.time() if now is None else now
        self.manifold.apply_decay(now=now)
        return self.manifold.prune(now=now)

    # 🆕 [体 P4 / Sir 2026-06-01] 内容中性算法健康: 自动合并近重复节点 (收 blob 体积) ===
    # charter JARVIS_ANCHOR_DESIGN.md §6 + 理念源 §6/0601 决议: 体复杂度走**内容中性算法
    # 健康**(模块度/去重), **非锚**(衡碰体仅护定点)。本法复用 D2(manifold_dump cmd_merge_dups)
    # 纯几何去重: 缓存向量 cosine >= threshold → add_alias(dup→rep, rep=度数高)。
    # **不删源、可逆、内容中性**(纯 embedding 相似, 不做任何内容/价值/锚判断)。
    def auto_merge_near_dups(self, threshold: float = 0.93,
                             max_merges: int = 10) -> int:
        """blob 时合并近重复节点收体积。返回合并对数。失败非致命 (返 0)。"""
        try:
            import numpy as np
            data = self._read_json(self.vectors_path) or {}
            vec = (data.get("vectors") or {}) if isinstance(data, dict) else {}
            ids = [k for k in vec
                   if isinstance(vec.get(k), dict) and vec[k].get("vec")]
            if len(ids) < 2:
                return 0
            M = np.array([vec[i]["vec"] for i in ids], dtype=np.float32)
            nrm = np.linalg.norm(M, axis=1, keepdims=True)
            nrm[nrm == 0] = 1.0
            Mn = M / nrm
            sim = Mn @ Mn.T
            pairs = []
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    c = float(sim[i, j])
                    if c >= threshold:
                        pairs.append((c, ids[i], ids[j]))
            pairs.sort(reverse=True)
            merged = 0
            for c, a, b in pairs:
                if merged >= max_merges:
                    break
                ra, rb = self.manifold.resolve(a), self.manifold.resolve(b)
                if ra == rb:
                    continue
                if self.manifold.degree(ra) >= self.manifold.degree(rb):
                    rep, dup = ra, rb
                else:
                    rep, dup = rb, ra
                if self.manifold.add_alias(dup, rep):
                    merged += 1
            if merged:
                self.manifold.save()
            return merged
        except Exception as exc:
            _log(f"[Weaver] auto_merge_near_dups 异常: {exc!r}")
            return 0

    # ---- 体势能 E (口识体-B3): 自转的坡度 ----
    def _concern_severity_map(self) -> Dict[str, float]:
        """{concern node_id: severity} for active concerns (张力源料)。

        🆕 [反刍治本-Fix3 / Sir 2026-06-02] 只计真 active + triggers_proactive 的 concern。
        snoozed (Sir 暂压) / archived / dismiss 软关闭 (triggers_proactive=False) 的不喂
        体张力 — 否则 snooze/dismiss 等于没用 (真机: keyrouter snooze 到 7/2 仍 tension=1.0)。
        """
        out: Dict[str, float] = {}
        cdata = self._read_json(self.concerns_path)
        if isinstance(cdata, dict):
            for cid, c in cdata.items():
                if not isinstance(c, dict) or cid.startswith("_"):
                    continue
                # Fix3: 只 active 状态喂张力 (snoozed/review/archived 不喂)
                if c.get("state") != "active":
                    continue
                # Fix3: dismiss 软关闭 (triggers_proactive=False) 也不喂体张力
                if not c.get("triggers_proactive", True):
                    continue
                try:
                    sev = float(c.get("severity", 0.0) or 0.0)
                except (TypeError, ValueError):
                    sev = 0.0
                out[make_node_id(KIND_CONCERN, c.get("id", cid))] = sev
        return out

    def _nudge_tension_map(self, valid_concerns: set,
                           now: Optional[float] = None) -> Dict[str, float]:
        """口识体-C: 读 SWM 近期 nudge/care 警报 → concern node 张力 (感知环穿体)。

        "一个 wellness/proactive 警报 = 体的张力" (grounded by event salience): nudge 不
        再直推 __NUDGE__, 退化为体能量, 识经 body_delta attend。**只计真实存在的 active
        concern node (valid_concerns), 不造幻影能量** (准则 5 全接地)。
        soul_alignment_advice 取 missed_concern_ids (Jarvis 漏掉的 = 张力)。失败返 {}。
        """
        cfg = self._ecfg()
        try:
            if not int(cfg.get("nudge_tension_enabled", 1)):
                return {}
        except (TypeError, ValueError):
            pass
        bus = self._event_bus if self._event_bus is not None else _default_event_bus()
        if bus is None:
            return {}
        etypes = set(cfg.get("nudge_tension_etypes", []) or [])
        if not etypes:
            return {}
        window = float(cfg.get("nudge_window_s", 600.0))
        per_w = float(cfg.get("nudge_tension_per_event", 0.5))
        cap = float(cfg.get("nudge_tension_cap", 1.5))
        try:
            events = bus.recent_events(within_seconds=window, types=etypes)
        except Exception as exc:
            _log(f"[Weaver/口识体-C] nudge tension read failed ({exc!r})")
            return {}
        out: Dict[str, float] = collections.defaultdict(float)
        for e in events or []:
            meta = e.get("metadata") or {}
            try:
                sal = float(e.get("salience", 0.5) or 0.5)
            except (TypeError, ValueError):
                sal = 0.5
            cids: List[str] = []
            cid = meta.get("concern_id")
            if cid:
                cids.append(str(cid))
            missed = meta.get("missed_concern_ids")
            if isinstance(missed, (list, tuple)):
                cids.extend(str(m) for m in missed if m)
            for c in cids:
                nid = make_node_id(KIND_CONCERN, c)
                if nid in valid_concerns:
                    out[nid] += per_w * max(0.0, min(1.0, sal))
        return {nid: min(v, cap) for nid, v in out.items()}

    def _habituation_map(self, now: Optional[float] = None) -> Dict[str, float]:
        """习惯化因子 {node_id: factor∈[floor,1.0]} — 接地的"放电反馈缺口"补全。

        Sir 2026-06-02 反刍治本: 设计 §3 承诺 "识放电→该区 E 降→不再醒", 但唯一 wired
        放电通道是 stance-coverage。低 agency concern (hydration) 识反复 attend 却只
        adjust_notes (不改 severity 不立 stance) → 永不放电 → tension=severity 每 weave
        重算 → 反复被召唤 ("认识到自己反刍却停不下" = 结构缺口, 早于衡/锚)。

        机制 (纯物理, 无 LLM, 准则 5 接地): 消费识每 tick publish 的 body_attention_outcome
        event (metadata: node, discharged)。某 node 被反复 attend 却 discharged=False →
        非放电 attend 累积 → 超 free_attends 后该 node tension ×= decay_base^excess (graded,
        到 floor 止)。真放电 (discharged=True) → 该 node 习惯化重置 (1.0)。久不 attend (>
        recovery_s) → 恢复 (1.0, spontaneous recovery)。

        只乘到 tension 源 1 (concern severity standing): novelty/drift/nudge/dyad 不受习惯
        化 → 真新进展 (novelty↑/drift↑) 或新外部警报 (nudge) 自然 dishabituate 突破。
        """
        now = time.time() if now is None else now
        cfg = self._ecfg()
        try:
            if not int(cfg.get("habituation_enabled", 1)):
                return {}
        except (TypeError, ValueError):
            return {}
        bus = self._event_bus if self._event_bus is not None else _default_event_bus()
        if bus is None:
            return {}
        etype = str(cfg.get("habituation_outcome_etype", "body_attention_outcome"))
        window = float(cfg.get("habituation_window_s", 1800.0))
        free = int(cfg.get("habituation_free_attends", 2))
        base = float(cfg.get("habituation_decay_base", 0.6))
        floor = float(cfg.get("habituation_floor", 0.15))
        recovery = float(cfg.get("habituation_recovery_s", 3600.0))
        base = max(0.0, min(0.999, base))
        floor = max(0.0, min(1.0, floor))
        try:
            events = bus.recent_events(within_seconds=window, types={etype})
        except Exception as exc:
            _log(f"[Weaver/habituation] outcome read failed ({exc!r})")
            return {}
        # 按 node 聚: 时间序列 [(ts, discharged)]
        per_node: Dict[str, List[tuple]] = collections.defaultdict(list)
        for e in events or []:
            meta = e.get("metadata") or {}
            nid = self.manifold.resolve(str(meta.get("node") or ""))  # alias→代表
            if not nid:
                continue
            try:
                ts = float(e.get("timestamp", now) or now)
            except (TypeError, ValueError):
                ts = now
            per_node[nid].append((ts, bool(meta.get("discharged", False))))
        out: Dict[str, float] = {}
        for nid, seq in per_node.items():
            seq.sort(key=lambda x: x[0])
            last_ts = seq[-1][0]
            # spontaneous recovery: 久不 attend → 恢复
            if now - last_ts > recovery:
                continue  # factor 1.0 (不衰)
            # 从最近一次放电之后起算非放电 attend 数 (放电 = 重置点)
            non_discharge = 0
            for _ts, discharged in seq:
                if discharged:
                    non_discharge = 0   # 放电重置
                else:
                    non_discharge += 1
            excess = max(0, non_discharge - free)
            if excess <= 0:
                continue  # 仍在免费窗内 → 不衰
            factor = max(floor, base ** excess)
            out[nid] = factor
        return out

    def _stance_covered_concerns(self) -> set:
        """有 active stance 覆盖的 concern node_id 集合 (张力已化解 = 不计能量)。"""
        covered: set = set()
        sdata = self._read_json(self.stance_path)
        if isinstance(sdata, dict):
            for s in (sdata.get("stances") or {}).values():
                if isinstance(s, dict) and s.get("state") == "active":
                    about = (s.get("about") or "").strip()
                    if about:
                        # about 可能是 concern id 原值 或 已命名空间化
                        covered.add(about)
                        covered.add(make_node_id(KIND_CONCERN, about))
        return covered

    # ---- 口识体-F: 张力 dyad (立场↔Sir关心 边, 阻力/老师载体) ----
    def _active_stance_dyads(self) -> List[tuple]:
        """返回 [(stance_node, concern_node, stance_id, confidence)] for 高置信 active
        stance whose about 指向一个 concern。grounded by stance_id (准则 5)。

        这是阻力的结构载体 (§6): 立场 = Jarvis 对某 concern 的坚定 view。当置信够高,
        体在那个区有"立场张力"(可能推开 Sir). 真冲突 valence (逆 Sir 当下意愿) 待
        Sir-wish 信号成熟再精算, 现保守: 高置信 active stance about concern = 基线阻力。
        """
        cfg = self._ecfg()
        try:
            if not int(cfg.get("stance_dyad_enabled", 1)):
                return []
        except (TypeError, ValueError):
            pass
        min_conf = float(cfg.get("stance_dyad_min_confidence", 0.6))
        out: List[tuple] = []
        sdata = self._read_json(self.stance_path)
        if not isinstance(sdata, dict):
            return out
        for sid, s in (sdata.get("stances") or {}).items():
            if not isinstance(s, dict) or s.get("state") != "active":
                continue
            try:
                conf = float(s.get("confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                conf = 0.0
            if conf < min_conf:
                continue
            about = (s.get("about") or "").strip()
            if not about:
                continue
            stance_node = make_node_id(KIND_STANCE, s.get("stance_id", sid))
            concern_node = make_node_id(KIND_CONCERN, about)
            out.append((stance_node, concern_node, str(s.get("stance_id", sid)), conf))
        return out

    def weave_stance_dyads(self, now: Optional[float] = None) -> int:
        """织 立场↔concern dyad 边 (grounded by stance_id). 返新增/强化边数。

        准则 5: ref=stance_id (接地, 非幻觉)。inferred=False (这是真实结构关系, 非 LLM
        猜的因果)。stance node 必须真存在于体 (harvest_nodes 含 active stance) 才连。
        """
        now = time.time() if now is None else now
        dyads = self._active_stance_dyads()
        if not dyads:
            return 0
        added = 0
        for stance_node, concern_node, sid, conf in dyads:
            # PROV_SHARED: 立场与 concern 共享同一关注对象 (结构边, 非几何). 接地 stance_id。
            if self.manifold.add_edge(
                    stance_node, concern_node, PROV_SHARED, ref=sid,
                    detail=f"stance-dyad conf={conf:.2f}", weight_scale=conf,
                    accumulate=False, now=now):
                added += 1
        return added

    def _stance_dyad_tension_map(self) -> Dict[str, float]:
        """{stance_node: 立场张力} — 高置信 active stance about concern 的基线阻力势能。"""
        cfg = self._ecfg()
        try:
            if not int(cfg.get("stance_dyad_enabled", 1)):
                return {}
        except (TypeError, ValueError):
            return {}
        per = float(cfg.get("stance_dyad_tension", 0.4))
        out: Dict[str, float] = {}
        for stance_node, _concern_node, _sid, conf in self._active_stance_dyads():
            out[stance_node] = per * conf   # 越坚定 → 阻力势能越高
        return out

    def compute_energy(
        self, new_edge_keys: set, pre_snapshot: Dict[str, Dict[str, Any]],
        post_snapshot: Dict[str, Dict[str, Any]], now: Optional[float] = None,
    ) -> Dict[str, Dict[str, float]]:
        """算每节点的势能 E = w_nov·新颖 + w_drift·漂移 + w_tension·张力 (接地, 无 LLM)。"""
        now = time.time() if now is None else now
        cfg = self._ecfg()
        drift_min = float(cfg.get("drift_min", 0.05))
        # 🆕 [body-diff-P2 / Sir 2026-06-06] 接地化门 (默 0 = 老行为全量数边). 1 时 novelty/
        # drift 只数接地边 (统一 is_grounded 谓词, 白名单 = top-level spread_grounded_provenance
        # {shared,said}, spread+energy 共用)。tension 不数边、不受此门影响。设计 §4 取舍:
        # cooccur/embed 边 novelty/drift 贡献→0 (接受丢失弱共现先验, 真关系以接地边重现)。
        _grounded_only = bool(int(cfg.get("energy_grounded_only", 1)))
        _grounded_provs = set(get_manifold_config().get(
            "spread_grounded_provenance", [PROV_SHARED, PROV_SAID])) if _grounded_only else None
        energy: Dict[str, Dict[str, float]] = collections.defaultdict(
            lambda: {"novelty": 0.0, "drift": 0.0, "tension": 0.0, "total": 0.0})
        # 新颖: 本轮新边的权重计给两端
        for key in new_edge_keys:
            e = post_snapshot.get(key)
            if e:
                if _grounded_provs is not None and not is_grounded(
                        e.get("provs") or set(), _grounded_provs):
                    continue  # 接地化: 纯假焊新边 (embed/cooccur) 不供 novelty 势能
                energy[e["a"]]["novelty"] += e["w"]
                energy[e["b"]]["novelty"] += e["w"]
        # 漂移: 非新边里权重变动超 drift_min 的
        for key, e in post_snapshot.items():
            if key in new_edge_keys or key not in pre_snapshot:
                continue
            if _grounded_provs is not None and not is_grounded(
                    e.get("provs") or set(), _grounded_provs):
                continue  # 接地化: 纯假焊边权变动不供 drift 势能
            d = abs(e["w"] - pre_snapshot[key]["w"])
            if d >= drift_min:
                energy[e["a"]]["drift"] += d
                energy[e["b"]]["drift"] += d
        # 张力源 1: 高 severity concern 且无 active stance 覆盖
        # 习惯化补全 (Sir 2026-06-02): 识反复 attend 某 concern 却不放电 (只 adjust_notes,
        # 不改 severity 不立 stance) → 该 concern tension ×= habituation factor (graded 衰
        # 到 floor). 补全设计 §3 "放电→E降→不再醒" 的缺口 (唯一 wired 放电是 stance-coverage,
        # 低 agency concern 永不放电 → 反复召唤). 真放电/真新进展 (novelty/drift) → 突破。
        sev_min = float(cfg.get("tension_severity_min", 0.40))
        sev = self._concern_severity_map()
        covered = self._stance_covered_concerns()
        habit = self._habituation_map(now=now)
        for nid, s in sev.items():
            if s >= sev_min and nid not in covered:
                energy[nid]["tension"] += s * habit.get(nid, 1.0)
        # 张力源 2 (口识体-C): 近期 nudge/care 警报 → 体张力 (感知环穿体).
        # 新外部警报是新扰动 → 不受 stance 覆盖压制 (放电靠 event 老化出窗 + 识 attend);
        # delta-on-rise 机制保证 tension 平台期不重复派 delta (杜绝 churn)。
        for nid, t in self._nudge_tension_map(set(sev.keys()), now=now).items():
            energy[nid]["tension"] += t
        # 张力源 3 (口识体-F): 立场 dyad — 高置信 active stance 在 stance 节点上的阻力
        # 势能 (Jarvis 持有坚定 view = 老师/阻力载体). 计在 stance 节点, 让识 attend 自己
        # 的立场区 (反思/巩固/或被 Sir outcome 削弱后放电)。grounded by stance_id。
        for nid, t in self._stance_dyad_tension_map().items():
            energy[nid]["tension"] += t
        # total
        wn, wd, wt = (float(cfg.get("w_novelty", 1.0)),
                      float(cfg.get("w_drift", 0.6)), float(cfg.get("w_tension", 1.2)))
        out: Dict[str, Dict[str, float]] = {}
        for nid, comp in energy.items():
            comp["total"] = wn * comp["novelty"] + wd * comp["drift"] + wt * comp["tension"]
            out[nid] = dict(comp)
        return out

    def _diff_and_emit_deltas(
        self, curr_energy: Dict[str, Dict[str, float]], now: float,
    ) -> List[Dict[str, Any]]:
        """对比上轮势能 → 能量上升超阈的节点 → 派 body_delta (唤醒识)。"""
        cfg = self._ecfg()
        thr = float(cfg.get("delta_threshold", 0.30))
        wn, wd, wt = (float(cfg.get("w_novelty", 1.0)),
                      float(cfg.get("w_drift", 0.6)), float(cfg.get("w_tension", 1.2)))
        deltas: List[Dict[str, Any]] = []
        for nid, comp in curr_energy.items():
            prev_total = self._prev_energy.get(nid, {}).get("total", 0.0)
            rise = comp["total"] - prev_total
            if rise >= thr:
                kind = max((("novelty", comp["novelty"] * wn),
                            ("drift", comp["drift"] * wd),
                            ("tension", comp["tension"] * wt)), key=lambda x: x[1])[0]
                deltas.append({
                    "node": nid, "kind": kind, "magnitude": round(rise, 3),
                    "energy": round(comp["total"], 3),
                    "ts": now, "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
                })
        deltas.sort(key=lambda d: d["magnitude"], reverse=True)
        deltas = deltas[: int(cfg.get("max_deltas_per_weave", 12))]
        for d in deltas:
            if self.delta_publisher:
                try:
                    self.delta_publisher(d)
                except Exception:
                    pass
        self._recent_deltas = deltas
        self._prev_energy = curr_energy
        return deltas

    def _save_energy(self, curr_energy: Dict[str, Dict[str, float]],
                     deltas: List[Dict[str, Any]]) -> None:
        top = sorted(curr_energy.items(), key=lambda x: x[1]["total"], reverse=True)[:30]
        payload = {
            "_meta": {"schema": "body_energy",
                      "updated_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
                      "node_count": len(curr_energy)},
            "top_energy": [{"node": n, **c} for n, c in top],
            "recent_deltas": deltas,
        }
        tmp = self.energy_path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self.energy_path) or ".", exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.energy_path)
        except Exception as exc:
            _log(f"[Weaver] save energy failed ({exc!r})")

    def recent_deltas(self) -> List[Dict[str, Any]]:
        return list(self._recent_deltas)

    # ---- 全量一轮 ----
    def weave_once(self, now: Optional[float] = None) -> Dict[str, Any]:
        now = time.time() if now is None else now
        with self._lock:
            # 体势能: weave 前快照边权 (算 novelty/drift)
            pre_snapshot = self.manifold.edge_snapshot(now=now)
            nodes = self.harvest_nodes()
            added = self.weave_geometric(nodes, now=now)
            # 口识体-F: 织立场 dyad 边 (立场↔concern, grounded by stance_id, 阻力载体)
            dyad_added = self.weave_stance_dyads(now=now)
            if dyad_added:
                added += dyad_added
                _log(f"[Weaver/F] 织 {dyad_added} 条立场 dyad 边 (阻力/老师载体)")
            self._weave_count += 1
            pruned = 0
            dev = int(self._wcfg().get("decay_every_n_weaves", 6))
            if dev > 0 and self._weave_count % dev == 0:
                pruned = self.maintain(now=now)
            # 体-P3: 重算语义曲面 (面随边变, 廉价图 BFS)
            surfaces = self.manifold.compute_surfaces(now=now)
            self.manifold.set_surfaces(surfaces)
            self.manifold.save()
            # 体势能 E (口识体-B3): 算势能 + diff → 派 body_delta 唤醒识
            post_snapshot = self.manifold.edge_snapshot(now=now)
            new_keys = set(post_snapshot.keys()) - set(pre_snapshot.keys())
            # 🆕 [body-diff-P2 耦合护栏 层2: 热路径 / Sir 2026-06-06] 误配 (flag=1 但白名单
            # 非法) 不静默 — 限流 bg_log 一次 (compute_energy 仍按 flag 跑, 配置错由层1 启动
            # 警 + 此处提醒; 不阻 weave 主流, 准则1 高效)。
            try:
                _ec_violation = validate_energy_coupling()
                if _ec_violation:
                    self._energy_coupling_warn_once(_ec_violation)
            except Exception:
                pass
            curr_energy = self.compute_energy(new_keys, pre_snapshot, post_snapshot, now=now)
            deltas = self._diff_and_emit_deltas(curr_energy, now)
            self._save_energy(curr_energy, deltas)
        # 🆕 [anchor-P0-activation-wiring 方案A / 2026-06-07] facets producer + reverify。
        # flag-gated (默认 off → 整段不执行, weave 行为逐字节不变)。在 manifold save 之后
        # (数据最新)、锁外 (facets store 自带锁)。整段裹 try/except — facets 任何异常都
        # **绝不**拖垮 weave 这个体维护主循环 (准则1)。节奏离散 (每 weave 一次 producer /
        # 每 R 次 weave 一次 reverify), 零 score/sort/argmax — 扫描序由 iter_grounded_nodes
        # 插入序决定, 跑的时机由周期/计数决定, 不看任何显著度。
        try:
            import jarvis_identity_facets as _facets
            if _facets.is_facets_enabled():
                try:
                    _facets.scan_and_crystallize()
                except Exception as _fe:
                    _log(f"[Weaver/facets] scan_and_crystallize 异常 (swallow, 不拖垮 weave): {_fe!r}")
                # reverify: 离散计数节拍 (% R, 复用 decay 同款离散节奏)。时间只触发
                # 重核, 降级只由证据 (接地边没了), 不按时长直接降级 (B.6 第3条)。
                _facets_R = int(self._wcfg().get("decay_every_n_weaves", 6)) or 6
                if self._weave_count % _facets_R == 0:
                    try:
                        _facets.reverify_all_facets()
                    except Exception as _re:
                        _log(f"[Weaver/facets] reverify_all_facets 异常 (swallow): {_re!r}")
        except Exception:
            pass  # import / flag 读取失败也绝不影响 weave
        stats = self.manifold.stats(now=now)
        # 复杂度度量 (closure D1): 测结构质量, 不只数体积
        cx = self.manifold.complexity_report(now=now)
        stats.update({"weave_count": self._weave_count, "nodes": len(nodes),
                      "embed_edges_added": added, "pruned": pruned,
                      "surface_count": len(surfaces), "deltas": len(deltas),
                      "energy_nodes": len(curr_energy), "complexity": cx})
        _log(f"[Weaver] weave#{self._weave_count} nodes={len(nodes)} "
             f"embed+={added} pruned={pruned} edges={stats['edge_count']} "
             f"surfaces={len(surfaces)} Δ={len(deltas)} "
             f"cx={cx['health']}/{cx['complexity_score']}")
        if cx["health"] in ("blob", "over_dense"):
            _log(f"⚠️ [Weaver/complexity] {cx['health']}: largest_surface_frac="
                 f"{cx['largest_surface_frac']} density={cx['density']} "
                 f"→ 体积大复杂度低, 待 merge (closure D2)")
            # 🆕 [体 P4 / Sir 2026-06-01] blob → 自动内容中性去重 (收体积), gated vocab.
            try:
                from jarvis_relational_manifold import get_manifold_config as _gmc
                _am = (_gmc().get("auto_merge_dups") or {})
                if _am.get("enabled", True):
                    _n = self.auto_merge_near_dups(
                        threshold=float(_am.get("threshold", 0.93)),
                        max_merges=int(_am.get("max_merges_per_weave", 10)))
                    if _n:
                        cx = self.manifold.complexity_report(now=now)
                        stats["complexity"] = cx
                        _log(f"🧹 [Weaver/P4] blob → 自动合并近重复 {_n} 对 (内容中性去重,"
                             f" 可逆 alias); 后 frac={cx['largest_surface_frac']}")
            except Exception as _e:
                _log(f"[Weaver/P4] auto_merge skip: {_e!r}")
        return stats

    # ---- daemon ----
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self.run_forever,
                                        name="RelationalWeaver", daemon=True)
        self._thread.start()
        _log("[Weaver] 织网者启动 (后台慢工)")

    def run_forever(self) -> None:
        cfg = self._wcfg()
        interval = float(cfg.get("weave_interval_s", 600))
        initial = float(cfg.get("initial_delay_s", 90))
        # 启动后先等 boot 稳定再第一次 weave (不和启动抢资源)
        if self._stop.wait(initial):
            return
        while not self._stop.is_set():
            try:
                self.weave_once()
            except Exception as exc:
                import traceback
                _log(f"[Weaver] weave_once 异常: {exc!r}\n{traceback.format_exc()}")
            if self._stop.wait(interval):
                break

    def stop(self) -> None:
        self._stop.set()
