"""Sessies, validatie, diff en twee-pass opslaan voor de ZENiX Ringbus Editor.

De editor werkt op een **werkkopie** in een tijdelijke sessiemap. Het
bronbestand wordt nooit beschreven: ``save`` schrijft uitsluitend
``<project> - aangepast.rbtproject`` in de sessiemap.

De API is bewust los van HTTP te gebruiken (en te testen):

* :func:`open_path` / :func:`open_bytes` maken een sessie met baseline-dump;
* :func:`warnings` markeert dubbele namen, dubbele (ring, unit, adres) en lege
  namen (blokkeert opslaan niet);
* :func:`save` controleert eerst de vendor-naamregels (zie
  :mod:`name_validation`): een nieuwe of gewijzigde ongeldige naam geeft
  :class:`NameValidationError` (HTTP 400 met de violations); bestaande
  overtredingen komen als waarschuwing mee;
* :func:`diff` vertaalt baseline + gewenste staat naar model-operaties;
* :func:`save` past die toe in twee rondes: eerst alles behalve de volgorde,
  daarna ``@order`` per ring met de na ronde 1 opnieuw gelezen ids.
"""
import atexit
import hashlib
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time

import core
import model_service
import name_validation

if getattr(sys, "frozen", False):
    # PyInstaller-onefile: de statische bestanden zitten in de uitpakmap, de
    # projectsleutel en eventuele samples staan naast de exe.
    _BUNDLE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    ROOT = os.path.dirname(os.path.abspath(sys.executable))
    SAMPLES = os.path.join(ROOT, "samples")
    STATIC = os.path.join(_BUNDLE, "app", "web", "static")
else:
    ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    SAMPLES = os.path.join(ROOT, "samples")
    STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

OUTPUT_SUFFIX = " - aangepast.rbtproject"
SESSION_TTL = 2 * 60 * 60  # seconden
MAX_UPLOAD = 64 * 1024 * 1024

#: Velden die de editor per element vergelijkt en via ``update`` mag zetten.
TEXT_FIELDS = ("unitId", "description", "alarmFunction")
BOOL_FIELDS = ("enabled", "invert", "normalOpen")


class EditorError(ValueError):
    """Fout met een Nederlandse melding die als 400 naar de client gaat."""


class NameValidationError(EditorError):
    """Ongeldige of dubbele namen; de 400-body bevat de violation-lijst.

    Alleen overtredingen op velden die de gebruiker toevoegde of wijzigde
    (``changed`` is ``True``) komen hier terecht; bestaande overtredingen gaan
    als waarschuwing mee.
    """

    def __init__(self, violations):
        self.violations = list(violations)
        first = self.violations[0] if self.violations else {}
        super(NameValidationError, self).__init__(
            "%d naamfout(en): %s"
            % (len(self.violations), name_validation.describe(first)))


# --------------------------------------------------------------- hulpfuncties

def _text(value):
    return "" if value is None else str(value).strip()


def _ring_key(name):
    """Sleutel voor een ringnaam; dezelfde normalisatie als de model-service.

    De editor delegeert naar :func:`model_service._ring_key`, zodat er één
    definitie van "dezelfde ringnaam" bestaat. ``_text`` eromheen houdt ``None``
    op een lege sleutel, precies zoals de editor dat altijd deed.
    """
    return model_service._ring_key(_text(name))


def _as_bool(value, what):
    if isinstance(value, bool):
        return value
    text = _text(value).lower()
    if text in ("true", "1", "ja", "yes", "waar"):
        return True
    if text in ("false", "0", "nee", "no", "onwaar", ""):
        return False
    raise EditorError("%s moet waar of onwaar zijn: %r" % (what, value))


def _as_int(value, what):
    if isinstance(value, bool):
        raise EditorError("%s moet een geheel getal zijn: %r" % (what, value))
    try:
        return int(_text(value))
    except (TypeError, ValueError):
        raise EditorError("%s moet een geheel getal zijn: %r" % (what, value))


def _element_id(element):
    """Baseline-id van een gegeven element, of ``None`` voor een nieuw element."""
    raw = element.get("id") if isinstance(element, dict) else None
    if raw is None or _text(raw) == "":
        return None
    return _as_int(raw, "element-id")


def _alarm_ident(alarm, index):
    """Stabiele alarm-id (index in de alarmenlijst) van een dump-alarm."""
    raw = alarm.get("id") if isinstance(alarm, dict) else None
    if raw is None or _text(raw) == "":
        return index
    return _as_int(raw, "alarm-id")


def _matrix_cells(element, alarms, what):
    """Controlematrix als ``{alarmId: waarde}``; ``None`` als het veld ontbreekt.

    De dump levert één object per alarm in alarmvolgorde. Voor de zekerheid
    wordt een oude vorm (lijst met getallen) ook gelezen, maar zodra
    ``alarms`` bekend is, moet de lengte en de ``alarmId`` per positie kloppen.
    Een celwaarde is -1 (geen koppeling) of >= 0.
    """
    raw = element.get("controlMatrix") if isinstance(element, dict) else None
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise EditorError("De controlematrix van %s is geen lijst" % what)
    if alarms is not None and len(raw) != len(alarms):
        raise EditorError(
            "De controlematrix van %s heeft %d cellen, verwacht %d (één per alarm)"
            % (what, len(raw), len(alarms)))
    cells = {}
    for index, item in enumerate(raw):
        expected = (_alarm_ident(alarms[index], index)
                    if alarms is not None and index < len(alarms) else index)
        if isinstance(item, dict):
            alarm_id = _as_int(item.get("alarmId", expected), "matrix-alarmId")
            if alarms is not None and index < len(alarms) and alarm_id != expected:
                raise EditorError(
                    "De controlematrix van %s staat niet in alarmvolgorde "
                    "(cel %d hoort bij alarm %d, kreeg %d)"
                    % (what, index, expected, alarm_id))
            raw_value = item.get("waarde", -1)
            value = -1 if raw_value is None else _as_int(raw_value, "matrixwaarde")
        else:
            alarm_id = expected
            value = _as_int(item, "matrixwaarde")
        if value < -1:
            raise EditorError(
                "Een matrixwaarde moet -1 of >= 0 zijn (kreeg %d)" % value)
        cells[alarm_id] = value
    return cells


