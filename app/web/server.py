"""Offline FastAPI-server voor de ZENiX Ringbus Editor.

Start met::

    python3 app/web/server.py --port 8800

De server luistert standaard alleen op localhost, doet geen externe requests en
serveert ``app/web/static/`` (geen CDN, geen build-stap).

Endpoints
---------
* ``GET /``                          -> de editor-UI (index.html)
* ``POST /api/projects/open``        -> upload (multipart of ruwe body) of JSON ``{"path": ...}``
* ``POST /api/projects/{sid}/save``  -> volledige gewenste staat opslaan
* ``GET /api/projects/{sid}/download`` -> het geschreven project downloaden
* ``DELETE /api/projects/{sid}``     -> sessie sluiten en tijdelijke map opruimen
"""
import argparse
import copy
import logging
import os
import sys
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
ROOT = os.path.dirname(APP)
for path in (APP, HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

from fastapi import Body, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

import core  # noqa: E402
import editor  # noqa: E402

app = FastAPI(title="ZENiX Ringbus Editor", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=editor.STATIC), name="static")

INDEX = os.path.join(editor.STATIC, "index.html")

# Versie van de applicatie; blijft gelijk aan de release-tag (v1.1.2) en de docs.
VERSION = "1.1.2"

# PyInstaller ``--windowed`` levert geen console: ``sys.stdout``/``sys.stderr``
# zijn dan ``None`` en elke ``print`` of uvicorn-log zou crashen. De handles
# hieronder blijven voor de levensduur van het proces open (bewust geen
# sluiten, geen rotatie: buiten scope).
LOG_DIR_NAME = "ZENiXEditor"
LOG_FILE_NAME = "editor.log"
_FALLBACK_STREAMS = []


def log_file_path():
    """Geef een beschrijfbaar logbestand terug, met fallbacks per platform.

    Volgorde: ``%LOCALAPPDATA%\\ZENiXEditor\\editor.log``, dan
    ``~/.ZENiXEditor/editor.log`` en ten slotte ``os.devnull``.
    """
    candidates = []
    localappdata = os.environ.get("LOCALAPPDATA", "").strip()
    if localappdata:
        candidates.append(os.path.join(localappdata, LOG_DIR_NAME))
    home = os.path.expanduser("~")
    if home and home != "~":
        candidates.append(os.path.join(home, "." + LOG_DIR_NAME))
    for directory in candidates:
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError:
            continue
        path = os.path.join(directory, LOG_FILE_NAME)
        try:
            with open(path, "a", encoding="utf-8"):
                pass
        except OSError:
            continue
        return path
    return os.devnull


def _open_log_stream():
    """Open een append-stream naar het logbestand (of ``os.devnull``)."""
    for path in (log_file_path(), os.devnull):
        try:
            return open(path, "a", buffering=1, encoding="utf-8", errors="replace")
        except OSError:
            continue
    return None


def ensure_std_streams():
    """Vervang ``None``-streams door een werkende log-stream (idempotent).

    Retourneert de namen van de streams die in deze aanroep vervangen zijn.
    Bestaande streams blijven ongemoeid en een tweede aanroep doet niets.
    Ontbreken zowel ``stdout`` als ``stderr``, dan delen ze één handle naar
    hetzelfde logbestand (geen twee appenders op hetzelfde bestand).
    """
    replaced = []
    missing = [name for name in ("stdout", "stderr")
               if getattr(sys, name, None) is None]
    if not missing:
        return replaced
    handle = _open_log_stream()
    if handle is None:
        return replaced
    _FALLBACK_STREAMS.append(handle)
    for name in missing:
        setattr(sys, name, handle)
        replaced.append(name)
    return replaced


def build_log_config():
    """uvicorn-logconfig zonder ``DefaultFormatter``/``isatty()``-afhankelijkheid.

    ``uvicorn.config.LOGGING_CONFIG`` gebruikt ``uvicorn.logging.DefaultFormatter``
    (die ``sys.stdout.isatty()`` aanroept) en streams die in windowed mode
    ontbreken. We deepcopy'en de config, vervangen de formatters door een gewone
    ``logging.Formatter`` en richten alle handlers op de gegarandeerde
    ``sys.stderr``; het info-niveau blijft behouden.
    """
    import uvicorn

    config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    formatters = config.setdefault("formatters", {})
    formatters["default"] = {
        "()": "logging.Formatter",
        "fmt": "%(levelname)s:     %(message)s",
    }
    # Alleen ``%(message)s``: uvicorn's access-record bevat de regel al als
    # geformatteerde message. Access-specifieke velden (``client_addr``,
    # ``request_line``, ``status_code``) bestaan alleen na
    # ``uvicorn.logging.AccessFormatter.formatMessage``; een gewone Formatter
    # zou daarop met een KeyError ("--- Logging error ---") stuklopen.
    formatters["access"] = {
        "()": "logging.Formatter",
        "fmt": "%(levelname)s:     %(message)s",
    }
    for handler in config.get("handlers", {}).values():
        if "stream" in handler:
            handler["stream"] = "ext://sys.stderr"
    return config


