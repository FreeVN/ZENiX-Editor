"""Tests voor de model-laag: stabiele ids, add/del/rename/order/zonedel en round-trip."""
import hashlib
import os
import subprocess
import sys

import pytest

import core
import model_service

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
CLI = os.path.join(APP, "zenix_cli.py")


def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def dump(path):
    return model_service.read_project(str(path))


def run_ops(src, ops, out):
    info = model_service.apply_operations(str(src), ops, str(out))
    return info, dump(out)


def ring(data):
    return data["rings"][0]


def ring_elements(data):
    rid = ring(data)["id"]
    return [e for e in data["elements"] if e["ringId"] == rid]


def free_unit(data):
    units = [e["unit"] for e in data["elements"]]
    return (max(units) + 1) if units else 1


def field_values(element, keys):
    return {k: element[k] for k in keys}


def expected_indexes_per_ring(data):
    """indexInRing hoort per ring 1..n te zijn, in dumpvolgorde."""
    counters, out = {}, []
    for e in data["elements"]:
        counters[e["ringId"]] = counters.get(e["ringId"], 0) + 1
        out.append(counters[e["ringId"]])
    return out


def assert_indexes_per_ring(data):
    assert [e["indexInRing"] for e in data["elements"]] == expected_indexes_per_ring(data)


def apply_raw(src, edits, out):
    """Pas rauwe ``@``-regels toe (voor tests die de service-API niet dekt, bv. @ringadd)."""
    key, blob, _ = core.open_project(str(src))
    with open(str(out), "wb") as f:
        f.write(core.apply_edits(blob, key, edits))
    return out


# ---------------------------------------------------------------- dump / ids

def test_dump_has_stable_id_and_unitid(sample):
    data = dump(sample)
    ids = [e["id"] for e in data["elements"]]
    assert ids == list(range(len(data["elements"])))
    assert ids, "sample heeft geen elementen"
    for e in data["elements"]:
        assert isinstance(e["unitId"], str) and e["unitId"].strip(), e
        # bestaande velden blijven aanwezig
        for key in ("name", "ringId", "unit", "address", "addressOnUnit", "indexInRing",
                    "type", "deviceType", "alarmFunction", "safe", "safeRaw",
                    "controlMatrix", "zones"):
            assert key in e
    # indexInRing is per ring 1..n in dumpvolgorde
    counters = {}
    for e in data["elements"]:
        counters[e["ringId"]] = counters.get(e["ringId"], 0) + 1
        assert e["indexInRing"] == counters[e["ringId"]]


# ------------------------------------------------------------------- add

def test_add_fire_naming_and_defaults(sample, tmp_path):
    data = dump(sample)
    r = ring(data)
    unit = free_unit(data)
    out = tmp_path / "add-fire.rbtproject"
    _, res = run_ops(sample, [{
        "op": "add", "ring_id": r["id"], "unit": unit, "address": 1,
        "type": "fire", "device_type": "FIRE", "unit_id": "010.000.001",
    }], out)

    assert len(res["elements"]) == len(data["elements"]) + 1
    e = res["elements"][-1]
    assert e["name"] == "fire_%s_%d_1" % (r["name"], unit)
    assert (e["type"], e["typeName"]) == (1, "fire")
    assert (e["deviceType"], e["deviceTypeName"]) == (1, "FIRE")
    assert e["alarmFunction"] == "AND"
    # getSafe() verbergt de waarde buiten FIO; de vendor bewaart 'safe' bovendien
    # niet voor FIRE/DIO, dus na opslaan is safeRaw leeg. AC-4's 'safe: stay'
    # wordt bewezen via FIO-DO (test_add_fio_do_gets_safe_stay).
    assert e["safe"] is None
    assert e["safeRaw"] is None
    # één controlematrix-cel per bestaand alarm, telkens -1
    assert len(e["controlMatrix"]) == len(data["alarms"])
    assert all(cell["waarde"] == -1 for cell in e["controlMatrix"])
    assert [cell["alarmId"] for cell in e["controlMatrix"]] == \
        list(range(len(data["alarms"])))
    assert e["normalOpen"] is True
    assert e["invert"] is False
    assert e["unitId"] == "010.000.001"
    assert e["indexInRing"] == len(res["elements"])
    assert e["zones"] == []


