# -*- coding: utf-8 -*-
"""scripts/kinship_alias_dump.py — kinship 别名表 + canonical registry CLI (准则6 三件套).

[canonical-entity-slice1 / 2026-06-08] 详
docs/process/JARVIS_SLICE1_CANONICAL_ENTITY_DESIGN.md.

让 Sir 不改码就能 list/改 kinship 表 + corrigible 撤 (revoke/rename)。

示例 (Sir 直接复制跑):
    python scripts/kinship_alias_dump.py --list
    python scripts/kinship_alias_dump.py --add-surface person:mother 妈咪
    python scripts/kinship_alias_dump.py --del-surface 老妈
    python scripts/kinship_alias_dump.py --revoke 我妈
    python scripts/kinship_alias_dump.py --rename person:mother 妈妈大人
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_canonical_entities as CE  # noqa: E402

_KINSHIP_PATH = os.path.join("memory_pool", "kinship_alias_vocab.json")


def _read_kinship() -> dict:
    if os.path.exists(_KINSHIP_PATH):
        try:
            with open(_KINSHIP_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # seed fallback
    return {"_meta": {"schema": "kinship_alias_vocab", "schema_version": 1,
                      "edit_via": "scripts/kinship_alias_dump.py"},
            "kinship": dict(CE._SEED_KINSHIP)}


def _write_kinship(data: dict) -> None:
    os.makedirs(os.path.dirname(_KINSHIP_PATH) or ".", exist_ok=True)
    tmp = _KINSHIP_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _KINSHIP_PATH)


def cmd_list() -> None:
    data = _read_kinship()
    kin = data.get("kinship", {})
    print(f"=== kinship 别名表 ({len(kin)} 条) ===")
    for cid, meta in kin.items():
        surfaces = "/".join(meta.get("surfaces", []))
        print(f"  {cid:34s} [{meta.get('label','')}] <- {surfaces}")


def cmd_add_surface(cid: str, surface: str) -> None:
    data = _read_kinship()
    kin = data.setdefault("kinship", {})
    if cid not in kin:
        print(f"[ERR] cid 不存在: {cid} (先 --add-entity)")
        return
    surfaces = kin[cid].setdefault("surfaces", [])
    if surface in surfaces:
        print(f"[skip] {surface} 已在 {cid}")
        return
    surfaces.append(surface)
    _write_kinship(data)
    print(f"[ok] +surface {surface} -> {cid}")


def cmd_del_surface(surface: str) -> None:
    data = _read_kinship()
    kin = data.get("kinship", {})
    hit = False
    for cid, meta in kin.items():
        surfaces = meta.get("surfaces", [])
        if surface in surfaces:
            surfaces.remove(surface)
            hit = True
            print(f"[ok] -surface {surface} (was {cid})")
    if hit:
        _write_kinship(data)
    else:
        print(f"[skip] surface 未找到: {surface}")


def cmd_add_entity(cid: str, label: str, relation: str) -> None:
    data = _read_kinship()
    kin = data.setdefault("kinship", {})
    if cid in kin:
        print(f"[skip] cid 已存在: {cid}")
        return
    kin[cid] = {"label": label, "relation": relation, "surfaces": []}
    _write_kinship(data)
    print(f"[ok] +entity {cid} [{label}] relation={relation}")


def cmd_revoke(surface: str) -> None:
    reg = CE.get_canonical_registry()
    ok = reg.revoke_alias_link(surface, by="sir", reason="CLI --revoke")
    if ok:
        reg.save()
        print(f"[ok] revoked AliasLink surface={surface} (终态, 再喂不再触达)")
    else:
        print(f"[skip] 无 active AliasLink: {surface} (尚未在 registry 建链)")


def cmd_rename(cid: str, new_label: str) -> None:
    reg = CE.get_canonical_registry()
    ok = reg.rename_canonical(cid, new_label, by="sir")
    if ok:
        reg.save()
        print(f"[ok] renamed {cid} -> {new_label}")
    else:
        print(f"[skip] cid 不存在于 registry: {cid}")


def cmd_activate(surface: str) -> None:
    """[canonical-soft-proposer-slice2] Sir 显式升级 proposed→active (含 revoked 复活)。"""
    reg = CE.get_canonical_registry()
    ok = reg.activate_alias_link(surface, by="sir", reason="CLI --activate")
    if ok:
        reg.save()
        print(f"[ok] activated AliasLink surface={surface} (proposed/revoked → active)")
    else:
        print(f"[skip] surface 无可升级链 (不存在/冲突): {surface}")


def cmd_list_proposed() -> None:
    """[canonical-soft-proposer-slice2] 列 Sir 待确认的 proposed 软提议队列。"""
    reg = CE.get_canonical_registry()
    proposed = reg.list_proposed()
    if not proposed:
        print("[empty] 无 proposed AliasLink (软提议队列空)")
        return
    print(f"=== proposed AliasLinks ({len(proposed)} 条待确认) ===")
    for l in proposed:
        print(f"  {l.get('surface')} -> {l.get('cid')} "
              f"source={l.get('source')} conf={l.get('confidence')}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="kinship 别名表 + canonical registry CLI (准则6)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--list", action="store_true", help="列当前 kinship 表")
    parser.add_argument("--add-surface", nargs=2, metavar=("CID", "SURFACE"),
                        help="给某 cid 加一个 surface (exact)")
    parser.add_argument("--del-surface", metavar="SURFACE",
                        help="删一个 surface (误触修正)")
    parser.add_argument("--add-entity", nargs=3, metavar=("CID", "LABEL", "RELATION"),
                        help="新建 kinship 条目")
    parser.add_argument("--revoke", metavar="SURFACE",
                        help="撤一条 AliasLink (registry, 终态)")
    parser.add_argument("--rename", nargs=2, metavar=("CID", "LABEL"),
                        help="改 canonical_label (registry)")
    parser.add_argument("--activate", metavar="SURFACE",
                        help="升级 proposed→active (Sir 确认软提议; 含 revoked 显式复活)")
    parser.add_argument("--list-proposed", action="store_true",
                        help="列 Sir 待确认的 proposed 软提议队列")
    args = parser.parse_args()

    did = False
    if args.list:
        cmd_list(); did = True
    if args.add_surface:
        cmd_add_surface(args.add_surface[0], args.add_surface[1]); did = True
    if args.del_surface:
        cmd_del_surface(args.del_surface); did = True
    if args.add_entity:
        cmd_add_entity(args.add_entity[0], args.add_entity[1], args.add_entity[2]); did = True
    if args.revoke:
        cmd_revoke(args.revoke); did = True
    if args.rename:
        cmd_rename(args.rename[0], args.rename[1]); did = True
    if args.activate:
        cmd_activate(args.activate); did = True
    if args.list_proposed:
        cmd_list_proposed(); did = True
    if not did:
        cmd_list()


if __name__ == "__main__":
    main()
