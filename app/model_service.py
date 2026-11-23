"""Dunne service-API voor model-operaties op een ``.rbtproject``.

Deze module vertaalt dict-operaties naar de ``@``-regels van ``ZenixTool apply``
en hergebruikt :mod:`core` voor decrypt/zip/Java. Er komen geen nieuwe
dependencies bij en er wordt **nooit** naar het bronbestand geschreven.

Operaties (lijst van dicts)::

    {"op": "add", "ring_id": 1, "unit": 9, "address": 1,
     "type": "fire", "device_type": "FIRE", "unit_id": "010.130.001",
     "zones": [1, 2], "name": "optioneel"}

    {"op": "update", "id": 3, "fields": {"name": "nieuw", "address": 4,
     "zones": [1, 2], "normalOpen": False}}

    {"op": "delete", "id": 3}
    {"op": "rename", "id": 3, "name": "nieuwe_naam"}
    {"op": "order", "ring_id": 1, "ids": [0, 2, 1]}
    {"op": "zone_add", "name": "Brandweer", "description": "optioneel"}
    {"op": "zone_update", "zone_id": 1, "name": "Brandweer", "description": ""}
    {"op": "zone_delete", "zone_id": 2}
    {"op": "ring_add", "name": "Ring2", "host": "10.0.0.42"}
    {"op": "ring_update", "ring_id": 1, "fields": {"name": "Ring A", "host": "10.0.0.9"}}
    {"op": "alarm_rename", "alarm_id": 0, "name": "alarm_rook"}
    {"op": "alarm_desc", "alarm_id": 0, "description": "rookmelding"}
    {"op": "alarm_value", "element_id": 3, "alarm_id": 0, "value": 5}

``alarm_id`` is de index in ``Configuration.getAlarms()`` (dezelfde ``id`` als
in de dump). ``alarm_value`` zet één cel van de controlematrix; ``value`` is
``-1`` (geen koppeling) of ``>= 0``. Alarmen aanmaken, verwijderen of
herordenen kan niet via deze API.

``update`` gebruikt de id-gebaseerde ``@set``-regels (los van de naam, dus
veilig bij dubbele namen) en accepteert de velden ``name``, ``ring`` (naam),
``unit``, ``address``, ``addressOnUnit``, ``unitId``, ``type``, ``deviceType``,
``enabled``, ``invert``, ``normalOpen``, ``safe``, ``description``,
``alarmFunction`` en ``zones``. ``type``/``device_type`` mogen zowel een int als
de naam uit ``diff_edits`` zijn ("fire", "DIN2", ...). ``id`` is de stabiele
``id`` uit de dump (index in ``Configuration.getElements()``).

Naast de model-operaties exposeert deze module de pure naamcontrole
:func:`validate_names` (plus de charset- en gereserveerde-naamconstanten) uit
:mod:`name_validation`. Die regels komen uit de vendor-klassen
``com/euroicc/ringbus/config/check/NameValidator.java`` en
``com/euroicc/rbtool/project/syntax/SyntaxChecker.java``.
"""
import hashlib
import os
import tempfile

import core
from diff_edits import DEVICE_TYPES, ELEMENT_TYPES
from name_validation import (  # noqa: F401 - service-API voor de Ringbus Editor
    FORBIDDEN_ELEMENT_CHARS,
    FORBIDDEN_ZONE_CHARS,
    NAME_RULES,
    RESERVED_NAMES,
    validate_names,
)

#: Veldscheiders die het tab-gescheiden ``@``-protocol van ZenixTool breken.
_UNSAFE_CHARS = (("\t", "tab"), ("\n", "newline"), ("\r", "carriage return"))


def _file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _int(value, what):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError("%s moet een geheel getal zijn: %r" % (what, value))


def _code(value, table, normalise, what):
    if isinstance(value, bool):
        raise ValueError("%s mag geen bool zijn" % what)
    if isinstance(value, int):
        return value
    text = str(value).strip()
    key = normalise(text)
    if key in table:
        return table[key]
    try:
        return int(text)
    except ValueError:
        raise ValueError("onbekende %s: %r" % (what, value))


def _type_code(value):
    return _code(value, ELEMENT_TYPES, str.lower, "type")


def _device_code(value):
    return _code(value, DEVICE_TYPES, str.upper, "deviceType")


