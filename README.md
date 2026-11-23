# ZENiX Ringbus Editor — handleiding

De handleiding van **ZENiX Ringbus Editor**: een offline web-UI om
`.rbtproject`-bestanden rechtstreeks in de browser te bewerken — elementen,
zones, ringen, alarmen en de controlematrix.

**Lezen kan hier: <https://freevn.github.io/ZENiX-Editor/>**

## Lokaal bekijken

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-docs.txt
.venv/bin/mkdocs serve
```

## Wat staat waar

| | |
|---|---|
| **ZENiX Ringbus Editor** (dit) | web-UI, bewerken in de browser |
| **ZENiX Bridge** | `.rbtproject` ⇄ Excel, met [eigen handleiding](https://freevn.github.io/ZENiX-Bridge/) |

Deze repo bevat **enkel documentatie**. De code van beide tools staat in de
privé-repo [FreeVN/zenix-ringbus-tool](https://github.com/FreeVN/zenix-ringbus-tool);
daar staan ook de releases (`editor-v*` voor de editor, `bridge-v*` voor de Bridge).

> **Verwar de namen niet.** De Bridge converteert naar Excel en heeft
> `ZENiXBridge.exe` / `ZENiXBridge-linux` / een Docker-image. De Ringbus Editor
> is een Python-webservice en heeft geen binary — je start hem met `python3
> app/web/server.py`.