def test_add_dio_zero_prefix(sample, tmp_path):
    data = dump(sample)
    r = ring(data)
    unit = free_unit(data) + 1
    out = tmp_path / "add-dio.rbtproject"
    _, res = run_ops(sample, [{
        "op": "add", "ring_id": r["id"], "unit": unit, "address": 2,
        "type": "di", "device_type": "DIN2", "unit_id": "003.003.003",
    }], out)

    e = res["elements"][-1]
    # DIO-deviceTypes krijgen een zero-padded unit in de vendor-naam
    assert e["name"] == "di_%s_%02d_2" % (r["name"], unit)
    assert (e["type"], e["typeName"]) == (3, "di")
    assert (e["deviceType"], e["deviceTypeName"]) == (23, "DIN2")
    assert e["addressOnUnit"] == 1
    assert len(e["controlMatrix"]) == len(res["alarms"])
    assert all(cell["waarde"] == -1 for cell in e["controlMatrix"])
    assert e["alarmFunction"] == "AND"


def test_add_address_on_unit_convention(sample, tmp_path):
    """addressOnUnit volgt de conventie die de bestaande elementen van dit sample tonen."""
    data = dump(sample)
    existing = [e for e in data["elements"] if e["address"] >= 1]
    assert existing, "sample heeft geen elementen met een adres"
    for e in existing:
        assert e["addressOnUnit"] == e["address"] - 1, e

    out = tmp_path / "aou.rbtproject"
    _, res = run_ops(sample, [{
        "op": "add", "ring_id": ring(data)["id"], "unit": free_unit(data), "address": 3,
        "type": "di", "device_type": "DIN2", "unit_id": "003.003.009",
    }], out)
    e = res["elements"][-1]
    assert (e["address"], e["addressOnUnit"]) == (3, 2)
    # dezelfde relatie als de bestaande elementen van hetzelfde deviceType
    same_kind = [x for x in data["elements"] if x["deviceType"] == e["deviceType"]]
    assert same_kind
    assert e["address"] - e["addressOnUnit"] == same_kind[0]["address"] - same_kind[0]["addressOnUnit"]

    bad = tmp_path / "aou-bad.rbtproject"
    with pytest.raises(RuntimeError) as excinfo:
        run_ops(sample, [{
            "op": "add", "ring_id": ring(data)["id"], "unit": free_unit(data), "address": 0,
            "type": "di", "device_type": "DIN2", "unit_id": "003.003.010",
        }], bad)
    assert "address" in str(excinfo.value)
    assert not bad.exists()


def test_add_fio_do_gets_safe_stay(sample, tmp_path):
    """Alleen FIO-DO geeft safe vrij in de dump; daar toetsen we de default echt."""
    data = dump(sample)
    r = ring(data)
    unit = free_unit(data) + 3
    out = tmp_path / "add-fio.rbtproject"
    _, res = run_ops(sample, [{
        "op": "add", "ring_id": r["id"], "unit": unit, "address": 1,
        "type": "do", "device_type": "FIO_8_8", "unit_id": "001.002.003",
    }], out)

    e = res["elements"][-1]
    assert e["name"] == "do_%s_%d_1" % (r["name"], unit)
    assert (e["typeName"], e["deviceTypeName"]) == ("do", "FIO_8_8")
    assert e["safe"] == "stay"
    assert e["safeRaw"] == "stay"
    assert len(e["controlMatrix"]) == len(res["alarms"])
    assert all(cell["waarde"] == -1 for cell in e["controlMatrix"])
    assert e["alarmFunction"] == "AND"
    assert e["normalOpen"] is True


def test_add_into_zone(sample, tmp_path):
    data = dump(sample)
    r = ring(data)
    zone_id = data["zones"][0]["id"]
    unit = free_unit(data) + 2
    out = tmp_path / "add-zone.rbtproject"
    _, res = run_ops(sample, [{
        "op": "add", "ring_id": r["id"], "unit": unit, "address": 1,
        "type": "fire", "device_type": "FIRE", "unit_id": "010.000.002",
        "zones": [zone_id],
    }], out)

    added = res["elements"][-1]
    assert added["zones"] == [zone_id]
    zone = next(z for z in res["zones"] if z["id"] == zone_id)
    assert added["name"] in zone["elements"]
    # bestaande zones en elementen blijven bestaan
    assert len(res["zones"]) == len(data["zones"])


def test_add_with_unknown_zone_fails(sample, tmp_path):
    data = dump(sample)
    out = tmp_path / "bad-zone.rbtproject"
    with pytest.raises(RuntimeError) as excinfo:
        run_ops(sample, [{
            "op": "add", "ring_id": ring(data)["id"], "unit": 99, "address": 1,
            "type": "fire", "device_type": "FIRE", "unit_id": "x", "zones": [999],
        }], out)
    assert "onbekende zone" in str(excinfo.value)
    assert not out.exists()


