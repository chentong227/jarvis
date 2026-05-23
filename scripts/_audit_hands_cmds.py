import os, re
hd='l4_hands_pool'
files = sorted([f for f in os.listdir(hd) if f.endswith('.py') and 'test' not in f])
for f in files:
    p=os.path.join(hd, f)
    with open(p, 'r', encoding='utf-8') as fp:
        src = fp.read()
    cmds = re.findall(r"cmd\s*==\s*['\"]([^'\"]+)['\"]", src)
    cmds_unique = list(dict.fromkeys(cmds))
    lines = src.count('\n')+1
    print(f'{f:42s} {lines:5d}L  cmds: {cmds_unique[:8]}')
