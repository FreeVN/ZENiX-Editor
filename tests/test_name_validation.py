"""Tests voor de vendor-naamregels en de harde save-gate van de Ringbus Editor.

De regels komen uit ``NameValidator.java`` (tekenset, gereserveerde namen,
gedeelde namespace) en ``SyntaxChecker.java`` regel 1045 (spatie in zonenamen),
zoals doorgegeven via de bestaande vendor-afgeleide constante in
``diff_edits.py`` en de handleiding. De letterlijke set telt 37 tekens; de
opdracht noemt 38 maar er is geen bron voor een 38e teken, dus die is niet
verzonnen.
"""
import hashlib
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
WEB = os.path.join(APP, "web")
for path in (APP, WEB):
    if path not in sys.path:
        sys.path.insert(0, path)

import editor  # noqa: E402
import model_service  # noqa: E402
import name_validation  # noqa: E402
import server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

SAMPLE = "Duizendpoot"
SAMPLE_PATH = "samples/%s/%s.rbtproject" % (SAMPLE, SAMPLE)
SAMPLE_FILE = os.path.join(ROOT, "samples", SAMPLE, SAMPLE + ".rbtproject")


# ----------------------------------------------------------------- fixtures

@pytest.fixture()
def client():
    return TestClient(server.app)


@pytest.fixture()
def opened(client):
    response = client.post("/api/projects/open", json={"path": SAMPLE_PATH})
    assert response.status_code == 200, response.text
    body = response.json()
    return client, body["sid"], body["state"]


def save(client, sid, state):
    return client.post("/api/projects/%s/save" % sid, json=state)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def make_state(elements=(), zones=(), rings=(), **extra):
    state = {
        "project": "naamtest",
        "rings": list(rings),
        "zones": list(zones),
        "elements": list(elements),
    }
    state.update(extra)
    return state


def codes(state, baseline=None):
    return [(v["code"], v["soort"]) for v in name_validation.validate_names(state, baseline)]


VIOLATION_KEYS = {"code", "soort", "id", "veld", "waarde", "changed"}


# --------------------------------------------------------------- tekenset

def test_charset_is_the_literal_vendor_tuple():
    # 28 ASCII (inclusief spatie) + 5 streepvarianten + '-' + CR/LF/TAB.
    assert len(name_validation.FORBIDDEN_ELEMENT_CHARS) == 37
    assert len(set(name_validation.FORBIDDEN_ELEMENT_CHARS)) == 37
    assert name_validation.FORBIDDEN_ELEMENT_CHARS[:28] == \
        tuple("().,!|&<>?*+/\\=\"%$#:;^'[]{} ")
    for code_point in (0x2010, 0x2011, 0x2013, 0x2014, 0x2015):
        assert chr(code_point) in name_validation.FORBIDDEN_ELEMENT_CHARS
    for char in ("-", "\r", "\n", "\t", " "):
        assert char in name_validation.FORBIDDEN_ELEMENT_CHARS
    assert " " not in name_validation.FORBIDDEN_ZONE_CHARS
    assert "-" in name_validation.FORBIDDEN_ZONE_CHARS


def test_minus_forbidden_toggle():
    assert "-" in name_validation.forbidden_chars("element", minus_forbidden=True)
    assert "-" in name_validation.forbidden_chars("zone", minus_forbidden=True)
    assert "-" not in name_validation.forbidden_chars("element", minus_forbidden=False)
    assert "-" not in name_validation.forbidden_chars("zone", minus_forbidden=False)


@pytest.mark.parametrize("char", [" ", "-", ".", "/", ":", "'", "[", "]", "?"])
def test_charset_rejects_each_listed_character(char):
    name = "a" + char + "b"
    violations = name_validation.validate_names(make_state(elements=[{"id": 0, "name": name}]))
    assert len(violations) == 1
    violation = violations[0]
    assert set(violation) == VIOLATION_KEYS | {"teken"}
    assert violation["code"] == "INVALID_CHAR"
    assert violation["soort"] == "element"
    assert violation["id"] == 0
    assert violation["veld"] == "name"
    assert violation["waarde"] == name
    assert violation["teken"] == char


