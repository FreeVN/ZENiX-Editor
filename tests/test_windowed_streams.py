"""Regressietest voor PyInstaller ``--windowed``: stdout/stderr zijn dan ``None``.

De test draait offline, zonder subprocess en zonder netwerk. De originelen worden
altijd in een ``finally`` hersteld, zodat pytest-capture niet beschadigd raakt.
"""
import logging
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (os.path.join(ROOT, "app"), os.path.join(ROOT, "app", "web")):
    if path not in sys.path:
        sys.path.insert(0, path)

import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def prepared_environment():
    """Deze module heeft geen projectsleutel of Java-helper nodig."""
    return None


@pytest.fixture
def windowed(monkeypatch, tmp_path):
    """Isoleer het logbestand in ``tmp_path`` en herstel de streams achteraf."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    stdout, stderr = sys.stdout, sys.stderr
    started = len(server._FALLBACK_STREAMS)
    try:
        yield tmp_path
    finally:
        sys.stdout, sys.stderr = stdout, stderr
        for handle in server._FALLBACK_STREAMS[started:]:
            handle.close()
        del server._FALLBACK_STREAMS[started:]


def test_none_streams_get_valid_fallback(windowed):
    sys.stdout = None
    sys.stderr = None

    replaced = server.ensure_std_streams()

    assert set(replaced) == {"stdout", "stderr"}
    for stream in (sys.stdout, sys.stderr):
        assert stream is not None
        assert isinstance(stream.isatty(), bool)

    print("regressie-regel naar het logbestand")
    sys.stdout.flush()

    log = windowed / "ZENiXEditor" / "editor.log"
    assert log.is_file()
    assert "regressie-regel naar het logbestand" in log.read_text(encoding="utf-8")


def test_second_call_does_not_replace_again(windowed):
    sys.stdout = None
    sys.stderr = None
    server.ensure_std_streams()
    out, err = sys.stdout, sys.stderr

    assert server.ensure_std_streams() == []
    assert sys.stdout is out
    assert sys.stderr is err


def test_existing_streams_are_untouched(windowed):
    marker_out, marker_err = object(), object()
    sys.stdout, sys.stderr = marker_out, marker_err

    assert server.ensure_std_streams() == []
    assert sys.stdout is marker_out
    assert sys.stderr is marker_err


def test_log_config_avoids_isatty_and_keeps_info(windowed):
    pytest.importorskip("uvicorn")

    config = server.build_log_config()

    assert config["loggers"]["uvicorn"]["level"] == "INFO"
    for name in ("default", "access"):
        fmt = config["formatters"][name]
        assert fmt["()"] == "logging.Formatter"
        assert "DefaultFormatter" not in str(fmt)
    for handler in config["handlers"].values():
        if "stream" in handler:
            assert handler["stream"] == "ext://sys.stderr"

    # Formatteren mag niet van sys.stdout afhangen (die is hier None).
    formatter = logging.Formatter(config["formatters"]["default"]["fmt"])
    record = logging.LogRecord("uvicorn", logging.INFO, __file__, 1, "test", None, None)
    assert "INFO" in formatter.format(record)
