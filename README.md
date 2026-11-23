# ZENiX Ringbus Editor

Offline web-UI om een ZENiX-projectbestand (`.rbtproject`, Rf-Technologies
brandkleppen) rechtstreeks in de browser te bewerken: elementen, zones, ringen,
alarmen en de controlematrix.

**Handleiding: <https://freevn.github.io/ZENiX-Editor/>** ·
**Download: [releases](https://github.com/FreeVN/ZENiX-Editor/releases)** (`ZENiXEditor.exe`)

Deze repo is **zelfstandig**: bron, handleiding, CI en releases staan hier samen.

> **Ander product:** **ZENiX Bridge** (`.rbtproject` ⇄ Excel) woont in
> <https://github.com/FreeVN/ZENiX-Bridge> met een eigen exe (`ZENiXBridge.exe`).
> Niets daarvan hoort in deze repo.

## Wat zit waar

| Pad | Inhoud |
|---|---|
| `app/web/server.py` | FastAPI-server: openen, opslaan, downloaden |
| `app/web/editor.py` | sessiebeheer en de twee-pass save |
| `app/web/static/` | de UI (HTML, CSS, JS — geen CDN, geen build-stap) |
| `app/model_service.py` | model-operaties (ringen, zones, alarmen, matrix) |
| `app/name_validation.py` | vendor-naamregels |
| `app/core.py` | container-crypto (AES-256-GCM) en vendor-jar-resolutie |
| `app/java/`, `app/build/` | Java-helper (Java 17) voor het vendor-formaat |
| `docs/` | de handleiding (MkDocs Material) |
| `tests/` | pytest-suite |

## Zelf draaien

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
ZENIX_KEY=<64 hex> .venv/bin/python app/web/server.py --port 8800
```

Open <http://localhost:8800>. De vendor-bibliotheek (`configuration-*.jar`,
`jaxb-api.jar`) zit **niet** in deze repo: die komt uit je RingBus
Tool-installatie (of `RINGBUSTOOL_HOME`).

## Release bouwen

Tag `v*` (bv. `v1.1.1`) → `.github/workflows/build.yml` bouwt `ZENiXEditor.exe` op
een Windows-runner en zet hem als asset op de release.

## Licentie

MIT — zie [LICENSE](LICENSE).