# ----------------------------------------------------------------- delete

def test_delete_element_removes_from_zones_and_keeps_others(sample, tmp_path):
    data = dump(sample)
    r = ring(data)
    zone_id = data["zones"][0]["id"]
    step1 = tmp_path / "step1.rbtproject"
    _, added = run_ops(sample, [{
        "op": "add", "ring_id": r["id"], "unit": free_unit(data), "address": 1,
        "type": "fire", "device_type": "FIRE", "unit_id": "010.000.003",
        "zones": [zone_id],
    }], step1)
    victim = added["elements"][-1]

    step2 = tmp_path / "step2.rbtproject"
    _, res = run_ops(step1, [{"op": "delete", "id": victim["id"]}], step2)

    assert [e["name"] for e in res["elements"]] == [e["name"] for e in data["elements"]]
    for zone in res["zones"]:
        assert victim["name"] not in zone["elements"]
    # alle andere elementen houden hun velden
    keys = ("name", "ringId", "unit", "unitId", "address", "type", "deviceType",
            "indexInRing", "zones", "alarmFunction", "safe", "normalOpen", "description")
    assert [field_values(e, keys) for e in res["elements"]] == \
           [field_values(e, keys) for e in data["elements"]]


def test_delete_unknown_id_fails_without_output(sample, tmp_path):
    out = tmp_path / "bad-del.rbtproject"
    with pytest.raises(RuntimeError) as excinfo:
        run_ops(sample, [{"op": "delete", "id": 999999}], out)
    assert "onbekende element-id" in str(excinfo.value)
    assert not out.exists()


# ----------------------------------------------------------------- rename

def test_rename_by_id_keeps_other_fields(sample, tmp_path):
    data = dump(sample)
    target = data["elements"][0]
    out = tmp_path / "rename.rbtproject"
    _, res = run_ops(sample, [{"op": "rename", "id": target["id"], "name": "test_rename_1"}], out)

    renamed = res["elements"][0]
    assert renamed["name"] == "test_rename_1"
    keys = ("ringId", "unit", "unitId", "address", "type", "deviceType",
            "indexInRing", "zones", "alarmFunction", "safe", "normalOpen")
    assert field_values(renamed, keys) == field_values(target, keys)
    assert len(res["elements"]) == len(data["elements"])


# ------------------------------------------------------------------ order

def test_order_renumbers_indexes(sample, tmp_path):
    data = dump(sample)
    rid = ring(data)["id"]
    ids = [e["id"] for e in ring_elements(data)]
    assert len(ids) > 2
    wanted = list(reversed(ids))
    out = tmp_path / "order.rbtproject"
    _, res = run_ops(sample, [{"op": "order", "ring_id": rid, "ids": wanted}], out)

    by_id = {e["id"]: e for e in data["elements"]}
    assert [e["name"] for e in res["elements"]] == [by_id[i]["name"] for i in wanted]
    assert [e["id"] for e in res["elements"]] == list(range(len(res["elements"])))
    # indexInRing wordt per ring genummerd, niet over de hele lijst
    assert_indexes_per_ring(res)
    assert [e["indexInRing"] for e in res["elements"]] == list(range(1, len(ids) + 1))


def test_renumber_is_per_ring_with_two_rings(sample, tmp_path):
    """Meerringige casus: nieuw element op een nieuwe ring via @ringadd + veld-edit 'ring'."""
    data = dump(sample)
    rid = ring(data)["id"]
    moving = data["elements"][-1]
    out = tmp_path / "two-rings.rbtproject"
    apply_raw(sample, ["@ringadd\tRing2\t10.0.0.42",
                       "%s\tring\tRing2" % moving["name"]], out)
    res = dump(out)

    assert [r["name"] for r in res["rings"]] == [ring(data)["name"], "Ring2"]
    assert len(res["elements"]) == len(data["elements"])
    # per ring 1..n: ring 2 heeft één element met index 1, ring 1 loopt 1..n-1
    assert_indexes_per_ring(res)
    second = [e for e in res["elements"] if e["ringId"] != rid]
    assert [(e["name"], e["indexInRing"]) for e in second] == [(moving["name"], 1)]
    assert [e["indexInRing"] for e in res["elements"] if e["ringId"] == rid] == \
        list(range(1, len(data["elements"])))

    # @order binnen de eerste ring laat de nummering van de tweede ring ongemoeid
    first_ring = [e["id"] for e in res["elements"] if e["ringId"] == rid]
    ordered = tmp_path / "two-rings-ordered.rbtproject"
    apply_raw(out, ["@order\t%d\t%s" % (rid, ",".join(str(i) for i in reversed(first_ring)))],
              ordered)
    res2 = dump(ordered)
    assert_indexes_per_ring(res2)
    second2 = [e for e in res2["elements"] if e["ringId"] != rid]
    assert [(e["name"], e["indexInRing"]) for e in second2] == [(moving["name"], 1)]


