"""Vendor-naamregels voor elementen, zones en ringen.

Deze module is de enige bron van waarheid voor de naamcontrole van de Ringbus Editor.
De regels komen letterlijk uit de vendor-klassen
``com/euroicc/ringbus/config/check/NameValidator.java`` (verboden tekens,
gereserveerde namen) en ``com/euroicc/rbtool/project/syntax/SyntaxChecker.java``
(regel 1045: de zone-uitzondering voor de spatie). Dezelfde tekenset zat al in
:data:`diff_edits.FORBIDDEN_NAME`; die blijft staan voor de Excel-route, maar
alle nieuwe controles lopen via deze module.

Wat de vendor doet en wat hier wordt nagebootst:

* elementnamen: 28 ASCII-tekens inclusief de spatie, de vijf streepvarianten
  (U+2010..U+2015), de ASCII-hyphen en CR/LF/TAB zijn verboden; ``_``, letters
  en cijfers mogen wel;
* zonenamen: dezelfde set **zonder** de spatie-uitzondering (SyntaxChecker regel
  1045 staat daar een spatie toe);
* ringnamen: als zonenamen; een ringnaam mag niet samenvallen met een
  elementnaam of met een andere ring;
* alarmnamen: de elementtekenset (alarmen leven in dezelfde vendor-namespace);
  een alarmnaam moet uniek zijn binnen die gedeelde namespace;
* namen zijn uniek binnen één gedeelde namespace van elementen en alarmen
  (case-sensitief, net als de vendor); de echte dump van de vendor
  (``core.open_project``) bevat ``elements``, ``zones``, ``rings``,
  ``gateways`` en ``alarms``. Er is geen aparte hulpelementenlijst; de
  tolerantie voor ``auxiliaryElements``/``aux`` blijft alleen staan voor
  handmatig samengestelde dumps en wordt nooit als waarheid aangenomen;
* ``bae_1``..``bae_1024`` en ``open_1``..``open_1024`` zijn gereserveerd en
  mogen niet als naam gebruikt worden (ook case-sensitief; de vendor gebruikt
  kleine letters).

:func:`validate_names` is puur: hij leest ``state`` en optioneel ``baseline`` en
geeft per overtreding een dict terug. De aanroeper beslist wat hard is: een
overtreding op een veld dat de gebruiker heeft toegevoegd of gewijzigd
(``changed`` is ``True``) blokkeert opslaan, een bestaande overtreding wordt
alleen een waarschuwing.
"""
from __future__ import annotations

#: 28 ASCII-tekens die de vendor in elementnamen weigert (inclusief spatie).
_ELEMENT_ASCII = tuple("().,!|&<>?*+/\\=\"%$#:;^'[]{} ")

#: De vijf streepvarianten die de vendor weigert.
_DASH_VARIANTS = ("\u2010", "\u2011", "\u2013", "\u2014", "\u2015")

#: Regeleinden en tab breken bovendien het ``@``-protocol van ZenixTool.
_CONTROL_CHARS = ("\r", "\n", "\t")

#: Letterlijke vendor-set voor elementnamen: 28 ASCII + 5 streepvarianten +
#: de ASCII-hyphen + CR/LF/TAB = 37 tekens. De opdracht noemt 38; de vendor-
#: afgeleide lijst in ``diff_edits.py`` en de handleiding bevatten 37 tekens en
#: er is geen bron voor een 38e. Er wordt er dus geen verzonnen.
FORBIDDEN_ELEMENT_CHARS = _ELEMENT_ASCII + _DASH_VARIANTS + ("-",) + _CONTROL_CHARS

#: Zone- en ringnamen: dezelfde set, maar de spatie is toegestaan.
FORBIDDEN_ZONE_CHARS = tuple(c for c in FORBIDDEN_ELEMENT_CHARS if c != " ")

_ELEMENT_CHAR_SET = frozenset(FORBIDDEN_ELEMENT_CHARS)
_ZONE_CHAR_SET = frozenset(FORBIDDEN_ZONE_CHARS)

#: ``minusForbidden`` van de vendor: de ASCII-hyphen is verboden.
MINUS_FORBIDDEN = True

#: Ondergrens en bovengrens van de vendor-gereserveerde namen.
RESERVED_PREFIXES = ("bae_", "open_")
RESERVED_MAX = 1024

RESERVED_NAMES = frozenset(
    ["%s%d" % (prefix, number)
     for prefix in RESERVED_PREFIXES
     for number in range(1, RESERVED_MAX + 1)])

EMPTY = "EMPTY"
INVALID_CHAR = "INVALID_CHAR"
TAKEN_NAME = "TAKEN_NAME"
RESERVED_NAME = "RESERVED_NAME"

