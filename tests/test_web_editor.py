"""Tests voor de ZENiX Ringbus Editor: API, foutpaden en de volledige round-trip."""
import hashlib
import json
import os
import shutil
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
import server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

SAMPLE = "Duizendpoot"
SAMPLE_PATH = "samples/%s/%s.rbtproject" % (SAMPLE, SAMPLE)
SAMPLE_FILE = os.path.join(ROOT, "samples", SAMPLE, SAMPLE + ".rbtproject")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


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


def download(client, sid, tmp_path, name="download.rbtproject"):
    response = client.get("/api/projects/%s/download" % sid)
    assert response.status_code == 200, response.text
    target = tmp_path / name
    target.write_bytes(response.content)
    return model_service.read_project(str(target))


def ring_id(state):
    return state["rings"][0]["id"]


def ring_elements(state, rid):
    return [e for e in state["elements"] if e["ringId"] == rid]


def element_by_id(state, element_id):
    return next(e for e in state["elements"] if e["id"] == element_id)


def free_unit(state):
    return max(e["unit"] for e in state["elements"]) + 1


# ------------------------------------------------------------------ statisch

def test_root_serves_editor_without_external_requests(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "ZENiX" in response.text
    for name in ("app.js", "style.css"):
        asset = client.get("/static/" + name)
        assert asset.status_code == 200, name

    static_dir = os.path.join(WEB, "static")
    for name in os.listdir(static_dir):
        with open(os.path.join(static_dir, name), encoding="utf-8") as f:
            assert "http" not in f.read().lower(), name


def test_server_script_has_cli_and_help():
    result = subprocess.run([sys.executable, os.path.join(WEB, "server.py"), "--help"],
                            capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    assert "--port" in result.stdout


# ------------------------------------------------------------------- openen

def test_open_via_samples_path(client):
    response = client.post("/api/projects/open", json={"path": SAMPLE_PATH})
    assert response.status_code == 200
    body = response.json()
    assert body["project"] == SAMPLE
    assert body["sid"]
    assert body["state"]["elements"]
    element = body["state"]["elements"][0]
    for key in ("id", "name", "ringId", "unit", "address", "unitId", "type",
                "deviceType", "enabled", "invert", "normalOpen", "safe",
                "description", "alarmFunction", "zones"):
        assert key in element
    assert body["state"]["rings"] and body["state"]["zones"]
    client.delete("/api/projects/%s" % body["sid"])


def test_open_via_upload(client):
    with open(SAMPLE_FILE, "rb") as f:
        data = f.read()
    response = client.post("/api/projects/open", content=data, headers={
        "content-type": "application/octet-stream",
        "x-filename": "upload.rbtproject",
    })
    assert response.status_code == 200
    assert response.json()["project"] == SAMPLE
    client.delete("/api/projects/%s" % response.json()["sid"])


def test_open_via_multipart_upload_if_available(client):
    pytest.importorskip("multipart")
    with open(SAMPLE_FILE, "rb") as f:
        data = f.read()
    response = client.post("/api/projects/open", files={
        "file": ("mijn project.rbtproject", data, "application/octet-stream")})
    assert response.status_code == 200
    assert response.json()["project"] == SAMPLE


def test_open_rejects_paths_outside_samples(client):
    for path in ("/etc/passwd", "samples/../README.md", "app/core.py", "", None):
        response = client.post("/api/projects/open", json={"path": path})
        assert response.status_code == 400, path
        assert "samples" in response.json()["detail"] or "pad" in response.json()["detail"]


def test_open_rejects_empty_upload(client):
    response = client.post("/api/projects/open", content=b"", headers={
        "content-type": "application/octet-stream", "x-filename": "leeg.rbtproject"})
    assert response.status_code == 400


# --------------------------------------------------------------- wijzigen

def test_field_change_only_on_save_and_source_untouched(client, tmp_path):
    before = sha256(SAMPLE_FILE)
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    target = state["elements"][0]
    state["elements"][0]["description"] = "aangepast via web"
    state["elements"][0]["unitId"] = "999.111.222"
    state["elements"][0]["alarmFunction"] = "OR"

    assert sha256(SAMPLE_FILE) == before
    response = save(client, sid, state)
    assert response.status_code == 200, response.text
    assert sha256(SAMPLE_FILE) == before

    result = download(client, sid, tmp_path)
    changed = result["elements"][0]
    assert changed["name"] == target["name"]
    assert changed["description"] == "aangepast via web"
    assert changed["unitId"] == "999.111.222"
    assert changed["alarmFunction"] == "OR"
    assert len(result["elements"]) == len(state["elements"])


def test_add_element_with_zones(client, tmp_path):
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    rid = ring_id(state)
    zone = state["zones"][0]
    unit = free_unit(state)
    state["elements"].append({
        "id": None, "name": "", "ringId": rid, "unit": unit, "address": 4,
        "unitId": "010.020.030", "type": "fire", "deviceType": "FIRE",
        "enabled": True, "invert": False, "normalOpen": True, "safe": None,
        "description": "nieuw", "alarmFunction": "AND", "zones": [zone["id"]],
    })

    response = save(client, sid, state)
    assert response.status_code == 200, response.text
    result = download(client, sid, tmp_path)

    added = next(e for e in result["elements"] if e["unitId"] == "010.020.030")
    assert added["name"] == "fire_%s_%d_4" % (state["rings"][0]["name"], unit)
    assert added["zones"] == [zone["id"]]
    assert added["description"] == "nieuw"
    assert added["enabled"] is True
    zone_after = next(z for z in result["zones"] if z["id"] == zone["id"])
    assert added["name"] in zone_after["elements"]
    assert len(result["elements"]) == len(state["elements"])


def test_add_element_into_new_zone(client, tmp_path):
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    rid = ring_id(state)
    state["zones"].append({"id": None, "name": "WebZone",
                           "description": "via web", "elements": []})
    state["elements"].append({
        "id": None, "name": "web_zone_element", "ringId": rid,
        "unit": free_unit(state), "address": 1, "unitId": "020.030.040",
        "type": "di", "deviceType": "DIN2", "enabled": True, "invert": False,
        "normalOpen": True, "safe": None, "description": "",
        "alarmFunction": "AND", "zones": ["WebZone"],
    })

    response = save(client, sid, state)
    assert response.status_code == 200, response.text
    result = download(client, sid, tmp_path)

    zone = next(z for z in result["zones"] if z["name"] == "WebZone")
    assert zone["description"] == "via web"
    assert zone["id"] == max(z["id"] for z in state["zones"] if z["id"] is not None) + 1
    added = next(e for e in result["elements"] if e["name"] == "web_zone_element")
    assert added["zones"] == [zone["id"]]


def test_add_fio_element_keeps_vendor_safe_default(client, tmp_path):
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    state["elements"].append({
        "id": None, "name": "", "ringId": ring_id(state), "unit": free_unit(state),
        "address": 2, "unitId": "001.002.003", "type": "do", "deviceType": "FIO_8_8",
        "enabled": True, "invert": False, "normalOpen": True, "safe": None,
        "description": "", "alarmFunction": "AND", "zones": [],
    })

    response = save(client, sid, state)
    assert response.status_code == 200, response.text
    result = download(client, sid, tmp_path)
    added = next(e for e in result["elements"] if e["unitId"] == "001.002.003")
    # @add zet 'safe' op 'stay' voor FIO; de editor mag dat niet leegmaken
    assert added["safe"] == "stay"
    assert added["safeRaw"] == "stay"


def test_delete_single_and_multiple(client, tmp_path):
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    first = state["elements"][0]
    second = state["elements"][1]
    third = state["elements"][2]
    dropped = [first, second, third]
    state["elements"] = state["elements"][3:]

    response = save(client, sid, state)
    assert response.status_code == 200, response.text
    result = download(client, sid, tmp_path)

    names = [e["name"] for e in result["elements"]]
    for element in dropped:
        assert element["name"] not in names
    assert len(result["elements"]) == len(state["elements"])
    for zone in result["zones"]:
        for element in dropped:
            assert element["name"] not in zone["elements"]


def test_order_drag_and_drop_per_ring(client, tmp_path):
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    rid = ring_id(state)
    elements = ring_elements(state, rid)
    assert len(elements) > 3
    wanted = list(reversed(elements))
    rest = [e for e in state["elements"] if e["ringId"] != rid]
    state["elements"] = wanted + rest

    response = save(client, sid, state)
    assert response.status_code == 200, response.text
    result = download(client, sid, tmp_path)

    assert [e["name"] for e in ring_elements(result, rid)] == [e["name"] for e in wanted]
    assert [e["indexInRing"] for e in ring_elements(result, rid)] == \
        list(range(1, len(wanted) + 1))


def test_bulk_rename_payload(client, tmp_path):
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    chosen = state["elements"][:3]
    for index, element in enumerate(chosen):
        element["name"] = "bulk_%d_%s" % (index, (element["name"] or "x").replace("fire", "rook"))

    response = save(client, sid, state)
    assert response.status_code == 200, response.text
    result = download(client, sid, tmp_path)
    assert [e["name"] for e in result["elements"][:3]] == \
        [e["name"] for e in chosen]


# ------------------------------------------------------------------ fouten

@pytest.mark.parametrize("bad_name", ["", "   ", "x\ty", "x\ny", "x\ry"])
def test_save_rejects_bad_names(client, bad_name):
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    state["elements"][0]["name"] = bad_name
    response = save(client, sid, state)
    assert response.status_code == 400
    assert response.json()["detail"]


def test_save_rejects_unknown_element_and_zone(client):
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]

    ghost = json.loads(json.dumps(state))
    ghost["elements"][0]["id"] = 999999
    response = save(client, sid, ghost)
    assert response.status_code == 400

    bad_zone = json.loads(json.dumps(state))
    bad_zone["elements"][0]["zones"] = ["BestaatNiet"]
    response = save(client, sid, bad_zone)
    assert response.status_code == 400
    assert "zone" in response.json()["detail"].lower()

    bad_ring = json.loads(json.dumps(state))
    bad_ring["elements"][0]["ringId"] = 424242
    response = save(client, sid, bad_ring)
    assert response.status_code == 400


def test_save_rejects_duplicate_new_zone_name(client):
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    state["zones"].append({"id": None, "name": state["zones"][0]["name"],
                           "description": "", "elements": []})
    response = save(client, sid, state)
    assert response.status_code == 400
    assert "zone" in response.json()["detail"].lower()


def test_unknown_session_gives_404(client):
    state = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()["state"]
    assert client.post("/api/projects/doesnotexist/save", json=state).status_code == 404
    assert client.get("/api/projects/doesnotexist/download").status_code == 404
    assert client.delete("/api/projects/doesnotexist").status_code == 404


def test_download_before_save_is_400(client):
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    response = client.get("/api/projects/%s/download" % body["sid"])
    assert response.status_code == 400
    assert "opgeslagen" in response.json()["detail"]


def test_close_session_removes_tempdir(client):
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid = body["sid"]
    directory = editor.SESSIONS.get(sid)["dir"]
    assert os.path.isdir(directory)
    assert client.delete("/api/projects/%s" % sid).status_code == 200
    assert not os.path.exists(directory)
    assert client.delete("/api/projects/%s" % sid).status_code == 404


# -------------------------------------------------------------- round-trip

def test_full_roundtrip(client, tmp_path):
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    rid = ring_id(state)
    zone = state["zones"][0]
    ring_name = state["rings"][0]["name"]
    n = len(state["elements"])

    renamed = state["elements"][0]
    renamed["name"] = "rt_renamed_1"
    changed = state["elements"][1]
    changed["description"] = "rt_desc"
    changed["alarmFunction"] = "OR"
    deleted = state["elements"][2]
    state["elements"] = [e for e in state["elements"] if e is not deleted]

    unit = free_unit(state)
    state["elements"].append({
        "id": None, "name": "", "ringId": rid, "unit": unit, "address": 1,
        "unitId": "010.000.009", "type": "fire", "deviceType": "FIRE",
        "enabled": True, "invert": False, "normalOpen": True, "safe": None,
        "description": "", "alarmFunction": "AND", "zones": [zone["id"]],
    })
    new_name = "fire_%s_%d_1" % (ring_name, unit)

    elements = ring_elements(state, rid)
    wanted = list(reversed(elements))
    state["elements"] = [e for e in wanted if e["ringId"] == rid] + \
        [e for e in state["elements"] if e["ringId"] != rid]

    expected = {}
    for element in state["elements"]:
        name = new_name if element["id"] is None else element["name"]
        expected.setdefault(element["ringId"], []).append(name)

    response = save(client, sid, state)
    assert response.status_code == 200, response.text
    result = download(client, sid, tmp_path)

    assert len(result["elements"]) == n
    for rid_expected, names in expected.items():
        actual = ring_elements(result, rid_expected)
        assert [e["name"] for e in actual] == names
        assert [e["indexInRing"] for e in actual] == list(range(1, len(names) + 1))
    actual_names = [e["name"] for e in result["elements"]]
    assert deleted["name"] not in actual_names
    assert [e["id"] for e in result["elements"]] == list(range(n))

    saved_changed = next(e for e in result["elements"] if e["name"] == changed["name"])
    assert saved_changed["description"] == "rt_desc"
    assert saved_changed["alarmFunction"] == "OR"

    added = next(e for e in result["elements"] if e["name"] == new_name)
    assert added["zones"] == [zone["id"]]
    zone_after = next(z for z in result["zones"] if z["id"] == zone["id"])
    assert new_name in zone_after["elements"]
    assert deleted["name"] not in zone_after["elements"]

    # opnieuw openen van het gedownloade bestand levert hetzelfde beeld
    again = model_service.read_project(str(tmp_path / "download.rbtproject"))
    for rid_expected, names in expected.items():
        assert [e["name"] for e in ring_elements(again, rid_expected)] == names


def test_save_roundtrip_state_reads_back_file(client, tmp_path):
    """De save-response bevat de staat zoals die uit het geschreven bestand is gelezen."""
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    rid = ring_id(state)
    unit = free_unit(state)
    state["elements"].append({
        "id": None, "name": "", "ringId": rid, "unit": unit, "address": 5,
        "unitId": "010.020.050", "type": "fire", "deviceType": "FIRE",
        "enabled": True, "invert": False, "normalOpen": True, "safe": None,
        "description": "", "alarmFunction": "AND", "zones": [],
    })

    response = save(client, sid, state)
    assert response.status_code == 200, response.text
    saved = response.json()

    for key in ("project", "rings", "zones", "alarms", "elements"):
        assert key in saved["state"], key

    added = next(e for e in saved["state"]["elements"] if e["unitId"] == "010.020.050")
    assert added["name"]
    assert isinstance(added["id"], int)
    assert added["name"] != ""
    kinds = [w["kind"] for w in saved["warnings"]]
    assert "empty_name" not in kinds
    assert all(e["name"] for e in saved["state"]["elements"])

    # exact dezelfde dump als het gedownloade bestand
    downloaded = download(client, sid, tmp_path)
    assert saved["state"] == downloaded


def test_second_save_without_changes_reports_no_change(client, tmp_path):
    """Na de rebase is een tweede, ongewijzigde save geen wijziging meer."""
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    state["elements"].append({
        "id": None, "name": "", "ringId": ring_id(state), "unit": free_unit(state),
        "address": 6, "unitId": "010.020.060", "type": "fire", "deviceType": "FIRE",
        "enabled": True, "invert": False, "normalOpen": True, "safe": None,
        "description": "", "alarmFunction": "AND", "zones": [],
    })

    first = save(client, sid, state)
    assert first.status_code == 200, first.text
    assert first.json()["changed"] is True
    reread = first.json()["state"]

    second = save(client, sid, reread)
    assert second.status_code == 200, second.text
    assert second.json()["changed"] is False
    assert second.json()["state"] == reread
    assert download(client, sid, tmp_path) == reread


def test_save_response_zone_gets_real_id(client):
    """Een nieuwe zone komt met een echte id terug in de response-state."""
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    state["zones"].append({"id": None, "name": "ResponsZone",
                           "description": "via web", "elements": []})

    response = save(client, sid, state)
    assert response.status_code == 200, response.text
    saved = response.json()
    zone = next(z for z in saved["state"]["zones"] if z["name"] == "ResponsZone")
    assert isinstance(zone["id"], int)
    assert zone["description"] == "via web"


def test_save_single_read_of_written_file(client, monkeypatch):
    """Eén leesactie per save: de response-state komt uit één decrypt+parse."""
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    state["elements"][0]["description"] = "een keer lezen"
    session = editor.SESSIONS.get(sid)
    out = os.path.abspath(os.path.join(session["dir"], editor.output_name(state, state)))

    calls = []
    real_open = editor.core.open_project

    def counting_open(path):
        calls.append(os.path.abspath(str(path)))
        return real_open(path)

    monkeypatch.setattr(editor.core, "open_project", counting_open)
    response = save(client, sid, state)
    assert response.status_code == 200, response.text
    assert calls.count(out) == 1


def test_save_keeps_session_key(client, tmp_path):
    """De rebase laat de sessiesleutel staan; blob en sleutel blijven bij elkaar."""
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    key_before = editor.SESSIONS.get(sid)["key"]

    state["elements"][0]["description"] = "sleutel blijft"
    response = save(client, sid, state)
    assert response.status_code == 200, response.text

    session = editor.SESSIONS.get(sid)
    assert session["key"] == key_before
    assert session["blob"][:2] == b"PK"
    with open(session["output"], "rb") as f:
        written = f.read()
    plain = editor.core.AESGCM(key_before).decrypt(key_before, written, None)
    assert plain[:2] == b"PK"


def test_download_uses_rfc5987_filename(client):
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    state["project"] = "Zënix test"
    assert save(client, sid, state).status_code == 200
    response = client.get("/api/projects/%s/download" % sid)
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "filename*=UTF-8''" in disposition
    assert "Z%C3%ABnix%20test" in disposition
    assert response.content


# -------------------------------------------------------------- warnings

def test_warnings_flags_duplicate_names_addresses_and_empty():
    state = {
        "project": "Test",
        "rings": [{"id": 1, "name": "R1"}],
        "zones": [{"id": 1, "name": "Z1", "description": ""}],
        "elements": [
            {"id": 0, "name": "dubbel", "ringId": 1, "unit": 1, "address": 1, "zones": []},
            {"id": 1, "name": "dubbel", "ringId": 1, "unit": 1, "address": 1, "zones": []},
            {"id": 2, "name": "", "ringId": 1, "unit": 2, "address": 1, "zones": []},
        ],
    }
    kinds = [w["kind"] for w in editor.warnings(state)]
    assert "duplicate_name" in kinds
    assert "duplicate_address" in kinds
    assert "empty_name" in kinds


def test_duplicate_address_does_not_block_save(client, tmp_path):
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    # bewust een dubbel adres maken; de namen blijven verschillend
    state["elements"][1]["unit"] = state["elements"][0]["unit"]
    state["elements"][1]["address"] = state["elements"][0]["address"]

    assert any(w["kind"] == "duplicate_address" for w in editor.warnings(state))
    response = save(client, sid, state)
    assert response.status_code == 200, response.text
    result = download(client, sid, tmp_path)
    assert result["elements"][1]["unit"] == result["elements"][0]["unit"]
    assert result["elements"][1]["address"] == result["elements"][0]["address"]


def test_duplicate_name_now_blocks_save(client):
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    state["elements"][1]["name"] = state["elements"][0]["name"]

    response = save(client, sid, state)
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert detail["error"] == "invalid_names"
    assert detail["violations"][0]["code"] == "TAKEN_NAME"
    assert editor.SESSIONS.get(sid)["output"] is None


# ------------------------------------------------------------------- ringen

def test_ring_rename_roundtrip(client, tmp_path):
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    rid = ring_id(state)
    state["rings"][0]["name"] = "Aangepaste ring"

    response = save(client, sid, state)
    assert response.status_code == 200, response.text
    saved = download(client, sid, tmp_path)
    ring = next(r for r in saved["rings"] if r["id"] == rid)
    assert ring["name"] == "Aangepaste ring"
    # de response-state komt uit hetzelfde bestand
    assert next(r for r in response.json()["state"]["rings"]
                if r["id"] == rid)["name"] == "Aangepaste ring"


def test_ring_host_roundtrip(client, tmp_path):
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    rid = ring_id(state)
    state["rings"][0]["host"] = "10.0.0.9"

    response = save(client, sid, state)
    assert response.status_code == 200, response.text
    saved = download(client, sid, tmp_path)
    assert next(r for r in saved["rings"] if r["id"] == rid)["host"] == "10.0.0.9"


def test_ring_host_may_not_be_cleared(client):
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    assert state["rings"][0]["host"]
    state["rings"][0]["host"] = ""

    response = save(client, sid, state)
    assert response.status_code == 400, response.text
    assert editor.EMPTY_HOST_MESSAGE in response.json()["detail"]


EMPTY_HOST_JAVA = """
import com.euroicc.ringbus.config.*;
import java.io.*;
public class EmptyHost {
  public static void main(String[] a) throws Exception {
    Configuration c = Configuration.load(new File(a[0]));
    c.getRings().get(0).setHost("");
    if (!c.saveAs(new File(a[0]))) throw new IllegalStateException("save");
  }
}
"""


def build_empty_host_project(tmp_path):
    """Bouw een project waarvan de eerste ring een lege host heeft (vendor-API)."""
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("javac/java ontbreken; de fixture-generator heeft een JDK nodig")
    assert javac is not None and java is not None
    classpath = os.pathsep.join([
        os.path.join(APP, "lib", "configuration-1.4.1.jar"),
        os.path.join(APP, "lib", "jaxb-api.jar"),
    ])
    source = tmp_path / "EmptyHost.java"
    source.write_text(EMPTY_HOST_JAVA, encoding="utf-8")
    classes = tmp_path / "empty-host-classes"
    classes.mkdir()
    compiled = subprocess.run(
        [javac, "--release", "17", "-cp", classpath, "-d", str(classes), str(source)],
        capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stderr

    key, blob, _data = editor.core.open_project(SAMPLE_FILE)
    work = tmp_path / "empty-host-work"
    editor.core._unzip(blob, str(work))
    run = subprocess.run(
        [java, "-cp", os.pathsep.join([str(classes), classpath]), "EmptyHost",
         editor.core._find_cfg(str(work))],
        capture_output=True, text=True)
    assert run.returncode == 0, run.stderr or run.stdout
    out = tmp_path / "lege-host.rbtproject"
    out.write_bytes(editor.core.AESGCM(key).encrypt(
        key, editor.core._rezip(str(work)), None))
    return out


def test_save_with_empty_baseline_host_does_not_fail_verification(client, tmp_path):
    """Een ongemoeide ring met lege host mag de save-verificatie niet blokkeren."""
    fixture = build_empty_host_project(tmp_path)
    body = client.post("/api/projects/open", content=fixture.read_bytes(), headers={
        "content-type": "application/octet-stream",
        "x-filename": "lege-host.rbtproject",
    })
    assert body.status_code == 200, body.text
    opened = body.json()
    sid, state = opened["sid"], opened["state"]
    assert state["rings"][0]["host"] == ""

    state["elements"][0]["description"] = "ander veld"
    response = save(client, sid, state)
    assert response.status_code == 200, response.text
    assert "Host van ring" not in response.text


def test_verify_compares_host_only_for_changed_rings():
    baseline = {"project": "P", "rings": [{"id": 1, "name": "R", "host": ""}],
                "zones": [], "elements": []}
    plan = editor._ring_plan(baseline, baseline)
    assert plan["expected"][0]["changed"] is False

    result = {"rings": [{"id": 1, "name": "R", "host": "localhost"}],
              "zones": [], "elements": []}
    zoned = {"ids_by_index": {}, "names": {}, "ids": set()}
    editor._verify(baseline, result, zoned, plan)

    changed = {"project": "P", "rings": [{"id": 1, "name": "R", "host": "10.0.0.5"}],
               "zones": [], "elements": []}
    plan2 = editor._ring_plan(baseline, changed)
    assert plan2["expected"][0]["changed"] is True
    assert plan2["expected"][0]["host_changed"] is True
    with pytest.raises(editor.EditorError) as excinfo:
        editor._verify(changed, result, zoned, plan2)
    assert "Host van ring" in str(excinfo.value)


def test_verify_skips_host_for_rename_only() -> None:
    """Een pure hernoeming wijzigt de host niet en mag niet op host falen."""
    baseline = {"project": "P", "rings": [{"id": 1, "name": "R", "host": ""}],
                "zones": [], "elements": []}
    renamed = {"project": "P", "rings": [{"id": 1, "name": "R2", "host": ""}],
               "zones": [], "elements": []}
    plan = editor._ring_plan(baseline, renamed)
    assert plan["expected"][0]["changed"] is True
    assert plan["expected"][0]["host_changed"] is False

    result = {"rings": [{"id": 1, "name": "R2", "host": "localhost"}],
              "zones": [], "elements": []}
    zoned = {"ids_by_index": {}, "names": {}, "ids": set()}
    editor._verify(renamed, result, zoned, plan)


def test_empty_host_message_is_shared() -> None:
    """De editor en de service gebruiken exact dezelfde melding."""
    assert editor.EMPTY_HOST_MESSAGE == model_service.EMPTY_HOST_MESSAGE


def test_ring_rename_with_empty_baseline_host_is_accepted(client, tmp_path):
    """Hernoemen van een ring met lege baseline-host mag niet op host falen."""
    fixture = build_empty_host_project(tmp_path)
    body = client.post("/api/projects/open", content=fixture.read_bytes(), headers={
        "content-type": "application/octet-stream",
        "x-filename": "lege-host.rbtproject",
    })
    assert body.status_code == 200, body.text
    opened = body.json()
    sid, state = opened["sid"], opened["state"]
    assert state["rings"][0]["host"] == ""
    state["rings"][0]["name"] = "Hernoemd"

    response = save(client, sid, state)
    assert response.status_code == 200, response.text
    assert "Host van ring" not in response.text


def test_ring_rename_does_not_touch_element_names(client, tmp_path):
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    names_before = [e["name"] for e in state["elements"]]
    state["rings"][0]["name"] = "Hernoemd"

    assert save(client, sid, state).status_code == 200
    saved = download(client, sid, tmp_path)
    assert [e["name"] for e in saved["elements"]] == names_before


def test_ring_add_roundtrip(client, tmp_path):
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    base = state["rings"][0]
    state["rings"].append({"id": None, "name": "Ring2", "host": "10.0.0.42"})

    response = save(client, sid, state)
    assert response.status_code == 200, response.text
    saved = download(client, sid, tmp_path)
    new = next(r for r in saved["rings"] if r["name"] == "Ring2")
    assert new["id"] == max(r["id"] for r in state["rings"] if r["id"] is not None) + 1
    assert new["host"] == "10.0.0.42"
    assert new["cpuType"] == 5
    assert new["bacnetInstanceId"] == base["bacnetInstanceId"] + 1000
    assert new["bacnetNetwork"] == base["bacnetNetwork"] + 1


@pytest.mark.parametrize("change", [
    lambda s: s["rings"][0].update({"id": 424242}),
    lambda s: s["rings"][0].update({"name": ""}),
    lambda s: s["rings"][0].update({"name": "   "}),
    lambda s: s["rings"][0].update({"name": "x\ty"}),
    lambda s: s["rings"].append({"id": None, "name": s["rings"][0]["name"]}),
    lambda s: s.update({"rings": []}),
])
def test_ring_save_rejects_bad_state(client, change):
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    change(state)
    response = save(client, sid, state)
    assert response.status_code == 400
    assert response.json()["detail"]


def test_ring_add_duplicate_of_new_ring_is_rejected(client):
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    state["rings"].append({"id": None, "name": "Ring2"})
    state["rings"].append({"id": None, "name": "Ring2"})
    response = save(client, sid, state)
    assert response.status_code == 400
    assert "ring" in response.json()["detail"].lower()


def test_ring_add_duplicate_name_is_case_insensitive(client):
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    existing = state["rings"][0]["name"]
    state["rings"].append({"id": None, "name": existing.upper()})
    response = save(client, sid, state)
    assert response.status_code == 400
    assert "ring" in response.json()["detail"].lower()


def test_ring_name_key_is_shared_between_layers(client, tmp_path):
    """Editor en service vinden ``' Ring1 '`` en ``'ring1'`` dezelfde ringnaam.

    De editor delegeert zijn ringnaam-sleutel naar ``model_service._ring_key``;
    deze test legt vast dat beide lagen bij toevoegen én bij dubbeldetectie
    dezelfde naam als botsing zien.
    """
    assert model_service._ring_key(" Ring1 ") == model_service._ring_key("ring1")
    assert model_service._ring_key(" Ring1 ") == "ring1"

    base_name = model_service.read_project(SAMPLE_FILE)["rings"][0]["name"]
    assert base_name
    variant = "  %s  " % base_name.upper()

    # (a) service-laag: toevoegen van een bestaande naam met spaties/hoofdletters
    out = tmp_path / "shared-add.rbtproject"
    with pytest.raises(ValueError) as excinfo:
        model_service.apply_operations(
            str(SAMPLE_FILE),
            [{"op": "ring_add", "name": variant, "host": "10.0.0.7"}],
            str(out))
    assert "ring" in str(excinfo.value).lower()
    assert not out.exists()

    # (b) service-laag: dubbeldetectie binnen dezelfde lijst
    out = tmp_path / "shared-dup.rbtproject"
    with pytest.raises(ValueError) as excinfo:
        model_service.apply_operations(
            str(SAMPLE_FILE),
            [{"op": "ring_add", "name": " Ring2 ", "host": "10.0.0.8"},
             {"op": "ring_add", "name": "ring2", "host": "10.0.0.9"}],
            str(out))
    assert "ring" in str(excinfo.value).lower()
    assert not out.exists()

    # (c) editor-laag: toevoegen van een bestaande naam met spaties/hoofdletters
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    state["rings"].append({"id": None, "name": variant})
    response = save(client, sid, state)
    assert response.status_code == 400
    assert "ring" in response.json()["detail"].lower()

    # (d) editor-laag: dubbeldetectie binnen dezelfde lijst
    body = client.post("/api/projects/open", json={"path": SAMPLE_PATH}).json()
    sid, state = body["sid"], body["state"]
    state["rings"].append({"id": None, "name": " Ring2 "})
    state["rings"].append({"id": None, "name": "ring2"})
    response = save(client, sid, state)
    assert response.status_code == 400
    assert "ring" in response.json()["detail"].lower()


# ------------------------------------------------------------------- alarmen

@pytest.fixture(scope="module")
def alarm_project(tmp_path_factory):
    """Een project met twee alarmen via de vendor-fixture (JDK vereist)."""
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
    from alarm_fixture import build_alarm_project
    return build_alarm_project(tmp_path_factory.mktemp("alarm-fixture"))


def open_uploaded(client, path):
    with open(path, "rb") as f:
        data = f.read()
    response = client.post("/api/projects/open", content=data, headers={
        "content-type": "application/octet-stream",
        "x-filename": os.path.basename(str(path)),
    })
    assert response.status_code == 200, response.text
    body = response.json()
    return body["sid"], body["state"]


def test_alarm_save_with_unchanged_ring_is_accepted(client, alarm_project):
    sid, state = open_uploaded(client, alarm_project)
    assert state["alarms"] and all("ringId" in a for a in state["alarms"])

    response = save(client, sid, state)
    assert response.status_code == 200, response.text


def test_alarm_save_with_changed_ring_id_is_rejected(client, alarm_project):
    sid, state = open_uploaded(client, alarm_project)
    base_ring = state["alarms"][0]["ringId"]
    state["alarms"][0]["ringId"] = int(base_ring) + 991

    response = save(client, sid, state)
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert "ring" in detail.lower()
    assert editor.SESSIONS.get(sid)["output"] is None


# ------------------------------------------------------------- statische check

def _js_function_body(source, name):
    start = source.index("function " + name + "(")
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[brace:index + 1]
    raise AssertionError("functie %s niet afgesloten" % name)


def test_save_path_refreshes_history_buttons_once():
    path = os.path.join(WEB, "static", "app.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    save_body = _js_function_body(js, "save")
    adopt_body = _js_function_body(js, "adoptServerState")
    # adoptServerState() doet de ene verversing; save() zelf roept hem niet dubbel.
    assert save_body.count("updateHistoryButtons()") == 0
    assert adopt_body.count("updateHistoryButtons()") == 1
    assert save_body.count("adoptServerState(") == 1
