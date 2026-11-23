"""Tests voor alarmen en de controlematrix: dump, apply, invarianten en web."""
import copy
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
WEB = os.path.join(APP, "web")
for path in (APP, WEB, os.path.dirname(os.path.abspath(__file__))):
    if path not in sys.path:
        sys.path.insert(0, path)

import editor  # noqa: E402
import model_service  # noqa: E402
import server  # noqa: E402
from alarm_fixture import build_alarm_project  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ALARMS = ("alarm_rook", "alarm_brand")


@pytest.fixture(scope="session")
def alarm_source(tmp_path_factory):
    """Eenmalig gegenereerd project met 2 alarmen en 3 elementen."""
    directory = tmp_path_factory.mktemp("alarm-fixture")
    return build_alarm_project(directory)


@pytest.fixture()
def alarm_file(alarm_source, tmp_path):
    target = tmp_path / "alarms.rbtproject"
    target.write_bytes(open(alarm_source, "rb").read())
    return target


@pytest.fixture()
def client():
    return TestClient(server.app)


def dump(path):
    return model_service.read_project(str(path))


def run_ops(src, ops, out):
    model_service.apply_operations(str(src), ops, str(out))
    return dump(out)


def open_fixture(client, path):
    with open(path, "rb") as f:
        data = f.read()
    response = client.post("/api/projects/open", content=data, headers={
        "content-type": "application/octet-stream",
        "x-filename": "alarmen.rbtproject",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    return body["sid"], body["state"]


def save(client, sid, state):
    return client.post("/api/projects/%s/save" % sid, json=state)


def download(client, sid, tmp_path):
    response = client.get("/api/projects/%s/download" % sid)
    assert response.status_code == 200, response.text
    target = tmp_path / "alarmen-uit.rbtproject"
    target.write_bytes(response.content)
    return dump(target)


def matrix_cells(element):
    return [(cell["alarmId"], cell["waarde"]) for cell in element["controlMatrix"]]


# ------------------------------------------------------------------- dump

def test_dump_alarm_shape(alarm_file):
    data = dump(alarm_file)
    assert len(data["alarms"]) == 2, data["alarms"]
    for index, alarm in enumerate(data["alarms"]):
        assert alarm["id"] == index
        assert alarm["name"] == ALARMS[index]
        assert alarm["description"] in ("rookmelding", "brandmelding")
        assert alarm["ringId"] == data["rings"][0]["id"]


def test_dump_control_matrix_is_per_alarm(alarm_file):
    data = dump(alarm_file)
    assert len(data["elements"]) == 3
    for element in data["elements"]:
        assert len(element["controlMatrix"]) == len(data["alarms"])
        assert [cell["alarmId"] for cell in element["controlMatrix"]] == [0, 1]
        assert all(cell["waarde"] == -1 for cell in element["controlMatrix"])
        # bestaande velden blijven aanwezig
        for key in ("id", "name", "ringId", "unit", "address", "zones"):
            assert key in element


# ------------------------------------------------------------------ apply

def test_alarm_rename_and_description(alarm_file, tmp_path):
    out = tmp_path / "alarm-rename.rbtproject"
    data = run_ops(alarm_file, [
        {"op": "alarm_rename", "alarm_id": 0, "name": "alarm_rook_2"},
        {"op": "alarm_desc", "alarm_id": 1, "description": "nieuwe omschrijving"},
    ], out)
    assert [a["name"] for a in data["alarms"]] == ["alarm_rook_2", ALARMS[1]]
    assert [a["description"] for a in data["alarms"]] == ["rookmelding", "nieuwe omschrijving"]
    # de matrixkoppeling blijft per alarm-object intact
    for element in data["elements"]:
        assert [cell["alarmId"] for cell in element["controlMatrix"]] == [0, 1]


def test_matrix_change_is_isolated(alarm_file, tmp_path):
    """Een wijziging bij alarm 2 van element 1 raakt geen andere cel."""
    out = tmp_path / "matrix-iso.rbtproject"
    data = run_ops(alarm_file, [
        {"op": "alarm_value", "element_id": 1, "alarm_id": 1, "value": 5},
    ], out)

    assert matrix_cells(data["elements"][1]) == [(0, -1), (1, 5)]
    assert matrix_cells(data["elements"][0]) == [(0, -1), (1, -1)]
    assert matrix_cells(data["elements"][2]) == [(0, -1), (1, -1)]
    # lengte-invariant: één cel per alarm, in alarmvolgorde
    for element in data["elements"]:
        assert len(element["controlMatrix"]) == len(data["alarms"])
        assert [cell["alarmId"] for cell in element["controlMatrix"]] == [0, 1]


def test_alarm_value_can_reset_to_minus_one(alarm_file, tmp_path):
    step1 = tmp_path / "step1.rbtproject"
    run_ops(alarm_file, [
        {"op": "alarm_value", "element_id": 0, "alarm_id": 0, "value": 3},
    ], step1)
    step2 = tmp_path / "step2.rbtproject"
    data = run_ops(step1, [
        {"op": "alarm_value", "element_id": 0, "alarm_id": 0, "value": -1},
    ], step2)
    assert matrix_cells(data["elements"][0]) == [(0, -1), (1, -1)]


@pytest.mark.parametrize("op", [
    {"op": "alarm_value", "element_id": 0, "alarm_id": 9, "value": 1},
    {"op": "alarm_value", "element_id": 99, "alarm_id": 0, "value": 1},
    {"op": "alarm_value", "element_id": 0, "alarm_id": 0, "value": -2},
    {"op": "alarm_value", "element_id": 0, "alarm_id": 0, "value": "geen-getal"},
    {"op": "alarm_rename", "alarm_id": 9, "name": "x"},
    {"op": "alarm_rename", "alarm_id": 0, "name": "slecht\tnaam"},
    {"op": "alarm_desc", "alarm_id": 9, "description": "x"},
])
def test_alarm_ops_reject_bad_input(alarm_file, tmp_path, op):
    out = tmp_path / "bad.rbtproject"
    with pytest.raises((ValueError, RuntimeError)):
        model_service.apply_operations(str(alarm_file), [op], str(out))
    assert not out.exists()


# -------------------------------------------------------------------- web

def test_web_alarm_and_matrix_roundtrip(client, alarm_source, tmp_path):
    sid, state = open_fixture(client, alarm_source)
    state["alarms"][0]["name"] = "alarm_rook_web"
    state["alarms"][0]["description"] = "via de web"
    state["elements"][0]["controlMatrix"][1]["waarde"] = 4

    response = save(client, sid, state)
    assert response.status_code == 200, response.text
    result = download(client, sid, tmp_path)

    assert result["alarms"][0]["name"] == "alarm_rook_web"
    assert result["alarms"][0]["description"] == "via de web"
    assert matrix_cells(result["elements"][0]) == [(0, -1), (1, 4)]
    assert matrix_cells(result["elements"][1]) == [(0, -1), (1, -1)]
    assert [a["name"] for a in result["alarms"]] == ["alarm_rook_web", ALARMS[1]]

    # de save-response is dezelfde staat als het gedownloade bestand
    assert response.json()["state"] == result
    client.delete("/api/projects/%s" % sid)


def test_web_new_element_gets_matrix_in_pass_two(client, alarm_source, tmp_path):
    sid, state = open_fixture(client, alarm_source)
    ring_id = state["rings"][0]["id"]
    unit = max(e["unit"] for e in state["elements"]) + 1
    state["elements"].append({
        "id": None, "name": "matrix_nieuw", "ringId": ring_id, "unit": unit,
        "address": 1, "unitId": "010.020.030", "type": "di", "deviceType": "DIN2",
        "enabled": True, "invert": False, "normalOpen": True, "safe": None,
        "description": "", "alarmFunction": "AND", "zones": [],
        "controlMatrix": [{"alarmId": 0, "waarde": -1}, {"alarmId": 1, "waarde": 4}],
    })

    response = save(client, sid, state)
    assert response.status_code == 200, response.text
    result = download(client, sid, tmp_path)
    added = next(e for e in result["elements"] if e["name"] == "matrix_nieuw")
    assert matrix_cells(added) == [(0, -1), (1, 4)]
    assert len(added["controlMatrix"]) == len(result["alarms"])
    client.delete("/api/projects/%s" % sid)


@pytest.mark.parametrize("change", [
    lambda s: s["alarms"].append({"id": 2, "name": "alarm_extra",
                                  "description": "", "ringId": s["rings"][0]["id"]}),
    lambda s: s["alarms"].pop(),
    lambda s: s["alarms"][0].update({"id": 5}),
    lambda s: s["elements"][0]["controlMatrix"].append({"alarmId": 2, "waarde": 0}),
    lambda s: s["elements"][0]["controlMatrix"].pop(),
    lambda s: s["elements"][0]["controlMatrix"][0].update({"alarmId": 5}),
    lambda s: s["elements"][0]["controlMatrix"][0].update({"waarde": -2}),
])
def test_web_rejects_alarm_count_matrix_length_and_values(client, alarm_source, change):
    sid, state = open_fixture(client, alarm_source)
    change(state)
    response = save(client, sid, state)
    assert response.status_code == 400, response.text
    assert response.json()["detail"]
    assert editor.SESSIONS.get(sid)["output"] is None
    client.delete("/api/projects/%s" % sid)


def test_web_alarm_names_follow_vendor_rules(client, alarm_source):
    sid, state = open_fixture(client, alarm_source)

    bad = copy.deepcopy(state)
    bad["alarms"][0]["name"] = "alarm rook"
    response = save(client, sid, bad)
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error"] == "invalid_names"
    assert detail["violations"][0]["soort"] == "alarm"

    duplicate = copy.deepcopy(state)
    duplicate["alarms"][0]["name"] = duplicate["elements"][0]["name"]
    response = save(client, sid, duplicate)
    assert response.status_code == 400
    assert response.json()["detail"]["violations"][0]["code"] == "TAKEN_NAME"
    client.delete("/api/projects/%s" % sid)


def test_web_existing_alarm_names_save_without_changes(client, alarm_source):
    sid, state = open_fixture(client, alarm_source)
    response = save(client, sid, state)
    assert response.status_code == 200, response.text
    saved = response.json()["state"]
    assert [a["name"] for a in saved["alarms"]] == list(ALARMS)
    client.delete("/api/projects/%s" % sid)


# ------------------------------------------------------------------- UI

def test_ui_has_alarm_and_matrix_panels():
    with open(os.path.join(WEB, "static", "index.html"), encoding="utf-8") as f:
        html = f.read()
    assert "<h2>Alarmen</h2>" in html
    assert "<h2>Controlematrix</h2>" in html
    assert 'id="alarms-body"' in html
    assert 'id="matrix-body"' in html
    assert "Rij op -1" in html
    assert "kan niet in deze editor" in html

    with open(os.path.join(WEB, "static", "app.js"), encoding="utf-8") as f:
        js = f.read()
    assert "function renderAlarms" in js
    assert "function renderMatrix" in js
    assert "adoptServerState" in js
    assert "state.alarms = serverState.alarms" in js
    assert "alarm_value" not in js  # de client stuurt de staat, geen @-regels

    with open(os.path.join(WEB, "static", "name_check.js"), encoding="utf-8") as f:
        check = f.read()
    assert '"alarm"' in check and "alarmBase" in check

    with open(os.path.join(WEB, "static", "style.css"), encoding="utf-8") as f:
        css = f.read()
    assert ".matrix-table" in css and ".matrix-wrap" in css