def _alarm_plan(baseline, state):
    """Bepaal alarm-operaties; toevoegen/verwijderen/herordenen is een fout.

    Alleen naam en omschrijving mogen wijzigen. De alarm-id is de index in
    ``Configuration.getAlarms()`` en blijft gelijk zolang er geen alarmen
    bijkomen of verdwijnen.
    """
    base_alarms = baseline.get("alarms") or []
    if "alarms" not in state:
        return [], base_alarms
    desired = state["alarms"]
    if not isinstance(desired, list):
        raise EditorError("'alarms' moet een lijst zijn")
    if len(desired) != len(base_alarms):
        raise EditorError(
            "Alarmen toevoegen of verwijderen kan niet in deze editor "
            "(%d in plaats van %d)" % (len(desired), len(base_alarms)))
    ops = []
    for index, (base, want) in enumerate(zip(base_alarms, desired)):
        expected = _alarm_ident(base, index)
        got = _alarm_ident(want, index)
        if got != expected:
            raise EditorError(
                "Alarm-id %s mag niet wijzigen (verwacht %d)" % (got, expected))
        # Een alarm hoort bij één ring; wisselen van ring is geen editor-bewerking
        # en zou de vendor-dump stilletjes anders maken dan de gebruiker ziet.
        if "ringId" in base or "ringId" in want:
            base_ring = base.get("ringId")
            want_ring = want.get("ringId", base_ring)
            if want_ring != base_ring:
                raise EditorError(
                    "Een alarm mag niet van ring wisselen (alarm %d: %r in plaats van %r)"
                    % (expected, want_ring, base_ring))
        name = _text(want.get("name"))
        base_name = _text(base.get("name"))
        if name != base_name:
            if not name:
                raise EditorError("Een alarm mag geen lege naam hebben")
            ops.append({"op": "alarm_rename", "alarm_id": expected, "name": name})
        description = _text(want.get("description"))
        if description != _text(base.get("description")):
            ops.append({"op": "alarm_desc", "alarm_id": expected,
                        "description": description})
    return ops, base_alarms


def _zones_of(element):
    zones = element.get("zones")
    if zones is None:
        return []
    if isinstance(zones, str):
        parts = zones.replace(";", ",").split(",")
    else:
        parts = list(zones)
    return [p for p in (_text(p) for p in parts) if p]


def _validate_state(state):
    if not isinstance(state, dict):
        raise EditorError("Verwacht een JSON-object met de projectstaat")
    for key in ("rings", "zones", "elements"):
        if not isinstance(state.get(key), list):
            raise EditorError("'%s' ontbreekt of is geen lijst" % key)
    if "alarms" in state and not isinstance(state.get("alarms"), list):
        raise EditorError("'alarms' moet een lijst zijn")
    for index, element in enumerate(state["elements"]):
        if not isinstance(element, dict):
            raise EditorError("element %d is geen object" % index)
    for index, zone in enumerate(state["zones"]):
        if not isinstance(zone, dict):
            raise EditorError("zone %d is geen object" % index)
    for index, ring in enumerate(state["rings"]):
        if not isinstance(ring, dict):
            raise EditorError("ring %d is geen object" % index)
    for index, alarm in enumerate(state.get("alarms") or []):
        if not isinstance(alarm, dict):
            raise EditorError("alarm %d is geen object" % index)


def _hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_bytes(data):
    return hashlib.sha256(data).hexdigest()


# ------------------------------------------------------------------- sessies

class Sessions(object):
    """Draadveilige sessiestore met tijdelijke mappen en een TTL."""

    def __init__(self):
        self._lock = threading.Lock()
        self._items = {}
        atexit.register(self.close_all)

    def create(self, filename, blob, key, baseline, source_path=None, source_hash=None):
        self.prune()
        sid = secrets.token_hex(16)
        directory = tempfile.mkdtemp(prefix="zenix-web-")
        session = {
            "sid": sid,
            "dir": directory,
            "filename": filename or "project.rbtproject",
            "source_path": source_path,
            "source_hash": source_hash,
            "blob": blob,
            "key": key,
            "baseline": baseline,
            "created": time.time(),
            "output": None,
            "output_name": None,
        }
        with self._lock:
            self._items[sid] = session
        return session

    def get(self, sid):
        with self._lock:
            session = self._items.get(sid)
        if session is None:
            raise KeyError(sid)
        if time.time() - session["created"] > SESSION_TTL:
            self.close(sid)
            raise KeyError(sid)
        return session

    def close(self, sid):
        with self._lock:
            session = self._items.pop(sid, None)
        if session is not None:
            shutil.rmtree(session["dir"], ignore_errors=True)
        return session is not None

    def prune(self):
        now = time.time()
        stale = [sid for sid, s in list(self._items.items())
                 if now - s["created"] > SESSION_TTL]
        for sid in stale:
            self.close(sid)

    def close_all(self):
        with self._lock:
            items = list(self._items.values())
            self._items.clear()
        for session in items:
            shutil.rmtree(session["dir"], ignore_errors=True)