def _text(value, what, required=False):
    """Valideer vrije tekst voor het tab-gescheiden ``@``-protocol.

    Een tab of regeleinde in een naam/zone/unit-id zou kolommen verschuiven of
    een extra ``@``-regel injecteren; dat wordt hier geweigerd.
    """
    text = "" if value is None else str(value).strip()
    if required and not text:
        raise ValueError("%s ontbreekt" % what)
    for char, label in _UNSAFE_CHARS:
        if char in text:
            raise ValueError("%s mag geen %s bevatten: %r" % (what, label, value))
    return text


def _zones_csv(value):
    if value is None:
        return ""
    if isinstance(value, str):
        parts = value.replace(";", ",").split(",")
    else:
        parts = [str(p) for p in value]
    ids = [_text(p, "add.zones") for p in parts]
    return ",".join(part for part in ids if part)


def _bool(value, what):
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "ja", "yes", "waar"):
        return True
    if text in ("false", "0", "nee", "no", "onwaar", ""):
        return False
    raise ValueError("%s moet true of false zijn: %r" % (what, value))


#: Velden die een ``update``-operatie via ``@set`` mag zetten (canonieke volgorde).
_UPDATE_FIELDS = (
    "name", "ring", "unit", "address", "addressOnUnit", "unitId", "type",
    "deviceType", "enabled", "invert", "normalOpen", "safe", "description",
    "alarmFunction", "zones",
)


def _update_lines(ident, fields, index):
    """Zet ``fields`` om naar id-gebaseerde ``@set``-regels (naam-onafhankelijk)."""
    if not isinstance(fields, dict):
        raise ValueError("operatie %d (update): 'fields' moet een object zijn" % index)
    unknown = sorted(k for k in fields if k not in _UPDATE_FIELDS)
    if unknown:
        raise ValueError(
            "operatie %d (update): onbekende velden: %s" % (index, ", ".join(unknown)))
    if not fields:
        raise ValueError("operatie %d (update): geen velden opgegeven" % index)
    getters = {
        "name": lambda: _text(fields.get("name"), "naam", required=True),
        "ring": lambda: _text(fields.get("ring"), "ringnaam", required=True),
        "unit": lambda: _int(fields.get("unit"), "update.unit"),
        "address": lambda: _int(fields.get("address"), "update.address"),
        "addressOnUnit": lambda: _int(
            fields.get("addressOnUnit"), "update.addressOnUnit"),
        "unitId": lambda: _text(fields.get("unitId"), "update.unitId"),
        "type": lambda: _type_code(fields.get("type")),
        "deviceType": lambda: _device_code(fields.get("deviceType")),
        "enabled": lambda: _bool(fields.get("enabled"), "update.enabled"),
        "invert": lambda: _bool(fields.get("invert"), "update.invert"),
        "normalOpen": lambda: _bool(fields.get("normalOpen"), "update.normalOpen"),
        "safe": lambda: _text(fields.get("safe"), "update.safe"),
        "description": lambda: _text(fields.get("description"), "update.description"),
        "alarmFunction": lambda: _text(
            fields.get("alarmFunction"), "update.alarmFunction"),
        "zones": lambda: _zones_csv(fields.get("zones")),
    }
    lines = []
    for field in _UPDATE_FIELDS:
        if field not in fields:
            continue
        value = getters[field]()
        if isinstance(value, bool):
            value = "true" if value else "false"
        lines.append("@set\t%d\t%s\t%s" % (ident, field, value))
    return lines


#: Velden die een ``ring_update``-operatie via ``@ringset`` mag zetten.
_RING_UPDATE_FIELDS = ("name", "host")

#: Vaste melding bij een leeg host-veld; de editor gebruikt dezelfde tekst.
EMPTY_HOST_MESSAGE = "De host van een ring mag niet leeg zijn"


def _ring_host(value):
    """Host van een bestaande ring; leegmaken is expliciet verboden."""
    text = _text(value, "ring_update.host")
    if not text:
        raise ValueError(EMPTY_HOST_MESSAGE)
    return text