#: Nederlandse teksten; de web-UI gebruikt dezelfde templates.
NAME_MESSAGES = {
    EMPTY: "Naam mag niet leeg zijn",
    INVALID_CHAR: "Naam bevat het verboden teken '{teken}'",
    TAKEN_NAME: "Naam '{waarde}' bestaat al",
    RESERVED_NAME: "Naam '{waarde}' is gereserveerd door de vendor",
}

#: Regelset die de web-UI bij het openen krijgt (client-side controle).
NAME_RULES = {
    "element_forbidden": list(FORBIDDEN_ELEMENT_CHARS),
    "alarm_forbidden": list(FORBIDDEN_ELEMENT_CHARS),
    "zone_forbidden": list(FORBIDDEN_ZONE_CHARS),
    "reserved_names": {"prefixes": list(RESERVED_PREFIXES), "max": RESERVED_MAX},
    "space_allowed_in_zones": True,
    "messages": dict(NAME_MESSAGES),
}


def forbidden_chars(soort="element", minus_forbidden=MINUS_FORBIDDEN):
    """Geef de verboden tekens voor ``soort`` (``element`` of ``zone``/``ring``)."""
    chars = FORBIDDEN_ELEMENT_CHARS if soort == "element" else FORBIDDEN_ZONE_CHARS
    if minus_forbidden:
        return chars
    return tuple(c for c in chars if c != "-")


def _text(value):
    return "" if value is None else str(value)


def _name(item):
    if not isinstance(item, dict):
        return ""
    # Bewust niet strippen: de tekensetcontrole hoort op de ruwe naam te lopen,
    # zodat ' pomp' en 'pomp ' als INVALID_CHAR met teken ' ' worden geweigerd
    # in plaats van stil genormaliseerd. Alleen de leegte-check gebruikt strip().
    return _text(item.get("name"))


def _id_of(item):
    """Stabiele id van een element/zone/ring, of ``None`` voor een nieuw item."""
    raw = item.get("id") if isinstance(item, dict) else None
    if raw is None or _text(raw).strip() == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _baseline_names(baseline, key):
    result = {}
    for item in (baseline or {}).get(key) or []:
        ident = _id_of(item)
        if ident is not None:
            result[ident] = _name(item)
    return result


def _changed(ident, name, base):
    if ident is None:
        return True
    if ident not in base:
        return True
    return base[ident] != name


def _first_forbidden(name, charset):
    for char in name:
        if char in charset:
            return char
    return None


def _violation(code, soort, ident, name, changed, teken=None):
    violation = {
        "code": code,
        "soort": soort,
        "id": ident,
        "veld": "name",
        "waarde": name,
        "changed": bool(changed),
    }
    if teken is not None:
        violation["teken"] = teken
    return violation


def describe(violation):
    """Nederlandse melding voor een violation-dict (voor waarschuwingen/UI)."""
    template = NAME_MESSAGES.get(violation.get("code"), "Ongeldige naam")
    return (template
            .replace("{teken}", _text(violation.get("teken")))
            .replace("{waarde}", _text(violation.get("waarde"))))


def _is_reserved(name):
    return name in RESERVED_NAMES