def test_order_with_incomplete_list_fails(sample, tmp_path):
    data = dump(sample)
    ids = [e["id"] for e in ring_elements(data)]
    out = tmp_path / "bad-order.rbtproject"
    with pytest.raises(RuntimeError) as excinfo:
        run_ops(sample, [{"op": "order", "ring_id": ring(data)["id"], "ids": ids[:-1]}], out)
    assert "id-lijst dekt niet alle" in str(excinfo.value)


# -------------------------------------------------------------- zone delete

def test_zone_delete_removes_zone_and_membership(sample, tmp_path):
    data = dump(sample)
    r = ring(data)
    zone_id = data["zones"][-1]["id"]
    step1 = tmp_path / "z1.rbtproject"
    _, added = run_ops(sample, [{
        "op": "add", "ring_id": r["id"], "unit": free_unit(data), "address": 1,
        "type": "fire", "device_type": "FIRE", "unit_id": "010.000.004",
        "zones": [zone_id],
    }], step1)
    member = added["elements"][-1]["name"]

    step2 = tmp_path / "z2.rbtproject"
    _, res = run_ops(step1, [{"op": "zone_delete", "zone_id": zone_id}], step2)

    assert zone_id not in [z["id"] for z in res["zones"]]
    assert len(res["zones"]) == len(data["zones"]) - 1
    for zone in res["zones"]:
        assert member not in zone["elements"]
    elem = next(e for e in res["elements"] if e["name"] == member)
    assert zone_id not in elem["zones"]
    assert zone_id not in elem["openZones"]
    # element zelf blijft bestaan
    assert len(res["elements"]) == len(data["elements"]) + 1


# ------------------------------------------------------------------ service

def test_service_never_writes_source(sample, tmp_path):
    before = file_hash(sample)
    out = tmp_path / "copy.rbtproject"
    info = model_service.apply_operations(str(sample), [{"op": "rename", "id": 0,
                                                        "name": "test_service_1"}], str(out))
    assert info["source_unchanged"] is True
    assert file_hash(sample) == before
    assert out.exists() and out != sample
    # geen tijdelijke bestanden achtergebleven
    assert [p for p in os.listdir(tmp_path) if p.startswith(".zenix-")] == []


def test_service_rejects_symlink_to_source(sample, tmp_path):
    """Een out_path dat via een symlink naar de bron wijst mag de bron niet raken."""
    before = file_hash(sample)
    link = tmp_path / "link.rbtproject"
    os.symlink(str(sample), str(link))

    with pytest.raises(ValueError):
        model_service.apply_operations(
            str(sample), [{"op": "rename", "id": 0, "name": "x"}], str(link))

    assert file_hash(sample) == before
    # de symlink is niet vervangen en wijst nog steeds naar de bron
    assert os.path.islink(link) and os.path.samefile(link, sample)
    assert [p for p in os.listdir(tmp_path) if p.startswith(".zenix-")] == []
    assert sorted(os.listdir(tmp_path)) == sorted([sample.name, "link.rbtproject"])


def test_service_rejects_hardlink_to_source(sample):
    """Een hardlink naar de bron is hetzelfde bestand: weigeren, niets schrijven."""
    before = file_hash(sample)
    hard = sample.parent / "hardlink.rbtproject"
    os.link(str(sample), str(hard))

    with pytest.raises(ValueError):
        model_service.apply_operations(
            str(sample), [{"op": "rename", "id": 0, "name": "x"}], str(hard))

    assert file_hash(sample) == before
    assert os.path.samefile(hard, sample)


def test_service_requires_explicit_output_path(sample):
    before = file_hash(sample)
    siblings = sorted(os.listdir(sample.parent))
    for bad in (None, "", "   "):
        with pytest.raises(ValueError):
            model_service.apply_operations(str(sample), [], bad)
    # er is niets naast de bron geschreven en de bron is byte-identiek
    assert sorted(os.listdir(sample.parent)) == siblings
    assert file_hash(sample) == before


