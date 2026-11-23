"""ZENiX Bridge — kern: project <-> Excel, zonder Google.

Een .rbtproject is AES-256-GCM (nonce = sleutel) rond een zip met
<naam>.rbproject (Java-serialized Configuration) + project.properties + fb/.
Python doet crypto en zip, Java doet enkel de (de)serialisatie.
"""
import base64
import glob
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

APP_DIR = os.path.dirname(os.path.abspath(__file__))
BASE = getattr(sys, "_MEIPASS", os.path.dirname(APP_DIR))
FROZEN = bool(getattr(sys, "frozen", False))
EXE_DIR = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(APP_DIR)
SHEET = "_zenix_base"          # verborgen tabblad met de originele container
CHUNK = 45000                  # tekens per cel (Google/Excel limiet is 32767)


def res(*parts):
    return os.path.join(BASE, *parts)


APP_LIB = res("app", "lib")


def _module_dirs():
    """Kandidaat-<installatie>/ringbustool/modules-mappen van de RingBus Tool.

    Volgorde: RINGBUSTOOL_HOME eerst, dan de vaste installatiepaden per platform.
    """
    cands = []
    env = os.environ.get("RINGBUSTOOL_HOME")
    if env:
        cands.append(os.path.join(env, "ringbustool", "modules"))
        cands.append(env)
        cands.append(os.path.join(env, "modules"))
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            cands += glob.glob(os.path.join(base, "EuroICC", "RingBusTool*",
                                            "ringbustool", "modules"))
    else:
        cands += glob.glob(os.path.join(BASE, "vendor", "RingBusTool*", "*",
                                        "ringbustool", "modules"))
        cands += glob.glob("/opt/RingBusTool*/ringbustool/modules")
        cands += glob.glob("/opt/euroicc*/ringbustool/modules")
    seen, out = set(), []
    for m in cands:
        key = os.path.normcase(os.path.abspath(m))
        if key not in seen:
            seen.add(key)
            out.append(m)
    return out


def vendor_jar():
    """Pad naar configuration-*.jar uit de RingBus Tool-installatie (of app/lib)."""
    for modules in _module_dirs():
        hits = sorted(glob.glob(os.path.join(modules, "lib", "configuration-*.jar")))
        if hits:
            return hits[0]
    hits = sorted(glob.glob(os.path.join(APP_LIB, "configuration-*.jar")))
    if hits:
        return hits[0]
    raise RuntimeError(
        "RingBus Tool vendor-bibliotheek (configuration-*.jar) niet gevonden. "
        "Installeer de RingBus Tool, of zet RINGBUSTOOL_HOME naar de installatiemap.")


def _jaxb_jar():
    """jaxb-api.jar uit dezelfde installatie (lib/ dan ext/), anders app/lib."""
    for modules in _module_dirs():
        for sub in ("lib", "ext"):
            p = os.path.join(modules, sub, "jaxb-api.jar")
            if os.path.exists(p):
                return p
    return os.path.join(APP_LIB, "jaxb-api.jar")


def jars():
    return [vendor_jar(), _jaxb_jar()]


def java_exe():
    bundled = res("app", "jre", "bin", "java.exe" if os.name == "nt" else "java")
    if os.path.exists(bundled):
        return bundled
    found = shutil.which("java")
    if found:
        return found
    raise RuntimeError("Java niet gevonden (bundled JRE ontbreekt en java staat niet in PATH).")


def classpath():
    sep = ";" if os.name == "nt" else ":"
    return sep.join([res("app", "build")] + [j for j in jars() if os.path.exists(j)])


# ---------------- sleutels ----------------

def _key_paths():
    paths = [os.path.join(EXE_DIR, "keys.txt"),
             os.path.join(EXE_DIR, ".secrets", "project.key"),
             os.path.join(EXE_DIR, "key.txt"),
             os.path.join(os.environ.get("APPDATA", ""), "ZENiX", "keys.txt")]
    return [p for p in paths if p]


