# -*- coding: utf-8 -*-
"""[P0+19-6.bcde 收尾] 批量改造所有"path = ... 'jarvis_nerve.py'" 模式的源码扫描测试 → corpus helper

匹配三种典型模式：
  1. path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'jarvis_nerve.py'))
     with open(path, 'r', encoding='utf-8') as f:
         src = f.read()
  2. with open(os.path.join(ROOT, 'jarvis_nerve.py'), 'r', encoding='utf-8') as f:
         cls.src = f.read()
  3. (在 setUpClass 内的同样模式)

全部替换为：
  sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
  from _source_corpus import read_nerve_corpus
  src = read_nerve_corpus()  # 或 cls.src = ...
"""
import os
import re
import glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.join(ROOT, 'tests')


# 已经改造过的（用 _read('jarvis_nerve.py') → read_nerve_corpus() 或 corpus helper）跳过
ALREADY_DONE = {
    '_test_p0_plus_18_d_brain_db_link.py',
    '_test_p0_plus_18_e_link_close.py',
    '_test_p0_plus_18_f_perf_and_honesty.py',
    '_test_p0_plus_18_c2_reminder_firing.py',
    '_test_p0_plus_18_c3_to_c14_remaining.py',
    '_test_p1_fixes.py',
    '_test_r8_axis3_l1_offer_guard.py',
}


# 模式 1: path = os.path.abspath(...) + with open(path) + cls.xxx/xxx = f.read()
PATTERN_1 = re.compile(
    r"(\s*)path\s*=\s*os\.path\.abspath\(\s*os\.path\.join\(\s*os\.path\.dirname\(__file__\)\s*,\s*['\"]\.\.['\"]\s*,\s*['\"]jarvis_nerve\.py['\"]\s*\)\s*\)\s*\n"
    r"\s*with\s+open\(\s*path\s*,\s*['\"]r['\"]\s*,\s*encoding\s*=\s*['\"]utf-8['\"]\s*\)\s+as\s+(\w+)\s*:\s*\n"
    r"\s*(\S+)\s*=\s*\2\.read\(\)",
    re.MULTILINE,
)

# 模式 2: with open(os.path.join(ROOT, 'jarvis_nerve.py'), ...) as f: cls.xxx = f.read()
PATTERN_2 = re.compile(
    r"(\s*)with\s+open\(\s*os\.path\.join\(\s*ROOT\s*,\s*['\"]jarvis_nerve\.py['\"]\s*\)\s*,\s*['\"]r['\"]\s*,\s*encoding\s*=\s*['\"]utf-8['\"]\s*\)\s+as\s+(\w+)\s*:\s*\n"
    r"\s*(\S+)\s*=\s*\2\.read\(\)",
    re.MULTILINE,
)


def make_replacement_1(match):
    indent = match.group(1)
    var = match.group(3)  # 例 src / cls.src / cls.nerve_src
    return (
        f'{indent}# [P0+19 corpus 扫源码 — auto-patched]\n'
        f'{indent}import sys as _sys\n'
        f'{indent}_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n'
        f'{indent}from _source_corpus import read_nerve_corpus as _read_corpus\n'
        f'{indent}{var} = _read_corpus()'
    )


def make_replacement_2(match):
    indent = match.group(1)
    var = match.group(3)
    return (
        f'{indent}# [P0+19 corpus 扫源码 — auto-patched]\n'
        f'{indent}import sys as _sys\n'
        f'{indent}_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n'
        f'{indent}from _source_corpus import read_nerve_corpus as _read_corpus\n'
        f'{indent}{var} = _read_corpus()'
    )


def patch_file(filepath: str) -> int:
    """Patch 单文件。返回替换次数。"""
    name = os.path.basename(filepath)
    if name in ALREADY_DONE:
        return 0
    with open(filepath, 'r', encoding='utf-8') as f:
        original = f.read()
    n1 = len(PATTERN_1.findall(original))
    n2 = len(PATTERN_2.findall(original))
    if n1 + n2 == 0:
        return 0
    patched = PATTERN_1.sub(make_replacement_1, original)
    patched = PATTERN_2.sub(make_replacement_2, patched)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(patched)
    return n1 + n2


def main():
    total = 0
    affected_files = []
    for filepath in sorted(glob.glob(os.path.join(TESTS_DIR, '_test_*.py'))):
        n = patch_file(filepath)
        if n > 0:
            affected_files.append((os.path.basename(filepath), n))
            total += n
    print(f'[P0+19 corpus] Total patches: {total} across {len(affected_files)} files')
    for name, n in affected_files:
        print(f'  {name}: {n}')


if __name__ == '__main__':
    main()