def _ring_update_lines(ring_id, fields, index):
    """Zet ``fields`` om naar ``@ringset``-regels voor een bestaande ring."""
    if not isinstance(fields, dict):
        raise ValueError(
            "operatie %d (ring_update): 'fields' moet een object zijn" % index)
    unknown = sorted(k for k in fields if k not in _RING_UPDATE_FIELDS)
    if unknown:
        raise ValueError(
            "operatie %d (ring_update): onbekende velden: %s"
            % (index, ", ".join(unknown)))
    if not fields:
        raise ValueError("operatie %d (ring_update): geen velden opgegeven" % index)
    getters = {
        "name": lambda: _text(fields.get("name"), "ringnaam", required=True),
        "host": lambda: _ring_host(fields.get("host")),
    }
    lines = []
    for field in _RING_UPDATE_FIELDS:
        if field not in fields:
            continue
        lines.append("@ringset\t%d\t%s\t%s" % (ring_id, field, getters[field]()))
    return lines


def operations_to_edits(operations):
    """Zet dict-operaties om naar ``@``-regels voor ``ZenixTool apply``."""
    lines = []
    for index, op in enumerate(operations or []):
        if not isinstance(op, dict):
            raise ValueError("operatie %d is geen dict" % index)
        kind = str(op.get("op") or op.get("type") or "").strip().lower()
        if kind == "add":
            name = _text(op.get("name"), "naam")
            fields = [
                "@add",
                _int(op.get("ring_id", op.get("ringId")), "add.ring_id"),
                _int(op.get("unit"), "add.unit"),
                _int(op.get("address"), "add.address"),
                _type_code(op.get("element_type", op.get("type"))),
                _device_code(op.get("device_type", op.get("deviceType"))),
                _text(op.get("unit_id", op.get("unitId")), "add.unit_id"),
                _zones_csv(op.get("zones")),
                name,
            ]
            lines.append("\t".join(str(f) for f in fields))
        elif kind in ("delete", "del", "remove"):
            lines.append("@del\t%d" % _int(op.get("id"), "delete.id"))
        elif kind == "update":
            lines.extend(_update_lines(
                _int(op.get("id"), "update.id"), op.get("fields"), index))
        elif kind == "rename":
            name = _text(op.get("name"), "naam", required=True)
            lines.append("@rename\t%d\t%s" % (_int(op.get("id"), "rename.id"), name))
        elif kind == "order":
            ids = op.get("ids") or []
            if not ids:
                raise ValueError("order.ids ontbreekt")
            lines.append("@order\t%d\t%s" % (
                _int(op.get("ring_id", op.get("ringId")), "order.ring_id"),
                ",".join(str(_int(i, "order.ids")) for i in ids)))
        elif kind in ("zone_delete", "zonedel"):
            lines.append("@zonedel\t%d" % _int(
                op.get("zone_id", op.get("zoneId")), "zone_delete.zone_id"))
        elif kind == "zone_add":
            name = _text(op.get("name"), "zonenaam", required=True)
            desc = _text(op.get("description"), "zone_add.description")
            lines.append("@zone\tnew\t%s\t%s" % (name, desc))
        elif kind == "zone_update":
            name = _text(op.get("name"), "zonenaam", required=True)
            desc = _text(op.get("description"), "zone_update.description")
            lines.append("@zone\t%d\t%s\t%s" % (
                _int(op.get("zone_id", op.get("zoneId")), "zone_update.zone_id"),
                name, desc))
        elif kind == "ring_add":
            name = _text(op.get("name"), "ringnaam", required=True)
            host = _text(op.get("host"), "ring_add.host")
            lines.append("@ringadd\t%s\t%s" % (name, host))
        elif kind == "ring_update":
            lines.extend(_ring_update_lines(
                _int(op.get("ring_id", op.get("ringId")), "ring_update.ring_id"),
                op.get("fields"), index))
        elif kind == "alarm_rename":
            name = _text(op.get("name"), "alarmnaam", required=True)
            lines.append("@alarmrename\t%d\t%s" % (
                _int(op.get("alarm_id", op.get("alarmId")), "alarm_rename.alarm_id"), name))
        elif kind == "alarm_desc":
            alarm_id = _int(op.get("alarm_id", op.get("alarmId")), "alarm_desc.alarm_id")
            desc = _text(op.get("description"), "alarm_desc.description")
            lines.append("@alarmdesc\t%d\t%s" % (alarm_id, desc))
        elif kind == "alarm_value":
            value = _int(op.get("value", op.get("waarde")), "alarm_value.value")
            if value < -1:
                raise ValueError(
                    "alarm_value.value moet -1 of >= 0 zijn: %r" % value)
            element_id = _int(op.get("element_id", op.get("elementId", op.get("id"))),
                              "alarm_value.element_id")
            alarm_id = _int(op.get("alarm_id", op.get("alarmId")), "alarm_value.alarm_id")
            lines.append("@alarmvalue\t%d\t%d\t%d" % (element_id, alarm_id, value))
        else:
            raise ValueError("onbekende operatie %d: %r" % (index, kind))
    return lines