def load_keys():
    keys = []
    env = os.environ.get("ZENIX_KEY", "").strip()
    if env:
        keys.append(env)
    for p in _key_paths():
        if os.path.exists(p):
            for line in open(p, encoding="utf-8"):
                line = line.split("#")[0].strip()
                if line:
                    keys.append(line)
    out = []
    for k in keys:
        h = k.replace("KEY=", "").replace(" ", "").replace(":", "").strip()
        try:
            b = bytes.fromhex(h)
        except ValueError:
            continue
        if len(b) in (16, 24, 32) and b not in out:
            out.append(b)
    return out


def key_id(k: bytes) -> str:
    import hashlib
    return hashlib.sha256(k).hexdigest()[:12]


def decrypt(blob: bytes):
    """Probeer alle sleutels; geeft (sleutel, plaintext)."""
    keys = load_keys()
    if not keys:
        raise KeyError("Geen sleutel gevonden. Zet je sleutel in keys.txt naast de app.")
    for k in keys:
        try:
            return k, AESGCM(k).decrypt(k, blob, None)
        except Exception:
            continue
    raise KeyError("Geen van de %d sleutels in keys.txt opent dit project." % len(keys))


# ---------------- java ----------------

def _java(*args):
    cmd = [java_exe(), "-cp", classpath(), "ZenixTool", *args]
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "java faalde").strip()[-800:])
    return p.stdout


def _find_cfg(folder):
    hits = [os.path.join(r, f) for r, _, fs in os.walk(folder)
            for f in fs if f.lower().endswith(".rbproject")]
    if len(hits) != 1:
        raise RuntimeError("Verwachtte 1 .rbproject in het archief, vond er %d." % len(hits))
    return hits[0]


def _unzip(blob: bytes, dest: str):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        z.extractall(dest)