@pytest.mark.parametrize("name", [" pomp", "pomp "])
def test_leading_or_trailing_space_is_not_stripped_before_charset_check(name):
    violations = name_validation.validate_names(
        make_state(elements=[{"id": 0, "name": name}]))
    assert len(violations) == 1, violations
    violation = violations[0]
    assert violation["code"] == "INVALID_CHAR"
    assert violation["soort"] == "element"
    assert violation["waarde"] == name
    assert violation["teken"] == " "


@pytest.mark.parametrize("name", ["di_Ring_01_1", "ABCdef", "naam123", "_", "a_b_c"])
def test_charset_allows_underscore_letters_and_digits(name):
    assert name_validation.validate_names(make_state(elements=[{"id": 0, "name": name}])) == []


# ------------------------------------------------------------------- zones

def test_zone_space_is_allowed_but_other_forbidden_chars_are_not():
    allowed = make_state(zones=[{"id": 1, "name": "Brand weer"}])
    assert name_validation.validate_names(allowed) == []

    for bad in ("Brand,weer", "Brand-weer"):
        violations = name_validation.validate_names(make_state(zones=[{"id": 1, "name": bad}]))
        assert len(violations) == 1, bad
        assert violations[0]["code"] == "INVALID_CHAR"
        assert violations[0]["soort"] == "zone"
        assert violations[0]["teken"] in (",", "-")


# -------------------------------------------------------------- uniciteit

def test_uniqueness_shared_namespace_with_helpers_and_alarms():
    state = make_state(
        elements=[{"id": 0, "name": "gedeeld"}],
        auxiliaryElements=[{"id": 900, "name": "gedeeld"}],
        alarms=[{"id": 0, "name": "gedeeld"}],
    )
    assert ("TAKEN_NAME", "element") in codes(state)


def test_uniqueness_alarms_in_real_dump_shape():
    # De echte vendor-dump (core.open_project) bevat een 'alarms'-lijst en geen
    # aparte hulpelementenlijst; de gedeelde namespace moet daarop werken.
    dump = model_service.read_project(SAMPLE_FILE)
    assert "alarms" in dump
    assert "auxiliaryElements" not in dump
    dump = json.loads(json.dumps(dump))
    dump["alarms"].append({"id": 0, "name": dump["elements"][0]["name"]})
    violations = name_validation.validate_names(dump, dump)
    assert ("TAKEN_NAME", "element") in [(v["code"], v["soort"]) for v in violations]


def test_uniqueness_ring_name_may_not_collide_with_element():
    untouched_baseline = make_state(
        rings=[{"id": 1, "name": "GLV", "host": "localhost"}],
        elements=[{"id": 0, "name": "GLV"}],
    )
    # Ongewijzigde bestaande botsing: één melding, op de ring, als waarschuwing.
    untouched = name_validation.validate_names(untouched_baseline, untouched_baseline)
    assert [(v["code"], v["soort"], v["changed"]) for v in untouched] == \
        [("TAKEN_NAME", "ring", False)]

    # Element hernoemd naar de ringnaam: de melding wijst naar het element.
    element_baseline = make_state(
        rings=[{"id": 1, "name": "GLV", "host": "localhost"}],
        elements=[{"id": 0, "name": "anders"}],
    )
    element_renamed = make_state(
        rings=[{"id": 1, "name": "GLV", "host": "localhost"}],
        elements=[{"id": 0, "name": "GLV"}],
    )
    violations = name_validation.validate_names(element_renamed, element_baseline)
    assert [(v["code"], v["soort"], v["changed"]) for v in violations] == \
        [("TAKEN_NAME", "element", True)]

    # Ring hernoemd naar de elementnaam: de melding wijst naar de ring.
    ring_baseline = make_state(
        rings=[{"id": 1, "name": "Ring", "host": "localhost"}],
        elements=[{"id": 0, "name": "GLV"}],
    )
    ring_renamed = make_state(
        rings=[{"id": 1, "name": "GLV", "host": "localhost"}],
        elements=[{"id": 0, "name": "GLV"}],
    )
    rerun = name_validation.validate_names(ring_renamed, ring_baseline)
    assert [(v["code"], v["soort"], v["changed"]) for v in rerun] == \
        [("TAKEN_NAME", "ring", True)]