@app.get("/")
def index():
    return FileResponse(INDEX, media_type="text/html")


@app.post("/api/projects/open")
async def open_project(request: Request):
    ctype = (request.headers.get("content-type") or "").lower()
    try:
        if ctype.startswith("application/json"):
            payload = await request.json()
            path = payload.get("path") if isinstance(payload, dict) else None
            session = editor.open_path(path)
        elif ctype.startswith("multipart/"):
            try:
                form = await request.form()
            except Exception as exc:
                raise editor.EditorError(
                    "Bestandsupload vereist de 'python-multipart'-dependency "
                    "(zie app/web/requirements.txt): %s" % exc)
            upload = form.get("file")
            if upload is None or not hasattr(upload, "read"):
                raise editor.EditorError("Geen bestand ontvangen (veld 'file')")
            data = await upload.read()
            session = editor.open_bytes(getattr(upload, "filename", None), data)
        else:
            filename = request.headers.get("x-filename") or "project.rbtproject"
            data = await request.body()
            if not data:
                raise editor.EditorError("Geen bestand ontvangen; stuur een .rbtproject")
            session = editor.open_bytes(filename, data)
    except editor.EditorError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return editor.open_response(session)


@app.post("/api/projects/{sid}/save")
async def save_project(sid: str, payload: dict = Body(...)):
    state = payload.get("state") if isinstance(payload.get("state"), dict) else payload
    try:
        return editor.save(sid, state)
    except KeyError:
        raise HTTPException(status_code=404, detail="Onbekende of verlopen sessie")
    except editor.NameValidationError as exc:
        raise HTTPException(status_code=400, detail={
            "error": "invalid_names",
            "violations": exc.violations,
        })
    except (editor.EditorError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail="Opslaan mislukt: %s" % exc)


@app.get("/api/projects/{sid}/download")
def download_project(sid: str):
    try:
        path, name = editor.download_info(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Onbekende of verlopen sessie")
    except editor.EditorError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    fallback = name.encode("ascii", "ignore").decode("ascii").strip() or "aangepast.rbtproject"
    fallback = fallback.replace('"', "_").replace("\\", "_")
    disposition = ("attachment; filename=\"%s\"; filename*=UTF-8''%s"
                   % (fallback, quote(name, safe="")))
    return FileResponse(path, media_type="application/octet-stream",
                        headers={"Content-Disposition": disposition})


@app.delete("/api/projects/{sid}")
def close_project(sid: str):
    try:
        closed = editor.close(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Onbekende of verlopen sessie")
    if not closed:
        raise HTTPException(status_code=404, detail="Onbekende of verlopen sessie")
    return {"closed": True}


def selftest():
    """Controleer de omgeving zonder de server te starten (voor CI)."""
    import json
    report = {
        "version": VERSION,
        "static": os.path.isfile(INDEX),
        "java": None,
        "jars": [],
        "java_check": None,
    }
    try:
        report["java"] = core.java_exe()
    except Exception as exc:  # noqa: BLE001 - rapport, geen crash
        report["java"] = "ontbreekt: %s" % exc
    try:
        report["jars"] = [[os.path.basename(p), os.path.isfile(p)] for p in core.jars()]
    except Exception as exc:  # noqa: BLE001
        report["jars"] = "ontbreekt: %s" % exc
    try:
        report["java_check"] = list(core.java_check())
    except Exception as exc:  # noqa: BLE001
        report["java_check"] = [False, str(exc)]
    print(json.dumps(report))
    ok = report["static"] and bool(report["java_check"] and report["java_check"][0])
    return 0 if ok else 1


def main(argv=None):
    # Eerste statement: in PyInstaller --windowed zijn stdout/stderr None.
    ensure_std_streams()
    parser = argparse.ArgumentParser(description="ZENiX Ringbus Editor (offline web-UI)")
    parser.add_argument("--port", type=int, default=8800, help="poort (standaard 8800)")
    parser.add_argument("--host", default="127.0.0.1", help="bind-adres (standaard localhost)")
    parser.add_argument("--no-browser", action="store_true",
                        help="open de browser niet automatisch")
    parser.add_argument("--selftest", action="store_true",
                        help="controleer de omgeving en stop")
    args = parser.parse_args(argv)
    if args.selftest:
        raise SystemExit(selftest())
    try:
        import uvicorn
    except ImportError:
        raise SystemExit(
            "uvicorn ontbreekt; installeer app/web/requirements.txt "
            "(bijvoorbeeld: python3 -m pip install -r app/web/requirements.txt)")
    if not args.no_browser:
        import threading
        import webbrowser
        url = "http://%s:%d/" % ("127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host,
                                 args.port)
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
        print("Editor: %s  (Ctrl+C om te stoppen)" % url)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info",
                log_config=build_log_config())


if __name__ == "__main__":
    main()