def test_service_rejects_tab_or_newline_in_text_fields(sample, tmp_path):
    data = dump(sample)
    r = ring(data)
    element = data["elements"][0]
    zone_id = data["zones"][0]["id"] if data["zones"] else 1
    base_add = {"op": "add", "ring_id": r["id"], "unit": free_unit(data),
                "address": 1, "type": "fire", "device_type": "FIRE",
                "unit_id": "010.000.001"}
    bad_ops = [
        dict(base_add, name="slecht\tnaam"),
        dict(base_add, name="slecht\nnaam"),
        dict(base_add, name="slecht\rnaam"),
        dict(base_add, unit_id="010\t000"),
        dict(base_add, zones=[zone_id, "2\t3"]),
        {"op": "rename", "id": element["id"], "name": "x\ty"},
        {"op": "rename", "id": element["id"], "name": "x\ny"},
    ]
    for index, op in enumerate(bad_ops):
        out = tmp_path / ("bad-%d.rbtproject" % index)
        with pytest.raises(ValueError):
            model_service.apply_operations(str(sample), [op], str(out))
        assert not out.exists(), op
    # geen enkele afgewezen operatie heeft het project aangetast
    assert dump(sample) == data


def test_noop_apply_keeps_model_identical(sample, tmp_path):
    data = dump(sample)
    out = tmp_path / "noop.rbtproject"
    _, res = run_ops(sample, [], out)
    assert res == data


# --------------------------------------------------------------- round-trip

def test_roundtrip_mutations(sample, tmp_path):
    data = dump(sample)
    r = ring(data)
    n = len(data["elements"])
    by_id = {e["id"]: e for e in data["elements"]}
    rename_id, delete_id = 0, 1
    fire_unit = free_unit(data)
    dio_unit = fire_unit + 1
    order_ids = [i for i in reversed(range(n)) if i != delete_id]

    ops = [
        {"op": "add", "ring_id": r["id"], "unit": fire_unit, "address": 1,
         "type": "fire", "device_type": "FIRE", "unit_id": "010.000.005",
         "zones": [data["zones"][0]["id"]]},
        {"op": "add", "ring_id": r["id"], "unit": dio_unit, "address": 1,
         "type": "di", "device_type": "DIN2", "unit_id": "003.003.003"},
        {"op": "rename", "id": rename_id, "name": "test_roundtrip_1"},
        {"op": "delete", "id": delete_id},
        {"op": "order", "ring_id": r["id"], "ids": order_ids},
    ]
    out = tmp_path / "roundtrip.rbtproject"
    _, res = run_ops(sample, ops, out)

    expected_names = ["test_roundtrip_1" if i == rename_id else by_id[i]["name"] for i in order_ids]
    expected_names.append("fire_%s_%d_1" % (r["name"], fire_unit))
    expected_names.append("di_%s_%02d_1" % (r["name"], dio_unit))
    # expliciet verwachte structuur na de mutaties (id, naam en indexInRing)
    expected = [{"id": pos, "name": name, "indexInRing": pos + 1}
                for pos, name in enumerate(expected_names)]

    def actual(data):
        return [{"id": e["id"], "name": e["name"], "indexInRing": e["indexInRing"]}
                for e in data["elements"]]

    assert actual(res) == expected
    assert len(res["elements"]) == n + 1
    assert [e["id"] for e in res["elements"]] == list(range(len(res["elements"])))
    assert by_id[delete_id]["name"] not in [e["name"] for e in res["elements"]]

    added_fire = res["elements"][-2]
    assert added_fire["zones"] == [data["zones"][0]["id"]]
    assert (added_fire["alarmFunction"], added_fire["normalOpen"]) == ("AND", True)
    assert added_fire["safe"] is None  # FIRE geeft safe niet vrij via getSafe()
    assert added_fire["safeRaw"] is None  # vendor bewaart 'safe' niet voor FIRE
    added_dio = res["elements"][-1]
    assert (added_dio["typeName"], added_dio["deviceTypeName"]) == ("di", "DIN2")

    # opnieuw openen levert exact de expliciet verwachte structuur
    assert actual(dump(out)) == expected


# --------------------------------------------------------------- CLI regressie

@pytest.mark.skipif(
    not os.path.exists(CLI),
    reason="de CLI (zenix_cli.py) hoort bij ZENiX Bridge, niet bij deze repo")