def _rezip(folder: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(folder):
            dirs.sort()
            files.sort()
            for f in files:
                full = os.path.join(root, f)
                z.write(full, os.path.relpath(full, folder).replace(os.sep, "/"))
    return buf.getvalue()


def open_project(path):
    """-> (sleutel, zip-bytes, dump-dict)"""
    key, blob = decrypt(open(path, "rb").read())
    tmp = tempfile.mkdtemp(prefix="zenix-")
    try:
        _unzip(blob, tmp)
        cfg = _find_cfg(tmp)
        out = os.path.join(tmp, "_dump.json")
        _java("dump", cfg, out)
        data = json.load(open(out, encoding="utf-8"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return key, blob, data


def apply_edits(zip_bytes: bytes, key: bytes, edits) -> bytes:
    """edits: lijst '<naam>\\t<veld>\\t<waarde>' (+ @zone-regels)."""
    tmp = tempfile.mkdtemp(prefix="zenix-")
    try:
        _unzip(zip_bytes, tmp)
        cfg = _find_cfg(tmp)
        tsv = os.path.join(tmp, "_edits.tsv")
        with open(tsv, "w", encoding="utf-8") as f:
            f.write("\n".join(edits) + ("\n" if edits else ""))
        _java("apply", cfg, tsv)
        blob = _rezip(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return AESGCM(key).encrypt(key, blob, None)


# ---------------- Excel ----------------

def _hidden_sheet_data(zip_bytes: bytes, key: bytes):
    b64 = base64.b64encode(zip_bytes).decode("ascii")
    rows = [["ZENIX1"], [key_id(key)]]
    rows += [[b64[i:i + CHUNK]] for i in range(0, len(b64), CHUNK)]
    return rows


def project_to_xlsx(project_path: str, out_path: str, progress=None):
    from xlsx_build import rows_from_dump, write_rows
    from openpyxl import load_workbook

    if progress:
        progress("Project ontsleutelen…")
    key, blob, data = open_project(project_path)
    rows = rows_from_dump_obj(data)

    if progress:
        progress("Excel opbouwen…")
    write_rows(rows, out_path)

    wb = load_workbook(out_path)
    ws = wb.create_sheet(SHEET)
    for r, row in enumerate(_hidden_sheet_data(blob, key), start=1):
        ws.cell(row=r, column=1, value=row[0])
    ws.sheet_state = "hidden"
    wb.save(out_path)
    return {"project": data.get("project"), "elements": len(data["elements"]),
            "zones": len(data["zones"]), "rings": len(data["rings"]), "out": out_path}


def rows_from_dump_obj(data):
    """Zelfde indeling als de Google Sheet, maar uit een dump-dict."""
    from xlsx_build import rows_from_dump
    import json as _json
    fd, tmp = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False)
        return rows_from_dump(tmp)
    finally:
        os.unlink(tmp)


def read_base(xlsx_path: str):
    from openpyxl import load_workbook
    wb = load_workbook(xlsx_path, data_only=True)
    if SHEET not in wb.sheetnames:
        raise RuntimeError("Dit Excel-bestand is niet door ZENiX gemaakt "
                           "(geen '%s'-tabblad)." % SHEET)
    ws = wb[SHEET]
    kid = str(ws.cell(row=2, column=1).value or "").strip()
    chunks = [str(ws.cell(row=r, column=1).value or "")
              for r in range(3, ws.max_row + 1)]
    blob = base64.b64decode("".join(chunks))
    return wb, kid, blob


def edits_from_xlsx(xlsx_path: str):
    """-> (edits, key, zip, telling)"""
    from diff_edits import diff_rows

    wb, kid, blob = read_base(xlsx_path)
    tmp = tempfile.mkdtemp(prefix="zenix-")
    try:
        _unzip(blob, tmp)
        cfg = _find_cfg(tmp)
        dump = os.path.join(tmp, "_base.json")
        _java("dump", cfg, dump)
        base = json.load(open(dump, encoding="utf-8"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    key = next((k for k in load_keys() if key_id(k) == kid), None)
    if key is None:
        raise KeyError("De sleutel voor dit project (%s…) staat niet in keys.txt." % kid[:8])

    el_rows = [list(r) for r in wb["Elementen"].iter_rows(min_row=2, values_only=True)]
    zone_rows = [list(r) for r in wb["Zones"].iter_rows(min_row=2, values_only=True)]
    matrix = [list(r) for r in wb["Zone-lidmaatschap"].iter_rows(values_only=True)]

    base_zones = {str(z["id"]): z for z in base["zones"]}
    base_names = {z["name"]: str(z["id"]) for z in base["zones"]}

    edits, new_ids, next_id = [], {}, max([int(z) for z in base_zones] or [0]) + 1
    for row in zone_rows:
        if not row:
            continue
        zid = "" if row[0] is None else str(row[0]).strip()
        name = str(row[1] or "").strip()
        desc = str(row[2] or "").strip() if len(row) > 2 else ""
        if not zid:
            if name and name not in base_names and name not in new_ids:
                edits.append("@zone\tnew\t%s\t%s" % (name, desc))
                new_ids[name] = str(next_id)
                next_id += 1
            continue
        if zid in base_zones:
            z = base_zones[zid]
            if name != (z["name"] or "") or desc != (z.get("description") or ""):
                edits.append("@zone\t%s\t%s\t%s" % (zid, name, desc))

    el_lines, unknown = diff_rows(el_rows, base["elements"], skip_fields=("zones",))
    edits += el_lines

    if len(matrix) >= 3:
        name_to_id = dict(base_names)
        name_to_id.update(new_ids)
        head_ids, head_names = matrix[0], matrix[1]
        col_zone = {}
        for i in range(2, len(head_ids)):
            zid = str(head_ids[i]).strip() if head_ids[i] is not None else ""
            if not zid:
                zn = str(head_names[i]).strip() if i < len(head_names) and head_names[i] else ""
                zid = name_to_id.get(zn, "")
            if zid:
                col_zone[i] = zid
        for pos, row in enumerate(matrix[2:]):
            if pos >= len(el_rows):
                break
            orig = str(el_rows[pos][0] or "").strip()
            base_e = next((e for e in base["elements"] if e["name"] == orig), None)
            if base_e is None:
                continue
            chosen = sorted({zid for i, zid in col_zone.items()
                             if i < len(row) and str(row[i]).strip().upper()
                             in ("WAAR", "TRUE", "1", "JA", "YES", "X")},
                            key=lambda x: (len(x), x))
            current = sorted({str(z) for z in (base_e.get("zones") or [])},
                             key=lambda x: (len(x), x))
            if chosen != current:
                edits.append("%s\tzones\t%s" % (orig, ",".join(chosen)))

    return edits, key, blob, {"changes": len(edits), "unknown": unknown,
                              "project": base.get("project", "")}


def xlsx_to_project(xlsx_path: str, out_path: str, progress=None):
    if progress:
        progress("Excel lezen…")
    edits, key, blob, info = edits_from_xlsx(xlsx_path)
    if progress:
        progress("Project wegschrijven (%d wijzigingen)…" % len(edits))
    data = apply_edits(blob, key, edits)
    with open(out_path, "wb") as f:
        f.write(data)
    info["out"] = out_path
    return info


# ---------------- dongle / sleutels toevoegen ----------------

def keys_file():
    return os.path.join(EXE_DIR, "keys.txt")


def hasp_home():
    """Map met hasp-srm-api.jar + HASPJava_*.dll van de RingBus Tool-installatie."""
    for m in _module_dirs():
        if os.path.exists(os.path.join(m, "ext", "hasp-srm-api.jar")):
            return m
    return None


def read_dongle(project_path=None):
    """Lees de sleutel(s) uit de HASP-dongle. Geeft een lijst hex-strings."""
    modules = hasp_home()
    if not modules:
        raise RuntimeError("RingBus Tool niet gevonden (nodig voor de dongle-driver).")
    lib = os.path.join(modules, "lib")
    hasp_jar = os.path.join(modules, "ext", "hasp-srm-api.jar")
    sep = ";" if os.name == "nt" else ":"
    cp = sep.join([res("app", "build"), hasp_jar])
    cmd = [java_exe(), "-Djava.library.path=" + lib, "-cp", cp, "ZenixKey"]
    if project_path:
        cmd.append(project_path)
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    keys = [l.split("=", 1)[1].strip() for l in out.splitlines() if l.startswith("KEY=")]
    if not keys:
        err = next((l.split("=", 1)[1] for l in out.splitlines() if l.startswith("ERROR=")), "")
        raise RuntimeError(err or "Geen sleutel gevonden. Dongle aangesloten? RingBus Tool afgesloten?")
    return keys


def add_keys(hex_keys):
    """Voeg sleutels toe aan keys.txt (dedupe) en geef het pad terug."""
    path = keys_file()
    have = {k.hex() for k in load_keys()}
    new = []
    for h in hex_keys:
        h = h.replace("KEY=", "").replace(" ", "").replace(":", "").strip().lower()
        try:
            b = bytes.fromhex(h)
        except ValueError:
            raise RuntimeError("Ongeldige hex-sleutel: %s…" % h[:12])
        if len(b) != 32:
            raise RuntimeError("Een sleutel is 64 hex-tekens (32 bytes), deze is %d." % len(b))
        if b.hex() not in have:
            new.append(b.hex())
            have.add(b.hex())
    if new:
        first = not os.path.exists(path)
        with open(path, "a", encoding="utf-8") as f:
            if first:
                f.write("# ZENiX Bridge - projectsleutels (een per lijn)\n")
            for k in new:
                f.write(k + "\n")
    return path, len(new)


def java_check():
    """Controleer of de gebundelde JRE de classes kan laden (geen versiemismatch)."""
    try:
        p = subprocess.run([java_exe(), "-cp", classpath(), "ZenixTool"],
                           capture_output=True, text=True, errors="replace")
    except Exception as e:
        return False, str(e)
    out = (p.stdout or "") + (p.stderr or "")
    if "UnsupportedClassVersionError" in out:
        return False, "JRE te oud voor de meegeleverde classes"
    if "NoClassDefFoundError" in out or "ClassNotFoundException" in out:
        return False, out.strip().splitlines()[-1]
    return True, "ok"
