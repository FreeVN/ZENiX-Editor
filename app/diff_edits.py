#!/usr/bin/env python3
"""Gedeelde diff-logica: bewerkte rijen (Excel of Google Sheet) vs baseline-dump."""
import json

ELEMENT_TYPES = {"": 0, "fire": 1, "smoke": 2, "di": 3, "do": 4, "motorless": 5,
                 "smoke op": 6, "smoke cl": 7, "smoke o/c": 8}

DEVICE_TYPES = {
    "": 0, "FIRE": 1, "SMOKE": 2, "FIO_8_8": 3, "FIRE2M": 4, "MOTORLESS": 5, "DIN": 6,
    "DOM12": 7, "SMOKE OP": 10, "SMOKE CL": 11, "SMOKE O/C": 12, "MOTORLESS2M": 13,
    "FIRE2S": 14, "DOM08": 15, "FIO_12_0": 16, "FIO_8_4": 17, "FIO_0_12": 18,
    "FIRE2B": 19, "FIRE_LOCAL": 20, "DOM16": 21, "SMOKE_LOCAL": 22, "DIN2": 23, "DOM2": 24,
}

# 0-based kolom -> (json-veld, soort)
COLMAP = {
    1: ("name", "str"),
    2: ("ring", "str"),
    3: ("unit", "int"),
    5: ("address", "int"),
    6: ("indexInRing", "int"),
    7: ("typeName", "type"),
    8: ("deviceTypeName", "devtype"),
    9: ("zones", "zones"),
    10: ("description", "str"),
    11: ("alarmFunction", "str"),
    12: ("normalOpen", "bool"),
    13: ("invert", "bool"),
    14: ("safe", "str"),
}


def norm(v, kind):
    if kind == "int":
        if v is None or str(v).strip() == "":
            return 0
        return int(float(str(v).replace(",", ".")))
    if kind == "bool":
        return str(v).strip().upper() in ("WAAR", "TRUE", "1", "JA", "YES")
    if kind == "type":
        s = str(v or "").strip().lower()
        return ELEMENT_TYPES[s] if s in ELEMENT_TYPES else int(s)
    if kind == "devtype":
        s = str(v or "").strip().upper()
        return DEVICE_TYPES[s] if s in DEVICE_TYPES else int(s)
    if kind == "zones":
        parts = [p.strip() for p in str(v or "").replace(";", ",").split(",") if p.strip()]
        return ",".join(sorted(parts, key=lambda x: (len(x), x)))
    return "" if v is None else str(v).strip()


FORBIDDEN_NAME = list("().,!|&<>?*+/\\=\"%$#:;^'[]{} ") + ["\u2010", "\u2011", "\u2013", "\u2014", "\u2015", "-"]
FORBIDDEN_DESC = ["<", ">", ",", "?", "*"]


def name_problem(name, taken=()):
    if not name:
        return "leeg"
    bad = [c for c in FORBIDDEN_NAME if c in name]
    if bad:
        return "verboden teken(s): " + " ".join(repr(c) for c in bad)
    if name in taken:
        return "naam bestaat al"
    return None


def desc_problem(desc):
    bad = [c for c in FORBIDDEN_DESC if c in (desc or "")]
    return ("verboden teken(s): " + " ".join(bad)) if bad else None


def diff_rows(rows, base_elements, skip_fields=()):
    """rows: lijst van lijsten zonder header. Geeft (edits, onbekende_namen)."""
    by_name = {e["name"]: e for e in base_elements}
    lines, unknown = [], []
    for row in rows:
        if not row or not str(row[0] or "").strip():
            continue
        orig = str(row[0]).strip()
        base_e = by_name.get(orig)
        if base_e is None:
            unknown.append(orig)
            continue
        for col, (field, kind) in COLMAP.items():
            if field in skip_fields:
                continue
            raw = row[col] if len(row) > col else None
            if kind == "bool":
                new_cmp = norm(raw, kind)
                if new_cmp != bool(base_e.get(field)):
                    lines.append(f"{orig}\t{field}\t{str(new_cmp).lower()}")
            elif kind == "zones":
                new_cmp = norm(raw, kind)
                old_cmp = ",".join(sorted([str(z) for z in (base_e.get("zones") or [])],
                                          key=lambda x: (len(x), x)))
                if new_cmp != old_cmp:
                    lines.append(f"{orig}\t{field}\t{new_cmp}")
            elif kind in ("type", "devtype"):
                key = "typeName" if kind == "type" else "deviceTypeName"
                new_cmp = str(raw or "").strip()
                old_cmp = "" if base_e.get(key) is None else str(base_e.get(key)).strip()
                if kind == "devtype":
                    new_cmp, old_cmp = new_cmp.upper(), old_cmp.upper()
                else:
                    new_cmp, old_cmp = new_cmp.lower(), old_cmp.lower()
                if new_cmp != old_cmp:
                    lines.append(f"{orig}\t{field}\t{norm(raw, kind)}")
            else:
                new_cmp = norm(raw, kind)
                if field == "name":
                    taken = {e["name"] for e in base_elements} - {orig}
                    prob = name_problem(new_cmp, taken)
                    if prob:
                        print(f"  !! naam geweigerd ({orig} -> {new_cmp}): {prob}")
                        continue
                if field == "description":
                    prob = desc_problem(new_cmp)
                    if prob:
                        print(f"  !! beschrijving geweigerd ({orig}): {prob}")
                        continue
                if kind == "int":
                    old_cmp = base_e.get(field)
                    old_cmp = 0 if old_cmp is None else int(old_cmp)
                else:
                    old_cmp = "" if base_e.get(field) is None else str(base_e.get(field)).strip()
                if new_cmp != old_cmp:
                    lines.append(f"{orig}\t{field}\t{new_cmp}")
    return lines, unknown


def write_tsv(lines, out_path):
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + ("\n" if lines else ""))


def summary(lines, unknown, out_path):
    print(f"OK {out_path}: {len(lines)} wijzigingen")
    for l in lines[:25]:
        print("   ", l.replace("\t", " | "))
    if len(lines) > 25:
        print(f"    ... +{len(lines)-25}")
    if unknown:
        print("LET OP: onbekende rijen (nieuw of hernoemd zonder Origineel):", ", ".join(unknown))


def load_json(path):
    return json.load(open(path, encoding="utf-8"))