def test_uniqueness_ring_name_may_not_collide_with_another_ring():
    vs_ring = make_state(rings=[{"id": 1, "name": "Ring"},
                                {"id": 2, "name": "Ring"}])
    assert [v["code"] for v in name_validation.validate_names(vs_ring)] == \
        ["TAKEN_NAME", "TAKEN_NAME"]


def test_uniqueness_collision_marks_only_the_changed_item():
    baseline = make_state(elements=[{"id": 0, "name": "een"},
                                    {"id": 1, "name": "twee"}])
    state = make_state(elements=[{"id": 0, "name": "twee"},
                                 {"id": 1, "name": "twee"}])
    violations = name_validation.validate_names(state, baseline)
    assert [(v["id"], v["changed"]) for v in violations] == [(0, True), (1, False)]
    assert [v for v in violations if v["changed"]] == [violations[0]]


@pytest.mark.parametrize("name", ["bae_1", "bae_1024", "open_1", "open_1024"])
def test_uniqueness_reserved_vendor_names_are_forbidden(name):
    violations = name_validation.validate_names(make_state(elements=[{"id": 0, "name": name}]))
    assert [v["code"] for v in violations] == ["RESERVED_NAME"]


@pytest.mark.parametrize("name", ["bae_0", "bae_1025", "BAE_1", "Open_1"])
def test_reserved_names_are_case_sensitive_and_bounded(name):
    assert name_validation.validate_names(make_state(elements=[{"id": 0, "name": name}])) == []


def test_empty_name_is_only_hard_for_stored_elements():
    new_element = make_state(elements=[{"id": None, "name": ""}])
    assert name_validation.validate_names(new_element) == []

    existing = make_state(elements=[{"id": 0, "name": "  "}])
    violations = name_validation.validate_names(existing)
    assert [v["code"] for v in violations] == ["EMPTY"]
    assert violations[0]["changed"] is True

    baseline = make_state(elements=[{"id": 0, "name": ""}])
    unchanged = name_validation.validate_names(baseline, baseline)
    assert [v["code"] for v in unchanged] == ["EMPTY"]
    assert unchanged[0]["changed"] is False


def test_changed_flag_follows_baseline():
    baseline = make_state(elements=[{"id": 0, "name": "oud"},
                                    {"id": 1, "name": "blijft"}])
    state = make_state(elements=[{"id": 0, "name": "a b"},
                                 {"id": 1, "name": "blijft"}])
    violations = name_validation.validate_names(state, baseline)
    assert [(v["id"], v["changed"]) for v in violations] == [(0, True)]


# -------------------------------------------------------------------- API

def test_save_rejected_changed_invalid_name_with_machine_readable_400(opened, tmp_path):
    client, sid, state = opened
    before = sha256(SAMPLE_FILE)
    state["elements"][0]["name"] = "brand weer"

    response = save(client, sid, state)
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert detail["error"] == "invalid_names"
    first = detail["violations"][0]
    for key in ("code", "soort", "id", "veld", "waarde", "teken"):
        assert key in first, key
    assert first["code"] == "INVALID_CHAR"
    assert first["teken"] == " "
    assert first["soort"] == "element"

    # niets geschreven, geen download en de bron byte-identiek
    session = editor.SESSIONS.get(sid)
    assert session["output"] is None
    assert not [n for n in os.listdir(session["dir"]) if n.endswith(".rbtproject")]
    assert client.get("/api/projects/%s/download" % sid).status_code == 400
    assert sha256(SAMPLE_FILE) == before


def test_save_rejected_duplicate_changed_name(opened, tmp_path):
    client, sid, state = opened
    state["elements"][1]["name"] = state["elements"][0]["name"]

    response = save(client, sid, state)
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert detail["error"] == "invalid_names"
    assert detail["violations"][0]["code"] == "TAKEN_NAME"
    assert editor.SESSIONS.get(sid)["output"] is None