def validate_names(state, baseline=None):
    """Controleer alle namen in ``state``; puur en zonder neveneffecten.

    ``state`` is de dump-vorm met ``rings``, ``zones``, ``elements`` en
    optioneel ``alarms``/``auxiliaryElements``. ``baseline`` is dezelfde vorm op
    het moment van openen; zonder baseline geldt elke overtreding als gewijzigd.

    Geeft een lijst dicts met ``code`` (EMPTY|INVALID_CHAR|TAKEN_NAME|
    RESERVED_NAME), ``soort`` (element|alarm|zone|ring), ``id``, ``veld``
    (``name``), ``waarde``, ``changed`` en bij INVALID_CHAR ook ``teken``.
    """
    state = state if isinstance(state, dict) else {}
    baseline = baseline if isinstance(baseline, dict) else None

    elements = [e for e in (state.get("elements") or []) if isinstance(e, dict)]
    zones = [z for z in (state.get("zones") or []) if isinstance(z, dict)]
    rings = [r for r in (state.get("rings") or []) if isinstance(r, dict)]
    alarms = [a for a in (state.get("alarms") or []) if isinstance(a, dict)]

    # Gedeelde vendor-namespace: elementen + alarmen. De echte dump bevat een
    # ``alarms``-lijst; ``auxiliaryElements``/``aux`` bestaan daar niet maar
    # worden wel getolereerd voor handmatig samengestelde dumps.
    namespace = list(elements)
    for key in ("auxiliaryElements", "aux"):
        namespace.extend(x for x in (state.get(key) or []) if isinstance(x, dict))
    namespace.extend(a for a in (state.get("alarms") or []) if isinstance(a, dict))

    element_base = _baseline_names(baseline, "elements")
    zone_base = _baseline_names(baseline, "zones")
    ring_base = _baseline_names(baseline, "rings")
    alarm_base = _baseline_names(baseline, "alarms")

    element_counts = {}
    for item in namespace:
        name = _name(item)
        if name.strip():
            element_counts[name] = element_counts.get(name, 0) + 1

    # Wijzigde een item met deze naam? Niet geaggregeerd: een botsing markeert
    # alleen het veld dat de gebruiker zelf aanraakte, zodat de 400 en de UI
    # niet wijzen naar een ongemoeid veld en het aantal fouten niet dubbelt.
    element_touched = {}
    for element in elements:
        name = _name(element)
        if not name.strip():
            continue
        if _changed(_id_of(element), name, element_base):
            element_touched[name] = True

    ring_counts = {}
    for ring in rings:
        name = _name(ring)
        if not name.strip():
            continue
        ring_counts[name] = ring_counts.get(name, 0) + 1

    zone_counts = {}
    for zone in zones:
        name = _name(zone)
        if not name.strip():
            continue
        zone_counts[name] = zone_counts.get(name, 0) + 1

    violations = []

    # ------------------------------------------------------------- elementen
    for element in elements:
        ident = _id_of(element)
        name = _name(element)
        changed = _changed(ident, name, element_base)
        if not name.strip():
            # Een nieuw element zonder naam krijgt van de vendor een naam;
            # alleen een bestaand element met een baseline-id is hier hard.
            if ident is not None:
                violations.append(_violation(EMPTY, "element", ident, name, changed))
            continue
        char = _first_forbidden(name, _ELEMENT_CHAR_SET)
        if char is not None:
            violations.append(
                _violation(INVALID_CHAR, "element", ident, name, changed, char))
            continue
        if _is_reserved(name):
            violations.append(_violation(RESERVED_NAME, "element", ident, name, changed))
            continue
        if element_counts.get(name, 0) > 1:
            violations.append(_violation(TAKEN_NAME, "element", ident, name, changed))
            continue
        # Een botsing met een ringnaam wordt één keer gerapporteerd: op het
        # element als de gebruiker dat wijzigde, anders op de ring (hieronder).
        if name in ring_counts and changed:
            violations.append(_violation(TAKEN_NAME, "element", ident, name, True))
            continue

    # --------------------------------------------------------------- alarmen
    # Alarmnamen leven in dezelfde vendor-namespace als elementen: dezelfde
    # tekenset, dezelfde reserveringen en dezelfde uniciteitsregel.
    for alarm in alarms:
        ident = _id_of(alarm)
        name = _name(alarm)
        changed = _changed(ident, name, alarm_base)
        if not name.strip():
            violations.append(_violation(EMPTY, "alarm", ident, name, changed))
            continue
        char = _first_forbidden(name, _ELEMENT_CHAR_SET)
        if char is not None:
            violations.append(
                _violation(INVALID_CHAR, "alarm", ident, name, changed, char))
            continue
        if _is_reserved(name):
            violations.append(_violation(RESERVED_NAME, "alarm", ident, name, changed))
            continue
        if element_counts.get(name, 0) > 1:
            violations.append(_violation(TAKEN_NAME, "alarm", ident, name, changed))

    # ----------------------------------------------------------------- zones
    for zone in zones:
        ident = _id_of(zone)
        name = _name(zone)
        changed = _changed(ident, name, zone_base)
        if not name.strip():
            violations.append(_violation(EMPTY, "zone", ident, name, changed))
            continue
        char = _first_forbidden(name, _ZONE_CHAR_SET)
        if char is not None:
            violations.append(
                _violation(INVALID_CHAR, "zone", ident, name, changed, char))
            continue
        if _is_reserved(name):
            violations.append(_violation(RESERVED_NAME, "zone", ident, name, changed))
            continue
        if zone_counts.get(name, 0) > 1:
            violations.append(_violation(TAKEN_NAME, "zone", ident, name, changed))

    # ---------------------------------------------------------------- ringen
    for ring in rings:
        ident = _id_of(ring)
        name = _name(ring)
        changed = _changed(ident, name, ring_base)
        if not name.strip():
            violations.append(_violation(EMPTY, "ring", ident, name, changed))
            continue
        char = _first_forbidden(name, _ZONE_CHAR_SET)
        if char is not None:
            violations.append(
                _violation(INVALID_CHAR, "ring", ident, name, changed, char))
            continue
        if _is_reserved(name):
            violations.append(_violation(RESERVED_NAME, "ring", ident, name, changed))
            continue
        takes_element_name = name in element_counts
        if takes_element_name and element_touched.get(name):
            # Al als elementviolation gerapporteerd; geen tweede telling.
            continue
        if ring_counts.get(name, 0) > 1 or takes_element_name:
            violations.append(_violation(TAKEN_NAME, "ring", ident, name, changed))

    return violations