def read_project_full(project_path):
    """Lees een project en geef ``(key, blob, data)`` in één decrypt+parse."""
    return core.open_project(project_path)


def read_project(project_path):
    """Lees een project en geef de dump-dict terug (inclusief stabiele ``id``)."""
    _, _, data = read_project_full(project_path)
    return data


def _same_file(a, b):
    """True als ``a`` en ``b`` hetzelfde bestand zijn, ook via symlink of hardlink."""
    if os.path.realpath(a) == os.path.realpath(b):
        return True
    try:
        return os.path.exists(a) and os.path.exists(b) and os.path.samefile(a, b)
    except OSError:
        return False


def _ring_key(name):
    """Sleutel voor een ringnaam: leidend/slepend weg en hoofdletterongevoelig."""
    return str(name).strip().casefold()


def _check_ring_adds(operations, data):
    """Weiger ``ring_add`` met een naam die al bestaat of dubbel in de lijst staat.

    De editor vergelijkt ringnamen op dezelfde manier (``str.casefold``); zonder
    deze controle zou de vendor-list een tweede ring met dezelfde naam toelaten.
    """
    seen = {_ring_key(x.get("name")) for x in (data.get("rings") or [])
            if isinstance(x, dict) and _ring_key(x.get("name"))}
    for index, op in enumerate(operations or []):
        if not isinstance(op, dict):
            continue
        kind = str(op.get("op") or op.get("type") or "").strip().lower()
        if kind != "ring_add":
            continue
        name = _text(op.get("name"), "ringnaam")
        key = _ring_key(name)
        if not key:
            continue  # operations_to_edits geeft de "naam ontbreekt"-fout
        if key in seen:
            raise ValueError(
                "operatie %d (ring_add): er bestaat al een ring met de naam '%s'"
                % (index, name))
        seen.add(key)


def apply_operations(project_path, operations, out_path):
    """Pas operaties toe en schrijf uitsluitend naar ``out_path``.

    ``out_path`` is verplicht: de service leidt nooit zelf een doelpad af en
    schrijft nooit naar het bronbestand. Een ``out_path`` dat (via symlink of
    hardlink) naar de bron wijst wordt geweigerd. De nieuwe blob gaat eerst
    naar een tijdelijk bestand in de doelmap; pas nadat de bronhash opnieuw is
    gecontroleerd wordt dat bestand atomisch naar ``out_path`` verplaatst.
    Geeft een samenvatting met o.a. ``out`` en ``changes``.
    """
    src = os.path.realpath(project_path)
    if not os.path.exists(src):
        raise FileNotFoundError(src)
    if out_path is None or not str(out_path).strip():
        raise ValueError(
            "out_path is verplicht; er wordt nooit naar een zelf afgeleid pad geschreven")
    dst = os.path.abspath(out_path)
    if _same_file(dst, src):
        raise ValueError(
            "out_path mag niet het bronbestand zijn (ook niet via symlink of hardlink)")

    before = _file_hash(src)
    key, blob, data = core.open_project(src)
    _check_ring_adds(operations, data)
    edits = operations_to_edits(operations)
    new_blob = core.apply_edits(blob, key, edits)

    dst_dir = os.path.dirname(dst) or "."
    fd, tmp = tempfile.mkstemp(prefix=".zenix-", suffix=".tmp", dir=dst_dir)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(new_blob)
            f.flush()
            os.fsync(f.fileno())
        after = _file_hash(src)
        if before != after:
            raise RuntimeError("bronbestand is gewijzigd tijdens apply_operations")
        # vlak voor de replace opnieuw controleren (TOCTOU: doel kan intussen
        # naar de bron zijn gaan wijzen)
        if _same_file(dst, src):
            raise ValueError(
                "out_path wijst naar het bronbestand; er is niets geschreven")
        os.replace(tmp, dst)
        tmp = None
    finally:
        if tmp is not None and os.path.exists(tmp):
            os.unlink(tmp)

    return {
        "out": dst,
        "project": data.get("project", ""),
        "operations": len(operations or []),
        "changes": len(edits),
        "source_unchanged": True,
    }