SESSIONS = Sessions()


# ---------------------------------------------------------------- openen

def _session_from_bytes(filename, data, source_path=None):
    if not data:
        raise EditorError("Het bestand is leeg")
    if len(data) > MAX_UPLOAD:
        raise EditorError("Het bestand is te groot (maximaal %d MB)" % (MAX_UPLOAD // (1024 * 1024)))
    name = os.path.basename(_text(filename).replace("\\", "/")) or "project.rbtproject"
    directory = tempfile.mkdtemp(prefix="zenix-web-")
    src = os.path.join(directory, "bron.rbtproject")
    try:
        with open(src, "wb") as f:
            f.write(data)
        try:
            key, blob, baseline = core.open_project(src)
        except Exception as exc:  # KeyError bij ontbrekende sleutel, RuntimeError bij Java
            raise EditorError("Kan dit project niet openen: %s" % exc)
    finally:
        shutil.rmtree(directory, ignore_errors=True)
    return SESSIONS.create(name, blob, key, baseline, source_path=source_path,
                           source_hash=_hash_bytes(data))


def open_bytes(filename, data):
    """Open een .rbtproject uit een upload (bytes)."""
    return _session_from_bytes(filename, data)


def resolve_sample_path(raw):
    """Valideer een pad voor 'openen via pad': alleen onder ``samples/``."""
    if not isinstance(raw, str) or not raw.strip():
        raise EditorError("Geef een pad naar een .rbtproject onder samples/")
    candidate = raw.strip()
    if not os.path.isabs(candidate):
        candidate = os.path.join(ROOT, candidate)
    real = os.path.realpath(candidate)
    samples = os.path.realpath(SAMPLES)
    if real != samples and not real.startswith(samples + os.sep):
        raise EditorError("Alleen projecten onder samples/ mogen via een pad geopend worden")
    if not os.path.isfile(real):
        raise EditorError("Bestand niet gevonden: %s" % raw)
    if not real.lower().endswith(".rbtproject"):
        raise EditorError("Verwacht een .rbtproject-bestand")
    return real


def open_path(raw):
    """Open een project via een pad onder ``samples/``."""
    real = resolve_sample_path(raw)
    before = _hash(real)
    with open(real, "rb") as f:
        data = f.read()
    session = _session_from_bytes(os.path.basename(real), data, source_path=real)
    if _hash(real) != before:  # pragma: no cover - paranoïde controle
        SESSIONS.close(session["sid"])
        raise EditorError("Het bronbestand is tijdens het openen gewijzigd")
    return session


def open_response(session):
    baseline = session["baseline"]
    return {
        "sid": session["sid"],
        "filename": session["filename"],
        "project": baseline.get("project", ""),
        "state": baseline,
        "warnings": warnings(baseline) + name_warnings(baseline, baseline),
        "name_rules": model_service.NAME_RULES,
    }


# -------------------------------------------------------------- validatie

def warnings(state):
    """Zichtbare waarschuwingen; ze blokkeren opslaan bewust niet."""
    result = []
    elements = state.get("elements") or []

    empty = [str(e.get("id")) for e in elements if not _text(e.get("name"))]
    if empty:
        result.append({
            "kind": "empty_name",
            "message": "%d element(en) zonder naam: id %s" % (len(empty), ", ".join(empty)),
            "ids": empty,
        })

    by_name = {}
    for element in elements:
        name = _text(element.get("name"))
        if not name:
            continue
        by_name.setdefault(name, []).append(element)
    for name, group in sorted(by_name.items()):
        if len(group) > 1:
            result.append({
                "kind": "duplicate_name",
                "message": "Naam '%s' komt %d keer voor" % (name, len(group)),
                "ids": [str(e.get("id")) for e in group],
                "name": name,
            })

    by_address = {}
    for element in elements:
        key = (_text(element.get("ringId")), _text(element.get("unit")),
               _text(element.get("address")))
        by_address.setdefault(key, []).append(element)
    for key, group in sorted(by_address.items()):
        if len(group) > 1 and all(part != "" for part in key):
            result.append({
                "kind": "duplicate_address",
                "message": "Ring %s, unit %s, adres %s komt %d keer voor"
                           % (key[0], key[1], key[2], len(group)),
                "ids": [str(e.get("id")) for e in group],
            })
    return result


def name_warnings(state, baseline=None):
    """Naamcontrole als waarschuwingen (code ``invalid_name_existing``).

    Gebruikt dezelfde pure validator als :func:`save`, maar levert alleen
    leesbare regels; blokkeren doet alleen :func:`save`.
    """
    result = []
    for violation in model_service.validate_names(state, baseline):
        result.append({
            "kind": "invalid_name_existing",
            "code": violation["code"],
            "soort": violation["soort"],
            "id": violation["id"],
            "veld": violation["veld"],
            "waarde": violation["waarde"],
            "message": name_validation.describe(violation),
        })
    return result


# ------------------------------------------------------------------- diff

def _zone_plan(baseline, state):
    """Bepaal zone-operaties en de voorspelde id per zone-index.

    Nieuwe zones krijgen van ``ZenixTool`` sequentieel ``max(id) + 1``; dat is
    hier voorspelbaar omdat we de ``@zone new``-regels in deze volgorde aanbieden.
    """
    base_zones = {int(z["id"]): z for z in baseline.get("zones") or []}
    desired = state["zones"]
    base_names = set(_text(z.get("name")) for z in base_zones.values())

    ops, ids_by_index, names_to_id = [], {}, {}
    existing_ids, new_names = set(), {}
    next_id = (max(base_zones) + 1) if base_zones else 1
    for index, zone in enumerate(desired):
        name = _text(zone.get("name"))
        description = _text(zone.get("description"))
        raw_id = zone.get("id")
        zone_id = None if raw_id is None or _text(raw_id) == "" else _as_int(raw_id, "zone-id")
        if zone_id is not None and zone_id in base_zones:
            ids_by_index[index] = zone_id
            existing_ids.add(zone_id)
            names_to_id[name] = zone_id
            base = base_zones[zone_id]
            if name != _text(base.get("name")) or description != _text(base.get("description")):
                if not name:
                    raise EditorError("Een zone mag geen lege naam hebben")
                ops.append({"op": "zone_update", "zone_id": zone_id,
                            "name": name, "description": description})
        elif zone_id is None:
            if not name:
                raise EditorError("Een nieuwe zone moet een naam hebben")
            if name in base_names or name in new_names:
                raise EditorError("Er bestaat al een zone met de naam '%s'" % name)
            predicted = next_id
            next_id += 1
            new_names[name] = predicted
            ids_by_index[index] = predicted
            names_to_id[name] = predicted
            ops.append({"op": "zone_add", "name": name, "description": description})
        else:
            raise EditorError("Onbekende zone-id %s" % zone_id)

    for zone_id in base_zones:
        if zone_id not in existing_ids:
            ops.append({"op": "zone_delete", "zone_id": zone_id})
    valid_ids = set(base_zones) | set(ids_by_index.values())
    return ops, ids_by_index, valid_ids, names_to_id


#: Vaste melding als een bestaande ring zijn host leegmaakt. De tekst komt uit
#: :mod:`model_service` (``ring_update.host``) zodat beide lagen niet kunnen
#: divergeren.
EMPTY_HOST_MESSAGE = model_service.EMPTY_HOST_MESSAGE


def _ring_plan(baseline, state):
    """Bepaal ring-operaties en de voorspelde id per ring-index.

    Nieuwe ringen krijgen van ``ZenixTool`` ``max(id) + 1``; dat is hier
    voorspelbaar omdat de ``@ringadd``-regels in deze volgorde worden
    aangeboden en vóór alle element-operaties worden toegepast. Ringen
    verwijderen kan niet (elementen verwijzen ernaar).
    """
    base_rings = {int(r["id"]): r for r in baseline.get("rings") or []}
    desired = state["rings"]
    base_names = {_ring_key(r.get("name")): ring_id
                  for ring_id, r in base_rings.items()}

    ops, ids_by_index, names_to_id, expected = [], {}, {}, []
    existing_ids = set()
    next_id = (max(base_rings) + 1) if base_rings else 1
    seen_names = {}

    for index, ring in enumerate(desired):
        name = _text(ring.get("name"))
        name_key = _ring_key(name)
        raw_id = ring.get("id")
        ring_id = None if raw_id is None or _text(raw_id) == "" else _as_int(raw_id, "ring-id")
        has_host = "host" in ring
        raw_host = _text(ring.get("host"))
        if ring_id is not None and ring_id in base_rings:
            base = base_rings[ring_id]
            base_name = _text(base.get("name"))
            base_host = _text(base.get("host"))
            if not name:
                raise EditorError("Een ring mag geen lege naam hebben")
            # Hoofdletterongevoelig, net als de service-API; de eigen oude naam
            # telt niet als botsing (een pure case-rename mag wel).
            if name != base_name and (
                    (name_key in base_names and base_names[name_key] != ring_id)
                    or name_key in seen_names):
                raise EditorError("Er bestaat al een ring met de naam '%s'" % name)
            if has_host and not raw_host and base_host:
                raise EditorError(EMPTY_HOST_MESSAGE)
            fields = {}
            host = base_host
            if name != base_name:
                fields["name"] = name
            if has_host and raw_host and raw_host != base_host:
                fields["host"] = raw_host
                host = raw_host
            existing_ids.add(ring_id)
            ids_by_index[index] = ring_id
            names_to_id[name] = ring_id
            # ``host_changed`` bepaalt of de host na het opslaan vergeleken mag
            # worden: de vendor normaliseert een lege baseline-host en dat mag
            # geen valse fout geven bij een ring waarvan de gebruiker de host
            # niet aanraakte (ook niet bij een pure hernoeming).
            expected.append({"name": name, "host": host, "changed": bool(fields),
                             "host_changed": "host" in fields})
            if fields:
                ops.append({"op": "ring_update", "ring_id": ring_id, "fields": fields})
        elif ring_id is None:
            if not name:
                raise EditorError("Een nieuwe ring moet een naam hebben")
            if name_key in base_names or name_key in seen_names:
                raise EditorError("Er bestaat al een ring met de naam '%s'" % name)
            ring_id = next_id
            next_id += 1
            host = raw_host or "localhost"
            ids_by_index[index] = ring_id
            names_to_id[name] = ring_id
            expected.append({"name": name, "host": host, "changed": True,
                             "host_changed": True})
            ops.append({"op": "ring_add", "name": name, "host": host})
        else:
            raise EditorError("Onbekende ring-id %s" % ring_id)
        seen_names[name_key] = index

    if len(set(_ring_key(spec["name"]) for spec in expected)) != len(expected):
        raise EditorError("Ringen mogen geen dubbele naam hebben")
    for ring_id in base_rings:
        if ring_id not in existing_ids:
            raise EditorError("Ringen verwijderen kan niet in deze editor (ring %s)" % ring_id)
    valid_ids = set(base_rings) | set(ids_by_index.values())
    return {
        "ops": ops,
        "ids_by_index": ids_by_index,
        "names_to_id": names_to_id,
        "ids": valid_ids,
        "expected": expected,
    }


def _resolve_zone_refs(refs, names_to_id, valid_ids):
    out = []
    for ref in refs:
        text = _text(ref)
        if text == "":
            continue
        resolved = None
        try:
            numeric = int(text)
        except ValueError:
            numeric = None
        if numeric is not None and numeric in valid_ids:
            resolved = numeric
        elif text in names_to_id:
            resolved = names_to_id[text]
        else:
            raise EditorError("Onbekende zone: %s" % text)
        if resolved not in out:
            out.append(resolved)
    return out


def _update_fields(base, desired, names_to_id, valid_ids, ring_names):
    """Vergelijk een bestaand element met de gewenste staat en bouw ``@set``-velden."""
    fields = {}
    if "unitId" in desired:
        value = _text(desired.get("unitId"))
        if value != _text(base.get("unitId")):
            fields["unitId"] = value
    for key in BOOL_FIELDS:
        if key in desired:
            value = _as_bool(desired.get(key), key)
            if value is not bool(base.get(key)):
                fields[key] = value
    if "safe" in desired:
        value = _text(desired.get("safe"))
        if value != _text(base.get("safe")):
            fields["safe"] = value
    if "alarmFunction" in desired:
        value = _text(desired.get("alarmFunction"))
        if value != _text(base.get("alarmFunction")):
            fields["alarmFunction"] = value
    if "description" in desired:
        value = _text(desired.get("description"))
        if value != _text(base.get("description")):
            fields["description"] = value
    if "unit" in desired:
        value = _as_int(desired.get("unit"), "unit")
        if value != int(base.get("unit")):
            fields["unit"] = value
    if "address" in desired:
        value = _as_int(desired.get("address"), "adres")
        if value != int(base.get("address")):
            fields["address"] = value
            # de vendor-conventie: addressOnUnit = address - 1 (zie @add)
            fields["addressOnUnit"] = value - 1
    if "type" in desired:
        value = model_service._type_code(desired.get("type"))
        if value != int(base.get("type")):
            fields["type"] = value
    if "deviceType" in desired:
        value = model_service._device_code(desired.get("deviceType"))
        if value != int(base.get("deviceType")):
            fields["deviceType"] = value
    if "ringId" in desired:
        value = _as_int(desired.get("ringId"), "ring")
        if value != int(base.get("ringId")):
            if value not in ring_names:
                raise EditorError("Onbekende ring-id %s" % value)
            fields["ring"] = ring_names[value]
    if "zones" in desired:
        refs = _resolve_zone_refs(_zones_of(desired), names_to_id, valid_ids)
        if sorted(refs) != sorted(int(z) for z in base.get("zones") or []):
            fields["zones"] = refs
    return fields


def _add_op(desired, ring_names, names_to_id, valid_ids):
    ring_id = _as_int(desired.get("ringId"), "ring")
    if ring_id not in ring_names:
        raise EditorError("Onbekende ring-id %s" % ring_id)
    op = {
        "op": "add",
        "ring_id": ring_id,
        "unit": _as_int(desired.get("unit"), "unit"),
        "address": _as_int(desired.get("address"), "adres"),
        "type": desired.get("type"),
        "device_type": desired.get("deviceType"),
        "unit_id": _text(desired.get("unitId")),
        "zones": _resolve_zone_refs(_zones_of(desired), names_to_id, valid_ids),
    }
    name = _text(desired.get("name"))
    if name:
        op["name"] = name
    return op


def diff(baseline, state):
    """Vertaal baseline + gewenste staat naar operaties (zonder ``order``)."""
    _validate_state(state)
    desired_elements = state["elements"]
    base_elements = baseline.get("elements") or []
    base_by_id = {int(e["id"]): e for e in base_elements}

    zone_ops, _ids_by_index, valid_zone_ids, names_to_id = _zone_plan(baseline, state)
    ring_plan = _ring_plan(baseline, state)
    ring_names = {ring_id: name for name, ring_id in ring_plan["names_to_id"].items()}
    alarm_ops, base_alarms = _alarm_plan(baseline, state)
    desired_alarms = state.get("alarms", base_alarms) if "alarms" in state else base_alarms

    adds, updates, renames, deletes = [], [], [], []
    seen = set()
    for element in desired_elements:
        element_id = _element_id(element)
        if element_id is None:
            adds.append(_add_op(element, ring_names, names_to_id, valid_zone_ids))
            continue
        base = base_by_id.get(element_id)
        if base is None:
            raise EditorError("Onbekend element-id %s" % element_id)
        if element_id in seen:
            raise EditorError("Element-id %s komt dubbel voor" % element_id)
        seen.add(element_id)
        if "name" in element:
            name = _text(element.get("name"))
            if name != _text(base.get("name")):
                renames.append({"op": "rename", "id": element_id, "name": name})
        fields = _update_fields(base, element, names_to_id, valid_zone_ids, ring_names)
        matrix_ops = []
        cells = _matrix_cells(element, desired_alarms,
                              "element '%s'" % (base.get("name") or element_id))
        if cells is not None:
            base_cells = _matrix_cells(base, None, "element '%s'" % element_id) or {}
            for alarm_id in sorted(cells):
                if base_cells.get(alarm_id, -1) != cells[alarm_id]:
                    matrix_ops.append({"op": "alarm_value", "element_id": element_id,
                                       "alarm_id": alarm_id, "value": cells[alarm_id]})
        if fields:
            updates.append({"op": "update", "id": element_id, "fields": fields})
        updates.extend(matrix_ops)

    for element_id in base_by_id:
        if element_id not in seen:
            deletes.append({"op": "delete", "id": element_id})

    order = [op for op in zone_ops if op["op"].startswith("zone_")]
    # ring-operaties eerst: elementen (ook nieuwe) verwijzen naar de ring;
    # alarm-operaties staan bewust vóór de element-operaties.
    ops = (alarm_ops + ring_plan["ops"] + adds + updates + renames + order + deletes)
    return ops


# --------------------------------------------------------------- opslaan

def output_name(state, baseline):
    name = _text(state.get("project")) or _text(baseline.get("project")) or "project"
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip() or "project"
    return name + OUTPUT_SUFFIX


def _map_desired(state):
    """Index in ``state['elements']`` per baseline-id en de lijst nieuwe indices."""
    index_of, new_indexes, seen = {}, [], set()
    for index, element in enumerate(state["elements"]):
        element_id = _element_id(element)
        if element_id is None:
            new_indexes.append(index)
        else:
            if element_id in seen:
                raise EditorError("Element-id %s komt dubbel voor" % element_id)
            seen.add(element_id)
            index_of[element_id] = index
    return index_of, new_indexes, seen


def _order_ops(baseline, state, pass1):
    index_of, new_indexes, seen = _map_desired(state)
    still_there = [int(e["id"]) for e in baseline.get("elements") or [] if int(e["id"]) in seen]
    expected = len(still_there) + len(new_indexes)
    if len(pass1.get("elements") or []) != expected:
        raise EditorError(
            "Tussenstap leverde %d elementen op, verwacht %d"
            % (len(pass1.get("elements") or []), expected))

    mapping = {}
    position_of = {element_id: pos for pos, element_id in enumerate(still_there)}
    for element_id, index in index_of.items():
        mapping[index] = position_of[element_id]
    for offset, index in enumerate(new_indexes):
        mapping[index] = len(still_there) + offset

    per_ring = {}
    for index, element in enumerate(state["elements"]):
        ring_id = _as_int(element.get("ringId"), "ring")
        per_ring.setdefault(ring_id, []).append(mapping[index])

    counts = {}
    for element in pass1.get("elements") or []:
        ring_id = int(element["ringId"])
        counts[ring_id] = counts.get(ring_id, 0) + 1
    if set(per_ring) != set(counts):
        raise EditorError("De ringen in de nieuwe staat komen niet overeen met het project")
    ops = []
    for ring_id, ids in per_ring.items():
        if len(ids) != counts[ring_id]:
            raise EditorError("Ring %s heeft %d van %d elementen"
                              % (ring_id, len(ids), counts[ring_id]))
        ops.append({"op": "order", "ring_id": ring_id, "ids": ids})
    return ops, mapping, new_indexes


def _new_element_updates(state, pass1, mapping, new_indexes, names_to_id, valid_ids,
                         ring_names):
    """Zet velden die ``@add`` niet zet (enabled, omschrijving, ...) op nieuwe elementen.

    ``@set`` werkt met ids uit de snapshot van ronde 1; een nieuw element heeft
    die id dus pas nadat ronde 1 is weggeschreven. In ronde 2 zetten we deze
    velden daarom alsnog, met de ids uit ronde 1.
    """
    pass1_by_id = {int(e["id"]): e for e in pass1.get("elements") or []}
    pass1_alarms = pass1.get("alarms") or []
    updates = []
    for index in new_indexes:
        pass1_id = mapping[index]
        have = pass1_by_id.get(pass1_id)
        if have is None:
            raise EditorError("Nieuw element %d ontbreekt in de tussenstap" % index)
        desired = dict(state["elements"][index])
        # Een leeg 'safe' betekent voor een nieuw element: laat de vendor-default
        # (@add zet 'stay') staan in plaats van die leeg te schrijven.
        if not _text(desired.get("safe")):
            desired.pop("safe", None)
        fields = _update_fields(have, desired, names_to_id, valid_ids, ring_names)
        if fields:
            updates.append({"op": "update", "id": pass1_id, "fields": fields})
        # Nieuwe elementen krijgen pas in ronde 1 een id; hun matrixcellen gaan
        # daarom in ronde 2 mee. -1 is al de vendor-default uit @add.
        cells = _matrix_cells(state["elements"][index], pass1_alarms,
                              "nieuw element %d" % index)
        if cells:
            for alarm_id in sorted(cells):
                if cells[alarm_id] != -1:
                    updates.append({"op": "alarm_value", "element_id": pass1_id,
                                    "alarm_id": alarm_id, "value": cells[alarm_id]})
    return updates


def _expected_refs(element, names_to_id, valid_ids):
    return sorted(_resolve_zone_refs(_zones_of(element), names_to_id, valid_ids))


def _verify(state, result, zone_prediction, ring_prediction=None):
    """Controleer dat het weggeschreven project exact de getoonde staat bevat."""
    desired = state["elements"]
    got = result.get("elements") or []
    if len(desired) != len(got):
        raise EditorError("Na opslaan staan er %d elementen in plaats van %d"
                          % (len(got), len(desired)))

    # alarmen: aantal, namen en omschrijvingen (volgorde/id liggen vast)
    desired_alarms = state.get("alarms") if "alarms" in state else None
    got_alarms = result.get("alarms") or []
    if desired_alarms is not None:
        if len(got_alarms) != len(desired_alarms):
            raise EditorError("Na opslaan zijn er %d alarmen in plaats van %d"
                              % (len(got_alarms), len(desired_alarms)))
        for index, alarm in enumerate(desired_alarms):
            have_alarm = got_alarms[index]
            if _text(have_alarm.get("name")) != _text(alarm.get("name")):
                raise EditorError("Alarmnaam '%s' is niet opgeslagen"
                                  % _text(alarm.get("name")))
            if _text(have_alarm.get("description")) != _text(alarm.get("description")):
                raise EditorError("Omschrijving van alarm '%s' is niet opgeslagen"
                                  % _text(alarm.get("name")))
    alarms_for_matrix = desired_alarms if desired_alarms is not None else got_alarms

    per_ring = {}
    for element in desired:
        per_ring.setdefault(_as_int(element.get("ringId"), "ring"), []).append(element)
    grouped = {}
    for element in got:
        grouped.setdefault(int(element["ringId"]), []).append(element)

    if set(per_ring) != set(grouped):
        raise EditorError("De ringindeling na opslaan wijkt af")

    for ring_id, wanted in per_ring.items():
        actual = grouped[ring_id]
        if len(wanted) != len(actual):
            raise EditorError("Ring %s heeft na opslaan %d van %d elementen"
                              % (ring_id, len(actual), len(wanted)))
        for position, (want, have) in enumerate(zip(wanted, actual), start=1):
            if have["indexInRing"] != position:
                raise EditorError("indexInRing van '%s' is %s, verwacht %d"
                                  % (have.get("name"), have["indexInRing"], position))
            name = _text(want.get("name"))
            if name and _text(have.get("name")) != name:
                raise EditorError("Naam '%s' is niet opgeslagen" % name)
            if not _text(have.get("name")):
                raise EditorError("Een element heeft na opslaan geen naam")
            checks = {
                "unit": _as_int(want.get("unit"), "unit"),
                "address": _as_int(want.get("address"), "adres"),
                "unitId": _text(want.get("unitId")),
                "enabled": _as_bool(want.get("enabled"), "enabled"),
                "invert": _as_bool(want.get("invert"), "invert"),
                "normalOpen": _as_bool(want.get("normalOpen"), "normalOpen"),
                "safe": _text(want.get("safe")),
                "description": _text(want.get("description")),
                "alarmFunction": _text(want.get("alarmFunction")),
                "type": model_service._type_code(want.get("type")),
                "deviceType": model_service._device_code(want.get("deviceType")),
                "zones": _expected_refs(want, zone_prediction["names"], zone_prediction["ids"]),
            }
            if _element_id(want) is None and not _text(want.get("safe")):
                # nieuw element zonder expliciete safe: vendor-default blijft staan
                checks.pop("safe", None)
            for key, expected in checks.items():
                if key == "safe":
                    actual_value = _text(have.get("safeRaw") if have.get("safe") is None
                                         else have.get("safe"))
                elif key == "zones":
                    actual_value = sorted(int(z) for z in have.get("zones") or [])
                elif key in ("enabled", "invert", "normalOpen"):
                    actual_value = bool(have.get(key))
                elif key in ("type", "deviceType", "unit", "address"):
                    actual_value = int(have.get(key))
                else:
                    actual_value = _text(have.get(key))
                if actual_value != expected:
                    raise EditorError(
                        "Veld '%s' van '%s' is na opslaan %r, verwacht %r"
                        % (key, have.get("name"), actual_value, expected))

            want_cells = _matrix_cells(
                want, alarms_for_matrix, "element '%s'" % (have.get("name")))
            if want_cells is not None:
                have_cells = _matrix_cells(
                    have, alarms_for_matrix, "element '%s'" % (have.get("name"))) or {}
                if have_cells != want_cells:
                    raise EditorError(
                        "De controlematrix van '%s' is niet opgeslagen" % have.get("name"))

    # zones: aantal, namen, omschrijvingen en voorspelde ids
    result_zones = {int(z["id"]): z for z in result.get("zones") or []}
    if len(result_zones) != len(state["zones"]):
        raise EditorError("Na opslaan zijn er %d zones in plaats van %d"
                          % (len(result_zones), len(state["zones"])))
    for index, zone in enumerate(state["zones"]):
        zone_id = zone_prediction["ids_by_index"][index]
        have = result_zones.get(zone_id)
        if have is None:
            raise EditorError("Zone '%s' ontbreekt na opslaan" % _text(zone.get("name")))
        if _text(have.get("name")) != _text(zone.get("name")):
            raise EditorError("Zonenaam '%s' is niet opgeslagen" % _text(zone.get("name")))
        if _text(have.get("description")) != _text(zone.get("description")):
            raise EditorError("Zone-omschrijving van '%s' is niet opgeslagen"
                              % _text(zone.get("name")))

    # ringen: aantal, naam en host per ring
    if ring_prediction is not None:
        result_rings = {int(r["id"]): r for r in result.get("rings") or []}
        if len(result_rings) != len(state["rings"]):
            raise EditorError("Na opslaan zijn er %d ringen in plaats van %d"
                              % (len(result_rings), len(state["rings"])))
        for index, ring in enumerate(state["rings"]):
            ring_id = ring_prediction["ids_by_index"][index]
            spec = ring_prediction["expected"][index]
            expected_name, expected_host = spec["name"], spec["host"]
            have = result_rings.get(ring_id)
            if have is None:
                raise EditorError("Ring '%s' ontbreekt na opslaan" % expected_name)
            if _text(have.get("name")) != expected_name:
                raise EditorError("Ringnaam '%s' is niet opgeslagen" % expected_name)
            # Alleen de host van een ring die de gebruiker werkelijk wijzigde
            # wordt gecontroleerd; een ongemoeide ring met een lege baseline-host
            # mag door de vendor-normalisatie geen valse fout geven.
            if spec.get("host_changed") and _text(have.get("host")) != expected_host:
                raise EditorError("Host van ring '%s' is niet opgeslagen" % expected_name)


def _ordering_changed(baseline, state):
    """True als de volgorde per ring afwijkt van de baseline (voor de dirty-vlag)."""
    present = set()
    for element in state["elements"]:
        element_id = _element_id(element)
        if element_id is not None:
            present.add(element_id)
    wanted, current = {}, {}
    for element in state["elements"]:
        ring_id = _as_int(element.get("ringId"), "ring")
        wanted.setdefault(ring_id, []).append(_element_id(element))
    for element in baseline.get("elements") or []:
        if int(element["id"]) in present:
            current.setdefault(int(element["ringId"]), []).append(int(element["id"]))
    return wanted != current


def save(sid, state):
    """Pas de gewenste staat toe op de werkkopie en schrijf het resultaat.

    De response bevat onder ``state`` de volledige staat zoals die opnieuw uit
    het weggeschreven bestand is gelezen (echte ids, vendor-namen, volgorde).
    Na een geslaagde controle rebaset de sessie op dat resultaat: de baseline
    wordt de nieuwe dump en de blob de geschreven bytes, zodat een volgende
    save tegen de nieuwe waarheid difft (en ``changed`` false kan zijn).
    De sessiesleutel blijft ongewijzigd: het bestand is met die sleutel
    geschreven en ``core.decrypt`` levert per definitie de sleutel waarmee het
    bestand opent. ``changed`` wordt nog tegen de oude baseline berekend.
    """
    session = SESSIONS.get(sid)
    baseline = session["baseline"]
    _validate_state(state)

    source_before = None
    if session.get("source_path"):
        source_before = _hash(session["source_path"])
        if session.get("source_hash") and source_before != session["source_hash"]:
            raise EditorError("Het bronbestand is gewijzigd sinds het openen")

    _zone_ops, ids_by_index, valid_ids, names_to_id = _zone_plan(baseline, state)
    ring_plan = _ring_plan(baseline, state)

    # Naamcontrole vóór diff/apply: een nieuwe of gewijzigde ongeldige naam
    # blokkeert de save (HTTP 400 met de violation-lijst); bestaande
    # overtredingen gaan als waarschuwing mee en blokkeren niet.
    violations = model_service.validate_names(state, baseline)
    blocking = [v for v in violations if v["changed"]]
    if blocking:
        raise NameValidationError(blocking)
    existing_name_warnings = name_warnings(state, baseline)

    ops = diff(baseline, state)
    edits = model_service.operations_to_edits(ops)

    blob1 = core.apply_edits(session["blob"], session["key"], edits)
    pass1_path = os.path.join(session["dir"], "tussenstap.rbtproject")
    with open(pass1_path, "wb") as f:
        f.write(blob1)
    key1, zip1, pass1 = core.open_project(pass1_path)

    order_ops, mapping, new_indexes = _order_ops(baseline, state, pass1)
    ring_names = {int(r["id"]): _text(r.get("name")) for r in baseline.get("rings") or []}
    follow_up = _new_element_updates(state, pass1, mapping, new_indexes,
                                     names_to_id, valid_ids, ring_names)
    blob2 = core.apply_edits(zip1, key1,
                             model_service.operations_to_edits(follow_up + order_ops))

    name = output_name(state, baseline)
    out = os.path.join(session["dir"], name)
    with open(out, "wb") as f:
        f.write(blob2)
    key_out, blob_out, result = model_service.read_project_full(out)
    # Het bestand is met session["key"] geschreven; decrypt() geeft dus die
    # sleutel terug. Wijk het af, dan is de sessie niet meer te vertrouwen.
    if key_out != session["key"]:
        raise EditorError("Het weggeschreven bestand opent met een andere sleutel")

    _verify(state, result, {"ids_by_index": ids_by_index, "names": names_to_id,
                            "ids": valid_ids}, ring_plan)

    if source_before is not None:
        if _hash(session["source_path"]) != source_before:
            raise EditorError("Het bronbestand is gewijzigd tijdens het opslaan")

    session["output"] = out
    session["output_name"] = name
    response = {
        "filename": name,
        "download": "/api/projects/%s/download" % sid,
        "elements": len(result.get("elements") or []),
        "zones": len(result.get("zones") or []),
        "rings": len(result.get("rings") or []),
        "state": result,
        "warnings": warnings(result) + existing_name_warnings,
        "changed": bool(ops) or _ordering_changed(baseline, state),
        "preview": _preview(state, result),
    }

    # rebase: volgende save difft tegen het zojuist geschreven bestand.
    # session["key"] blijft ongewijzigd (zie de check hierboven).
    session["baseline"] = result
    session["blob"] = blob_out
    return response


def _preview(state, result):
    """Korte samenvatting per ring: namen in de opgeslagen volgorde."""
    names = {}
    for element in result.get("elements") or []:
        names.setdefault(str(element["ringId"]), []).append(_text(element.get("name")))
    return names


def download_info(sid):
    session = SESSIONS.get(sid)
    if not session.get("output") or not os.path.exists(session["output"]):
        raise EditorError("Dit project is nog niet opgeslagen")
    return session["output"], session["output_name"]


def close(sid):
    return SESSIONS.close(sid)