def test_cli_regression_to_xlsx_and_back(sample, tmp_path):
    data = dump(sample)
    xlsx = tmp_path / "sheet.xlsx"
    project = tmp_path / "from-xlsx.rbtproject"
    project_alias = tmp_path / "from-alias.rbtproject"
    env = dict(os.environ)

    r1 = subprocess.run([sys.executable, CLI, "to-xlsx", str(sample), str(xlsx)],
                        capture_output=True, text=True, env=env)
    assert r1.returncode == 0, r1.stderr
    assert xlsx.exists()

    # de gedocumenteerde naam uit AC-8 ...
    r2 = subprocess.run([sys.executable, CLI, "xlsx-to-project", str(xlsx), str(project)],
                        capture_output=True, text=True, env=env)
    assert r2.returncode == 0, r2.stderr
    assert project.exists()

    # ... en de bestaande naam blijven beide werken
    r3 = subprocess.run([sys.executable, CLI, "to-project", str(xlsx), str(project_alias)],
                        capture_output=True, text=True, env=env)
    assert r3.returncode == 0, r3.stderr
    assert project_alias.exists()

    res = dump(project)
    assert len(res["elements"]) == len(data["elements"])
    assert [e["name"] for e in res["elements"]] == [e["name"] for e in data["elements"]]
    assert [e["name"] for e in dump(project_alias)["elements"]] == [e["name"] for e in data["elements"]]


# ---------------------------------------------------- id-based update (@set)

def test_update_by_id_changes_only_requested_fields(sample, tmp_path):
    data = dump(sample)
    target = data["elements"][0]
    out = tmp_path / "update.rbtproject"
    _, res = run_ops(sample, [{"op": "update", "id": target["id"], "fields": {
        "unit": target["unit"] + 5,
        "address": target["address"] + 2,
        "addressOnUnit": target["address"] + 1,
        "unitId": "999.888.777",
        "description": "aangepast",
        "enabled": not target["enabled"],
        "invert": not target["invert"],
        "normalOpen": not target["normalOpen"],
    }}], out)

    changed = res["elements"][0]
    assert changed["unit"] == target["unit"] + 5
    assert changed["address"] == target["address"] + 2
    assert changed["addressOnUnit"] == target["address"] + 1
    assert changed["unitId"] == "999.888.777"
    assert changed["description"] == "aangepast"
    assert changed["enabled"] is (not target["enabled"])
    assert changed["invert"] is (not target["invert"])
    assert changed["normalOpen"] is (not target["normalOpen"])
    # naam en overige velden blijven staan
    keys = ("name", "ringId", "type", "deviceType", "safe", "alarmFunction", "zones")
    assert field_values(changed, keys) == field_values(target, keys)
    # de andere elementen zijn onaangeroerd
    assert [e["name"] for e in res["elements"]] == [e["name"] for e in data["elements"]]
    assert len(res["elements"]) == len(data["elements"])


def test_update_rename_and_zones_by_id(sample, tmp_path):
    """Update is naam-onafhankelijk: rename + zone-lidmaatschap in één operatie."""
    data = dump(sample)
    target = data["elements"][0]
    zone = data["zones"][0]
    new_name = "test_update_zones_1"
    out = tmp_path / "update-zones.rbtproject"
    _, res = run_ops(sample, [{"op": "update", "id": target["id"], "fields": {
        "name": new_name,
        "zones": [zone["id"]],
    }}], out)

    changed = next(e for e in res["elements"] if e["name"] == new_name)
    assert changed["zones"] == [zone["id"]]
    zone_after = next(z for z in res["zones"] if z["id"] == zone["id"])
    assert new_name in zone_after["elements"]
    assert target["name"] not in zone_after["elements"]
    # geen dubbel lidmaatschap in een zone waar het element al in zat
    for z in res["zones"]:
        assert z["elements"].count(new_name) <= 1


def test_update_type_and_safe_codes(sample, tmp_path):
    data = dump(sample)
    target = data["elements"][0]
    out = tmp_path / "update-type.rbtproject"
    _, res = run_ops(sample, [{"op": "update", "id": target["id"], "fields": {
        "type": "do", "deviceType": "FIO_8_8", "safe": "stay",
        "alarmFunction": "OR",
    }}], out)

    changed = res["elements"][0]
    assert (changed["type"], changed["typeName"]) == (4, "do")
    assert (changed["deviceType"], changed["deviceTypeName"]) == (3, "FIO_8_8")
    assert changed["safe"] == "stay"
    assert changed["safeRaw"] == "stay"
    assert changed["alarmFunction"] == "OR"