def test_existing_invalid_name_saves_with_warning(client, tmp_path):
    # Bouw een echt projectbestand met een ongeldige naam erin, zodat de
    # overtreding in de baseline staat en niet door de gebruiker is gewijzigd.
    target = tmp_path / "met-spatie.rbtproject"
    model_service.apply_operations(
        SAMPLE_FILE, [{"op": "rename", "id": 0, "name": "brand weer"}], str(target))
    data = target.read_bytes()

    body = client.post("/api/projects/open", content=data, headers={
        "content-type": "application/octet-stream", "x-filename": "met-spatie.rbtproject",
    })
    assert body.status_code == 200, body.text
    opened_body = body.json()
    sid, state = opened_body["sid"], opened_body["state"]
    assert state["elements"][0]["name"] == "brand weer"
    assert any(w.get("code") == "INVALID_CHAR" for w in opened_body["warnings"])

    response = save(client, sid, state)
    assert response.status_code == 200, response.text
    warnings = [w for w in response.json()["warnings"]
                if w["kind"] == "invalid_name_existing"]
    assert warnings and warnings[0]["code"] == "INVALID_CHAR"
    assert warnings[0]["soort"] == "element"
    assert editor.SESSIONS.get(sid)["output"] is not None


def test_open_response_carries_name_rules_for_the_ui(opened):
    client, sid, _state = opened
    rules = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()["name_rules"]
    assert rules["element_forbidden"]
    assert " " in rules["element_forbidden"]
    assert " " not in rules["zone_forbidden"]
    assert rules["reserved_names"]["prefixes"] == ["bae_", "open_"]
    assert rules["reserved_names"]["max"] == 1024
    assert rules["space_allowed_in_zones"] is True
    assert "{teken}" in rules["messages"]["INVALID_CHAR"]
    assert "{waarde}" in rules["messages"]["TAKEN_NAME"]

    with open(os.path.join(WEB, "static", "app.js"), encoding="utf-8") as f:
        js = f.read()
    assert "naamfout" in js
    assert "invalid-name" in js
    with open(os.path.join(WEB, "static", "style.css"), encoding="utf-8") as f:
        css = f.read()
    assert ".invalid-name" in css
    assert ".name-error" in css


def test_ui_name_check_filename_is_served_by_the_root_page():
    with open(os.path.join(WEB, "static", "index.html"), encoding="utf-8") as f:
        html = f.read()
    assert "/static/name_check.js" in html
    with open(os.path.join(WEB, "static", "style.css"), encoding="utf-8") as f:
        css = f.read()
    assert ".name-warning" in css


def test_ui_client_check_blocks_only_changed_names(tmp_path):
    """De client-poort mag een bestaande ongeldige naam niet blokkeren."""
    script = """
const check = require(%s);
const rules = {
  element_forbidden: [" "],
  zone_forbidden: [],
  reserved_names: {prefixes: ["bae_", "open_"], max: 1024},
  messages: {
    EMPTY: "Naam mag niet leeg zijn",
    INVALID_CHAR: "Naam bevat het verboden teken '{teken}'",
    TAKEN_NAME: "Naam '{waarde}' bestaat al",
    RESERVED_NAME: "Naam '{waarde}' is gereserveerd door de vendor",
  },
};
const item = {id: 0, name: "brand weer"};
const baseline = {elements: [{id: 0, name: "brand weer"}], zones: [], rings: []};
const untouched = check.collect({elements: [item], zones: [], rings: [], alarms: []},
                                rules, baseline);
const changed = check.collect({elements: [{id: 0, name: "brand weer"}], zones: [],
                               rings: [], alarms: []}, rules, {elements: [], zones: [], rings: []});
console.log(JSON.stringify({
  untouched: untouched,
  changed: changed,
  blockingUntouched: untouched.filter((e) => e.changed).length,
  blockingChanged: changed.filter((e) => e.changed).length,
}));
""" % json.dumps(os.path.join(WEB, "static", "name_check.js"))
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert len(data["untouched"]) == 1
    assert data["untouched"][0]["code"] == "INVALID_CHAR"
    assert data["untouched"][0]["teken"] == " "
    assert data["untouched"][0]["changed"] is False
    assert data["blockingUntouched"] == 0
    assert data["blockingChanged"] == 1


def test_model_service_reexports_the_validator():
    assert model_service.validate_names is name_validation.validate_names
    assert model_service.NAME_RULES["messages"]["RESERVED_NAME"]


def test_valid_sample_states_have_no_name_violations():
    for name in ("Duizendpoot", "Levensvreugde"):
        path = os.path.join(ROOT, "samples", name, name + ".rbtproject")
        dump = model_service.read_project(path)
        assert name_validation.validate_names(dump, dump) == [], name
