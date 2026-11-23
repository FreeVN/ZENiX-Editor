"""Vendor-jar-resolutie: RingBus Tool-installatie eerst, app/lib als ontwikkelroute."""
import os

import pytest

import core


def _make_install(root, jar_name="configuration-9.9.9.jar"):
    lib = root / "ringbustool" / "modules" / "lib"
    lib.mkdir(parents=True)
    jar = lib / jar_name
    jar.write_bytes(b"")
    jaxb = lib / "jaxb-api.jar"
    jaxb.write_bytes(b"")
    return jar, jaxb


def test_vendor_jar_uit_ringbustool_home(tmp_path, monkeypatch):
    """RINGBUSTOOL_HOME wint van de app/lib-map in de repo (ontwikkelroute)."""
    jar, jaxb = _make_install(tmp_path)
    monkeypatch.setenv("RINGBUSTOOL_HOME", str(tmp_path))

    found = core.jars()

    assert found[0] == str(jar)
    assert found[1] == str(jaxb)


def test_vendor_jar_gesorteerd_en_deterministisch(tmp_path, monkeypatch):
    """Meerdere configuration-*.jar: de gesorteerde eerste wint."""
    lib = tmp_path / "ringbustool" / "modules" / "lib"
    lib.mkdir(parents=True)
    (lib / "configuration-2.0.0.jar").write_bytes(b"")
    first = lib / "configuration-1.4.1.jar"
    first.write_bytes(b"")
    monkeypatch.setenv("RINGBUSTOOL_HOME", str(tmp_path))

    assert core.vendor_jar() == str(first)


def test_zonder_vendor_jar_expliciete_fout(tmp_path, monkeypatch):
    """Geen installatie en geen app/lib -> RuntimeError met beide termen."""
    monkeypatch.setattr(core, "_module_dirs", lambda: [])
    monkeypatch.setattr(core, "APP_LIB", str(tmp_path / "leeg"))

    with pytest.raises(RuntimeError) as excinfo:
        core.jars()

    msg = str(excinfo.value)
    assert "RingBus Tool" in msg
    assert "RINGBUSTOOL_HOME" in msg


def test_ontwikkelroute_zonder_installatie(tmp_path, monkeypatch):
    """Zonder RingBus-installatie blijft app/lib werken (dev en tests).

    De publieke repo bevat geen vendor-jars (auteursrecht), dus de test zet
    zelf lege placeholders in een tijdelijke app/lib.
    """
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "configuration-1.4.1.jar").write_bytes(b"")
    (lib / "jaxb-api.jar").write_bytes(b"")
    monkeypatch.setattr(core, "_module_dirs", lambda: [])
    monkeypatch.setattr(core, "APP_LIB", str(lib))

    found = core.jars()

    assert [os.path.basename(p) for p in found] == [
        "configuration-1.4.1.jar", "jaxb-api.jar"]
    assert all(os.path.exists(p) for p in found)
    assert os.path.dirname(found[0]) == os.path.dirname(found[1])