def test_update_rejects_unknown_field_and_bad_id(sample, tmp_path):
    data = dump(sample)
    target = data["elements"][0]
    for index, op in enumerate([
        {"op": "update", "id": target["id"], "fields": {"bestaatNiet": 1}},
        {"op": "update", "id": 999999, "fields": {"unit": 1}},
        {"op": "update", "id": target["id"], "fields": {}},
        {"op": "update", "id": target["id"], "fields": {"name": "slecht\tnaam"}},
        {"op": "update", "id": target["id"], "fields": {"name": "  "}},
        {"op": "update", "id": target["id"], "fields": {"unit": "geen-getal"}},
        {"op": "update", "id": target["id"], "fields": {"enabled": "misschien"}},
        {"op": "update", "id": target["id"], "fields": {"description": "x\ny"}},
    ]):
        out = tmp_path / ("bad-update-%d.rbtproject" % index)
        with pytest.raises((ValueError, RuntimeError)):
            model_service.apply_operations(str(sample), [op], str(out))
        assert not out.exists(), op
    assert dump(sample) == data


# -------------------------------------------------------- zone add / update

def test_zone_add_creates_zone(sample, tmp_path):
    data = dump(sample)
    out = tmp_path / "zone-add.rbtproject"
    _, res = run_ops(sample, [{
        "op": "zone_add", "name": "Testzone", "description": "nieuwe zone"}], out)

    assert len(res["zones"]) == len(data["zones"]) + 1
    zone = next(z for z in res["zones"] if z["name"] == "Testzone")
    assert zone["description"] == "nieuwe zone"
    assert zone["id"] == max(z["id"] for z in data["zones"]) + 1
    assert zone["elements"] == []
    # elementen blijven ongemoeid
    assert [e["name"] for e in res["elements"]] == [e["name"] for e in data["elements"]]


def test_zone_update_renames_zone(sample, tmp_path):
    data = dump(sample)
    zone = data["zones"][0]
    out = tmp_path / "zone-update.rbtproject"
    _, res = run_ops(sample, [{
        "op": "zone_update", "zone_id": zone["id"],
        "name": "Aangepaste zone", "description": "aangepast"}], out)

    changed = next(z for z in res["zones"] if z["id"] == zone["id"])
    assert changed["name"] == "Aangepaste zone"
    assert changed["description"] == "aangepast"
    assert changed["elements"] == zone["elements"]
    assert len(res["zones"]) == len(data["zones"])


def test_zone_ops_reject_bad_input(sample, tmp_path):
    zone = dump(sample)["zones"][0]
    for index, op in enumerate([
        {"op": "zone_add", "name": ""},
        {"op": "zone_add", "name": "x\ty"},
        {"op": "zone_update", "zone_id": zone["id"], "name": "x\ty"},
        {"op": "zone_update", "zone_id": zone["id"], "name": ""},
    ]):
        out = tmp_path / ("bad-zone-op-%d.rbtproject" % index)
        with pytest.raises((ValueError, RuntimeError)):
            model_service.apply_operations(str(sample), [op], str(out))
        assert not out.exists(), op


# ------------------------------------------------------- ring add / update

def test_ringset_rename_and_host(sample, tmp_path):
    data = dump(sample)
    r = ring(data)
    out = tmp_path / "ringset.rbtproject"
    apply_raw(sample, ["@ringset\t%d\tname\tRing A" % r["id"],
                       "@ringset\t%d\thost\t10.0.0.9" % r["id"]], out)
    res = dump(out)

    changed = next(x for x in res["rings"] if x["id"] == r["id"])
    assert changed["name"] == "Ring A"
    assert changed["host"] == "10.0.0.9"
    # elementen blijven staan en hun ringnaam-veld volgt de ring
    assert [e["name"] for e in res["elements"]] == [e["name"] for e in data["elements"]]
    assert all(e["ring"] == "Ring A" for e in res["elements"])


def test_ringset_unknown_ring_id(sample, tmp_path):
    out = tmp_path / "bad-ringset-id.rbtproject"
    with pytest.raises(RuntimeError) as excinfo:
        apply_raw(sample, ["@ringset\t999999\tname\tX"], out)
    assert "onbekende ring-id" in str(excinfo.value)


def test_ringset_unknown_field(sample, tmp_path):
    r = ring(dump(sample))
    out = tmp_path / "bad-ringset-field.rbtproject"
    with pytest.raises(RuntimeError) as excinfo:
        apply_raw(sample, ["@ringset\t%d\tcpuType\t9" % r["id"]], out)
    assert "onbekend veld" in str(excinfo.value)


def test_ringset_rejects_empty_and_duplicate_name(sample, tmp_path):
    data = dump(sample)
    r = ring(data)
    out = tmp_path / "ringadd-dup.rbtproject"
    apply_raw(sample, ["@ringadd\tRing2\t10.0.0.42"], out)
    for index, edits in enumerate([
        ["@ringset\t%d\tname\t " % r["id"]],
        ["@ringset\t%d\tname\tRing2" % r["id"]],
        ["@ringset\t%d\thost\t " % r["id"]],
    ]):
        bad = tmp_path / ("bad-ringset-%d.rbtproject" % index)
        with pytest.raises(RuntimeError):
            apply_raw(out, edits, bad)


def test_ringadd_sets_vendor_defaults(sample, tmp_path):
    data = dump(sample)
    base = ring(data)
    out = tmp_path / "ringadd-defaults.rbtproject"
    apply_raw(sample, ["@ringadd\tRing2\t10.0.0.42"], out)
    res = dump(out)

    new = next(x for x in res["rings"] if x["name"] == "Ring2")
    assert new["id"] == max(x["id"] for x in data["rings"]) + 1
    assert new["cpuType"] == 5
    assert new["bacnetInstanceId"] == base["bacnetInstanceId"] + 1000
    assert new["bacnetNetwork"] == base["bacnetNetwork"] + 1


def test_ring_ops_via_service(sample, tmp_path):
    data = dump(sample)
    r = ring(data)
    out = tmp_path / "ring-ops.rbtproject"
    _, res = run_ops(sample, [
        {"op": "ring_add", "name": "Ring2", "host": "10.0.0.42"},
        {"op": "ring_update", "ring_id": r["id"],
         "fields": {"name": "Ring A", "host": "10.0.0.9"}},
    ], out)

    changed = next(x for x in res["rings"] if x["id"] == r["id"])
    assert (changed["name"], changed["host"]) == ("Ring A", "10.0.0.9")
    new = next(x for x in res["rings"] if x["name"] == "Ring2")
    assert new["host"] == "10.0.0.42"
    assert new["cpuType"] == 5


def test_ring_ops_reject_bad_input(sample, tmp_path):
    r = ring(dump(sample))
    for index, op in enumerate([
        {"op": "ring_add", "name": ""},
        {"op": "ring_add", "name": "x\ty"},
        {"op": "ring_update", "ring_id": r["id"], "fields": {"naam": "x"}},
        {"op": "ring_update", "ring_id": r["id"], "fields": {}},
        {"op": "ring_update", "ring_id": r["id"], "fields": {"name": "x\ny"}},
        {"op": "ring_update", "ring_id": r["id"], "fields": {"host": " "}},
    ]):
        out = tmp_path / ("bad-ring-op-%d.rbtproject" % index)
        with pytest.raises((ValueError, RuntimeError)):
            model_service.apply_operations(str(sample), [op], str(out))
        assert not out.exists(), op


def test_ring_update_rejects_empty_host(sample):
    r = ring(dump(sample))
    op = {"op": "ring_update", "ring_id": r["id"], "fields": {"host": ""}}
    with pytest.raises(ValueError) as excinfo:
        model_service.operations_to_edits([op])
    assert model_service.EMPTY_HOST_MESSAGE in str(excinfo.value)


@pytest.mark.parametrize("case", ["same", "upper", "duplicate"])
def test_ring_add_rejects_existing_or_duplicate_name(sample, tmp_path, case):
    data = dump(sample)
    base_name = ring(data)["name"]
    if case == "same":
        ops = [{"op": "ring_add", "name": base_name, "host": "10.0.0.1"}]
    elif case == "upper":
        ops = [{"op": "ring_add", "name": base_name.upper(), "host": "10.0.0.1"}]
    else:
        ops = [{"op": "ring_add", "name": "Ring2", "host": "10.0.0.1"},
               {"op": "ring_add", "name": "ring2", "host": "10.0.0.2"}]
    out = tmp_path / ("dup-ring-add-%s.rbtproject" % case)
    with pytest.raises(ValueError) as excinfo:
        model_service.apply_operations(str(sample), ops, str(out))
    assert "ring" in str(excinfo.value).lower()
    assert not out.exists()